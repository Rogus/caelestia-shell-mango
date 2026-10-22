import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"assets/{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


theme = module("mango_theme")
recorder = module("mango_recorder")
schemes = module("mango_schemes")


class ThemeTest(unittest.TestCase):
    def test_preserve_multiline_alacritty_import_and_preferences(self):
        original = '[general]\nimport = [\n "old.toml",\n]\n[window]\nopacity = 0.7\n'
        result = theme.alacritty_include(original, Path('/tmp/theme.toml'))
        parsed = tomllib.loads(result)
        self.assertEqual(parsed['general']['import'], ['old.toml', '/tmp/theme.toml'])
        self.assertEqual(parsed['window']['opacity'], 0.7)
        self.assertEqual(theme.alacritty_include(result, Path('/tmp/theme.toml')), result)

    def test_legacy_alacritty_import_and_no_general_section(self):
        for original in ['import = ["old.toml"]\n[window]\nopacity = 0.7\n', 'live_config_reload = true\n[window]\nopacity = 0.7\n']:
            result = tomllib.loads(theme.alacritty_include(original, Path('/tmp/theme.toml')))
            self.assertEqual(result['window']['opacity'], 0.7)
            self.assertIn('/tmp/theme.toml', result.get('import', result.get('general', {}).get('import', [])))

    def test_application_files_and_backups_are_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)
            terminal = config / 'alacritty/alacritty.toml'
            terminal.parent.mkdir()
            original = '[general]\nimport = ["other-theme.toml"]\n[window]\nopacity = 0.7\n'
            terminal.write_text(original)
            palette = schemes.select('ocean', 'default', 'dark')
            theme.apply_theme(palette, config)
            first = terminal.read_text()
            theme.apply_theme(palette, config)
            self.assertEqual(first, terminal.read_text())
            self.assertEqual(terminal.with_name('alacritty.toml.before-caelestia-theme').read_text(), original)
            self.assertTrue((config / 'caelestia/themes/foot.ini').exists())
            self.assertEqual((config / 'gtk-3.0/gtk.css').read_text().count('@import'), 1)

    def test_managed_config_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'target'
            target.write_text('preserve')
            link = Path(folder) / 'managed'
            link.symlink_to(target)
            theme.update_config(link, lambda text: 'changed')
            self.assertEqual(target.read_text(), 'preserve')

    def test_all_bundled_palettes_render_application_themes(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, flavours in schemes.catalog().items():
                for flavour, modes in flavours.items():
                    for mode in modes:
                        theme.apply_theme(schemes.select(name, flavour, mode), Path(folder))

    def test_user_palette_and_mode_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CONFIG_HOME': folder}):
            path = Path(folder) / 'caelestia/schemes/custom.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'name':'custom','mode':'light','colours':{'primary':'abcdef'}}))
            self.assertEqual(schemes.select('custom', 'default', 'dark')['mode'], 'light')


class RecorderTest(unittest.TestCase):
    def test_system_audio_alias_matches_installed_recorder_version(self):
        for listing, expected in [('default_output|Default output\n', 'default_output'),
                                  ('defaultoutput|Default output\n', 'defaultoutput')]:
            with self.subTest(expected=expected), patch.object(recorder.subprocess, 'run') as query:
                query.return_value.stdout = listing
                self.assertEqual(recorder.system_audio_device(), expected)
                self.assertEqual(query.call_args.args[0], ['gpu-screen-recorder', '--list-audio-devices'])

    def test_region_and_sound_flags_reach_recorder(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(recorder.subprocess, 'Popen') as spawn, \
                patch.object(recorder, 'system_audio_device', return_value='default_output'), \
                patch.object(recorder, 'process_identity', return_value='same'), \
                patch.object(recorder.time, 'sleep'):
            spawn.return_value.poll.return_value = None
            spawn.return_value.pid = 12
            recorder.operate('start', {}, 'eDP-1', folder + '/recording.mp4', True, '640x480+10+20')
            command = spawn.call_args.args[0]
            self.assertEqual(command[command.index('-w') + 1], 'region')
            self.assertEqual(command[command.index('-region') + 1], '640x480+10+20')
            self.assertEqual(command[command.index('-a') + 1], 'default_output')

    def test_pid_reuse_and_missing_process_clear_state(self):
        with patch.object(recorder, 'process_identity', return_value='replacement'):
            self.assertFalse(recorder.status({'pid': 1, 'identity':'old'})['running'])
        self.assertFalse(recorder.status({'pid': -1})['running'])

    def test_paused_elapsed_does_not_advance(self):
        state = {'pid':1,'identity':'same','started':10,'paused':True,'paused_at':30,'paused_seconds':5}
        with patch.object(recorder, 'process_identity', return_value='same'), patch.object(recorder.time, 'time', return_value=100):
            self.assertEqual(recorder.status(state)['elapsed'], 15)

    def test_only_owned_pid_is_signalled(self):
        state = {'pid':12,'identity':'same','started':10,'paused':False,'paused_seconds':0}
        with patch.object(recorder, 'process_identity', return_value='same'), patch.object(recorder.os, 'pidfd_open', return_value=5) as opened, patch.object(recorder.os, 'close'), patch.object(recorder.signal, 'pidfd_send_signal') as send:
            recorder.operate('pause', state)
            opened.assert_called_once_with(12)
            send.assert_called_once_with(5, recorder.signal.SIGUSR2)
            self.assertTrue(state['paused'])

    def test_failed_launch_never_reports_running(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(recorder.subprocess, 'Popen') as spawn, patch.object(recorder.time, 'sleep'):
            spawn.return_value.poll.return_value = 1
            with self.assertRaisesRegex(RuntimeError, 'failed to start'):
                recorder.operate('start', {}, 'eDP-1', folder + '/recording.mp4')

    def test_detached_recorder_survives_helper_and_can_be_paused_and_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            executable = directory / 'gpu-screen-recorder'
            executable.write_text("#!/usr/bin/python3\nimport signal,time\nsignal.signal(signal.SIGUSR2, lambda *args: None)\ntime.sleep(10)\n")
            executable.chmod(0o755)
            environment = {**os.environ, 'XDG_RUNTIME_DIR': folder, 'PATH': folder + ':' + os.environ['PATH']}
            def call(*args):
                return json.loads(subprocess.check_output(['python3', str(ROOT / 'assets/mango_recorder.py'), *args], env=environment, text=True))
            state = call('start', '--destination', str(directory / 'record.mp4'))
            try:
                self.assertTrue(state['running'])
                self.assertTrue(call('status')['running'])
                self.assertTrue(call('pause')['paused'])
                self.assertFalse(call('pause')['paused'])
                call('stop')
                for _ in range(20):
                    if not call('status')['running']: break
                    time.sleep(0.05)
                self.assertFalse(call('status')['running'])
            finally:
                if recorder.process_identity(state['pid']) == state['identity']:
                    os.kill(state['pid'], recorder.signal.SIGTERM)

    def test_real_process_identity_disappears_after_exit(self):
        process = subprocess.Popen(['sleep', '1'])
        try:
            self.assertIsNotNone(recorder.process_identity(process.pid))
        finally:
            process.terminate()
            process.wait()
        self.assertIsNone(recorder.process_identity(process.pid))


if __name__ == '__main__':
    unittest.main()
