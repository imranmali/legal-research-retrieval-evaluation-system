# Tasks

## 1. Container and local runtime

- [x] 1.1 Add multi-stage `Dockerfile`, `.dockerignore` and `docker-compose.yml`; verify `docker build` succeeds and the container answers `/healthz` as non-root

## 2. CI/CD workflows

- [x] 2.1 Add `.github/workflows/ci.yml` with lint, test matrix, spec, build, docker smoke and k8s validation jobs; verify YAML parses and jobs run green on the pull request
- [x] 2.2 Add `cd.yml` and `release.yml`; verify YAML parses and tag/version check script works locally

## 3. Deployment manifests

- [x] 3.1 Add kustomize manifests in `deploy/k8s/`; verify with kubeconform in CI

## 4. Project hygiene and docs

- [x] 4.1 Add pre-commit, Dependabot, PR template, issue templates, CONTRIBUTING, SECURITY, CHANGELOG, CODE_OF_CONDUCT; verify `pre-commit run --all-files` passes
- [x] 4.2 Write full README (overview, install, CLI, API, metrics reference, architecture, deployment, license); verify commands in it run against `data/sample`

## Workflow follow-up

- Archive with `openspec archive add-delivery-pipeline -y` after merge review.
