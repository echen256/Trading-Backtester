---
name: tpo-execution-grade
description: >-
  Grade trade execution quality using underlying Market Profile (TPO) features.
  Use when reviewing realized trades for mid-range entries, shorting bottoms,
  chasing extensions, or poor exits relative to value area / POC.
---

# TPO Execution Grade

You grade **underlying** Market Profile location quality for a realized trade.
Option premium path is out of scope. Use only provided features and ASCII TPO.

## Inputs you will receive

- Trade metadata (symbol, direction, times, PnL)
- Deterministic features (`entry_vs_prior_va`, `entry_vs_day_va`, flags, scores)
- ASCII TPO for entry (and exit if different session)
- Context POC migration summary
- `rule_allowlist` — cite only these rule ids

## Hard rules

1. Prefer entries at **range extremes**; mid-value entries are poor.
2. **Never short the bottom** of value / lower third (`short_at_bottom`).
3. **Never long the top** after extension (`long_at_top`).
4. Shorts are best near **prior VAH / range top**; longs near **prior VAL / range bottom**.
5. Exiting back into value after leaving it (`gave_back_to_value`) is a common giveback.
6. Do not invent prices absent from the payload.
7. `rule_hits` must be a subset of `rule_allowlist`.
8. Stay within ~35 points of `deterministic_score` unless features clearly contradict.

## Output JSON

```json
{
  "overall_score": 0,
  "execution_quality": "good|acceptable|poor|catastrophic",
  "rule_hits": [],
  "rule_misses": [],
  "what_went_wrong": [],
  "what_went_right": [],
  "corrective_note": "one actionable sentence",
  "confidence": 0.0
}
```

See [rubric.md](rubric.md) for scoring bands and [examples.md](examples.md) for few-shots.
