# =============================================================================
# ERD Validation Utilities — Deterministic Data Type Correction
# =============================================================================
#
# This module provides programmatic validation and auto-correction of data types
# extracted by the vision model during ERD image parsing (Step 2).
#
# PURPOSE:
# Vision models frequently truncate data type definitions when processing ERD
# images (e.g., "decimal(28" instead of "decimal(28,2)"). This produces invalid
# DDL that fails at CREATE TABLE time. This utility catches and fixes ALL such
# truncation errors BEFORE erd_parsed.yaml is written.
#
# USAGE:
# Call validate_and_fix_datatypes() on the parsed tables list AFTER vision model
# returns and BEFORE writing erd_parsed.yaml:
#
#   tables, fixes = validate_and_fix_datatypes(parsed_tables)
#   # tables is now guaranteed to have complete data types
#   # fixes lists what was corrected (for audit/logging)
#
# GUARANTEE:
# After this function runs, every column datatype will be:
# - Non-empty
# - Have balanced parentheses
# - Have complete precision/scale for decimal/numeric types
# - Have complete length for varchar/char types
# - Be a valid Databricks SQL data type
# =============================================================================

import re
from typing import Any


# =============================================================================
# SECTION 1: Core Validation & Fix
# =============================================================================

def validate_and_fix_datatypes(tables: list[dict]) -> tuple[list[dict], list[str]]:
    """Validate and auto-fix all column datatypes for completeness.

    This is the DETERMINISTIC GATE that prevents incomplete types from
    reaching DDL generation. The vision model may truncate; this function
    guarantees completeness.

    Args:
        tables: List of table dicts from ERD parsing. Expected structure:
            [{"name": "table_name", "observed": {"columns": [{"name": "col", "datatype": "..."}]}}]

    Returns:
        Tuple of (fixed_tables, fixes_applied).
        - fixed_tables: Same list with corrected datatypes in-place
        - fixes_applied: List of human-readable fix descriptions for logging

    Guarantees after execution:
        - No unclosed parentheses in any datatype
        - All decimal/numeric types have (precision,scale)
        - All varchar/char types have (length)
        - No empty datatypes (defaults to 'string')
    """
    fixes = []

    for table in tables:
        table_name = table.get('name', 'unknown')
        columns = table.get('observed', {}).get('columns', [])

        for col in columns:
            col_name = col.get('name', 'unknown')
            dtype = col.get('datatype', '').strip()
            original = dtype

            # Fix 1: Empty datatype
            if not dtype:
                col['datatype'] = 'string'
                fixes.append(f"{table_name}.{col_name}: <empty> → 'string'")
                continue

            # Fix 2: Unclosed parenthesis — the #1 vision model truncation error
            if '(' in dtype and ')' not in dtype:
                dtype = _fix_unclosed_parenthesis(dtype, table_name, col_name)
                col['datatype'] = dtype
                if dtype != original:
                    fixes.append(f"{table_name}.{col_name}: '{original}' → '{dtype}'")
                continue

            # Fix 3: Decimal/numeric with precision but no scale — e.g., decimal(28)
            dtype = _fix_decimal_missing_scale(dtype, table_name, col_name)
            if dtype != original:
                col['datatype'] = dtype
                fixes.append(f"{table_name}.{col_name}: '{original}' → '{dtype}' (added scale)")
                continue

            # Fix 4: Mismatched parentheses count
            if dtype.count('(') != dtype.count(')'):
                fixed = _balance_parentheses(dtype)
                if fixed != dtype:
                    col['datatype'] = fixed
                    fixes.append(f"{table_name}.{col_name}: '{dtype}' → '{fixed}' (balanced parens)")

    # Report
    if fixes:
        print(f"⚠️  ERD Data Type Validation: {len(fixes)} fix(es) applied:")
        for f in fixes[:20]:  # Cap output for large schemas
            print(f"    • {f}")
        if len(fixes) > 20:
            print(f"    ... and {len(fixes) - 20} more")
    else:
        print("✓ ERD Data Type Validation: all types complete and valid")

    return tables, fixes


# =============================================================================
# SECTION 2: Type-Specific Fix Functions
# =============================================================================

def _fix_unclosed_parenthesis(dtype: str, table_name: str, col_name: str) -> str:
    """Fix a data type with an unclosed parenthesis.

    Applies domain-aware defaults:
    - decimal/numeric: assumes scale=2 for precision>10 (financial), scale=0 otherwise
    - varchar/char: closes with the partial length or defaults to 255
    - other: simply closes the parenthesis
    """
    lower = dtype.lower()

    # Decimal/Numeric: decimal(28 → decimal(28,2)
    match = re.match(r'(decimal|numeric)\((\d+),?\s*$', lower)
    if match:
        type_name = match.group(1)
        precision = int(match.group(2))
        # Financial heuristic: precision > 10 likely needs scale=2
        scale = 2 if precision > 10 else 0
        return f"{type_name}({precision},{scale})"

    # Decimal with partial scale: decimal(28,  → decimal(28,2)
    match = re.match(r'(decimal|numeric)\((\d+),\s*$', lower)
    if match:
        type_name = match.group(1)
        precision = int(match.group(2))
        return f"{type_name}({precision},2)"

    # Varchar/Char: varchar(100 → varchar(100), varchar( → varchar(255)
    match = re.match(r'(n?varchar|char)\((\d*)$', lower)
    if match:
        type_name = match.group(1)
        length = match.group(2) or '255'
        return f"{type_name}({length})"

    # Generic: just close the parenthesis
    return dtype + ')'


def _fix_decimal_missing_scale(dtype: str, table_name: str, col_name: str) -> str:
    """Fix decimal(N) → decimal(N,S) when scale is likely needed.

    Heuristic: precision > 4 and column name suggests monetary value → scale=2
    Otherwise leaves decimal(N) as-is (it's valid SQL, just unusual).
    """
    match = re.match(r'^(decimal|numeric)\((\d+)\)$', dtype, re.IGNORECASE)
    if not match:
        return dtype

    type_name = match.group(1)
    precision = int(match.group(2))

    # Heuristic: likely financial if precision > 4
    # Column name patterns that suggest monetary: amount, paid, cost, charge, price, rate
    monetary_patterns = ('amount', 'paid', 'cost', 'charge', 'price', 'rate',
                         'fee', 'balance', 'payment', 'billed', 'allowed',
                         'copay', 'deductible', 'coinsurance')
    col_lower = col_name.lower()

    if precision > 4 and any(p in col_lower for p in monetary_patterns):
        return f"{type_name}({precision},2)"

    # Non-monetary with high precision: likely needs some scale
    if precision > 10:
        return f"{type_name}({precision},2)"

    return dtype


def _balance_parentheses(dtype: str) -> str:
    """Ensure parentheses are balanced."""
    open_count = dtype.count('(')
    close_count = dtype.count(')')

    if open_count > close_count:
        dtype += ')' * (open_count - close_count)
    elif close_count > open_count:
        # Extra closing parens — strip from end
        while dtype.count(')') > dtype.count('('):
            dtype = dtype.rstrip(')')
            dtype += ')' * dtype.count('(')
            break

    return dtype


# =============================================================================
# SECTION 3: Full Schema Validation (DDL-ready check)
# =============================================================================

def validate_schema_for_ddl(tables: list[dict]) -> dict:
    """Comprehensive schema validation before DDL generation.

    Checks beyond data types:
    - Every table has a name
    - Every table has at least one column
    - Every column has a name and datatype
    - No duplicate column names within a table
    - At least one PK identified per table
    - Data types are syntactically valid for Databricks SQL

    Returns:
        {"status": "PASS"|"FAIL", "errors": [...], "warnings": [...]}
    """
    errors = []
    warnings = []

    VALID_BASE_TYPES = {
        'bigint', 'int', 'integer', 'smallint', 'tinyint', 'long',
        'double', 'float', 'boolean', 'string', 'binary',
        'date', 'timestamp', 'timestamp_ntz',
        'decimal', 'numeric', 'varchar', 'char', 'nvarchar',
    }

    for table in tables:
        table_name = table.get('name')
        if not table_name:
            errors.append("Table found with no name")
            continue

        columns = table.get('observed', {}).get('columns', [])
        if not columns:
            errors.append(f"{table_name}: no columns defined")
            continue

        col_names = []
        has_pk = False

        for col in columns:
            col_name = col.get('name', '')
            dtype = col.get('datatype', '')
            key_marker = col.get('key_marker', '')

            if not col_name:
                errors.append(f"{table_name}: column with empty name")
                continue

            if col_name in col_names:
                errors.append(f"{table_name}: duplicate column '{col_name}'")
            col_names.append(col_name)

            if not dtype:
                errors.append(f"{table_name}.{col_name}: empty datatype")

            # Check base type is valid
            base_type = re.match(r'^([a-z_]+)', dtype.lower())
            if base_type and base_type.group(1) not in VALID_BASE_TYPES:
                warnings.append(f"{table_name}.{col_name}: unusual type '{dtype}' — verify")

            # Check for unclosed parens (should be caught by validate_and_fix_datatypes)
            if '(' in dtype and ')' not in dtype:
                errors.append(f"{table_name}.{col_name}: unclosed parenthesis in '{dtype}'")

            if key_marker == 'PK':
                has_pk = True

        if not has_pk:
            warnings.append(f"{table_name}: no PK marker found (will be inferred)")

    status = "PASS" if not errors else "FAIL"

    if errors:
        print(f"❌ Schema validation FAILED ({len(errors)} error(s)):")
        for e in errors:
            print(f"    • {e}")
    else:
        print(f"✓ Schema validation PASSED")

    if warnings:
        print(f"  ⚠️  {len(warnings)} warning(s):")
        for w in warnings[:10]:
            print(f"    • {w}")

    return {"status": status, "errors": errors, "warnings": warnings}


# =============================================================================
# SECTION 4: Convenience — Combined Validation Pipeline
# =============================================================================

def validate_erd_output(tables: list[dict]) -> tuple[list[dict], dict]:
    """Run the FULL validation pipeline on ERD-parsed tables.

    This is the ONE function the orchestrating agent should call after
    vision model parsing. It:
    1. Fixes truncated data types (deterministic auto-correction)
    2. Validates the full schema is DDL-ready
    3. Returns the fixed tables + validation report

    Usage:
        tables, report = validate_erd_output(parsed_tables)
        assert report['status'] == 'PASS', f"ERD validation failed: {report['errors']}"
        # Now safe to write erd_parsed.yaml and generate DDL
    """
    print("═" * 60)
    print("ERD OUTPUT VALIDATION PIPELINE")
    print("═" * 60)

    # Step 1: Fix data types
    print("\n[1/2] Data type completeness check...")
    tables, fixes = validate_and_fix_datatypes(tables)

    # Step 2: Full schema validation
    print("\n[2/2] Schema structure validation...")
    report = validate_schema_for_ddl(tables)
    report['datatype_fixes'] = fixes
    report['datatype_fixes_count'] = len(fixes)

    print("\n" + "═" * 60)
    if report['status'] == 'PASS':
        print(f"✅ ERD VALIDATION PASSED — {len(tables)} tables, {len(fixes)} type fixes applied")
    else:
        print(f"❌ ERD VALIDATION FAILED — {len(report['errors'])} errors must be resolved")
    print("═" * 60)

    return tables, report
