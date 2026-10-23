# claude-desktop-importer

English | [简体中文](https://github.com/Leeiio/claude-desktop-importer/blob/main/README.zh-CN.md)

Bring your Claude Code CLI sessions into the Claude Desktop sidebar: all of them, with their real titles, in the right order.

Claude Desktop already has **Help → Troubleshooting → Import Claude Code CLI sessions…**, but it:

- **silently skips sessions** started through the Agent SDK or `claude -p` (headless, `sdk-*` entrypoints);
- **silently skips projects** whose folder is not marked trusted in `~/.claude.json` under that exact path;
- **titles every session with its first prompt**, even when Claude Code generated a title or you set one with `/rename` ([anthropics/claude-code#89857](https://github.com/anthropics/claude-code/issues/89857));
- **uses the transcript's file modification time as "last activity"**, so the sidebar order is wrong: Claude Code appends metadata long after the last message ([anthropics/claude-code#83203](https://github.com/anthropics/claude-code/issues/83203));
- tells you nothing about what it skipped, or why.

This tool does the same job transparently, and can repair the sessions the built-in Import already added.

## Install

Python 3.9 or newer, no dependencies. With [uv](https://docs.astral.sh/uv/) you can run it without installing anything:

```bash
uvx claude-desktop-importer scan
```

Or install the command once:

```bash
uv tool install claude-desktop-importer     # or: pipx install claude-desktop-importer
```

Upgrade later with `uv tool upgrade claude-desktop-importer` (or `pipx upgrade claude-desktop-importer`); `uvx claude-desktop-importer@latest` always runs the newest release.

To run from source instead:

```bash
git clone https://github.com/Leeiio/claude-desktop-importer.git
cd claude-desktop-importer
python3 -m claude_desktop_importer scan
```

## Usage

The examples use the installed command; with uvx, put `uvx` in front (`uvx claude-desktop-importer import --apply`). Every command only shows what it would do until you add `--apply`.

```bash
claude-desktop-importer scan             # which sessions are missing from the sidebar, and why some are skipped
claude-desktop-importer import           # preview
claude-desktop-importer import --apply   # add them, then quit and reopen Claude Desktop
```

Whenever you have new CLI sessions, run `scan` and `import --apply` again, then restart Claude Desktop. Sessions already in the sidebar are never touched by `import`.

To fix the titles and order of sessions imported by Claude Desktop's own Import, **quit Claude Desktop first** (Cmd+Q, not just closing the window):

```bash
claude-desktop-importer fix              # preview
claude-desktop-importer fix --apply
```

Every `--apply` makes a backup. To undo:

```bash
claude-desktop-importer restore                          # list backups
claude-desktop-importer restore 20261022-195403-fix      # preview
claude-desktop-importer restore 20261022-195403-fix --apply
```

Options shared by all commands:

| Option | Default |
| --- | --- |
| `--claude-dir` | `$CLAUDE_CONFIG_DIR`, else `~/.claude` |
| `--store` | Claude Desktop's `claude-code-sessions` folder, found automatically |
| `--profile` | the only `<account>/<org>` folder, else the one Claude Desktop last signed in to |
| `--backup-dir` | `~/.claude-desktop-importer/backups` |

`import` also takes `--only ID…` (full ids or prefixes) and `--include-desktop` (see below).

## How it works

Claude Code keeps each session in `~/.claude/projects/<folder>/<session-id>.jsonl`. Claude Desktop's sidebar is a folder of small JSON records, one per session, in `~/Library/Application Support/Claude/claude-code-sessions/<account>/<org>/`. Claude Desktop reads that folder when it starts.

`import` writes a `local_<session-id>.json` record for each missing session, in the same shape the built-in Import uses, with:

- **title**: your `/rename` title, else Claude Code's generated title, else the first real prompt (IDE context and bare slash commands such as `/model` are skipped);
- **created / last activity**: the timestamps of the first and last real message;
- **model** and **permission mode**: the last ones the session used.

It never modifies transcripts. A transcript is skipped when it:

- has no messages;
- has no working directory recorded, or that directory no longer exists;
- is filed under a different project folder than its working directory (Claude Desktop could not resume it);
- is open in a running Claude Code process;
- is already in the sidebar, including the earlier transcripts of a Desktop session that was compacted or continued;
- was started in Claude Desktop and is no longer in its sidebar. You most likely removed it there, so it takes `--include-desktop`.

It does not skip a project just because its folder is not marked trusted in `~/.claude.json`.

`fix` only touches records marked as adopted from another surface (what Import creates). It leaves alone titles you renamed in Claude Desktop, and time differences under five minutes. A replaced title is kept in the record's `previousTitles`.

## Safety

- Dry run unless you pass `--apply`.
- Every `--apply` first writes a backup with a manifest of what it adds and the originals of what it changes; `restore` puts it back.
- `import` works while Claude Desktop is running; the new sessions appear after the next restart.
- `fix` and `restore` refuse to run while Claude Desktop is open. It keeps the session list in memory and writes a session's record back whenever that session changes, which would undo the edit.
- Records are written atomically, compact, readable only by you (mode 600), the way Claude Desktop writes them.

## Limitations

- Built and tested on macOS with the Claude Desktop of October 2026. The Windows and Linux folder locations are best guesses, and there the tool cannot tell whether Claude Desktop is running, so `fix --apply` and `restore --apply` need `--force` once you have quit it.
- It relies on Claude Desktop's internal files, which are undocumented and may change in any update. Run `scan` and the dry runs first; `restore` if anything looks wrong.
- Claude Desktop leaves no trace this tool can find when you delete a session. If you delete an imported CLI session from the sidebar, a later `import` offers it again: archive it instead, or use `--only`.
- One sidebar at a time: use `--profile` if you use several accounts or organizations.

## Development

```bash
python3 -m unittest discover -s tests -t .
```

The tests build fake transcripts and sidebar folders in a temp directory; they never read your real data. Releases are published to PyPI by GitHub Actions; see [RELEASING.md](https://github.com/Leeiio/claude-desktop-importer/blob/main/RELEASING.md).

## License

[MIT](https://github.com/Leeiio/claude-desktop-importer/blob/main/LICENSE). Not affiliated with or endorsed by Anthropic.
