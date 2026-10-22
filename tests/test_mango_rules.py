import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'assets'))
import mango_rules as rules


class WindowRulesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'config.conf'
        self.config.write_text('gap_inner_horizontal=8\n')
        self.fragment = Path(self.temp.name) / 'caelestia-window-rules.conf'
        self.rule = {'match': {'app_id': '^org.example.App$'}, 'options': {'is_floating': '1', 'width': '800'}}

    @patch.object(rules, 'dispatch')
    def test_save_edit_delete_reload_and_preserve_config(self, dispatch):
        result = rules.change(self.config, self.fragment, 'save', self.rule)
        identity = result['savedId']
        self.assertEqual(dispatch.call_args.args, ('reload_config',))
        self.assertIn('window_rule=app_id:^org.example.App$,is_floating:1,width:800', self.fragment.read_text())
        self.assertEqual(self.config.read_text().count('source='), 1)
        self.assertEqual(self.config.with_suffix('.conf.before-caelestia-rules').read_text(), 'gap_inner_horizontal=8\n')
        self.rule['id'] = identity
        self.rule['options']['is_floating'] = '0'
        rules.change(self.config, self.fragment, 'save', self.rule)
        self.assertEqual(len(rules.load_rules(self.fragment)), 1)
        self.assertEqual(self.config.read_text().count('source='), 1)
        rules.change(self.config, self.fragment, 'delete', identity)
        self.assertEqual(rules.load_rules(self.fragment), [])
        self.assertEqual(dispatch.call_count, 3)

    @patch.object(rules, 'dispatch', side_effect=RuntimeError('reload failed'))
    def test_failed_reload_restores_files(self, dispatch):
        before = self.config.read_text()
        self.fragment.write_text(rules.render([]))
        with self.assertRaisesRegex(RuntimeError, 'reload failed'):
            rules.change(self.config, self.fragment, 'save', self.rule)
        self.assertEqual(self.config.read_text(), before)
        self.assertEqual(rules.load_rules(self.fragment), [])

    def test_invalid_options_and_injection_never_write(self):
        for options in ({'width': 'nan'}, {'height': '-1'}, {'tags': '32'},
                        {'tags': '1\nexec=bad'}, {'is_floating': '2'}, {'unknown': '1'},
                        {'monitor': 'DP-1,exec:bad'}, {'offset_x': '1.5'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                rules.validate({**self.rule, 'options': options})
        for expression in ('^App$,is_floating:1', 'App\nexec=bad', 'App#comment', '['):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                rules.validate({**self.rule, 'match': {'title': expression}})
        self.assertFalse(self.fragment.exists())

    def test_explicit_off_roundtrips_and_default_is_absent(self):
        rule = rules.validate({'match': {'title': '^Picture-in-Picture$'}, 'options': {'is_floating': 0, 'focused_opacity': '0.8'}})
        self.fragment.write_text(rules.render([rule]))
        self.assertEqual(rules.load_rules(self.fragment), [rule])
        self.assertNotIn('no_border:', self.fragment.read_text())
        self.assertIn('is_floating:0', self.fragment.read_text())

    def test_managed_config_requires_declarative_source(self):
        actual = Path(self.temp.name) / 'managed.conf'
        actual.write_text('gap_inner_horizontal=8\n')
        self.config.unlink()
        self.config.symlink_to(actual)
        with self.assertRaisesRegex(ValueError, 'Add source='):
            rules.config_with_source(self.config, self.fragment)
        actual.write_text(f'source={self.fragment}\n')
        self.assertEqual(*rules.config_with_source(self.config, self.fragment))
        self.assertTrue(self.config.is_symlink())

    def test_toml_source_is_respected(self):
        config = self.config.with_suffix('.toml')
        config.write_text('[global]\nsource=["caelestia-window-rules.conf"]\n')
        self.assertEqual(*rules.config_with_source(config, self.fragment))
        config.write_text('[global]\nborder_px=2\n')
        with self.assertRaisesRegex(ValueError, 'TOML'):
            rules.config_with_source(config, self.fragment)

    @patch.object(rules.subprocess, 'run')
    @patch.object(rules, 'dispatch')
    def test_live_actions_target_original_client_and_only_toggle_if_needed(self, dispatch, run):
        run.return_value.stdout = json.dumps({'clients': [
            {'id': 17, 'is_floating': False, 'is_fullscreen': True, 'is_global': False, 'width': 700, 'height': 500},
            {'id': 99, 'title': 'Caelestia Window Rules', 'is_focused': True}]})
        rules.apply_live(17, {'is_floating': '1', 'is_fullscreen': '1', 'is_global': '1', 'width': '800'})
        self.assertEqual([c.args[0] for c in dispatch.call_args_list], [
            'togglefloating,client,17', 'toggleglobal,client,17',
            'resizewin,800,500,client,17', 'centerwin,client,17'])

    @patch.object(rules.subprocess, 'run')
    @patch.object(rules, 'dispatch')
    def test_closed_target_never_changes_focused_editor(self, dispatch, run):
        run.return_value.stdout = '{"clients": [{"id": 99, "is_focused": true}]}'
        self.assertIn('closed', rules.apply_live(17, {'is_floating': '1'}))
        dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
