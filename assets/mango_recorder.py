#!/usr/bin/env python3
"""Own one detached recorder per login session, with PID reuse protection."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def process_identity(pid):
    try:
        # comm can contain spaces and parentheses; starttime is field 22.
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if stat[0] == "Z" else stat[19]
    except (OSError, IndexError):
        return None


def status(state):
    if not state or not state.get("identity") or process_identity(state.get("pid", -1)) != state.get("identity"):
        return {"running": False, "paused": False, "elapsed": 0}
    now = time.time()
    end = state.get("paused_at", now) if state.get("paused") else now
    return {**state, "running": True, "elapsed": max(0, end - state["started"] - state.get("paused_seconds", 0))}


def save(path, state):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        json.dump(state, stream)
        temporary = Path(stream.name)
    temporary.replace(path)


def system_audio_device():
    result = subprocess.run(["gpu-screen-recorder", "--list-audio-devices"],
                            capture_output=True, text=True, timeout=5, check=True)
    devices = {line.split("|", 1)[0] for line in result.stdout.splitlines()}
    # New releases renamed the default-output alias. Keep older versions working.
    return "default_output" if "default_output" in devices else "defaultoutput"


def operate(action, state, output="", destination="", sound=False, region=""):
    current = status(state)
    if action == "start" and not current["running"]:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        command = ["gpu-screen-recorder", "-w", "region" if region else output, "-f", "60", "-o", destination]
        if region:
            command += ["-region", region]
        if sound:
            command += ["-a", system_audio_device()]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(0.3)
        if process.poll() is not None:
            raise RuntimeError("Screen recorder failed to start; check capture permissions and gpu-screen-recorder installation")
        state = {"pid": process.pid, "identity": process_identity(process.pid), "started": time.time(), "paused": False, "paused_seconds": 0, "path": destination}
    elif action in ("stop", "pause") and current["running"]:
        # pidfds ensure a recycled PID cannot be signalled after validation.
        fd = os.pidfd_open(state["pid"])
        try:
            if process_identity(state["pid"]) == state["identity"]:
                signal.pidfd_send_signal(fd, signal.SIGINT if action == "stop" else signal.SIGUSR2)
                if action == "pause":
                    now = time.time()
                    if state["paused"]:
                        state["paused_seconds"] += now - state.pop("paused_at")
                    else:
                        state["paused_at"] = now
                    state["paused"] = not state["paused"]
        finally:
            os.close(fd)
    return state if status(state)["running"] else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "pause", "status"))
    parser.add_argument("--output", default="screen")
    parser.add_argument("--destination", default="")
    parser.add_argument("--sound", action="store_true")
    parser.add_argument("--region", default="")
    args = parser.parse_args()
    directory = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())) / f"caelestia-recorder-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.stat().st_uid != os.getuid() or directory.is_symlink():
        raise RuntimeError("Recorder state directory is not owned by this user")
    path = directory / "state.json"
    with (directory / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            state = {}
        state = operate(args.action, state, args.output, args.destination, args.sound, args.region)
        save(path, state)
        print(json.dumps(status(state)))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
