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
      - name: valid_to_date
        type: DATE
        generator: date
      - name: line_of_business
        type: STRING
        generator: string
    foreign_keys:
      - column: address_sk
        references: dim_address.address_sk
        parent_table: dim_address
```

**Every FK column must appear in `columns`** with the same `name` as in DDL.

---

## Rule 1: Define every column before FKs

dbldatagen error: `column 'X' must refer to defined column`

| Cause | Fix |
|-------|-----|
| FK wired to `address_sk` but column not in generator spec | Add `address_sk` to `columns` and `.withColumn(...)` **before** FK |
| Child FK name ≠ DDL column name | Use exact name from `DESCRIBE TABLE` |
| Parent table not built yet | Generate parent dimension **first**; keep parent DataFrame for FK |

**Order per table:**

1. Create `DataGenerator` with `rows=synthetic_rows`
2. `.withColumn(...)` for **every** non-FK column
3. `.withColumn(...)` for each **FK column** (type only)
4. Attach FK to **parent DataFrame** already built
5. `.build()` → write to Delta

---

## Rule 2: Date and timestamp formats (must match SQL type)

dbldatagen error: `time data '2023-01-01' does not match format '%Y-%m-%d %H:%M:%S'`

| DDL / Spark type | Generator | Format / pattern |
|------------------|-----------|------------------|
| `DATE` | Date range / date generator | `format="%Y-%m-%d"` only — **no time component** |
| `TIMESTAMP` | Timestamp generator | `format="%Y-%m-%d %H:%M:%S"` or ISO with time |
| `STRING` date-like | String generator | Literal `"2023-01-01"` if column is STRING |

**Forbidden:** `%Y-%m-%d %H:%M:%S` format on a **DATE** column or date-only values like `'2023-01-01'`.

Record `type: DATE` vs `TIMESTAMP` in `erd_parsed.yaml` and match generator + format in the notebook.

```python
# DATE column — date-only format
gen.withColumn(
    "valid_from_date",
    "date",
    initial=datetime.date(2023, 1, 1),
    end=datetime.date(2025, 12, 31),
    format="%Y-%m-%d",
)

# TIMESTAMP column — include time in format and values
gen.withColumn(
    "created_at",
    "timestamp",
    format="%Y-%m-%d %H:%M:%S",
)
```

When unsure, **`DESCRIBE TABLE`** the column `data_type` and align generator to that type.

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
| `time data 'YYYY-MM-DD' does not match format '%Y-%m-%d %H:%M:%S'` | Use `%Y-%m-%d` for DATE columns |
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
