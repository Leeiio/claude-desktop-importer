"""Where Claude Code and Claude Desktop keep their files, and whether the desktop app is running."""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

from . import ImporterError

ACTIVE_PROFILE = re.compile(r"\[LocalSessionManager\] Initialization succeeded — accountId=([\w-]+), orgId=([\w-]+)")


def claude_dir(override: str | None = None) -> str:
    """The Claude Code config folder that holds projects/<folder>/<session>.jsonl."""
    return os.path.abspath(os.path.expanduser(override or os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


def _store_candidates():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        yield os.path.join(home, "Library", "Application Support", "Claude", "claude-code-sessions")
    elif sys.platform == "win32":
        local, roaming = os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")
        if local:  # Microsoft Store (MSIX) installs keep app data in a package folder
            yield from glob.glob(os.path.join(local, "Packages", "Claude_*", "LocalCache", "Roaming", "Claude",
                                              "claude-code-sessions"))
        if roaming:
            yield os.path.join(roaming, "Claude", "claude-code-sessions")
    else:
        config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        yield os.path.join(config, "Claude", "claude-code-sessions")


def _log_candidates():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        yield os.path.join(home, "Library", "Logs", "Claude", "main.log")
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        yield os.path.join(os.environ["APPDATA"], "Claude", "logs", "main.log")


def store_root(override: str | None = None) -> str:
    """Claude Desktop's claude-code-sessions folder."""
    if override:
        path = os.path.abspath(os.path.expanduser(override))
        if not os.path.isdir(path):
            raise ImporterError("--store folder does not exist: %s" % path)
        return path
    for path in _store_candidates():
        if os.path.isdir(path):
            return path
    raise ImporterError("Could not find Claude Desktop's claude-code-sessions folder. Open the Code tab in "
                        "Claude Desktop once, or pass --store.")


def profiles(root: str) -> list[str]:
    """Every <account>/<org> folder; each one is a separate sidebar."""
    return sorted(p for p in glob.glob(os.path.join(root, "*", "*")) if os.path.isdir(p))


def _active_profile_from_log(root: str) -> str | None:
    for log in _log_candidates():
        try:
            with open(log, errors="replace") as fh:
                matches = ACTIVE_PROFILE.findall(fh.read())
        except OSError:
            continue
        if matches:
            path = os.path.join(root, *matches[-1])
            if os.path.isdir(path):
                return path
    return None


def pick_profile(root: str, choice: str | None = None) -> str:
    """The sidebar to work on: the one asked for, the only one, or the one Claude Desktop last signed in to."""
    found = profiles(root)
    if choice:
        path = choice if os.path.isabs(choice) else os.path.join(root, choice)
        if path not in found:
            raise ImporterError("No such profile: %s\nAvailable: %s" % (choice, ", ".join(_rel(root, p) for p in found)))
        return path
    if len(found) == 1:
        return found[0]
    active = _active_profile_from_log(root)
    if active:
        return active
    if not found:
        raise ImporterError("Claude Desktop has no session list yet in %s. Sign in and open the Code tab first." % root)
    raise ImporterError("Several accounts/organizations found; pick one with --profile:\n  "
                        + "\n  ".join(_rel(root, p) for p in found))


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def app_running() -> bool | None:
    """Whether Claude Desktop is running; None where we cannot tell (the CLI and the app share names there)."""
    if sys.platform != "darwin":
        return None
    # pgrep can miss the app; ps lists it reliably.
    out = subprocess.run(["ps", "-axo", "comm"], capture_output=True, text=True).stdout
    return any(line.strip().endswith("/Claude.app/Contents/MacOS/Claude") for line in out.splitlines())


def transcript_in_use(path: str) -> bool:
    """Whether a running Claude Code process has the transcript open (it may still be writing to it)."""
    try:
        out = subprocess.run(["lsof", "-Fc", "--", path], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    # Readers such as SpecStory also open transcripts; only Claude processes count.
    return any(line.startswith("c") and "claude" in line.lower() for line in out.splitlines())
