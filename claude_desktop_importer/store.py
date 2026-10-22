"""Claude Desktop's sidebar records (claude-code-sessions/<account>/<org>/local_<id>.json) and their backups."""
from __future__ import annotations

import glob
import json
import os
import shutil
import tempfile
from datetime import datetime

from . import ImporterError, __version__

MANIFEST = "manifest.json"


def record_name(session_id: str) -> str:
    return "local_%s.json" % session_id


def load_records(profile_dir: str) -> dict:
    """cliSessionId -> (path, record) for every session in this sidebar, archived ones included."""
    out = {}
    for path in glob.glob(os.path.join(profile_dir, "local_*.json")):
        try:
            with open(path) as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("cliSessionId"):
            out[rec["cliSessionId"]] = (path, rec)
    return out


def indexed_ids(records: dict) -> set:
    """Every transcript the sidebar already shows. A Desktop session that was compacted or continued moves on to a
    new transcript and lists the ones before it in priorCliSessionIds; those are part of it, not missing."""
    ids = set(records)
    for _, rec in records.values():
        ids.update(i for i in rec.get("priorCliSessionIds") or [] if isinstance(i, str))
    return ids


def write_json(path: str, data: dict) -> None:
    """Write the way Claude Desktop does (compact, owner-only), atomically so a crash never leaves half a file."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def back_up(backup_root: str, profile_dir: str, action: str, added: list, modified: list) -> str:
    """Save what a change is about to do, before doing it: originals of modified files plus the names it adds."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(backup_root, "%s-%s" % (stamp, action))
    os.makedirs(os.path.join(backup_dir, "files"))
    for name in modified:
        shutil.copy2(os.path.join(profile_dir, name), os.path.join(backup_dir, "files", name))
    manifest = {"tool": "claude-desktop-importer", "version": __version__, "action": action,
                "created": datetime.now().isoformat(timespec="seconds"), "profile": profile_dir,
                "added": sorted(added), "modified": sorted(modified)}
    with open(os.path.join(backup_dir, MANIFEST), "w") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return backup_dir


def read_manifest(backup_dir: str) -> dict:
    try:
        with open(os.path.join(backup_dir, MANIFEST)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        raise ImporterError("Not a claude-desktop-importer backup (no readable %s): %s" % (MANIFEST, backup_dir))


def list_backups(backup_root: str) -> list:
    """(path, manifest) for every backup, oldest first."""
    if not os.path.isdir(backup_root):
        return []
    out = []
    for name in sorted(os.listdir(backup_root)):
        path = os.path.join(backup_root, name)
        try:
            out.append((path, read_manifest(path)))
        except ImporterError:
            continue
    return out


def restore(backup_dir: str) -> tuple:
    """Undo one change: remove the records it added and put back the ones it modified."""
    manifest = read_manifest(backup_dir)
    profile_dir = manifest["profile"]
    if not os.path.isdir(profile_dir):
        raise ImporterError("The sidebar folder this backup belongs to is gone: %s" % profile_dir)
    removed = 0
    for name in manifest["added"]:
        path = os.path.join(profile_dir, name)
        if os.path.exists(path):
            os.unlink(path)
            removed += 1
    for name in manifest["modified"]:
        # Byte-for-byte copy through a temp file, so the original comes back exactly as Claude Desktop wrote it.
        fd, tmp = tempfile.mkstemp(dir=profile_dir, suffix=".tmp")
        os.close(fd)
        shutil.copy2(os.path.join(backup_dir, "files", name), tmp)
        os.replace(tmp, os.path.join(profile_dir, name))
    return removed, len(manifest["modified"]), profile_dir
