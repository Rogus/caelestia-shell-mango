"""Exercise the real recording service without capturing the desktop.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/check_recorder_service.py
Requires Quickshell and built Caelestia modules in build/qml.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HELPER = '''import json, os, sys, time
from pathlib import Path
folder = Path(os.environ['RECORDER_CHECK_ROOT'])
action = sys.argv[1]
with (folder / 'commands.jsonl').open('a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
time.sleep(0.12)
path = folder / 'state.json'
state = json.loads(path.read_text()) if path.exists() else {'running': False, 'paused': False, 'elapsed': 0}
if action == 'start': state.update(running=True, paused=False)
elif action == 'stop': state.update(running=False, paused=False)
elif action == 'pause': state['paused'] = not state['paused']
path.write_text(json.dumps(state))
print(json.dumps(state))
'''
PICKER = '''#!/usr/bin/python3
import os, signal, time
from pathlib import Path
path = Path(os.environ['RECORDER_CHECK_ROOT']) / 'selections'
count = int(path.read_text()) + 1 if path.exists() else 1
path.write_text(str(count))
if count == 2:
    signal.signal(signal.SIGTERM, lambda *args: None)
    time.sleep(0.4)
elif count == 3:
    raise SystemExit(1)
else:
    time.sleep(0.08)
print('640x480+100+200')
'''


def check(scenario):
    with tempfile.TemporaryDirectory(prefix='recorder-check-') as folder:
        directory = Path(folder)
        for name in ('services', 'utils', 'assets', 'bin', 'runtime'):
            (directory / name).mkdir(mode=0o700)
        shutil.copy(ROOT / 'services/Recorder.qml', directory / 'services/Recorder.qml')
        shutil.copy(ROOT / 'tests/recorder-service-check.qml', directory / 'shell.qml')
        (directory / 'services/Mango.qml').write_text('pragma Singleton\nimport QtQuick\nQtObject { property string focusedOutput: "test-output" }\n')
        (directory / 'utils/Paths.qml').write_text('pragma Singleton\nimport QtQuick\nQtObject { property string recsdir: "/tmp/recorder-test-output" }\n')
        (directory / 'assets/mango_recorder.py').write_text(HELPER)
        if scenario != 'missing-python':
            (directory / 'bin/python3').symlink_to(shutil.which('python3'))
        if scenario != 'missing-slurp':
            picker = directory / 'bin/slurp'
            picker.write_text(PICKER)
            picker.chmod(0o755)
        environment = {
            **os.environ,
            'PATH': str(directory / 'bin'),
            'QT_QPA_PLATFORM': 'offscreen',
            'QML_IMPORT_PATH': str(ROOT / 'build/qml'),
            'XDG_RUNTIME_DIR': str(directory / 'runtime'),
            'XDG_CONFIG_HOME': str(directory / 'config'),
            'XDG_CACHE_HOME': str(directory / 'cache'),
            'RECORDER_CHECK_ROOT': folder,
            'RECORDER_CHECK_SCENARIO': scenario,
            'PYTHONDONTWRITEBYTECODE': '1',
        }
        try:
            result = subprocess.run([shutil.which('qs'), '-p', folder, '--no-color'], env=environment,
                                    text=True, capture_output=True, timeout=15)
        except subprocess.TimeoutExpired as error:
            log = directory / 'commands.jsonl'
            raise AssertionError((error.stdout or b'').decode() + (error.stderr or b'').decode()
                                 + (log.read_text() if log.exists() else '')) from error
        output = result.stdout + result.stderr
        assert result.returncode == 0 and f'RECORDER_SERVICE_PASS {scenario}' in output, output
        assert 'Error:' not in output, output
        log = directory / 'commands.jsonl'
        commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        starts = [args for args in commands if args[0] == 'start']
        if scenario == 'normal':
            assert len(starts) == 3, commands
            for args in starts[:2]:
                assert '--sound' in args and '--region' in args, args
                assert args[args.index('--region') + 1] == '640x480+100+200', args
                assert args[args.index('--output') + 1] == 'test-output', args
            assert '--sound' in starts[2] and '--region' not in starts[2], starts[2]
            assert int((directory / 'selections').read_text()) == 4
            assert len([args for args in commands if args[0] == 'pause']) == 2
        else:
            assert not starts, commands
        print(f'Recorder QML check passed: {scenario}')


if __name__ == '__main__':
    for scenario in ('normal', 'missing-slurp', 'missing-python'):
        check(scenario)
