# Member Claims KPI Design Specification

> This document is the authoritative KPI catalog for the Member Claims domain. Every KPI listed here must be implemented in the Metric View. If a KPI cannot be implemented due to missing source data, flag it as skipped with a reason. All physical table names, column names, joins, and dimensions must be discovered by profiling the source schema — this document defines only the business logic.

---

## KPI Catalog — Member Domain

| ID | KPI Name | Purpose | Formula | Type | Format | Pitfalls |
|----|----------|---------|---------|------|--------|----------|
| M-1 | New Member Enrollment | Count new members entering coverage in the period | `COUNT(DISTINCT member_key) FILTER (WHERE valid_from_date IN period)` | filtered, semi-additive | Integer | Requires SCD2 history table with `valid_from_date`. Skip if unavailable. |
| M-2 | Members by Line of Business | Active member distribution across products | `COUNT(DISTINCT member_key)` | semi-additive | Integer | Do NOT sum across time — each period is a snapshot. |
| M-3 | Members by Geography | Active member population by location | `COUNT(DISTINCT member_key)` | semi-additive | Integer | Same semi-additive warning as M-2. |

---

## KPI Catalog — Claim Domain

| ID | KPI Name | Purpose | Formula | Type | Format | Pitfalls |
|----|----------|---------|---------|------|--------|----------|
| C-1 | Total Claims | Count distinct claims | `COUNT(DISTINCT claim_id)` | additive | Integer | Use DISTINCT — one claim has multiple lines. |
| C-2 | Total Claim Lines | Count service lines | `COUNT(*)` | additive | Integer | Row count at detail level. Not same as C-1. |
| C-3 | Total Paid Amount | Sum paid across all lines | `SUM(paid_amount)` | additive | Currency USD | Always SUM, never LAST or AVG. |
| C-4 | Average Paid per Claim | Average paid at claim level | `MEASURE(C-3) / NULLIF(MEASURE(C-1), 0)` | ratio | Currency USD | Ratio — never sum. Recompute from components. |

---

## KPI Catalog — Member-Claim Domain

| ID | KPI Name | Purpose | Formula | Type | Format | Pitfalls |
|----|----------|---------|---------|------|--------|----------|
| MC-1 | PMPM | Cost per member per month | `MEASURE(total_paid) / NULLIF(MEASURE(member_months), 0)` | ratio | Currency USD | **NEVER sum PMPM.** `member_months` = `COUNT(DISTINCT CONCAT(member_key, '-', month))`. |
| MC-2 | Claims per 1,000 Members | Claim frequency normalized by population | `(MEASURE(C-1) / NULLIF(MEASURE(member_months), 0)) * 1000` | ratio | Decimal 1dp | Denominator is **member_months**, not unique_members. The ×1000 scaling is essential. |
| MC-3 | Utilization Rate | Share of active members who used services | `MEASURE(members_with_claims) / NULLIF(MEASURE(active_enrolled_members), 0)` | ratio | Percentage | Denominator must come from **enrollment** table, not claims. Skip if no enrollment table. |
| MC-4 | High-Cost Member Count | Members whose spend exceeds threshold | `COUNT(DISTINCT member_key) FILTER (WHERE member_paid > $10,000)` | filtered | Integer | Requires pre-aggregation to member level. Document if not expressible as single measure. |

---

## Window Measures

These KPIs require the Metric View **window measure** capability (`window:` property with `order:` and `trailing:`).

| ID | KPI Name | Purpose | Formula | Window | Format | Pitfalls |
|----|----------|---------|---------|--------|--------|----------|
| W-1 | Rolling 3-Month PMPM | Smooth cost volatility over trailing 3 months | `trailing_3m_paid / NULLIF(trailing_3m_member_months, 0)` | `trailing: 3 months` on `service_month` | Currency USD | Do NOT average the PMPM ratio. Roll the **numerator and denominator separately**, then divide. |
| W-2 | MoM Active Member Growth | Month-over-month change in active members | `(current_month_members - prior_month_members) / prior_month_members` | `trailing: 1 month` on `service_month` | Percentage | If window offset not supported, implement as dashboard SQL dataset using `LAG()` and document the limitation. |

---

## Additional Derived Measures

Create these if source data supports them. All are composed from core measures using `MEASURE()`.

| KPI Name | Formula | Type | Format |
|----------|---------|------|--------|
| Denial Rate | `denied_lines / NULLIF(total_lines, 0)` | ratio | Percentage |
| Clean Claim Rate | `clean_lines / NULLIF(total_lines, 0)` | ratio | Percentage |
| Payment-to-Billed Ratio | `total_paid / NULLIF(total_billed, 0)` | ratio | Percentage |
| Payment-to-Allowed Ratio | `total_paid / NULLIF(total_allowed, 0)` | ratio | Percentage |
| Average Paid per Member | `total_paid / NULLIF(unique_members, 0)` | ratio | Currency USD |
| Claims per Member | `total_claims / NULLIF(unique_members, 0)` | ratio | Decimal |
| Lines per Claim | `total_lines / NULLIF(total_claims, 0)` | ratio | Decimal |
| Inpatient Paid Amount | `SUM(paid) FILTER (WHERE claim_type = Institutional)` | filtered | Currency USD |
| Outpatient Paid Amount | `SUM(paid) FILTER (WHERE claim_type = Professional)` | filtered | Currency USD |
| Participating Provider Rate | `par_paid / NULLIF(total_paid, 0)` | ratio | Percentage |

---

## Aggregation Rules

These are **non-negotiable**. Violating them produces incorrect business results.

| Rule | Why |
|------|-----|
| Never SUM members across time | Same member counted in multiple months inflates totals |
| Never SUM PMPM or any ratio | Ratios must be recomputed from numerator/denominator |
| Never use LAST for paid amounts | Paid is transactional — always SUM |
| Always use NULLIF(denominator, 0) | Guards against division by zero |

---

## Dashboard Mapping

| Dashboard | Page | KPIs |
|-----------|------|------|
| **KPIs Overview** | Financial Overview | C-1, C-3, MC-1, W-1, W-2, top-N cost drivers |
| | Claims Analysis | C-4, Denial Rate, Clean Claim Rate, monthly trends |
| | Member Demographics | M-2, M-3, age/sex breakdowns |
| **Utilization & Provider** | Utilization Patterns | C-1, C-2, Inpatient/Outpatient Paid |
| | Provider Insights | Specialty rankings, Par Provider Rate |
| | Operational Metrics | Denial trends, Payment-to-Billed, Payment-to-Allowed |

---

## Glossary

| Term | Definition |
|------|-----------|
| **PMPM** | Per Member Per Month — total cost ÷ member-month exposure |
| **Member-Month** | One member active for one month (12 months = 12 member-months) |
| **Semi-additive** | Cannot be summed across time |
| **Ratio** | Must be recomputed from components, never summed |
| **Window measure** | Computed over a trailing time window |
| **LOB** | Line of Business (Commercial, Medicare, Medicaid, etc.) |
| **SCD2** | Slowly Changing Dimension Type 2 — tracks history with valid_from/valid_to |
