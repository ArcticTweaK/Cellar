"""Encryption of accounts.dat.

Formats (first byte of the file):
  'P'  your own password - byte-for-byte the same format as the Windows app
       (PBKDF2-SHA1 100k -> AES-256-CBC + HMAC-SHA256), so a password-protected
       accounts.dat from Windows opens here and vice versa.
  'K'  no password to remember: a random 256-bit key kept in your keyring
       (Secret Service, or KWallet on KDE; a 0600 key file only as a last resort),
       data sealed with AES-256-GCM. Second byte says where the key lives.
  'D'  Windows DPAPI - cannot be opened on Linux (tied to the Windows user).
"""

import hashlib
import hmac
import os
from typing import Optional

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import paths

KEYRING_SERVICE = "cellar"
KEYRING_ACCOUNT = "accounts-key"
KWALLET_FOLDER = "Cellar"
APP_ID = "Cellar"
# Where the key was kept before the rename (Roblox MultiHub for Linux). Read as a fallback and
# copied to the new place; never deleted, so going back to the old app keeps working.
OLD_KEYRING_SERVICE = "roblox-multihub"
OLD_KWALLET_FOLDER = "RobloxMultiHub"
# Bound into every 'K' file. Kept from before the rename: changing it would make existing
# accounts files unreadable.
_AAD = b"RobloxMultiHub.linux.v1"


class DecryptError(Exception):
    pass


# ---------------------------------------------------------------- 'P' (Windows compatible)
def _derive(password: str, salt: bytes):
    keys = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), salt, 100000, 64)
    return keys[:32], keys[32:]


def encrypt_password(data: bytes, password: str) -> bytes:
    salt, iv = os.urandom(16), os.urandom(16)
    enc_key, mac_key = _derive(password, salt)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    e = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).encryptor()
    cipher = e.update(padded) + e.finalize()
    body = salt + iv + cipher
    mac = hmac.new(mac_key, body, hashlib.sha256).digest()
    return b"P" + mac + body


def decrypt_password(raw: bytes, password: str) -> bytes:
    if len(raw) < 1 + 32 + 32 + 16:
        raise DecryptError("file too short")
    mac, body = raw[1:33], raw[33:]
    salt, iv = body[:16], body[16:32]
    enc_key, mac_key = _derive(password, salt)
    if not hmac.compare_digest(mac, hmac.new(mac_key, body, hashlib.sha256).digest()):
        raise DecryptError("Wrong password (or the file is damaged).")
    d = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).decryptor()
    padded = d.update(body[32:]) + d.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


# ---------------------------------------------------------------- key providers for 'K'
class KeyProvider:
    code = "?"
    label = "?"

    def available(self) -> bool:
        return False

    def load(self) -> Optional[bytes]:
        return None

    def store(self, key: bytes) -> bool:
        return False


class SecretServiceProvider(KeyProvider):
    code, label = "S", "system keyring (Secret Service)"

    def _collection(self):
        import secretstorage
        conn = secretstorage.dbus_init()
        if not secretstorage.check_service_availability(conn):
            return None
        col = secretstorage.get_default_collection(conn)
        if col.is_locked():
            col.unlock()
        return col

    def available(self) -> bool:
        try:
            return self._collection() is not None
        except Exception:
            return False

    def load(self):
        try:
            col = self._collection()
            if col is None:
                return None
            for service in (KEYRING_SERVICE, OLD_KEYRING_SERVICE):
                for item in col.search_items({"service": service, "account": KEYRING_ACCOUNT}):
                    key = bytes.fromhex(item.get_secret().decode())
                    if service != KEYRING_SERVICE:
                        self.store(key)             # copy to Cellar's name; the old item stays
                    return key
        except Exception:
            return None
        return None

    def store(self, key: bytes) -> bool:
        try:
            col = self._collection()
            col.create_item("Cellar accounts key", {"service": KEYRING_SERVICE, "account": KEYRING_ACCOUNT},
                            key.hex().encode(), replace=True)
            return True
        except Exception:
            return False


class KWalletProvider(KeyProvider):
    """KWallet over D-Bus. Uses busctl because KWallet's open() wants a 64-bit window id,
    which Python ints do not marshal to through QtDBus."""
    code, label = "W", "KWallet"
    _svc = None

    def _call(self, method: str, sig: str, *args, timeout: int = 25):
        import json
        import shutil
        import subprocess
        busctl = shutil.which("busctl")
        if busctl is None or self._svc is None:
            return None
        svc, path = self._svc
        cmd = [busctl, "--user", "--json=short", f"--timeout={timeout}", "call", svc, path, "org.kde.KWallet", method]
        if sig:
            cmd += [sig] + [str(a) for a in args]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
            if out.returncode != 0:
                return None
            data = json.loads(out.stdout).get("data") or []
            return data[0] if data else None
        except Exception:
            return None

    def _find(self) -> bool:
        if self._svc is not None:
            return True
        for svc, path in (("org.kde.kwalletd6", "/modules/kwalletd6"), ("org.kde.kwalletd5", "/modules/kwalletd5")):
            self._svc = (svc, path)
            if self._call("isEnabled", "") is True:
                return True
        self._svc = None
        return False

    def _open(self):
        if not self._find():
            return None
        wallet = self._call("networkWallet", "") or "kdewallet"
        h = self._call("open", "sxs", wallet, 0, APP_ID, timeout=120)   # an unlock prompt may be shown
        if h is None or int(h) < 0:
            return None
        return int(h)

    def available(self) -> bool:
        try:
            return self._find()
        except Exception:
            return False

    def load(self):
        h = self._open()
        if h is None:
            return None
        for folder in (KWALLET_FOLDER, OLD_KWALLET_FOLDER):
            if not self._call("hasEntry", "isss", h, folder, KEYRING_ACCOUNT, APP_ID):
                continue
            v = self._call("readPassword", "isss", h, folder, KEYRING_ACCOUNT, APP_ID)
            try:
                key = bytes.fromhex(v) if v else None
            except ValueError:
                key = None
            if key and folder != KWALLET_FOLDER:
                self.store(key)                     # copy to Cellar's folder; the old entry stays
            return key
        return None

    def store(self, key: bytes) -> bool:
        h = self._open()
        if h is None:
            return False
        if not self._call("hasFolder", "iss", h, KWALLET_FOLDER, APP_ID):
            self._call("createFolder", "iss", h, KWALLET_FOLDER, APP_ID)
        return self._call("writePassword", "issss", h, KWALLET_FOLDER, KEYRING_ACCOUNT, key.hex(), APP_ID) == 0


class FileKeyProvider(KeyProvider):
    """Last resort: a key file readable only by you. Protects against casual copying of
    accounts.dat on its own, NOT against someone who can read your home folder."""
    code, label = "F", "key file in your data folder (no keyring found)"

    def available(self) -> bool:
        return True

    def load(self):
        try:
            return bytes.fromhex(paths.KEY_FILE.read_text().strip())
        except Exception:
            return None

    def store(self, key: bytes) -> bool:
        try:
            paths.KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(paths.KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(key.hex())
            return True
        except OSError:
            return False


PROVIDERS = [SecretServiceProvider(), KWalletProvider(), FileKeyProvider()]


def provider_by_code(code: str) -> Optional[KeyProvider]:
    for p in PROVIDERS:
        if p.code == code:
            return p
    return None


def pick_provider() -> KeyProvider:
    for p in PROVIDERS:
        if p.available():
            return p
    return PROVIDERS[-1]


# ---------------------------------------------------------------- 'K'
_key_cache = {}


def _get_key(provider: KeyProvider, create: bool) -> bytes:
    if provider.code in _key_cache:
        return _key_cache[provider.code]
    key = provider.load()
    if key is None and create:
        key = os.urandom(32)
        if not provider.store(key):
            raise DecryptError(f"Could not save the encryption key in {provider.label}.")
    if key is None:
        raise DecryptError(f"The encryption key was not found in {provider.label}.")
    _key_cache[provider.code] = key
    return key


def encrypt_keyring(data: bytes, provider: KeyProvider) -> bytes:
    key = _get_key(provider, create=True)
    nonce = os.urandom(12)
    return b"K" + provider.code.encode() + nonce + AESGCM(key).encrypt(nonce, data, _AAD)


def decrypt_keyring(raw: bytes) -> bytes:
    if len(raw) < 2 + 12 + 16:
        raise DecryptError("file too short")
    provider = provider_by_code(chr(raw[1]))
    if provider is None:
        raise DecryptError("unknown key location")
    key = _get_key(provider, create=False)
    try:
        return AESGCM(key).decrypt(raw[2:14], raw[14:], _AAD)
    except Exception:
        raise DecryptError(f"The key in {provider.label} does not open this file.")


def provider_of(raw: bytes) -> Optional[KeyProvider]:
    if len(raw) >= 2 and raw[:1] == b"K":
        return provider_by_code(chr(raw[1]))
    return None
