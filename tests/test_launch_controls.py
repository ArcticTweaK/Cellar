"""Launch/relaunch labels must follow the selection and the live client state in both views."""
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication

from cellar import store, util
from cellar.models import Account, AppSettings
from cellar.ui import accounts, common, main_window


class LaunchControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        common.init_threading()

    def setUp(self):
        self.accs = [Account(username='one'), Account(username='two')]
        for patch in (mock.patch.object(store, 'accounts', self.accs),
                      mock.patch.object(store, 'settings', AppSettings()),
                      mock.patch.object(store, 'loaded', False),
                      mock.patch.object(store, 'save_settings'),
                      mock.patch.object(store, 'key_location', return_value='test keyring'),
                      mock.patch('cellar.sober.scan', return_value=[]),
                      mock.patch.object(main_window.wm, 'pick', return_value=None),
                      mock.patch.object(main_window.MainWindow, 'startup'),
                      mock.patch('cellar.ui.launch_pages.bg'),
                      mock.patch('cellar.sober.sober_installed', return_value=False),
                      mock.patch('cellar.sober.multi_instance_support', return_value=(False, 'test'))):
            patch.start()
            self.addCleanup(patch.stop)
        self.w = main_window.MainWindow()
        self.addCleanup(self.cleanup_window)
        self.w.select_accounts(self.accs[:1])

    def cleanup_window(self):
        self.w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_labels_follow_offline_running_and_mixed_selection(self):
        self.assertEqual(self.w.account_launch.text(), 'Launch')
        self.w.model.running = {self.accs[0].id}
        self.w.refresh_launch_action()
        self.assertEqual(self.w.account_launch.text(), 'Relaunch')
        self.assertTrue(self.w.launch_page.b_launch.toolTip().startswith('Relaunch 1 account'))
        self.w.select_accounts(self.accs)
        self.assertEqual(self.w.account_launch.text(), 'Launch / relaunch')
        self.w.set_launching(True)
        self.assertFalse(self.w.account_launch.isEnabled())
        self.w.set_launching(False)
        self.assertTrue(self.w.account_launch.isEnabled())

    def test_context_menu_names_the_action_and_disables_it_during_launch(self):
        self.w.model.running = {self.accs[0].id}
        with mock.patch.object(accounts, 'popup') as popup:
            self.w.context_menu(QPoint())
            menu = popup.call_args.args[0]
            self.assertEqual(menu.actions()[0].text(), 'Relaunch')
            menu.deleteLater()
        self.w.set_launching(True)
        with mock.patch.object(accounts, 'popup') as popup:
            self.w.context_menu(QPoint())
            menu = popup.call_args.args[0]
            self.assertFalse(menu.actions()[0].isEnabled())
            menu.deleteLater()

    def test_empty_launch_does_not_start_a_worker(self):
        with mock.patch('cellar.ui.launching.bg') as bg:
            self.w.start_launch([])
        bg.assert_not_called()
        self.assertFalse(self.w.launching)

    def test_live_refresh_updates_label_when_selected_client_stops(self):
        with mock.patch.object(self.w.launcher, 'alive_instances', return_value=[
                SimpleNamespace(account=self.accs[0], frozen=False, macro=None, screen=None)]):
            self.w.update_running()
        self.assertEqual(self.w.account_launch.text(), 'Relaunch')
        with mock.patch.object(self.w.launcher, 'alive_instances', return_value=[]):
            self.w.update_running()
        self.assertEqual(self.w.account_launch.text(), 'Launch')


class ActionNames(unittest.TestCase):
    def test_empty_selection_and_running_unselected_accounts(self):
        self.assertEqual(util.launch_action([], {'a'}), 'Launch')
        self.assertEqual(util.launch_action(['b'], {'a'}), 'Launch')
