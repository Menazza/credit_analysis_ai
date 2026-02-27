"""
LLM-assisted memo narrative writer.
Generates junior analyst-style memo sections using metrics + notes evidence.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

TARGET_SECTIONS = [
    "executive_summary",
    "business_description",
    "financial_performance",
    "financial_risk",
    "cash_flow_liquidity",
    "balance_sheet_leverage",
    "stress_testing_results",
    "accounting_disclosure_quality",
    "key_notes_accounting",
    "key_risks",
    "covenants_headroom",
    "internal_rating_rationale",
    "credit_risk_quantification",
    "recommendation_conditions",
    "monitoring_plan",
]

SYSTEM_PROMPT = """You are a junior corporate credit analyst drafting a memo for senior credit approvers.

Write in a professional analyst tone: clear, cautious, and evidence-based.
Do NOT invent facts, values, note references, covenant terms, or conclusions.
If evidence is missing, explicitly state "insufficient evidence".

Hard requirements:
1) Every analytical claim must tie to provided data.
2) Use note citations naturally, e.g. "(Note 21: Borrowings, p. 58-60)".
3) Highlight both strengths and downside risks.
4) Flag items that require senior reviewer attention.
5) Keep concise paragraphs with occasional bullets.
6) Return JSON only:
{
  "sections": {
    "<section_key>": "<section text>"
  }
}
Only output section keys requested in the input payload.
"""


def _strip_json_fences(content: str) -> str:
    s = (content or "").strip()
    if s.startswith("```"):
        parts = s.split("```")
        if len(parts) >= 2:
            s = parts[1]
            if s.lower().startswith("json"):
                s = s[4:]
    return s.strip()


def _compact_metrics(values: dict[str, Any], limit: int = 16) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (values or {}).items():
        if isinstance(v, (int, float, str, bool)) and v is not None:
            out[k] = round(v, 4) if isinstance(v, float) else v
    keys = sorted(out.keys())[:limit]
    return {k: out[k] for k in keys}


def _note_score(title: str, snippet: str) -> int:
    text = f"{title} {snippet}".lower()
    score = 0
    for kw in [
        "borrow", "debt", "lease", "covenant", "going concern", "liquidity",
        "impair", "tax", "provision", "contingent", "financial instrument", "credit risk",
    ]:
        if kw in text:
            score += 2
    return score


def _build_note_briefs(notes_json: dict[str, Any] | None, max_notes: int = 14) -> list[dict[str, str]]:
    notes_root = notes_json or {}
    notes = notes_root.get("notes") if isinstance(notes_root, dict) and isinstance(notes_root.get("notes"), dict) else notes_root
    if not isinstance(notes, dict):
        return []

    ranked: list[tuple[int, str, dict[str, str]]] = []
    for note_id, note in notes.items():
        if not isinstance(note, dict):
            continue
        title = str(note.get("title") or "").strip()
        pages = str(note.get("pages") or "").strip()
        text = str(note.get("text") or "")
        if not title and not text:
            continue
        snippet = re.sub(r"\s+", " ", text).strip()[:900]
        score = _note_score(title, snippet)
        ranked.append(
            (
                -score,
                str(note_id),
                {
                    "note_id": str(note_id),
                    "title": title or f"Note {note_id}",
                    "pages": pages,
                    "snippet": snippet,
                },
            )
        )
    ranked.sort(key=lambda x: (x[0], x[1]))
    return [r[2] for r in ranked[:max_notes]]


def _period_snapshot(
    facts_by_period: dict[date, dict[str, float]],
    metric_by_period: dict[date, dict[str, float]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pe in sorted(facts_by_period.keys(), reverse=True)[:limit]:
        rows.append(
            {
                "period": pe.isoformat() if hasattr(pe, "isoformat") else str(pe),
                "facts": _compact_metrics(facts_by_period.get(pe, {}), limit=24),
                "metrics": _compact_metrics(metric_by_period.get(pe, {}), limit=24),
            }
        )
    return rows


def _call_openai(system: str, user_prompt: str) -> str:
    settings = get_settings()
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        temperature=max(0.0, min(0.4, settings.llm_temperature)),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def generate_junior_analyst_sections(
    company_name: str,
    review_period_end: date | None,
    rating_grade: str | None,
    recommendation: str,
    section_blocks: dict[str, dict[str, Any]],
    aggregation: dict[str, Any],
    facts_by_period: dict[date, dict[str, float]],
    metric_by_period: dict[date, dict[str, float]],
    notes_json: dict[str, Any] | None,
    baseline_sections: dict[str, str],
    recommendation_conditions: list[str] | None = None,
) -> dict[str, str]:
    settings = get_settings()
    if not settings.openai_api_key:
        return {}

    try:
        section_payload: dict[str, Any] = {}
        for k, block in (section_blocks or {}).items():
            section_payload[k] = {
                "section_name": block.get("section_name"),
                "score": block.get("score"),
                "section_rating": block.get("section_rating"),
                "key_metrics": _compact_metrics(block.get("key_metrics") or {}, limit=28),
                "risk_flags": (block.get("risk_flags") or [])[:8],
                "evidence_notes": (block.get("evidence_notes") or [])[:10],
            }

        payload = {
            "company_name": company_name,
            "review_period_end": review_period_end.isoformat() if hasattr(review_period_end, "isoformat") else str(review_period_end or ""),
            "rating_grade": rating_grade,
            "recommendation": recommendation,
            "recommendation_conditions": recommendation_conditions or [],
            "target_sections": TARGET_SECTIONS,
            "aggregation": aggregation or {},
            "section_blocks": section_payload,
            "period_snapshot": _period_snapshot(facts_by_period, metric_by_period),
            "note_briefs": _build_note_briefs(notes_json),
        }

        user_prompt = (
            "Use the payload to rewrite memo sections in junior-analyst voice for senior approvers. "
            "Write original section narratives (do not copy template wording), include note references where relevant, "
            "and explicitly flag items requiring senior review. Return JSON only.\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        raw = _call_openai(SYSTEM_PROMPT, user_prompt)
        parsed = json.loads(_strip_json_fences(raw))
        sections = parsed.get("sections") if isinstance(parsed, dict) else None
        if not isinstance(sections, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in sections.items():
            if k in TARGET_SECTIONS and isinstance(v, str) and v.strip():
                out[k] = v.strip()
        if out:
            log.info("LLM memo narrative generated for %d sections", len(out))
        return out
    except Exception as e:
        log.warning("LLM memo narrative generation failed: %s", e)
        return {}
