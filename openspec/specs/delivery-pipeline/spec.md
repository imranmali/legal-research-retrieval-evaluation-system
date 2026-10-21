# delivery-pipeline Specification

## Purpose
Guarantees every change is verified before merge and every release produces
deployable, secure, horizontally scalable artifacts.

## Requirements

### Requirement: Merge gate
Every pull request and push to `main` SHALL run lint, format check, strict type check, the test suite with at least 90% coverage on all supported Python versions, OpenSpec strict validation and a container build, and the pipeline SHALL fail if any step fails.

#### Scenario: Failing test blocks merge
- **WHEN** a pull request introduces a failing test
- **THEN** the CI workflow reports failure

### Requirement: Container smoke test
CI SHALL start the built container and SHALL fail unless `/healthz` responds successfully and a sample evaluation request succeeds.

#### Scenario: Broken image
- **WHEN** the image cannot start the API
- **THEN** the smoke test step fails

### Requirement: Secure container image
The image SHALL run as a non-root user, contain no build toolchain or test files, declare a health check and be configurable only through environment variables.

#### Scenario: Non-root
- **WHEN** the container starts
- **THEN** the process user id is not 0

### Requirement: Release publishing
Pushing to `main` SHALL publish the image tagged `main` and with the commit SHA; pushing a `v*` tag SHALL publish the image tagged with the version, build wheel and sdist, and attach them to a GitHub release.

#### Scenario: Tagged release
- **WHEN** tag `v0.1.0` is pushed
- **THEN** a GitHub release `v0.1.0` with wheel and sdist exists and image tag `0.1.0` is published

### Requirement: Scalable deployment manifests
The repository SHALL provide Kubernetes manifests with liveness and readiness probes, resource requests and limits, a horizontal autoscaler and a disruption budget, and SHALL validate them in CI.

#### Scenario: Autoscaling
- **WHEN** the manifests are applied
- **THEN** a HorizontalPodAutoscaler targets the API deployment
