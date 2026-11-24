import time
import unittest

from PySide6.QtWidgets import QApplication


class Threads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from cellar.ui import common
        common.init_threading()
        cls.common = common

    def pump(self, until, seconds=3.0):
        end = time.time() + seconds
        while not until() and time.time() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def test_done_gets_the_result(self):
        got = []
        self.common.bg(lambda x: x * 2, 21, done=got.append)
        self.pump(lambda: got)
        self.assertEqual(got, [42])

    def test_err_gets_the_exception(self):
        # regression: err used to see a NameError instead of the exception (Python clears `ex` after except)
        got = []

        def boom():
            raise ValueError("nope")
        self.common.bg(boom, err=got.append)
        self.pump(lambda: got)
        self.assertEqual(len(got), 1)
        self.assertIsInstance(got[0], ValueError)
