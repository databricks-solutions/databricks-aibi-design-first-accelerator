# Synthetic Data Generation (dbldatagen)

Mandatory reference for Step 01 when `data_source.greenfield.synthetic_data` is `true`. Applies to **every domain**. Row counts: [`synthetic_data_sizing.md`](synthetic_data_sizing.md). **This doc:** column/FK/type rules so POC synthetic notebooks run without manual fixes.

DDL and dbldatagen are **separate notebooks** — both must use the **same column names and types** from `erd_parsed.yaml`. Correct DDL does not guarantee correct dbldatagen.

---

## Workflow

1. Parse ERD → `erd_parsed.yaml` with **every column** (name + SQL type + PK/FK).
2. Generate and run **DDL notebook** → tables exist in UC.
3. **`DESCRIBE TABLE`** each table — confirm columns match `erd_parsed.yaml`.
4. Generate **dbldatagen notebook** from template + `erd_parsed.yaml` + this doc.
5. **Pre-flight:** column list in generator = DESCRIBE column list (same names, count, types).
6. Execute one table per cell (or logical group); **halt on first error**.

---

## `erd_parsed.yaml` — columns (required for synthetic)

Each table entry must include full column metadata (from ERD + DDL):

```yaml
tables:
  - name: dim_member
    role: dimension
    synthetic_rows: 10000
    primary_key: member_sk
    columns:
      - name: member_sk
        type: BIGINT          # Spark SQL type from DDL
        generator: id         # id | fk | date | timestamp | string | decimal | int | literal
      - name: valid_from_date
        type: DATE
        generator: date
        format: "%Y-%m-%d"
      - name: valid_to_date
        type: DATE
        generator: date
        format: "%Y-%m-%d"
      - name: line_of_business
        type: STRING
        generator: string
    foreign_keys:
      - column: address_sk
        references: dim_address.address_sk
        parent_table: dim_address
```

**Every FK column must appear in `columns`** with the same `name` as in DDL.

**Every `DATE` column must include `format: "%Y-%m-%d"`** in `erd_parsed.yaml`. Every `TIMESTAMP` column must include `format: "%Y-%m-%d %H:%M:%S"`.

---

## Rule 2: Date and timestamp formats (mandatory)

dbldatagen error: `time data '2023-01-01' does not match format '%Y-%m-%d %H:%M:%S'`

**Root cause:** A **DATE** column (values like `'2023-01-01'`) was generated with a **TIMESTAMP** format string.

| DDL / Spark type | `format` in erd_parsed.yaml | dbldatagen |
|------------------|----------------------------|------------|
| `DATE` | `"%Y-%m-%d"` **required** | `format=DATE_FMT` only |
| `TIMESTAMP` | `"%Y-%m-%d %H:%M:%S"` **required** | `format=TIMESTAMP_FMT` |
| `STRING` | omit | string generator — not date parser |

### Forbidden (causes this error)

* ❌ One global `DATE_FORMAT = '%Y-%m-%d %H:%M:%S'` used for all columns
* ❌ Loop over columns without branching on `col["type"]`
* ❌ Applying TIMESTAMP `format=` to `type: DATE` (including `valid_from_date`, `service_date`, enrollment dates)
* ❌ Inline `withColumn` for dates — **must use `add_column()`** from template helper cell

### Required notebook pattern

1. Copy **helper cell verbatim** from `dbldatagen_notebook.py.template` (`validate_erd_date_formats`, `add_column`, `DATE_FMT`, `TIMESTAMP_FMT`).
2. Run **`validate_erd_date_formats(tables)`** before any `DataGenerator` — must print `✅ erd_parsed.yaml date formats validated`.
3. For **every** column: `gen = add_column(gen, col)` — never ad-hoc date `withColumn`.

```python
DATE_FMT = "%Y-%m-%d"
TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"

# DATE — format must be DATE_FMT
gen.withColumn(
    "valid_from_date",
    "date",
    begin=datetime.date(2023, 1, 1),
    end=datetime.date(2025, 12, 31),
    format=DATE_FMT,
)

# TIMESTAMP only
gen.withColumn(
    "created_at",
    "timestamp",
    begin="2023-01-01 00:00:00",
    end="2025-12-31 23:59:59",
    format=TIMESTAMP_FMT,
)
```

When unsure, **`DESCRIBE TABLE`** and set `type` + `format` in `erd_parsed.yaml` to match.

### POC fallback (if dbldatagen date API still fails)

Generate as STRING `'2023-01-01'`, then after `build()`:

```python
from pyspark.sql import functions as F
df = df.withColumn("valid_from_date", F.to_date(F.col("valid_from_date"), "yyyy-MM-dd"))
```

---

## Rule 2b — Define every column before FKs

dbldatagen error: `column 'X' must refer to defined column`

| Cause | Fix |
|-------|-----|
| FK wired to `address_sk` but column not in generator spec | Add `address_sk` to `columns` and `.withColumn(...)` **before** FK |
| Child FK name ≠ DDL column name | Use exact name from `DESCRIBE TABLE` |
| Parent table not built yet | Generate parent dimension **first**; keep parent DataFrame for FK |

**Order per table:**

1. Create `DataGenerator` with `rows=synthetic_rows`
2. `add_column(gen, col)` for **every** non-FK column
3. `add_column(gen, col, fk_parent_df=..., fk_parent_key=...)` for each FK column
4. `.build()` → write to Delta

---

## Rule 3: Generation order

Same as [`synthetic_data_sizing.md`](synthetic_data_sizing.md):

```
reference → dimension → bridge → scd2 → fact (header before detail when 1:N)
```

Store each built DataFrame in a dict keyed by table name for FK lookups:

```python
built = {}
# built["dim_address"] = address_df
# child FK uses built["dim_address"]
```

---

## Rule 4: POC-safe FK pattern (preferred for reliability)

For POC, prefer **explicit FK from parent DataFrame** after parent is built:

1. Build parent with PK column populated
2. On child: define FK column, then sample/join from parent keys (dbldatagen `withForeignKey` or equivalent **only after** column exists)

If `withForeignKey` fails after column is defined, POC fallback:

- Generate FK as `long` in range `[1, parent_row_count]` using `ForeignKeyGenerator` / parent key column
- Ensures joinable data without complex API edge cases

---

## Rule 5: Pre-flight checklist (before executing synthetic notebook)

For **each** table in generation order:

- [ ] Helper cell copied verbatim; **`validate_erd_date_formats(tables)`** passed
- [ ] All columns use **`add_column()`** — no shared datetime format variable
- [ ] All columns from `DESCRIBE TABLE` listed in generator
- [ ] PK column defined and unique
- [ ] Each FK column defined on child **before** FK attachment
- [ ] Parent table already in `built` dict
- [ ] DATE columns use `%Y-%m-%d`; TIMESTAMP use datetime format
- [ ] `synthetic_rows` matches `erd_parsed.yaml`
- [ ] Target write: `{catalog}.{schema}.{table}` matches DDL

---

## Common errors

| Error | Fix |
|-------|-----|
| `column 'X' must refer to defined column` | Define column X; match DDL name; parent built first |
| `time data 'YYYY-MM-DD' does not match format '%Y-%m-%d %H:%M:%S'` | DATE column used TIMESTAMP format — use `add_column()`; set `format: "%Y-%m-%d"` in erd_parsed |
| FK all null / join failures | Parent row count ≥ distinct FK values; rebuild parent first |
| Column count mismatch on write | Generator columns = DDL columns |

---

## After generation

1. Row count > 0 on fact tables
2. Sample FK join:

```sql
SELECT COUNT(*)
FROM fact f
JOIN dim d ON f.member_sk = d.member_sk
LIMIT 1;
```

3. On failure: fix notebook, re-run from failed table — do not proceed to metric views with empty facts.
