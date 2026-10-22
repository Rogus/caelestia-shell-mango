"""Exercise the real QML editor with isolated settings and fake Mango IPC."""
import os
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='window-rules-qml-') as folder:
    p=Path(folder)
    for name in ('modules','components','utils','assets'):
        (p/name).symlink_to(root/name)
    (p/'services').mkdir()
    (p/'services/Mango.qml').write_text("""pragma Singleton
import QtQuick
QtObject {
    property var clientState: []
    signal configReloaded
}
""")
    (p/'services/Colours.qml').write_text("""pragma Singleton
import QtQuick
QtObject {
    property bool light: false
    property var palette: ({m3onSurface: '#eeeeee', m3onSurfaceVariant: '#cccccc', m3primary: '#aabbff', m3onPrimary: '#111111', m3onSecondary: '#111111', m3secondary: '#aabbff', m3secondaryContainer: '#334455', m3onSecondaryContainer: '#ffffff', m3surfaceContainer: '#222222', m3surfaceContainerHigh: '#333333', m3surfaceContainerHighest: '#444444', m3outline: '#777777', m3error: '#ff3333'})
    property var tPalette: palette
}
""")
    (p/'runtime').mkdir(mode=0o700)
    (p/'bin').mkdir()
    (p/'config/mango').mkdir(parents=True)
    (p/'config/mango/config.conf').write_text('border_px=2\n')
    (p/'bin/mmsg').write_text('''#!/usr/bin/python3
import sys,json,time
if sys.argv[1]=='watch': time.sleep(20)
elif sys.argv[1]=='dispatch': print('{"success": true}')
elif sys.argv[2]=='all-clients': print(json.dumps({'clients':[{'id':17,'appid':'org.example.App','title':'Example','is_floating':False,'width':700,'height':500}]}))
else: print('{}')
''')
    (p/'bin/mmsg').chmod(0o755)
    (p/'shell.qml').write_text('''import QtQuick
import Quickshell
import Caelestia.Config
import qs.services
import qs.modules.windowrules
ShellRoot {
    FloatingWindow {
        implicitWidth: 900; implicitHeight: 760
        Sheet {
            id: editor
            anchors.fill: parent
            initialClient: ({id: 17, appid: "org.example.App", title: "Example"})
        }
    }
    property int stage: 0
    Timer {
        running: true; repeat: true; interval: 300
        onTriggered: {
            if (editor.status && editor.failed) throw new Error(editor.status);
            if (stage === 0) {
                if (editor.initialClient.id !== 17) throw new Error("lost selected window");
                editor.setOption("is_floating", "1");
                editor.save();
                stage++;
            } else if (stage === 1 && editor.rules.length) {
                if (!editor.editingId) throw new Error("saved ID missing");
                editor.edit(editor.rules[0]);
                if (editor.options.is_floating !== "1") throw new Error("edit state lost");
                editor.setOption("is_floating", "0");
                editor.save();
                stage++;
            } else if (stage === 2 && editor.rules[0].options.is_floating === "0") {
                if (editor.rules.length !== 1) throw new Error("editing duplicated a rule");
                editor.run("delete", editor.rules[0].id);
                stage++;
            } else if (stage === 3 && !editor.rules.length) {
                console.log("WINDOW_RULES_QML_PASS"); Qt.quit();
            }
        }
    }
}
''')
    env={**os.environ,'XDG_RUNTIME_DIR':str(p/'runtime'),'QML_IMPORT_PATH':str(root/'build/qml'),'QT_QPA_PLATFORM':'offscreen','QT_QUICK_CONTROLS_STYLE':'Basic','XDG_CONFIG_HOME':str(p/'config'),'XDG_STATE_HOME':str(p/'state'),'XDG_CACHE_HOME':str(p/'cache'),'PATH':str(p/'bin')+':'+os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'}
    try:
        result=subprocess.run(['qs','-p',str(p),'--no-color'],env=env,capture_output=True,text=True,timeout=15)
        output = result.stdout + result.stderr
        assert result.returncode == 0 and 'WINDOW_RULES_QML_PASS' in output, output
        print('Window rule QML checks passed: selected window, create, edit without duplication, delete.')
    except subprocess.TimeoutExpired as e:
        print((e.stdout or b'').decode()+(e.stderr or b'').decode())
        raise
