# Contributing to Ground Truth

Thanks for helping make legal research retrieval measurable. This guide covers
the local setup, how changes are planned with OpenSpec, the branching model and
what has to pass before a pull request can merge.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Report security issues privately as described in [SECURITY.md](SECURITY.md),
never in a public issue.

## Development setup

Ground Truth uses [uv](https://docs.astral.sh/uv/) for environments,
dependency locking and builds. Python 3.11, 3.12 and 3.13 are supported.

```bash
git clone https://github.com/imranmali/legal-research-retrieval-evaluation-system.git
cd legal-research-retrieval-evaluation-system
uv sync                       # creates .venv with runtime + dev dependencies from uv.lock
uv run pre-commit install     # ruff, formatting and file hygiene on every commit
make check                    # ruff lint + format check, mypy --strict, pytest (coverage >= 90%)
```

Useful targets:

| Command | What it does |
| --- | --- |
| `make lint` | `ruff check` and `ruff format --check` |
| `make format` | Apply ruff fixes and formatting |
| `make typecheck` | `mypy --strict` over `src/groundtruth` |
| `make test` | `pytest` with branch coverage, gate at 90% |
| `make check` | All of the above; run before every push |
| `make spec-validate` | `openspec validate --all --strict` |

Dependencies are changed with `uv add` / `uv add --dev` / `uv lock --upgrade-package NAME`;
always commit `uv.lock` together with `pyproject.toml`. CI runs `uv sync --locked`,
so a stale lock fails the build.

To run the service locally: `uv run groundtruth serve`, or `docker compose up --build`
for the production image (see [docs/deployment.md](docs/deployment.md)).

## Spec-driven workflow (OpenSpec)

Every behavior change is planned before it is implemented. Specifications live
in `openspec/specs/` (the current truth) and proposed changes in
`openspec/changes/<change-name>/`. The CLI is
[`@fission-ai/openspec`](https://www.npmjs.com/package/@fission-ai/openspec)
(`npm install -g @fission-ai/openspec`, or `npx @fission-ai/openspec ...`).

1. **Propose.** Create `openspec/changes/<change-name>/` with
   - `proposal.md`: why, what changes, affected capabilities and what is out of scope;
   - `specs/<capability>/spec.md`: `ADDED` / `MODIFIED` / `REMOVED` requirements, each
     with at least one `#### Scenario:` written as WHEN/THEN;
   - `design.md`: decisions, module layout, trade-offs;
   - `tasks.md`: checklist where each task names the test or command that proves it.

   Run `openspec validate <change-name> --strict` and open a pull request for
   review of the proposal (docs-only PRs are fine at this stage).
2. **Apply.** Implement the tasks on a feature branch, ticking each checkbox in
   `tasks.md` as its proof passes. Tests mirror the requirement scenarios.
3. **Archive.** After the implementation is merged, run
   `openspec archive <change-name> -y`. This folds the spec deltas into
   `openspec/specs/` and moves the change to `openspec/changes/archive/`, so the
   specs keep describing the system as it is.

Changes that do not alter behavior (typo fixes, refactors with no observable
effect, dependency bumps) do not need an OpenSpec change.

## Branching model

`main` is always releasable and protected: it only moves through reviewed pull
requests with green CI. Create short-lived branches off `main`:

| Prefix | Use for |
| --- | --- |
| `feature/*` | New capabilities (metrics, retrievers, endpoints, CLI commands) |
| `fix/*` | Bug fixes |
| `docs/*` | Documentation and OpenSpec proposals |
| `ci/*` | Workflows, container image, deployment manifests |
| `chore/*` | Tooling, dependency updates, housekeeping |

Rebase on `main` to pick up changes rather than merging `main` into your branch.
Releases are cut by tagging `main` with `vX.Y.Z` (see below).

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```text
<type>(<optional scope>): <imperative summary>

<body: what and why, wrapped at 72 columns>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`.
Mark breaking changes with `!` (`feat(api)!: ...`) and a `BREAKING CHANGE:` footer.
Examples: `feat(metrics): add JurisdictionMatch@k`, `fix(io): reject duplicate qrels lines`.

## Pull requests

- Fill in the pull request template, link the OpenSpec change and the issue.
- `make check` must pass locally; CI runs the same gates plus OpenSpec
  validation, a package build, the container smoke test and Kubernetes
  manifest validation on Python 3.11 to 3.13.
- New metrics implement `groundtruth.metrics.base.Metric`, register with
  `@register_metric`, build rankings with `groundtruth.ranking.rank_documents`
  and come with hand-computed test values. Keep results compatible with
  `trec_eval` conventions unless the spec says otherwise.
- Errors raised to users derive from `groundtruth.errors.GroundTruthError`.
- Never commit real client documents or privileged material; sample data must
  be fictional.

## Releasing (maintainers)

1. Update `version` in `pyproject.toml` and move the `Unreleased` entries in
   `CHANGELOG.md` under the new version; merge via pull request.
2. Tag the merge commit: `git tag -a v0.2.0 -m "v0.2.0" && git push origin v0.2.0`.
3. The release workflow verifies the tag matches the project version, builds the
   wheel and sdist, creates the GitHub release with generated notes and pushes
   the image tags `0.2.0`, `0.2` and `latest` to GHCR.
