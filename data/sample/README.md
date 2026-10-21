# Ground Truth sample collection

> **FICTIONAL DATA. NOT LEGAL AUTHORITY.**
> Every case name, party, holding, court decision, reporter citation and
> statutory summary in this directory is invented for software testing and
> demonstrations. Any resemblance to a real case or citation is coincidental.
> Statute numbers such as `42 U.S.C. § 2000e-2` or `17 U.S.C. § 107` are used
> generically, and the descriptions of them are simplified. Do not cite, quote
> or rely on any of this material as law.

A small legal retrieval test collection: 24 documents, 8 research queries and
graded relevance judgments. It is meant for demos, tutorials and tests of the
retrievers and metrics in this repository.

| File            | Contents                                                       |
|-----------------|----------------------------------------------------------------|
| `corpus.jsonl`  | 24 documents: 23 fictional opinions, 1 fictional statute summary |
| `queries.jsonl` | 8 research queries with jurisdictions and expected citations   |
| `qrels.txt`     | Graded relevance judgments in TREC format                      |

The documents cover employment discrimination, Fourth Amendment searches,
contract formation, negligence and duty of care, copyright fair use and data
privacy. They come from four jurisdictions: `US-FED`, `US-CA`, `US-NY` and `UK`.
Some documents are `overruled`, `superseded` or `questioned`, and several of
those are judged topically relevant. A system that ranks them highly scores
well on relevance but badly on `BadLaw@k`.

## `corpus.jsonl`

One JSON object per line (the file may also be gzip-compressed):

| Field           | Type              | Required | Meaning                                                            |
|-----------------|-------------------|----------|--------------------------------------------------------------------|
| `doc_id`        | string            | yes      | Unique document id                                                 |
| `text`          | string            | yes      | Full text                                                          |
| `title`         | string            | no       | Case name or title (default `""`)                                  |
| `jurisdiction`  | string            | no       | e.g. `US-FED`, `US-CA`, `US-NY`, `UK`                              |
| `court`         | string            | no       | Deciding court                                                     |
| `decision_date` | `YYYY-MM-DD`      | no       | Date of decision                                                   |
| `citations`     | list of strings   | no       | How this document is cited (normalized on load)                    |
| `cites`         | list of strings   | no       | Authorities this document cites (normalized on load)               |
| `status`        | string            | no       | `good_law`, `questioned`, `overruled`, `superseded` or `unknown` (default) |

## `queries.jsonl`

| Field                   | Type            | Required | Meaning                                                   |
|-------------------------|-----------------|----------|-----------------------------------------------------------|
| `query_id`              | string          | yes      | Unique query id                                           |
| `text`                  | string          | yes      | The research question                                     |
| `jurisdiction`          | string          | no       | Target jurisdiction                                       |
| `binding_jurisdictions` | list of strings | no       | Other jurisdictions whose authority binds the research    |
| `expected_citations`    | list of strings | no       | Citations a good answer should surface (normalized)       |

## `qrels.txt`

Standard TREC format, one judgment per line:

```
<query_id> 0 <doc_id> <grade>
```

Grade scale:

| Grade | Meaning                                                                 |
|-------|-------------------------------------------------------------------------|
| 0     | Not relevant                                                            |
| 1     | Tangential: related topic, different issue or persuasive only           |
| 2     | Relevant: addresses the issue                                           |
| 3     | Controlling / key authority: the authority a researcher must find      |

Unjudged documents count as not relevant. `KeyAuthorityRecall@k` uses the
grade-3 judgments.

## Example

```python
from groundtruth.legal import load_documents, load_queries
from groundtruth.retrieval import get_retriever

docs = load_documents("data/sample/corpus.jsonl")
queries = load_queries("data/sample/queries.jsonl")
run = get_retriever("bm25").fit(docs).retrieve(queries, k=10)
```
