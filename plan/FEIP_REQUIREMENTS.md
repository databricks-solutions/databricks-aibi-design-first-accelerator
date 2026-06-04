# FEIP-7399 Requirements

**Jira:** [FEIP-7399](https://databricks.atlassian.net/browse/FEIP-7399)

## Problem Statement

Building a secure, effective, and governed Databricks AI/BI experience requires a consistent semantic layer (Unity Catalog Metric Views) and aligned consumption assets (Lakeview dashboards, Genie spaces, SQL). However, creating these assets is manual, time-consuming, and inconsistent across engagements: each RSA/SA/customer reinvents KPI-to-YAML translation, schema profiling, dashboard layout, and Genie configuration. Errors in metric semantics (summing ratios, mis-handling semi-additive measures, duplicating logic outside Metric Views) are common and hard to catch without structured validation.

Workshops and POCs show that design-first artifacts—a KPI catalog, platform best practices, and an ERD—are enough to produce strong demos, but there is no reusable field framework that any team can apply to any domain from those inputs alone.

## Opportunity Statement

A Design-First AI/BI Accelerator Framework can standardize how field and customers go from business-defined metrics to a full, governed stack. With three inputs as the contract—(1) KPI specification, (2) semantic-layer best practices, (3) data model (ERD **image** **or** live Unity Catalog schema)—and Genie Code (or Vibe) orchestrating generation, teams can produce sample data, Unity Catalog tables, Metric Views, dashboards, and Genie spaces repeatably for healthcare, retail, finance, or other domains without rewriting the pipeline.

The framework cuts time-to-implement, enforces one `MEASURE()` source of truth across SQL, dashboards, and Genie, and turns successful workshops into a portable field accelerator, not a one-off artifact.

## Final deliverables (v1)

| Deliverable | Description |
|-------------|-------------|
| **Accelerator package** | Versioned repo with `accelerator.yaml`, `inputs/`, `framework/prompts/`, `framework/templates/`; runtime assets under `workspace.output_folder` |
| **Input templates** | Domain-agnostic KPI specification template, metric-view best practices doc, ERD image (`data_source.erd.image`); **or** live UC schema pointer in YAML |
| **Orchestration** | YAML-driven Genie Code master prompt: greenfield (DDL + dbldatagen) **or** brownfield (profile existing UC tables) → Metric Views → dashboards → Genie space |
| **Reference implementation** | Synthetic `member_claims` example under `examples/` for end-to-end validation — not part of core framework source |
| **Portability proof** | Same framework applied to a second `data_source.type` (e.g. `live_schema`) without prompt changes — optional in validation phase |
| **Field runbook** | README: prerequisites, config, greenfield vs brownfield, run order, validation checklist, architecture diagram |

## Definition of done (v1)

An SA can stand up a **new domain POC** using only `accelerator.yaml` + domain inputs, and deliver:

- Governed UC tables (synthetic or existing Gold)
- Metric View YAML implementing the KPI catalog (with documented skips)
- At least two Lakeview dashboards
- A Genie space configured via the template notebook
- Sample `MEASURE()` SQL and validation results
