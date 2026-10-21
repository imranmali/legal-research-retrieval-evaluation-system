---
name: Bug report
about: Report incorrect scores, crashes or unexpected behavior
title: "fix: "
labels: [bug]
assignees: []
---

## What happened

<!-- A clear description of the problem. For wrong metric values, include the expected value and where it comes from (e.g. trec_eval output). -->

## How to reproduce

<!-- Smallest qrels/run/corpus that shows the problem, plus the exact command or HTTP request. Do not attach confidential client data. -->

```text
groundtruth evaluate qrels.txt run.txt --metric nDCG@10
```

## Expected behavior

## Environment

- Ground Truth version (`groundtruth version`):
- Interface: library / CLI / HTTP API / container image tag
- Python version and OS:

## Logs

<!-- Error output or API error body (`{"error": {...}}`), including the request id if any. -->
