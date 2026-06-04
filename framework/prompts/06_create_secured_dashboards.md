# Create Secured Dashboards (Optional — v2)

## Role

Create row-level security (RLS) dashboards when `pipeline.steps.create_secured_dashboards` is `true`.

---

## Step 1: Load Configuration

Read `accelerator.yaml`. Requires base dashboards from `03_create_dashboards.md`.

---

## Step 2: Implement RLS

Follow Unity Catalog and Lakeview RLS patterns for the domain's entitlement column(s). Document filters applied per dashboard page.

---

## Status

Stub for v2. Default `create_secured_dashboards: false` in `accelerator.yaml`.
