'''GTK Apport user interface tests.'''

# Copyright (C) 2012 Canonical Ltd.
# Author: Evan Dandrea <evan.dandrea@canonical.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

import unittest
import tempfile
import sys
import os
import imp
import apport
import shutil
from gi.repository import GLib, Gtk
from apport import unicode_gettext as _
from mock import patch

import apport.crashdb_impl.memory

if os.environ.get('APPORT_TEST_LOCAL'):
    apport_gtk_path = 'gtk/apport-gtk'
else:
    apport_gtk_path = os.path.join(os.environ.get('APPORT_DATA_DIR', '/usr/share/apport'), 'apport-gtk')
GTKUserInterface = imp.load_source('', apport_gtk_path).GTKUserInterface

class T(unittest.TestCase):
    @classmethod
    def setUpClass(klass):
        r = apport.Report()
        r.add_os_info()
        klass.distro = r['DistroRelease']

    def setUp(self):
        self.report_dir = tempfile.mkdtemp()
        apport.fileutils.report_dir = self.report_dir

        saved = sys.argv[0]
        # Work around GTKUserInterface using basename to find the GtkBuilder UI
        # file.
        sys.argv[0] = apport_gtk_path
        self.app = GTKUserInterface()
        sys.argv[0] = saved

        # use in-memory crashdb
        self.app.crashdb = apport.crashdb_impl.memory.CrashDatabase(None, {})

        # test report
        self.app.report_file = os.path.join(self.report_dir, 'bash.crash')

        self.app.report = apport.Report()
        self.app.report['ExecutablePath'] = '/bin/bash'
        self.app.report['Signal'] = '11'
        self.app.report['CoreDump'] = ''
        with open(self.app.report_file, 'w') as f:
            self.app.report.write(f)

    def tearDown(self):
        shutil.rmtree(self.report_dir)

    def test_close_button(self):
        '''Clicking the close button on the window does not report the crash.'''

        self.app.w('send_error_report').set_active(True)
        def c(*args):
            self.app.w('dialog_crash_new').destroy()
        GLib.idle_add(c)
        result = self.app.ui_present_report_details(True)
        self.assertFalse(result['report'])

    def test_kernel_crash_layout(self):
        '''
        +-----------------------------------------------------------------+
        | [ logo] YourDistro has experienced an internal error.           |
        |                                                                 |
        |            [x] Send an error report to help fix this problem.   |
        |                                                                 |
        | [ Show Details ]                                   [ Continue ] |
        +-----------------------------------------------------------------+
        '''
        self.app.report['ProblemType'] = 'KernelCrash'
        GLib.idle_add(Gtk.main_quit)
        self.app.ui_present_report_details(True)
        self.assertEqual(self.app.w('title_label').get_text(),
            _('Sorry, %s has experienced an internal error.') % self.distro)
        send_error_report = self.app.w('send_error_report')
        self.assertTrue(send_error_report.get_property('visible'))
        self.assertTrue(send_error_report.get_active())
        self.assertTrue(self.app.w('show_details').get_property('visible'))
        self.assertTrue(self.app.w('continue_button').get_property('visible'))
        self.assertEqual(self.app.w('continue_button').get_label(),
                         _('Continue'))
        self.assertFalse(self.app.w('closed_button').get_property('visible'))
        self.assertFalse(self.app.w('subtitle_label').get_property('visible'))

    def test_package_crash_layout(self):
        '''
        +-----------------------------------------------------------------+
        | [ error  ] Sorry, a problem occurred while installing software. |
        |            Package: apport 1.2.3~0ubuntu1                       |
        |                                                                 |
        |            [x] Send an error report to help fix this problem.   |
        |                                                                 |
        | [ Show Details ]                                   [ Continue ] |
        +-----------------------------------------------------------------+
        '''
        self.app.report['ProblemType'] = 'Package'
        self.app.report['Package'] = 'apport 1.2.3~0ubuntu1'
        GLib.idle_add(Gtk.main_quit)
        self.app.ui_present_report_details(True)
        self.assertEqual(self.app.w('title_label').get_text(),
            _('Sorry, a problem occurred while installing software.'))
        send_error_report = self.app.w('send_error_report')
        self.assertTrue(send_error_report.get_property('visible'))
        self.assertTrue(send_error_report.get_active())
        self.assertTrue(self.app.w('show_details').get_property('visible'))
        self.assertTrue(self.app.w('continue_button').get_property('visible'))
        self.assertEqual(self.app.w('continue_button').get_label(),
                         _('Continue'))
        self.assertFalse(self.app.w('closed_button').get_property('visible'))
        self.assertTrue(self.app.w('subtitle_label').get_property('visible'))
        self.assertEqual(self.app.w('subtitle_label').get_text(),
                         _('Package: apport 1.2.3~0ubuntu1'))

    def test_regular_crash_layout(self):
        '''
        +-----------------------------------------------------------------+
        | [ apport ] The application Apport has closed unexpectedly.      |
        |                                                                 |
        |            [x] Send an error report to help fix this problem.   |
        |                                                                 |
        | [ Show Details ]                 [ Leave Closed ]  [ Relaunch ] |
        +-----------------------------------------------------------------+
        '''
        self.app.report['ProblemType'] = 'Crash'
        self.app.report['Package'] = 'apport 1.2.3~0ubuntu1'
        with tempfile.NamedTemporaryFile() as fp:
            fp.write('''[Desktop Entry]
Version=1.0
Name=Apport
Type=Application''')
            fp.flush()
            self.app.report['DesktopFile'] = fp.name
            GLib.idle_add(Gtk.main_quit)
            self.app.ui_present_report_details(True)
        self.assertEqual(self.app.w('title_label').get_text(),
            _('The application Apport has closed unexpectedly.'))
        send_error_report = self.app.w('send_error_report')
        self.assertTrue(send_error_report.get_property('visible'))
        self.assertTrue(send_error_report.get_active())
        self.assertTrue(self.app.w('show_details').get_property('visible'))
        self.assertTrue(self.app.w('continue_button').get_property('visible'))
        self.assertEqual(self.app.w('continue_button').get_label(),
                         _('Relaunch'))
        self.assertTrue(self.app.w('closed_button').get_property('visible'))
        self.assertFalse(self.app.w('subtitle_label').get_property('visible'))

    def test_system_crash_layout(self):
        '''
        +---------------------------------------------------------------+
        | [ logo ] Sorry, YourDistro has experienced an internal error. |
        |          If you notice further problems, try restarting the   |
        |          computer                                             |
        |                                                               |
        |            [x] Send an error report to help fix this problem. |
        |                                                               |
        | [ Show Details ]                                 [ Continue ] |
        +---------------------------------------------------------------+
        '''
        self.app.report['ProblemType'] = 'Crash'
        self.app.report['Package'] = 'bash 5'
        GLib.idle_add(Gtk.main_quit)
        self.app.ui_present_report_details(True)
        self.assertEqual(self.app.w('title_label').get_text(),
            _('Sorry, %s has experienced an internal error.') % self.distro)
        self.assertEqual(self.app.w('subtitle_label').get_text(),
            _('If you notice further problems, try restarting the computer.'))
        self.assertTrue(self.app.w('subtitle_label').get_property('visible'))
        send_error_report = self.app.w('send_error_report')
        self.assertTrue(send_error_report.get_property('visible'))
        self.assertTrue(send_error_report.get_active())
        self.assertTrue(self.app.w('show_details').get_property('visible'))
        self.assertTrue(self.app.w('continue_button').get_property('visible'))
        self.assertEqual(self.app.w('continue_button').get_label(),
                         _('Continue'))
        self.assertFalse(self.app.w('closed_button').get_property('visible'))

    def test_system_crash_from_console_layout(self):
        '''
        +-------------------------------------------------------------------+
        | [ ubuntu ] Sorry, the application apport has closed unexpectedly. |
        |            If you notice further problems, try restarting the     |
        |            computer                                               |
        |                                                                   |
        |            [x] Send an error report to help fix this problem.     |
        |                                                                   |
        | [ Show Details ]                                     [ Continue ] |
        +-------------------------------------------------------------------+
        '''
        self.app.report['ProblemType'] = 'Crash'
        self.app.report['Package'] = 'bash 5'
        self.app.report['ProcEnviron'] = ('LANGUAGE=en_GB:en\n'
                                      'SHELL=/bin/sh\n'
                                      'TERM=xterm')
        self.app.report['ExecutablePath'] = '/usr/bin/apport'
        # This will be set by apport/ui.py in load_report()
        self.app.cur_package = 'apport'
        GLib.idle_add(Gtk.main_quit)
        self.app.ui_present_report_details(True)
        self.assertEqual(self.app.w('title_label').get_text(),
            _('Sorry, the application apport has closed unexpectedly.'))
        self.assertEqual(self.app.w('subtitle_label').get_text(),
            _('If you notice further problems, try restarting the computer.'))
        self.assertTrue(self.app.w('subtitle_label').get_property('visible'))
        send_error_report = self.app.w('send_error_report')
        self.assertTrue(send_error_report.get_property('visible'))
        self.assertTrue(send_error_report.get_active())
        self.assertTrue(self.app.w('show_details').get_property('visible'))
        self.assertTrue(self.app.w('continue_button').get_property('visible'))
        self.assertEqual(self.app.w('continue_button').get_label(),
                         _('Continue'))
        self.assertFalse(self.app.w('closed_button').get_property('visible'))

        del self.app.report['ExecutablePath']
        GLib.idle_add(Gtk.main_quit)
        self.app.ui_present_report_details(True)
        self.assertEqual(self.app.w('title_label').get_text(),
            _('Sorry, apport has closed unexpectedly.'))

    @patch.object(GTKUserInterface, 'can_examine_locally')
    def test_examine_button(self, *args):
        '''
        +---------------------------------------------------------------------+
        | [ apport ] The application Apport has closed unexpectedly.          |
        |                                                                     |
        |            [x] Send an error report to help fix this problem.       |
        |                                                                     |
        | [ Show Details ] [ Examine locally ]  [ Leave Closed ] [ Relaunch ] |
        +---------------------------------------------------------------------+
        '''
        self.app.report['ProblemType'] = 'Crash'
        self.app.report['Package'] = 'bash 5'

        GLib.idle_add(Gtk.main_quit)
        self.app.can_examine_locally.return_value = False
        self.app.ui_present_report_details(True)
        self.assertFalse(self.app.w('examine').get_property('visible'))

        GLib.idle_add(self.app.w('examine').clicked)
        self.app.can_examine_locally.return_value = True
        result = self.app.ui_present_report_details(True)
        self.assertTrue(self.app.w('examine').get_property('visible'))
        self.assertTrue(result['examine'])

    def test_apport_bug_package_layout(self):
        '''
        +-------------------------------------------------------------------+
        | [ error  ] Send problem report to the developers?                 |
        |                                                                   |
        |            +----------------------------------------------------+ |
        |            | |> ApportVersion                                   | |
        |            | ...                                                | |
        |            +----------------------------------------------------+ |
        |                                                                   |
        | [ Cancel ]                                               [ Send ] |
        +-------------------------------------------------------------------+
        '''
        self.app.report_file = None
        GLib.idle_add(Gtk.main_quit)
        self.app.ui_present_report_details(True)
        self.assertEqual(self.app.w('title_label').get_text(),
            _('Send problem report to the developers?'))
        self.assertFalse(self.app.w('subtitle_label').get_property('visible'))
        send_error_report = self.app.w('send_error_report')
        self.assertFalse(send_error_report.get_property('visible'))
        self.assertTrue(send_error_report.get_active())
        self.assertFalse(self.app.w('show_details').get_property('visible'))
        self.assertTrue(self.app.w('continue_button').get_property('visible'))
        self.assertEqual(self.app.w('continue_button').get_label(),
                         _('Send'))
        self.assertFalse(self.app.w('closed_button').get_property('visible'))
        self.assertTrue(self.app.w('cancel_button').get_property('visible'))
        self.assertTrue(self.app.w('details_scrolledwindow').get_property('visible'))

    def test_administrator_disabled_reporting(self):
        GLib.idle_add(Gtk.main_quit)
        self.app.ui_present_report_details(False)
        send_error_report = self.app.w('send_error_report')
        self.assertFalse(send_error_report.get_property('visible'))
        self.assertFalse(send_error_report.get_active())

    @patch.object(GTKUserInterface, 'open_url')
    def test_crash_nodetails(self, *args):
        '''Crash report without showing details'''

        def cont(*args):
            if not self.app.w('continue_button').get_visible():
                return True
            self.app.w('continue_button').clicked()
            return False

        GLib.timeout_add_seconds(1, cont)
        self.app.run_crash(self.app.report_file)

        # we should have reported one crash
        self.assertEqual(self.app.crashdb.latest_id(), 0)
        r = self.app.crashdb.download(0)
        self.assertEqual(r['ProblemType'], 'Crash')
        self.assertEqual(r['ExecutablePath'], '/bin/bash')

        # data was collected
        self.assertTrue(r['Package'].startswith('bash '))
        self.assertTrue('libc' in r['Dependencies'])
        self.assertTrue('Stacktrace' in r)

        # URL was opened
        self.assertEqual(self.app.open_url.call_count, 1)

    @patch.object(GTKUserInterface, 'open_url')
    def test_crash_details(self, *args):
        '''Crash report with showing details'''

        def show_details(*args):
            if not self.app.w('show_details').get_visible():
                return True
            self.app.w('show_details').clicked()
            GLib.timeout_add(200, cont)
            return False

        def cont(*args):
            # wait until data collection is done and tree filled
            if  self.app.tree_model.get_iter_first() is None:
                return True

            self.assertTrue(self.app.w('continue_button').get_visible())
            self.app.w('continue_button').clicked()
            return False

        GLib.timeout_add(200, show_details)
        self.app.run_crash(self.app.report_file)

        # we should have reported one crash
        self.assertEqual(self.app.crashdb.latest_id(), 0)
        r = self.app.crashdb.download(0)
        self.assertEqual(r['ProblemType'], 'Crash')
        self.assertEqual(r['ExecutablePath'], '/bin/bash')

        # data was collected
        self.assertTrue(r['Package'].startswith('bash '))
        self.assertTrue('libc' in r['Dependencies'])
        self.assertTrue('Stacktrace' in r)

        # URL was opened
        self.assertEqual(self.app.open_url.call_count, 1)

    def test_bug_report_installed_package(self):
        '''Bug report for installed package'''

        self.app.report_file = None
        self.app.options.package = 'bash'
        def c(*args):
            if not self.app.w('cancel_button').get_visible():
                return True
            self.app.w('cancel_button').clicked()
            return False
        GLib.timeout_add_seconds(1, c)
        self.app.run_report_bug()

        self.assertEqual(self.app.report['ProblemType'], 'Bug')
        self.assertEqual(self.app.report['SourcePackage'], 'bash')
        self.assertTrue(self.app.report['Package'].startswith('bash '))
        self.assertNotEqual(self.app.report['Dependencies'], '')

    def test_bug_report_uninstalled_package(self):
        '''Bug report for uninstalled package'''

        pkg = apport.packaging.get_uninstalled_package()

        self.app.report_file = None
        self.app.options.package = pkg
        def c(*args):
            if not self.app.w('cancel_button').get_visible():
                return True
            self.app.w('cancel_button').clicked()
            return False
        GLib.timeout_add_seconds(1, c)
        self.app.run_report_bug()

        self.assertEqual(self.app.report['ProblemType'], 'Bug')
        self.assertEqual(self.app.report['SourcePackage'],
                apport.packaging.get_source(pkg))
        self.assertEqual(self.app.report['Package'], '%s (not installed)' % pkg)

    @patch.object(GTKUserInterface, 'get_desktop_entry')
    def test_missing_icon(self, *args):
        # LP: 937354
        self.app.report['ProblemType'] = 'Crash'
        self.app.report['Package'] = 'apport 1.2.3~0ubuntu1'
        self.app.get_desktop_entry.return_value.getIcon.return_value = 'nonexistent'
        self.app.get_desktop_entry.return_value.getName.return_value = 'apport'
        GLib.idle_add(Gtk.main_quit)
        self.app.ui_present_report_details(True)

    def test_resizing(self):
        '''Problem report window resizability and sizing.'''
        
        def show_details(data):
            if not self.app.w('show_details').get_visible():
                return True

            data['orig_size'] = self.app.w('dialog_crash_new').get_size()
            data['orig_resizable'] = self.app.w('dialog_crash_new').get_resizable()
            self.app.w('show_details').clicked()
            GLib.timeout_add(200, hide_details, data)
            return False

        def hide_details(data):
            # wait until data collection is done and tree filled
            if  self.app.tree_model.get_iter_first() is None:
                return True

            data['detail_size'] = self.app.w('dialog_crash_new').get_size()
            data['detail_resizable'] = self.app.w('dialog_crash_new').get_resizable()
            self.app.w('show_details').clicked()
            GLib.timeout_add(200, details_hidden, data)
            return False

        def details_hidden(data):
            # wait until data collection is done and tree filled
            if  self.app.w('details_scrolledwindow').get_visible():
                return True

            data['hidden_size'] = self.app.w('dialog_crash_new').get_size()
            data['hidden_resizable'] = self.app.w('dialog_crash_new').get_resizable()
            Gtk.main_quit()

        data = {}
        GLib.timeout_add(200, show_details, data)
        self.app.run_crash(self.app.report_file)

        # when showing details, dialog should get considerably bigger
        self.assertGreater(data['detail_size'][1], data['orig_size'][1] + 100)
       
        # when hiding details, original size should be restored
        self.assertEqual(data['orig_size'], data['hidden_size'])

        # should only be resizable in details mode
        self.assertFalse(data['orig_resizable'])
        self.assertTrue(data['detail_resizable'])
        self.assertFalse(data['hidden_resizable'])

unittest.main()