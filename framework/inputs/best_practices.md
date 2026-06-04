# Design Principles for Metric Views (Databricks Unity Catalog)

Metric Views are a semantic abstraction layer in Unity Catalog that centralizes and standardizes business metrics, making them reusable, consistent, and easy to query. This document outlines key design principles and best practices for designing Metric Views.

---

## 1. Single Source of Truth

- **Principle:** Define each metric once, in a single metric view, and reference it everywhere.
- **Practice:** Avoid duplicating metric logic across dashboards, notebooks, or views. Use metric views to centralize metric definitions so that every consumer — dashboards, notebooks, Genie spaces — computes metrics consistently.

---

## 2. Clear Separation of Dimensions and Measures

- **Principle:** Distinguish between *dimensions* (attributes for slicing/dicing) and *measures* (aggregated values).
- **Practice:** Use the `dimensions` section for grouping/filtering columns and the `measures` section for aggregations (SUM, COUNT, AVG, etc.). Measures must always use aggregate functions. Dimensions are unaggregated expressions.

### YAML Structure

```yaml
version: 1.1
source: catalog.schema.table_name
dimensions:
  - name: order_date
    expr: o_orderdate
    display_name: Order Date
    comment: Date when the order was placed
measures:
  - name: total_revenue
    expr: SUM(o_totalprice)
    display_name: Total Revenue
    comment: Total revenue from all orders
```

---

## 3. Composability — Build Complex Metrics from Simple Ones

- **Principle:** Build complex metrics by referencing simpler, foundational measures using the `MEASURE()` function.
- **Practice:** Define "atomic" measures first (SUM, COUNT, AVG), then compose derived KPIs by referencing them. This avoids duplicating logic and ensures consistency.

### Best Practices for Composability

- **Define atomic measures first**: Establish fundamental measures before defining derived ones.
- **Use `MEASURE()` for consistency**: Always use the `MEASURE()` function when referencing another measure. Don't manually repeat aggregation logic.
- **Prioritize readability**: Composed expressions should read like mathematical formulas.

### Example

```yaml
measures:
  - name: gross_profit
    expr: SUM(revenue) - SUM(cost)
    display_name: Gross Profit

  - name: total_revenue
    expr: SUM(revenue)
    display_name: Total Revenue

  - name: gross_margin
    expr: MEASURE(gross_profit) / MEASURE(total_revenue)
    display_name: Gross Margin
    format:
      type: percent
      decimal_places:
        type: exact
        places: 2
```

---

## 4. Consistent Naming and Semantic Metadata

- **Principle:** Use clear, human-readable names and rich metadata for all metrics.
- **Practice:** Utilize `display_name`, `comment`, `synonyms`, and `format` for each dimension and measure. This improves discoverability, AI-assisted querying, and downstream tool rendering.

### Example with Full Semantic Metadata

```yaml
dimensions:
  - name: customer_segment
    expr: |
      CASE
        WHEN o_totalprice > 100000 THEN 'Enterprise'
        WHEN o_totalprice > 10000 THEN 'Mid-market'
        ELSE 'SMB'
      END
    display_name: Customer Segment
    comment: Customer classification based on order value
    synonyms:
      - segment
      - customer tier

measures:
  - name: total_revenue
    expr: SUM(o_totalprice)
    display_name: Total Revenue
    comment: Total revenue from all orders
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
    synonyms:
      - revenue
      - total sales
      - sales amount
```

---

## 5. Star Schema Modeling with Joins

- **Principle:** Model fact and dimension tables using LEFT JOINs for a star schema.
- **Practice:** Use the `joins` section to link fact tables to dimension tables. This allows dimensions from related tables to be used for slicing without denormalizing.

### Example

```yaml
version: 1.1
source: catalog.schema.orders
joins:
  - name: customer
    source: catalog.schema.customers
    type: LEFT
    on: source.customer_id = customer.customer_id
  - name: region
    source: catalog.schema.regions
    type: LEFT
    on: customer.region_id = region.region_id
dimensions:
  - name: customer_name
    expr: customer.name
    display_name: Customer Name
  - name: region_name
    expr: region.name
    display_name: Region
measures:
  - name: total_revenue
    expr: SUM(source.order_total)
    display_name: Total Revenue
```

---

## 6. Windowed and Semiadditive Measures

- **Principle:** Support time-based and windowed aggregations for advanced analytics (trailing, cumulative, semiadditive).
- **Practice:** Use the `window` property in measures for trailing periods (e.g., trailing 7-day revenue, trailing 30-day distinct users).

### Example

```yaml
measures:
  - name: trailing_7d_revenue
    expr: SUM(revenue)
    display_name: Trailing 7-Day Revenue
    window:
      trailing: 7 days
      time_dimension: order_date

  - name: trailing_30d_unique_customers
    expr: COUNT(DISTINCT customer_id)
    display_name: Trailing 30-Day Unique Customers
    window:
      trailing: 30 days
      time_dimension: order_date
```

---

## 7. Filtered Measures

- **Principle:** Apply filters at both the metric view level (global WHERE) and individual measure level for precise metric calculation.
- **Practice:** Use the top-level `filter` for global constraints and `FILTER (WHERE ...)` syntax inside measure expressions for conditional aggregations.

### Example

```yaml
version: 1.1
source: catalog.schema.orders
filter: source.o_orderdate > '1990-01-01'
measures:
  - name: total_revenue
    expr: SUM(o_totalprice)
    display_name: Total Revenue

  - name: open_order_revenue
    expr: SUM(o_totalprice) FILTER (WHERE o_orderstatus = 'O')
    display_name: Revenue for Open Orders

  - name: high_priority_revenue
    expr: SUM(o_totalprice) FILTER (WHERE o_orderpriority = '1-URGENT')
    display_name: High Priority Order Revenue
```

---

## 8. Materialization for Performance

- **Principle:** Precompute and materialize metric views for faster query performance on frequently used metrics.
- **Practice:** Use the `materialization` section to define refresh schedules and specify which dimension/measure combinations to pre-aggregate.

### Example

```yaml
materialization:
  schedule: every 6 hours
  mode: relaxed
  materialized_views:
    - name: baseline
      type: unaggregated

    - name: revenue_breakdown
      type: aggregated
      dimensions:
        - category
        - region
      measures:
        - total_revenue

    - name: suppliers_by_category
      type: aggregated
      dimensions:
        - category
      measures:
        - number_of_suppliers
```

---

## 9. Correct Handling of Column Names with Spaces

- **Principle:** Always escape column names with spaces correctly in YAML.
- **Practice:**
  - For **dimensions**: Wrap with backticks and double quotes — `"`Trip Distance`"`
  - For **measures**: Use backticks inside aggregate functions — `SUM(`Trip Distance`)`

---

## 10. Querying Metric Views

Metric views are queried like standard views, but measures must always be wrapped with the `MEASURE()` function.

### Example Queries

```sql
-- Simple aggregation by dimension
SELECT
  customer_region,
  MEASURE(total_revenue) AS revenue
FROM catalog.schema.my_metric_view
GROUP BY customer_region
ORDER BY revenue DESC;

-- Multiple measures with filtering
SELECT
  order_month,
  MEASURE(total_revenue) AS revenue,
  MEASURE(order_count) AS orders
FROM catalog.schema.my_metric_view
WHERE order_month >= '2024-01-01'
GROUP BY order_month
ORDER BY order_month;

-- Window measures
SELECT
  DATE_TRUNC('month', date),
  MEASURE(trailing_7d_revenue) AS t7d_rev,
  MEASURE(trailing_30d_unique_customers) AS t30d_customers
FROM catalog.schema.my_window_metric_view
WHERE date >= DATE'2024-06-01'
GROUP BY ALL;
```

---

## How to Think About Designing a Metric View

| Step | Action |
|------|--------|
| 1 | **Start with the business question**: What metric(s) do users need? What dimensions are required for slicing? |
| 2 | **Identify the best source table**: Choose the fact table that contains the relevant measures and dimensions. |
| 3 | **Define dimensions and measures**: List all relevant attributes and aggregations with proper naming and metadata. |
| 4 | **Model joins if needed**: Add dimension tables for additional context (product, customer, date). |
| 5 | **Compose derived metrics**: Use `MEASURE()` to build KPIs from atomic measures. |
| 6 | **Add filters**: Apply global or measure-level filters as needed. |
| 7 | **Consider windowed measures**: If time-based analysis is needed, define windowed aggregations. |
| 8 | **Add semantic metadata**: Use `display_name`, `format`, `comment`, and `synonyms` for downstream tools. |
| 9 | **Materialize for performance**: If the metric view will be heavily queried, configure materialization. |
| 10 | **Validate and test**: Ensure all column references are valid and the metric view produces expected results. |

---

## Common Pitfalls to Avoid

| Pitfall | Why It Matters |
|---------|---------------|
| Inventing column names not in source tables | Causes runtime errors |
| Duplicating aggregation logic across measures | Leads to inconsistency; use `MEASURE()` instead |
| Omitting necessary joins | Missing dimensions from related tables |
| Forgetting to escape column names with spaces | YAML parsing or SQL errors |
| Using multiple `dimensions:` or `measures:` sections | YAML only uses the last one; earlier definitions are silently lost |
| Not adding semantic metadata | Reduces discoverability and AI-assisted querying |
| Referencing measures in custom calculations on dashboards | Dashboard custom calculations can only reference dimensions, not measures |

---

## Version History

| Version | Runtime Requirement | Key Features |
|---------|-------------------|--------------|
| 0.1 | DBR 16.4 — 17.1 | Initial release |
| 1.1 | DBR 17.2+ | Semantic metadata (`display_name`, `format`, `synonyms`, `comment`) |

---

## References

- [Unity Catalog Metric Views](https://learn.microsoft.com/en-us/azure/databricks/metric-views/)
- [YAML Syntax Reference](https://learn.microsoft.com/en-us/azure/databricks/metric-views/data-modeling/syntax/)
- [Composability in Metric Views](https://learn.microsoft.com/en-us/azure/databricks/metric-views/data-modeling/composability/)
- [Semantic Metadata](https://learn.microsoft.com/en-us/azure/databricks/metric-views/data-modeling/semantic-metadata/)
- [Window Measures](https://learn.microsoft.com/en-us/azure/databricks/metric-views/data-modeling/window-measures/)
- [Materialization](https://learn.microsoft.com/en-us/azure/databricks/metric-views/materialization/)
