"""Decide what to import or repair. Nothing here writes; the CLI applies the plans."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from . import paths, store, transcript
from .transcript import Transcript, clip

# Closer than this to the transcript's real times is noise, not a misplaced session.
TIME_TOLERANCE_MS = 5 * 60 * 1000


@dataclass
class Candidate:
    transcript: Transcript
    reason: str | None = None  # why it is skipped; None means importable

    @property
    def importable(self) -> bool:
        return self.reason is None


@dataclass
class ScanResult:
    total: int
    indexed: int
    candidates: list


def scan(claude_dir: str, profile_dir: str, include_desktop: bool = False, check_in_use: bool = True) -> ScanResult:
    """Every CLI transcript that is not in the sidebar yet, each marked importable or with the reason it is not."""
    known = store.indexed_ids(store.load_records(profile_dir))
    total = indexed = 0
    candidates = []
    for path in transcript.find_transcripts(claude_dir):
        total += 1
        if os.path.basename(path)[: -len(".jsonl")] in known:
            indexed += 1  # already in the sidebar; no need to read it
            continue
        t = transcript.read(path)
        candidates.append(Candidate(t, _skip_reason(t, include_desktop, check_in_use)))
    return ScanResult(total, indexed, candidates)


def _skip_reason(t: Transcript, include_desktop: bool, check_in_use: bool) -> str | None:
    if t.messages == 0:
        return "no messages"
    if not t.cwd:
        return "no working directory recorded"
    if not t.folder_matches_cwd():
        return "stored outside its working directory's project folder"
    if not os.path.isdir(t.cwd):
        return "working directory no longer exists"
    if t.origin == "claude-desktop" and not include_desktop:
        # A desktop session missing from its own sidebar was most likely removed there on purpose.
        return "started in Claude Desktop and no longer in its sidebar (use --include-desktop)"
    if check_in_use and paths.transcript_in_use(t.path):
        return "open in a running Claude Code process"
    return None


def build_record(t: Transcript, now_ms: int | None = None) -> dict:
    """A sidebar record shaped like the ones Claude Desktop's Import writes, but with real times and the best title."""
    rec = {
        "sessionId": "local_" + t.session_id,
        "cliSessionId": t.session_id,
        "cwd": t.cwd,
        "originCwd": t.cwd,
        "createdAt": t.first_at,
        "lastActivityAt": t.last_at,
        "model": t.model,
        "isArchived": False,
        "title": clip(t.best_title) if t.best_title else None,
        "permissionMode": t.permission_mode or "default",
        "interruptedAwaitingPerson": None,
        "indexedAt": now_ms if now_ms is not None else int(time.time() * 1000),
        "steeredByRemoteClient": None,
        "alwaysAllowedReasons": [],
        "sessionPermissionUpdates": [],
        "adoptedFromOtherSurface": True,
    }
    for optional in ("model", "title"):  # Import leaves these out when it has nothing
        if rec[optional] is None:
            del rec[optional]
    return rec


@dataclass
class Repair:
    path: str
    record: dict
    changes: dict


def plan_repairs(claude_dir: str, profile_dir: str) -> list:
    """Fix records adopted from other surfaces: real activity times, and a real title instead of a raw prompt.

    Desktop-native records and titles the user set themselves (titleSource "user") are left alone.
    """
    by_id = {os.path.basename(p)[: -len(".jsonl")]: p for p in transcript.find_transcripts(claude_dir)}
    repairs = []
    for session_id, (path, rec) in sorted(store.load_records(profile_dir).items()):
        if not rec.get("adoptedFromOtherSurface") or session_id not in by_id:
            continue
        t = transcript.read(by_id[session_id])
        changes = {}
        if t.first_at and abs((rec.get("createdAt") or 0) - t.first_at) > TIME_TOLERANCE_MS:
            changes["createdAt"] = t.first_at
        if t.last_at and abs((rec.get("lastActivityAt") or 0) - t.last_at) > TIME_TOLERANCE_MS:
            changes["lastActivityAt"] = t.last_at
        title = _better_title(t, rec)
        if title:
            changes["title"] = title
        if changes:
            repairs.append(Repair(path, rec, changes))
    return repairs


def _better_title(t: Transcript, rec: dict) -> str | None:
    if rec.get("titleSource") == "user":
        return None
    current = rec.get("title") or ""
    named = t.custom_title or t.ai_title
    if named:
        return None if current.startswith(named[:20]) else clip(named)
    # No title anywhere: only replace a title built from a bare slash command or IDE context.
    if t.first_prompt and not current.lower().startswith(t.first_prompt[:20].lower()):
        return clip(t.first_prompt)
    return None


def apply_repair(repair: Repair) -> dict:
    rec = dict(repair.record)
    if "title" in repair.changes and rec.get("title"):
        # Same field Claude Desktop uses when you rename a session.
        rec["previousTitles"] = list(rec.get("previousTitles") or []) + [rec["title"]]
    rec.update(repair.changes)
    store.write_json(repair.path, rec)
    return rec
