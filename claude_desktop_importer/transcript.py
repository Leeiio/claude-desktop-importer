"""Read just enough of a Claude Code transcript (projects/<folder>/<session>.jsonl) to index it."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TAG = re.compile(r"<[^>]+>")
IDE_CONTEXT = re.compile(r"^\s*<ide_\w+>.*?</ide_\w+>\s*", re.S)
COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
TITLE_LIMIT = 60

# Entrypoints of interactive surfaces. Anything else (sdk-cli, sdk-ts, sdk-py...) is a headless/SDK session,
# which Claude Desktop's own Import never offers.
INTERACTIVE = {"cli", "claude-vscode", "claude-desktop", "claude-jetbrains"}


def to_ms(timestamp: str) -> int:
    return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)


def clip(title: str, limit: int = TITLE_LIMIT) -> str:
    if len(title) <= limit:
        return title
    # Forks are titled "<first prompt> (fork)"; keep the marker visible after clipping.
    suffix = " (fork)" if title.endswith("(fork)") else ""
    return title[: limit - len(suffix) - 1] + "…" + suffix


def project_folder_name(cwd: str) -> str:
    """The folder name Claude Code files a session under: every non-alphanumeric character becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def _text(message: dict | None) -> str | None:
    content = (message or {}).get("content")
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content if isinstance(content, str) else None


def prompt_wording(raw: str) -> str | None:
    """What the person actually asked: IDE context dropped, a slash command reduced to its arguments."""
    raw = IDE_CONTEXT.sub("", raw)
    if "<command-name>" in raw:
        name, args = COMMAND_NAME.search(raw), COMMAND_ARGS.search(raw)
        args = args.group(1).strip() if args else ""
        if not args:  # /model, /login, /effort...: nothing worth a title
            return None
        raw = "%s %s" % (name.group(1).strip() if name else "", args)
    if "<local-command-stdout>" in raw or raw.lstrip().startswith("[Request interrupted"):
        return None
    return " ".join(TAG.sub(" ", raw).split()) or None


@dataclass
class Transcript:
    session_id: str
    path: str
    cwd: str | None = None
    first_at: int | None = None  # ms since epoch, first real message
    last_at: int | None = None  # ms since epoch, last real message
    messages: int = 0
    entrypoints: list = field(default_factory=list)  # in order of first appearance
    custom_title: str | None = None
    ai_title: str | None = None
    first_prompt: str | None = None
    permission_mode: str | None = None
    model: str | None = None

    @property
    def folder(self) -> str:
        return os.path.basename(os.path.dirname(self.path))

    @property
    def origin(self) -> str | None:
        return self.entrypoints[0] if self.entrypoints else None

    @property
    def headless(self) -> bool:
        return bool(self.entrypoints) and not INTERACTIVE.intersection(self.entrypoints)

    @property
    def best_title(self) -> str | None:
        return self.custom_title or self.ai_title or self.first_prompt

    def folder_matches_cwd(self) -> bool:
        # Claude Desktop resumes a session from its cwd, so the transcript must sit in that cwd's folder.
        expected = project_folder_name(self.cwd or "")
        # Very long paths are shortened by Claude Code; accept a matching prefix there.
        return self.folder == expected or (len(expected) > 200 and self.folder.startswith(expected[:180]))


def read(path: str) -> Transcript:
    t = Transcript(session_id=os.path.basename(path)[: -len(".jsonl")], path=path)
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            kind = r.get("type")
            t.cwd = t.cwd or r.get("cwd")
            entry = r.get("entrypoint")
            if entry and entry not in t.entrypoints:
                t.entrypoints.append(entry)
            t.permission_mode = r.get("permissionMode") or t.permission_mode
            if kind == "custom-title" and r.get("customTitle"):
                t.custom_title = r["customTitle"]
            elif kind == "ai-title" and r.get("aiTitle"):
                t.ai_title = r["aiTitle"]
            if kind not in ("user", "assistant") or r.get("isSidechain"):
                continue
            # Only real turns count as activity; trailing metadata (cost-state, last-prompt...) has no timestamp
            # but still bumps the file's mtime, which is why mtime is a poor activity clock.
            if r.get("timestamp"):
                t.messages += 1
                t.first_at = t.first_at or to_ms(r["timestamp"])
                t.last_at = to_ms(r["timestamp"])
            if kind == "assistant":
                model = (r.get("message") or {}).get("model")
                if model and model != "<synthetic>":
                    t.model = model
            elif t.first_prompt is None and not r.get("isMeta"):
                raw = _text(r.get("message"))
                if raw:
                    t.first_prompt = prompt_wording(raw)
    return t


def find_transcripts(claude_dir: str):
    """Top-level session transcripts; subagent logs and other files are left out."""
    root = os.path.join(claude_dir, "projects")
    if not os.path.isdir(root):
        return
    for folder in sorted(os.listdir(root)):
        folder_path = os.path.join(root, folder)
        if not os.path.isdir(folder_path):
            continue
        for name in sorted(os.listdir(folder_path)):
            if name.endswith(".jsonl") and SESSION_ID.match(name[: -len(".jsonl")]):
                yield os.path.join(folder_path, name)
