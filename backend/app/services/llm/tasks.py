"""
LLM semantic tasks: region classification, scale extraction, canonical mapping, note classification, risk snippets.
Each task: cache check → OpenAI (temperature=0) → Pydantic validate → cache set → return.
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from app.config import get_settings
from app.schemas.llm_semantic import (
    SCHEMA_VERSION,
    PROMPT_VERSION,
    StatementRegionClassification,
    PresentationScaleOutput,
    CanonicalMappingOutput,
    NoteClassificationOutput,
    RiskSnippetOutput,
    StatementTableParseOutput,
)
from app.services.llm.cache import get_cached, set_cached
from app.services.llm.prompts import (
    REGION_CLASSIFICATION_SYSTEM,
    build_region_classification_prompt,
    SCALE_EXTRACTION_SYSTEM,
    build_scale_extraction_prompt,
    CANONICAL_MAPPING_SYSTEM,
    build_canonical_mapping_prompt,
    NOTE_CLASSIFICATION_SYSTEM,
    build_note_classification_prompt,
    RISK_SNIPPET_SYSTEM,
    build_risk_snippet_prompt,
    STATEMENT_TABLE_PARSER_SYSTEM,
    build_statement_table_parser_prompt,
)

TASK_REGION_CLASSIFIER = "region_classifier"
TASK_SCALE_EXTRACTOR = "scale_extractor"
TASK_CANONICAL_MAPPER = "canonical_mapper"
TASK_NOTE_CLASSIFIER = "note_classifier"
TASK_RISK_SNIPPETS = "risk_snippets"
TASK_STATEMENT_TABLE_PARSER = "statement_table_parser"

CONFIDENCE_THRESHOLD = 0.80  # Below this → canonical_key="UNMAPPED"


def _call_llm(system: str, user_content: str) -> str:
    """Call OpenAI with temperature=0. Returns raw content."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not set")
    if settings.log_llm_prompts:
        logger.info("LLM SYSTEM PROMPT:\n%s", system[:2000] + ("..." if len(system) > 2000 else ""))
        logger.info("LLM USER CONTENT (len=%d):\n%s", len(user_content), user_content[:3000] + ("..." if len(user_content) > 3000 else ""))
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def _parse_json_response(content: str) -> dict:
    """Strip markdown code fence if present and parse JSON."""
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.lower().startswith("json"):
            s = s[4:]
    return json.loads(s.strip())


def _normalize_statement_region_payload(data: dict) -> dict:
    """
    LLMs sometimes emit evidence_spans with bbox=null or malformed values.
    Clean these before Pydantic validation so we don't crash the pipeline.
    """
    regions = data.get("regions") or []
    normalized_regions: list[dict[str, Any]] = []
    for region in regions:
        region_dict = dict(region)
        spans = region_dict.get("evidence_spans") or []
        normalized_spans: list[dict[str, Any]] = []
        for span in spans:
            span_dict = dict(span)
            bbox = span_dict.get("bbox")
            # Keep only spans with a proper 4-number bbox
            if (
                isinstance(bbox, (list, tuple))
                and len(bbox) >= 4
                and all(isinstance(v, (int, float)) for v in bbox[:4])
            ):
                span_dict["bbox"] = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                normalized_spans.append(span_dict)
        region_dict["evidence_spans"] = normalized_spans
        normalized_regions.append(region_dict)
    data["regions"] = normalized_regions
    return data


def llm_region_classifier(regions_input: list[dict], document_version_id: str) -> StatementRegionClassification | None:
    """
    Input: [{"region_id": "page18_left", "page": 18, "text": "..."}]
    Output: StatementRegionClassification (regions with statement_type, entity_scope, evidence_spans).
    """
    if not regions_input:
        return StatementRegionClassification(regions=[])

    # Cache at whole-document level so repeated calls don't re-run batches
    payload = {"document_version_id": document_version_id, "regions": regions_input}
    cached = get_cached(TASK_REGION_CLASSIFIER, payload)
    if cached is not None:
        return StatementRegionClassification.model_validate(_normalize_statement_region_payload(cached))

    settings = get_settings()
    if not settings.openai_api_key:
        return None

    # Batch regions to keep each request within token limits
    all_regions: list[dict] = []
    batch_size = 8  # 79 pages -> ~10 calls max
    for i in range(0, len(regions_input), batch_size):
        chunk = regions_input[i : i + batch_size]
        content = _call_llm(REGION_CLASSIFICATION_SYSTEM, build_region_classification_prompt(chunk))
        data = _parse_json_response(content)
        data = _normalize_statement_region_payload(data)
        chunk_out = StatementRegionClassification.model_validate(data)
        all_regions.extend([r.model_dump() for r in chunk_out.regions])

    # Re-validate combined regions through the schema (after normalizing again for safety)
    combined = StatementRegionClassification.model_validate(
        _normalize_statement_region_payload({"regions": all_regions})
    )

    set_cached(TASK_REGION_CLASSIFIER, payload, combined.model_dump(), settings.llm_model)
    return combined


def llm_scale_extractor(region_id: str, text: str, document_version_id: str) -> PresentationScaleOutput | None:
    """Extract presentation scale/currency from region text. Missing evidence → scale=unknown + warning."""
    payload = {"document_version_id": document_version_id, "region_id": region_id, "text": text[:20000]}
    cached = get_cached(TASK_SCALE_EXTRACTOR, payload)
    if cached is not None:
        return PresentationScaleOutput.model_validate(cached)
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    content = _call_llm(SCALE_EXTRACTION_SYSTEM, build_scale_extraction_prompt(region_id, text))
    data = _parse_json_response(content)
    out = PresentationScaleOutput.model_validate(data)
    set_cached(TASK_SCALE_EXTRACTOR, payload, out.model_dump(), settings.llm_model)
    return out


def llm_canonical_mapper(
    statement_lines: list[dict],
    document_version_id: str,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> CanonicalMappingOutput | None:
    """
    Input: [{"statement_type": "SFP", "section_path": ["Assets", "Current assets"], "raw_label": "Trade and other receivables"}, ...]
    Output: mappings with canonical_key; if confidence < threshold → canonical_key="UNMAPPED".
    """
    if not statement_lines:
        return CanonicalMappingOutput(mappings=[])
    payload = {"document_version_id": document_version_id, "lines": statement_lines}
    cached = get_cached(TASK_CANONICAL_MAPPER, payload)
    if cached is not None:
        return CanonicalMappingOutput.model_validate(cached)
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    # Batch lines to keep each request within token / rate limits
    batch_size = 80
    all_mappings: list[dict] = []
    for i in range(0, len(statement_lines), batch_size):
        chunk = statement_lines[i : i + batch_size]
        content = _call_llm(CANONICAL_MAPPING_SYSTEM, build_canonical_mapping_prompt(chunk))
        data = _parse_json_response(content)
        for m in data.get("mappings", []):
            if m.get("confidence", 0) < confidence_threshold:
                m["canonical_key"] = "UNMAPPED"
        out_chunk = CanonicalMappingOutput.model_validate(data)
        all_mappings.extend([m.model_dump() for m in out_chunk.mappings])

    combined = CanonicalMappingOutput.model_validate({"mappings": all_mappings})
    set_cached(TASK_CANONICAL_MAPPER, payload, combined.model_dump(), settings.llm_model)
    return combined


def llm_note_classifier(
    note_number: str | int,
    title: str,
    body_text: str,
    document_version_id: str,
) -> NoteClassificationOutput | None:
    """Classify note type, table types, covenant/security flags. No numeric extraction."""
    payload = {"document_version_id": document_version_id, "note_number": str(note_number), "title": title, "body": body_text[:15000]}
    cached = get_cached(TASK_NOTE_CLASSIFIER, payload)
    if cached is not None:
        return NoteClassificationOutput.model_validate(cached)
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    content = _call_llm(NOTE_CLASSIFICATION_SYSTEM, build_note_classification_prompt(note_number, title, body_text))
    data = _parse_json_response(content)
    out = NoteClassificationOutput.model_validate(data)
    set_cached(TASK_NOTE_CLASSIFIER, payload, out.model_dump(), settings.llm_model)
    return out


def llm_risk_snippets(text: str, document_version_id: str) -> RiskSnippetOutput | None:
    """Find and tag risk language with citations only."""
    payload = {"document_version_id": document_version_id, "text": text[:25000]}
    cached = get_cached(TASK_RISK_SNIPPETS, payload)
    if cached is not None:
        return RiskSnippetOutput.model_validate(cached)
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    content = _call_llm(RISK_SNIPPET_SYSTEM, build_risk_snippet_prompt(text))
    data = _parse_json_response(content)
    out = RiskSnippetOutput.model_validate(data)
    set_cached(TASK_RISK_SNIPPETS, payload, out.model_dump(), settings.llm_model)
    return out


def llm_statement_table_parser(
    region_id: str,
    text: str,
    statement_type_hint: str | None,
    document_version_id: str,
) -> StatementTableParseOutput | None:
    """
    Universal table parser: given raw statement text, return column headers (period_labels)
    and data rows (raw_label + values_json). Same flow for SFP, SCI, CF, SOCE.
    """
    if not (text or "").strip():
        return StatementTableParseOutput(period_labels=[], lines=[], warnings=["empty text"])
    payload = {
        "document_version_id": document_version_id,
        "region_id": region_id,
        "text": text[:12000],
        "statement_type_hint": statement_type_hint,
    }
    cached = get_cached(TASK_STATEMENT_TABLE_PARSER, payload)
    if cached is not None:
        return StatementTableParseOutput.model_validate(cached)
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    content = _call_llm(
        STATEMENT_TABLE_PARSER_SYSTEM,
        build_statement_table_parser_prompt(region_id, text, statement_type_hint),
    )
    data = _parse_json_response(content)
    out = StatementTableParseOutput.model_validate(data)
    set_cached(TASK_STATEMENT_TABLE_PARSER, payload, out.model_dump(), settings.llm_model)
    return out
