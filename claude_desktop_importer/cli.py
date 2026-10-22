"""claude-desktop-importer scan | import | fix | restore"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

from . import ImporterError, __version__, core, paths, store
from .transcript import clip

PROG = "claude-desktop-importer"
DEFAULT_BACKUPS = "~/.claude-desktop-importer/backups"
RESTART_HINT = "Quit Claude Desktop completely (Cmd+Q / File > Quit) and reopen it: it reads the session list only at startup."


def _when(ms: int | None) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else "-".ljust(16)


def _home(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def _origin(t) -> str:
    return "sdk" if t.headless else (t.origin or "?")


def _context(args) -> tuple:
    claude = paths.claude_dir(args.claude_dir)
    if not os.path.isdir(os.path.join(claude, "projects")):
        raise ImporterError("No Claude Code transcripts in %s (no projects/ folder). Pass --claude-dir if they live "
                            "elsewhere." % claude)
    profile = paths.pick_profile(paths.store_root(args.store), args.profile)
    print("Claude Code:  %s" % _home(claude))
    print("Sidebar:      %s\n" % _home(profile))
    return claude, profile


def _require_quit(args, what: str) -> None:
    running = paths.app_running()
    if running:
        raise ImporterError("Quit Claude Desktop first (Cmd+Q, not just closing the window). While it runs it keeps "
                            "the session list in memory and would write over the %s." % what)
    if running is None and not args.force:
        raise ImporterError("Cannot tell whether Claude Desktop is running on this platform. Quit it, then rerun "
                            "with --force.")


def _print_session(t, note: str | None = None) -> None:
    print("  %s  %s  %-14s %s" % (t.session_id[:8], _when(t.last_at), _origin(t), _home(t.cwd or "?")))
    print("            %s" % (note or clip(t.best_title or "(untitled)", 70)))


def _scan(args, claude, profile):
    result = core.scan(claude, profile, include_desktop=args.include_desktop)
    print("%d transcripts, %d already in the sidebar." % (result.total, result.indexed))
    return result


def cmd_scan(args) -> int:
    claude, profile = _context(args)
    result = _scan(args, claude, profile)
    importable = [c for c in result.candidates if c.importable]
    skipped = [c for c in result.candidates if not c.importable]
    if importable:
        print("\nCan be imported (%d):" % len(importable))
        for c in importable:
            _print_session(c.transcript)
    if skipped:
        print("\nSkipped (%d):" % len(skipped))
        for c in skipped:
            _print_session(c.transcript, "skipped: " + c.reason)
    if importable:
        print("\nPreview with `%s import`, then add --apply to import them." % PROG)
    else:
        print("\nNothing to import.")
    return 0


def cmd_import(args) -> int:
    claude, profile = _context(args)
    result = _scan(args, claude, profile)
    chosen = [c for c in result.candidates if c.importable]
    if args.only:
        chosen = [c for c in chosen if any(c.transcript.session_id.startswith(p) for p in args.only)]
        for prefix in args.only:
            if not any(c.transcript.session_id.startswith(prefix) for c in chosen):
                print("note: %s is not an importable session (see `%s scan`)." % (prefix, PROG))
    if not chosen:
        print("\nNothing to import.")
        return 0
    print("\nWill add %d session(s) to the sidebar:" % len(chosen))
    for c in chosen:
        _print_session(c.transcript)
    if not args.apply:
        print("\nDry run, nothing written. Add --apply to import.")
        return 0

    # Claude Desktop may have indexed one of these since the scan; never overwrite its own record.
    chosen = [c for c in chosen if not os.path.exists(os.path.join(profile, store.record_name(c.transcript.session_id)))]
    names = [store.record_name(c.transcript.session_id) for c in chosen]
    backup = store.back_up(os.path.expanduser(args.backup_dir), profile, "import", added=names, modified=[])
    now = int(time.time() * 1000)
    for c, name in zip(chosen, names):
        store.write_json(os.path.join(profile, name), core.build_record(c.transcript, now))
    print("\nImported %d session(s)." % len(names))
    print("Undo: %s restore %s --apply" % (PROG, _home(backup)))
    print(RESTART_HINT)
    return 0


def cmd_fix(args) -> int:
    claude, profile = _context(args)
    repairs = core.plan_repairs(claude, profile)
    if not repairs:
        print("Every imported session already has its real title and activity times.")
        return 0
    print("Will update %d imported session(s):" % len(repairs))
    for r in repairs:
        print("  %s  %s" % (r.record["cliSessionId"][:8], _home(r.record.get("cwd") or "?")))
        if "title" in r.changes:
            print("      title:          %r -> %r" % (r.record.get("title"), r.changes["title"]))
        for key, label in (("createdAt", "created:       "), ("lastActivityAt", "last activity: ")):
            if key in r.changes:
                print("      %s %s -> %s" % (label, _when(r.record.get(key)), _when(r.changes[key])))
    if not args.apply:
        print("\nDry run, nothing written. Quit Claude Desktop, then add --apply.")
        return 0

    _require_quit(args, "fixed records")
    names = [os.path.basename(r.path) for r in repairs]
    backup = store.back_up(os.path.expanduser(args.backup_dir), profile, "fix", added=[], modified=names)
    for r in repairs:
        core.apply_repair(r)
    print("\nUpdated %d session(s)." % len(repairs))
    print("Undo: %s restore %s --apply" % (PROG, _home(backup)))
    print("Open Claude Desktop again to see the changes.")
    return 0


def cmd_restore(args) -> int:
    root = os.path.expanduser(args.backup_dir)
    if not args.backup:
        backups = store.list_backups(root)
        if not backups:
            print("No backups in %s." % _home(root))
            return 0
        print("Backups in %s (oldest first):" % _home(root))
        for path, m in backups:
            print("  %-28s %-7s %3d added, %3d modified" % (os.path.basename(path), m.get("action", "?"),
                                                          len(m.get("added", [])), len(m.get("modified", []))))
        print("\nUndo one with `%s restore <name>`." % PROG)
        return 0

    backup = args.backup if os.path.isdir(os.path.expanduser(args.backup)) else os.path.join(root, args.backup)
    backup = os.path.expanduser(backup)
    m = store.read_manifest(backup)
    print("Backup of `%s` from %s, sidebar %s" % (m.get("action"), m.get("created"), _home(m.get("profile", "?"))))
    print("  remove %d record(s) it added, put back %d it modified" % (len(m["added"]), len(m["modified"])))
    if not args.apply:
        print("\nDry run, nothing written. Quit Claude Desktop, then add --apply.")
        return 0
    _require_quit(args, "restored records")
    removed, restored, _ = store.restore(backup)
    print("\nRemoved %d, restored %d. Open Claude Desktop again to see the result." % (removed, restored))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="Bring Claude Code CLI sessions into the Claude Desktop sidebar, and fix the titles "
                               "and order of sessions Claude Desktop imported. Every command is a dry run unless "
                               "you pass --apply.")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--claude-dir", help="Claude Code config folder (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    common.add_argument("--store", help="Claude Desktop's claude-code-sessions folder (default: found automatically)")
    common.add_argument("--profile", help="<account>/<org> folder inside the store, when there are several")
    common.add_argument("--backup-dir", default=DEFAULT_BACKUPS, help="where backups go (default: %(default)s)")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("scan", parents=[common], help="list CLI sessions missing from the sidebar")
    p.add_argument("--include-desktop", action="store_true",
                   help="also offer sessions started in Claude Desktop that are no longer in its sidebar")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("import", parents=[common], help="add missing sessions to the sidebar")
    p.add_argument("--apply", action="store_true", help="write the records (default: only show them)")
    p.add_argument("--include-desktop", action="store_true",
                   help="also import sessions started in Claude Desktop that are no longer in its sidebar")
    p.add_argument("--only", nargs="+", metavar="ID", help="import only these sessions (id or id prefix)")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("fix", parents=[common],
                       help="give imported sessions their real title and activity times (Claude Desktop must be quit)")
    p.add_argument("--apply", action="store_true", help="write the changes (default: only show them)")
    p.add_argument("--force", action="store_true", help="skip the is-Claude-running check where it is unavailable")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("restore", parents=[common], help="list backups, or undo one import/fix")
    p.add_argument("backup", nargs="?", help="backup folder or name (omit to list backups)")
    p.add_argument("--apply", action="store_true", help="undo it (default: only show what would change)")
    p.add_argument("--force", action="store_true", help="skip the is-Claude-running check where it is unavailable")
    p.set_defaults(func=cmd_restore)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except ImporterError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
