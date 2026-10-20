# Ground Truth — contributor notes

- Spec-driven: plan every behavior change as an OpenSpec change under
  `openspec/changes/<name>/` (proposal, specs, design, tasks), implement it,
  then `openspec archive <name> -y` so `openspec/specs/` stays the source of truth.
- Tooling: `uv sync` installs everything. Before committing run
  `make check` (ruff lint + format check, mypy --strict, pytest with coverage >= 90%).
- Layout: library code in `src/groundtruth/`, tests mirror it in `tests/`.
- Metrics implement `groundtruth.metrics.base.Metric` and register with
  `@register_metric`; rankings come from `groundtruth.ranking.rank_documents`.
- Errors derive from `groundtruth.errors.GroundTruthError`.
- Commits use Conventional Commits (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`, `test:`).
