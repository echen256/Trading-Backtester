"""Optional LLM grader for TPO execution features."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..market_data import REPO_ROOT, load_env_value
from .render import _quality_from_score
from .schema import TpoFeatures, TpoGrade

DEFAULT_ENV_PATH = REPO_ROOT / ".env"
_load_env_value = load_env_value
DEFAULT_SKILL_DIR = REPO_ROOT / ".cursor" / "skills" / "tpo-execution-grade"
# modules/analysis/skills/tpo-execution-grade (parents[3] == analysis/)
FALLBACK_SKILL_DIR = Path(__file__).resolve().parents[3] / "skills" / "tpo-execution-grade"

RULE_ALLOWLIST = frozenset(
    {
        "mid_range_entry",
        "short_at_bottom",
        "long_at_top",
        "short_at_prior_vah",
        "long_at_prior_val",
        "entry_at_extreme",
        "against_ib_break",
        "gave_back_to_value",
        "exit_above_value",
        "exit_below_value",
        "chased_extension",
        "weekend_hold_risk",
        "scattered_overtrading",
        "revenge_reentry",
        "overworking_theme",
    }
)


def resolve_skill_dir() -> Path:
    if DEFAULT_SKILL_DIR.exists():
        return DEFAULT_SKILL_DIR
    if FALLBACK_SKILL_DIR.exists():
        return FALLBACK_SKILL_DIR
    return DEFAULT_SKILL_DIR


def load_rubric_text(skill_dir: Path | None = None) -> str:
    root = skill_dir or resolve_skill_dir()
    rubric_path = root / "rubric.md"
    skill_path = root / "SKILL.md"
    parts: list[str] = []
    if skill_path.exists():
        parts.append(skill_path.read_text(encoding="utf-8"))
    if rubric_path.exists():
        parts.append(rubric_path.read_text(encoding="utf-8"))
    if not parts:
        parts.append(
            "Grade underlying Market Profile execution. Prefer extremes over mid-range. "
            "Shorts at bottoms and longs at tops are serious errors. Cite only allowlisted rules."
        )
    return "\n\n".join(parts)


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-4.1-mini"


def _env_value(key: str) -> str | None:
    return os.getenv(key) or _load_env_value(DEFAULT_ENV_PATH, key)


def get_grade_provider() -> str:
    """
    Resolve LLM provider for TPO grading.

    Priority:
      1. TPO_GRADE_PROVIDER=deepseek|openai
      2. DEEPSEEK_API_KEY present without OpenAI keys → deepseek
      3. otherwise openai (OpenAI-compatible default)
    """
    explicit = (_env_value("TPO_GRADE_PROVIDER") or "").strip().lower()
    if explicit in {"deepseek", "openai"}:
        return explicit

    has_deepseek = bool(_env_value("DEEPSEEK_API_KEY"))
    has_openai = bool(_env_value("TPO_GRADE_API_KEY") or _env_value("OPENAI_API_KEY"))
    if has_deepseek and not has_openai:
        return "deepseek"
    return "openai"


def get_grade_api_key() -> str | None:
    provider = get_grade_provider()
    if provider == "deepseek":
        key_names = ("TPO_GRADE_API_KEY", "DEEPSEEK_API_KEY")
    else:
        key_names = ("TPO_GRADE_API_KEY", "OPENAI_API_KEY")
    for key in key_names:
        value = _env_value(key)
        if value:
            return value
    return None


def get_grade_base_url() -> str:
    explicit = _env_value("TPO_GRADE_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    if get_grade_provider() == "deepseek":
        return DEEPSEEK_BASE_URL
    return OPENAI_BASE_URL


def get_grade_model() -> str:
    explicit = _env_value("TPO_GRADE_MODEL")
    if explicit:
        return explicit
    if get_grade_provider() == "deepseek":
        return DEEPSEEK_DEFAULT_MODEL
    return OPENAI_DEFAULT_MODEL


def features_only_grade(features: TpoFeatures) -> TpoGrade:
    score = features.deterministic_score
    return TpoGrade(
        status="features_only",
        overall_score=score,
        execution_quality=_quality_from_score(score),
        rule_hits=list(features.rule_hits),
        rule_misses=[],
        what_went_wrong=[hit for hit in features.rule_hits if hit in {
            "mid_range_entry", "short_at_bottom", "long_at_top", "against_ib_break", "gave_back_to_value"
        }],
        what_went_right=[hit for hit in features.rule_hits if hit in {
            "short_at_prior_vah", "long_at_prior_val", "entry_at_extreme", "exit_above_value", "exit_below_value"
        }],
        corrective_note=_default_corrective_note(features),
        confidence=0.55,
        model=None,
        graded_at=datetime.now(timezone.utc).isoformat(),
    )


def _default_corrective_note(features: TpoFeatures) -> str:
    if features.short_bottom_flag:
        return "Do not short at the bottom of value; wait for a range top / prior VAH."
    if features.long_top_flag:
        return "Do not buy extensions at the top of value; wait for a pullback to VAL/extreme."
    if "mid_range_entry" in features.rule_hits:
        return "Skip mid-range entries; only take trades at local range extremes."
    if features.gave_back_to_value:
        return "When price leaves value in your favor, scale out before it rotates back into VA."
    return "Keep taking extremes aligned with direction; avoid fighting developing value."


def grade_with_llm(
    *,
    features: TpoFeatures,
    trade_payload: dict[str, Any],
    entry_ascii: str | None,
    exit_ascii: str | None,
    context_summary: dict[str, Any],
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> TpoGrade:
    key = api_key or get_grade_api_key()
    if not key:
        return features_only_grade(features)

    resolved_model = model or get_grade_model()
    resolved_base = (base_url or get_grade_base_url()).rstrip("/")
    rubric = load_rubric_text()

    user_payload = {
        "trade": trade_payload,
        "features": features.to_dict(),
        "entry_session_tpo_ascii": entry_ascii,
        "exit_session_tpo_ascii": exit_ascii,
        "context_summary": context_summary,
        "rule_allowlist": sorted(RULE_ALLOWLIST),
        "deterministic_score": features.deterministic_score,
    }
    system = (
        "You are a trading execution coach grading Market Profile / TPO location quality. "
        "Use only the provided numeric features and ASCII profiles. "
        "Do not invent prices. rule_hits must be a subset of rule_allowlist. "
        "Return strict JSON matching the schema."
    )
    user = (
        f"RUBRIC:\n{rubric}\n\n"
        f"TRADE DATA:\n{json.dumps(user_payload, indent=2)}\n\n"
        "Respond with JSON keys: overall_score (0-100), execution_quality "
        "(good|acceptable|poor|catastrophic), rule_hits, rule_misses, "
        "what_went_wrong, what_went_right, corrective_note, confidence (0-1)."
    )

    body = {
        "model": resolved_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    url = f"{resolved_base}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        return TpoGrade(
            status="error",
            overall_score=features.deterministic_score,
            execution_quality=_quality_from_score(features.deterministic_score),
            rule_hits=list(features.rule_hits),
            corrective_note=_default_corrective_note(features),
            model=resolved_model,
            graded_at=datetime.now(timezone.utc).isoformat(),
            error=f"LLM HTTP {exc.code}: {details[:500]}",
        )
    except urllib.error.URLError as exc:
        return TpoGrade(
            status="error",
            overall_score=features.deterministic_score,
            execution_quality=_quality_from_score(features.deterministic_score),
            rule_hits=list(features.rule_hits),
            corrective_note=_default_corrective_note(features),
            model=resolved_model,
            graded_at=datetime.now(timezone.utc).isoformat(),
            error=f"LLM unreachable: {exc}",
        )

    try:
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        return TpoGrade(
            status="error",
            overall_score=features.deterministic_score,
            execution_quality=_quality_from_score(features.deterministic_score),
            rule_hits=list(features.rule_hits),
            corrective_note=_default_corrective_note(features),
            model=resolved_model,
            graded_at=datetime.now(timezone.utc).isoformat(),
            error=f"Invalid LLM response: {exc}",
        )

    return _normalize_llm_grade(parsed, features, resolved_model)


def _normalize_llm_grade(parsed: dict[str, Any], features: TpoFeatures, model: str) -> TpoGrade:
    try:
        score = float(parsed.get("overall_score"))
    except (TypeError, ValueError):
        score = features.deterministic_score
    score = max(0.0, min(100.0, score))

    # Keep LLM within a band of deterministic score to limit hallucination drift
    if abs(score - features.deterministic_score) > 35:
        score = (score + features.deterministic_score) / 2

    quality = str(parsed.get("execution_quality") or _quality_from_score(score)).lower()
    if quality not in {"good", "acceptable", "poor", "catastrophic"}:
        quality = _quality_from_score(score)

    rule_hits = [str(r) for r in (parsed.get("rule_hits") or []) if str(r) in RULE_ALLOWLIST]
    if not rule_hits:
        rule_hits = list(features.rule_hits)
    rule_misses = [str(r) for r in (parsed.get("rule_misses") or []) if str(r) in RULE_ALLOWLIST]

    try:
        confidence = float(parsed.get("confidence"))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.6

    return TpoGrade(
        status="ok",
        overall_score=round(score, 2),
        execution_quality=quality,
        rule_hits=rule_hits,
        rule_misses=rule_misses,
        what_went_wrong=[str(x) for x in (parsed.get("what_went_wrong") or [])][:5],
        what_went_right=[str(x) for x in (parsed.get("what_went_right") or [])][:5],
        corrective_note=str(parsed.get("corrective_note") or _default_corrective_note(features))[:400],
        confidence=confidence,
        model=model,
        graded_at=datetime.now(timezone.utc).isoformat(),
    )


def grade_trade_record(
    *,
    features: TpoFeatures,
    trade_payload: dict[str, Any],
    entry_ascii: str | None,
    exit_ascii: str | None,
    context_summary: dict[str, Any],
    use_llm: bool,
) -> TpoGrade:
    if use_llm:
        return grade_with_llm(
            features=features,
            trade_payload=trade_payload,
            entry_ascii=entry_ascii,
            exit_ascii=exit_ascii,
            context_summary=context_summary,
        )
    return features_only_grade(features)
