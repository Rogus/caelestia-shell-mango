pragma Singleton

import QtQuick
import Quickshell
import Caelestia.Config
import qs.services

Singleton {
    id: root

    property var window: null
    property int floatedClient: -1
    readonly property bool opened: window !== null

    function toggle(): void {
        if (window) { close(); return; }
        const target = Mango.focusedClientData;
        window = sheet.createObject(root, {
            selectedClient: target,
            screen: Quickshell.screens.find(s => s.name === Mango.focusedOutput) ?? Quickshell.screens[0]
        });
    }

    function close(): void {
        const current = window;
        window = null;
        floatedClient = -1;
        if (current) current.destroy();
    }

    // A manually added IPC binding should also produce a floating sheet, even
    // when the user hasn't sourced the bundled window rule yet.
    Connections {
        target: Mango
        function onClientStateChanged(): void {
            if (!root.window) return;
            const client = Mango.clientState.find(c => c.pid === Quickshell.processId && c.title === "Caelestia Window Rules");
            if (client && root.floatedClient !== client.id) {
                root.floatedClient = client.id;
                if (!client.is_floating) Mango.send("togglefloating", "", client.id);
                const width = Math.round(Math.min(900, (root.window.screen?.width ?? 1200) * 0.86));
                const height = Math.round(Math.min(760, (root.window.screen?.height ?? 900) * 0.82));
                Mango.send("resizewin", `${width},${height}`, client.id);
                Mango.send("centerwin", "", client.id);
            }
        }
    }

    Component {
        id: sheet
        FloatingWindow {
            id: win
            required property var selectedClient
            title: "Caelestia Window Rules"
            color: Colours.palette.m3surface
            implicitWidth: Math.min(900, (screen?.width ?? 1200) * 0.86)
            implicitHeight: Math.min(760, (screen?.height ?? 900) * 0.82)
            minimumSize.width: 560
            minimumSize.height: 420
            contentItem.Config.screen: screen.name
            contentItem.Tokens.screen: screen.name
            onClosed: root.close()
            onVisibleChanged: { if (!visible && root.window === win) root.close(); }

            Sheet {
                anchors.fill: parent
                initialClient: win.selectedClient
                onClose: root.close()
            }
        }
    }
}
