"""A failed preset must unlock the launch controls so the user can try again."""
import unittest
from types import SimpleNamespace
from unittest import mock

from cellar.models import Account, AppSettings, LaunchSpec, Preset, PresetEntry
from cellar import store
from cellar.ui import presets_page


class PresetFailures(unittest.TestCase):
    def test_worker_exception_resets_launching(self):
        account = Account(username='fake')
        mw = SimpleNamespace(launching=False, log=mock.Mock(), reload_pages=mock.Mock(),
                             launch_page=SimpleNamespace(read_form=mock.Mock(return_value=None)),
                             launcher=SimpleNamespace(running=mock.Mock(return_value=False)))
        mw.set_launching = lambda value, *args: setattr(mw, 'launching', value)
        page = SimpleNamespace(mw=mw)
        preset = Preset(name='test', entries=[PresetEntry(account_id=account.id)])

        def worker(fn, done=None, err=None):
            try:
                result = fn()
            except Exception as ex:
                self.assertIsNotNone(err)
                err(ex)
            else:
                done(result)

        with mock.patch.object(store, 'settings', AppSettings()), \
                mock.patch.object(store, 'save_settings'), \
                mock.patch.object(store, 'find_by_id', return_value=account), \
                mock.patch.object(presets_page, 'bg', side_effect=worker), \
                mock.patch.object(presets_page.specs, 'saved_spec', side_effect=OSError('test error')):
            presets_page.PresetsPage.run(page, preset)
        self.assertFalse(mw.launching)
        self.assertIn('stopped because of an error', mw.log.call_args.args[0])

    def test_preset_share_link_does_not_change_accounts_saved_game(self):
        account = Account(username='fake', game_link='424242')
        mw = SimpleNamespace(launching=False, log=mock.Mock(), reload_pages=mock.Mock(),
                             launch_page=SimpleNamespace(read_form=mock.Mock(return_value=None)),
                             launcher=SimpleNamespace(running=mock.Mock(return_value=False),
                                                      breaker_clear=mock.Mock(), launch=mock.Mock()))
        mw.set_launching = lambda value, *args: setattr(mw, 'launching', value)
        page = SimpleNamespace(mw=mw, _place_when_ready=mock.Mock())
        preset = Preset(entries=[PresetEntry(account_id=account.id,
                                            spec=LaunchSpec(kind='Private', share_code='fake'))])
        with mock.patch.object(store, 'settings', AppSettings()), \
                mock.patch.object(store, 'save_settings'), \
                mock.patch.object(store, 'find_by_id', return_value=account), \
                mock.patch.object(presets_page, 'bg', side_effect=lambda fn, **kw: kw['done'](fn())), \
                mock.patch.object(presets_page.specs, 'resolve_saved_share', return_value=True) as resolve:
            presets_page.PresetsPage.run(page, preset)
        self.assertFalse(resolve.call_args.kwargs['save'])
