"""Bring Claude Code CLI sessions into the Claude Desktop sidebar, and repair the ones already there."""

__version__ = "0.1.0"


class ImporterError(Exception):
    """A problem the user has to fix (wrong folder, app still running...); printed without a traceback."""
