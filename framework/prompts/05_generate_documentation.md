# Generate Documentation

## Role

Produce a factual, auditable run summary after all accelerator pipeline stages complete.

The documentation must describe:

- what inputs were used;
- what semantic/data assets were created;
- which KPIs were successfully implemented;
- which KPIs were skipped and why;
- which dashboards and Genie assets were deployed;
- which validation checks passed or failed;
- how the generated assets relate to one another;
- how a user can consume the resulting solution.

The documentation MUST be derived from generated pipeline artifacts and deployed-asset manifests.

Do not reconstruct results from memory or assumptions.

---

# Core Principle

Documentation must reflect the actual final state of the accelerator run:

```text
Configuration
    ↓
Data / Schema Layer
    ↓
Metric Layer
    ↓
Dashboard Layer
    ↓
Genie Layer
    ↓
Validation Artifacts
    ↓
README
```

If an asset failed or was skipped, document that explicitly.

Do not present planned assets as successfully created assets.

---

## State & Checkpoint Contract

This step uses **artifact-as-state** checkpointing (see `07_state_contract.md`).
The same rules apply in App mode and Genie Code — no backend infrastructure required.

**Before executing each phase**, check whether its output artifact already exists.
If it exists and is structurally valid → **skip** that phase and call `report_progress(status="completed")` immediately.
If it does not exist → execute the phase normally.

**Verification flow (run at the START of this step, after loading config):**

1. List the output folder.
2. Manage `run_context.yaml` per `07_state_contract.md` Section 8.
3. For each artifact below, apply ONE cheap check:
   - `readme.md` exists: skip generate_documentation
   - `run_manifest.json` exists: skip generate_manifest
4. Continue from the **first phase whose artifact is missing**.
5. On step completion, set `status: completed` in `run_context.yaml`.

**Note:** Documentation is always safe to regenerate (idempotent overwrite). On explicit re-run, ignore existing artifacts and regenerate.

**Artifact-as-State mapping:**

| Phase | Artifact | Skip when |
|-------|----------|----------|
| gather_artifacts | Artifacts loaded | Always re-read (stateless) |
| generate_documentation | readme.md | file exists in output folder |
| generate_manifest | run_manifest.json | file exists |

---

# Step 1: Load Configuration

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "gather_artifacts"
> - `phase_name`: "Gather Artifacts"
> - `status`: "started"
> - `current_task`: "Loading configuration and run artifacts"
> - `happenings`: ["Reading accelerator.yaml", "Loading run artifacts", "Establishing artifact authority"]

Read:

```text
accelerator.yaml
```

with all asset-name and version-suffix resolution applied.

Capture:

```text
domain.name
domain.display_name
data_source.type
config.version_suffix
catalog.source
catalog.target
assets.metric_views
assets.dashboards
assets.genie
workspace.output_folder
```

Only include configuration values relevant to understanding the generated solution.

Do not dump the full configuration file into the README.

---

# Step 2: Load Run Artifacts

Read all artifacts that exist for this run.

Potential artifacts include:

```text
erd_parsed.yaml
semantic_model.yaml
synthetic_data_spec.yaml
data_layer_validation.yaml

schema_profile.yaml
kpi_metric_mapping.yaml
metric_view_design.yaml
metric_view_validation.yaml

dashboards/dashboard_design.yaml
dashboards/dashboard_dataset_validation.yaml
dashboards/*_manifest.json
dashboards/*_validation.yaml

genie_space/genie_semantic_inventory.yaml
genie_space/*_manifest.json
genie_space/*_validation.yaml

genie_space/{assets.sample_queries_file}
```

Do not require artifacts that are not applicable to the configured `data_source.type`.

Examples:

- `live_schema` may not have `erd_parsed.yaml`.
- `erd` may not have live-schema drift information.
- Genie may be disabled.
- Dashboards may be disabled or only partially generated.

Document only artifacts applicable to the current run.

---

# Step 3: Establish Artifact Authority

Use generated validation and manifest artifacts as the source of truth.

Preferred authority order:

```text
Validation artifact
    ↓
Deployment manifest
    ↓
Design artifact
    ↓
Configuration
```

Examples:

For Metric Views:

```text
metric_view_validation.yaml
```

determines whether KPIs are implemented and validated.

For Dashboards:

```text
*_validation.yaml
+
*_manifest.json
```

determine deployment state.

For Genie:

```text
*_validation.yaml
+
*_manifest.json
```

determine final Genie state.

Do not state that an asset is successful solely because it appears in `accelerator.yaml`.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "gather_artifacts"
> - `phase_name`: "Gather Artifacts"
> - `status`: "completed"
> - `findings`: ["{N} artifacts loaded", "Artifact authority established"]
> - `stats`: {"artifacts_loaded": N, "steps_documented": M}

---

# Step 4: Determine Overall Run Status

Determine:

```text
PASS
PARTIAL_SUCCESS
FAIL
```

Use:

### PASS

All mandatory enabled pipeline stages completed successfully and their mandatory validations passed.

### PARTIAL_SUCCESS

Core pipeline completed but one or more optional:

- KPIs;
- widgets;
- dashboards;
- Genie questions;
- semantic elements

were skipped or failed without invalidating the overall solution.

### FAIL

A mandatory pipeline stage failed or required validation did not pass.

Document the reason.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_documentation"
> - `phase_name`: "Generate Documentation"
> - `status`: "started"
> - `current_task`: "Writing comprehensive README documentation"
> - `happenings`: ["Documenting data layer", "Documenting metric views", "Documenting dashboards and Genie"]

---

# Step 5: Write README

### Pre-Flight Checklist

Before writing the README, confirm:

- [ ] `accelerator.yaml` loaded with resolved version suffix
- [ ] All applicable run artifacts from Step 2 have been read (do not skip available artifacts)
- [ ] Artifact authority hierarchy applied (Step 3)
- [ ] Overall run status determined (Step 4)
- [ ] For every asset to be documented: corresponding manifest or validation artifact exists
- [ ] No artifact shows `status: FAIL` on a mandatory check without being classified correctly in Step 4

If a required artifact cannot be read (workspace IO error), classify as `DOCUMENTATION_ARTIFACT_MISSING` and document the gap rather than guessing.

Create:

```text
{workspace.output_folder}/readme.md
```

using Workspace API / agent tools defined by:

```text
workspace_file_io.md
```

Never use `dbutils.fs` for `/Workspace/`.

The README must contain the following sections.

---

# 1. Solution Overview

Include:

- domain display name;
- resolved domain name;
- accelerator version suffix;
- data-source mode;
- source catalog/schema locations;
- target catalog/schema;
- overall run status.

Provide a short factual description of what the generated solution contains.

Example structure:

```text
This accelerator run created a semantic analytics solution for <domain> using <data source mode>. The solution includes <N> Metric Views, <N> dashboards, and <Genie status>.
```

Include reproducibility metadata:

```text
Generated: <ISO 8601 timestamp>
LLM Model: <llm.default_model from accelerator.yaml>
Vision Model: <llm.vision_model from accelerator.yaml>
Version: <config.version_suffix>
```

This enables consumers to understand which model produced the solution and when.

Do not use marketing language.

---

# 2. Architecture / Asset Flow

Document the generated solution flow.

Use a simple text diagram such as:

```text
Source Data / ERD
      ↓
Unity Catalog Tables
      ↓
Metric Views
      ↓
AI/BI Dashboards
      ↓
Genie Space / Agent
```

Modify this based on the actual run.

For brownfield runs where no tables were generated:

```text
Existing Unity Catalog Data
      ↓
Metric Views
      ↓
Dashboards / Genie
```

Do not show stages that did not execute.

---

# 3. Source Schema Summary

For `erd` or greenfield portions of `erd_and_live_schema`, summarize:

```text
erd_parsed.yaml
semantic_model.yaml
```

Include:

- number of tables;
- table roles;
- important grains;
- relationship count;
- unresolved ERD elements if any.

Do not reproduce every column.

Provide a compact table such as:

| Table | Role | Grain | Key Relationships |
|---|---|---|---|

---

For `live_schema` or live portions of `erd_and_live_schema`, summarize:

```text
schema_profile.yaml
```

Include:

- catalogs/schemas profiled;
- table count;
- fact/dimension/bridge/SCD classifications;
- significant schema gaps;
- schema drift if present.

For `erd_and_live_schema`, explicitly document ERD-vs-live drift.

---

# 4. Data Layer

Include this section only when greenfield data generation ran.

Summarize:

- Unity Catalog tables created;
- synthetic-data generation status;
- row counts by major table;
- PK validation;
- FK validation;
- cardinality validation;
- semantic constraint validation.

Source these facts from:

```text
data_layer_validation.yaml
```

Report failures or generic fallback columns where relevant.

Do not claim synthetic data is realistic merely because generation succeeded.

---

# 5. Metric Views

List every generated Metric View.

For each include:

```text
name
FQN
source table
source grain
validated measures
major dimensions
validation status
```

Source from:

```text
metric_view_design.yaml
metric_view_validation.yaml
```

Use a table such as:

| Metric View | Source Grain | Measures | Dimensions | Status |
|---|---|---|---|---|

If multiple Metric Views were created because of incompatible fact grains, explain that briefly.

---

# 6. KPI Catalog

Document every KPI from the KPI specification.

Use:

```text
kpi_metric_mapping.yaml
metric_view_validation.yaml
```

For each KPI report its final status.

Allowed documentation statuses should reflect the Metric View validation artifact, such as:

```text
IMPLEMENTED_AND_VALIDATED
SKIPPED_MISSING_DATA
SKIPPED_UNRESOLVED_RELATIONSHIP
SKIPPED_UNSAFE_GRAIN
SKIPPED_UNSUPPORTED_SEMANTICS
SKIPPED_UNSUPPORTED_METRIC_VIEW_FEATURE
```

Use:

| KPI | Metric View | Measure | Status | Notes |
|---|---|---|---|---|

Do not collapse all skipped KPIs into a generic "not implemented."

Include the actual reason.

---

# 7. Dashboards

For every dashboard manifest found in:

```text
{workspace.output_folder}/dashboards/
```

include:

- display name;
- dashboard ID;
- source Metric View(s);
- page count;
- widget count;
- filter count;
- publication status;
- validation status;
- workspace/AI/BI link if present in the manifest/API response.

Use:

```text
*_manifest.json
*_validation.yaml
```

as the authoritative sources.

Example:

| Dashboard | ID | Pages | Widgets | Published | Validation |
|---|---|---|---|---|---|

### Deployed Asset Links

When `workspace.host` is available from `databricks.yml`, construct clickable links:

```text
Dashboard: {workspace.host}/dashboardsv3/{dashboard_id}/published
Genie Space: {workspace.host}/genie/rooms/{space_id}
```

Only construct links when both `workspace.host` and the asset ID are verified from manifests.

Do not construct URLs from assumptions if a verified ID is unavailable.

---

# 8. Genie Space / Genie Agent

If Genie is enabled and successfully deployed, document:

- title;
- space ID;
- warehouse ID;
- attached Metric Views;
- sample-question count;
- example-SQL count;
- benchmark count;
- benchmark pass rate where available;
- configuration notebook path;
- validation status.

Source from:

```text
genie_semantic_inventory.yaml
*_manifest.json
*_validation.yaml
```

Do not report Genie as validated solely because the space exists.

If Genie creation was skipped or failed, state that explicitly.

---

# 9. Validation Summary

Provide one concise consolidated validation table.

Example:

| Layer | Validation | Result |
|---|---|---|
| Data Layer | Schema integrity | PASS |
| Data Layer | PK/FK integrity | PASS |
| Metric Layer | KPI reconciliation | PASS |
| Metric Layer | Join fanout checks | PASS |
| Dashboards | Dataset SQL | PASS |
| Dashboards | Filter binding | PASS |
| Genie | Example SQL | PASS |
| Genie | Benchmarks | PASS |

Include only applicable checks.

If a validation failed, link it to the corresponding generated validation artifact path.

---

# 10. Known Limitations

Document known gaps and constraints of the generated solution.

Sources:

- Skipped KPIs from `metric_view_validation.yaml` (with reasons)
- `GENERIC_FALLBACK` columns from `data_layer_validation.yaml`
- Unresolved ERD elements from `erd_parsed.yaml`
- Failed benchmark questions from Genie validation
- Any `WARN` conditions from upstream validations

Structure:

| Limitation | Layer | Impact | Reason |
|---|---|---|---|
| MC-4 (High-Cost Member Count) | Metric View | KPI not available | Requires pre-aggregation not supported in YAML 1.1 |
| W-2 (MoM Growth) | Metric View | KPI not available | LAG() not supported in metric view window |

Do not speculate about limitations not evidenced by artifacts.

Do not minimize documented limitations with qualifiers like "minor" or "unlikely to matter."

This section is critical for consumer trust — it sets accurate expectations.

---

# 11. Usage

Explain how a consumer should use the generated assets.

## Query Metric Views

Provide a small generic example using the actual generated Metric View and measure names:

```sql
SELECT
    <dimension>,
    MEASURE(<validated_measure>)
FROM <metric_view_fqn>
GROUP BY ALL;
```

Use real validated asset names from this run.

Do not invent example measures.

---

## Dashboards

Explain:

- which dashboard(s) to open;
- their intended purpose;
- where to find the dashboard ID/link.

---

## Genie

Explain:

- which Genie Space to open;
- that questions should use the configured semantic model;
- examples of representative sample questions from the generated sample-question inventory.

Do not introduce new unsupported questions.

---

# 12. Troubleshooting

Include this section when overall status is `PARTIAL_SUCCESS` or `FAIL`.

For each failed or degraded layer, provide:

```text
Layer: <Data Layer | Metric Views | Dashboards | Genie>
Symptom: <what the user will observe>
Root Cause: <from validation artifact>
Resolution: <specific next step>
Artifact: <path to validation file with details>
```

Common patterns:

| Symptom | Likely Cause | Resolution |
|---|---|---|
| Dashboard shows "No rows returned" | FK integrity failure in data layer | Re-run `01_create_data_layer` with fixed FK generation |
| Metric View returns zero rows | Join column mismatch (STRING vs BIGINT) | Check `data_layer_validation.yaml` §7.9 analytical readiness |
| Genie gives wrong answers | Incorrect MEASURE() SQL | Check `genie_validation.yaml` benchmark failures |
| Dashboard filters don't respond | Missing filter column in dataset SQL | Check `dashboard_validation.yaml` filter binding |

Adapt based on actual failures observed in this run's validation artifacts.

Do not include this section when status is `PASS`.

---

# 13. Generated Artifacts

List important generated files by logical category.

Example:

```text
Schema
- erd_parsed.yaml
- semantic_model.yaml

Metrics
- kpi_metric_mapping.yaml
- metric_view_design.yaml
- metric_view_validation.yaml

Dashboards
- dashboard_design.yaml
- <dashboard>_manifest.json
- <dashboard>_validation.yaml

Genie
- genie_semantic_inventory.yaml
- <space>_manifest.json
- <space>_validation.yaml
```

Only list files that actually exist.

---

# 12. Configuration Reference

Summarize the primary `accelerator.yaml` configuration used by this run.

Include relevant keys such as:

```text
domain
data_source.type
catalog.source
catalog.target
assets.metric_views
assets.dashboards
assets.genie
config.version_suffix
```

Reference:

```text
accelerator.yaml
```

for full configuration.

Do not duplicate the complete YAML.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_documentation"
> - `phase_name`: "Generate Documentation"
> - `status`: "completed"
> - `findings`: ["README.md generated", "All sections written from artifacts"]
> - `stats`: {"sections_written": N}

---

# Step 6: Validate, Check Placeholders, and Write Manifest (SINGLE PASS)

## CRITICAL — EFFICIENCY (saves 10+ tool calls)

Steps 6, 7, and 8 are ONE logical pass. Do NOT re-read any artifact files.
You already loaded ALL artifacts in Steps 1-2 — they are in your context.

Do NOT:
- Re-read erd_parsed.yaml, semantic_model.yaml, metric_view_design.yaml, manifests, etc.
- Re-read validation YAML files you already loaded
- Call read_workspace_file for any artifact you already have in context
- Validate assets one at a time with separate file reads

DO:
- Validate from context/memory (all artifact data is already loaded from Steps 1-2)
- Check consistency + scan for placeholders + prepare run_manifest.json in ONE logical pass
- Write readme.md in ONE write_workspace_file call
- Write run_manifest.json in ONE write_workspace_file call
- Report progress completed immediately after the two writes
- Total tool calls for this entire step: 2-3 (write readme + write manifest + report_progress)

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_documentation"
> - `phase_name`: "Validate Documentation"
> - `status`: "started"
> - `current_task`: "Validating factual consistency and completeness"
> - `happenings`: ["Checking factual consistency", "Scanning for placeholders", "Writing run manifest"]

## 6.1 Factual Consistency (from context — NO file reads)

Validate every stated asset against its authoritative manifest/validation artifact **using data already in your context from Step 2**.

Check:

```text
Metric View listed → actually exists in design/validation
Dashboard listed → dashboard_id exists in manifest
Published dashboard → published=true
Genie listed → space_id exists
Validated KPI → validation status is IMPLEMENTED_AND_VALIDATED
Skipped KPI → documented reason exists
```

If documentation conflicts with generated artifacts:

```text
DOCUMENTATION_CONSISTENCY_ERROR
```

Fix the documentation.

Do not modify upstream artifacts merely to make documentation consistent.

## 6.2 No Placeholder Check (inline — NO file reads)

Confirm the README contains none of:

```text
<<< REPLACE >>>
TODO
TBD
<placeholder>
example_dashboard_id
example_space_id
```

unless `TODO` or `TBD` is itself actual source content that must be documented.

## 6.3 Write Run Manifest

After README generation, write the machine-readable run manifest:

```text
{workspace.output_folder}/run_manifest.json
```

using Workspace API / agent tools.

Structure:

```json
{
  "version": "<VERSION_SUFFIX>",
  "domain": "<domain.name>",
  "status": "PASS | PARTIAL_SUCCESS | FAIL",
  "timestamp": "<ISO 8601 UTC>",
  "llm": {
    "default_model": "<llm.default_model from accelerator.yaml>",
    "vision_model": "<llm.vision_model>"
  },
  "data_source": {
    "type": "<data_source.type>",
    "catalog": "<catalog.source.catalog>",
    "schema": "<catalog.source.schema>"
  },
  "assets": {
    "tables": {"count": N, "status": "PASS|FAIL|SKIPPED"},
    "metric_views": [{"name": "...", "fqn": "...", "status": "..."}],
    "dashboards": [{"name": "...", "dashboard_id": "...", "published": true, "url": "..."}],
    "genie_spaces": [{"title": "...", "space_id": "...", "benchmark_pass_rate": 0.85}]
  },
  "kpis": {
    "total": N,
    "implemented": N,
    "skipped": N,
    "skipped_reasons": {"UNSUPPORTED_SEMANTICS": N, "MISSING_DATA": N}
  },
  "validation": {
    "data_layer": "PASS|FAIL|SKIPPED",
    "metric_views": "PASS|FAIL",
    "dashboards": "PASS|FAIL|SKIPPED",
    "genie": "PASS|FAIL|SKIPPED"
  },
  "artifacts": [
    "erd_parsed.yaml",
    "semantic_model.yaml",
    "..."
  ],
  "readme_path": "{workspace.output_folder}/readme.md"
}
```

Populate from the same authoritative sources used for the README.

Do not include fields for disabled/skipped stages.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_documentation"
> - `phase_name`: "Validate Documentation"
> - `status`: "completed"
> - `findings`: ["Factual consistency: PASS", "No placeholders found", "Manifest written"]
> - `stats`: {"validation_checks": N, "checks_passed": N}

---

# Step 9: Final Output

Write:

```text
{workspace.output_folder}/readme.md
{workspace.output_folder}/run_manifest.json
```

Then report:

```text
README path
Run manifest path
overall run status
Metric View count
validated KPI count
skipped KPI count
dashboard count
Genie status
```

---

# Error Classification

Use:

```text
DOCUMENTATION_INPUT_ERROR
DOCUMENTATION_ARTIFACT_MISSING
DOCUMENTATION_CONSISTENCY_ERROR
DOCUMENTATION_WORKSPACE_IO_ERROR
```

For errors report:

```text
Observed problem:
Root cause:
Missing/conflicting artifact:
Affected documentation section:
Corrective action:
```

---

# Pipeline Halt Rules

Documentation generation should NOT fail merely because an upstream optional asset failed.

Instead document that failure.

Return:

```text
❌ EXECUTION HALTED
```

only when:

- `accelerator.yaml` cannot be read;
- required run artifacts cannot be accessed;
- documentation cannot determine the actual run state;
- README cannot be written;
- factual consistency cannot be established.

---

# Non-Negotiable Rules

1. **Documentation reflects actual final state, not intended state.**
2. **Validation artifacts are authoritative for success/failure claims.**
3. **Do not mark configured assets as created unless manifests confirm creation.**
4. **Do not mark KPIs implemented unless Metric View validation passed.**
5. **Skipped KPIs must include their actual reason.**
6. **Do not invent asset IDs or workspace links.**
7. **Do not infer publication or validation status.**
8. **Do not re-derive schema or metric semantics during documentation generation.**
9. **Only document artifacts applicable to the configured data-source mode.**
10. **Do not modify upstream artifacts to make the README look complete.**
11. **README must contain no unresolved placeholders.**
12. **Workspace writes use `workspace_file_io.md`, never `dbutils.fs`.**
13. On unrecoverable documentation failure:

```text
❌ EXECUTION HALTED
```