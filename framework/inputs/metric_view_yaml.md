# Metric View YAML — Platform Syntax Contract

Mandatory reference for Step 02. Applies to **every domain** (greenfield, brownfield, multi-catalog). Domain-specific table and column names come from **`schema_profile.yaml`** and DESCRIBE — not from this file.

Official reference: [Metric view YAML syntax](https://learn.microsoft.com/en-us/azure/databricks/business-semantics/metric-views/yaml-reference)

---

## Workflow (generic)

1. Profile source tables → write `{workspace.output_folder}/schema_profile.yaml` (columns + join map).
2. Draft metric view YAML from KPI spec + join map.
3. **Lint** against this document (structural rules below).
4. Save draft to `{workspace.output_folder}/metric_views/{name}.yaml`.
5. `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$`.
6. Smoke-test each measure with `SELECT MEASURE(...) ... GROUP BY ALL`.

Do **not** run CREATE until steps 3–4 pass.

---

## `schema_profile.yaml` (runtime artifact)

Written during profiling; shape is domain-agnostic:

```yaml
locations:
  - catalog: catalog_a
    schema: schema_a
    label: optional_label

tables:
  - fqn: catalog.schema.fact_table
    role: fact | dimension | bridge | reference | scd2
    columns: [col_a, col_b]   # from DESCRIBE only

joins:
  - name: dim_alias          # used in metric view YAML joins[].name
    source: catalog.schema.dim_table
    on: source.fk_col = dim_alias.pk_col   # verified via DESCRIBE
```

Every `{alias}.{column}` in metric view YAML must resolve to a column listed under the matching table in this profile.

---

## Joins

Metric views use **implicit LEFT OUTER JOIN**. Valid join fields: `name`, `source`, `'on'` or `using`, optional nested `joins`, optional `rely`, optional `cardinality`.

**Forbidden on joins:** `type`, `join_type`, `LEFT`, `INNER`, or any SQL join keyword.

```yaml
version: 1.1
source: catalog.schema.fact_table

joins:
  - name: dim_alias
    source: catalog.schema.dim_table
    'on': source.fk_col = dim_alias.pk_col
```

### Column qualification in `'on'`

| Prefix | Refers to |
|--------|-----------|
| `source` | Base table (`source:` at top of YAML) |
| `{joins[].name}` | That joined table |

If unqualified in `'on'`, the reference defaults to the **joined** table — prefer explicit `source.` and `{alias}.` prefixes.

**Quote `'on'`** — YAML 1.1 parsers may treat unquoted `on` as boolean.

When both sides share a column name, use `using:`:

```yaml
  - name: dim_alias
    source: catalog.schema.dim_table
    using:
      - shared_key_col
```

---

## Dimensions and measures

- Reference joined columns as `{join_name}.{column}` — the join **`name`**, not the physical table name unless they match.
- Unqualified columns in `expr` resolve against **`source`** (fact) by default.
- Every column in `expr` must exist on the table implied by its prefix (from DESCRIBE / `schema_profile.yaml`).

---

## Format types (`format.type`)

Closed enum — only these values are valid:

| Allowed | Use for |
|---------|---------|
| `byte` | Byte sizes |
| `currency` | Monetary amounts |
| `date` | Dates |
| `date_time` | Timestamps |
| `number` | Counts, decimals, integers |
| `percentage` | Rates, ratios displayed as percent |

**Forbidden:** `percent`, `pct`, `decimal`, or any value not in the table above.

Map KPI spec **Format** column when generating YAML:

| KPI spec Format (examples) | YAML `format.type` |
|----------------------------|-------------------|
| Integer, Count | `number` |
| Currency, Currency USD | `currency` |
| Percentage, Percent, Rate | `percentage` |
| Decimal | `number` (+ `decimal_places` if needed) |

```yaml
  - name: example_rate
    expr: MEASURE(numerator) / NULLIF(MEASURE(denominator), 0)
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 1
```

---

## Forbidden patterns

| Pattern | Typical error | Fix |
|---------|---------------|-----|
| `type: LEFT` under `joins` | `Unrecognized field "type"` | Remove; use `'on'` or `using` only |
| `format.type: percent` | `Could not resolve type id 'percent'` | Use `percentage` |
| `{wrong_alias}.{col}` in expr or `'on'` | `UNRESOLVED_COLUMN` | Use join `name` alias; verify DESCRIBE |
| Invented column names | `UNRESOLVED_COLUMN` | Only columns from profiling |
| Unquoted `on:` key | Broken join / parse issues | Use `'on':` |
| CREATE before lint / save draft | Wasted retries | Lint → save YAML → CREATE |

---

## Post-CREATE validation (every domain)

For each KPI measure (or documented skip):

```sql
SELECT MEASURE(<measure_name>)
FROM {catalog.target.catalog}.{catalog.target.schema}.{metric_view_name}
GROUP BY ALL
LIMIT 5;
```

Do not proceed to dashboards until the primary metric view passes these smoke tests.
