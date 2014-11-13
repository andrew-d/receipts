import os
import hashlib
import datetime
#import mimetypes

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for
)
from werkzeug import secure_filename
from sqlalchemy.sql import func

from . import app, db
from . import models as m
from . import forms as f
from . import scanner


def read_in_chunks(infile, chunk_size=1*1024*1024):
    while True:
        chunk = infile.read(chunk_size)
        if chunk:
            yield chunk

        else:
            # The chunk was empty, which means we're at the end
            # of the file
            return


def get_page():
    """
    Helper function to get the current page # from a request.
    """
    try:
        return int(request.args.get('page') or 1)
    except ValueError:
        abort(400)


def fill_scan_form(scan_form):
    # Fill in the choices for scanner names
    scan_form.scanner_name.choices = [
        (d.name, d.vendor + ' - ' + d.model)
        for d in app.config['scanners'].scanner_info
    ]


@app.route("/")
@app.route("/index")
def index():
    return render_template('index.html',)


@app.errorhandler(400)
def bad_request(error):
    return render_template('error.html', error=error), 400


@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', error=error), 404


@app.errorhandler(500)
def internal_server_error(error):
    return render_template('error.html', error=error), 500


@app.route("/stats")
def stats():
    size_query = db.session.query(func.sum(m.File.size).label("total_size"))
    args = {
        'num_documents': m.Document.query.count(),
        'num_files':     m.File.query.count(),
        'total_size':    size_query.first().total_size,
        'num_tags':      m.Tag.query.count(),
        'scanners':      app.config['scanners'].scanner_info,
    }

    return render_template('stats.html', **args)


def handle_uploaded_file(f):
    """
    Handle an uploaded file.  Returns (file, exists), where 'file' is the new
    File object, and 'exists' indicates whether or not it already existed.
    'file' will be None on error.
    """
    # Hash the file to get the filename we're using
    fhash = hashlib.sha256()
    fsize = 0
    try:
        for chunk in read_in_chunks(f):
            fhash.update(chunk)
            fsize += len(chunk)
    finally:
        f.seek(0)

    app.logger.info("Got uploaded file '%s' with hash: %s",
                    f.filename, fhash.hexdigest())

    # Generate needed filenames
    sfname = secure_filename(f.filename)
    _, ext = os.path.splitext(sfname)
    fname = fhash.hexdigest() + ext

    # Check if this file exists already.
    existing = m.File.query.filter_by(name=fname).first()
    if existing is not None:
        return existing, True

    # Save the file in our file storage, create database object
    f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
    newfile = m.File(name=fname, size=fsize)

    # All set - commit everything
    db.session.commit()
    return newfile, False


def scan_file(scanner_name):
    """
    As per handle_uploaded_file, except that we retrieve an image
    from an attached scanner.
    """
    data, fhash, fsize = scanner.scan_image(scanner_name)
    fname = fhash + '.png'

    # Check if this document exists already.
    existing = m.File.query.filter_by(name=fname).first()
    if existing is not None:
        return existing, True

    # Save the file in our file storage, create database object
    with open(os.path.join(app.config['UPLOAD_FOLDER'], fname), 'wb') as f:
        f.write(data)

    newfile = m.File(name=fname, size=fsize)

    # All set - commit everything
    db.session.commit()
    return newfile, False


@app.route("/documents")
def documents():
    upload_form = f.UploadDocumentForm()
    scan_form = f.ScanDocumentForm()
    fill_scan_form(scan_form)

    page = get_page()
    documents = (m.Document.query.
                    order_by(m.Document.created).
                    paginate(page, error_out=False)
                 )

    return render_template('documents.html',
                           documents=documents,
                           upload_form=upload_form,
                           scan_form=scan_form,
                           have_scanner=app.config['scanners'].have_scanner)


@app.route("/documents/upload", methods=['POST'])
def documents_upload():
    upload_form = f.UploadDocumentForm()

    if upload_form.validate_on_submit():
        nfile, exists = handle_uploaded_file(upload_form.file.data)
        if exists is True:
            flash('This file already exists', 'warning')
            return redirect(url_for('documents'))
            # TODO: make this work
            #return redirect(url_for('single_document', id=doc.id))

        if nfile is None:
            flash('Upload was not allowed', 'error')
            return redirect(url_for('documents'))

        # Create a new document with this file instance
        doc = m.Document(name=upload_form.name.data)
        nfile.document = doc

        # Apply tags
        doc.apply_tags(upload_form.tags.data)

        # Add a tag for the current year
        now = datetime.datetime.utcnow().year
        year_tag = m.Tag.get_or_create('year:' + str(now))
        if year_tag not in doc.tags:
            doc.tags.append(year_tag)

        # Add it all and commit
        db.session.add(nfile)
        db.session.add(doc)
        db.session.commit()

        flash('Uploaded new document', 'success')
        return redirect(url_for('single_document', id=doc.id))

    # TODO
    abort(501)


@app.route("/documents/scan", methods=['POST'])
def documents_scan():
    scan_form = f.ScanDocumentForm()
    fill_scan_form(scan_form)

    if scan_form.validate_on_submit():
        scanner_name = scan_form.scanner_name.data
        app.logger.info("Scanning document with scanner %s", scanner_name)

        nfile, exists = scan_file(scan_form.scanner_name.data)
        if exists is True:
            flash('This file already exists', 'warning')
            return redirect(url_for('documents'))
            # TODO: make this work
            #return redirect(url_for('single_document', id=doc.id))

        if nfile is None:
            flash('Could not scan the document', 'error')
            return redirect(url_for('documents'))

        # TODO: merge with the uploading, above

        # Create a new document with this file instance
        doc = m.Document(name=scan_form.name.data)
        nfile.document = doc

        # Apply tags
        doc.apply_tags(scan_form.tags.data)

        # Add a tag for the current year
        now = datetime.datetime.utcnow().year
        year_tag = m.Tag.get_or_create('year:' + str(now))
        if year_tag not in doc.tags:
            doc.tags.append(year_tag)

        # Add it all and commit
        db.session.add(nfile)
        db.session.add(doc)
        db.session.commit()

        flash('Scanned new document', 'success')
        return redirect(url_for('single_document', id=doc.id))

    abort(501)


@app.route("/documents/<int:id>", methods=['GET', 'POST'])
def single_document(id):
    doc = m.Document.query.get_or_404(id)

    try:
        curr_file = int(request.args.get('curr_file') or 1)
    except (IndexError, ValueError):
        abort(400)

    document_files = (doc.files.order_by(m.File.id).
                        paginate(curr_file, per_page=1))

    add_tags_form = f.AddTagsForm()
    upload_form = f.UploadFileForm()
    scan_form = f.ScanFileForm()
    fill_scan_form(scan_form)

    return render_template('single_document.html',
                           document=doc,
                           document_files=document_files,
                           curr_file=curr_file,
                           add_tags_form=add_tags_form,
                           upload_form=upload_form,
                           scan_form=scan_form,
                           have_scanner=app.config['scanners'].have_scanner)


@app.route("/documents/<int:id>/tags", methods=['POST'])
def single_document_tags(id):
    abort(501)


@app.route("/documents/<int:id>/files", methods=['POST'])
def single_document_files(id):
    abort(501)


@app.route("/documents/<int:id>/scan", methods=['POST'])
def single_document_scan(id):
    abort(501)


@app.route("/files/<int:id>/content")
def file_data(id):
    f = m.File.query.get_or_404(id)
    return send_from_directory(app.config['UPLOAD_FOLDER'], f.name)


@app.route("/tags")
def tags():
    page = get_page()
    tags = (m.Tag.query.
            order_by(m.Tag.name).
            paginate(page, error_out=False)
           )
    return render_template('tags.html',
                           tags=tags)


@app.route("/tags/<int:id>")
def single_tag(id):
    page = get_page()
    tag = m.Tag.query.get_or_404(id)
    tag_documents = (tag.documents.
                     order_by(m.Document.id).
                     paginate(page, error_out=False)
                    )
    return render_template('single_tag.html',
                           tag=tag,
                           tag_documents=tag_documents)