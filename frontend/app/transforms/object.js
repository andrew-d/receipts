import Ember from 'ember';
import DS from 'ember-data';

export default DS.Transform.extend({
    deserialize: function(serialized) {
        return Ember.none(serialized) ? {} : serialized;
    },

    serialize: function(deserialized) {
        return Ember.none(deserialized) ? {} : deserialized;
    }
});