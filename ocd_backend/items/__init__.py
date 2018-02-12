import json
from collections import MutableMapping
from datetime import datetime
from hashlib import sha1

from ocd_backend.exceptions import (UnableToGenerateObjectId,
                                    FieldNotAvailable)
from ocd_backend.utils import json_encoder
from ocd_backend.models import Metadata
from owltology.model import ModelBase


class BaseItem(object):
    """Represents a single extracted and transformed item.

    :param source_definition: The configuration of a single source in
        the form of a dictionary (as defined in the settings).
    :type source_definition: dict
    :param data_content_type: The content-type of the data retrieved
        from the source (e.g. ``application/json``).
    :type data_content_type: str
    :param data: The data in it's original format, as retrieved
        from the source.
    :type data: unicode
    :param item: the deserialized item retrieved from the source.
    :param processing_started: The datetime we started processing this
        item. If ``None``, the current datetime is used.
    :type processing_started: datetime or None
    """

    def __init__(self, source_definition, data_content_type, data, item, run_node, processing_started=None, final_try=False):
        self.source_definition = source_definition
        self.data_content_type = data_content_type
        self.data = data
        self.original_item = item
        self.run_node = run_node
        self.final_try = final_try

        # On init, all data should be available to construct self.meta
        # and self.combined_item
        self._store_object_data()
        self._construct_object_meta(processing_started)

    def _construct_object_meta(self, processing_started=None):
        meta = Metadata('ori_identifier', self.object_data.get_ori_id())

        if not processing_started:
            meta.processing_started = datetime.now()

        meta.source_id = unicode(self.source_definition['id'])
        meta.collection = self.get_collection()
        meta.rights = self.get_rights()

        self.object_data.attach('meta', self.run_node, rel_params=meta)

        return meta

    def _store_object_data(self):
        object_data = self.get_object_model()
        object_data.save()

        self.object_data = object_data

    def get_object_model(self):
        """Construct the document that should be inserted into the index
        belonging to the item's source.

        :returns: a dict ready for indexing.
        :rtype: dict
        """
        return self.object_data

    def get_collection(self):
        """Retrieves the name of the collection the item belongs to.

        This method should be implemented by the class that inherits from
        :class:`.BaseItem`.

        :rtype: unicode.
        """
        raise NotImplementedError

    def get_rights(self):
        """Retrieves the rights of the item as defined by the source.
        With 'rights' we mean information about copyright, licenses,
        instructions for reuse, etcetera. "Creative Commons Zero" is an
        example of a possible value of rights.

        This method should be implemented by the class that inherits from
        :class:`.BaseItem`.

        :rtype: unicode.
        """
        raise NotImplementedError

    def map_object_data(self):
        """Returns a dictionary containing the data that is suitable to
        be indexed in a combined/normalized repository, together with
        items from other collections. Only keys defined in
        :attr:`.combined_index_fields`
        are allowed.

        This method should be implemented by the class that inherits
        from :class:`.BaseItem`.

        :rtype: owltology.models.Modelbase
        """
        raise NotImplementedError


class LocalDumpItem(BaseItem):
    """
    Represents an Item extracted from a local dump
    """
    def get_collection(self):
        collection = self.original_item['_source'].get('meta', {})\
            .get('collection')
        if not collection:
            raise FieldNotAvailable('collection')
        return collection

    def get_rights(self):
        rights = self.original_item['_source'].get('meta', {}).get('rights')
        if not rights:
            raise FieldNotAvailable('rights')
        return rights

    def get_original_object_id(self):
        original_object_id = self.original_item['_source'].get('meta', {})\
            .get('original_object_id')
        if not original_object_id:
            raise FieldNotAvailable('original_object_id')
        return original_object_id

    def get_original_object_urls(self):
        original_object_urls = self.original_item['_source'].get('meta', {})\
            .get('original_object_urls')
        if not original_object_urls:
            raise FieldNotAvailable('original_object_urls')
        return original_object_urls

    def get_object_model(self):
        combined_index_data = self.original_item['_source']\
            .get('combined_index_data')
        if not combined_index_data:
            raise FieldNotAvailable('combined_index_data')

        data = json.loads(combined_index_data)
        data.pop('meta')
        # Cast datetimes
        for key, value in data.iteritems():
            if self.combined_index_fields.get(key) == datetime:
                data[key] = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')

        return data

    def get_all_text(self):
        """
        Returns the content that is stored in the combined_index_data.all_text
        field, and raise a `FieldNotAvailable` exception when it is not
        available.

        :rtype: unicode
        """
        combined_index_data = json.loads(self.original_item['_source']
                                         .get('combined_index_data', {}))
        all_text = combined_index_data.get('all_text')
        if not all_text:
            raise FieldNotAvailable('combined_index_data.all_text')
        return all_text

    def get_index_data(self):
        """Restore all fields that are originally indexed.

        :rtype: dict
        """
        return self.original_item.get('_source', {})
