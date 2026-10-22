pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.services

FocusScope {
    id: root
    required property var initialClient
    property var selectedClient: initialClient
    property var rules: []
    property string editingId: ""
    property var options: ({})
    property string status: ""
    property bool failed: false
    readonly property var windows: Mango.clientState.filter(c => !(c.pid === Quickshell.processId && c.title === "Caelestia Window Rules"))
    readonly property var flags: [
        ["is_floating", "Floating"], ["is_fullscreen", "Fullscreen"],
        ["is_global", "Pinned across workspaces"], ["is_overlay", "Always on top"],
        ["no_border", "No border"], ["no_blur", "No blur"],
        ["no_shadow", "No shadow"], ["no_radius", "Square corners"],
        ["no_animation", "No animation"], ["is_open_silent", "Open without focus"]
    ]
    readonly property var fields: [
        ["width", "Width: pixels or fraction (0–1)"], ["height", "Height: pixels or fraction (0–1)"],
        ["offset_x", "Horizontal offset (%)"], ["offset_y", "Vertical offset (%)"],
        ["focused_opacity", "Focused opacity (0–1)"], ["unfocused_opacity", "Unfocused opacity (0–1)"],
        ["tags", "Workspace tags: 1 or 1|3|5"], ["monitor", "Monitor: e.g. DP-1"]
    ]
    signal close

    function setOption(key, value): void {
        const next = Object.assign({}, options);
        if (value === "") delete next[key];
        else next[key] = value;
        options = next;
    }
    function exact(value): string {
        return "^" + value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$";
    }
    function selectWindow(client): void {
        selectedClient = client;
        editingId = "";
        options = {};
        appId.text = client?.appid ? exact(client.appid) : "";
        titleMatch.text = client?.appid ? "" : client?.title ? exact(client.title) : "";
        status = "";
    }
    function edit(rule): void {
        editingId = rule.id;
        selectedClient = null;
        appId.text = rule.match.app_id ?? "";
        titleMatch.text = rule.match.title ?? "";
        options = Object.assign({}, rule.options);
        status = "";
    }
    function run(operation, value = ""): void {
        if (worker.running) return;
        failed = false;
        status = "";
        worker.command = ["python3", Quickshell.shellPath("assets/mango_rules.py"), operation];
        if (value) worker.command = [...worker.command, value];
        if (operation === "save" && selectedClient)
            worker.command = [...worker.command, "--client", String(selectedClient.id)];
        worker.running = true;
    }
    function save(): void {
        const match = {};
        if (appId.text.trim()) match.app_id = appId.text.trim();
        if (titleMatch.text.trim()) match.title = titleMatch.text.trim();
        run("save", JSON.stringify({ id: editingId, match, options }));
    }
    Component.onCompleted: { selectWindow(initialClient); run("list"); }
    Shortcut { sequence: "Escape"; onActivated: root.close() }

    Process {
        id: worker
        property string diagnostic: ""
        onStarted: diagnostic = ""
        stderr: StdioCollector { onStreamFinished: worker.diagnostic = text.trim() }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    root.failed = !!result.error;
                    root.status = result.error ?? result.message ?? "";
                    if (result.rules) root.rules = result.rules;
                    if (result.message) {
                        root.editingId = result.savedId ?? "";
                        Mango.configReloaded();
                    }
                } catch (error) { root.failed = true; root.status = String(error); }
            }
        }
        onExited: (code, exitStatus) => {
            if (code !== 0 && !root.failed) {
                root.failed = true;
                root.status = diagnostic || "Window rule operation failed";
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.padding.large
        spacing: Tokens.spacing.medium
        RowLayout {
            Layout.fillWidth: true
            StyledText { Layout.fillWidth: true; text: "Window rules"; font: Tokens.font.headline.small }
            StyledText { text: "Super + Ctrl + R"; color: Colours.palette.m3primary }
            IconButton { icon: "close"; type: IconButton.Text; onClicked: root.close() }
        }
        StyledText {
            Layout.fillWidth: true
            text: "Choose a window, configure its defaults, then save and reload Mango."
            color: Colours.palette.m3onSurfaceVariant
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            StyledText { text: "Window" }
            RuleCombo {
                Layout.fillWidth: true
                model: root.windows.map(c => `${c.appid || "Unknown app"} — ${c.title}`)
                currentIndex: root.windows.findIndex(c => c.id === root.selectedClient?.id)
                displayText: currentIndex >= 0 ? currentText : "Select an open window"
                onActivated: index => root.selectWindow(root.windows[index])
            }
            TextButton { text: "New"; type: TextButton.Tonal; disabled: worker.running; onClicked: root.selectWindow(null) }
        }
        Flickable {
            id: formViewport
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: form.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            clip: true
            ColumnLayout {
                id: form
                width: formViewport.width
                spacing: Tokens.spacing.medium
                enabled: !worker.running
                StyledText { text: root.editingId ? "Edit saved rule" : "Create rule"; font: Tokens.font.title.medium }
                StyledTextField {
                    id: appId
                    type: StyledTextField.Filled
                    Layout.fillWidth: true
                    placeholderText: "App ID expression (e.g. ^org.mozilla.firefox$)"
                    verticalPadding: Tokens.padding.small
                }
                RowLayout {
                    Layout.fillWidth: true
                    StyledTextField {
                        id: titleMatch
                        type: StyledTextField.Filled
                        Layout.fillWidth: true
                        placeholderText: "Title expression (optional)"
                        verticalPadding: Tokens.padding.small
                    }
                    TextButton {
                        text: "Use title"; type: TextButton.Tonal
                        disabled: !root.selectedClient?.title
                        onClicked: titleMatch.text = root.exact(root.selectedClient.title)
                    }
                }
                StyledText {
                    Layout.fillWidth: true
                    text: "Both expressions must match when both are set. Default leaves that option unchanged."
                    wrapMode: Text.Wrap
                    color: Colours.palette.m3onSurfaceVariant
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: root.width >= 720 ? 2 : 1
                    columnSpacing: Tokens.spacing.large
                    rowSpacing: Tokens.spacing.small
                    Repeater {
                        model: root.flags
                        RowLayout {
                            id: flagRow
                            required property var modelData
                            Layout.fillWidth: true
                            StyledText { Layout.fillWidth: true; text: flagRow.modelData[1] }
                            RuleCombo {
                                model: ["Default", "On", "Off"]
                                currentIndex: root.options[flagRow.modelData[0]] === "1" ? 1 : root.options[flagRow.modelData[0]] === "0" ? 2 : 0
                                onActivated: index => root.setOption(flagRow.modelData[0], index === 0 ? "" : index === 1 ? "1" : "0")
                            }
                        }
                    }
                    Repeater {
                        model: root.fields
                        ColumnLayout {
                            id: fieldRow
                            required property var modelData
                            Layout.fillWidth: true
                            StyledText { text: fieldRow.modelData[1]; font: Tokens.font.body.small }
                            StyledTextField {
                                Layout.fillWidth: true
                                type: StyledTextField.Filled
                                text: root.options[fieldRow.modelData[0]] ?? ""
                                placeholderText: "Default"
                                verticalPadding: Tokens.padding.small
                                onTextEdited: root.setOption(fieldRow.modelData[0], text)
                            }
                        }
                    }
                }
                StyledText {
                    Layout.fillWidth: true
                    text: "Saved rules"
                    font: Tokens.font.title.medium
                }
                StyledText {
                    visible: !root.rules.length
                    text: "No saved rules yet."
                    color: Colours.palette.m3onSurfaceVariant
                }
                Repeater {
                    model: root.rules
                    RowLayout {
                        id: savedRow
                        required property var modelData
                        Layout.fillWidth: true
                        StyledText {
                            Layout.fillWidth: true
                            text: Object.entries(savedRow.modelData.match).map(([k, v]) => `${k}: ${v}`).join(" · ")
                            elide: Text.ElideRight
                        }
                        TextButton { text: "Edit"; type: TextButton.Tonal; onClicked: root.edit(savedRow.modelData) }
                        IconButton { icon: "delete"; type: IconButton.Text; onClicked: root.run("delete", savedRow.modelData.id) }
                    }
                }
            }
        }
        StyledText {
            Layout.fillWidth: true
            text: root.status || "Rules persist across restarts. Some effects take effect when the next matching window opens."
            color: root.failed ? Colours.palette.m3error : Colours.palette.m3onSurfaceVariant
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            TextButton { text: "Close"; type: TextButton.Tonal; onClicked: root.close() }
            TextButton { text: worker.running ? "Working…" : "Save and reload Mango"; disabled: worker.running; onClicked: root.save() }
        }
    }

    component RuleCombo: ComboBox {
        id: combo
        implicitHeight: 36
        implicitWidth: 116
        palette.window: Colours.palette.m3surfaceContainerHigh
        palette.base: Colours.palette.m3surfaceContainerHigh
        palette.text: Colours.palette.m3onSurface
        palette.buttonText: Colours.palette.m3onSurface
        palette.highlight: Colours.palette.m3primary
        palette.highlightedText: Colours.palette.m3onPrimary
        background: StyledRect {
            radius: Tokens.rounding.small
            color: Colours.palette.m3surfaceContainerHigh
        }
        contentItem: StyledText {
            text: combo.displayText
            leftPadding: Tokens.padding.small
            rightPadding: 28
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: MaterialIcon {
            x: combo.width - width - Tokens.padding.extraSmall
            anchors.verticalCenter: parent.verticalCenter
            text: "expand_more"
        }
    }

}
