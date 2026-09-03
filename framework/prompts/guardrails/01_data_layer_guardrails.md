# Data Layer Guardrails — Step 2 (Create Data Layer)

> **Also read:** `guardrails/00_global_rules.md` (always applies)

---

## Gates

### GATE 2.1b: Data Type Validation (MANDATORY post-parse)
After parsing ERD, verify every column has a concrete data type. If ANY column has NULL/UNKNOWN type, re-invoke vision model with a targeted crop. HALT if still unresolved after 2 retries.

### GATE 4.1: Table Count Verification
`SHOW TABLES IN {catalog}.{schema} LIKE '%{VERSION_SUFFIX}'` must return expected count. HALT if fewer.

### GATE 4.2: Schema Reconciliation (MANDATORY after DDL execution)
After GATE 4.1, verify each table's **actual schema** matches the **ERD-parsed schema**. `CREATE TABLE IF NOT EXISTS` is a no-op on tables that already exist with a different schema from a prior interrupted run.

### GATE 5.1: Domain Value Validation
Every categorical column MUST have domain-specific values (not `val_1`...`val_5`). Run the Domain Value Inference Protocol for any column with generic values.

### GATE 5.2: YAML Type Safety Validation (MANDATORY before writing spec)
All values for VARCHAR/STRING columns MUST be quoted strings in `synthetic_data_spec.yaml`. YAML parses `99213` as integer, creating mixed-type lists.

### GATE 6.1: Row Count Verification
ALL tables must have rows > 0 after synthetic data generation. HALT with `SYNTHETIC_GENERATION_ERROR` if any table is empty.

### GATE 7.1: Data Layer Validation
`data_layer_validation.yaml` must exist with `overall_status: PASS`. HALT if FAIL.

---

## Prohibited Actions

1. DO NOT skip ERD parsing by using a cached/assumed schema
2. DO NOT modify column names, types, or constraints from the ERD
3. DO NOT create tables outside the configured catalog.schema
4. DO NOT use `DROP TABLE` on source tables
5. DO NOT proceed past a GATE without verifying the condition
6. DO NOT use generic column names (`col1`, `col2`, `value`)
7. DO NOT skip validation of generated synthetic data
8. DO NOT use `CTAS` (CREATE TABLE AS SELECT) for DDL — use explicit `CREATE TABLE` with column definitions
9. DO NOT invent new tables not in the ERD
10. DO NOT add columns beyond what the ERD specifies
11. DO NOT skip the vision model step if an ERD image is provided
12. DO NOT assume column types from names — always verify with the parsed ERD
13. DO NOT skip schema reconciliation (GATE 4.2)
14. DO NOT use unquoted numeric values for STRING/VARCHAR columns in synthetic_data_spec.yaml
15. DO NOT generate data without calling `validate_domain_cols()` first (DETERMINISM GATE)
16. DO NOT generate data without calling `validate_fk_replacements()` for FK columns (DETERMINISM GATE)
17. DO NOT use generic placeholder values (`val_1` through `val_5`) for categorical columns
18. DO NOT skip the Domain Value Inference Protocol for categorical columns
19. DO NOT write the data generation notebook without the safety utilities from `dbldatagen_notebook.py.template`
20. DO NOT execute data generation without `verify_before_write()` pre-write validation
21. DO NOT skip the `enforce_varchar_limits()` truncation safety net

---

## Prohibited Value Patterns (GATE 5.1 rejects these)

```text
val_1, val_2, val_3, val_4, val_5           — generic placeholders
type_1, type_2, type_3                       — generic type names
category_a, category_b                       — generic categories
status_1, active, inactive (for non-status)  — wrong domain
```

## Prohibited Column Name Patterns

```text
table_name_column_name   — concatenated table+column
original_source_column   — source system prefix
any column not in ERD    — invented columns
```

---

## Anti-Patterns

### AP-DL-1: Vision Model Truncation
Vision model returns partial table (e.g., 5 of 12 columns). GATE 2.1b catches this by checking for NULL types. Fix: re-invoke with targeted crop.

### AP-DL-2: Mixed-Type YAML Lists
`synthetic_data_spec.yaml` has `[99213, "99214", 99215]` — YAML parses unquoted numbers as integers. Fix: quote ALL string column values.

### AP-DL-3: dbldatagen Boolean/Timestamp Bugs
`dbldatagen` raises DATATYPE_MISMATCH for BooleanType with values/weights, and ValueError for TimestampType with date-only begin/end. Fix: `_safe_withColumn` patch in template handles both.
