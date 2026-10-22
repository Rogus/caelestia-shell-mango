#!/usr/bin/env python3
"""Persist Caelestia window rules and reload Mango after each change."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import uuid

from mango_blur import atomic_write

BOOLS = {"is_floating", "is_fullscreen", "is_global", "is_overlay", "no_border",
         "no_blur", "no_shadow", "no_radius", "no_animation", "is_open_silent"}
NUMBERS = {"width": (0.01, 9999), "height": (0.01, 9999),
           "focused_opacity": (0, 1), "unfocused_opacity": (0, 1),
           "offset_x": (-999, 999), "offset_y": (-999, 999)}
MARKER = "# caelestia-rule "


def paths():
    folder = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "mango"
    requested = os.environ.get("CAELESTIA_MANGO_CONFIG")
    config = Path(requested).expanduser() if requested else next(
        (p for p in (folder / "config.conf", folder / "config.toml") if p.exists()), folder / "config.conf")
    return config, folder / "caelestia-window-rules.conf"


def validate(rule):
    if not isinstance(rule, dict):
        raise ValueError("Invalid window rule")
    matches = rule.get("match", {})
    options = rule.get("options", {})
    if not isinstance(matches, dict) or not isinstance(options, dict):
        raise ValueError("Invalid rule fields")
    if not matches or set(matches) - {"app_id", "title"}:
        raise ValueError("Match an app ID, title, or both")
    for value in matches.values():
        if not isinstance(value, str) or not value.strip() or any(c in value for c in ",#\n\r\0"):
            raise ValueError("Matches cannot contain commas, #, or line breaks; use the app ID or a simpler expression")
        checked = subprocess.run(["grep", "-E", "-q", "--", value], input="", capture_output=True, text=True, timeout=2)
        if checked.returncode == 2:
            raise ValueError("Invalid match expression: " + checked.stderr.strip())
    if not options:
        raise ValueError("Choose at least one rule option")
    options = dict(options)
    for key, value in options.items():
        if key in BOOLS:
            if str(value) not in ("0", "1"):
                raise ValueError(f"{key} must be 0 or 1")
        elif key in NUMBERS:
            low, high = NUMBERS[key]
            number = float(value)
            if not math.isfinite(number) or not low <= number <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
            if key.startswith("offset_") and not number.is_integer():
                raise ValueError(f"{key} must be a whole number")
            options[key] = str(int(number)) if number.is_integer() else str(number)
        elif key == "tags":
            if not re.fullmatch(r"(?:[0-9]|[12][0-9]|3[01])(?:\|(?:[0-9]|[12][0-9]|3[01]))*", str(value)):
                raise ValueError("Tags must be 0–31, separated by |")
        elif key == "monitor":
            if not isinstance(value, str) or not value.strip() or any(c in value for c in ",#\n\r\0"):
                raise ValueError("Invalid monitor name")
        else:
            raise ValueError(f"Unsupported rule option: {key}")
    identity = rule.get("id") or uuid.uuid4().hex
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Invalid rule ID")
    return {"id": identity, "match": matches, "options": {k: str(v) for k, v in options.items()}}


def load_rules(fragment):
    if not fragment.exists():
        return []
    return [validate(json.loads(line[len(MARKER):])) for line in fragment.read_text().splitlines() if line.startswith(MARKER)]


def render(rules):
    lines = ["# Managed by Caelestia Window Rules. Edit using the rule manager."]
    for rule in rules:
        lines.extend([MARKER + json.dumps(rule, ensure_ascii=True),
                      "window_rule=" + ",".join(f"{k}:{v}" for k, v in {**rule["match"], **rule["options"]}.items())])
    return "\n".join(lines) + "\n"


def config_with_source(config, fragment):
    original = config.read_text() if config.exists() else "source=/etc/mango/config.conf\n"
    if config.suffix == ".toml":
        sources = tomllib.loads(original).get("global", {}).get("source", [])
        if isinstance(sources, str):
            sources = [sources]
        included = any(resolve_source(s, config) == fragment for s in sources)
    else:
        included = any(resolve_source(line.split("=", 1)[1].split("#", 1)[0].strip(), config) == fragment
                       for line in original.splitlines() if re.match(r"^\s*source\s*=", line))
    if included:
        return original, original
    if config.is_symlink() or config.suffix == ".toml":
        raise ValueError(f"Add source={fragment} to your managed Mango configuration first (TOML: [global].source)")
    if any(c in str(fragment) for c in "#\n\r"):
        raise ValueError("Unsupported config directory name")
    return original, original.rstrip() + f"\n\n# Caelestia window rules\nsource={fragment}\n"


def resolve_source(source, config):
    path = Path(os.path.expandvars(str(source))).expanduser()
    return (config.parent / path if not path.is_absolute() else path).absolute()


def dispatch(command):
    result = subprocess.run(["mmsg", "dispatch", command], capture_output=True, text=True, timeout=10)
    payload = json.loads(result.stdout or "{}")
    if result.returncode or not payload.get("success"):
        raise RuntimeError(payload.get("error") or result.stderr or "Mango command failed")


def apply_live(client_id, options):
    """Apply actions available through IPC to the captured client, never the editor."""
    result = subprocess.run(["mmsg", "get", "all-clients"], capture_output=True, text=True, timeout=10, check=True)
    client = next((c for c in json.loads(result.stdout).get("clients", []) if c["id"] == client_id), None)
    if not client:
        return "Selected window has closed; the rule will apply to future windows."
    for key, action in (("is_floating", "togglefloating"), ("is_fullscreen", "togglefullscreen"),
                        ("is_global", "toggleglobal"), ("is_overlay", "toggleoverlay")):
        if key in options and bool(client.get(key)) != (options[key] == "1"):
            dispatch(f"{action},client,{client_id}")
    # Geometry is safe to apply directly only to floating windows and pixel sizes.
    floating = options.get("is_floating", str(int(bool(client.get("is_floating"))))) == "1"
    if floating and any(k in options for k in ("width", "height")):
        width = float(options.get("width", client.get("width", 0)))
        height = float(options.get("height", client.get("height", 0)))
        if width >= 1 and height >= 1:
            dispatch(f"resizewin,{round(width)},{round(height)},client,{client_id}")
            dispatch(f"centerwin,client,{client_id}")
    return "Floating, fullscreen, pinning and pixel size apply now. Other options apply when a matching window opens."


def change(config, fragment, operation, value, client_id=-1):
    original, updated = config_with_source(config, fragment)
    rules = load_rules(fragment)
    if operation == "save":
        rule = validate(value)
        rules = [r for r in rules if r["id"] != rule["id"]] + [rule]
    else:
        rules = [r for r in rules if r["id"] != value]
    old_fragment = fragment.read_text() if fragment.exists() else None
    atomic_write(fragment, render(rules))
    try:
        if updated != original:
            backup = config.with_name(config.name + ".before-caelestia-rules")
            if config.exists() and not backup.exists():
                backup.write_text(original)
            atomic_write(config, updated)
        dispatch("reload_config")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        # Keep both files consistent and restore the previous loaded rules.
        if old_fragment is None:
            fragment.unlink(missing_ok=True)
        else:
            atomic_write(fragment, old_fragment)
        if updated != original:
            atomic_write(config, original)
        try:
            dispatch("reload_config")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            pass
        raise
    message = "Rules saved; Mango reloaded."
    if operation == "save" and client_id >= 0:
        try:
            message += " " + apply_live(client_id, rule["options"])
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            message += f" Could not update the selected window: {error}"
    return {"rules": rules, "message": message, "savedId": rule["id"] if operation == "save" else ""}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("list", "save", "delete"))
    parser.add_argument("value", nargs="?")
    parser.add_argument("--client", type=int, default=-1)
    args = parser.parse_args()
    config, fragment = paths()
    if args.operation == "list":
        result = {"rules": load_rules(fragment)}
    else:
        fragment.parent.mkdir(parents=True, exist_ok=True)
        with (fragment.parent / ".caelestia-rules.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = json.loads(args.value) if args.operation == "save" else args.value
            result = change(config, fragment, args.operation, value, args.client)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(1)
