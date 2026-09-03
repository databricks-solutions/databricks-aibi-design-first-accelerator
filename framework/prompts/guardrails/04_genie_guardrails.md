# Genie Space Guardrails — Step 5 (Create Genie Space)

> **Also read:** `guardrails/00_global_rules.md` (always applies)

---

## Enforcement Architecture

Genie space deployment uses the **template notebook pattern** (`genie_space_notebook.py.template`).
The LLM populates configuration cells (title, instructions, questions, SQL, benchmarks).
The template cells (8-10) handle API calls, validation, and post-deploy readback.

---

## Gates

### GATE 2.2: LLM Design Validation
Before proceeding to Genie creation, validate:
- Instructions >= 500 chars
- Sample questions >= 10
- Example SQL queries >= 10 (each syntactically valid)
- Benchmarks >= 10 (different phrasing from examples)

HALT if any threshold is not met.

### POST-DEPLOY: Blank Space Detection
After creation, read the space back via API and verify:
- `sample_questions` count matches what was sent
- Instructions text is non-empty
- Table identifiers are present

### POST-DEPLOY: API Readback
`validate_genie_from_api()` must return PASS. Write manifest only with `validation_source: api_readback`.

---

## Prohibited Actions

1. DO NOT bypass the notebook template — ALWAYS use `genie_space_notebook.py.template`
2. DO NOT use `createAsset(assetType="genie")` — it creates blank title-only spaces
3. DO NOT use raw SUM/COUNT/AVG in example SQL — ALWAYS use MEASURE() syntax
4. DO NOT skip SQL validation for example queries
5. DO NOT use column names from spec text — use DESCRIBE output
6. DO NOT create a Genie space with 0 sample questions
7. DO NOT create a Genie space with empty instructions
8. DO NOT skip the post-deploy API readback
9. DO NOT write the manifest without `validation_source: api_readback`
10. DO NOT report success if the API readback shows 0 sample questions
11. DO NOT use generic placeholder questions ("What is the total?")
12. DO NOT duplicate questions between sample_questions and benchmarks
13. DO NOT skip the benchmark questions — they evaluate Genie accuracy
14. DO NOT catch or suppress `GateCheckError` exceptions
15. DO NOT skip writing the Genie notebook to the output folder
16. DO NOT create spaces with instructions shorter than 500 characters
17. DO NOT skip the pre-deploy configuration validation (Cell 8)

---

## Anti-Patterns

### AP-GN-1: Blank Genie Space
**Pattern:** Manifest claims `sample_questions_count: 10` but API readback shows 0.
**Root cause:** Agent used `createAsset(assetType="genie")` which creates blank spaces.
**Fix:** MUST use template notebook pattern with full `serialized_space` payload.

### AP-GN-2: Raw Aggregation in Example SQL
**Pattern:** Example SQL uses `SELECT SUM(total_paid) ...` instead of `SELECT MEASURE(total_paid) ...`
**Root cause:** Agent wrote SQL from memory without following MEASURE() convention.
**Fix:** All example SQL MUST use MEASURE() syntax. Template validation cell checks this.

### AP-GN-3: Agent Bypasses Template
**Pattern:** Agent writes Genie notebook from scratch instead of reading and populating the template.
**Root cause:** Template path not loaded or agent took a shortcut.
**Fix:** Prompt enforces template usage. `create_genie_space` tool is disabled (returns error directing to template).
