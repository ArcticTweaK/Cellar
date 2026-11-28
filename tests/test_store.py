"""Saving failures must preserve the last readable accounts file and its password."""
import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cellar import paths, store
from cellar.models import Account


class AccountSaving(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.file = Path(temp.name) / 'accounts.dat'
        for patch in (mock.patch.object(paths, 'ACCOUNTS_FILE', self.file),
                      mock.patch.object(paths, 'BACKUP_DIR', Path(temp.name) / 'backups'),
                      mock.patch.object(store, 'password', 'old password'),
                      mock.patch.object(store, 'accounts', [Account(username='test', cookie='fake')]),
                      mock.patch.object(store, 'loaded', True)):
            patch.start()
            self.addCleanup(patch.stop)
        self.assertTrue(store.save_accounts())

    def test_failed_password_change_keeps_original_file_and_password(self):
        before = self.file.read_bytes()
        with mock.patch.object(store.os, 'replace', side_effect=OSError('disk full')):
            self.assertFalse(store.set_password('new password'))
        self.assertEqual(store.password, 'old password')
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(store.accounts_from_json(store.decrypt_file(before, store.password))[0].username, 'test')
        self.assertEqual(list(self.file.parent.glob('*.tmp')), [])
        # A subsequent background save must still use the old password.
        self.assertTrue(store.save_accounts())
        store.decrypt_file(self.file.read_bytes(), 'old password')

    def test_password_change_is_readable_with_new_password(self):
        self.assertTrue(store.set_password('new password'))
        store.decrypt_file(self.file.read_bytes(), 'new password')

    def test_backups_in_same_second_do_not_overwrite_each_other(self):
        with mock.patch.object(store.time, 'strftime', return_value='accounts_same_second_'):
            store.backup()
            store.backup()
        self.assertEqual(len(store.backups()), 2)

    def test_concurrent_atomic_writes_leave_one_complete_file(self):
        data = [bytes([i]) * 50000 for i in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda payload: store.atomic_write(self.file, payload), data))
        self.assertIn(self.file.read_bytes(), data)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.file.parent.glob('*.tmp')), [])
