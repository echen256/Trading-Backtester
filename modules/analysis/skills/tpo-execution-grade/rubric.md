# TPO Execution Rubric v1.0

## Scoring bands

| Score | Quality | Meaning |
|------:|---------|---------|
| 75–100 | good | Extreme entry aligned with direction; exit not a giveback |
| 55–74 | acceptable | Mostly OK location with minor flaws |
| 30–54 | poor | Mid-range, fighting IB, or mild location error |
| 0–29 | catastrophic | Short-at-bottom / long-at-top / clear rulebook violation |

## Allowlisted rule ids

| Id | When to apply |
|----|----------------|
| `mid_range_entry` | Entry inside day VA with low extreme score |
| `short_at_bottom` | Short in lower third or below VAL |
| `long_at_top` | Long in upper third or above VAH |
| `short_at_prior_vah` | Short near/above prior session VAH (good) |
| `long_at_prior_val` | Long near/below prior session VAL (good) |
| `entry_at_extreme` | Extreme score ≥ 0.75 |
| `against_ib_break` | Entry fights Initial Balance break |
| `gave_back_to_value` | Left value then exited back inside VA |
| `exit_above_value` | Long exit above VAH (good) |
| `exit_below_value` | Short exit below VAL (good) |
| `chased_extension` | Entered after stretched trend day extension |
| `weekend_hold_risk` | Short-dated option held across weekend (metadata) |
| `scattered_overtrading` | Behavioral tag when context implies impulse |
| `revenge_reentry` | Behavioral tag for failed-symbol re-entry |
| `overworking_theme` | Behavioral tag for overtrading a paid theme |

## Direction semantics

Same location, opposite quality:

- Long below VAL / at prior VAL → good
- Short below VAL / at bottom → catastrophic
- Short above VAH / at prior VAH → good
- Long above VAH / at top → poor/catastrophic

## Deterministic baseline

Start from `deterministic_score` in the payload. Adjust with justification tied to features. Prefer concrete corrective notes ("Wait for prior VAH rejection before shorting TSLA") over vague advice.

## Out of scope

- MACD / Fisher / narrative (not in TPO payload)
- Option IV / premium path
- Predicting future PnL — grade **execution location**, not outcome luck
