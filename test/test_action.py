import datetime
import io
import logging
import os
import unittest

import openpyxl

import six

from camelot.core.exception import UserException
from camelot.core.item_model import ListModelProxy, ObjectRole
from camelot.admin.action import Action, ActionStep, State
from camelot.admin.action import (
    list_action, application_action, form_action, list_filter,
    ApplicationActionGuiContext
)
from camelot.admin.action.application import Application
from camelot.admin.validator.entity_validator import EntityValidator
from camelot.core.qt import QtGui, QtWidgets, Qt
from camelot.core.exception import CancelRequest
from camelot.core.utils import ugettext_lazy as _
from camelot.core.orm import Session

from camelot.model import party
from camelot.model.party import Person

from camelot.test import GrabMixinCase, RunningThreadCase
from camelot.test.action import MockModelContext
from camelot.view import action_steps, import_utils
from camelot.view.controls import tableview, actionsbox
from camelot.view import utils
from camelot.view.import_utils import (
    ColumnMapping, MatchNames, ColumnMappingAdmin
)
from camelot.view.workspace import DesktopWorkspace
from camelot_example.model import Movie

from sqlalchemy import orm

from . import app_admin
from . import test_view
from .test_item_model import QueryQStandardItemModelMixinCase
from .test_model import ExampleModelMixinCase

test_images = [os.path.join( os.path.dirname(__file__), '..', 'camelot_example', 'media', 'covers', 'circus.png') ]

LOGGER = logging.getLogger(__name__)

class SerializableMixinCase(object):

    def _write_read(self, step):
        """
        Serialize and deserialize an object, return the deserialized object
        """
        stream = io.BytesIO()
        step.write_object(stream)
        stream.seek(0)
        stream.seek(0)
        step_type = type(step)
        deserialized_object = step_type.__new__(step_type)
        deserialized_object.read_object(stream)
        return deserialized_object


class ActionBaseCase(RunningThreadCase, SerializableMixinCase):

    def setUp(self):
        super().setUp()
        self.admin_route = app_admin.get_admin_route()
        self.gui_context = ApplicationActionGuiContext()
        self.gui_context.admin_route = self.admin_route

    def test_action_step(self):
        step = ActionStep()
        step.gui_run(self.gui_context)

    def test_action(self):

        class CustomAction( Action ):
            verbose_name = 'Custom Action'
            shortcut = QtGui.QKeySequence.New

        action = CustomAction()
        list(self.gui_run(action, self.gui_context))
        state = self.get_state(action, self.gui_context)
        self.assertTrue(state.verbose_name)


class ActionWidgetsCase(unittest.TestCase, GrabMixinCase):
    """Test widgets related to actions.
    """

    images_path = test_view.static_images_path

    def setUp(self):
        from camelot_example.importer import ImportCovers
        self.action = ImportCovers()
        self.admin_route = app_admin.get_admin_route()
        self.workspace = DesktopWorkspace(self.admin_route, None)
        self.gui_context = self.workspace.gui_context
        self.parent = QtWidgets.QWidget()
        enabled = State()
        disabled = State()
        disabled.enabled = False
        notification = State()
        notification.notification = True
        self.states = [ ( 'enabled', enabled),
                        ( 'disabled', disabled),
                        ( 'notification', notification) ]

    def grab_widget_states( self, widget, suffix ):
        for state_name, state in self.states:
            widget.set_state( state )
            self.grab_widget( widget, suffix='%s_%s'%( suffix,
                                                       state_name ) )

    def test_action_push_botton( self ):
        from camelot.view.controls.action_widget import ActionPushButton
        widget = ActionPushButton( self.action,
                                   self.gui_context,
                                   self.parent )
        self.grab_widget_states( widget, 'application' )

    def test_hide_progress_dialog( self ):
        from camelot.view.action_runner import hide_progress_dialog
        dialog = self.gui_context.get_progress_dialog()
        dialog.show()
        with hide_progress_dialog(self.gui_context):
            self.assertTrue( dialog.isHidden() )
        self.assertFalse( dialog.isHidden() )

class ActionStepsCase(RunningThreadCase, GrabMixinCase, ExampleModelMixinCase, SerializableMixinCase):
    """Test the various steps that can be executed during an
    action.
    """

    images_path = test_view.static_images_path

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thread.post(cls.setup_sample_model)
        cls.thread.post(cls.load_example_data)
        cls.process()

    @classmethod
    def tearDownClass(cls):
        cls.thread.post(cls.tear_down_sample_model)
        cls.process()
        super().tearDownClass()

    def setUp(self):
        super(ActionStepsCase, self).setUp()
        self.admin_route = app_admin.get_admin_route()
        self.workspace = DesktopWorkspace(self.admin_route, None)
        self.gui_context = self.workspace.gui_context

    def test_change_object( self ):
        from camelot.bin.meta import NewProjectOptions
        from camelot.view.action_steps.change_object import ChangeObject
        admin = app_admin.get_related_admin(NewProjectOptions)
        options = NewProjectOptions()
        options.name = 'Videostore'
        options.module = 'videostore'
        options.domain = 'example.com'
        change_object = ChangeObject(options, admin)
        dialog = change_object.render(self.gui_context)
        self.grab_widget( dialog )

    def test_select_file( self ):
        action_steps.SelectFile('Image Files (*.png *.jpg);;All Files (*)')

    def test_select_item( self ):
        from camelot.view.action_steps import SelectItem

        # begin select item
        class SendDocumentAction( Action ):

            def model_run( self, model_context ):
                methods = [ ('email', 'By E-mail'),
                            ('fax',   'By Fax'),
                            ('post',  'By postal mail') ]
                method = yield SelectItem( methods, value='email' )
                # handle sending of the document
                LOGGER.info('selected {}'.format(method))

        # end select item

        action = SendDocumentAction()
        for step in self.gui_run(action, self.gui_context):
            if isinstance(step, ActionStep):
                dialog = step.render()
                self.grab_widget(dialog)
        self.assertTrue(dialog)

    def test_edit_profile(self):
        from camelot.view.action_steps.profile import EditProfiles
        step = EditProfiles([], '')
        dialog = step.render(self.gui_context)
        dialog.show()
        self.grab_widget(dialog)

    def test_open_file( self ):
        stream = six.BytesIO(b'1, 2, 3, 4')
        open_stream = action_steps.OpenStream( stream, suffix='.csv' )
        self.assertTrue( six.text_type( open_stream ) )
        action_steps.OpenString( six.b('1, 2, 3, 4') )
        context = { 'columns':['width', 'height'],
                    'table':[[1,2],[3,4]] }
        action_steps.OpenJinjaTemplate( 'list.html', context )
        action_steps.WordJinjaTemplate( 'list.html', context )

    def test_update_progress( self ):
        update_progress = action_steps.UpdateProgress(
            20, 100, _('Importing data')
        )
        self.assertTrue( six.text_type( update_progress ) )
        # give the gui context a progress dialog, so it can be updated
        progress_dialog = self.gui_context.get_progress_dialog()
        update_progress.gui_run( self.gui_context )
        # now press the cancel button
        progress_dialog.cancel()
        with self.assertRaises( CancelRequest ):
            update_progress.gui_run( self.gui_context )

    def test_message_box( self ):
        step = action_steps.MessageBox('Hello World')
        dialog = step.render()
        dialog.show()
        self.grab_widget(dialog)

class ListActionsCase(
    RunningThreadCase,
    GrabMixinCase, ExampleModelMixinCase, QueryQStandardItemModelMixinCase):
    """Test the standard list actions.
    """

    images_path = test_view.static_images_path

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thread.post(cls.setup_sample_model)
        cls.thread.post(cls.load_example_data)
        cls.group_box_filter = list_filter.GroupBoxFilter(
            'last_name', exclusive=True
        )
        cls.combo_box_filter = list_filter.ComboBoxFilter('last_name')
        cls.process()

    @classmethod
    def tearDownClass(cls):
        cls.thread.post(cls.tear_down_sample_model)
        cls.process()
        super().tearDownClass()

    def setUp( self ):
        super(ListActionsCase, self).setUp()
        self.thread.post(self.session.close)
        self.process()
        self.admin = app_admin.get_related_admin(Person)
        self.thread.post(self.setup_proxy)
        self.process()
        self.admin_route = self.admin.get_admin_route()
        self.setup_item_model(self.admin_route, self.admin.get_name())
        self.movie_admin = app_admin.get_related_admin(Movie)
        # make sure the model has rows and header data
        self._load_data(self.item_model)
        table_view = tableview.TableView(ApplicationActionGuiContext(), self.admin_route)
        table_view.set_admin()
        table_view.table.setModel(self.item_model)
        # select the first row
        table_view.table.setCurrentIndex(self.item_model.index(0, 0))
        self.gui_context = table_view.gui_context
        self.gui_context.admin_route = self.admin_route
        self.model_context = self.gui_context.create_model_context()
        # create a model context
        self.example_folder = os.path.join( os.path.dirname(__file__), '..', 'camelot_example' )

    def tearDown( self ):
        Session().expunge_all()

    def test_gui_context( self ):
        self.assertTrue( isinstance( self.gui_context.copy(),
                                     list_action.ListActionGuiContext ) )
        model_context = self.gui_context.create_model_context()
        self.assertTrue( isinstance( model_context,
                                     list_action.ListActionModelContext ) )
        list( model_context.get_collection() )
        list( model_context.get_selection() )
        model_context.get_object()

    def test_change_row_actions( self ):
        from camelot.test.action import MockListActionGuiContext

        gui_context = MockListActionGuiContext()
        to_first = list_action.ToFirstRow()
        to_previous = list_action.ToPreviousRow()
        to_next = list_action.ToNextRow()
        to_last = list_action.ToLastRow()

        # the state does not change when the current row changes,
        # to make the actions usable in the main window toolbar
        to_last.gui_run( gui_context )
        #self.assertFalse( get_state( to_last ).enabled )
        #self.assertFalse( get_state( to_next ).enabled )
        to_previous.gui_run( gui_context )
        #self.assertTrue( get_state( to_last ).enabled )
        #self.assertTrue( get_state( to_next ).enabled )
        to_first.gui_run( gui_context )
        #self.assertFalse( get_state( to_first ).enabled )
        #self.assertFalse( get_state( to_previous ).enabled )
        to_next.gui_run( gui_context )
        #self.assertTrue( get_state( to_first ).enabled )
        #self.assertTrue( get_state( to_previous ).enabled )

    def test_print_preview(self):
        action = list_action.PrintPreview()
        for step in self.gui_run(action, self.gui_context):
            if isinstance(step, action_steps.PrintPreview):
                dialog = step.render(self.gui_context)
                dialog.show()
                self.grab_widget(dialog)
        self.assertTrue(dialog)

    def test_export_spreadsheet( self ):
        action = list_action.ExportSpreadsheet()
        for step in self.gui_run(action, self.gui_context):
            if isinstance(step, action_steps.OpenFile):
                filename = step.get_path()
        self.assertTrue(filename)
        # see if the generated file can be parsed
        openpyxl.load_workbook(filename)

    def test_save_restore_export_mapping(self):
        from camelot_example.model import Movie

        admin = app_admin.get_related_admin(Movie)

        settings = utils.get_settings(admin.get_admin_route()[-1])
        settings.beginGroup('export_mapping')
        # make sure there are no previous settings
        settings.remove('')

        save_export_mapping = list_action.SaveExportMapping(settings)
        restore_export_mapping = list_action.RestoreExportMapping(settings)

        model_context = MockModelContext()
        
        field_choices = [('field_{0}'.format(i), 'Field {0}'.format(i)) for i in range(10)]
        model_context.admin = import_utils.ColumnSelectionAdmin(
            admin,
            field_choices = field_choices
        )
        model_context.selection = [import_utils.ColumnMapping(0, [], 'field_1'),
                                   import_utils.ColumnMapping(1, [], 'field_2')]

        for step in save_export_mapping.model_run(model_context):
            if isinstance(step, action_steps.ChangeObject):
                options = step.get_object()
                options.name = 'mapping 1'

        stored_mappings = settings.beginReadArray('mappings')
        settings.endArray()
        self.assertTrue(stored_mappings)

        mappings = save_export_mapping.read_mappings()
        self.assertTrue('mapping 1' in mappings)
        self.assertEqual(mappings['mapping 1'], ['field_1', 'field_2'])

        model_context.selection =  [import_utils.ColumnMapping(0, [], 'field_3'),
                                   import_utils.ColumnMapping(1, [], 'field_4')]

        generator = restore_export_mapping.model_run(model_context)
        for step in generator:
            if isinstance(step, action_steps.SelectItem):
                generator.send('mapping 1')

        self.assertEqual(model_context.selection[0].field, 'field_1')

    def test_match_names(self):
        rows = [
            ['first_name', 'last_name'],
            ['Unknown',    'Unknown'],
        ]
        fields = [field for field, _fa in self.admin.get_columns()]
        mapping = ColumnMapping(0, rows)
        self.assertNotEqual(mapping.field, 'first_name' )
        
        match_names = MatchNames()
        model_context = MockModelContext()
        model_context.obj = mapping
        model_context.admin = ColumnMappingAdmin(
            self.admin,
            field_choices=[(f,f) for f in fields]
        )
        list(match_names.model_run(model_context))
        self.assertEqual(mapping.field, 'first_name')

    def test_import_from_xls_file( self ):
        with self.assertRaises(Exception) as ec:
            self.test_import_from_file('import_example.xls')
        self.assertIn('xls is not a supported', str(ec.exception))

    def test_import_from_xlsx_file( self ):
        self.test_import_from_file( 'import_example.xlsx' )

    def test_import_from_xlsx_formats( self ):
        reader = import_utils.XlsReader(os.path.join(
            self.example_folder, 'excel_formats_example.xlsx'
        ))
        rows = [row for row in reader]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(utils.string_from_string(row[0]), u'Test')
        self.assertEqual(utils.date_from_string(row[1]), datetime.date(2017,4,1))
        self.assertEqual(utils.int_from_string(row[2]), 234567)
        self.assertEqual(utils.float_from_string(row[3]), 3.15)
        self.assertEqual(utils.float_from_string(row[4]), 3.145)
        self.assertEqual(utils.bool_from_string(row[5]), True)
        self.assertEqual(utils.bool_from_string(row[6]), False)

    def test_import_from_file(self, filename='import_example.csv'):
        action = list_action.ImportFromFile()
        generator = self.gui_run(action, self.gui_context)
        for step in generator:
            if isinstance(step, action_steps.SelectFile):
                generator.send([os.path.join(self.example_folder, filename)])
            if isinstance(step, action_steps.ChangeObject):
                dialog = step.render(self.gui_context)
                dialog.show()
                self.grab_widget(dialog, suffix='column_selection')
            if isinstance(step, action_steps.ChangeObjects):
                dialog = step.render()
                dialog.show()
                self.grab_widget(dialog, suffix='preview')
            if isinstance(step, action_steps.MessageBox):
                dialog = step.render()
                dialog.show()
                self.grab_widget(dialog, suffix='confirmation')

    def test_replace_field_contents( self ):
        action = list_action.ReplaceFieldContents()
        steps = self.gui_run(action, self.gui_context)
        for step in steps:
            if isinstance(step, action_steps.ChangeField):
                dialog = step.render()
                field_editor = dialog.findChild(QtWidgets.QWidget, 'field_choice')
                field_editor.set_value('first_name')
                dialog.show()
                self.grab_widget( dialog )
                steps.send(('first_name', 'known'))

    def test_open_form_view( self ):
        # sort and filter the original model
        item_view = self.gui_context.item_view
        list_model = item_view.model()
        list_model.sort(1, Qt.DescendingOrder)
        list_model.timeout_slot()
        self.process()
        list_model.headerData(0, Qt.Vertical, ObjectRole)
        list_model.data(list_model.index(0, 0), Qt.DisplayRole)
        list_model.timeout_slot()
        self.process()
        self.gui_context.item_view.setCurrentIndex(list_model.index(0, 0))
        model_context = self.gui_context.create_model_context()
        open_form_view_action = list_action.OpenFormView()
        for step in open_form_view_action.model_run(model_context):
            form = step.render(self.gui_context)
            form_value = form.model.get_value()
        self.assertTrue(isinstance(form_value, ListModelProxy))

    @staticmethod
    def track_crud_steps(action, model_context):
        created = updated = None
        steps = []
        flushed = False
        for step in action.model_run(model_context):
            steps.append(type(step))
            if isinstance(step, action_steps.CreateObjects):
                created = step.objects_created if created is None else created.extend(step.objects_created)
            elif isinstance(step, action_steps.UpdateObjects):
                updated = step.objects_updated if updated is None else updated.extend(step.objects_updated)
        return steps, created, updated

    def test_duplicate_selection( self ):
        initial_row_count = self._row_count(self.item_model)
        action = list_action.DuplicateSelection()
        action.gui_run(self.gui_context)
        self.process()
        new_row_count = self._row_count(self.item_model)
        self.assertEqual(new_row_count, initial_row_count+1)
        person = Person(first_name='test', last_name='person')
        self.session.flush()
        model_context = MockModelContext(self.session)
        model_context.admin = self.admin
        model_context.proxy = self.admin.get_proxy([])

        # The action should only be applicable for a single selection.
        # So verify a UserException is raised when selecting multiple ...
        model_context.selection = [None, None]
        model_context.selection_count = 2
        with self.assertRaises(UserException) as exc:
            list(action.model_run(model_context))
        self.assertEqual(exc.exception.text, action.Message.no_single_selection.value) 
        # ...and selecting None has no side-effects.
        model_context.selection = []
        model_context.selection_count = 0
        steps, created, updated = self.track_crud_steps(action, model_context)
        self.assertIsNone(created)
        self.assertIsNone(updated)
        self.assertNotIn(action_steps.FlushSession, steps)

        # Verify the valid duplication of a single selection.
        model_context.selection = [person]
        model_context.selection_count = 1
        steps, created, updated = self.track_crud_steps(action, model_context)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(updated), 0)
        self.assertIn(action_steps.FlushSession, steps)
        copied_obj = created[0]
        self.assertEqual(copied_obj.first_name, person.first_name)
        self.assertEqual(copied_obj.last_name, person.last_name)

        # Verify in the case wherein the duplicated instance is invalid, its is not flushed yet and opened within its form.
        # Set custom validator that always fails to make sure duplicated instance is found to be invalid/
        validator = self.admin.validator
        class CustomValidator(EntityValidator):

            def validate_object(self, p):
                return ['some validation error']

        self.admin.validator = CustomValidator
        model_context.selection = [person]
        steps, created, updated = self.track_crud_steps(action, model_context)
        self.assertEqual(len(created), 1)
        self.assertIsNone(updated)
        self.assertIn(action_steps.OpenFormView, steps)
        self.assertNotIn(action_steps.FlushSession, steps)
        copied_obj = created[0]
        self.assertEqual(copied_obj.first_name, person.first_name)
        self.assertEqual(copied_obj.last_name, person.last_name)
        # Reinstated original validator to prevent intermingling with other test (cases).
        self.admin.validator = validator

    def test_delete_selection(self):
        selected_object = self.model_context.get_object()
        self.assertTrue(selected_object in self.session)
        delete_selection_action = list_action.DeleteSelection()
        delete_selection_action.gui_run( self.gui_context )
        self.process()
        self.assertFalse(selected_object in self.session)

    def test_add_existing_object(self):
        initial_row_count = self._row_count(self.item_model)
        action = list_action.AddExistingObject()
        steps = self.gui_run(action, self.gui_context)
        for step in steps:
            if isinstance(step, action_steps.SelectObjects):
                steps.send([Person(first_name='Unknown', last_name='Unknown')])
        new_row_count = self._row_count(self.item_model)
        self.assertEqual(new_row_count, initial_row_count+1)

    def test_add_new_object(self):
        add_new_object_action = list_action.AddNewObject()
        add_new_object_action.gui_run( self.gui_context )

    def test_remove_selection(self):
        remove_selection_action = list_action.RemoveSelection()
        list( remove_selection_action.model_run( self.gui_context.create_model_context() ) )

    def test_set_filters(self):
        set_filters = list_action.SetFilters()
        state = self.get_state(set_filters, self.gui_context)
        self.assertTrue(len(state.modes))
        mode_names = set(m.name for m in state.modes)
        self.assertIn('first_name', mode_names)
        self.assertNotIn('note', mode_names)
        set_filters.gui_run(self.gui_context)
        #steps = self.gui_run(set_filters, self.gui_context)
        #for step in steps:
            #if isinstance(step, action_steps.ChangeField):
                #steps.send(('first_name', 'test'))

    def test_group_box_filter(self):
        state = self.get_state(self.group_box_filter, self.gui_context)
        self.assertTrue(len(state.modes))
        widget = self.gui_context.view.render_action(self.group_box_filter, None)
        widget.set_state(state)
        self.assertTrue(len(widget.get_value()))
        widget.run_action()
        self.grab_widget(widget)

    def test_combo_box_filter(self):
        state = self.get_state(self.combo_box_filter, self.gui_context)
        self.assertTrue(len(state.modes))
        widget = self.gui_context.view.render_action(self.combo_box_filter, None)
        widget.set_state(state)
        self.assertTrue(len(widget.get_value()))
        widget.run_action()
        self.grab_widget(widget)

    def test_filter_list(self):
        action_box = actionsbox.ActionsBox(None)
        for action in [self.group_box_filter,
                       self.combo_box_filter]:
            action_widget = self.gui_context.view.render_action(action, None)
            action_box.layout().addWidget(action_widget)
        self.grab_widget(action_box)
        return action_box

    def test_filter_list_in_table_view(self):
        from camelot.view.controls.tableview import TableView
        from camelot.model.party import Person
        from camelot.admin.action.base import GuiContext
        gui_context = GuiContext()
        gui_context.action_routes = {}
        person_admin = Person.Admin(app_admin, Person)
        table_view = TableView(gui_context, person_admin.get_admin_route())
        table_view.set_filters([self.group_box_filter,
                                self.combo_box_filter])

    def test_orm( self ):

        class UpdatePerson( Action ):

            verbose_name = _('Update person')

            def model_run( self, model_context ):
                for person in model_context.get_selection():
                    soc_number = person.social_security_number
                    if soc_number:
                        # assume the social sec number contains the birth date
                        person.birth_date = datetime.date( int(soc_number[0:4]),
                                                           int(soc_number[4:6]),
                                                           int(soc_number[6:8])
                                                           )
                    # delete the email of the person
                    for contact_mechanism in person.contact_mechanisms:
                        model_context.session.delete( contact_mechanism )
                        yield action_steps.DeleteObjects((contact_mechanism,))
                    # add a new email
                    m = ('email', '%s.%s@example.com'%( person.first_name,
                                                        person.last_name ) )
                    cm = party.ContactMechanism( mechanism = m )
                    pcm = party.PartyContactMechanism( party = person,
                                                       contact_mechanism = cm )
                    # immediately update the GUI
                    yield action_steps.CreateObjects((cm,))
                    yield action_steps.CreateObjects((pcm,))
                    yield action_steps.UpdateObjects((person,))
                # flush the session on finish
                model_context.session.flush()

        # end manual update

        action_step = None
        update_person = UpdatePerson()
        for step in self.gui_run(update_person, self.gui_context):
            if isinstance(step, ActionStep):
                action_step = step
                action_step.gui_run(self.gui_context)
        self.assertTrue(action_step)

        # begin auto update

        class UpdatePerson( Action ):

            verbose_name = _('Update person')

            def model_run( self, model_context ):
                for person in model_context.get_selection():
                    soc_number = person.social_security_number
                    if soc_number:
                        # assume the social sec number contains the birth date
                        person.birth_date = datetime.date( int(soc_number[0:4]),
                                                           int(soc_number[4:6]),
                                                           int(soc_number[6:8])
                                                           )
                        # delete the email of the person
                        for contact_mechanism in person.contact_mechanisms:
                            model_context.session.delete( contact_mechanism )
                        # add a new email
                        m = ('email', '%s.%s@example.com'%( person.first_name,
                                                            person.last_name ) )
                        cm = party.ContactMechanism( mechanism = m )
                        party.PartyContactMechanism( party = person,
                                                    contact_mechanism = cm )
                # flush the session on finish and update the GUI
                yield action_steps.FlushSession( model_context.session )

        # end auto update

        action_step = None
        update_person = UpdatePerson()
        for step in self.gui_run(update_person, self.gui_context):
            if isinstance(step, ActionStep):
                action_step = step
                action_step.gui_run(self.gui_context)
        self.assertTrue(action_step)

    def test_print_html( self ):

        # begin html print
        class PersonSummary(Action):

            verbose_name = _('Summary')

            def model_run(self, model_context):
                from camelot.view.action_steps import PrintHtml
                person = model_context.get_object()
                yield PrintHtml("<h1>This will become the personal report of {}!</h1>".format(person))
        # end html print

        action = PersonSummary()
        steps = list(self.gui_run(action, self.gui_context))
        dialog = steps[0].render(self.gui_context)
        dialog.show()
        self.grab_widget(dialog)

class FormActionsCase(
    RunningThreadCase,
    ExampleModelMixinCase, GrabMixinCase, QueryQStandardItemModelMixinCase):
    """Test the standard list actions.
    """

    images_path = test_view.static_images_path

    @classmethod
    def setUpClass(cls):
        super(FormActionsCase, cls).setUpClass()
        cls.thread.post(cls.setup_sample_model)
        cls.thread.post(cls.load_example_data)
        cls.process()

    @classmethod
    def tearDownClass(cls):
        cls.thread.post(cls.tear_down_sample_model)
        cls.process()
        super().tearDownClass()

    def setUp( self ):
        super(FormActionsCase, self).setUp()
        self.thread.post(self.setup_proxy)
        self.process()
        person_admin = app_admin.get_related_admin(Person)
        self.admin_route = person_admin.get_admin_route()
        self.setup_item_model(self.admin_route, person_admin.get_name())
        self.gui_context = form_action.FormActionGuiContext()
        self.gui_context._model = self.item_model
        self.gui_context.widget_mapper = QtWidgets.QDataWidgetMapper()
        self.gui_context.widget_mapper.setModel(self.item_model)
        self.gui_context.admin_route = self.admin_route
        self.gui_context.admin = person_admin

    def tearDown(self):
        super().tearDown()

    def test_gui_context( self ):
        self.assertTrue( isinstance( self.gui_context.copy(),
                                     form_action.FormActionGuiContext ) )
        self.assertTrue( isinstance( self.gui_context.create_model_context(),
                                     form_action.FormActionModelContext ) )

    def test_previous_next( self ):
        previous_action = form_action.ToPreviousForm()
        list(self.gui_run(previous_action, self.gui_context))
        next_action = form_action.ToNextForm()
        list(self.gui_run(next_action, self.gui_context))
        first_action = form_action.ToFirstForm()
        list(self.gui_run(first_action, self.gui_context))
        last_action = form_action.ToLastForm()
        list(self.gui_run(last_action, self.gui_context))

    def test_show_history( self ):
        show_history_action = form_action.ShowHistory()
        list(self.gui_run(show_history_action, self.gui_context))

    def test_close_form( self ):
        close_form_action = form_action.CloseForm()
        list(self.gui_run(close_form_action, self.gui_context))

class ApplicationCase(RunningThreadCase, GrabMixinCase, ExampleModelMixinCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thread.post(cls.setup_sample_model)
        cls.thread.post(cls.load_example_data)
        cls.process()

    @classmethod
    def tearDownClass(cls):
        cls.thread.post(cls.tear_down_sample_model)
        cls.process()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.gui_context = ApplicationActionGuiContext()
        self.admin_route = app_admin.get_admin_route()

    def tearDown(self):
        super().tearDown()

    def test_application(self):
        app = Application(app_admin)
        list(self.gui_run(app, self.gui_context))

    def test_custom_application(self):

        # begin custom application
        class CustomApplication(Application):
        
            def model_run( self, model_context ):
                from camelot.view import action_steps
                yield action_steps.UpdateProgress(text='Starting up')
        # end custom application

        application = CustomApplication(app_admin)
        list(self.gui_run(application, self.gui_context))

class ApplicationActionsCase(
    RunningThreadCase, GrabMixinCase, ExampleModelMixinCase
    ):
    """Test application actions.
    """

    images_path = test_view.static_images_path

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thread.post(cls.setup_sample_model)
        cls.thread.post(cls.load_example_data)
        cls.process()

    @classmethod
    def tearDownClass(cls):
        cls.thread.post(cls.tear_down_sample_model)
        cls.process()
        super().tearDownClass()

    def setUp(self):
        super( ApplicationActionsCase, self ).setUp()
        from camelot.view.workspace import DesktopWorkspace
        self.context = MockModelContext(session=self.session)
        self.context.admin = app_admin
        self.admin_route = app_admin.get_admin_route()
        self.gui_context = application_action.ApplicationActionGuiContext()
        self.gui_context.admin_route = self.admin_route
        self.gui_context.workspace = DesktopWorkspace(self.admin_route, None)

    def test_refresh(self):
        refresh_action = application_action.Refresh()
        self.thread.post(self.dirty_session)
        self.process()
        #
        # refresh the session through the action
        #
        generator = self.gui_run(refresh_action, self.gui_context)
        for step in generator:
            if isinstance(step, action_steps.UpdateObjects):
                updates = step.get_objects()
        self.assertTrue(len(updates))

    def test_select_profile(self):
        from . import test_core
        profile_case = test_core.ProfileCase('setUp')
        profile_case.setUp()
        profile_store = profile_case.test_profile_store()
        action = application_action.SelectProfile(profile_store)
        generator = self.gui_run(action, self.gui_context)
        for step in generator:
            if isinstance(step, action_steps.SelectItem):
                generator.send(profile_store.get_last_profile())
                profile_selected = True
        self.assertTrue(profile_selected)

    def test_backup_and_restore( self ):
        backup_action = application_action.Backup()
        generator = self.gui_run(backup_action, self.gui_context)
        file_saved = False
        for step in generator:
            if isinstance(step, action_steps.SaveFile):
                generator.send('unittest-backup.db')
                file_saved = True
        self.assertTrue(file_saved)
        restore_action = application_action.Restore()
        generator = self.gui_run(restore_action, self.gui_context)
        file_selected = False
        for step in generator:
            if isinstance(step, action_steps.SelectFile):
                generator.send(['unittest-backup.db'])
                file_selected = True
        self.assertTrue(file_selected)

    def test_open_table_view(self):
        person_admin = app_admin.get_related_admin( Person )
        open_table_view_action = application_action.OpenTableView(person_admin)
        list(self.gui_run(open_table_view_action, self.gui_context))

    def test_open_new_view( self ):
        person_admin = app_admin.get_related_admin(Person)
        open_new_view_action = application_action.OpenNewView(person_admin)
        generator = self.gui_run(open_new_view_action, self.gui_context)
        for step in generator:
            if isinstance(step, action_steps.SelectSubclass):
                generator.send(person_admin)

    def test_change_logging( self ):
        change_logging_action = application_action.ChangeLogging()
        for step in change_logging_action.model_run(self.context):
            if isinstance( step, action_steps.ChangeObject ):
                step.get_object().level = logging.INFO

    def test_segmentation_fault( self ):
        segmentation_fault = application_action.SegmentationFault()
        list(self.gui_run(segmentation_fault, self.gui_context))
