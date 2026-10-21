# Deploying Ground Truth

This directory holds everything needed to run the Ground Truth API outside a
developer laptop:

| Path | Purpose |
| --- | --- |
| `gunicorn.conf.py` | Process-manager settings baked into the image (all overridable by environment). |
| `k8s/` | Kustomize base: Namespace, ConfigMap, Deployment, Service, HPA, PodDisruptionBudget. |

Configuration reference and scaling background: [docs/deployment.md](../docs/deployment.md).

## Prerequisites

- Kubernetes 1.27 or newer with the metrics server installed (required by the HPA).
- `kubectl` 1.27+ (kustomize is built in).
- Pull access to `ghcr.io/imranmali/legal-research-retrieval-evaluation-system`
  (public packages need no credentials; for a private package create an
  image pull secret and reference it from the Deployment in an overlay).

## Deploy

```bash
# Render to inspect what will be applied
kubectl kustomize deploy/k8s

# Apply and wait for the rollout
kubectl apply -k deploy/k8s
kubectl -n groundtruth rollout status deployment/groundtruth-api

# Smoke test through a port-forward
kubectl -n groundtruth port-forward svc/groundtruth-api 8000:80 &
curl -s localhost:8000/readyz
curl -s -X POST localhost:8000/v1/evaluate -H 'Content-Type: application/json' \
  -d '{"qrels":{"q1":{"d1":1}},"run":{"q1":{"d1":1.0}},"metrics":["P@1"]}'
```

### Enable API keys

Keys are read from an optional Secret named `groundtruth-api-keys`; the
Deployment picks it up via `envFrom`. Create it before (or after, then restart)
the rollout:

```bash
kubectl -n groundtruth create secret generic groundtruth-api-keys \
  --from-literal=GROUNDTRUTH_API_KEYS="$(openssl rand -hex 24),$(openssl rand -hex 24)"
kubectl -n groundtruth rollout restart deployment/groundtruth-api
```

Two keys allow rotation: add the new key, move clients, then remove the old one.

### Pin a version and customize with an overlay

The base tracks the `main` image tag. For production, create an overlay that
pins a release and adjusts settings without editing the base:

```yaml
# deploy/overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../k8s
images:
  - name: ghcr.io/imranmali/legal-research-retrieval-evaluation-system
    newTag: "0.1.0"
patches:
  - target: {kind: ConfigMap, name: groundtruth-api}
    patch: |
      - op: replace
        path: /data/GROUNDTRUTH_CORPUS_PATH
        value: /corpus/corpus.jsonl
```

Mount your corpus (for example from a PersistentVolumeClaim or a volume
populated by an init container) at the path you configure; keep it read-only.

### Expose outside the cluster

The Service is `ClusterIP`. Put an Ingress or Gateway in front of it that
terminates TLS and applies rate limiting, and set `FORWARDED_ALLOW_IPS` in the
ConfigMap to the proxy's address range so client IPs in logs are correct.

## Sizing

Defaults: 3 to 20 pods, each requesting `250m` CPU / `256Mi` and limited to
`1` CPU / `1Gi`, running `WEB_CONCURRENCY=2` gunicorn workers.

| Workload | Suggested settings |
| --- | --- |
| Evaluation only (no corpus), CI gating | Defaults. |
| Sample or small corpus (< 50k documents) | Defaults. |
| Medium corpus (50k to 500k documents) | Memory limit 2-4 Gi, request 1 Gi; startup probe `failureThreshold` 90+ to cover indexing. |
| Large corpus (> 500k documents) | Prefer evaluating an external search engine's run files; the in-memory baselines are sized for evaluation collections. If needed, `WEB_CONCURRENCY=1` and memory sized at index size + 200 Mi per worker. |

Rules of thumb:

- Keep `WEB_CONCURRENCY` at or below the CPU limit; scale out with more pods.
- Memory per pod is roughly `WEB_CONCURRENCY x (150 Mi + index size)`; every
  worker builds its own index.
- Keep the HPA minimum at 3 or more so the PodDisruptionBudget (`minAvailable: 2`)
  still allows node drains.
- Keep gunicorn's graceful timeout (25 s) plus the `preStop` delay (5 s) within
  `terminationGracePeriodSeconds` (30 s); raise all three together for long evaluations.

## Validate changes to the manifests

CI renders and validates the manifests on every pull request; run the same
check locally:

```bash
kubectl kustomize deploy/k8s | kubeconform -strict -summary -
```

## Roll back

```bash
kubectl -n groundtruth rollout undo deployment/groundtruth-api
# or pin a known-good immutable tag
kubectl -n groundtruth set image deployment/groundtruth-api \
  api=ghcr.io/imranmali/legal-research-retrieval-evaluation-system:sha-<short>
```
