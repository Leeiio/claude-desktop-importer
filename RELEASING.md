# Releasing

Releases are uploaded to PyPI by the [Publish](.github/workflows/publish.yml) workflow using PyPI's [Trusted Publishing](https://docs.pypi.org/trusted-publishers/): GitHub proves to PyPI which workflow is running, so no API token is stored anywhere.

## One-time setup

1. **PyPI**: sign in at pypi.org, open **Your account → Publishing**, and under **Add a new pending publisher → GitHub** enter:

   | Field | Value |
   | --- | --- |
   | PyPI Project Name | `claude-desktop-importer` |
   | Owner | `Leeiio` |
   | Repository name | `claude-desktop-importer` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

   The first successful upload creates the project and turns this into its regular trusted publisher.

2. **GitHub**: in the repository's **Settings → Environments**, create an environment named `pypi`. Adding yourself under **Required reviewers** makes every upload wait for your approval.

## Each release

1. Set the new version in `claude_desktop_importer/__init__.py` (`__version__`), commit, push to `main`, and wait for CI to pass.
2. On GitHub, **Releases → Draft a new release**, create the tag `v<version>` (for example `v0.1.1`) on `main`, click **Generate release notes**, and **Publish release**.
3. The Publish workflow runs the tests, checks that the tag matches `__version__`, builds the sdist and wheel, and uploads them to PyPI.

PyPI accepts each version number only once. To fix a broken release, bump the version and release again.
