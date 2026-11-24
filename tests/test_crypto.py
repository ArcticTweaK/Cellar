import os
import unittest

from cellar import crypto, paths


class Crypto(unittest.TestCase):
    def test_password_format(self):
        raw = crypto.encrypt_password(b'{"accounts": []}', "hunter2")
        self.assertEqual(raw[:1], b"P")
        self.assertEqual(crypto.decrypt_password(raw, "hunter2"), b'{"accounts": []}')
        with self.assertRaises(crypto.DecryptError):
            crypto.decrypt_password(raw, "wrong")

    def test_key_file_format(self):
        paths.ensure_dirs()                       # temp folders (tests/__init__.py): never your real key
        p = crypto.FileKeyProvider()
        raw = crypto.encrypt_keyring(b"secret", p)
        self.assertEqual(raw[:2], b"KF")
        self.assertEqual(crypto.decrypt_keyring(raw), b"secret")
        self.assertIs(crypto.provider_of(raw), crypto.provider_by_code("F"))
        bad = raw[:-1] + bytes([raw[-1] ^ 1])
        with self.assertRaises(crypto.DecryptError):
            crypto.decrypt_keyring(bad)

    def test_temp_home(self):
        self.assertIn("cellar-tests-", str(paths.DATA_DIR))
        self.assertTrue(str(paths.KEY_FILE).startswith(os.environ["XDG_DATA_HOME"]))


class Export(unittest.TestCase):
    def test_round_trip(self):
        import tempfile
        from pathlib import Path
        from cellar import store
        from cellar.models import Account
        f = Path(tempfile.mkdtemp()) / "x.dat"
        accs = [Account(username="a", user_id=1, cookie="c1", group="Farm", pinned=True), Account(username="b")]
        store.export_accounts(f, accs, "pw")
        self.assertEqual(f.read_bytes()[:1], b"P")
        self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")
        back = store.accounts_from_json(store.decrypt_file(f.read_bytes(), "pw"))
        self.assertEqual([(a.username, a.cookie, a.group, a.pinned) for a in back],
                         [("a", "c1", "Farm", True), ("b", "", "", False)])
        with self.assertRaises(crypto.DecryptError):
            store.decrypt_file(f.read_bytes(), "nope")
