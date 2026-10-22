pragma Singleton

import Caelestia
import QtQuick
import Quickshell
import Quickshell.Io
import qs.services
import qs.utils

Singleton {
    id: root

    property bool running: false
    property bool paused: false
    property real elapsed: 0
    property int refCount: 0
    property list<string> startArgs
    property var queue: []
    property bool selecting: false
    property bool starting: false

    function getNewRecordingPath(): string {
        return `${Paths.recsdir}/recording_${Date.now()}.mp4`;
    }

    function request(args: var): void {
        queue = [...queue, args];
        Qt.callLater(root.runNext);
    }

    function runNext(): void {
        if (control.running || !queue.length) return;
        control.command = ["python3", Quickshell.shellPath("assets/mango_recorder.py"), ...queue[0]];
        queue = queue.slice(1);
        control.running = true;
    }

    function startRecording(regionGeometry = ""): void {
        const args = ["start", "--output", Mango.focusedOutput || "screen", "--destination", getNewRecordingPath()];
        if (startArgs.includes("-s")) args.push("--sound");
        if (regionGeometry) args.push("--region", regionGeometry);
        request(args);
    }

    function start(extraArgs = []): void {
        if (running || selecting || starting) return;
        // Accept both separate flags and the legacy combined -sr/-rs spelling.
        const normalized = [];
        for (const arg of extraArgs) {
            if (/^-[rs]+$/.test(arg)) {
                for (const flag of arg.slice(1)) normalized.push("-" + flag);
            } else normalized.push(arg);
        }
        startArgs = normalized;
        starting = true;
        if (startArgs.includes("-r")) {
            selecting = true;
            slurpProc.completed = false;
            slurpProc.running = true;
        } else startRecording();
    }

    function stop(): void {
        if (selecting) {
            selecting = false;
            // Keep the start guard until the old picker has actually exited.
            // Otherwise a second start can consume its late geometry output.
            slurpProc.running = false;
            return;
        }
        // Cancel a start still queued behind a status/stop command.
        if (queue.some(args => args[0] === "start")) {
            queue = queue.filter(args => args[0] !== "start");
            starting = false;
        }
        request(["stop"]);
    }
    function togglePause(): void { if (running) request(["pause"]); }

    IpcHandler {
        target: "recorder"
        function toggle(mode: string): void {
            if (root.running || root.selecting || root.starting) root.stop();
            else root.start(mode === "region-sound" ? ["-r", "-s"]
                : mode === "region" ? ["-r"] : mode === "sound" ? ["-s"] : []);
        }
        function stop(): void { root.stop(); }
    }

    Process {
        id: slurpProc
        command: ["slurp", "-f", "%wx%h+%x+%y"]
        property string geometry
        property bool completed: true
        stdout: StdioCollector { onStreamFinished: slurpProc.geometry = text.trim() }
        onRunningChanged: {
            // FailedToStart emits runningChanged without exited in Quickshell.
            if (!running && !completed) {
                completed = true;
                const notify = root.selecting;
                root.selecting = false;
                root.starting = false;
                if (notify) Toaster.toast("Recording", "Could not start region selection. Check that slurp is installed.", "videocam_off");
            }
        }
        onExited: code => {
            completed = true;
            const accepted = root.selecting && code === 0 && geometry.length > 0;
            root.selecting = false;
            if (accepted) root.startRecording(geometry);
            else root.starting = false;
            geometry = "";
        }
    }

    Process {
        id: control
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const state = JSON.parse(text);
                    root.running = state.running;
                    root.paused = state.paused;
                    root.elapsed = state.elapsed;
                } catch (error) { console.warn("Recorder state:", error); }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim()) Toaster.toast("Recording", text.trim(), "videocam_off");
            }
        }
        onRunningChanged: {
            if (!running) {
                if (root.starting && command[2] === "start") {
                    root.starting = false;
                    Toaster.toast("Recording", "Could not start the recorder helper. Check that python3 is installed.", "videocam_off");
                }
                Qt.callLater(root.runNext);
            }
        }
        onExited: {
            if (command[2] === "start") root.starting = false;
            Qt.callLater(root.runNext);
        }
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: { if (!root.starting && !control.running && !root.queue.length) root.request(["status"]); }
    }
}
