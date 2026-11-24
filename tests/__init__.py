"""Cellar's tests. Run: python -m unittest discover -s tests -t .   (no extra packages needed)

Every test runs with throw-away XDG folders, set here before any cellar module is imported, so nothing touches
your real accounts, settings, keyring or Sober.
"""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="cellar-tests-")
for _v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    os.environ[_v] = os.path.join(_tmp, _v.lower())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
