# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x (latest release and `main`) | Yes |
| Older releases | No |

Security fixes are released as patch versions and published as new container
image tags; redeploy from the latest tag to pick them up.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report vulnerabilities privately through GitHub's security advisories:
open the repository's **Security** tab and choose
**Report a vulnerability**
(<https://github.com/imranmali/legal-research-retrieval-evaluation-system/security/advisories/new>).

Include as much of the following as you can:

- affected component (library, CLI, HTTP API, container image, Kubernetes manifests) and version or image tag;
- a description of the issue and its impact;
- steps or a proof of concept to reproduce it;
- any suggested fix or mitigation.

## What to expect

- Acknowledgement within 3 business days.
- An initial assessment and planned remediation timeline within 10 business days.
- Coordinated disclosure: we publish a GitHub security advisory (and request a
  CVE where appropriate) once a fix is available, crediting you unless you
  prefer otherwise.

## Scope notes

- The HTTP API is designed to run behind an ingress or API gateway that
  terminates TLS and applies rate limiting. Request-size and run-size limits
  and optional API keys are built in; misconfiguration of the surrounding
  infrastructure is out of scope.
- Index files are loaded from a versioned JSON format, never from pickle; reports
  of code execution through crafted input files are in scope.
- The sample collection in `data/sample/` is fictional and contains no real
  client or court data.
