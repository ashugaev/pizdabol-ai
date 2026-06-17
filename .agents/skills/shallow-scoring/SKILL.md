---
name: shallow-scoring
description: Score task complexity 1-5 from the request text only. Use during manager routing before codebase exploration.
---

# Shallow Scoring

Assign score from task description only.

| Score | Criteria |
|---|---|
| 1 | Single file, obvious implementation, no external boundary |
| 2 | 2-5 files, clear approach, small tests/docs update |
| 3 | Multiple modules or integrations, some design choice |
| 4 | Cross-cutting behavior, production/runtime risk, multiple valid approaches |
| 5 | Architecture or workflow change with high uncertainty |

## Output

```text
Complexity: <N>/5
Reason: <one sentence>
```
