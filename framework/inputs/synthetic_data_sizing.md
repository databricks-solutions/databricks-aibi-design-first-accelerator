# Synthetic Data Sizing (Greenfield)

Mandatory reference for Step 01 when `data_source.greenfield.synthetic_data` is `true`. Applies to **every domain** — table names and row counts come from the **ERD**, not from per-entity keys in `accelerator.yaml`.

---

## Config vs runtime

| Source | What it holds |
|--------|----------------|
| `accelerator.yaml` → `greenfield.volume.scale` | Optional preset: `demo` \| `standard` \| `large` (default `standard`) |
| `accelerator.yaml` → `greenfield.volume.overrides` | Optional `{table_name: row_count}` — rare tuning only |
| **`erd_parsed.yaml`** (generated) | Every ERD table + **`synthetic_rows`** computed by Genie using this doc |

Users do **not** list table names or row counts in `accelerator.yaml` unless using `overrides`.

---

## Scale presets

| `scale` | Base dimension rows | Fact multiplier | Reference / lookup rows |
|---------|---------------------|-----------------|-------------------------|
| `demo` | 1,000 | ×10 vs largest parent dim | 100 |
| `standard` | 10,000 | ×10 | 500 |
| `large` | 100,000 | ×10 | 1,000 |

Default when `volume` is omitted or `scale` is not set: **`standard`**.

---

## Assign `synthetic_rows` per table (in `erd_parsed.yaml`)

After parsing the ERD, classify each table and assign rows:

| ERD role | Rule |
|----------|------|
| `dimension` | `base_dimension_rows` for the active scale |
| `reference` / lookup | `reference_rows` for the scale |
| `fact` | `max(parent dimension synthetic_rows) × fact_multiplier`, at least 1,000 at `standard` |
| `bridge` | `min(parent dimension rows)` or same as smallest parent fact grain |
| `scd2` / history | `dimension_rows × 2` to `×5` (enough history for semi-additive KPIs) |

### FK-aware adjustments

1. Generate **dimensions and references before facts** (dbldatagen order).
2. Fact `synthetic_rows` must support FK cardinality — do not generate fewer fact rows than distinct parent keys unless intentional sparsity.
3. Detail facts (e.g. line-level) may use **×2 to ×5** the header fact row count when ERD shows 1:N header→detail.

### Overrides

If `accelerator.yaml` contains:

```yaml
greenfield:
  volume:
    scale: standard
    overrides:
      fact_orders: 500000
```

Use `500000` for `fact_orders` and preset rules for all other tables.

---

## `erd_parsed.yaml` shape (runtime)

Written during Step 01 ERD parse. Example (table names vary by ERD):

```yaml
volume_scale: standard
tables:
  - name: dim_customer
    role: dimension
    columns: [...]
    primary_key: customer_id
    synthetic_rows: 10000
  - name: fact_orders
    role: fact
    columns: [...]
    foreign_keys:
      - column: customer_id
        references: dim_customer.customer_id
    synthetic_rows: 100000
joins: [...]
```

Every table from the ERD must appear with `role` and `synthetic_rows` before generating the dbldatagen notebook.

---

## dbldatagen notebook

The synthetic data notebook reads **`{workspace.output_folder}/erd_parsed.yaml`** — not `accelerator.yaml` volume keys.

1. Load `tables` ordered: reference → dimension → bridge → scd2 → fact (headers before details when ERD implies 1:N).
2. For each table, use `synthetic_rows` from `erd_parsed.yaml`.
3. Respect FK relationships from `foreign_keys` / join map when generating keys.

---

## When synthetic data is off

If `greenfield.synthetic_data: false`, run DDL only — skip row assignment and dbldatagen notebook.
