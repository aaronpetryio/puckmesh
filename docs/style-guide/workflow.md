# Workflow

How changes get into `main`. The goal is that `main` always works, because the scheduled
pipeline runs whatever is on it against prod every morning.

## Branches and pull requests

- `main` is protected: changes arrive through pull requests, and CI must pass first
  (GitHub → Settings → Branches → branch protection or a ruleset: "Require status checks").
- One topic per branch and PR. Short-lived; rebase or merge `main` in rather than letting
  it drift.
- The PR description says what changed, why, and how it was checked (`dbt build` on dev,
  row counts, a query that shows the fix).

## Commits

Following [git's own guidance](https://git-scm.com/docs/git-commit#_discussion), as the
history already does:

- Summary line in the imperative ("Add play-by-play extraction"), about 50 characters,
  72 at most, no trailing period.
- Blank line, then a body explaining *why* when the diff doesn't make it obvious.
- One logical change per commit. Formatting-only changes get their own commit, so
  `git blame` can skip them (list them in `.git-blame-ignore-revs`).

## Checks

| Where | What |
|---|---|
| pre-commit (every commit) | whitespace/EOF, YAML syntax, no private keys, `ruff check`, `ruff format`, `sqlfluff lint`, `yamllint` |
| CI on every PR | the pre-commit hooks, `pytest`, `dbt deps && dbt parse`, then `dbt build --target dev` into a per-PR schema (`DBT_SCHEMA=ci_pr_<number>`) |
| Scheduled pipeline | as today: extract, then `dbt build --target prod` |

Later, when builds get slow:
[slim CI](https://docs.getdbt.com/best-practices/best-practice-workflows#run-only-modified-models-to-test-changes-slim-ci)
(`dbt build --select state:modified+ --defer --state <prod manifest>`) builds only what
a PR changed. [dbt-project-evaluator](https://github.com/dbt-labs/dbt-project-evaluator)
checks the [dbt guide](dbt.md)'s structural rules automatically (marts reading sources,
missing primary key tests, undocumented models).

## GitHub Actions

From GitHub's
[security hardening guide for Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions):

- Pin third-party actions to a full commit SHA, with the version in a comment:
  `uses: actions/checkout@<sha> # v4.2.2`. A tag can be moved; a SHA can't.
  Dependabot (`.github/dependabot.yml`, ecosystem `github-actions`) keeps the pins current.
- Least-privilege `permissions:` per workflow (`pipeline.yml` already sets `contents: read`).
- Secrets only through `secrets.*`, never echoed. PR workflows from forks don't get
  secrets, which is fine: the dev `dbt build` step runs only for branches in this repo.
- Every workflow sets `timeout-minutes` and, if it writes, a `concurrency` group
  (`pipeline.yml` does both).
