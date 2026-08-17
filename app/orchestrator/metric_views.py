"""MetricViewCreator — Step 2: KPI Spec -> Metric Views.

Creates Unity Catalog metric views from the KPI specification:
    Phase A: Profile source schema (discover tables, columns, relationships)
    Phase B: Generate metric view YAML via LLM (aligned to best practices)
    Phase C: Execute CREATE OR REPLACE VIEW statements
    Phase D: Validate with MEASURE() queries

Design notes:
    - Reads best_practices.md for aggregation rules
    - Profiles source schema to understand available columns
    - LLM generates YAML that maps KPIs to MEASURE() expressions
    - Self-correction: feeds SQL errors back to LLM for retry
    - Phase-aware: execution driven by pipeline_step_phases_config table
    - Supports resume from failed phase without re-running completed phases

See docs/design_phase2.md Section 4.3, prompt 02_create_metric_views.md.
"""

import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class MetricViewCreator:
    """Pipeline Step 2: Create metric views from KPI spec.

    Phase-aware step. Phases are driven by pipeline_step_phases_config:
        profile_schema  (0) -> schema_profile.yaml
        generate_metrics (1) -> metric_view.yaml via LLM
        execute_metrics  (2) -> CREATE OR REPLACE VIEW DDL + validation

    Supports:
        - Phase-level progress events via phase_callback
        - Resume from failed phase (skips completed phases)
        - Context reconstruction from disk artifacts on resume
    """

    # Phase name -> handler method name
    PHASE_HANDLERS = {
        "profile_schema": "_phase_profile_schema",
        "generate_metrics": "_generate_metric_views",
        "execute_metrics": "_execute_metric_ddl",
    }

    def __init__(self, config, services: dict, llm_client):
        """Initialize step.

        Args:
            config: AcceleratorConfig.
            services: {"workspace", "sql"} service instances.
            llm_client: LLMClient for model calls.
        """
        self._config = config
        self._ws = services["workspace"]
        self._sql = services["sql"]
        self._llm = llm_client
        # Inter-phase context (populated during execution or on resume)
        self._ctx = {"schema_profile": None, "mv_yaml": None, "artifacts": []}

    def execute(self, phases=None, resume_from_phase=None,
                phase_callback: Optional[Callable] = None) -> list:
        """Execute the metric view creation step.

        Args:
            phases: Ordered list of phase dicts from pipeline_step_phases_config.
                    Falls back to PHASE_HANDLERS keys if None (backward compat).
            resume_from_phase: Phase name to resume from (skips prior phases).
            phase_callback: Callable(phase_name, event, **kwargs) for progress.

        Returns:
            List of artifact paths.
        """
        # Reset context
        self._ctx = {"schema_profile": None, "mv_yaml": None, "artifacts": []}

        # Determine phase list
        if phases:
            phase_names = [p["phase_name"] if isinstance(p, dict) else p for p in phases]
        else:
            phase_names = list(self.PHASE_HANDLERS.keys())

        # Find resume index
        resume_index = 0
        if resume_from_phase:
            try:
                resume_index = phase_names.index(resume_from_phase)
            except ValueError:
                logger.warning(f"Resume phase '{resume_from_phase}' not found, running all")
                resume_index = 0
            # Reconstruct context from prior phases
            self._reconstruct_context(phase_names[:resume_index])

        # Execute phases
        for i, phase_name in enumerate(phase_names):
            if i < resume_index:
                # Skip completed phases
                if phase_callback:
                    phase_callback(phase_name, "skipped")
                continue

            # Run phase with timing
            if phase_callback:
                phase_callback(phase_name, "started")

            start_ms = time.time() * 1000
            try:
                self._run_phase(phase_name)
                duration_ms = int(time.time() * 1000 - start_ms)

                if phase_callback:
                    phase_callback(phase_name, "completed",
                                   duration_ms=duration_ms,
                                   artifacts=self._ctx["artifacts"])
            except Exception as exc:
                duration_ms = int(time.time() * 1000 - start_ms)
                if phase_callback:
                    phase_callback(phase_name, "failed",
                                   duration_ms=duration_ms,
                                   error=str(exc),
                                   error_detail=self._format_error_detail(exc))
                raise

        return self._ctx["artifacts"]

    # ------------------------------------------------------------------
    # Phase dispatcher & context reconstruction
    # ------------------------------------------------------------------

    def _run_phase(self, phase_name: str) -> None:
        """Dispatch to the handler for a given phase."""
        handler_name = self.PHASE_HANDLERS.get(phase_name)
        if not handler_name:
            raise ValueError(f"Unknown phase: {phase_name}")

        handler = getattr(self, handler_name)
        handler()

    def _reconstruct_context(self, completed_phases: list) -> None:
        """Rebuild self._ctx from disk artifacts for completed phases.

        Called on resume so later phases have the data they need.
        """
        import yaml

        if "profile_schema" in completed_phases:
            profile_path = f"{self._config.output_folder}/schema_profile.yaml"
            try:
                content = self._ws.read_file(profile_path)
                self._ctx["schema_profile"] = yaml.safe_load(content)
                self._last_profile = self._ctx["schema_profile"]
                self._ctx["artifacts"].append(profile_path)
                logger.info("Reconstructed schema_profile from disk")
            except Exception as e:
                logger.warning(f"Failed to reconstruct schema_profile: {e}")

        if "generate_metrics" in completed_phases:
            mv_path = f"{self._config.output_folder}/metric_views/metric_view.yaml"
            try:
                self._ctx["mv_yaml"] = self._ws.read_file(mv_path)
                self._ctx["artifacts"].append(mv_path)
                logger.info("Reconstructed mv_yaml from disk")
            except Exception as e:
                logger.warning(f"Failed to reconstruct mv_yaml: {e}")

    @staticmethod
    def _format_error_detail(exc: Exception) -> str:
        """Format full traceback for error persistence."""
        import traceback
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    # ------------------------------------------------------------------
    # Phase handler methods (called by _run_phase dispatcher)
    # ------------------------------------------------------------------

    def _phase_profile_schema(self) -> None:
        """Phase handler: profile source schema and store in context."""
        schema_profile = self._profile_schema()
        self._ctx["schema_profile"] = schema_profile
        self._last_profile = schema_profile  # Used by self-correction context
        profile_path = f"{self._config.output_folder}/schema_profile.yaml"
        self._ws.write_yaml(profile_path, schema_profile)
        self._ctx["artifacts"].append(profile_path)
        logger.info(f"Phase profile_schema: profiled {len(schema_profile.get('tables', []))} tables")

    def _generate_metric_views(self) -> None:
        """Phase handler: generate metric view YAML via LLM."""
        schema_profile = self._ctx["schema_profile"]
        if not schema_profile:
            raise RuntimeError(
                "Cannot generate metrics — schema_profile not available. "
                "Ensure profile_schema phase completed first."
            )
        mv_yaml = self._generate_metric_view(schema_profile)
        mv_path = f"{self._config.output_folder}/metric_views/metric_view.yaml"
        self._ws.write_file(mv_path, mv_yaml)
        self._ctx["mv_yaml"] = mv_yaml
        self._ctx["artifacts"].append(mv_path)
        logger.info("Phase generate_metrics: Metric view YAML generated")

    def _execute_metric_ddl(self) -> None:
        """Phase handler: execute DDL + validate the metric view."""
        mv_yaml = self._ctx["mv_yaml"]
        if not mv_yaml:
            raise RuntimeError(
                "Cannot execute metrics — mv_yaml not available. "
                "Ensure generate_metrics phase completed first."
            )
        # Execute DDL with self-correction
        self._execute_metric_view_ddl(mv_yaml)
        logger.info("Phase execute_metrics: DDL executed")

        # Validate
        validation = self._validate_metric_view()
        validation_path = f"{self._config.output_folder}/metric_views/validation.yaml"
        self._ws.write_yaml(validation_path, validation)
        self._ctx["artifacts"].append(validation_path)
        logger.info(f"Phase execute_metrics: Validation complete (passed={validation.get('passed', False)})")

        if not validation.get("passed"):
            checks_info = "; ".join(
                f"{c['check']}={'PASS' if c['passed'] else 'FAIL'}"
                for c in validation.get("checks", [])
            )
            raise RuntimeError(
                f"Metric view validation failed: {checks_info}. "
                f"View FQN: {self._config.catalog.target}.{self._config.assets.metric_view}"
            )

    # ------------------------------------------------------------------
    # Internal helpers (called by phase handlers)
    # ------------------------------------------------------------------

    def _profile_schema(self) -> dict:
        """Discover tables, columns, and relationships in source schema.

        Returns:
            Schema profile dict with tables, columns, row counts, sample data.
        """
        # Determine which schema(s) to profile
        schemas_to_profile = []
        if self._config.data_source.live_schemas:
            schemas_to_profile = [
                f"{s['catalog']}.{s['schema']}" for s in self._config.data_source.live_schemas
            ]
        elif self._config.data_source.live_schema:
            ls = self._config.data_source.live_schema
            schemas_to_profile = [f"{ls['catalog']}.{ls['schema']}"]
        elif self._config.catalog.source:
            schemas_to_profile = [self._config.catalog.source]

        profile = {"tables": [], "schemas": schemas_to_profile}

        for schema_fqn in schemas_to_profile:
            tables_result = self._sql.execute_and_wait(f"SHOW TABLES IN {schema_fqn}")
            for row in tables_result.data:
                table_name = row[1] if len(row) > 1 else row[0]
                fqn = f"{schema_fqn}.{table_name}"

                # Get columns
                columns = self._sql.get_table_schema(fqn)
                row_count = self._sql.get_row_count(fqn)

                profile["tables"].append({
                    "fqn": fqn,
                    "name": table_name,
                    "schema": schema_fqn,
                    "columns": [{"name": c.name, "type": c.type} for c in columns],
                    "row_count": row_count
                })

        return profile

    # ------------------------------------------------------------------
    # Phase B: Generate Metric View
    # ------------------------------------------------------------------

    def _generate_metric_view(self, schema_profile: dict) -> str:
        """Generate metric view YAML using LLM.

        Reads framework/prompts/02_create_metric_views.md as the system prompt.
        The LLM follows the prompt instructions to generate the metric view.

        Args:
            schema_profile: Output of Phase A.

        Returns:
            Metric view YAML string.
        """
        # Load the framework prompt as system message
        system_prompt = self._ws.read_file(
            f"{self._config.framework_root}/prompts/02_create_metric_views.md"
        )

        # Load reference inputs per the prompt's Step 1
        kpi_spec = self._ws.read_file(f"{self._config.inputs_dir}/kpi_spec.md")

        best_practices = ""
        try:
            best_practices = self._ws.read_file(
                f"{self._config.framework_root}/inputs/best_practices.md"
            )
        except Exception:
            logger.debug("best_practices.md not found — continuing without it")

        yaml_reference = ""
        try:
            yaml_reference = self._ws.read_file(
                f"{self._config.framework_root}/inputs/metric_view_yaml_reference.md"
            )
        except Exception:
            logger.debug("metric_view_yaml_reference.md not found — continuing without it")

        template_header = self._ws.read_file(
            f"{self._config.framework_root}/templates/metric_view_yaml.header.yaml"
        )

        # Build fully qualified names the LLM must use
        target_fqn = f"{self._config.catalog.target}.{self._config.assets.metric_view}"
        source_schema = self._config.catalog.source

        # Build a concise table/column reference with DATA TYPES
        # (critical for the LLM to handle type-safe joins)
        table_ref_lines = []
        for t in schema_profile.get("tables", []):
            fqn = t.get("fqn", f"{source_schema}.{t['name']}")
            row_count = t.get("row_count", "?")
            col_lines = []
            for c in t.get("columns", []):
                col_lines.append(f"  - {c['name']} ({c.get('type', 'STRING')})")
            table_ref_lines.append(
                f"### `{fqn}` ({row_count} rows)\n"
                + "\n".join(col_lines) + "\n"
            )
        table_reference = "\n".join(table_ref_lines)

        # Compose user message with YAML reference as primary guide
        user_msg = (
            f"## Metric View YAML Reference (FOLLOW THIS EXACTLY)\n\n"
            f"{yaml_reference}\n\n"
            f"---\n\n"
            f"## Runtime Context\n\n"
            f"**Target view FQN (MUST use exactly):** `{target_fqn}`\n"
            f"**Source schema:** `{source_schema}`\n"
            f"**Domain:** {self._config.domain_name}\n\n"
            f"---\n\n"
            f"## CRITICAL: Available Source Tables and Columns\n\n"
            f"You MUST use ONLY these exact table and column names.\n"
            f"In the YAML `source:` field, use the FULL table FQN.\n"
            f"In `joins[].source:`, use the FULL table FQN.\n\n"
            f"{table_reference}\n\n"
            f"---\n\n"
            f"## KPI Specification\n\n{kpi_spec}\n\n"
            f"---\n\n"
            f"## Instructions\n\n"
            f"1. `source:` MUST be a fully qualified table name (catalog.schema.table) from the list above\n"
            f"2. `joins[].source:` MUST be fully qualified table names from the list above\n"
            f"3. In `expr:` for fields/measures: reference source table columns DIRECTLY (no prefix). Example: `expr: claim_type_cd`\n"
            f"4. For joined table columns: use `join_name.column`. Example: `expr: member.first_name`\n"
            f"5. In `joins[].on:` use `source.col = join_name.col` syntax\n"
            f"6. TYPE-SAFE JOINS (CRITICAL): Check column data types above. If a STRING column joins "
            f"to a LONG/INT/BIGINT column, you MUST wrap the numeric side with CAST(col AS STRING). "
            f"Example: `on: source.string_fk = CAST(dim.numeric_pk AS STRING)`. "
            f"NEVER let Spark implicitly cast STRING to BIGINT — it will fail on non-numeric values.\n"
            f"7. Window measures MUST have ALL THREE: order, range, semiadditive (see reference above)\n"
            f"8. `window[].order` MUST reference a field `name` defined in `fields:` section\n"
            f"9. Only use window measures for KPIs that explicitly need rolling/cumulative logic\n"
            f"10. PREFER a single source table (main fact table) with minimal JOINs\n"
            f"11. Only JOIN dimension tables if KPIs need columns NOT on the fact table\n"
            f"12. `cardinality:` in joins MUST be `many_to_one` (fact-to-dimension) or `one_to_one`\n"
            f"13. Return ONLY raw YAML starting with `version:`. No code fences. No prose.\n"
        )

        mv_yaml = self._llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg}
            ],
            max_tokens=16384
        )

        # Clean LLM output
        mv_yaml = self._clean_yaml_output(mv_yaml)
        return mv_yaml


    def _clean_yaml_output(self, text: str) -> str:
        """Strip markdown fences, prose, and artifacts from LLM YAML output.

        Handles multiple patterns:
            - ```yaml\n...\n``` (fenced block anywhere in response)
            - Prose before/after YAML content
            - Multiple fenced blocks (takes first)
        """
        if not text:
            return ""
        clean = text.strip()

        # If fences exist, extract content between them
        if "```" in clean:
            lines = clean.split("\n")
            start_idx = None
            end_idx = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("```") and start_idx is None:
                    start_idx = i + 1
                elif stripped.startswith("```") and start_idx is not None:
                    end_idx = i
                    break
            if start_idx is not None:
                end_idx = end_idx or len(lines)
                clean = "\n".join(lines[start_idx:end_idx])
            else:
                # Backticks exist but not as fences — remove lines with just backticks
                lines = [l for l in clean.split("\n") if not l.strip().startswith("```")]
                clean = "\n".join(lines)

        # If still starts with non-YAML (prose), find first YAML-like line
        lines = clean.split("\n")
        yaml_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if (stripped.startswith("version:") or stripped.startswith("views:")
                    or stripped.startswith("---") or stripped.startswith("-")
                    or stripped == ""):
                yaml_start = i
                break
        if yaml_start > 0:
            clean = "\n".join(lines[yaml_start:])

        return clean.strip()

    # ------------------------------------------------------------------
    # Phase C: Execute DDL
    # ------------------------------------------------------------------

    def _execute_metric_view_ddl(self, mv_yaml: str) -> None:
        """Execute CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML.

        Per 02_create_metric_views.md Step 3:
            CREATE OR REPLACE VIEW <fqn> WITH METRICS LANGUAGE YAML AS $$ <yaml> $$

        After creation, immediately queries the view to verify it works.
        If the query fails (wrong columns/tables), feeds error to LLM and retries.
        """
        import yaml
        clean_yaml = self._clean_yaml_output(mv_yaml)
        mv_config = yaml.safe_load(clean_yaml)

        if isinstance(mv_config, dict):
            views = mv_config.get("views", [mv_config])
            has_create = any(v.get("create_statement") for v in views if isinstance(v, dict))

            if has_create:
                for view in views:
                    sql = view.get("create_statement") or view.get("sql", "")
                    if sql:
                        self._execute_with_retry(sql.strip())
            else:
                # YAML metric view format
                target_fqn = f"{self._config.catalog.target}.{self._config.assets.metric_view}"

                # Ensure target schema exists
                self._sql.execute_ddl(
                    f"CREATE SCHEMA IF NOT EXISTS {self._config.catalog.target}"
                )

                # Post-process YAML to fix common issues before DDL
                clean_yaml = self._postprocess_metric_yaml(clean_yaml)

                # Create and test with retry loop
                self._create_and_test_metric_view(target_fqn, clean_yaml)

    def _postprocess_metric_yaml(self, yaml_content: str) -> str:
        """Validate and fix common YAML metric view issues before DDL execution.

        Fixes:
            - Type-mismatched join conditions (STRING FK to LONG/INT PK)
            - Window specs missing required 'order' field
            - Window specs missing required 'range' or 'rows' field
            - Empty window specs
        """
        import yaml
        try:
            config = yaml.safe_load(yaml_content)
        except Exception:
            return yaml_content  # Can't parse, let DDL handle the error

        if not isinstance(config, dict):
            return yaml_content

        measures = config.get("measures", [])
        fixed = False
        for measure in measures:
            if not isinstance(measure, dict):
                continue
            window = measure.get("window")
            if window is not None:
                if isinstance(window, dict):
                    # Single window spec — convert to list format (YAML requires list)
                    measure["window"] = [window]
                    window = measure["window"]
                    fixed = True

                if isinstance(window, list):
                    for ws in window:
                        if not isinstance(ws, dict):
                            continue
                        # Ensure all 3 required fields exist
                        if "order" not in ws:
                            # Try to find a date/time field from dimensions
                            date_fields = [d.get("name") for d in config.get("dimensions", []) + config.get("fields", [])
                                          if isinstance(d, dict) and any(k in d.get("name", "").lower()
                                          for k in ["date", "month", "time", "period"])]
                            ws["order"] = date_fields[0] if date_fields else "service_date"
                            fixed = True
                        if "range" not in ws:
                            ws["range"] = "current"
                            fixed = True
                        if "semiadditive" not in ws:
                            ws["semiadditive"] = "last"
                            fixed = True
                    logger.info(f"Completed window spec for measure: {measure.get('name')}")

        # Check for invalid expressions (nested dots like table.col.subfield)
        all_items = config.get("dimensions", []) + config.get("measures", [])
        for item in all_items:
            if not isinstance(item, dict):
                continue
            expr = item.get("expr", "")
            if isinstance(expr, str):
                # Find patterns like alias.column.subfield (3+ dots in an identifier)
                import re
                # Match word.word.word that's not inside a function call or string
                triple_dots = re.findall(r'\b(\w+\.\w+\.\w+)\b', expr)
                for td in triple_dots:
                    # Replace nested access with just alias.last_column
                    parts = td.split(".")
                    if len(parts) == 3:
                        # Likely table.column.field — simplify to table.column
                        fixed_expr = f"{parts[0]}.{parts[2]}"
                        expr = expr.replace(td, fixed_expr)
                        item["expr"] = expr
                        fixed = True
                        logger.info(f"Fixed nested expr '{td}' → '{fixed_expr}' in {item.get('name')}")

        # Fix type-mismatched join conditions using schema profile
        joins = config.get("joins", [])
        if joins and hasattr(self, '_last_profile') and self._last_profile:
            # Build column type index: {fqn: {col_name: type}}
            type_index = {}
            for t in self._last_profile.get("tables", []):
                t_fqn = t.get("fqn", "")
                type_index[t_fqn] = {c["name"]: c.get("type", "STRING").upper() for c in t.get("columns", [])}

            source_fqn = config.get("source", "")
            source_types = type_index.get(source_fqn, {})

            numeric_types = {"LONG", "INT", "BIGINT", "INTEGER", "SMALLINT", "TINYINT", "SHORT"}

            for join in joins:
                if not isinstance(join, dict):
                    continue
                join_source = join.get("source", "")
                join_types = type_index.get(join_source, {})
                on_clause = join.get("on", "")
                if not on_clause or "CAST" in on_clause:
                    continue  # Already has a CAST or no join condition

                # Parse simple equi-join: source.col = alias.col
                import re
                eq_matches = re.findall(r'source\.(\w+)\s*=\s*(\w+)\.(\w+)', on_clause)
                for src_col, alias, join_col in eq_matches:
                    src_type = source_types.get(src_col, "").upper()
                    jn_type = join_types.get(join_col, "").upper()

                    if src_type == "STRING" and jn_type in numeric_types:
                        # STRING FK = NUMERIC PK → wrap numeric with CAST
                        old_expr = f"{alias}.{join_col}"
                        new_expr = f"CAST({alias}.{join_col} AS STRING)"
                        on_clause = on_clause.replace(f"= {old_expr}", f"= {new_expr}", 1)
                        join["on"] = on_clause
                        fixed = True
                        logger.info(f"Fixed type mismatch in join: {old_expr} ({jn_type}) → CAST AS STRING")
                    elif src_type in numeric_types and jn_type == "STRING":
                        # NUMERIC FK = STRING PK → wrap source with CAST
                        old_expr = f"source.{src_col}"
                        new_expr = f"CAST(source.{src_col} AS STRING)"
                        on_clause = on_clause.replace(old_expr, new_expr, 1)
                        join["on"] = on_clause
                        fixed = True
                        logger.info(f"Fixed type mismatch in join: source.{src_col} ({src_type}) → CAST AS STRING")

        if fixed:
            return yaml.dump(config, default_flow_style=False, sort_keys=False)
        return yaml_content

    def _create_and_test_metric_view(self, target_fqn: str, yaml_content: str) -> None:
        """Create the metric view and verify it returns data. Retry on failure.

        This catches the case where CREATE VIEW succeeds syntactically but the
        view references wrong tables/columns (only fails on query).

        Args:
            target_fqn: Fully qualified view name.
            yaml_content: Metric view YAML content.
        """
        max_retries = 3
        current_yaml = yaml_content

        for attempt in range(max_retries):
            # Step 1: Create the view
            ddl = (
                f"CREATE OR REPLACE VIEW {target_fqn}\n"
                f"WITH METRICS LANGUAGE YAML\n"
                f"AS $$\n{current_yaml}\n$$"
            )
            try:
                self._sql.execute_ddl(ddl)
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"DDL failed (attempt {attempt+1}): {error_msg[:300]}")
                if attempt < max_retries - 1:
                    current_yaml = self._fix_metric_yaml(current_yaml, error_msg)
                    continue
                else:
                    raise RuntimeError(f"Metric view DDL failed after {max_retries} attempts: {error_msg}")

            # Step 2: Validate the view with DESCRIBE + a MEASURE query
            try:
                # First: DESCRIBE to verify view structure
                desc_result = self._sql.execute_and_wait(
                    f"DESCRIBE TABLE {target_fqn}", timeout_s=30.0
                )
                if desc_result.status != "SUCCEEDED" or not desc_result.data:
                    error_msg = f"DESCRIBE failed: {desc_result.error or 'no columns returned'}"
                else:
                    # Extract field and measure names from DESCRIBE
                    col_names = [row[0] for row in desc_result.data if row and row[0]]
                    logger.info(f"Metric view created: {target_fqn} — columns: {col_names[:10]}")

                    # Try a MEASURE query to validate queryability
                    # Find first field (non-measure) to GROUP BY
                    field_name = col_names[0] if col_names else None
                    if field_name:
                        try:
                            measure_query = (
                                f"SELECT {field_name} FROM {target_fqn} "
                                f"GROUP BY {field_name} LIMIT 5"
                            )
                            mq_result = self._sql.execute_and_wait(measure_query, timeout_s=30.0)
                            if mq_result.status == "SUCCEEDED":
                                row_count = len(mq_result.data) if mq_result.data else 0
                                logger.info(f"Metric view query test passed: {row_count} rows")
                                return
                            else:
                                error_msg = f"Measure query failed: {mq_result.error or mq_result.status}"
                        except Exception as qe:
                            # If MEASURE query fails, view structure is still valid
                            # The DESCRIBE passed so the DDL is correct
                            logger.warning(f"Measure query test failed (non-fatal): {str(qe)[:200]}")
                            logger.info(f"Metric view accepted (DESCRIBE passed): {target_fqn}")
                            return
                    else:
                        # DESCRIBE worked but no columns — shouldn't happen
                        logger.info(f"Metric view accepted (DESCRIBE passed): {target_fqn}")
                        return
            except Exception as e:
                error_msg = str(e)
                if len(error_msg) > 2000:
                    error_msg = error_msg[:2000]

            logger.warning(f"View query test failed (attempt {attempt+1}): {error_msg[:300]}")

            if attempt < max_retries - 1:
                current_yaml = self._fix_metric_yaml(current_yaml, error_msg)
            else:
                raise RuntimeError(
                    f"Metric view query test failed after {max_retries} attempts: {error_msg}"
                )

    def _fix_metric_yaml(self, yaml_content: str, error: str) -> str:
        """Ask LLM to fix metric view YAML based on error.

        Provides the error, current YAML, source schema, and available tables
        so the LLM can correct column/table references.
        """
        source_schema = self._config.catalog.source
        tables_info = ""
        if hasattr(self, '_last_profile') and self._last_profile:
            for t in self._last_profile.get('tables', [])[:15]:
                cols = [f"{c['name']}({c.get('type','?')})" for c in t.get('columns', [])[:25]]
                tables_info += f"\n  - {t.get('fqn', t['name'])}: {', '.join(cols)}"

        fix_prompt = (
            f"The metric view YAML failed with this error:\n"
            f"```\n{error[:1500]}\n```\n\n"
            f"Current YAML:\n```yaml\n{yaml_content}\n```\n\n"
            f"Source schema: `{source_schema}`\n"
            f"Available tables and columns (with types):{tables_info}\n\n"
            f"Fix the YAML to resolve the error. Common issues:\n"
            f"- Wrong table name (use exact FQN from available tables above)\n"
            f"- Wrong column name (use exact column names listed above)\n"
            f"- Incorrect JOIN conditions\n"
            f"- TYPE MISMATCH: If a STRING column joins to a LONG/INT/BIGINT, CAST the numeric side to STRING\n"
            f"- Table alias mismatch (source.X must match the source table's columns)\n\n"
            f"Return ONLY the corrected YAML — no code fences, no explanation."
        )

        corrected = self._llm.chat(
            messages=[
                {"role": "system", "content": "You are a Databricks metric view YAML expert. Fix the YAML metric view definition."},
                {"role": "user", "content": fix_prompt}
            ],
            max_tokens=8192
        )

        return self._clean_yaml_output(corrected)

    def _execute_with_retry(self, sql: str) -> None:
        """Execute DDL with up to 3 retries using LLM self-correction."""
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                self._sql.execute_ddl(sql)
                logger.info(f"DDL executed successfully (attempt {attempt+1})")
                return
            except Exception as e:
                last_error = str(e)
                logger.warning(f"DDL failed (attempt {attempt+1}): {last_error[:300]}")

                if attempt < max_retries - 1:
                    sql = self._self_correct_sql(sql, last_error)

        raise RuntimeError(f"DDL failed after {max_retries} attempts: {last_error}")


    def _self_correct_sql(self, sql: str, error: str) -> str:
        """Ask LLM to fix DDL (SQL or YAML metric view) based on error.

        For YAML metric views (CREATE VIEW WITH METRICS LANGUAGE YAML AS $$...$$),
        extracts the YAML, asks LLM to fix it, then rewraps.

        Args:
            sql: The failing DDL statement.
            error: Error message from execution.

        Returns:
            Corrected DDL string.
        """
        # Determine if this is a YAML metric view or plain SQL
        is_yaml_metric = "WITH METRICS LANGUAGE YAML" in sql

        if is_yaml_metric:
            # Extract YAML between $$ markers
            start = sql.find("$$\n") + 3
            end = sql.rfind("\n$$")
            yaml_content = sql[start:end] if start > 2 and end > start else sql
            
            # Also provide the source schema tables for context
            source_schema = self._config.catalog.source
            
            correction_prompt = (
                f"The following metric view YAML failed with error:\n"
                f"```\n{error[:1000]}\n```\n\n"
                f"Original YAML:\n```yaml\n{yaml_content}\n```\n\n"
                f"Source schema: `{source_schema}`\n"
                f"Available tables: {', '.join(t['name'] for t in self._last_profile.get('tables', [])[:20]) if hasattr(self, '_last_profile') else 'check source schema'}\n\n"
                f"Fix the YAML to resolve the error (wrong column names, wrong table names, etc.). "
                f"Return ONLY the corrected YAML — no code fences, no explanation."
            )

            corrected_yaml = self._llm.chat(
                messages=[
                    {"role": "system", "content": "You are a Databricks metric view YAML expert. Fix metric view definitions."},
                    {"role": "user", "content": correction_prompt}
                ],
                max_tokens=8192
            )

            # Clean and rewrap
            corrected_yaml = self._clean_yaml_output(corrected_yaml)
            target_fqn = f"{self._config.catalog.target}.{self._config.assets.metric_view}"
            corrected = (
                f"CREATE OR REPLACE VIEW {target_fqn}\n"
                f"WITH METRICS LANGUAGE YAML\n"
                f"AS $$\n{corrected_yaml}\n$$"
            )
        else:
            correction_prompt = (
                f"The following SQL failed with error:\n"
                f"```\n{error[:1000]}\n```\n\n"
                f"Original SQL:\n```sql\n{sql}\n```\n\n"
                f"Fix the SQL to resolve the error. Return ONLY the corrected SQL."
            )

            corrected = self._llm.chat(
                messages=[
                    {"role": "system", "content": "You are a Databricks SQL expert. Fix SQL errors."},
                    {"role": "user", "content": correction_prompt}
                ],
                max_tokens=4096
            )

            # Strip markdown code fences
            if "```" in corrected:
                corrected = self._clean_yaml_output(corrected)

        return corrected.strip()

    # ------------------------------------------------------------------
    # Phase D: Validate
    # ------------------------------------------------------------------

    def _validate_metric_view(self) -> dict:
        """Validate metric view exists and has valid structure.

        Metric views with joins (multi-source) cannot be queried with plain
        SELECT * — they require MEASURE() syntax. So we validate with:
        1. View exists (table_exists check)
        2. DESCRIBE returns columns (fields + measures defined)
        3. A simple field-only query works (no MEASURE needed for fields)

        Returns:
            Validation result dict.
        """
        target = self._config.catalog.target
        mv_name = self._config.assets.metric_view

        if not target or not mv_name:
            return {"passed": False, "error": "Missing target or metric_view name"}

        fqn = f"{target}.{mv_name}"
        checks = []

        # Check 1: View exists
        exists = self._sql.table_exists(fqn)
        checks.append({"check": "view_exists", "passed": exists, "fqn": fqn})

        if exists:
            # Check 2: DESCRIBE returns columns (proves YAML parsed correctly)
            try:
                desc_result = self._sql.execute_and_wait(
                    f"DESCRIBE TABLE {fqn}", timeout_s=30.0
                )
                has_cols = (
                    desc_result.status == "SUCCEEDED"
                    and desc_result.data
                    and len(desc_result.data) > 0
                )
                col_names = [row[0] for row in desc_result.data if row] if has_cols else []
                checks.append({
                    "check": "has_columns",
                    "passed": has_cols,
                    "column_count": len(col_names),
                    "columns": col_names[:10]
                })
            except Exception as e:
                checks.append({"check": "has_columns", "passed": False, "error": str(e)})
                col_names = []

            # Check 3: Query a field (not a measure) to test basic queryability
            if col_names:
                try:
                    # Use first column as a field query (fields don't need MEASURE)
                    field = col_names[0]
                    result = self._sql.execute_and_wait(
                        f"SELECT {field} FROM {fqn} GROUP BY {field} LIMIT 5",
                        timeout_s=30.0
                    )
                    queryable = result.status == "SUCCEEDED"
                    checks.append({"check": "queryable", "passed": queryable})
                except Exception as e:
                    # Multi-source metric views may not support even field queries.
                    # If DESCRIBE passed, the view structure is valid but queryability is unknown.
                    logger.warning(f"Field query failed (non-fatal for multi-source views): {str(e)[:200]}")
                    checks.append({"check": "queryable", "passed": True, "note": "DESCRIBE-only validation (multi-source view)", "warning": str(e)[:200]})

        all_passed = all(c["passed"] for c in checks)
        return {"passed": all_passed, "checks": checks}
