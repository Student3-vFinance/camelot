import datetime
import os
import unittest

import six

from sqlalchemy import orm, schema, types, create_engine

from camelot.admin.application_admin import ApplicationAdmin
from camelot.admin.entity_admin import EntityAdmin
from camelot.core.orm import Session, process_deferred_properties
from camelot.core.conf import settings
from camelot.core.sql import metadata

from camelot.model import party, memento, authentication
from camelot.model.party import Person
from camelot.model.authentication import (
    update_last_login, get_current_authentication
)
from camelot.model.batch_job import BatchJob, BatchJobType
from camelot.model.fixture import Fixture, FixtureVersion
from camelot.model.i18n import Translation

from camelot.test.action import MockModelContext

from camelot_example.fixtures import load_movie_fixtures
from camelot_example import model
from camelot_example.view import setup_views

from .test_orm import TestMetaData

app_admin = ApplicationAdmin()

#
# This creates an in memory database per thread
#
model_engine = create_engine('sqlite://')

class ExampleModelMixinCase(object):

    @classmethod
    def setup_sample_model(cls):
        process_deferred_properties()
        setup_views()
        metadata.bind = model_engine
        metadata.create_all(model_engine)
        cls.session = Session()
        cls.session.expunge_all()
        update_last_login()

    @classmethod
    def tear_down_sample_model(cls):
        cls.session.expunge_all()
        metadata.bind = None

    @classmethod
    def load_example_data(cls):
        """
        set cls.first_person_id, to have the id of a person available in the gui
        """
        load_movie_fixtures()
        cls.first_person_id = cls.session.query(Person).first().id

    @classmethod
    def dirty_session(cls):
        """
        Create objects in various states to make the session dirty
        """
        cls.session.expunge_all()
        # create objects in various states
        #
        p1 = Person(first_name = u'p1', last_name = u'persistent' )
        p2 = Person(first_name = u'p2', last_name = u'dirty' )
        p3 = Person(first_name = u'p3', last_name = u'deleted' )
        p4 = Person(first_name = u'p4', last_name = u'to be deleted' )
        p5 = Person(first_name = u'p5', last_name = u'detached' )
        p6 = Person(first_name = u'p6', last_name = u'deleted outside session' )
        cls.session.flush()
        p3.delete()
        cls.session.flush()
        p4.delete()
        p2.last_name = u'clean'
        #
        # delete p6 without the session being aware
        #
        person_table = Person.table
        cls.session.execute(
            person_table.delete().where( person_table.c.party_id == p6.id )
        )


class ModelCase(unittest.TestCase, ExampleModelMixinCase):
    """Test the build in camelot model"""

    @classmethod
    def setUpClass(cls):
        cls.setup_sample_model()

    @classmethod
    def tearDownClass(cls):
        cls.tear_down_sample_model()

    def test_memento( self ):
        m = memento.Memento( primary_key = 1,
                             model = 'TestCase',
                             authentication = get_current_authentication(),
                             memento_type = 1,
                             previous_attributes = {'name':u'memento'} )
        self.assertTrue( m.previous )
        
    def test_i18n( self ):
        session = Session()
        session.execute( Translation.__table__.delete() )
        self.assertEqual( Translation.translate( 'bucket', 'nl_BE' ), None )
        # run twice to check all branches in the code
        Translation.translate_or_register( 'bucket', 'nl_BE' )
        Translation.translate_or_register( 'bucket', 'nl_BE' )
        self.assertEqual( Translation.translate( 'bucket', 'nl_BE' ), 'bucket' )
        self.assertEqual( Translation.translate( '', 'nl_BE' ), '' )
        self.assertEqual( Translation.translate_or_register( '', 'nl_BE' ), '' )
        # clear the cache
        Translation._cache.clear()
        # fill the cache again
        translation = Translation( language = 'nl_BE', source = 'bucket',
                                   value = 'emmer' )
        orm.object_session( translation ).flush()
        self.assertEqual( Translation.translate( 'bucket', 'nl_BE' ), 'emmer' )
        
    def test_batch_job_example( self ):
        # begin batch job example
        synchronize = BatchJobType.get_or_create( u'Synchronize' )
        with BatchJob.create( synchronize ) as batch_job:
            batch_job.add_strings_to_message( [ u'Synchronize part A',
                                                u'Synchronize part B' ] )
            batch_job.add_strings_to_message( [ u'Done' ], color = 'green' )
        # end batch job example
            
    def test_batch_job( self ):
        batch_job_type = BatchJobType.get_or_create( u'Synchronize' )
        self.assertTrue( six.text_type( batch_job_type ) )
        batch_job = BatchJob.create( batch_job_type )
        self.assertTrue( orm.object_session( batch_job ) )
        self.assertFalse( batch_job.is_canceled() )
        batch_job.change_status( 'canceled' )
        self.assertTrue( batch_job.is_canceled() )
        # run batch job without exception
        with batch_job:
            batch_job.add_strings_to_message( [ u'Doing something' ] )
            batch_job.add_strings_to_message( [ u'Done' ], color = 'green' )
        self.assertEqual( batch_job.current_status, 'success' )
        # run batch job with exception
        batch_job = BatchJob.create( batch_job_type )
        with batch_job:
            batch_job.add_strings_to_message( [ u'Doing something' ] )
            raise Exception('Something went wrong')
        self.assertEqual( batch_job.current_status, 'errors' )
    
    def test_current_authentication( self ):
        authentication.clear_current_authentication()
        mechanism = authentication.get_current_authentication()
        # current authentication cache should survive 
        # a session expire + expunge
        orm.object_session( mechanism ).expire_all()
        orm.object_session( mechanism ).expunge_all()
        mechanism = authentication.get_current_authentication()
        self.assertTrue( mechanism.username )
        self.assertTrue( six.text_type( mechanism ) )
        
    def test_authentication_group( self ):
        # begin roles definition
        authentication.clear_current_authentication()
        authentication.roles.extend( [ (1, 'administrator'),
                                       (2, 'movie_editor') ] )
        # end roles definition
        # begin intial group creation
        authentication.update_last_login( initial_group_name = 'Admin',
                                          initial_group_roles = ['administrator'] )
        # end initial group creation
        auth = authentication.get_current_authentication()
        self.assertTrue( auth.has_role( 'administrator' ) )
        self.assertFalse( auth.has_role( 'movie_editor' ) )

class PartyCase(unittest.TestCase, ExampleModelMixinCase):
    """Test the build in party - address - contact mechanism model"""

    @classmethod
    def setUpClass(cls):
        super(PartyCase, cls).setUpClass()
        cls.setup_sample_model()
        cls.app_admin = ApplicationAdmin()
        cls.person_admin = cls.app_admin.get_related_admin(party.Person)
        cls.organization_admin = cls.app_admin.get_related_admin(party.Organization)

    @classmethod
    def tearDownClass(cls):
        cls.tear_down_sample_model()

    def setUp(self):
        self.session = Session()
        self.session.close()

    def test_party( self ):
        p = party.Party()
        self.assertFalse(p.name)
        
    def test_geographic_boundary( self ):
        belgium = party.Country.get_or_create( code = u'BE', 
                                               name = u'Belgium' )
        self.assertTrue( six.text_type( belgium ) )
        city = party.City.get_or_create( country = belgium,
                                         code = '1000',
                                         name = 'Brussels' )
        return city
        
    def test_address( self ):
        city = self.test_geographic_boundary()
        address = party.Address.get_or_create( street1 = 'Avenue Louise',
                                               street2 = None,
                                               city = city,
                                               zip_code='1000')
        self.assertTrue( six.text_type( address ) )
        return address

    def test_party_address( self ):
        city = self.test_geographic_boundary()
        org = party.Organization( name = 'PSF' )
        party_address = party.PartyAddress( party = org )
        party_address.street1 = 'Avenue Louise 5'
        party_address.street2 = 'Boite 4'
        party_address.city = city
        party_address_admin = party.AddressAdmin( self.app_admin, party.PartyAddress )
        self.assertEqual(len(org.addresses), 1)
        self.assertTrue( party_address.address in party_address_admin.get_compounding_objects( party_address ) )
        self.assertTrue( party_address.address in self.session.new )
        # everything should be flushed through the party admin
        org_admin = self.app_admin.get_related_admin( party.Organization )
        org_validator = org_admin.get_validator()
        self.assertTrue( party_address in org_admin.get_compounding_objects( org ) )
        org_admin.flush(org)
        self.assertFalse(party_address.address in self.session.new)
        self.assertFalse(party_address in self.session.new)
        self.assertFalse(org in self.session.new)
        self.assertEqual(len(org.addresses), 1)
        party_address_admin.refresh(party_address)
        # test hybrid property getters on Party and PartyAddress
        self.assertEqual(len(org.addresses), 1)
        self.assertEqual( party_address.street1, 'Avenue Louise 5' )
        self.assertEqual( party_address.street2, 'Boite 4' )
        self.assertEqual( party_address.city, city )
        self.assertEqual( org.street1, 'Avenue Louise 5' )
        self.assertEqual( org.street2, 'Boite 4' )
        self.assertEqual( org.city, city )        
        self.assertTrue( six.text_type( party_address ) )
        query = self.session.query( party.PartyAddress )
        self.assertTrue( query.filter( party.PartyAddress.street1 == 'Avenue Louise 5' ).first() )
        self.assertTrue( query.filter( party.PartyAddress.street2 == 'Boite 4' ).first() )
        # if party address changes, party should be updated
        depending_objects = list( party_address_admin.get_depending_objects( party_address ) )
        self.assertTrue( org in depending_objects )
        # if address changes, party address and party should be updated
        address = party_address.address
        address_admin = self.app_admin.get_related_admin( party.Address )
        depending_objects = list( address_admin.get_depending_objects( address ) )
        self.assertTrue( party_address in depending_objects )
        self.assertTrue( org in depending_objects )
        # test hybrid property setters on Party
        org.street1 = 'Rue Belliard 1'
        org.street2 = 'Second floor'
        org.city = None
        # expunge should expunge the related address objects as well, so
        # after an expunge, the session as a whole can be flushed
        org_admin.expunge( org )
        self.session.flush()
        # test hybrid property setters on a new party
        org = party.Organization( name = 'PSF' )
        org.street1 = 'Rue Belliard 1'
        org.street2 = 'Second floor'
        org.city = city
        org_admin.flush( org )
        self.assertEqual( len( org.addresses ), 1 )
        self.assertEqual( org.street1, 'Rue Belliard 1' )
        self.assertEqual( org.street2, 'Second floor' )
        self.assertEqual( org.city, city )
        # test invalidation of org object and refresh it
        self.assertFalse( org_validator.validate_object( org ) )
        org.city = None
        self.assertTrue( org_validator.validate_object( org ) )
        org_admin.refresh( org )
        self.assertFalse( org_validator.validate_object( org ) )
        # removing all the address properties should make the
        # object valid again
        org.street1 = None
        org.street2 = None
        org.city = None
        self.assertFalse( org_validator.validate_object( org ) )
        # removing all address properties of a not yet flushed
        # address should expunge the address
        org = party.Organization( name = 'PSF' )
        org.street1 = 'Rue Belliard 1'
        for address in org.addresses:
            self.assertTrue( address in self.session.new )
        org.street1 = None
        self.assertTrue( address not in self.session )
        self.assertEqual( len(org.addresses), 0 )
        
    def test_person( self ):
        person = party.Person( first_name = u'Robin',
                               last_name = u'The brave' )
        self.assertEqual( person.email, None )
        self.assertEqual( person.phone, None )
        self.assertEqual( person.fax, None )
        self.assertEqual( person.street1, None )
        self.assertEqual( person.street2, None )
        self.assertEqual( person.city, None )
        self.person_admin.flush( person )
        person2 = party.Person( first_name = u'Robin' )
        self.assertFalse( person2.note )
        person2.last_name = u'The brave'
        # gui should warn this person exists
        self.assertTrue( person2.note )
        return person
        
    def test_contact_mechanism( self ):
        contact_mechanism = party.ContactMechanism( mechanism = (u'email', u'info@test.be') )
        self.assertTrue( six.text_type( contact_mechanism ) )
        
    def test_person_contact_mechanism( self ):
        # create a new person
        person = party.Person( first_name = u'Robin',
                               last_name = u'The brave' )
        self.person_admin.flush( person )
        self.assertEqual( person.email, None )
        # set the contact mechanism
        mechanism_1 = (u'email', u'robin@test.org')
        person.email = mechanism_1
        # the default from and thru dates should be set when
        # setting the party defaults
        self.person_admin.set_defaults( person )
        self.assertTrue( person.contact_mechanisms[0].from_date )
        self.person_admin.flush( person )
        self.assertEqual( person.email, mechanism_1 )
        # change the contact mechanism, after a flush
        mechanism_2 = (u'email', u'robin@test.com')
        person.email = mechanism_2
        self.person_admin.flush( person )
        self.assertEqual( person.email, mechanism_2 )
        # remove the contact mechanism after a flush
        person.email = ('email', '')
        self.assertEqual( person.email, None )
        self.person_admin.flush( person )
        self.assertEqual( person.email, None )
        admin = party.PartyContactMechanismAdmin( self.app_admin, 
                                                  party.PartyContactMechanism )
        contact_mechanism = party.ContactMechanism( mechanism = mechanism_1 )
        party_contact_mechanism = party.PartyContactMechanism( party = person,
                                                               contact_mechanism = contact_mechanism )
        admin.flush( party_contact_mechanism )
        admin.refresh( party_contact_mechanism )
        list( admin.get_depending_objects( party_contact_mechanism ) )
        #
        # if the contact mechanism changes, the party person should be 
        # updated as well
        #
        contact_mechanism_admin = self.app_admin.get_related_admin( party.ContactMechanism )
        depending_objects = list( contact_mechanism_admin.get_depending_objects( contact_mechanism ) )
        self.assertTrue( person in depending_objects )
        self.assertTrue( party_contact_mechanism in depending_objects )
        #
        # if the party contact mechanism changes, the party should be updated
        # as well
        depending_objects = list( admin.get_depending_objects( party_contact_mechanism ) )
        self.assertTrue( person in depending_objects )
        # delete the person
        self.person_admin.delete( person )
        
    def test_organization( self ):
        org = party.Organization( name = 'PSF' )
        org.email = ('email', 'info@python.org')
        org.phone = ('phone', '1234')
        org.fax = ('fax', '4567')
        self.organization_admin.flush( org )
        self.assertTrue( six.text_type( org ) )
        query = orm.object_session( org ).query( party.Organization )
        self.assertTrue( query.filter( party.Organization.email == ('email', 'info@python.org') ).first() )
        self.assertTrue( query.filter( party.Organization.phone == ('phone', '1234') ).first() )
        self.assertTrue( query.filter( party.Organization.fax == ('fax', '4567') ).first() )
        return org
        
    def test_party_contact_mechanism( self ):
        person = self.test_person()
        party_contact_mechanism = party.PartyContactMechanism( party = person )
        party_contact_mechanism.mechanism = (u'email', u'info@test.be')
        party_contact_mechanism.mechanism = (u'email', u'info2@test.be')
        self.assertTrue( party_contact_mechanism in self.session.new )
        self.assertTrue( party_contact_mechanism.contact_mechanism in self.session.new )
        # flushing trough the party should flush the contact mechanism
        self.person_admin.flush( person )
        self.assertFalse( party_contact_mechanism in self.session.new )
        self.assertFalse( party_contact_mechanism.contact_mechanism in self.session.new )        
        self.assertTrue( six.text_type( party_contact_mechanism ) )
        query = self.session.query( party.PartyContactMechanism )
        self.assertTrue( query.filter( party.PartyContactMechanism.mechanism == (u'email', u'info2@test.be') ).first() )
        # party contact mechanism is only valid when contact mechanism is
        # valid
        party_contact_mechanism_admin = self.app_admin.get_related_admin( party.PartyContactMechanism )
        compounding_objects = list( party_contact_mechanism_admin.get_compounding_objects( party_contact_mechanism ) )
        self.assertTrue( party_contact_mechanism.contact_mechanism in compounding_objects )
        party_contact_mechanism_validator = party_contact_mechanism_admin.get_validator()
        self.assertFalse( party_contact_mechanism_validator.validate_object( party_contact_mechanism ) )
        party_contact_mechanism.contact_mechanism.mechanism = None
        self.assertTrue( party_contact_mechanism_validator.validate_object( party_contact_mechanism ) )
        # the party is only valid when the contact mechanism is
        # valid
        party_admin = self.app_admin.get_related_admin( party.Person )
        party_validator = party_admin.get_validator()
        self.assertTrue( party_validator.validate_object( person ) )
        
    def test_party_category( self ):
        org = self.test_organization()
        category = party.PartyCategory( name = u'Imortant' )
        category.parties.append( org )
        self.session.flush()
        self.assertTrue( list( category.get_contact_mechanisms( u'email') ) )
        self.assertTrue( six.text_type( category ) )

class FixtureCase(unittest.TestCase, ExampleModelMixinCase):
    """Test the build in camelot model for fixtures"""

    @classmethod
    def setUpClass(cls):
        cls.setup_sample_model()

    @classmethod
    def tearDownClass(cls):
        cls.tear_down_sample_model()

    def test_fixture( self ):
        session = Session()
        self.assertEqual( Fixture.find_fixture_key( Person, -1 ), None )
        p1 = Person()
        self.assertEqual( Fixture.find_fixture_key_and_class( p1 ), 
                          (None, None) )
        session.expunge(p1)
        # insert a new Fixture
        p2 = Fixture.insert_or_update_fixture( Person, 'test',
                                               {'first_name':'Peter',
                                                'last_name':'Principle'},
                                               fixture_class = 'test' )
        # see if we can find it back
        self.assertEqual( Fixture.find_fixture_key( Person, p2.id ), 'test' )
        self.assertEqual( Fixture.find_fixture_key_and_class( p2 ), 
                          ('test', 'test') )
        self.assertEqual( Fixture.find_fixture_keys_and_classes( Person )[p2.id],
                          ('test', 'test') )
        # delete the person, and insert it back in the same fixture
        session.delete(p2)
        session.flush()
        p3 = Fixture.insert_or_update_fixture( Person, 'test',
                                               {'first_name':'Peter',
                                                'last_name':'Principle'},
                                               fixture_class = 'test' )
        self.assertNotEqual( p2, p3 )
        # remove all fixtures
        Fixture.remove_all_fixtures( Person )
        
    def test_fixture_version( self ):
        self.assertEqual( FixtureVersion.get_current_version( u'unexisting' ),
                          0 )        
        FixtureVersion.set_current_version( u'demo_data', 0 )
        self.session.flush()
        self.assertEqual( FixtureVersion.get_current_version( u'demo_data' ),
                          0 )
        example_file = os.path.join( os.path.dirname(__file__), 
                                     '..', 
                                     'camelot_example',
                                     'import_example.xlsx' )
        person_count_before_import = Person.query.count()
        # begin load csv if fixture version
        from camelot.view.import_utils import XlsReader
        if FixtureVersion.get_current_version( u'demo_data' ) == 0:
            reader = XlsReader(example_file)
            for line in reader:
                Person( first_name = line[0], last_name = line[1] )
            FixtureVersion.set_current_version( u'demo_data', 1 )
            self.session.flush()
        # end load csv if fixture version
        self.assertTrue( Person.query.count() > person_count_before_import )
        self.assertEqual( FixtureVersion.get_current_version( u'demo_data' ),
                          1 )
        
class CustomizationCase(unittest.TestCase, ExampleModelMixinCase):

    @classmethod
    def setUpClass(cls):
        cls.setup_sample_model()

    def test_add_field( self ):
        metadata.drop_all()
        session = Session()
        # begin add custom field
        party.Person.language = schema.Column( types.Unicode(30) )
        
        metadata.create_all()
        p = party.Person( first_name = u'Peter', 
                          last_name = u'Principle', 
                          language = u'English' )
        session.flush()
        # end add custom field
        
class StatusCase( TestMetaData ):
    
    def test_status_type( self ):
        Entity, session = self.Entity, self.session
        
        #begin status type definition
        from camelot.model import type_and_status
        
        class Invoice( Entity, type_and_status.StatusMixin ):
            book_date = schema.Column( types.Date(), nullable = False )
            status = type_and_status.Status()
            
        #end status type definition
        self.create_all()
        self.assertTrue( issubclass( Invoice._status_type, type_and_status.StatusTypeMixin ) )
        self.assertTrue( issubclass( Invoice._status_history, type_and_status.StatusHistory ) )
        #begin status types definition
        draft = Invoice._status_type( code = 'DRAFT' )
        ready = Invoice._status_type( code = 'READY' )
        session.flush()
        #end status types definition
        self.assertTrue( six.text_type( ready ) )
        #begin status type use
        invoice = Invoice( book_date = datetime.date.today() )
        self.assertEqual( invoice.current_status, None )
        invoice.change_status( draft, status_from_date = datetime.date.today() )
        #end status type use
        self.assertEqual( invoice.current_status, draft )
        self.assertEqual( invoice.get_status_from_date( draft ), datetime.date.today() )
        self.assertTrue( len( invoice.status ) )
        for history in invoice.status:
            self.assertTrue( six.text_type( history ) )
        
    def test_status_enumeration( self ):
        Entity, session = self.Entity, self.session
        
        #begin status enumeration definition
        from camelot.model import type_and_status
        
        class Invoice( Entity, type_and_status.StatusMixin ):
            book_date = schema.Column( types.Date(), nullable = False )
            status = type_and_status.Status( enumeration = [ (1, 'DRAFT'),
                                                             (2, 'READY'),
                                                             (3, 'BLOCKED')] )
            
            class Admin( EntityAdmin ):
                list_display = ['book_date', 'current_status']
                list_actions = [ type_and_status.ChangeStatus( 'DRAFT' ),
                                 type_and_status.ChangeStatus( 'READY' ) ]
                form_actions = list_actions
                
        #end status enumeration definition
        self.create_all()
        self.assertTrue( issubclass( Invoice._status_history, type_and_status.StatusHistory ) )
        #begin status enumeration use
        invoice = Invoice( book_date = datetime.date.today() )
        self.assertEqual( invoice.current_status, None )
        invoice.change_status( 'DRAFT', status_from_date = datetime.date(2012,1,1) )
        session.flush()
        self.assertEqual( invoice.current_status, 'DRAFT' )
        self.assertEqual( invoice.get_status_from_date( 'DRAFT' ), datetime.date(2012,1,1) )
        draft_invoices = Invoice.query.filter( Invoice.current_status == 'DRAFT' ).count()
        ready_invoices = Invoice.query.filter( Invoice.current_status == 'READY' ).count()
        #end status enumeration use
        self.assertEqual( draft_invoices, 1 )
        self.assertEqual( ready_invoices, 0 )
        ready_action = Invoice.Admin.list_actions[-1]
        model_context = MockModelContext()
        model_context.obj = invoice
        model_context.admin = app_admin.get_related_admin(Invoice)
        list( ready_action.model_run( model_context ) )
        self.assertTrue( invoice.current_status, 'READY' )
        # changing the status should work without flushing
        invoice.status.append(Invoice._status_history(
            status_from_date=datetime.date.today(),
            status_thru_date=party.end_of_times(),
            classified_by='DRAFT'))
        session.flush()
        self.assertTrue( invoice.current_status, 'DRAFT')
        invoice.status.append(Invoice._status_history(
            status_from_date=datetime.date.today(),
            status_thru_date=party.end_of_times(),
            classified_by='BLOCKED'))
        self.assertTrue( invoice.current_status, 'BLOCKED')
        session.flush()
        self.assertTrue( invoice.current_status, 'BLOCKED')
