# KPI Design Specification — Template

> Replace `{domain}` with your domain slug. Every KPI listed must be implemented in the Metric View or explicitly skipped with a reason.

---

## KPI Catalog — {Domain Area 1}

| ID | KPI Name | Purpose | Formula | Type | Format | Pitfalls |
|----|----------|---------|---------|------|--------|----------|
| X-1 | | | | additive / semi-additive / ratio / filtered | | |

## KPI Catalog — {Domain Area 2}

| ID | KPI Name | Purpose | Formula | Type | Format | Pitfalls |
|----|----------|---------|---------|------|--------|----------|

---

## Window Measures

| ID | KPI Name | Purpose | Formula | Window | Format | Pitfalls |
|----|----------|---------|---------|--------|--------|----------|

---

## Additional Derived Measures

| KPI Name | Formula | Type | Format |
|----------|---------|------|--------|

---

## Aggregation Rules

| Rule | Why |
|------|-----|
| Never SUM members across time | Same entity in multiple periods inflates totals |
| Never SUM ratios or PMPM-style metrics | Recompute numerator/denominator |
| Always use NULLIF(denominator, 0) | Division by zero |

---

## Dashboard Mapping

Map KPIs to dashboard `id` values from `accelerator.yaml` → `assets.dashboards`.

| Dashboard (`assets.dashboards[].id`) | Page | KPIs |
|--------------------------------------|------|------|
| kpis | Page 1 | |
| utilization | Page 1 | |

---

## Glossary

| Term | Definition |
|------|------------|
