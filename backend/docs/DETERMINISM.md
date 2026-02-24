# Determinism Guarantees

The credit analysis pipeline is designed to be deterministic: same inputs → same outputs.

## Rules

1. **Mapping Pass A + B**
   - Uses ordered `RAW_TO_CANONICAL` and `pass_b_patterns()` lists.
   - Iteration order is fixed; first match wins.
   - Coalesced facts are emitted in sorted `(canonical_key, period_end)` order.
   - `mapping_rules.map_raw_label` has no random or nondeterministic logic.

2. **LLM Suggestions Never Auto-Apply**
   - `suggest_canonical_key` / `suggest_batch` are API-only; used for human-assisted suggestions.
   - The mapping pipeline uses only `map_raw_label` (rule-based). No LLM output is persisted without explicit user action.

3. **No Randomization**
   - No `random` usage in mapping, financial engine, rating, or memo builders.
   - If future code adds randomness, it must be seeded and documented.

4. **Stable Sorting**
   - All dict iterations that affect output order use explicit `sorted()` where order matters.
   - Example: `facts_by_key` coalescence iterates in sorted order.

## Verification

Run the gold test suite:

```bash
cd backend
python -m tests.gold_runner
```

Exit 0 = all gold documents produce output identical to snapshots.
