# Documentation Guardrails — Step 6 (Generate Documentation)

> **Also read:** `guardrails/00_global_rules.md` (always applies)

---

## Gates

### Ground-Truth Validation Prerequisite
`ground_truth_validation.yaml` MUST exist before documentation can be written. If it does not exist, run the cross-validation sweep BEFORE generating documentation.

**Loading cross-validation in App context (execute_python):**
```python
import sys, os, shutil

deploy_root = os.environ.get("DEPLOY_ROOT", "/Workspace/Users/{username}/databricks-aibi-design-first-accelerator")
templates_dir = f"{deploy_root}/framework/templates"

tmp_dir = "/tmp/pipeline_python"
os.makedirs(tmp_dir, exist_ok=True)
shutil.copy2(f"{templates_dir}/gate_checks.py", f"{tmp_dir}/gate_checks.py")
sys.path.insert(0, tmp_dir)

from gate_checks import run_cross_validation, write_ground_truth_validation
report = run_cross_validation(OUTPUT_FOLDER, quality_gates=quality_gates)
write_ground_truth_validation(f"{OUTPUT_FOLDER}/ground_truth_validation.yaml", report, source="cross_validation_sweep")
```

---

## Required README Sections (ALL 11 MANDATORY)

The README MUST have ALL of these sections from `05_generate_documentation.md`:

1. **Solution Overview** — domain, version, status, generation date
2. **Architecture / Asset Flow** — text diagram: ERD → Tables → MVs → Dashboards → Genie
3. **Source Schema Summary** — table listing with roles, grains, relationships
4. **Data Layer** — table/row counts, validation status
5. **Metric Views** — MV listing with source, measures, dimensions, status
6. **KPI Catalog** — EVERY KPI from spec with status and notes
7. **Not Implemented KPIs** — reference SQL for each, reason, manual implementation guide
8. **Dashboards** — ID, page count, widget count, filter count, validation status
9. **Genie Space** — ID, instruction length, question counts, status
10. **Validation Summary** — per-layer pass/fail table
11. **Generated Artifacts** — complete inventory of all output files

---

## Prohibited Actions

1. DO NOT skip reading `05_generate_documentation.md` before writing README
2. DO NOT write a flat summary instead of the structured 11-section format
3. DO NOT report assets as successfully deployed if `ground_truth_validation.yaml` shows failures
4. DO NOT omit NOT_IMPLEMENTED KPIs from the catalog
5. DO NOT omit reference SQL for NOT_IMPLEMENTED KPIs
6. DO NOT re-execute earlier pipeline stages (data layer, metric views, dashboards) to produce ground_truth_validation.yaml
7. DO NOT run any notebook that imports `dbldatagen` during documentation — that is exclusively a Step 2 dependency

---

## Anti-Patterns

### AP-DOC-1: Flat README Instead of Structured Documentation
**Pattern:** Agent writes a 90-line flat summary with no artifact inventory, no architecture diagram, no per-KPI status table.
**Root cause:** Agent skipped reading `05_generate_documentation.md` entirely.
**Fix:** Enforcement checklist in master prompt requires all 11 sections. Compare against structured 107-line v3 README.

### AP-DOC-2: dbldatagen Import in Documentation Stage
**Pattern:** `ModuleNotFoundError: No module named 'dbldatagen'` during documentation or cross-validation.
**Root cause:** Agent tried to "re-execute failed stages" and went all the way back to data layer.
**Fix:** G-6 (no stage re-execution). Cross-validation reads EXISTING manifests — it creates nothing new.

### AP-DOC-3: Missing Ground-Truth Reference
**Pattern:** README says "All dashboards deployed" but doesn't reference `ground_truth_validation.yaml`.
**Root cause:** Agent self-reported dashboard status instead of citing the validation artifact.
**Fix:** Section 10 (Validation Summary) MUST reference ground_truth_validation.yaml.
