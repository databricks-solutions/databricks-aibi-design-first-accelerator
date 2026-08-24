# Genie Space Configuration

Mandatory reference for Step 04. A Genie space is **not** complete until it is configured with instructions, sample questions, example SQLs, and benchmark questions via the **template notebook**.

> **Background:** Genie Code agents sometimes shortcut this step with `createAsset` or a bare `POST /api/2.0/genie/spaces`, producing a title-only space with no instructions, sample questions, or benchmarks. That fails validation and mirrors the "datasets-only dashboard" anti-pattern from Step 03. This doc defines the only acceptable path: populate `genie_space_notebook.py.template`, execute cells 8–10, and pass Cell 10 validation before proceeding.

---

## Deliverable

| ✅ Complete | ❌ Incomplete (do not proceed) |
|-------------|--------------------------------|
| Configuration notebook at `{workspace.output_folder}/genie_space/{notebook_name}` | Blank space created via UI `createAsset` |
| Cells 2–7 populated from KPI spec + metric view profiling | Empty space with title only |
| Cells 8–10 copied **verbatim** from `genie_space_notebook.py.template` | Hand-rolled API calls without `build_serialized_space()` |
| Cells 8 → 9 → 10 executed; Cell 10 validation report passes | Notebook created but never executed |
| `serialized_space` includes instructions, examples, benchmarks | `POST /api/2.0/genie/spaces` without full `serialized_space` |

**Analogy:** Same as dashboards — datasets without widgets is incomplete. A Genie space without `serialized_space` content is incomplete.

---

## Forbidden shortcuts

Do **not** use any of these as a substitute for the template notebook:

- **`createAsset`** or UI "Create Genie Space" — creates an empty shell with no instructions or benchmarks
- **`POST /api/2.0/genie/spaces`** with only `title`, `warehouse_id`, `parent_path` (no `serialized_space`)
- Hand-written REST payloads instead of `build_serialized_space()` in the template
- Leaving `<<< REPLACE >>>` placeholder text in cells 2–7
- Skipping execution of cells 8, 9, or 10

The Genie Space API **must** receive a full `serialized_space` JSON string built by the template helper. That helper lives in **Cell 8** — copy it verbatim from the template.

---

## Template workflow

Path: `{EXAMPLE_DIR}/{templates.genie_notebook}` → `genie_space_notebook.py.template`

| Cell | Action |
|------|--------|
| 1 | Replace `{{DOMAIN_NAME}}` |
| 2 | `SPACE_TITLE`, `SPACE_DESCRIPTION`, `WAREHOUSE_ID`, `PARENT_PATH`, `SPACE_ID=""` |
| 3 | `GENERAL_INSTRUCTIONS` — dimension/measure catalog, MEASURE() rules (> 500 chars) |
| 4 | `METRIC_VIEW_DESCRIPTIONS` — FQN → description (sorted keys) |
| 5 | `SAMPLE_QUESTIONS` — 15–20 natural-language questions |
| 6 | `EXAMPLE_QUESTION_SQLS` — 15–20 `(question, sql)` tuples |
| 7 | `BENCHMARK_QUESTIONS` — 15–20 `(question, sql)` tuples (different phrasing from cell 6) |
| 8–10 | **Copy verbatim** — helpers, create/update, validate |

Output notebook: `{workspace.output_folder}/genie_space/{assets.genie.notebook_name}`

Create via Workspace `import` (`format: JUPYTER`) — see `workspace_file_io.md`.

---

## `serialized_space` structure

### Authoritative Schema Reference

The complete `serialized_space` JSON schema is defined in the official Databricks documentation:

```text
https://docs.databricks.com/aws/en/genie-agents/conversation-api#understanding-the-serialized_space-field
```

Always consult this reference for the canonical field structure, required vs optional fields, and correct nesting. The example below shows the minimal structure used by this accelerator; the docs define additional optional fields (`sql_functions`, `join_specs`, `sql_snippets`, etc.).

Cell 8 `build_serialized_space()` assembles:

```json
{
  "version": 2,
  "config": {
    "sample_questions": [
      {"id": "<32-char-hex>", "question": ["What is the average fare per trip?"]}
    ]
  },
  "data_sources": {
    "tables": [
      {
        "identifier": "catalog.schema.metric_view_name",
        "description": ["Description of the metric view"],
        "column_configs": [{"column_name": "column_name"}]
      }
    ]
  },
  "instructions": {
    "text_instructions": [
      {"id": "<32-char-hex>", "content": ["Single-line instruction text with no newlines."]}
    ],
    "example_question_sqls": [
      {"id": "<32-char-hex>", "question": ["What is total revenue?"], "sql": ["SELECT MEASURE(total_paid) FROM catalog.schema.mv"]}
    ]
  },
  "benchmarks": {
    "questions": [
      {"id": "<32-char-hex>", "question": ["How much revenue?"], "answer": [{"format": "SQL", "content": ["SELECT ..."]}]}
    ]
  }
}
```

### Critical API Behaviors (Common Failures)

| Field | Behavior | Fix |
|-------|----------|-----|
| `data_sources` | Key is **`tables`** (NOT `metric_views`) | Always use `data_sources.tables[]` |
| `text_instructions[].content[]` | API **truncates at newline characters** (`\n`) — only the first line is persisted | Instructions MUST be a **single continuous string with no newlines** |
| `column_configs` | Optional per table — lists columns for reference. **Must be sorted alphabetically by `column_name`** or API rejects with InvalidParameterValue | Sort with `sorted(configs, key=lambda x: x['column_name'])` |
| All IDs | Must be 32-character lowercase hex UUIDs | Use `uuid.uuid4().hex` |
| All text fields | Wrapped in arrays `["text"]` | Always use `["..."]` not bare strings |

**Instruction format (CRITICAL):**

The `text_instructions[].content[0]` string MUST NOT contain `\n` characters. The Genie API truncates at the first newline, silently discarding everything after it.

```python
# WRONG — will be truncated to first line only:
"content": ["Line one.\nLine two.\nLine three."]
# → API stores only: "Line one."

# CORRECT — single continuous string, use spaces/punctuation for separation:
"content": ["Line one. Line two. Line three."]
# → API stores complete text
```

If instructions are long, use sentence-based formatting with periods and spaces — never newlines.

- **text_instructions:** exactly one block (`GENERAL_INSTRUCTIONS`) — must be a single line (no `\n`)
- **example_question_sqls:** teaches Genie how to answer (part of instructions)
- **benchmarks:** evaluates accuracy only — Genie does not learn from these

All SQL must use `MEASURE()` and `GROUP BY ALL` against metric view FQNs.

---

## Execute and validate

1. Open the configuration notebook (`openAsset` or equivalent).
2. Run **Cell 8** (load helpers) → **Cell 9** (create/update space) → **Cell 10** (validate).
3. Cell 9 must return `✅ SUCCESS` with a `space_id`.
4. Cell 10 must print a validation report. **Halt** if any check fails:

| Check | Minimum |
|-------|---------|
| Benchmark questions | ≥ `validation.min_benchmark_questions` from `accelerator.yaml` |
| Sample questions | ≥ 15 |
| Example question SQLs | ≥ 15 |
| Text instructions | > 500 characters |
| Metric views | ≥ 1 (all primary/secondary metric views listed) |

5. Copy returned `space_id` into Cell 2 (`SPACE_ID = "..."`) for idempotent updates.

---

## Delete existing space (idempotent)

Before create, list spaces and delete any matching `assets.genie.space_name` so reruns do not leave orphaned blank spaces.

---

## Fail-fast

On API failure, report status code, `error_code`, and message. Do not mark Step 04 complete if Cell 10 shows zero benchmarks or placeholder instructions.
