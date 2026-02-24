# Provenance & Audit Trail

Every number and claim in the credit memo can be traced back to source.

## NormalizedFact provenance

Each `NormalizedFact` stores `source_refs_json` with:

- **page** — PDF page number
- **line_no** — row/line in extraction
- **raw_label** — original label from statements
- **source_sheet** — Excel sheet (e.g. SFP_GROUP)
- **mapping_method** — RULE, REGEX, or UNMAPPED
- **mapping_confidence** — 0.95 (RULE), 0.85 (REGEX), 0 (UNMAPPED)
- **extraction_cell_ref** — e.g. `SFP_GROUP!row_12`
- **entity_scope** — GROUP or COMPANY

## MetricFact provenance

Each `MetricFact` stores `calc_trace_json` with:

- **formula_id** — e.g. `v1_net_debt_to_ebitda`
- **inputs** — list of `{canonical_key, period_end, value}`
- **output** — computed value

## Analysis output provenance

`analysis_output["provenance"]` contains:

- **facts** — list of fact provenance (canonical_key, period_end, value_base, source_refs)
- **metrics** — list of metric provenance (metric_key, period_end, value, calc_trace)
- **section_citations** — per-section mapping of metric_keys and evidence_notes

## UI/API usage

To show "click memo bullet → see facts + page refs":

1. Map section key to `section_citations[section_key]` for metric_keys and evidence_notes.
2. Look up metric provenance by metric_key + period_end for calc_trace (inputs).
3. For each input canonical_key, look up fact provenance for source_refs (page, raw_label, etc.).
