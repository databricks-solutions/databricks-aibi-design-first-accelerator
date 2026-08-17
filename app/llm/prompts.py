"""Prompt builders for AI/BI Studio pipeline steps.

Each function returns a (system_message, user_message) tuple derived from
the framework prompts in framework/prompts/*.md. The prompts guide the LLM
to produce structured output aligned with pipeline requirements.

Design notes:
    - System prompts set the role and constraints
    - User prompts provide the specific context (schema, KPIs, templates)
    - Each prompt references its source framework prompt file
    - Prompts are deterministic functions (no LLM calls here)

See docs/design_phase2.md Section 3.3 for full reference.
"""

import json
import yaml
from typing import Optional


# ---------------------------------------------------------------------------
# Step 1A: ERD Parsing (Vision Model)
# ---------------------------------------------------------------------------

def erd_parser_prompt(
    catalog_source: str,
    domain_description: str = "",
) -> tuple:
    """Build prompt for ERD image parsing via vision model.

    Source: framework/prompts/01_create_data_layer.md (Phase A)

    Args:
        catalog_source: Target catalog.schema for table names.
        domain_description: Domain context for naming conventions.

    Returns:
        (system_message, user_message) tuple.
    """
    system = (
        "You are a data engineer analyzing an Entity-Relationship Diagram (ERD). "
        "Extract ALL tables, columns, data types, primary keys, foreign keys, "
        "and relationships from the image. Output YAML format with the following structure:\n"
        "tables:\n"
        "  - name: <snake_case_table_name>\n"
        "    table_type: fact|dimension|bridge\n"
        "    columns:\n"
        "      - name: <column_name>\n"
        "        data_type: <SQL_TYPE>\n"
        "        nullable: true|false\n"
        "    primary_key: [col1, col2]\n"
        "    foreign_keys:\n"
        "      - column: <fk_col>\n"
        "        references_table: <table>\n"
        "        references_column: <col>\n"
        "relationships:\n"
        "  - from_table: <table>\n"
        "    from_column: <col>\n"
        "    to_table: <table>\n"
        "    to_column: <col>\n"
        "    cardinality: many-to-one\n\n"
        "CRITICAL RULES:\n"
        "- You MUST extract EVERY table in the diagram — do NOT skip any\n"
        "- Before generating YAML, COUNT all tables visible in the image\n"
        "- Use snake_case for all names (convert dots to underscores: dim.member → dim_member)\n"
        "- Map visual types to Databricks SQL types (STRING, INT, BIGINT, DECIMAL, DATE, TIMESTAMP, BOOLEAN)\n"
        "- Identify fact vs dimension tables from naming and relationships\n"
        "- Include ALL columns visible in every table box — read carefully, do not truncate\n"
        "- Look at ALL areas of the diagram: top, bottom, left, right, center\n"
        "- Small tables and reference tables at edges are often missed — check for them explicitly"
    )

    user = (
        f"Parse this ERD image for the domain: {domain_description or 'healthcare claims'}. "
        f"Tables will be created in schema: {catalog_source}. "
        "IMPORTANT: First COUNT the total number of tables/entities visible in this diagram. "
        "State the count, then extract EVERY single table with all its columns. "
        "Do not skip any tables even if they appear small or partially visible. "
        "Return YAML only (with the count as a comment at the top)."
    )

    return system, user


# ---------------------------------------------------------------------------
# Step 1B: DDL Generation
# ---------------------------------------------------------------------------

def ddl_generator_prompt(
    parsed_erd: dict,
    template: str,
    target_schema: str,
    table_suffix: str = "",
) -> tuple:
    """Build prompt for DDL notebook generation.

    Source: framework/prompts/01_create_data_layer.md (Phase B)

    Args:
        parsed_erd: Parsed ERD from Step 1A (tables, relationships).
        template: DDL notebook template content.
        target_schema: catalog.schema for CREATE TABLE statements.
        table_suffix: Version suffix to append to table names (e.g. '_v1').

    Returns:
        (system_message, user_message) tuple.
    """
    system = (
        "You are a Databricks SQL engineer. Generate a SQL notebook in Databricks "
        "SOURCE format that creates Unity Catalog tables from the provided ERD.\n\n"
        "OUTPUT FORMAT (Databricks SQL notebook SOURCE format):\n"
        "- First line MUST be: -- Databricks notebook source\n"
        "- Cells are separated by: -- COMMAND ----------\n"
        "- Cell titles: -- DBTITLE 1,Title Here\n"
        "- Each cell contains plain SQL (NO # MAGIC, NO %sql prefix)\n"
        "- Do NOT wrap output in markdown code fences\n\n"
        "SQL RULES:\n"
        "- Use CREATE OR REPLACE TABLE (not IF NOT EXISTS) to ensure fresh schema\n"
        "- Include COMMENT on each table and column\n"
        "- Add NOT NULL constraints for primary keys\n"
        "- Use Delta format (default)\n"
        "- Each table in a separate cell\n"
        "- First cell: CREATE SCHEMA IF NOT EXISTS\n"
        "- Create dimension/reference tables BEFORE fact tables\n"
        "- Add PRIMARY KEY constraints (CONSTRAINT pk_name PRIMARY KEY (col))\n"
        "- Do NOT add FOREIGN KEY constraints (they are informational-only in Databricks and cause errors)\n"
        "- Instead, document relationships in column COMMENTs, e.g. COMMENT \'References provider_dim.provider_id\'"
    )

    erd_yaml = yaml.dump(parsed_erd, default_flow_style=False)

    suffix_instruction = ""
    if table_suffix:
        suffix_instruction = (
            f"\n\nTABLE NAMING: Append `{table_suffix}` to every table name. "
            f"For example: `dim_member` becomes `dim_member{table_suffix}`, "
            f"`fact_claim_header` becomes `fact_claim_header{table_suffix}`. "
            f"Apply this suffix to ALL table names in CREATE statements, "
            f"but NOT to column names or schema names."
        )

    user = (
        f"Generate a DDL notebook for schema `{target_schema}` using this ERD:\n\n"
        f"```yaml\n{erd_yaml}\n```\n\n"
        f"Follow this template structure:\n```\n{template}\n```"
        f"{suffix_instruction}\n\n"
        "Return the complete notebook content in Databricks SQL SOURCE format. "
        "Do NOT wrap in code fences."
    )

    return system, user


# ---------------------------------------------------------------------------
# Step 1C: Synthetic Data Generation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Volume Tier Calculation
# ---------------------------------------------------------------------------

# Row count multipliers by volume tier and table type
VOLUME_TIERS = {
    "low": {"dimension": 500, "fact": 5000, "bridge": 10000, "reference": 200},
    "medium": {"dimension": 5000, "fact": 100000, "bridge": 200000, "reference": 1000},
    "large": {"dimension": 50000, "fact": 1000000, "bridge": 2000000, "reference": 5000},
}


def _compute_volume_per_table(parsed_erd: dict, volume_config) -> dict:
    """Compute row counts per table based on ERD structure and volume tier.

    Classifies tables as dimension, fact, bridge, or reference based on:
    - Name contains 'dim' or is referenced by FKs → dimension
    - Name contains 'fact' or has FKs to dimensions → fact
    - Name contains 'bridge' or 'map' or has only FKs → bridge
    - Else → reference (small lookup table)

    Args:
        parsed_erd: Parsed ERD dict with 'tables' and 'relationships'.
        volume_config: "low"|"medium"|"large" string, or legacy dict.

    Returns:
        Dict mapping table_name → row_count.
    """
    # Handle legacy dict format (backwards compatible)
    if isinstance(volume_config, dict) and volume_config:
        return volume_config

    # Determine tier
    tier = volume_config if isinstance(volume_config, str) else "low"
    tier = tier.lower() if tier else "low"
    if tier not in VOLUME_TIERS:
        tier = "low"

    multipliers = VOLUME_TIERS[tier]
    tables = parsed_erd.get("tables", [])
    relationships = parsed_erd.get("relationships", [])

    # Build FK reference map to classify tables
    fk_sources = set()  # tables that HAVE foreign keys (likely facts/bridges)
    fk_targets = set()  # tables that ARE referenced by FKs (likely dimensions)

    for rel in relationships:
        src = rel.get("from_table") or rel.get("source", "")
        tgt = rel.get("to_table") or rel.get("target", "")
        if src:
            fk_sources.add(src.lower())
        if tgt:
            fk_targets.add(tgt.lower())

    result = {}
    for table in tables:
        name = table.get("name", "") if isinstance(table, dict) else str(table)
        name_lower = name.lower()

        # Classify table type
        if "bridge" in name_lower or "map" in name_lower or "xref" in name_lower:
            table_type = "bridge"
        elif "dim" in name_lower or name_lower in fk_targets:
            table_type = "dimension"
        elif "fact" in name_lower or name_lower in fk_sources:
            table_type = "fact"
        elif "date" in name_lower or "calendar" in name_lower:
            table_type = "dimension"
        else:
            # Default: if table has FKs it's a fact, otherwise reference
            table_type = "fact" if name_lower in fk_sources else "reference"

        result[name] = multipliers[table_type]

    return result


def synthetic_data_prompt(
    parsed_erd: dict,
    template: str,
    target_schema: str,
    volume_config=None,
    table_suffix: str = "",
) -> tuple:
    """Build prompt for synthetic data notebook generation.

    Source: framework/prompts/01_create_data_layer.md (Phase C)

    Args:
        parsed_erd: Parsed ERD (tables, relationships, types).
        template: dbldatagen notebook template.
        target_schema: catalog.schema for INSERT targets.
        volume_config: Volume tier ("low"|"medium"|"large") or legacy dict.
        table_suffix: Version suffix to append to table names (e.g. '_v1').

    Returns:
        (system_message, user_message) tuple.
    """
    # Compute dynamic row counts per table based on volume tier and ERD
    volume_per_table = _compute_volume_per_table(parsed_erd, volume_config)
    system = (
        "You are a data engineer generating synthetic test data using dbldatagen. "
        "Generate a Python notebook (Databricks SOURCE format) that creates realistic sample data.\n\n"
        "OUTPUT FORMAT (Databricks Python notebook SOURCE format):\n"
        "- First line: # Databricks notebook source\n"
        "- Cells separated by: # COMMAND ----------\n"
        "- Cell titles: # DBTITLE 1,Title Here\n"
        "- Do NOT wrap output in markdown code fences\n\n"
        "DBLDATAGEN API RULES (CRITICAL — use only these valid column options):\n"
        "- withColumn(colName, colType, ...) valid kwargs:\n"
        "  minValue, maxValue, step, random, values, weights,\n"
        "  percentNulls (NOT percentNullValues), numFeatures, numColumns,\n"
        "  baseColumn, baseColumnType, template, text, expr,\n"
        "  structType, begin, end, interval, uniqueValues, dataRange\n"
        "- withColumnSpec(colName, ...) — same kwargs as withColumn\n"
        "- For nullable columns use: percentNulls=0.1 (NOT percentNullValues)\n"
        "- For FK references use: baseColumn=\'parent_col\', values=list_of_ids\n"
        "- For DateType columns: begin=\'2020-01-01\', end=\'2024-12-31\', interval=\'1 day\' (MUST be YYYY-MM-DD only, NEVER include time like 00:00:00)\n"
        "- For TimestampType columns: begin=\'2020-01-01 00:00:00\', end=\'2024-12-31 23:59:59\', interval=\'1 day\' (MUST include time component)\n"
        "- For IDs: template=r\'\\\\w\\\\w\\\\w-\\\\d\\\\d\\\\d\\\\d\'\n"
        "- Row count via: DataGenerator(spark, rows=N, ...)\n\n"
        "CRITICAL CONSTRAINTS:\n"
        "- Use ONLY dbldatagen DataGenerator for ALL tables (including date dimensions)\n"
        "- Do NOT use raw PySpark DataFrame operations (no col(), no F.concat(), no selectExpr)\n"
        "- Do NOT import pyspark.sql.functions — use dbldatagen only\n"
        "- For date dimensions: use DataGenerator with DateType(), begin/end/interval\n"
        "- Keep each table simple — avoid complex expressions\n"
        "- Keep ALL strings on a single line (no multi-line f-strings or triple-quoted strings)\n"
        "- Use short, simple print() statements for logging\n"
        "- Ensure every string literal is properly closed on the same line\n\n"
        "COLUMN ORDERING (CRITICAL — causes DataGenError if violated):\n"
        "- In dbldatagen, columns are processed in the order they are defined via .withColumn()\n"
        "- If column B uses baseColumn='A', then column A MUST be defined BEFORE column B\n"
        "- Primary key columns (e.g. member_sk, claim_id) must ALWAYS be defined FIRST\n"
        "- Foreign key columns that reference another column via baseColumn must come AFTER the referenced column\n"
        "- If a column does NOT reference another column (no baseColumn), order does not matter\n"
        "- Rule of thumb: define columns in this order: (1) PK/SK columns, (2) independent columns, (3) dependent/FK columns\n\n"
        "GENERAL RULES:\n"
        "- CRITICAL: Generate data ONLY for columns listed in the ERD below. Do NOT invent extra columns.\n"
        "- Maintain referential integrity (FK values from parent tables)\n"
        "- Process dimension tables before fact tables\n"
        "- Write using: df.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').saveAsTable(...)\n"
        "- Each table is a separate cell\n"
        "- Use 1000 rows for dimension tables, 10000 for fact tables unless specified\n"
        "- Match column names and types EXACTLY as specified in the ERD"
    )

    erd_yaml = yaml.dump(parsed_erd, default_flow_style=False)
    volume_str = json.dumps(volume_per_table, indent=2)

    # Build explicit table list
    table_names = list(volume_per_table.keys())
    table_list_str = ", ".join(f"`{t}`" for t in table_names)

    suffix_instruction = ""
    if table_suffix:
        suffix_instruction = (
            f"\n\nTABLE NAMING: Append `{table_suffix}` to every table name in saveAsTable(). "
            f"For example: `dim_member` becomes `dim_member{table_suffix}`, "
            f"`fact_claim_header` becomes `fact_claim_header{table_suffix}`. "
            f"Apply to ALL saveAsTable calls but NOT to column names or schema names."
        )

    user = (
        f"Generate a synthetic data notebook for schema `{target_schema}`.\n\n"
        f"ERD:\n```yaml\n{erd_yaml}\n```\n\n"
        f"## Row counts per table (MUST use these exact values for rows=N):\n"
        f"```json\n{volume_str}\n```\n\n"
        f"## STRICT TABLE LIST — generate EXACTLY these {len(table_names)} tables, NO MORE:\n"
        f"{table_list_str}\n\n"
        f"CRITICAL: Do NOT invent, infer, or add any tables beyond the {len(table_names)} listed above. "
        f"Do NOT create duplicates with alternative names (e.g. no fact_claim_header if claim_header_fact is listed). "
        f"If a FK references a table not in this list, use synthetic IDs inline — do NOT create the referenced table."
        f"{suffix_instruction}\n\n"
        f"Template:\n```\n{template[:2000]}\n```\n\n"
        "Return Python notebook cells using dbldatagen."
    )

    return system, user


# ---------------------------------------------------------------------------
# Step 2: Metric View Design
# ---------------------------------------------------------------------------

def metric_view_prompt(
    kpi_spec: str,
    best_practices: str,
    schema_profile: dict,
    template_header: str,
    target_schema: str,
    view_fqn: str = None,
    source_schema: str = None,
) -> tuple:
    """Build prompt for metric view YAML generation.

    Source: framework/prompts/02_create_metric_views.md

    Args:
        kpi_spec: KPI specification markdown.
        best_practices: Metric view design rules.
        schema_profile: Schema profile from Step 1/2A.
        template_header: YAML template header for structure guidance.
        target_schema: catalog.schema for CREATE VIEW target.
        view_fqn: Exact FQN the view MUST be created with.
        source_schema: Exact source schema FQN for FROM/JOIN clauses.

    Returns:
        (system_message, user_message) tuple.
    """
    system = (
        "You are a semantic layer architect designing Unity Catalog metric views. "
        "Design metric views that:\n"
        "- Use MEASURE() aggregation semantics (SUM, COUNT, AVG, etc.)\n"
        "- Classify columns as dimension, measure, or time_dimension\n"
        "- Follow the best practices document exactly\n"
        "- Include a complete CREATE OR REPLACE VIEW statement for each view\n"
        "- Use descriptive COMMENT ON for Genie discoverability\n"
        "- Handle NULL values gracefully (COALESCE, NULLIF)\n"
        "- Apply correct JOIN logic for star-schema patterns\n"
        "- CRITICAL: When joining columns with mismatched types (e.g. STRING FK to BIGINT/LONG PK), "
        "always wrap the numeric side with CAST(col AS STRING) to avoid CAST_INVALID_INPUT errors\n\n"
    )

    if best_practices:
        system += f"Best Practices:\n{best_practices[:3000]}\n\n"

    profile_yaml = yaml.dump(schema_profile, default_flow_style=False)[:4000]

    user = f"Design a metric view for these KPIs:\n\n"

    # Enforce exact names
    if view_fqn:
        user += (
            f"CRITICAL NAMING REQUIREMENTS:\n"
            f"- The view MUST be created as: `{view_fqn}`\n"
            f"- Use exactly this name in the CREATE OR REPLACE VIEW statement\n"
        )
    if source_schema:
        user += (
            f"- All source tables are in: `{source_schema}`\n"
            f"- Use fully qualified table names: `{source_schema}.<table_name>`\n"
            f"- DO NOT use any other catalog/schema for source tables\n\n"
        )
    else:
        user += f"Target schema: `{target_schema}`\n\n"

    user += (
        f"## KPI Spec\n{kpi_spec[:3000]}\n\n"
        f"## Source Schema Profile\n```yaml\n{profile_yaml}\n```\n\n"
        f"## Template Header\n```yaml\n{template_header}\n```\n\n"
        "Return YAML with `views:` array. Each view must have:\n"
        "- name, description, source_tables, create_statement, columns[]"
    )

    return system, user


# ---------------------------------------------------------------------------
# Step 3: Dashboard Design
# ---------------------------------------------------------------------------

def dashboard_prompt(
    mv_profile: dict,
    dashboard_name: str,
    kpi_spec: str = None,
    lakeview_guide: str = None,
) -> tuple:
    """Build prompt for Lakeview dashboard JSON generation.

    Uses framework/inputs/lakeview_dashboard_api.md as the definitive
    format guide for the LLM. The guide contains exact JSON structure,
    widget rules, and validation checklist.

    Args:
        mv_profile: Metric view profile (columns, measures, dimensions, fqn).
        dashboard_name: Display name for the dashboard.
        kpi_spec: Optional KPI specification (from inputs/kpi_spec.md).
        lakeview_guide: Content of lakeview_dashboard_api.md.

    Returns:
        (system_message, user_message) tuple.
    """
    system = (
        "You are a dashboard designer creating a Databricks Lakeview (AI/BI) dashboard. "
        "Generate the serialized_dashboard JSON that the Lakeview API accepts.\n\n"
        "CRITICAL: Return ONLY raw JSON. No markdown fences, no prose, no explanation.\n\n"
    )

    # Include the full Lakeview API guide if provided
    if lakeview_guide:
        system += (
            "## Lakeview Dashboard API Reference\n"
            f"{lakeview_guide}\n\n"
        )

    fqn = mv_profile.get("fqn", "catalog.schema.metric_view")
    measures = mv_profile.get("measures", [])
    dimensions = mv_profile.get("dimensions", [])
    columns = mv_profile.get("columns", [])

    col_list = "\n".join([f"  - {c['name']} ({c['type']})" for c in columns[:30]])
    measures_list = ", ".join(measures[:15])
    dimensions_list = ", ".join(dimensions[:15])

    user = (
        f"Create a dashboard named \'{dashboard_name}\' for metric view: {fqn}\n\n"
        f"Available columns:\n{col_list}\n\n"
        f"Measures (numeric): {measures_list}\n"
        f"Dimensions (categorical/date): {dimensions_list}\n\n"
    )

    if kpi_spec:
        user += f"## KPI Specification\n{kpi_spec}\n\n"

    user += (
        "Requirements:\n"
        "- Include a PAGE_TYPE_CANVAS page\n"
        "- 3-4 counter widgets at top for key metrics\n"
        "- 2-3 bar or line charts in middle\n"
        "- 1 detail table at bottom\n"
        "- All dataset queries must reference the metric view table directly\n"
        "- Follow the exact JSON format from the Lakeview API reference above\n\n"
        "Return ONLY the serialized_dashboard JSON object."
    )

    return system, user


# ---------------------------------------------------------------------------
# Step 4: Genie Space Content
# ---------------------------------------------------------------------------

def genie_content_prompt(
    kpi_spec: str,
    schema_profile: dict,
    genie_guide: str,
    domain: str,
    metric_view_fqn: str,
) -> tuple:
    """Build prompt for Genie space content generation.

    Source: framework/prompts/04_create_genie_space.md

    Args:
        kpi_spec: KPI spec for question/SQL generation.
        schema_profile: Schema profile for SQL context.
        genie_guide: Genie space configuration guide.
        domain: Domain name for context.
        metric_view_fqn: Fully qualified metric view name.

    Returns:
        (system_message, user_message) tuple.
    """
    system = (
        "You are configuring a Databricks Genie space for natural language analytics. "
        "Generate comprehensive content that enables business users to ask questions. "
        "Requirements:\n"
        "- general_instructions: >500 chars, domain-specific guidance for the AI agent\n"
        "- benchmark_questions: >= 5 questions for quality testing\n"
        "- sample_questions: >= 15 diverse questions for user discovery\n"
        "- example_sqls: >= 15 question/SQL pairs using MEASURE() syntax\n\n"
        f"Genie Guide:\n{genie_guide[:3000]}"
    )

    profile_yaml = yaml.dump(schema_profile, default_flow_style=False)[:2000]
    user = (
        f"Generate Genie space content for domain '{domain}'.\n"
        f"Metric view: `{metric_view_fqn}`\n\n"
        f"## KPI Spec\n{kpi_spec[:2000]}\n\n"
        f"## Schema\n```yaml\n{profile_yaml}\n```\n\n"
        "Return YAML with: general_instructions, benchmark_questions, "
        "sample_questions, example_sqls (each with question + sql fields)."
    )

    return system, user


# ---------------------------------------------------------------------------
# Step 5: Documentation
# ---------------------------------------------------------------------------

def documentation_prompt(
    config: dict,
    outputs: dict,
) -> tuple:
    """Build prompt for run summary generation (optional LLM enhancement).

    Source: framework/prompts/05_generate_documentation.md

    Args:
        config: Pipeline config summary dict.
        outputs: Collected outputs and validation results.

    Returns:
        (system_message, user_message) tuple.
    """
    system = (
        "You are a technical writer summarizing a data pipeline run. "
        "Generate a concise, well-structured summary of what was created, "
        "including asset links, validation results, and recommended next steps."
    )

    user = (
        f"Summarize this pipeline run:\n\n"
        f"Config: {json.dumps(config, indent=2)}\n\n"
        f"Outputs: {json.dumps(outputs, indent=2, default=str)[:3000]}\n\n"
        "Return a markdown summary with sections: Overview, Assets Created, "
        "Validation, Next Steps."
    )

    return system, user
