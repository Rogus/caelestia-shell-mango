import QtQuick
import Caelestia
import Quickshell
import qs.services

ShellRoot {
    id: root
    property int stage: 0
    property int ticks: 0
    property int waitTicks: 0
    readonly property string scenario: Quickshell.env("RECORDER_CHECK_SCENARIO")

    function check(ok, message): void {
        if (!ok) throw new Error(message);
    }
    function next(): void { stage++; waitTicks = 0; }

    Timer {
        interval: 40
        running: true
        repeat: true
        onTriggered: {
            root.check(++root.ticks < 250, "Recorder scenario timed out at stage " + root.stage);
            root.waitTicks++;
            if (root.scenario !== "normal") {
                if (root.stage === 0) {
                    Recorder.start(root.scenario === "missing-slurp" ? ["-r"] : []);
                    root.next();
                } else if (!Recorder.starting && !Recorder.selecting && Toaster.toasts.length > 0) {
                    root.check(!Recorder.running, "Failed launch reported recording");
                    console.log("RECORDER_SERVICE_PASS " + root.scenario);
                    Qt.quit();
                }
                return;
            }
            switch (root.stage) {
            case 0:
                Recorder.start(["-sr"]);
                Recorder.start(["-s"]); // Must not duplicate or replace the pending mode.
                root.check(Recorder.starting && Recorder.selecting, "Combined flags must select a region");
                root.next();
                break;
            case 1:
                if (!Recorder.running || Recorder.starting) return;
                Recorder.togglePause();
                root.next();
                break;
            case 2:
                if (!Recorder.paused) return;
                Recorder.togglePause();
                root.next();
                break;
            case 3:
                if (Recorder.paused) return;
                Recorder.stop();
                root.next();
                break;
            case 4:
                if (Recorder.running) return;
                Recorder.start(["-r"]);
                root.next();
                break;
            case 5:
                // Let the picker start, then cancel while it delays termination.
                if (root.waitTicks < 4) return;
                Recorder.stop();
                Recorder.start(["-s"]); // Must wait for the cancelled picker to exit.
                root.check(Recorder.starting && !Recorder.selecting, "Cancelled picker must retain the start guard");
                root.next();
                break;
            case 6:
                if (Recorder.starting) return;
                root.check(!Recorder.running, "Late cancelled geometry started recording");
                Recorder.start(["-r"]); // Third picker exits as if Escape were pressed.
                root.next();
                break;
            case 7:
                if (Recorder.starting || Recorder.selecting) return;
                root.check(!Recorder.running, "Escape must cancel recording");
                Recorder.start(["-r", "-s"]);
                root.next();
                break;
            case 8:
                if (!Recorder.running || Recorder.starting) return;
                Recorder.stop();
                root.next();
                break;
            case 9:
                if (Recorder.running) return;
                // Cancel a start before the deferred command queue runs.
                Recorder.start();
                Recorder.stop();
                root.check(!Recorder.starting, "Queued start must cancel immediately");
                root.next();
                break;
            case 10:
                if (Recorder.queue.length || root.waitTicks < 8) return;
                root.check(!Recorder.running && !Recorder.starting, "Recorder must finish idle");
                Recorder.start(["-s"]);
                root.next();
                break;
            case 11:
                Recorder.stop(); // Stop while the start helper is still in flight.
                root.next();
                break;
            case 12:
                if (Recorder.queue.length || root.waitTicks < 8 || Recorder.running) return;
                root.check(!Recorder.starting, "Stopping in-flight start must clear the guard");
                console.log("RECORDER_SERVICE_PASS normal");
                Qt.quit();
            }
        }
    }
}
