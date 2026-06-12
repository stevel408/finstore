# Publishing to PyPI

## When to publish

Follow semantic versioning (see [contributing.md](contributing.md#versioning)).
As a rule of thumb: bug fixes → patch, new features → minor, breaking changes → major.

## Steps

**1. Bump the version** in `pyproject.toml`:

```toml
[project]
version = "0.2.0"
```

**2. Commit the version bump:**

```bash
git add pyproject.toml
git commit -m "Bump version to 0.2.0"
```

**3. Publish to PyPI:**

```bash
./scripts/publish.sh
```

The script sources `.env`, reads `PYPI_TOKEN`, builds the distribution, and
publishes in one step. If you don't have a token yet, generate one at
[pypi.org/manage/account/token](https://pypi.org/manage/account/token/) and
add `PYPI_TOKEN=pypi-...` to your `.env`.

**4. Verify the release:**

```bash
uv venv --clear /tmp/verify-finstore
source /tmp/verify-finstore/bin/activate
pip install 'finstore[local]'==0.2.0
finstore --help
deactivate
```

## Notes

- The `dist/` directory is gitignored. Never commit build artefacts.
- Static files under `src/finstore_local/web/static/` are included in the
  wheel via the `artifacts` key in `[tool.hatch.build.targets.wheel]` —
  no extra steps needed.
- If a release is broken, yank it on PyPI rather than deleting it:
  `uv publish --yank "reason"` (or use the PyPI web UI). Yanked versions
  are hidden from installers but remain accessible to anyone who pinned them.
