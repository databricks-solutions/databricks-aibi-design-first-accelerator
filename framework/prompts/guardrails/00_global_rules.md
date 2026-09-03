# Global Guardrails — Apply to ALL Pipeline Steps

These rules are BINDING for every step. Violations are pipeline failures.

---

## G-1: Manifest Integrity (API Readback Required)

All deployment manifests (`*_manifest.json`, `genie_manifest.json`) MUST be produced using **API readback validation**, not agent self-reporting.

**Required fields in every manifest:**
```yaml
validation_source: api_readback   # MUST be "api_readback" — never "agent_reported"
```

**Manifest writing procedure (NON-NEGOTIABLE):**
1. Deploy the asset via the API (create + publish for dashboards, POST for Genie)
2. Call `validate_dashboard_from_api()` or `validate_genie_from_api()` from `gate_checks.py`
3. Confirm the readback returns `status: PASS`
4. Write the manifest using **counts from the API readback**, NOT from agent memory
5. Include `validation_source: api_readback` in the manifest

**A manifest that claims success without API readback is FRAUD.** This is the #1 cause of pipeline failures: the agent writes `published: true` and `sample_questions_count: 10` without ever reading the deployed asset back, and the actual asset is empty.

**State checkpoint impact:**
- Manifest with `validation_source: api_readback` → trust and skip
- Manifest WITHOUT `validation_source` → re-run API readback validation before skipping
- No manifest → execute from the beginning

---

## G-2: MEASURE() Syntax Enforcement

All KPI queries against metric views MUST use `MEASURE()` syntax, never raw `SUM()`/`COUNT()`/`AVG()`.

```sql
-- CORRECT
SELECT claim_type, MEASURE(total_paid_amount) FROM metric_view GROUP BY ALL

-- WRONG — bypasses metric view semantics
SELECT claim_type, SUM(total_paid_amount) FROM metric_view GROUP BY claim_type
```

This applies to:
- Dashboard dataset SQL
- Genie example SQL
- Documentation sample queries
- Cross-validation sweep queries

---

## G-3: Column Name Authority (DESCRIBE Is Truth)

Physical column names MUST come from `DESCRIBE TABLE {metric_view_fqn}` (runtime) or `erd_parsed.yaml` (greenfield DDL), NOT from spec text, KPI descriptions, or agent memory.

**Why:** Metric view DDL uses aliases that differ from source table column names (e.g., `clm_dtl_claim_type` → `claim_type`, `clm_dtl_specific_dos_date` → `service_date`). Dashboard SQL must use metric view aliases, not source names.

**Enforcement:**
- `describe_metric_view()` in helpers template → returns actual columns
- `validate_column_refs()` → asserts all references exist
- `validate_domain_cols()` in dbldatagen template → asserts column names match schema

---

## G-4: Template Usage (Always Import, Never Hand-Write)

All deployment artifacts MUST be built using the project's template functions. Never hand-write JSON structures for:
- Dashboard widgets → use `build_bar_chart()`, `build_counter()`, `build_line_chart()`, `build_filter_widget()`
- Dashboard pages → use `build_canvas_page()`, `build_filters_page()`
- Dashboard assembly → use `build_serialized_dashboard()`, `deploy_dashboard()`
- Genie spaces → use the template notebook (`genie_space_notebook.py.template`)
- Synthetic data → use the template notebook (`dbldatagen_notebook.py.template`)
- Dashboard deployment → use the template notebook (`dashboard_notebook.py.template`)

**Why:** Hand-written JSON consistently omits required fields (e.g., `queryName` in filter widgets). Template functions include these fields unconditionally.

---

## G-5: No Silent Failures

NEVER catch and ignore errors during:
- SQL execution (dataset validation, metric view creation)
- API calls (dashboard create/publish, Genie space POST)
- Gate check assertions

If a step fails, it MUST either:
1. Raise an exception that halts the pipeline, OR
2. Write a FAIL status to the step's validation artifact

Catching an error and proceeding as if it succeeded is a pipeline violation.

---

## G-6: No Stage Re-Execution During Later Stages

NEVER re-run an earlier pipeline stage during a later stage:
- Do NOT re-run data layer notebooks during dashboard/Genie/documentation steps
- Do NOT re-create metric views during dashboard creation
- Do NOT regenerate synthetic data to fix a dashboard issue

If an earlier stage's output is missing or invalid:
1. HALT the current stage
2. Report the dependency failure
3. Let the orchestrator re-run the failed stage explicitly

**Specific prohibition:** Do NOT run any notebook that imports `dbldatagen` outside of Step 2 (Create Data Layer). The `dbldatagen` library is a Step 2 dependency only.

---

## G-7: Python 3.11 Compatibility

DO NOT use backslashes inside f-string `{}` expressions. This is a hard Python 3.11 syntax constraint.

```python
# ILLEGAL — SyntaxError on Python <3.12
f"{'\u2500' * 40}"
f"{'\n'.join(items)}"

# CORRECT — extract to variable
separator = '\u2500' * 40
f"{separator}"
joined = '\n'.join(items)
f"{joined}"
```

---

## G-8: Workspace I/O Rules

- Use `write_workspace_file` tool (Apps agent) or direct file I/O (Genie Code) for workspace files
- Do NOT use `dbutils.fs` for `/Workspace/` paths
- Do NOT use `os.makedirs` on `/Workspace/` paths from `execute_python` subprocess
- Do NOT use shell commands to create, write, or modify workspace files

---

## G-9: Anti-Shortcut Enforcement

The agent MUST NOT take shortcuts even when:
- "It's just a small change"
- "The previous step already validated this"
- "I know what the columns are from the spec"
- The context window is running low

Every numbered step must execute. Every GATE must be verified. Every Output Contract artifact must exist.
