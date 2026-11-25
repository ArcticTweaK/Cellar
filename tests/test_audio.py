import unittest
from pathlib import Path
from unittest import mock

from cellar import audio


def _client(cid, **props):
    return {"id": cid, "type": "PipeWire:Interface:Client", "info": {"props": props}}


def _stream(nid, client_id, cls="Stream/Output/Audio"):
    props = {"media.class": cls, "client.id": client_id, "application.process.id": 3}
    return {"id": nid, "type": "PipeWire:Interface:Node", "info": {"props": props}}


SOBER = {"pipewire.sec.pid": 2391, "application.process.id": 3,          # pipewire-pulse / pid in the sandbox
         "pipewire.access.portal.app_id": "org.vinegarhq.Sober"}


class StreamsOf(unittest.TestCase):
    """Shape measured on PipeWire 1.6.9 with six Sober clients: every client had the same sec.pid."""

    def test_flatpak_clients_map_to_their_instance_scope(self):
        objs = [_client(112, **SOBER, **{"pipewire.access.portal.instance_id": 2144662762}),
                _client(120, **SOBER, **{"pipewire.access.portal.instance_id": 2432548995}),
                _stream(113, 112), _stream(130, 120),
                _stream(140, 120, cls="Stream/Input/Audio")]                    # a microphone: left alone
        with mock.patch.object(audio, "app_slice", return_value=Path("/cg/app.slice")):
            got = audio.streams_of(objs)
        self.assertEqual(got, {113: Path("/cg/app.slice/app-flatpak-org.vinegarhq.Sober-2144662762.scope"),
                               130: Path("/cg/app.slice/app-flatpak-org.vinegarhq.Sober-2432548995.scope")})

    def test_programs_outside_flatpak_use_their_pid(self):
        objs = [_client(7, **{"pipewire.sec.pid": 4242}), _stream(8, 7)]
        with mock.patch.object(audio, "cgroup_of", return_value=Path("/cg/x.scope")) as cg:
            self.assertEqual(audio.streams_of(objs), {8: Path("/cg/x.scope")})
        cg.assert_called_with(4242)


if __name__ == "__main__":
    unittest.main()
