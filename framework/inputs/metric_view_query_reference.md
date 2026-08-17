# How to Query Metric Views
# Source: https://docs.databricks.com/aws/en/uc-semantics/metric-views/query

## CRITICAL RULES

1. ALL measures MUST be wrapped in `MEASURE()` function
2. Fields (dimensions) can be selected directly — no MEASURE() needed
3. Every query with MEASURE() MUST have `GROUP BY` (use `GROUP BY ALL` for convenience)
4. NEVER use `SELECT *` — it will fail on multi-source metric views
5. NEVER wrap metric view queries in subqueries like `SELECT * FROM (...) _t`

## Basic Query Pattern

```sql
SELECT
  field1,
  field2,
  MEASURE(measure_name) AS alias
FROM catalog.schema.metric_view_name
GROUP BY ALL
ORDER BY field1;
```

## Examples

### Aggregate by dimension
```sql
SELECT
  region,
  MEASURE(total_revenue) AS total_revenue,
  MEASURE(order_count) AS order_count
FROM catalog.schema.my_metric_view
GROUP BY ALL
ORDER BY total_revenue DESC;
```

### Filter then aggregate
```sql
SELECT
  category,
  MEASURE(total_revenue) AS revenue,
  MEASURE(avg_order_value) AS aov
FROM catalog.schema.my_metric_view
WHERE status = 'Active'
GROUP BY ALL;
```

### Time series (by month)
```sql
SELECT
  DATE_TRUNC('month', order_date) AS month,
  MEASURE(total_revenue) AS monthly_revenue,
  MEASURE(order_count) AS monthly_orders
FROM catalog.schema.my_metric_view
GROUP BY ALL
ORDER BY month;
```

### Multiple dimensions
```sql
SELECT
  region,
  product_category,
  MEASURE(total_revenue) AS revenue,
  MEASURE(order_count) AS orders,
  MEASURE(avg_order_value) AS aov
FROM catalog.schema.my_metric_view
GROUP BY ALL
ORDER BY revenue DESC;
```

### Window measures (rolling/cumulative)
```sql
SELECT
  order_date,
  MEASURE(rolling_7d_revenue) AS rolling_revenue
FROM catalog.schema.my_metric_view
GROUP BY ALL
ORDER BY order_date;
```

## Key Points

- `MEASURE(x)` automatically aggregates measure `x` at the grain of your GROUP BY fields
- You can apply additional `FILTER (WHERE ...)` to MEASURE: `MEASURE(revenue) FILTER (WHERE region = 'US')`
- Use `GROUP BY ALL` to avoid listing all fields manually
- Date functions work on fields: `DATE_TRUNC('month', date_field)`
- Measures CANNOT appear outside MEASURE() — `SELECT total_revenue` will FAIL
