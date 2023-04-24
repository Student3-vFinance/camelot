# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from camelot.core.conf import settings, SimpleSettings
from camelot.core.memento import memento_change, SqlMemento, memento_types
from camelot.core.profile import Profile, ProfileStore
from camelot.core.qt import py_to_variant, variant_to_py

from .test_model import ExampleModelMixinCase

memento_id_counter = 0

class MementoCase(unittest.TestCase, ExampleModelMixinCase):
    """test functions from camelot.core.memento
    """
    
    def setUp( self ):
        super( MementoCase, self ).setUp()
        self.setup_sample_model()
        global memento_id_counter
        custom_memento_types = memento_types + [(100, 'custom')]
        self.memento = SqlMemento( memento_types = custom_memento_types )
        memento_id_counter += 1
        self.id_counter = memento_id_counter
        self.model = 'TestMemento'

    def tearDown(self):
        self.tear_down_sample_model()

    def test_lifecycle( self ):
        memento_changes = [
            memento_change( self.model, 
                            [self.id_counter], 
                            None, 'create' ),            
            memento_change( self.model, 
                            [self.id_counter], 
                            {'name':'foo'}, 'before_update' ),
            memento_change( self.model, 
                            [self.id_counter], 
                            {'name':'bar'}, 'before_delete' ),            
            ]
        
        self.memento.register_changes( memento_changes )
        changes = list( self.memento.get_changes( self.model,
                                                  [self.id_counter],
                                                  {} ) )
        self.assertEqual( len(changes), 3 )
        
    def test_no_error( self ):
        memento_changes = [
            memento_change( None, 
                            [self.id_counter], 
                            None, None ),                     
            ]
        self.memento.register_changes( memento_changes )
        
    def test_custom_memento_type( self ):
        memento_changes = [
            memento_change( self.model, 
                            [self.id_counter], 
                            {}, 'custom' ),                     
            ]
        self.memento.register_changes( memento_changes )
        changes = list( self.memento.get_changes( self.model,
                                                  [self.id_counter],
                                                  {} ) )
        self.assertEqual( len(changes), 1 )
       
class ProfileCase(unittest.TestCase):
    """Test the save/restore and selection functions of the database profile
    """
    
    def test_profile_state( self ):
        name, host, password = u'profile_tést', u'192.168.1.1', u'top-sécrèt'
        profile = Profile( name=name, host=host, password=password )
        state = profile.__getstate__()
        # name should not be encrypted, others should
        self.assertEqual( state['profilename'], name )
        self.assertEqual( state['host'], host )
        self.assertEqual( state['pass'], password )
        new_profile = Profile(name=None)
        new_profile.__setstate__( state )
        self.assertEqual( new_profile.name, name )
        self.assertEqual( new_profile.host, host )
        self.assertEqual( new_profile.password, password )

    def test_registry_settings(self):
        # construct a profile store from application settings
        store = ProfileStore()
        store.read_profiles()
        # continue test with a profile store from file, to avoid test inference

    def test_profile_store( self ):
        handle, filename = tempfile.mkstemp()
        os.close(handle)
        store = ProfileStore(filename)
        self.assertEqual( store.read_profiles(), [] )
        self.assertEqual( store.get_last_profile(), None )
        profile_1 = Profile('prôfile_1')
        profile_1.dialect = 'sqlite'
        profile_1.locale_language = 'en_US'
        profile_2 = Profile('prôfile_2')
        profile_2.dialect = 'mysql'
        profile_2.locale_language = 'en_GB'
        store.write_profiles( [profile_1, profile_2] )
        self.assertEqual( len(store.read_profiles()), 2 )
        store.set_last_profile( profile_1 )
        self.assertTrue( store.get_last_profile().name, 'prôfile_1' )
        self.assertTrue( store.get_last_profile().dialect, 'sqlite' )
        self.assertTrue( store.get_last_profile().locale_language, 'en_US' )
        store.set_last_profile( profile_2 )
        self.assertTrue( store.get_last_profile().name, 'prôfile_2' )
        self.assertTrue( store.get_last_profile().dialect, 'mysql' )
        self.assertTrue( store.get_last_profile().locale_language, 'en_GB' )
        # os.remove(filename)

        return store

class ConfCase(unittest.TestCase):
    """Test the global configuration"""
    
    def test_import_settings(self):
        self.assertEqual( settings.get('FOO', None), None )
        self.assertRaises( AttributeError, lambda:settings.FOO )
        self.assertTrue( settings.CAMELOT_MEDIA_ROOT.endswith( 'media' ) )
        self.assertFalse( hasattr( settings, 'FOO' ) )
        
        class AdditionalSettings( object ):
            FOO = True
            
        settings.append( AdditionalSettings() )
        self.assertTrue( hasattr( settings, 'FOO' ) )
        try:
            settings.append_settings_module()
        except ImportError:
            pass
        
    def test_simple_settings(self):
        settings = SimpleSettings( 'Conceptive Engineering', 'Camelot Test')
        self.assertTrue( settings.ENGINE() )
        self.assertTrue( settings.CAMELOT_MEDIA_ROOT() )

class QtCase(unittest.TestCase):
    """Test the qt binding abstraction module
    """

    def test_variant(self):
        for obj in ['a', 5]:
            self.assertEqual(variant_to_py(py_to_variant(obj)), obj)
