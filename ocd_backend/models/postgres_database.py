from sqlalchemy import create_engine, Sequence
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.pool import StaticPool

from ocd_backend import settings
from ocd_backend.models.definitions import Ori
from ocd_backend.models.misc import Uri
from ocd_backend.models.postgres_models import Source, Resource, Property
from ocd_backend.models.properties import StringProperty, URLProperty, IntegerProperty, DateProperty, JsonProperty, \
    DateTimeProperty, ArrayProperty, Relation, OrderedRelation


class PostgresDatabase(object):

    def __init__(self, serializer):
        self.serializer = serializer
        self.connection_string = 'postgresql://%s:%s@%s/%s' % (
                                    settings.POSTGRES_USERNAME,
                                    settings.POSTGRES_PASSWORD,
                                    settings.POSTGRES_HOST,
                                    settings.POSTGRES_DATABASE)
        self.engine = create_engine(self.connection_string, poolclass=StaticPool)
        self.Session = sessionmaker(bind=self.engine)

    def get_ori_identifier(self, iri):
        """
        Retrieves a Resource-based ORI identifier from the database. If no corresponding Resource exists,
        a new one is created.
        """

        session = self.Session()
        try:
            resource = session.query(Resource).join(Source).filter(Source.iri == iri).first()
            if not resource:
                raise NoResultFound
            return Uri(Ori, resource.ori_id)
        except MultipleResultsFound:
            raise MultipleResultsFound('Multiple resources found for IRI %s' % iri)
        except NoResultFound:
            return self.generate_ori_identifier(iri=iri)
        finally:
            session.close()

    def generate_ori_identifier(self, iri):
        """
        Generates a Resource with an ORI identifier and adds the IRI as a Source if it does not already exist.
        """

        session = self.Session()
        new_id = self.engine.execute(Sequence('ori_id_seq'))
        new_identifier = Uri(Ori, new_id)

        try:
            # If the resource already exists, create the source as a child of the resource
            resource = session.query(Source).filter(Source.iri == iri).one().resource
            resource.sources.append(Source(iri=iri))
            session.flush()
        except NoResultFound:
            # If the resource does not exist, create resource and source together
            resource = Resource(ori_id=new_id, iri=new_identifier, sources=[Source(iri=iri)])
            session.add(resource)
            session.commit()
        finally:
            session.close()

        return new_identifier

    def get_mergeable_resource_identifier(self, model_object, predicate, column, value):
        """
        Queries the database to find the ORI identifier of the Resource linked to the Property with the given
        predicate and value in the specified column.
        """

        definition = model_object.definition(predicate)

        session = self.Session()
        try:
            query_result = session.query(Property).filter(Property.predicate == definition.absolute_uri())
            if column == 'prop_resource':
                query_result = query_result.filter(Property.prop_resource == value)
            elif column == 'prop_string':
                query_result = query_result.filter(Property.prop_string == value)
            elif column == 'prop_datetime':
                query_result = query_result.filter(Property.prop_datetime == value)
            elif column == 'prop_integer':
                query_result = query_result.filter(Property.prop_integer == value)
            elif column == 'prop_url':
                query_result = query_result.filter(Property.prop_url == value)
            else:
                raise ValueError('Invalid column type "%s" specified for merge_into' % column)
            resource_property = query_result.one()
            return resource_property.resource.iri
        except MultipleResultsFound:
            raise MultipleResultsFound('Multiple resources found for predicate "%s" with value "%s" in column "%s"' %
                                       (predicate, value, column))
        except NoResultFound:
            raise NoResultFound('No resource found for predicate "%s" with value "%s" in column "%s"' %
                                (predicate, value, column))
        finally:
            session.close()

    def save(self, model_object):
        if not model_object.source_iri:
            # If the item is an Individual, like EventConfirmed, we "save" it by setting an ORI identifier
            iri = self.serializer.label(model_object)
            if not model_object.values.get('ori_identifier'):
                model_object.ori_identifier = self.get_ori_identifier(iri=iri)
        else:
            if not model_object.values.get('ori_identifier'):
                model_object.ori_identifier = self.get_ori_identifier(iri=model_object.source_iri)

            # Handle canonical IRI or ID
            if hasattr(model_object, 'canonical_iri') and model_object.canonical_iri is not None:
                self.update_source(model_object, iri=True)
            if hasattr(model_object, 'canonical_id') and model_object.canonical_id is not None:
                self.update_source(model_object, id=True)

            serialized_properties = self.serializer.deflate(model_object, props=True, rels=True)

            session = self.Session()
            resource = session.query(Resource).filter(Resource.ori_id == model_object.ori_identifier.partition(Ori.uri)[2]).one()

            # Delete properties that are about to be updated
            predicates = serialized_properties.keys()
            session.query(Property).filter(Property.resource_id == resource.ori_id,
                                           Property.predicate.in_(predicates)
                                           ).delete(synchronize_session='fetch')

            # Save new properties
            for predicate, value_and_property_type in serialized_properties.iteritems():
                if isinstance(value_and_property_type[0], list):
                    # Create each item as a separate Property with the same predicate, and save the order to
                    # the `order` column
                    for order, item in enumerate(value_and_property_type[0], start=1):
                        new_property = (Property(predicate=predicate, order=order))
                        setattr(new_property, self.map_column_type((item, value_and_property_type[1])), item)
                        resource.properties.append(new_property)
                else:
                    new_property = (Property(predicate=predicate))
                    setattr(new_property, self.map_column_type(value_and_property_type), value_and_property_type[0])
                    resource.properties.append(new_property)

            session.commit()
            session.close()

    @staticmethod
    def map_column_type(value_and_property_type):
        """Maps the property type to a column."""
        value = value_and_property_type[0]
        property_type = value_and_property_type[1]

        if property_type == StringProperty:
            return 'prop_string'
        if property_type is URLProperty:
            return 'prop_url'
        elif property_type is IntegerProperty:
            return 'prop_integer'
        elif property_type in (DateProperty, DateTimeProperty):
            return 'prop_datetime'
        elif property_type is JsonProperty:
            return 'prop_json'
        elif property_type in (ArrayProperty, Relation, OrderedRelation):
            try:
                int(value)
                return 'prop_resource'
            except (ValueError, TypeError):
                return 'prop_string'
        else:
            raise ValueError('Unable to map property of type "%s" to a column.' % property_type)

    def update_source(self, model_object, iri=False, id=False):
        """Updates the canonical IRI or ID field of the Source of the corresponding model object."""

        if iri:
            canonical_field = 'canonical_iri'
        elif id:
            canonical_field = 'canonical_id'
        else:
            raise ValueError('update_source must be called with either iri or id as True')

        session = self.Session()
        resource = session.query(Resource).get(model_object.get_short_identifier())

        try:
            # Check if there is already a Source record, and if so update its canonical field
            source = session.query(Source).filter(Source.resource_ori_id == resource.ori_id).one()
            setattr(source, canonical_field, getattr(model_object, canonical_field))
        except NoResultFound:
            # No Source exists for the given source IRI, so create it and fill the corresponding canonical field
            source = Source(resource=resource,
                            iri=model_object.source_iri)
            setattr(source, canonical_field, getattr(model_object, canonical_field))
            session.add(source)
        except MultipleResultsFound:
            raise

        session.commit()
        session.close()
