"""Tests against synthetic transcripts and sidebar folders in a temp dir; nothing real is read or written."""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from claude_desktop_importer import cli, core, store, transcript
from claude_desktop_importer.transcript import clip, project_folder_name, prompt_wording, to_ms

A = "aaaaaaaa-0000-4000-8000-000000000001"
B = "bbbbbbbb-0000-4000-8000-000000000002"
C = "cccccccc-0000-4000-8000-000000000003"
D = "dddddddd-0000-4000-8000-000000000004"


def user(text, ts, **extra):
    return dict({"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}, **extra)


def assistant(text, ts, model="claude-opus-5-5", **extra):
    return dict({"type": "assistant", "timestamp": ts,
                 "message": {"role": "assistant", "model": model, "content": [{"type": "text", "text": text}]}},
                **extra)


class Sandbox(unittest.TestCase):
    """A fake ~/.claude, a fake claude-code-sessions/<account>/<org>, and a real folder to use as cwd."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.claude = os.path.join(root, "claude")
        self.store = os.path.join(root, "store")
        self.profile = os.path.join(self.store, "account", "org")
        self.backups = os.path.join(root, "backups")
        self.cwd = os.path.join(root, "work", "my.project")
        for d in (os.path.join(self.claude, "projects"), self.profile, self.cwd):
            os.makedirs(d)
        # The real lsof would see nothing here anyway; skip the subprocess.
        patcher = mock.patch("claude_desktop_importer.paths.transcript_in_use", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def session(self, session_id, records, cwd=None, folder=None):
        cwd = cwd or self.cwd
        records = [dict({"cwd": cwd, "sessionId": session_id}, **r) for r in records]
        folder = os.path.join(self.claude, "projects", folder or project_folder_name(cwd))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, session_id + ".jsonl")
        with open(path, "w") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in records))
        return path

    def basic(self, session_id, entrypoint="cli", **extra):
        return self.session(session_id, [
            user("Fix the login bug", "2026-10-01T10:00:00.000Z", entrypoint=entrypoint),
            assistant("Done.", "2026-10-01T10:30:00.000Z", entrypoint=entrypoint),
        ], **extra)

    def record(self, session_id, **fields):
        rec = dict({"sessionId": "local_" + session_id, "cliSessionId": session_id, "cwd": self.cwd}, **fields)
        path = os.path.join(self.profile, store.record_name(session_id))
        store.write_json(path, rec)
        return path

    def run_cli(self, *argv, running=False):
        out, err = io.StringIO(), io.StringIO()
        common = ["--claude-dir", self.claude, "--store", self.store, "--backup-dir", self.backups]
        with mock.patch("claude_desktop_importer.paths.app_running", return_value=running), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([argv[0]] + common + list(argv[1:]))
        return code, out.getvalue() + err.getvalue()


class TranscriptTest(Sandbox):
    def test_reads_times_titles_and_metadata(self):
        path = self.session(A, [
            {"type": "permission-mode", "permissionMode": "plan", "entrypoint": "sdk-cli"},
            user("<ide_opened_file>The user opened foo.py</ide_opened_file>Why is this slow?",
                 "2026-10-01T10:00:00.000Z", entrypoint="sdk-cli"),
            assistant("Sidechain work", "2026-10-01T10:05:00.000Z", isSidechain=True),
            assistant("Because of N+1 queries.", "2026-10-01T10:10:00.000Z"),
            assistant("No response requested.", "2026-10-01T10:11:00.000Z", model="<synthetic>"),
            {"type": "ai-title", "aiTitle": "Diagnose slow query"},
            {"type": "last-prompt", "lastPrompt": "Why is this slow?"},  # no timestamp: not activity
        ])
        t = transcript.read(path)
        self.assertEqual(t.messages, 3)
        self.assertEqual(t.first_at, to_ms("2026-10-01T10:00:00.000Z"))
        self.assertEqual(t.last_at, to_ms("2026-10-01T10:11:00.000Z"))
        self.assertEqual(t.first_prompt, "Why is this slow?")
        self.assertEqual(t.best_title, "Diagnose slow query")
        self.assertEqual(t.model, "claude-opus-5-5")
        self.assertEqual(t.permission_mode, "plan")
        self.assertTrue(t.headless)
        self.assertTrue(t.folder_matches_cwd())

    def test_custom_title_beats_ai_title(self):
        path = self.session(A, [user("hi", "2026-10-01T10:00:00.000Z"),
                                {"type": "ai-title", "aiTitle": "Greeting"},
                                {"type": "custom-title", "customTitle": "My name"}])
        self.assertEqual(transcript.read(path).best_title, "My name")

    def test_prompt_wording(self):
        self.assertIsNone(prompt_wording("<command-name>/model</command-name><command-args></command-args>"))
        self.assertEqual(prompt_wording("<command-name>/design</command-name><command-args>a landing page"
                                        "</command-args>"), "/design a landing page")
        self.assertIsNone(prompt_wording("<local-command-stdout>Set model</local-command-stdout>"))
        self.assertIsNone(prompt_wording("[Request interrupted by user]"))

    def test_first_prompt_skips_bare_commands(self):
        path = self.session(A, [
            user("<command-name>/login</command-name><command-args></command-args>", "2026-10-01T10:00:00.000Z"),
            user("Caveat: local command output", "2026-10-01T10:00:01.000Z", isMeta=True),
            user("Real question", "2026-10-01T10:01:00.000Z"),
        ])
        self.assertEqual(transcript.read(path).first_prompt, "Real question")

    def test_clip_keeps_fork_marker(self):
        self.assertEqual(clip("short"), "short")
        clipped = clip("x" * 100 + " (fork)")
        self.assertEqual(len(clipped), 60)
        self.assertTrue(clipped.endswith("… (fork)"))

    def test_folder_name(self):
        self.assertEqual(project_folder_name("/Users/me/my.app_v2"), "-Users-me-my-app-v2")

    def test_finds_only_top_level_session_files(self):
        self.basic(A)
        sub = os.path.join(self.claude, "projects", project_folder_name(self.cwd), A, "subagents")
        os.makedirs(sub)
        open(os.path.join(sub, "agent-1.jsonl"), "w").close()
        open(os.path.join(os.path.dirname(sub), "..", "notes.jsonl"), "w").close()
        self.assertEqual([os.path.basename(p) for p in transcript.find_transcripts(self.claude)], [A + ".jsonl"])


class ScanTest(Sandbox):
    def test_statuses(self):
        self.basic(A)  # importable
        self.basic(B)
        self.record(B)  # already indexed
        self.session(C, [{"type": "summary", "summary": "nothing"}])  # empty
        gone = os.path.join(self.tmp.name, "deleted-project")
        self.basic(D, cwd=gone)  # cwd no longer exists
        result = core.scan(self.claude, self.profile)
        self.assertEqual((result.total, result.indexed), (4, 1))
        reasons = {c.transcript.session_id: c.reason for c in result.candidates}
        self.assertIsNone(reasons[A])
        self.assertEqual(reasons[C], "no messages")
        self.assertEqual(reasons[D], "working directory no longer exists")

    def test_desktop_sessions_need_opt_in(self):
        self.basic(A, entrypoint="claude-desktop")
        self.assertIn("--include-desktop", core.scan(self.claude, self.profile).candidates[0].reason)
        self.assertTrue(core.scan(self.claude, self.profile, include_desktop=True).candidates[0].importable)

    def test_earlier_transcripts_of_a_continued_session_count_as_indexed(self):
        self.basic(A, entrypoint="claude-desktop")  # before compaction
        self.basic(B, entrypoint="claude-desktop")  # after
        self.record(B, priorCliSessionIds=[A])
        result = core.scan(self.claude, self.profile, include_desktop=True)
        self.assertEqual((result.total, result.indexed, result.candidates), (2, 2, []))

    def test_wrong_folder(self):
        self.basic(A, folder="-somewhere-else")
        self.assertEqual(core.scan(self.claude, self.profile).candidates[0].reason,
                         "stored outside its working directory's project folder")

    def test_in_use_is_skipped(self):
        self.basic(A)
        with mock.patch("claude_desktop_importer.paths.transcript_in_use", return_value=True):
            self.assertEqual(core.scan(self.claude, self.profile).candidates[0].reason,
                             "open in a running Claude Code process")

    def test_build_record(self):
        t = transcript.read(self.basic(A))
        rec = core.build_record(t, now_ms=123)
        self.assertEqual(rec["sessionId"], "local_" + A)
        self.assertEqual(rec["createdAt"], to_ms("2026-10-01T10:00:00.000Z"))
        self.assertEqual(rec["lastActivityAt"], to_ms("2026-10-01T10:30:00.000Z"))
        self.assertEqual(rec["title"], "Fix the login bug")
        self.assertEqual(rec["permissionMode"], "default")
        self.assertTrue(rec["adoptedFromOtherSurface"])
        bare = self.session(B, [user("<command-name>/login</command-name>", "2026-10-01T10:00:00.000Z")])
        self.assertNotIn("title", core.build_record(transcript.read(bare)))
        self.assertNotIn("model", core.build_record(transcript.read(bare)))


class RepairTest(Sandbox):
    def test_plan_and_apply(self):
        self.session(A, [user("Make a logo", "2026-10-01T10:00:00.000Z"),
                         assistant("Here", "2026-10-01T12:00:00.000Z"),
                         {"type": "ai-title", "aiTitle": "Design a logo"}])
        mtime = to_ms("2026-10-20T08:00:00.000Z")  # what Desktop's Import used as last activity
        path = self.record(A, title="Make a logo", createdAt=to_ms("2026-10-01T10:00:00.000Z"),
                           lastActivityAt=mtime, adoptedFromOtherSurface=True)
        [repair] = core.plan_repairs(self.claude, self.profile)
        self.assertEqual(repair.changes, {"lastActivityAt": to_ms("2026-10-01T12:00:00.000Z"),
                                          "title": "Design a logo"})
        core.apply_repair(repair)
        with open(path) as fh:
            rec = json.load(fh)
        self.assertEqual(rec["title"], "Design a logo")
        self.assertEqual(rec["previousTitles"], ["Make a logo"])
        self.assertEqual(core.plan_repairs(self.claude, self.profile), [])  # idempotent

    def test_leaves_user_titles_and_native_records_alone(self):
        self.session(A, [user("q", "2026-10-01T10:00:00.000Z"), {"type": "ai-title", "aiTitle": "AI name"}])
        self.session(B, [user("q", "2026-10-01T10:00:00.000Z"), {"type": "ai-title", "aiTitle": "AI name"}])
        t0 = to_ms("2026-10-01T10:00:00.000Z")
        self.record(A, title="Mine", titleSource="user", createdAt=t0, lastActivityAt=t0,
                    adoptedFromOtherSurface=True)
        self.record(B, title="q", createdAt=t0, lastActivityAt=t0)  # started in Desktop
        self.assertEqual(core.plan_repairs(self.claude, self.profile), [])

    def test_small_time_drift_is_ignored(self):
        self.session(A, [user("Same title", "2026-10-01T10:00:00.000Z")])
        t0 = to_ms("2026-10-01T10:00:00.000Z")
        self.record(A, title="Same title", createdAt=t0 + 60000, lastActivityAt=t0 - 60000,
                    adoptedFromOtherSurface=True)
        self.assertEqual(core.plan_repairs(self.claude, self.profile), [])


class StoreTest(Sandbox):
    def test_write_json_is_compact_and_private(self):
        path = os.path.join(self.profile, "x.json")
        store.write_json(path, {"title": "中文", "n": 1})
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{"title":"中文","n":1}')
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual([n for n in os.listdir(self.profile) if n.endswith(".tmp")], [])

    def test_backup_and_restore_round_trip(self):
        kept = self.record(A, title="old")
        with open(kept, "rb") as fh:
            original = fh.read()
        backup = store.back_up(self.backups, self.profile, "test", added=[store.record_name(B)],
                               modified=[store.record_name(A)])
        self.record(A, title="new")
        self.record(B, title="added")
        removed, restored, profile = store.restore(backup)
        self.assertEqual((removed, restored, profile), (1, 1, self.profile))
        with open(kept, "rb") as fh:
            self.assertEqual(fh.read(), original)
        self.assertFalse(os.path.exists(os.path.join(self.profile, store.record_name(B))))
        self.assertEqual(len(store.list_backups(self.backups)), 1)


class CliTest(Sandbox):
    def test_import_dry_run_then_apply_then_restore(self):
        self.basic(A)
        code, out = self.run_cli("import")
        self.assertEqual(code, 0)
        self.assertIn("Dry run", out)
        self.assertEqual(os.listdir(self.profile), [])

        code, out = self.run_cli("import", "--apply", running=True)  # adding records is fine while it runs
        self.assertEqual(code, 0, out)
        self.assertEqual(os.listdir(self.profile), [store.record_name(A)])
        [(backup, manifest)] = store.list_backups(self.backups)
        self.assertEqual(manifest["added"], [store.record_name(A)])

        code, out = self.run_cli("import", "--apply")
        self.assertIn("Nothing to import", out)

        code, out = self.run_cli("restore", backup, "--apply", running=True)
        self.assertEqual(code, 2)
        self.assertIn("Quit Claude Desktop first", out)
        code, out = self.run_cli("restore", os.path.basename(backup), "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(os.listdir(self.profile), [])

    def test_only_filters_by_prefix(self):
        self.basic(A)
        self.basic(B)
        code, out = self.run_cli("import", "--only", B[:8], "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(os.listdir(self.profile), [store.record_name(B)])

    def test_fix_refuses_while_running(self):
        self.session(A, [user("q", "2026-10-01T10:00:00.000Z"), {"type": "ai-title", "aiTitle": "Better"}])
        self.record(A, title="q", adoptedFromOtherSurface=True)
        code, out = self.run_cli("fix", running=True)  # dry run is always allowed
        self.assertEqual(code, 0)
        self.assertIn("'q' -> 'Better'", out)
        code, out = self.run_cli("fix", "--apply", running=True)
        self.assertEqual(code, 2)
        code, out = self.run_cli("fix", "--apply", running=None)  # unknown platform needs --force
        self.assertEqual(code, 2)
        self.assertIn("--force", out)
        code, out = self.run_cli("fix", "--apply", "--force", running=None)
        self.assertEqual(code, 0, out)

    def test_missing_claude_dir_is_a_clean_error(self):
        code, out = self.run_cli("scan", "--claude-dir", os.path.join(self.tmp.name, "nope"))
        self.assertEqual(code, 2)
        self.assertIn("No Claude Code transcripts", out)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()
