# Python style

Applies to `extract/` and any future Python (ML helpers, export). Based on
[PEP 8](https://peps.python.org/pep-0008/) (code),
[PEP 257](https://peps.python.org/pep-0257/) (docstrings),
[PEP 484](https://peps.python.org/pep-0484/) (type hints), and the
[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).
Ruff formats and lints it (`pyproject.toml`): `ruff format . && ruff check --fix .`.

## Formatting

- `ruff format` decides layout. It's Black-compatible, which dbt Labs recommends.
  Don't hand-format around it.
- 88 columns (Ruff/Black default; PEP 8 allows teams up to 99). The formatter won't
  split strings or comments; wrap those yourself.
- Imports at the top of the module, grouped stdlib / third-party / local, sorted (Ruff `I`).
  Absolute imports (`from extract.raw import save`).
- **Deferred imports need a comment saying why** (a slow or optional dependency, a
  cycle). Without one, move the import to the top.

## Naming (PEP 8)

| Thing | Style | Example |
|---|---|---|
| Modules, functions, variables | `snake_case` | `play_by_play`, `final_game_ids` |
| Classes, exceptions | `CapWords`, errors end in `Error` | `HockeyTechClient`, `HockeyTechError` |
| Constants | `UPPER_SNAKE` at module level | `BASE_URL`, `RECENT_GAMES` |
| Internal | leading underscore | `_throttle`, `_normalize` |

Use the same domain words as the dbt project: `season_id`, `game_id`, `endpoint`, `league`.

## Types

- Annotate every public function's parameters and return type (Ruff `ANN001`,
  `ANN201`). Private helpers too, where it helps.
- Modern syntax: `list[int]`, `dict[str, int]`, `X | None` (PEP 585, PEP 604).
- API JSON gets a name instead of nothing or `Any` everywhere:
  `Json = dict[str, Any]` in one module, imported where needed.
- Fixed choices are a `Literal` (`Mode = Literal["daily", "full"]`), not a bare `str`.

## Docstrings (PEP 257, Google style)

- **Every module starts with a docstring** saying what it's for. `extract/` already
  does this well; `raw.py` and `load.py` are good models.
- Classes and non-obvious public functions get a docstring: one summary line, a blank
  line, then details. Add `Args:` / `Returns:` / `Raises:` sections when the signature
  doesn't make them obvious.
- A function whose name and types say everything doesn't need one.
- Docstrings say what and why; `#` comments explain a specific line.

## Errors and retries

- Catch the narrowest exception that you can handle. No bare `except:`, and never swallow
  an error silently.
- Retry only transient failures: connection errors, timeouts, HTTP 429 and 5xx. A 4xx
  won't succeed on retry.
- Raise project exceptions (`HockeyTechError`) for "the API answered, but wrong".

## Output and logging

- `print` belongs to the command line (`extract/__main__.py`). Library modules
  (`pipeline.py`, `upload.py`, ...) use
  [`logging`](https://docs.python.org/3/howto/logging.html): `log = logging.getLogger(__name__)`,
  configured once in `main()`. Ruff `T201` enforces this.
- Log what happened and the counts, not the payloads.

## Configuration and secrets

- Environment variables are read in one module (`extract/db.py` today, or a
  `config.py`), each with its default, not scattered. The one exception is the
  Databricks SDK, which reads `DATABRICKS_HOST` / `DATABRICKS_TOKEN` itself.
- Every variable the code reads is listed in `.env.example` with a comment.
- No secrets in code or in raw files. The HockeyTech key in `client.py` is public (it's in
  the league's own website); say so in a comment so nobody "fixes" it into a secret.

## SQL from Python

See [sql.md, "SQL in Python"](sql.md#sql-in-python): bind values as parameters, and
interpolate only backtick-quoted identifiers from config.

## Data and time

- Timezone-aware UTC timestamps: `datetime.now(UTC)`. `date.today()` is the local date;
  use `datetime.now(UTC).date()` for "today" in the pipeline.
- `pathlib.Path` for files (Ruff `PTH`), with `encoding="utf-8"` always written out.
- **One owner for each response shape.** Knowledge like
  `response["SiteKit"]["Schedule"]` lives in that endpoint's module
  (`schedule.games(response)`), not in callers.

## Tests

- [pytest](https://docs.pytest.org/), in `tests/` mirroring the package
  (`tests/test_raw.py` for `extract/raw.py`).
- Pure functions are tested: `parse_body`, `content_hash`, `_normalize`, `_is_active`,
  `final_game_ids`. These hold the project's subtle rules (JSONP stripping, `[]`/`{}`
  equivalence, season windows) and cost nothing to test.
- No network or warehouse in unit tests. Pass fakes in (the code already takes a
  `client` and `state` as arguments, which makes this easy).
- A bug fix comes with the test that would have caught it.

## Dependencies

- Declare dependencies and `requires-python` in `pyproject.toml`
  ([Python Packaging User Guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)),
  and commit a lockfile (`uv lock` or `pip-compile`) so CI installs exactly what you
  tested. `requirements.txt` with only lower bounds means any release can change a
  scheduled run.
- Keep dev tools in `requirements-dev.txt` (pre-commit, pytest), separate from what the
  pipeline needs.

## Not done yet

- Dependencies are still in `requirements.txt` with lower bounds only; move them to
  `pyproject.toml` with a lockfile, together with the CI workflow that installs them.
