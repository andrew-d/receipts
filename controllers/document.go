package controllers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/lann/squirrel"
	"github.com/zenazn/goji/web"

	"github.com/andrew-d/docstore/models"
)

type DocumentController struct {
	AppController
}

func (c *DocumentController) GetAll(ctx web.C, w http.ResponseWriter, r *http.Request) error {
	allDocuments := []models.Document{}
	err := c.DB.Select(&allDocuments, `SELECT * FROM documents ORDER BY id ASC`)
	if err != nil {
		return VError{err, "error getting documents", http.StatusInternalServerError}
	}

	c.JSON(w, http.StatusOK, allDocuments)
	return nil
}

func (c *DocumentController) GetOne(ctx web.C, w http.ResponseWriter, r *http.Request) error {
	id, err := c.parseIntParam(ctx, "document_id")
	if err != nil {
		return err
	}

	var doc models.Document
	sql, args, _ := (c.Builder.
		Select("*").
		From("documents").
		Where(squirrel.Eq{"id": id}).
		ToSql())
	err = c.DB.Get(&doc, sql, args...)
	if doc.Id == 0 {
		return VError{err, "document not found", 404}
	}

	// TODO: Load this document's tags

	c.JSON(w, http.StatusOK, doc)
	return nil
}

func (c *DocumentController) Create(ctx web.C, w http.ResponseWriter, r *http.Request) error {
	var createParams struct {
		Tags         []int64 `json:"tags"`
		CollectionId int64   `json:"collection_id"`
	}

	if err := json.NewDecoder(r.Body).Decode(&createParams); err != nil {
		return VError{err, "invalid body JSON", http.StatusBadRequest}
	}

	// Validate collection
	var coll models.Collection
	sql, args, _ := (c.Builder.
		Select("*").
		From("collections").
		Where(squirrel.Eq{"id": createParams.CollectionId}).
		ToSql())
	err := c.DB.Get(&coll, sql, args...)
	if coll.Id == 0 {
		return VError{err, fmt.Sprintf("collection %d not found", createParams.CollectionId),
			http.StatusNotFound}
	}

	createdAt := time.Now().UTC().Unix()

	// Insert everything in a transaction
	var id int64
	err = c.inTransaction(func(tx *sqlx.Tx) error {
		sql, args, _ := (c.Builder.
			Insert("documents").
			Columns("created_at", "collection_id").
			Values(createdAt, createParams.CollectionId).
			ToSql())
		ret, err := tx.Exec(c.iQuery(sql), args...)
		if err != nil {
			return VError{err, "error saving document", http.StatusInternalServerError}
		}

		id, _ = ret.LastInsertId()

		// Insert all tags
		for _, tag_id := range createParams.Tags {
			var tag models.Tag

			// Check the tag exists
			sql, args, _ := (c.Builder.
				Select("*").
				From("tags").
				Where(squirrel.Eq{"id": id}).
				ToSql())
			err = tx.Get(&tag, sql, args...)
			if tag.Id == 0 {
				return VError{err, fmt.Sprintf("tag %d not found", tag_id),
					http.StatusNotFound}
			}

			// Insert it
			sql, args, _ = (c.Builder.
				Insert("document_tags").
				Columns("document_id", "tag_id").
				Values(id, tag_id).
				ToSql())
			_, err := tx.Exec(sql, args...)
			if err != nil {
				return VError{err, "error saving document tag",
					http.StatusInternalServerError}
			}
		}

		return nil
	})

	if err != nil {
		return err
	}

	// TODO: render document tags too
	c.JSON(w, http.StatusOK, models.Document{
		Id:           id,
		CreatedAt:    createdAt,
		CollectionId: createParams.CollectionId,
	})
	return nil
}
