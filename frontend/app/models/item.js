import DS from 'ember-data';

export default DS.Model.extend({
  created_at: DS.attr('date'),
  files:      DS.hasMany('file'),
});