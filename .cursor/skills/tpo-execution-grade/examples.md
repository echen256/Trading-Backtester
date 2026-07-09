# TPO Grade Examples

## Example A — catastrophic short at bottom

Features:

- direction: short
- entry_vs_day_va: below_val
- short_bottom_flag: true
- entry_extreme_score: 0.82
- deterministic_score: 25

Expected grade:

```json
{
  "overall_score": 18,
  "execution_quality": "catastrophic",
  "rule_hits": ["short_at_bottom", "entry_at_extreme"],
  "rule_misses": ["short_at_prior_vah"],
  "what_went_wrong": ["Shorted the lower extreme / below value"],
  "what_went_right": [],
  "corrective_note": "Only short at range tops or prior VAH; skip bottoms even if extreme.",
  "confidence": 0.9
}
```

## Example B — good long at prior VAL

Features:

- direction: long
- entry_vs_prior_va: below_val
- entry_vs_day_va: below_val
- entry_extreme_score: 0.88
- long_top_flag: false
- deterministic_score: 90

Expected grade:

```json
{
  "overall_score": 88,
  "execution_quality": "good",
  "rule_hits": ["long_at_prior_val", "entry_at_extreme"],
  "rule_misses": [],
  "what_went_wrong": [],
  "what_went_right": ["Bought prior value low / session extreme"],
  "corrective_note": "Keep buying defined range lows; manage exit before rotation back into VA if scaling.",
  "confidence": 0.85
}
```

## Example C — poor mid-range entry

Features:

- direction: long
- entry_vs_day_va: inside_va
- entry_extreme_score: 0.22
- deterministic_score: 40

Expected grade:

```json
{
  "overall_score": 38,
  "execution_quality": "poor",
  "rule_hits": ["mid_range_entry"],
  "rule_misses": ["entry_at_extreme", "long_at_prior_val"],
  "what_went_wrong": ["Entered middle of developing value"],
  "what_went_right": [],
  "corrective_note": "Skip mid-VA entries; wait for a test of VAL or a clear extreme.",
  "confidence": 0.8
}
```
