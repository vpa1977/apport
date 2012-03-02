import unittest, shutil, signal, tempfile, resource, pwd, time, os, sys
import subprocess, errno, glob

try:
    from cStringIO import StringIO
except ImportError:
    from io import StringIO

import apport.ui
from apport.ui import _
import apport.report
import problem_report
import apport.crashdb_impl.memory

class TestSuiteUserInterface(apport.ui.UserInterface):
    '''Concrete apport.ui.UserInterface suitable for automatic testing'''

    def __init__(self):
        # use our dummy crashdb
        self.crashdb_conf = tempfile.NamedTemporaryFile()
        self.crashdb_conf.write('''default = 'testsuite'
databases = {
    'testsuite': {
        'impl': 'memory',
        'bug_pattern_url': None
    }
}
''')
        self.crashdb_conf.flush()

        os.environ['APPORT_CRASHDB_CONF'] = self.crashdb_conf.name

        apport.ui.UserInterface.__init__(self)

        self.crashdb = apport.crashdb_impl.memory.CrashDatabase(None,
                {'dummy_data': 1})

        # state of progress dialogs
        self.ic_progress_active = False
        self.ic_progress_pulses = 0 # count the pulses
        self.upload_progress_active = False
        self.upload_progress_pulses = 0

        # these store the choices the ui_present_* calls do
        self.present_package_error_response = None
        self.present_kernel_error_response = None
        self.present_details_response = None
        self.question_yesno_response = None
        self.question_choice_response = None
        self.question_file_response = None

        self.opened_url = None
        self.present_details_shown = False

        self.clear_msg()

    def clear_msg(self):
        # last message box
        self.msg_title = None
        self.msg_text = None
        self.msg_severity = None # 'warning' or 'error'
        self.msg_choices = None

    def ui_present_report_details(self, is_update):
        self.present_details_shown = True
        return self.present_details_response

    def ui_info_message(self, title, text):
        self.msg_title = title
        self.msg_text = text
        self.msg_severity = 'info'

    def ui_error_message(self, title, text):
        self.msg_title = title
        self.msg_text = text
        self.msg_severity = 'error'

    def ui_start_info_collection_progress(self):
        self.ic_progress_pulses = 0
        self.ic_progress_active = True

    def ui_pulse_info_collection_progress(self):
        assert self.ic_progress_active
        self.ic_progress_pulses += 1

    def ui_stop_info_collection_progress(self):
        self.ic_progress_active = False

    def ui_start_upload_progress(self):
        self.upload_progress_pulses = 0
        self.upload_progress_active = True

    def ui_set_upload_progress(self, progress):
        assert self.upload_progress_active
        self.upload_progress_pulses += 1

    def ui_stop_upload_progress(self):
        self.upload_progress_active = False

    def open_url(self, url):
        self.opened_url = url

    def ui_question_yesno(self, text):
        self.msg_text = text
        return self.question_yesno_response

    def ui_question_choice(self, text, options, multiple):
        self.msg_text = text
        self.msg_choices = options
        return self.question_choice_response

    def ui_question_file(self, text):
        self.msg_text = text
        return self.question_file_response

class T(unittest.TestCase):
    def setUp(self):
        # we test a few strings, don't get confused by translations
        for v in ['LANG', 'LANGUAGE', 'LC_MESSAGES', 'LC_ALL']:
            try:
                del os.environ[v]
            except KeyError:
                pass

        self.orig_report_dir = apport.fileutils.report_dir
        apport.fileutils.report_dir = tempfile.mkdtemp()
        self.orig_symptom_script_dir = apport.ui.symptom_script_dir
        apport.ui.symptom_script_dir = tempfile.mkdtemp()
        self.orig_ignore_file = apport.report._ignore_file
        (fd, apport.report._ignore_file) = tempfile.mkstemp()
        os.close(fd)

        # need to do this to not break ui's ctor
        self.orig_argv = sys.argv
        sys.argv = ['ui-test']
        self.ui = TestSuiteUserInterface()

        # demo report
        self.report = apport.Report()
        self.report['ExecutablePath'] = '/bin/bash'
        self.report['Package'] = 'libfoo1 1-1'
        self.report['SourcePackage'] = 'foo'
        self.report['Foo'] = 'A' * 1000
        self.report['CoreDump'] = 'A' * 100000

        # write demo report into temporary file
        self.report_file = tempfile.NamedTemporaryFile()
        self.update_report_file()

        # set up our local hook directory
        self.hookdir = tempfile.mkdtemp()
        self.orig_hook_dir = apport.report._hook_dir
        apport.report._hook_dir = self.hookdir

        # test suite should not stumble over local packages
        os.environ['APPORT_IGNORE_OBSOLETE_PACKAGES'] = '1'
        os.environ['APPORT_DISABLE_DISTRO_CHECK'] = '1'

    def update_report_file(self):
        self.report_file.seek(0)
        self.report_file.truncate()
        self.report.write(self.report_file)
        self.report_file.flush()

    def tearDown(self):
        sys.argv = self.orig_argv
        shutil.rmtree(apport.fileutils.report_dir)
        apport.fileutils.report_dir = self.orig_report_dir
        self.orig_report_dir = None
        shutil.rmtree(apport.ui.symptom_script_dir)
        apport.ui.symptom_script_dir = self.orig_symptom_script_dir
        self.orig_symptom_script_dir = None

        os.unlink(apport.report._ignore_file)
        apport.report._ignore_file = self.orig_ignore_file

        self.ui = None
        self.report_file.close()

        self.assertEqual(subprocess.call(['pidof', '/bin/yes']), 1, 'no stray test processes')

        # clean up apport report from _gen_test_crash()
        for f in glob.glob('/var/crash/_usr_bin_yes.*.crash'):
            try:
                os.unlink(f)
            except OSError:
                pass

        shutil.rmtree(self.hookdir)
        apport.report._hook_dir = self.orig_hook_dir

    def test_format_filesize(self):
        '''format_filesize()'''

        self.assertEqual(self.ui.format_filesize(0), '0.0 KB')
        self.assertEqual(self.ui.format_filesize(2048), '2.0 KB')
        self.assertEqual(self.ui.format_filesize(2560), '2.6 KB')
        self.assertEqual(self.ui.format_filesize(999999), '1000.0 KB')
        self.assertEqual(self.ui.format_filesize(1000000), '1.0 MB')
        self.assertEqual(self.ui.format_filesize(2.7*1000000), '2.7 MB')
        self.assertEqual(self.ui.format_filesize(1024*1000000), '1.0 GB')
        self.assertEqual(self.ui.format_filesize(2560*1000000), '2.6 GB')

    def test_get_size_loaded(self):
        '''get_complete_size() and get_reduced_size() for loaded Reports'''

        self.ui.load_report(self.report_file.name)

        fsize = os.path.getsize(self.report_file.name)
        complete_ratio = float(self.ui.get_complete_size()) / fsize
        self.assertTrue(complete_ratio >= 0.99 and complete_ratio <= 1.01)

        rs = self.ui.get_reduced_size()
        self.assertTrue(rs > 1000)
        self.assertTrue(rs < 10000)

        # now add some information (e. g. from package hooks)
        self.ui.report['ExtraInfo'] = 'A' * 50000
        s = self.ui.get_complete_size()
        self.assertTrue(s >= fsize + 49900)
        self.assertTrue(s < fsize + 60000)

        rs = self.ui.get_reduced_size()
        self.assertTrue(rs > 51000)
        self.assertTrue(rs < 60000)

    def test_get_size_constructed(self):
        '''get_complete_size() and get_reduced_size() for on-the-fly Reports'''

        self.ui.report = apport.Report('Bug')
        self.ui.report['Hello'] = 'World'

        s = self.ui.get_complete_size()
        self.assertTrue(s > 5)
        self.assertTrue(s < 100)

        self.assertEqual(s, self.ui.get_reduced_size())

    def test_load_report(self):
        '''load_report()'''

        # valid report
        self.ui.load_report(self.report_file.name)
        self.assertEqual(self.ui.report, self.report)
        self.assertEqual(self.ui.msg_title, None)

        # report without Package
        del self.report['Package']
        del self.report['SourcePackage']
        del self.report['ExecutablePath']
        self.update_report_file()
        self.ui.load_report(self.report_file.name)

        self.assertTrue(self.ui.report == None)
        self.assertEqual(self.ui.msg_title, _('Invalid problem report'))
        self.assertEqual(self.ui.msg_severity, 'info')

        self.ui.clear_msg()

        # invalid base64 encoding
        self.report_file.seek(0)
        self.report_file.truncate()
        self.report_file.write('''Type: test
Package: foo 1-1
CoreDump: base64
bOgUs=
''')
        self.report_file.flush()

        self.ui.load_report(self.report_file.name)
        self.assertTrue(self.ui.report == None)
        self.assertEqual(self.ui.msg_title, _('Invalid problem report'))
        self.assertEqual(self.ui.msg_severity, 'error')

    def test_restart(self):
        '''restart()'''

        # test with only ProcCmdline
        p = os.path.join(apport.fileutils.report_dir, 'ProcCmdline')
        r = os.path.join(apport.fileutils.report_dir, 'Custom')
        self.report['ProcCmdline'] = 'touch ' + p
        self.update_report_file()
        self.ui.load_report(self.report_file.name)

        self.ui.restart()
        time.sleep(1) # FIXME: race condition
        self.assertTrue(os.path.exists(p))
        self.assertTrue(not os.path.exists(r))
        os.unlink(p)

        # test with RespawnCommand
        self.report['RespawnCommand'] = 'touch ' + r
        self.update_report_file()
        self.ui.load_report(self.report_file.name)

        self.ui.restart()
        time.sleep(1) # FIXME: race condition
        self.assertTrue(not os.path.exists(p))
        self.assertTrue(os.path.exists(r))
        os.unlink(r)

        # test that invalid command does not make us fall apart
        del self.report['RespawnCommand']
        self.report['ProcCmdline'] = '/nonexisting'
        self.update_report_file()
        self.ui.load_report(self.report_file.name)

    def test_collect_info_distro(self):
        '''collect_info() on report without information (distro bug)'''

        # report without any information (distro bug)
        self.ui.report = apport.Report()
        self.ui.collect_info()
        self.assertTrue(set(['Date', 'Uname', 'DistroRelease', 'ProblemType']).issubset(
            set(self.ui.report.keys())))
        self.assertEqual(self.ui.ic_progress_pulses, 0,
            'no progress dialog for distro bug info collection')

    def test_collect_info_exepath(self):
        '''collect_info() on report with only ExecutablePath'''

        # report with only package information
        self.report = apport.Report('Bug')
        self.report['ExecutablePath'] = '/bin/bash'
        self.update_report_file()
        self.ui.load_report(self.report_file.name)
        # add some tuple values, for robustness testing (might be added by
        # apport hooks)
        self.ui.report['Fstab'] = ('/etc/fstab', True)
        self.ui.report['CompressedValue'] = problem_report.CompressedValue('Test')
        self.ui.collect_info()
        self.assertTrue(set(['SourcePackage', 'Package', 'ProblemType',
            'Uname', 'Dependencies', 'DistroRelease', 'Date',
            'ExecutablePath']).issubset(set(self.ui.report.keys())))
        self.assertTrue(self.ui.ic_progress_pulses > 0,
            'progress dialog for package bug info collection')
        self.assertEqual(self.ui.ic_progress_active, False,
            'progress dialog for package bug info collection finished')

    def test_collect_info_package(self):
        '''collect_info() on report with a package'''

        # report with only package information
        self.ui.report = apport.Report('Bug')
        self.ui.cur_package = 'bash'
        self.ui.collect_info()
        self.assertTrue(set(['SourcePackage', 'Package', 'ProblemType',
            'Uname', 'Dependencies', 'DistroRelease',
            'Date']).issubset(set(self.ui.report.keys())))
        self.assertTrue(self.ui.ic_progress_pulses > 0,
            'progress dialog for package bug info collection')
        self.assertEqual(self.ui.ic_progress_active, False,
            'progress dialog for package bug info collection finished')

    def test_handle_duplicate(self):
        '''handle_duplicate()'''

        self.ui.load_report(self.report_file.name)
        self.assertEqual(self.ui.handle_duplicate(), False)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)

        demo_url = 'http://example.com/1'
        self.report['KnownReport'] = demo_url
        self.update_report_file()
        self.ui.load_report(self.report_file.name)
        self.assertEqual(self.ui.handle_duplicate(), True)
        self.assertEqual(self.ui.msg_severity, 'info')
        self.assertEqual(self.ui.opened_url, demo_url)

        self.ui.opened_url = None
        demo_url = 'http://example.com/1'
        self.report['KnownReport'] = '1'
        self.update_report_file()
        self.ui.load_report(self.report_file.name)
        self.assertEqual(self.ui.handle_duplicate(), True)
        self.assertEqual(self.ui.msg_severity, 'info')
        self.assertEqual(self.ui.opened_url, None)

    def test_run_nopending(self):
        '''running the frontend without any pending reports'''

        sys.argv = []
        self.ui = TestSuiteUserInterface()
        self.assertEqual(self.ui.run_argv(), False)

    def test_run_report_bug_noargs(self):
        '''run_report_bug() without specifying arguments'''

        sys.argv = ['ui-test', '-f']
        self.ui = TestSuiteUserInterface()
        self.assertEqual(self.ui.run_argv(), False)
        self.assertEqual(self.ui.msg_severity, 'error')

    def test_run_version(self):
        '''run_report_bug() as "ubuntu-bug" with version argument'''

        sys.argv = ['ubuntu-bug', '-v']
        self.ui = TestSuiteUserInterface()
        orig_stdout = sys.stdout
        sys.stdout = StringIO()
        self.assertEqual(self.ui.run_argv(), True)
        output = sys.stdout.getvalue()
        sys.stdout = orig_stdout
        self.assertEqual(output, apport.ui.__version__+"\n")

    def test_run_report_bug_package(self):
        '''run_report_bug() for a package'''

        sys.argv = ['ui-test', '-f', '-p', 'bash']
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.assertEqual(self.ui.run_argv(), True)

        self.assertEqual(self.ui.msg_severity, None)
        self.assertEqual(self.ui.msg_title, None)
        self.assertTrue(self.ui.present_details_shown)
        self.assertEqual(self.ui.opened_url, 'http://bash.bugs.example.com/%i' % self.ui.crashdb.latest_id())

        self.assertTrue(self.ui.ic_progress_pulses > 0)
        self.assertEqual(self.ui.report['SourcePackage'], 'bash')
        self.assertTrue('Dependencies' in self.ui.report.keys())
        self.assertTrue('ProcEnviron' in self.ui.report.keys())
        self.assertEqual(self.ui.report['ProblemType'], 'Bug')

        # should not crash on nonexisting package
        sys.argv = ['ui-test', '-f', '-p', 'nonexisting_gibberish']
        self.ui = TestSuiteUserInterface()
        self.ui.run_argv()

        self.assertEqual(self.ui.msg_severity, 'error')

    def test_run_report_bug_pid_tags(self):
        '''run_report_bug() for a pid with extra tags'''

        # fork a test process
        pid = os.fork()
        if pid == 0:
            os.dup2(os.open('/dev/null', os.O_WRONLY), sys.stdout.fileno())
            os.execv('/usr/bin/yes', ['yes'])
            assert False, 'Could not execute /usr/bin/yes'

        time.sleep(0.5)

        try:
            # report a bug on yes process
            sys.argv = ['ui-test', '-f', '--tag', 'foo', '-P', str(pid)]
            self.ui = TestSuiteUserInterface()
            self.ui.present_details_response = {'report': True,
                                                'blacklist': False,
                                                'examine' : False,
                                                'restart' : False }
            self.assertEqual(self.ui.run_argv(), True)
        finally:
            # kill test process
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)

        self.assertTrue('SourcePackage' in self.ui.report.keys())
        self.assertTrue('Dependencies' in self.ui.report.keys())
        self.assertTrue('ProcMaps' in self.ui.report.keys())
        self.assertEqual(self.ui.report['ExecutablePath'], '/usr/bin/yes')
        self.assertFalse('ProcCmdline' in self.ui.report) # privacy!
        self.assertTrue('ProcEnviron' in self.ui.report.keys())
        self.assertEqual(self.ui.report['ProblemType'], 'Bug')
        self.assertTrue('Tags' in self.ui.report.keys())
        self.assertTrue('foo' in self.ui.report['Tags'])

        self.assertEqual(self.ui.msg_severity, None)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, 'http://coreutils.bugs.example.com/%i' % self.ui.crashdb.latest_id())
        self.assertTrue(self.ui.present_details_shown)
        self.assertTrue(self.ui.ic_progress_pulses > 0)

    @classmethod
    def _find_unused_pid(klass):
        '''Find and return an unused PID'''

        pid = 1
        while True:
            pid += 1
            try:
                os.kill(pid, 0)
            except OSError as e:
                if e.errno == errno.ESRCH:
                    break
        return pid

    def test_run_report_bug_wrong_pid(self):
        '''run_report_bug() for a nonexisting pid'''

        # silently ignore missing PID; this happens when the user closes
        # the application prematurely
        pid = self._find_unused_pid()
        sys.argv = ['ui-test', '-f', '-P', str(pid)]
        self.ui = TestSuiteUserInterface()
        self.ui.run_argv()

    def test_run_report_bug_noperm_pid(self):
        '''run_report_bug() for a pid which runs as a different user'''

        restore_root = False
        if os.getuid() == 0:
            # temporarily drop to normal user "mail"
            os.setresuid(8, 8, -1)
            restore_root = True

        try:
            sys.argv = ['ui-test', '-f', '-P', '1']
            self.ui = TestSuiteUserInterface()
            self.ui.run_argv()

            self.assertEqual(self.ui.msg_severity, 'error')
        finally:
            if restore_root:
                os.setresuid(0, 0, -1)

    def test_run_report_bug_unpackaged_pid(self):
        '''run_report_bug() for a pid of an unpackaged program'''

        # create unpackaged test program
        (fd, exename) = tempfile.mkstemp()
        os.write(fd, open('/usr/bin/yes').read())
        os.close(fd)
        os.chmod(exename, 0o755)

        # unpackaged test process
        pid = os.fork()
        if pid == 0:
            os.dup2(os.open('/dev/null', os.O_WRONLY), sys.stdout.fileno())
            os.execv(exename, [exename])

        try:
            sys.argv = ['ui-test', '-f', '-P', str(pid)]
            self.ui = TestSuiteUserInterface()
            self.assertRaises(SystemExit, self.ui.run_argv)
        finally:
            os.kill(pid, signal.SIGKILL)
            os.wait()
            os.unlink(exename)

        self.assertEqual(self.ui.msg_severity, 'error')

    def test_run_report_bug_kernel_thread(self):
        '''run_report_bug() for a pid of a kernel thread'''

        pid = None
        for path in glob.glob('/proc/[0-9]*/stat'):
            stat = open(path).read().split()
            flags = int(stat[8])
            if flags & apport.ui.PF_KTHREAD:
                pid = int(stat[0])
                break

        self.assertFalse(pid is None)
        sys.argv = ['ui-test', '-f', '-P', str(pid)]
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_argv()

        self.assertTrue(self.ui.report['Package'].startswith(apport.packaging.get_kernel_package()))

    def test_run_report_bug_file(self):
        '''run_report_bug() with saving report into a file'''

        d = os.path.join(apport.fileutils.report_dir, 'home')
        os.mkdir(d)
        reportfile = os.path.join(d, 'bashisbad.apport')

        sys.argv = ['ui-test', '-f', '-p', 'bash', '--save', reportfile]
        self.ui = TestSuiteUserInterface()
        self.assertEqual(self.ui.run_argv(), True)

        self.assertEqual(self.ui.msg_severity, None)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertFalse(self.ui.present_details_shown)

        self.assertTrue(self.ui.ic_progress_pulses > 0)

        r = apport.Report()
        r.load(open(reportfile))

        self.assertEqual(r['SourcePackage'], 'bash')
        self.assertTrue('Dependencies' in r.keys())
        self.assertTrue('ProcEnviron' in r.keys())
        self.assertEqual(r['ProblemType'], 'Bug')

        # report it
        sys.argv = ['ui-test', '-c', reportfile]
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.assertEqual(self.ui.run_argv(), True)

        self.assertEqual(self.ui.msg_text, None)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertTrue(self.ui.present_details_shown)

    def _gen_test_crash(self):
        '''Generate a Report with real crash data'''

        # create a test executable
        test_executable = '/usr/bin/yes'
        assert os.access(test_executable, os.X_OK), test_executable + ' is not executable'
        pid = os.fork()
        if pid == 0:
            os.dup2(os.open('/dev/null', os.O_WRONLY), sys.stdout.fileno())
            sys.stdin.close()
            os.setsid()
            resource.setrlimit(resource.RLIMIT_CORE, (-1, -1))
            os.chdir(apport.fileutils.report_dir)
            os.execv(test_executable, [test_executable])
            assert False, 'Could not execute ' + test_executable

        time.sleep(0.5)

        # generate crash report
        r = apport.Report()
        r['ExecutablePath'] = test_executable
        r['Signal'] = '11'
        r.add_proc_info(pid)
        r.add_user_info()

        # generate a core dump
        coredump = os.path.join(apport.fileutils.report_dir, 'core')
        os.kill(pid, signal.SIGSEGV)
        os.waitpid(pid, 0)
        # Otherwise the core dump is empty.
        time.sleep(0.5)
        assert os.path.exists(coredump)
        r['CoreDump'] = (coredump,)

        return r

    def test_run_crash(self):
        '''run_crash()'''

        r = self._gen_test_crash()

        # write crash report
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')

        # cancel crash notification dialog
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': False,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertEqual(self.ui.ic_progress_pulses, 0)

        # report in crash notification dialog, send full report
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None, self.ui.msg_text)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, 'http://coreutils.bugs.example.com/%i' % self.ui.crashdb.latest_id())
        self.assertFalse(self.ui.ic_progress_active)
        self.assertNotEqual(self.ui.ic_progress_pulses, 0)
        self.assertTrue(self.ui.present_details_shown)

        self.assertTrue('SourcePackage' in self.ui.report.keys())
        self.assertTrue('Dependencies' in self.ui.report.keys())
        self.assertTrue('Stacktrace' in self.ui.report.keys())
        self.assertTrue('ProcEnviron' in self.ui.report.keys())
        self.assertFalse('ExecutableTimestamp' in self.ui.report.keys())
        self.assertFalse('StacktraceAddressSignature' in self.ui.report.keys())
        self.assertEqual(self.ui.report['ProblemType'], 'Crash')
        self.assertTrue(len(self.ui.report['CoreDump']) > 10000)
        self.assertTrue(self.ui.report['Title'].startswith('yes crashed with SIGSEGV'))

        # so far we did not blacklist, verify that
        self.assertTrue(not self.ui.report.check_ignored())

        # cancel crash notification dialog and blacklist
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': False,
                                            'blacklist': True,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertEqual(self.ui.ic_progress_pulses, 0)

        self.assertTrue(self.ui.report.check_ignored())

    def test_run_crash_abort(self):
        '''run_crash() for an abort() without assertion message'''

        r = self._gen_test_crash()
        r['Signal'] = '6'
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        r.write(open(report_file, 'w'))

        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None,  self.ui.msg_text)

        self.assertTrue('SourcePackage' in self.ui.report.keys())
        self.assertTrue('Dependencies' in self.ui.report.keys())
        self.assertTrue('Stacktrace' in self.ui.report.keys())
        self.assertTrue('ProcEnviron' in self.ui.report.keys())
        self.assertFalse('ExecutableTimestamp' in self.ui.report.keys())
        self.assertEqual(self.ui.report['Signal'], '6')

        # we disable the ABRT filtering, we want these crashes after all
        #self.assertTrue('assert' in self.ui.msg_text, '%s: %s' %
        #    (self.ui.msg_title, self.ui.msg_text))
        #self.assertEqual(self.ui.msg_severity, 'info')
        self.assertEqual(self.ui.msg_severity, None)
        self.assertTrue(self.ui.present_details_shown)

    def test_run_crash_broken(self):
        '''run_crash() for an invalid core dump'''

        # generate broken crash report
        r = apport.Report()
        r['ExecutablePath'] = '/usr/bin/yes'
        r['Signal'] = '11'
        r['CoreDump'] = problem_report.CompressedValue()
        r['CoreDump'].gzipvalue = 'AAAAAAAA'
        r.add_user_info()

        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        r.write(open(report_file, 'w'))

        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, 'error',  self.ui.msg_text)
        self.assertTrue('decompress' in self.ui.msg_text)
        self.assertTrue(self.ui.present_details_shown)

    def test_run_crash_argv_file(self):
        '''run_crash() through a file specified on the command line'''

        # valid
        self.report['Package'] = 'bash'
        self.update_report_file()

        sys.argv = ['ui-test', '-c', self.report_file.name]
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }

        self.assertEqual(self.ui.run_argv(), True)

        self.assertEqual(self.ui.msg_text, None)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertTrue(self.ui.present_details_shown)

        # unreportable
        self.report['Package'] = 'bash'
        self.report['UnreportableReason'] = u'It stinks. \u2665'
        self.update_report_file()

        sys.argv = ['ui-test', '-c', self.report_file.name]
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.assertEqual(self.ui.run_argv(), True)

        self.assertTrue('It stinks.' in self.ui.msg_text, '%s: %s' %
            (self.ui.msg_title, self.ui.msg_text))
        self.assertEqual(self.ui.msg_severity, 'info')

        # should not die with an exception on an invalid name
        sys.argv = ['ui-test', '-c', '/nonexisting.crash' ]
        self.ui = TestSuiteUserInterface()
        self.assertEqual(self.ui.run_argv(), True)
        self.assertEqual(self.ui.msg_severity, 'error')

    def test_run_crash_unreportable(self):
        '''run_crash() on a crash with the UnreportableReason field'''

        self.report['UnreportableReason'] = 'It stinks.'
        self.report['ExecutablePath'] = '/bin/bash'
        self.report['Package'] = 'bash 1'
        self.update_report_file()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }

        self.ui.run_crash(self.report_file.name)

        self.assertTrue('It stinks.' in self.ui.msg_text, '%s: %s' %
            (self.ui.msg_title, self.ui.msg_text))
        self.assertEqual(self.ui.msg_severity, 'info')

    def test_run_crash_ignore(self):
        '''run_crash() on a crash with the Ignore field'''
        self.report['Ignore'] = 'True'
        self.report['ExecutablePath'] = '/bin/bash'
        self.report['Package'] = 'bash 1'
        self.update_report_file()

        self.ui.run_crash(self.report_file.name)
        self.assertEqual(self.ui.msg_severity, None)

    def test_run_crash_nocore(self):
        '''run_crash() for a crash dump without CoreDump'''

        # create a test executable
        test_executable = '/usr/bin/yes'
        assert os.access(test_executable, os.X_OK), test_executable + ' is not executable'
        pid = os.fork()
        if pid == 0:
            os.setsid()
            os.dup2(os.open('/dev/null', os.O_WRONLY), sys.stdout.fileno())
            os.execv(test_executable, [test_executable])
            assert False, 'Could not execute ' + test_executable

        try:
            time.sleep(0.5)
            # generate crash report
            r = apport.Report()
            r['ExecutablePath'] = test_executable
            r['Signal'] = '42'
            r.add_proc_info(pid)
            r.add_user_info()
        finally:
            # kill test executable
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)

        # write crash report
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        r.write(open(report_file, 'w'))

        # run
        self.ui = TestSuiteUserInterface()
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, 'error')
        self.assertTrue('memory' in self.ui.msg_text, '%s: %s' %
            (self.ui.msg_title, self.ui.msg_text))

    def test_run_crash_preretraced(self):
        '''run_crash() pre-retraced reports.

        This happens with crashes which are pre-processed by
        apport-retrace.
        '''
        r = self._gen_test_crash()

        #  effect of apport-retrace -c
        r.add_gdb_info()
        del r['CoreDump']

        # write crash report
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')

        # report in crash notification dialog, cancel details report
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': False,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None, 'has %s message: %s: %s' % (
            self.ui.msg_severity, str(self.ui.msg_title), str(self.ui.msg_text)))
        self.assertEqual(self.ui.msg_title, None)
        self.assertTrue(self.ui.present_details_shown)

    def test_run_crash_precollected(self):
        '''run_crash() on complete report on uninstalled package

        This happens when reporting a problem from a different machine through
        copying a .crash file.
        '''
        self.ui.report = self._gen_test_crash()
        self.ui.collect_info()

        # now pretend to move it to a machine where the package is not
        # installed
        self.ui.report['Package'] = 'uninstalled_pkg 1'

        # write crash report
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        self.ui.report.write(open(report_file, 'w'))

        # report it
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.cur_package, 'uninstalled_pkg')
        self.assertEqual(self.ui.msg_severity, None, 'has %s message: %s: %s' % (
            self.ui.msg_severity, str(self.ui.msg_title), str(self.ui.msg_text)))
        self.assertTrue(self.ui.opened_url.startswith('http://coreutils.bugs.example.com'))
        self.assertTrue(self.ui.present_details_shown)

    def test_run_crash_errors(self):
        '''run_crash() on various error conditions'''

        # crash report with invalid Package name
        r = apport.Report()
        r['ExecutablePath'] = '/bin/bash'
        r['Package'] = 'foobarbaz'
        r['SourcePackage'] = 'foobarbaz'
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        r.write(open(report_file, 'w'))

        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)

        self.assertEqual(self.ui.msg_title, _('Invalid problem report'))
        self.assertEqual(self.ui.msg_severity, 'error')

    def test_run_crash_uninstalled(self):
        '''run_crash() on reports with subsequently uninstalled packages'''

        # program got uninstalled between crash and report
        r = self._gen_test_crash()
        r['ExecutablePath'] = '/bin/nonexisting'
        r['Package'] = 'bash'
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        r.write(open(report_file, 'w'))

        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)

        self.assertEqual(self.ui.msg_title, _('Invalid problem report'))
        self.assertEqual(self.ui.msg_severity, 'info')

        # interpreted program got uninstalled between crash and report
        r = apport.Report()
        r['ExecutablePath'] = '/bin/nonexisting'
        r['InterpreterPath'] = '/usr/bin/python'
        r['Traceback'] = 'ZeroDivisionError: integer division or modulo by zero'

        self.ui.run_crash(report_file)

        self.assertEqual(self.ui.msg_title, _('Invalid problem report'))
        self.assertEqual(self.ui.msg_severity, 'info')

        # interpreter got uninstalled between crash and report
        r = apport.Report()
        r['ExecutablePath'] = '/bin/sh'
        r['InterpreterPath'] = '/usr/bin/nonexisting'
        r['Traceback'] = 'ZeroDivisionError: integer division or modulo by zero'

        self.ui.run_crash(report_file)

        self.assertEqual(self.ui.msg_title, _('Invalid problem report'))
        self.assertEqual(self.ui.msg_severity, 'info')

    def test_run_crash_updated_binary(self):
        '''run_crash() on binary that got updated in the meantime'''

        r = self._gen_test_crash()
        r['ExecutableTimestamp'] = str(int(r['ExecutableTimestamp'])-10)
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        r.write(open(report_file, 'w'))

        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)

        self.assertFalse('ExecutableTimestamp' in self.ui.report)
        self.assertTrue(self.ui.report['ExecutablePath'] in self.ui.msg_text, '%s: %s' %
            (self.ui.msg_title, self.ui.msg_text))
        self.assertTrue('changed' in self.ui.msg_text, '%s: %s' %
            (self.ui.msg_title, self.ui.msg_text))
        self.assertEqual(self.ui.msg_severity, 'info')

    def test_run_crash_package(self):
        '''run_crash() for a package error'''

        # generate crash report
        r = apport.Report('Package')
        r['Package'] = 'bash'
        r['SourcePackage'] = 'bash'
        r['ErrorMessage'] = 'It broke'
        r['VarLogPackagerlog'] = 'foo\nbar'
        r.add_os_info()

        # write crash report
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')

        # cancel crash notification dialog
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': False,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertEqual(self.ui.ic_progress_pulses, 0)
        self.assertTrue(self.ui.present_details_shown)

        # report in crash notification dialog, send report
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, 'http://bash.bugs.example.com/%i' % self.ui.crashdb.latest_id())
        self.assertTrue(self.ui.present_details_shown)

        self.assertTrue('SourcePackage' in self.ui.report.keys())
        self.assertTrue('Package' in self.ui.report.keys())
        self.assertEqual(self.ui.report['ProblemType'], 'Package')

        # verify that additional information has been collected
        self.assertTrue('Architecture' in self.ui.report.keys())
        self.assertTrue('DistroRelease' in self.ui.report.keys())
        self.assertTrue('Uname' in self.ui.report.keys())

    def test_run_crash_kernel(self):
        '''run_crash() for a kernel error'''

        # set up hook
        f = open(os.path.join(self.hookdir, 'source_linux.py'), 'w')
        f.write('''def add_info(report, ui):
    report['KernelDebug'] = 'LotsMoreInfo'
''')
        f.close()

        # generate crash report
        r = apport.Report('KernelCrash')
        r['Package'] = apport.packaging.get_kernel_package()
        r['SourcePackage'] = 'linux'

        # write crash report
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')

        # cancel crash notification dialog
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': False,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None, 'error: %s - %s' %
            (self.ui.msg_title, self.ui.msg_text))
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertEqual(self.ui.ic_progress_pulses, 0)
        self.assertTrue(self.ui.present_details_shown)

        # report in crash notification dialog, send report
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None, str(self.ui.msg_title) +
            ' ' + str(self.ui.msg_text))
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, 'http://linux.bugs.example.com/%i' % self.ui.crashdb.latest_id())
        self.assertTrue(self.ui.present_details_shown)

        self.assertTrue('SourcePackage' in self.ui.report.keys())
        # did we run the hooks properly?
        self.assertTrue('KernelDebug' in self.ui.report.keys())
        self.assertEqual(self.ui.report['ProblemType'], 'KernelCrash')

    def test_run_crash_anonymity(self):
        '''run_crash() anonymization'''

        r = self._gen_test_crash()
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        r.write(open(report_file, 'w'))
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.msg_severity, None,  self.ui.msg_text)

        self.assertFalse('ProcCwd' in self.ui.report)

        dump = StringIO()
        self.ui.report.write(dump)

        p = pwd.getpwuid(os.getuid())
        bad_strings = [os.uname()[1], p[0], p[4], p[5], os.getcwd()]

        for s in bad_strings:
            self.assertFalse(s in dump.getvalue(), 'dump contains sensitive string: %s' % s)

    def test_run_crash_known(self):
        '''run_crash() for already known problem'''

        r = self._gen_test_crash()
        report_file = os.path.join(apport.fileutils.report_dir, 'test.crash')
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }

        # known without URL
        with open(report_file, 'w') as f:
            r.write(f)
        self.ui.crashdb.known = lambda r: True
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.report['KnownReport'], '1')
        self.assertEqual(self.ui.msg_severity, 'info')
        self.assertEqual(self.ui.opened_url, None)

        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        # known with URL
        with open(report_file, 'w') as f:
            r.write(f)
        self.ui.crashdb.known = lambda r: 'http://myreport/1'
        self.ui.run_crash(report_file)
        self.assertEqual(self.ui.report['KnownReport'], 'http://myreport/1')
        self.assertEqual(self.ui.msg_severity, 'info')
        self.assertEqual(self.ui.opened_url, 'http://myreport/1')

    def test_run_update_report_nonexisting_package_from_bug(self):
        '''run_update_report() on a nonexisting package (from bug)'''

        sys.argv = ['ui-test', '-u', '1']
        self.ui = TestSuiteUserInterface()

        self.assertEqual(self.ui.run_argv(), False)
        self.assertTrue('No additional information collected.' in
                self.ui.msg_text)
        self.assertFalse(self.ui.present_details_shown)

    def test_run_update_report_nonexisting_package_cli(self):
        '''run_update_report() on a nonexisting package (CLI argument)'''

        sys.argv = ['ui-test', '-u', '1', '-p', 'bar']
        self.ui = TestSuiteUserInterface()

        self.assertEqual(self.ui.run_argv(), False)
        self.assertTrue('No additional information collected.' in
                self.ui.msg_text)
        self.assertFalse(self.ui.present_details_shown)

    def test_run_update_report_existing_package_from_bug(self):
        '''run_update_report() on an existing package (from bug)'''

        sys.argv = ['ui-test', '-u', '1']
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }

        self.ui.crashdb.download(1)['SourcePackage'] = 'bash'
        self.ui.crashdb.download(1)['Package'] = 'bash'
        self.assertEqual(self.ui.run_argv(), True)
        self.assertEqual(self.ui.msg_severity, None, self.ui.msg_text)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertTrue(self.ui.present_details_shown)

        self.assertTrue(self.ui.ic_progress_pulses > 0)
        self.assertTrue(self.ui.report['Package'].startswith('bash '))
        self.assertTrue('Dependencies' in self.ui.report.keys())
        self.assertTrue('ProcEnviron' in self.ui.report.keys())

    def test_run_update_report_existing_package_cli_tags(self):
        '''run_update_report() on an existing package (CLI argument) with extra tag'''

        sys.argv = ['ui-test', '-u', '1', '-p', 'bash', '--tag', 'foo']
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }

        self.assertEqual(self.ui.run_argv(), True)
        self.assertEqual(self.ui.msg_severity, None, self.ui.msg_text)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertTrue(self.ui.present_details_shown)

        self.assertTrue(self.ui.ic_progress_pulses > 0)
        self.assertTrue(self.ui.report['Package'].startswith('bash '))
        self.assertTrue('Dependencies' in self.ui.report.keys())
        self.assertTrue('ProcEnviron' in self.ui.report.keys())
        self.assertTrue('foo' in self.ui.report['Tags'])

    def test_run_update_report_existing_package_cli_cmdname(self):
        '''run_update_report() on an existing package (-collect program)'''

        sys.argv = ['apport-collect', '-p', 'bash', '1']
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }

        self.assertEqual(self.ui.run_argv(), True)
        self.assertEqual(self.ui.msg_severity, None, self.ui.msg_text)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertTrue(self.ui.present_details_shown)

        self.assertTrue(self.ui.ic_progress_pulses > 0)
        self.assertTrue(self.ui.report['Package'].startswith('bash '))
        self.assertTrue('Dependencies' in self.ui.report.keys())
        self.assertTrue('ProcEnviron' in self.ui.report.keys())

    def test_run_update_report_noninstalled_but_hook(self):
        '''run_update_report() on an uninstalled package with a source hook'''

        sys.argv = ['ui-test', '-u', '1']
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }

        f = open(os.path.join(self.hookdir, 'source_foo.py'), 'w')
        f.write('def add_info(r, ui):\n  r["MachineType"]="Laptop"\n')
        f.close()

        self.assertEqual(self.ui.run_argv(), True, self.ui.report)
        self.assertEqual(self.ui.msg_severity, None, self.ui.msg_text)
        self.assertEqual(self.ui.msg_title, None)
        self.assertEqual(self.ui.opened_url, None)
        self.assertTrue(self.ui.present_details_shown)

        self.assertTrue(self.ui.ic_progress_pulses > 0)
        self.assertEqual(self.ui.report['Package'], 'foo (not installed)')
        self.assertEqual(self.ui.report['MachineType'], 'Laptop')
        self.assertTrue('ProcEnviron' in self.ui.report.keys())

    def _run_hook(self, code):
        f = open(os.path.join(self.hookdir, 'coreutils.py'), 'w')
        f.write('def add_info(report, ui):\n%s\n' %
                '\n'.join(['    ' + l for l in code.splitlines()]))
        f.close()
        self.ui.options.package = 'coreutils'
        self.ui.run_report_bug()

    def test_interactive_hooks_information(self):
        '''interactive hooks: HookUI.information()'''

        self.ui.present_details_response = {'report': False,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self._run_hook('''report['begin'] = '1'
ui.information('InfoText')
report['end'] = '1'
''')
        self.assertEqual(self.ui.report['begin'], '1')
        self.assertEqual(self.ui.report['end'], '1')
        self.assertEqual(self.ui.msg_text, 'InfoText')

    def test_interactive_hooks_yesno(self):
        '''interactive hooks: HookUI.yesno()'''

        self.ui.present_details_response = {'report': False,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.question_yesno_response = True
        self._run_hook('''report['begin'] = '1'
report['answer'] = str(ui.yesno('YesNo?'))
report['end'] = '1'
''')
        self.assertEqual(self.ui.report['begin'], '1')
        self.assertEqual(self.ui.report['end'], '1')
        self.assertEqual(self.ui.msg_text, 'YesNo?')
        self.assertEqual(self.ui.report['answer'], 'True')

        self.ui.question_yesno_response = False
        self.ui.run_report_bug()
        self.assertEqual(self.ui.report['answer'], 'False')
        self.assertEqual(self.ui.report['end'], '1')

        self.ui.question_yesno_response = None
        self.ui.run_report_bug()
        self.assertEqual(self.ui.report['answer'], 'None')
        self.assertEqual(self.ui.report['end'], '1')

    def test_interactive_hooks_file(self):
        '''interactive hooks: HookUI.file()'''

        self.ui.present_details_response = {'report': False,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.question_file_response = '/etc/fstab'
        self._run_hook('''report['begin'] = '1'
report['answer'] = str(ui.file('YourFile?'))
report['end'] = '1'
''')
        self.assertEqual(self.ui.report['begin'], '1')
        self.assertEqual(self.ui.report['end'], '1')
        self.assertEqual(self.ui.msg_text, 'YourFile?')
        self.assertEqual(self.ui.report['answer'], '/etc/fstab')

        self.ui.question_file_response = None
        self.ui.run_report_bug()
        self.assertEqual(self.ui.report['answer'], 'None')
        self.assertEqual(self.ui.report['end'], '1')

    def test_interactive_hooks_choices(self):
        '''interactive hooks: HookUI.choice()'''

        self.ui.present_details_response = {'report': False,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.question_choice_response = [1]
        self._run_hook('''report['begin'] = '1'
report['answer'] = str(ui.choice('YourChoice?', ['foo', 'bar']))
report['end'] = '1'
''')
        self.assertEqual(self.ui.report['begin'], '1')
        self.assertEqual(self.ui.report['end'], '1')
        self.assertEqual(self.ui.msg_text, 'YourChoice?')
        self.assertEqual(self.ui.report['answer'], '[1]')

        self.ui.question_choice_response = None
        self.ui.run_report_bug()
        self.assertEqual(self.ui.report['answer'], 'None')
        self.assertEqual(self.ui.report['end'], '1')

    def test_interactive_hooks_cancel(self):
        '''interactive hooks: user cancels'''

        self.assertRaises(SystemExit, self._run_hook,
            '''report['begin'] = '1'
raise StopIteration
report['end'] = '1'
''')

    def test_run_symptom(self):
        '''run_symptom()'''

        # unknown symptom
        sys.argv = ['ui-test', '-s', 'foobar' ]
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.assertEqual(self.ui.run_argv(), True)
        self.assertTrue('foobar" is not known' in self.ui.msg_text)
        self.assertEqual(self.ui.msg_severity, 'error')

        # does not determine package
        f = open(os.path.join(apport.ui.symptom_script_dir, 'nopkg.py'), 'w')
        f.write('def run(report, ui):\n    pass\n')
        f.close()
        orig_stderr = sys.stderr
        sys.argv = ['ui-test', '-s', 'nopkg' ]
        self.ui = TestSuiteUserInterface()
        sys.stderr = StringIO()
        self.assertRaises(SystemExit, self.ui.run_argv)
        err = sys.stderr.getvalue()
        sys.stderr = orig_stderr
        self.assertTrue('did not determine the affected package' in err)

        # does not define run()
        f = open(os.path.join(apport.ui.symptom_script_dir, 'norun.py'), 'w')
        f.write('def something(x, y):\n    return 1\n')
        f.close()
        sys.argv = ['ui-test', '-s', 'norun' ]
        self.ui = TestSuiteUserInterface()
        sys.stderr = StringIO()
        self.assertRaises(SystemExit, self.ui.run_argv)
        err = sys.stderr.getvalue()
        sys.stderr = orig_stderr
        self.assertTrue('norun.py crashed:' in err)

        # crashing script
        f = open(os.path.join(apport.ui.symptom_script_dir, 'crash.py'), 'w')
        f.write('def run(report, ui):\n    return 1/0\n')
        f.close()
        sys.argv = ['ui-test', '-s', 'crash' ]
        self.ui = TestSuiteUserInterface()
        sys.stderr = StringIO()
        self.assertRaises(SystemExit, self.ui.run_argv)
        err = sys.stderr.getvalue()
        sys.stderr = orig_stderr
        self.assertTrue('crash.py crashed:' in err)
        self.assertTrue('ZeroDivisionError:' in err)

        # working noninteractive script
        f = open(os.path.join(apport.ui.symptom_script_dir, 'itching.py'), 'w')
        f.write('def run(report, ui):\n  report["itch"] = "scratch"\n  return "bash"\n')
        f.close()
        sys.argv = ['ui-test', '-s', 'itching' ]
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.assertEqual(self.ui.run_argv(), True)
        self.assertEqual(self.ui.msg_text, None)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertTrue(self.ui.present_details_shown)

        self.assertEqual(self.ui.report['itch'], 'scratch')
        self.assertTrue('DistroRelease' in self.ui.report)
        self.assertEqual(self.ui.report['SourcePackage'], 'bash')
        self.assertTrue(self.ui.report['Package'].startswith('bash '))
        self.assertEqual(self.ui.report['ProblemType'], 'Bug')

        # working noninteractive script with extra tag
        sys.argv = ['ui-test', '--tag', 'foo', '-s', 'itching' ]
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.assertEqual(self.ui.run_argv(), True)
        self.assertEqual(self.ui.msg_text, None)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertTrue(self.ui.present_details_shown)

        self.assertEqual(self.ui.report['itch'], 'scratch')
        self.assertTrue('foo' in self.ui.report['Tags'])

        # working interactive script
        f = open(os.path.join(apport.ui.symptom_script_dir, 'itching.py'), 'w')
        f.write('''def run(report, ui):
    report['itch'] = 'slap'
    report['q'] = str(ui.yesno('do you?'))
    return 'bash'
''')
        f.close()
        sys.argv = ['ui-test', '-s', 'itching' ]
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }
        self.ui.question_yesno_response = True
        self.assertEqual(self.ui.run_argv(), True)
        self.assertTrue(self.ui.present_details_shown)
        self.assertEqual(self.ui.msg_text, 'do you?')

        self.assertEqual(self.ui.report['itch'], 'slap')
        self.assertTrue('DistroRelease' in self.ui.report)
        self.assertEqual(self.ui.report['SourcePackage'], 'bash')
        self.assertTrue(self.ui.report['Package'].startswith('bash '))
        self.assertEqual(self.ui.report['ProblemType'], 'Bug')
        self.assertEqual(self.ui.report['q'], 'True')

    def test_run_report_bug_list_symptoms(self):
        '''run_report_bug() without specifying arguments and available symptoms'''

        f = open(os.path.join(apport.ui.symptom_script_dir, 'foo.py'), 'w')
        f.write('''description = 'foo does not work'
def run(report, ui):
    return 'bash'
''')
        f.close()
        f = open(os.path.join(apport.ui.symptom_script_dir, 'bar.py'), 'w')
        f.write('def run(report, ui):\n  return "coreutils"\n')
        f.close()

        sys.argv = ['ui-test', '-f']
        self.ui = TestSuiteUserInterface()
        self.ui.present_details_response = {'report': True,
                                            'blacklist': False,
                                            'examine' : False,
                                            'restart' : False }

        self.ui.question_choice_response = None
        self.assertEqual(self.ui.run_argv(), True)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertTrue('kind of problem' in self.ui.msg_text)
        self.assertEqual(set(self.ui.msg_choices),
                set(['bar', 'foo does not work', 'Other problem']))

        # cancelled
        self.assertEqual(self.ui.ic_progress_pulses, 0)
        self.assertEqual(self.ui.report, None)
        self.assertFalse(self.ui.present_details_shown)

        # now, choose foo -> bash report
        self.ui.question_choice_response = [self.ui.msg_choices.index('foo does not work')]
        self.assertEqual(self.ui.run_argv(), True)
        self.assertEqual(self.ui.msg_severity, None)
        self.assertTrue(self.ui.ic_progress_pulses > 0)
        self.assertTrue(self.ui.present_details_shown)
        self.assertTrue(self.ui.report['Package'].startswith('bash'))

    def test_parse_argv_single_arg(self):
        '''parse_args() option inference for a single argument'''

        def _chk(program_name, arg, expected_opts):
            sys.argv = [program_name]
            if arg:
                sys.argv.append(arg)
            orig_stderr = sys.stderr
            sys.stderr = open('/dev/null', 'w')
            try:
                ui = apport.ui.UserInterface()
            finally:
                sys.stderr.close()
                sys.stderr = orig_stderr
            expected_opts['version'] = None
            self.assertEqual(ui.args, [])
            self.assertEqual(ui.options, expected_opts)

        # no arguments -> show pending crashes
        _chk('apport-gtk', None, {'filebug': False, 'package': None,
            'pid': None, 'crash_file': None, 'symptom': None,
            'update_report': None, 'save': None, 'window': False,
            'tag': []})
        # updating report not allowed without args
        self.assertRaises(SystemExit, _chk, 'apport-collect', None, {})

        # package
        _chk('apport-kde', 'coreutils', {'filebug': True, 'package':
            'coreutils', 'pid': None, 'crash_file': None, 'symptom': None,
            'update_report': None, 'save': None, 'window': False,
            'tag': []})

        # symptom is preferred over package
        f = open(os.path.join(apport.ui.symptom_script_dir, 'coreutils.py'), 'w')
        f.write('''description = 'foo does not work'
def run(report, ui):
return 'bash'
''')
        f.close()
        _chk('apport-cli', 'coreutils', {'filebug': True, 'package': None,
             'pid': None, 'crash_file': None, 'symptom': 'coreutils',
             'update_report': None, 'save': None, 'window': False,
             'tag': []})

        # PID
        _chk('apport-cli', '1234', {'filebug': True, 'package': None,
             'pid': '1234', 'crash_file': None, 'symptom': None,
             'update_report': None, 'save': None, 'window': False,
             'tag': []})

        # .crash/.apport files; check correct handling of spaces
        for suffix in ('.crash', '.apport'):
            _chk('apport-cli', '/tmp/f oo' + suffix, {'filebug': False,
                 'package': None, 'pid': None,
                 'crash_file': '/tmp/f oo' + suffix, 'symptom': None,
                 'update_report': None, 'save': None, 'window': False,
                 'tag': []})

        # executable
        _chk('apport-cli', '/usr/bin/tail', {'filebug': True,
             'package': 'coreutils',
             'pid': None, 'crash_file': None, 'symptom': None,
             'update_report': None, 'save': None, 'window': False,
             'tag': []})

        # update existing report
        _chk('apport-collect', '1234', {'filebug': False, 'package': None,
             'crash_file': None, 'symptom': None, 'update_report': 1234,
             'tag': []})
        _chk('apport-update-bug', '1234', {'filebug': False, 'package': None,
             'crash_file': None, 'symptom': None, 'update_report': 1234,
             'tag': []})

    def test_parse_argv_apport_bug(self):
        '''parse_args() option inference when invoked as *-bug'''

        def _chk(args, expected_opts):
            sys.argv = ['apport-bug'] + args
            orig_stderr = sys.stderr
            sys.stderr = open('/dev/null', 'w')
            try:
                ui = apport.ui.UserInterface()
            finally:
                sys.stderr.close()
                sys.stderr = orig_stderr
            expected_opts['version'] = None
            self.assertEqual(ui.args, [])
            self.assertEqual(ui.options, expected_opts)

        #
        # no arguments: default to 'ask for symptom' bug mode
        #
        _chk([], {'filebug': True, 'package': None,
            'pid': None, 'crash_file': None, 'symptom': None,
            'update_report': None, 'save': None, 'window': False,
            'tag': []})

        #
        # single arguments
        #

        # package
        _chk(['coreutils'], {'filebug': True, 'package':
            'coreutils', 'pid': None, 'crash_file': None, 'symptom': None,
            'update_report': None, 'save': None, 'window': False,
            'tag': []})

        # symptom (preferred over package)
        f = open(os.path.join(apport.ui.symptom_script_dir, 'coreutils.py'), 'w')
        f.write('''description = 'foo does not work'
def run(report, ui):
return 'bash'
''')
        f.close()
        _chk(['coreutils'], {'filebug': True, 'package': None,
             'pid': None, 'crash_file': None, 'symptom': 'coreutils',
             'update_report': None, 'save': None, 'window': False,
             'tag': []})
        os.unlink(os.path.join(apport.ui.symptom_script_dir, 'coreutils.py'))

        # PID
        _chk(['1234'], {'filebug': True, 'package': None,
             'pid': '1234', 'crash_file': None, 'symptom': None,
             'update_report': None, 'save': None, 'window': False,
             'tag': []})

        # .crash/.apport files; check correct handling of spaces
        for suffix in ('.crash', '.apport'):
            _chk(['/tmp/f oo' + suffix], {'filebug': False,
                 'package': None, 'pid': None,
                 'crash_file': '/tmp/f oo' + suffix, 'symptom': None,
                 'update_report': None, 'save': None, 'window': False,
                 'tag': []})

        # executable name
        _chk(['/usr/bin/tail'], {'filebug': True, 'package': 'coreutils',
             'pid': None, 'crash_file': None, 'symptom': None,
             'update_report': None, 'save': None, 'window': False,
             'tag': []})

        #
        # supported options
        #

        # --save
        _chk(['--save', 'foo.apport', 'coreutils'], {'filebug': True,
            'package': 'coreutils', 'pid': None, 'crash_file': None,
            'symptom': None, 'update_report': None, 'save': 'foo.apport',
            'window': False, 'tag': []})

        # --tag
        _chk(['--tag', 'foo', 'coreutils'], {'filebug': True,
            'package': 'coreutils', 'pid': None, 'crash_file': None,
            'symptom': None, 'update_report': None, 'save': None,
            'window': False, 'tag': ['foo']})
        _chk(['--tag', 'foo', '--tag', 'bar', 'coreutils'], {
            'filebug': True, 'package': 'coreutils', 'pid': None,
            'crash_file': None, 'symptom': None, 'update_report': None,
            'save': None, 'window': False, 'tag': ['foo', 'bar']})

    def test_can_examine_locally_crash(self):
        '''can_examine_locally() for a crash report'''

        self.ui.load_report(self.report_file.name)

        orig_path = os.environ['PATH']
        orig_fn = self.ui.ui_run_terminal
        try:
            self.ui.ui_run_terminal = lambda command: True
            os.environ['PATH'] = ''
            self.assertEqual(self.ui.can_examine_locally(), False)

            src_bindir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                    'bin')
            # this will only work for running the tests in the source tree
            if os.access(os.path.join(src_bindir, 'apport-retrace'), os.X_OK):
                os.environ['PATH'] = src_bindir
                self.assertEqual(self.ui.can_examine_locally(), True)
            else:
                # if we run tests in installed system, we just check that
                # it doesn't crash
                self.assertTrue(self.ui.can_examine_locally() in [False, True])

            self.ui.ui_run_terminal = lambda command: False
            self.assertEqual(self.ui.can_examine_locally(), False)

            # does not crash on NotImplementedError
            self.ui.ui_run_terminal = orig_fn
            self.assertEqual(self.ui.can_examine_locally(), False)

        finally:
            os.environ['PATH'] = orig_path
            self.ui.ui_run_terminal = orig_fn

    def test_can_examine_locally_nocrash(self):
        '''can_examine_locally() for a non-crash report'''

        self.ui.load_report(self.report_file.name)
        del self.ui.report['CoreDump']

        orig_fn = self.ui.ui_run_terminal
        try:
            self.ui.ui_run_terminal = lambda command: True
            self.assertEqual(self.ui.can_examine_locally(), False)
        finally:
            self.ui.ui_run_terminal = orig_fn

unittest.main()
