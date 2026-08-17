# Metric View YAML Reference (Databricks)
# Source: https://docs.databricks.com/aws/en/uc-semantics/metric-views/yaml-reference

## Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| version | String | Yes | Must be "1.1" |
| source | String | Yes | Fully qualified table name (catalog.schema.table) |
| comment | String | No | Description |
| filter | String | No | SQL boolean expression applied to all queries |
| joins | Array | No | Star/snowflake schema joins |
| fields | Array | Conditional | Field (dimension) definitions. Required if no measures. |
| measures | Array | Conditional | Measure definitions. Required if no fields. |

## Fields (Dimensions)

Each field:
```yaml
fields:
- name: field_alias       # Required. The alias name
  expr: source_column     # Required. SQL expression (column reference or transformation)
  display_name: "Label"   # Optional
  comment: "Description"  # Optional
```

Column references in `expr`:
- `column_name` — column from the source table (NO prefix needed for source table)
- `join_name.column_name` — column from a joined table

## Measures

Each measure:
```yaml
measures:
- name: measure_alias             # Required
  expr: SUM(column_name)          # Required. Must use aggregate function
  display_name: "Label"           # Optional
  comment: "Description"          # Optional
  window:                         # Optional. Only for window measures
  - order: field_name             # Required in window. Must reference a defined field
    range: trailing 7 day         # Required in window
    semiadditive: last            # Required in window. Values: first | last
```

### Valid Aggregate Functions in expr:
- SUM(col), COUNT(col), COUNT(DISTINCT col), AVG(col), MIN(col), MAX(col)
- SUM(col) FILTER (WHERE condition)
- Compound: SUM(a) / NULLIF(SUM(b), 0)

### Window Spec (ALL THREE fields required):
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| order | String | Yes | A field name defined in `fields:` section |
| range | String | Yes | current, cumulative, trailing N day/month, leading N day/month, all |
| semiadditive | String | Yes | `first` or `last` |

## Joins

```yaml
joins:
- name: alias_name                        # Required. Use this as prefix in expr
  source: catalog.schema.table_name       # Required. Fully qualified table
  on: source.key = alias_name.key         # Required. Join condition
  cardinality: one_to_one                 # Optional: one_to_one (default), one_to_many
```

## Complete Example

```yaml
version: "1.1"
source: catalog.schema.fact_orders

fields:
- name: order_date
  expr: order_date
  display_name: Order Date
- name: region
  expr: region_code
  display_name: Region

measures:
- name: total_revenue
  expr: SUM(order_amount)
  display_name: Total Revenue
- name: order_count
  expr: COUNT(DISTINCT order_id)
  display_name: Order Count
- name: avg_order_value
  expr: SUM(order_amount) / NULLIF(COUNT(DISTINCT order_id), 0)
  display_name: Avg Order Value
- name: rolling_7d_revenue
  expr: SUM(order_amount)
  display_name: Rolling 7-Day Revenue
  window:
  - order: order_date
    range: trailing 7 day
    semiadditive: last
```

## Key Rules

1. `source:` must be a fully qualified table name (catalog.schema.table)
2. In `expr:`, reference columns directly (no `source.` prefix needed for the source table)
3. For joined tables, use `join_name.column` as prefix
4. Window measures: `order` must reference a field defined in `fields:` section
5. Every window spec needs ALL THREE: order, range, semiadditive
6. `fields` keyword is preferred over `dimensions` (both work, but `fields` is standard)
