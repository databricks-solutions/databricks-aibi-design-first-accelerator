"""DataLayerCreator — Step 1: ERD -> DDL + Synthetic Data.

Handles greenfield data layer creation:
    Phase A: Parse ERD image via vision model -> structured tables/relationships
    Phase B: Generate DDL notebook from parsed ERD
    Phase C: Generate synthetic data notebook (dbldatagen)
    Phase D: Execute notebooks and validate tables exist

Brownfield (type=live_schema): This step is skipped entirely.

Design notes:
    - Vision model (Llama 3.2 90B) parses ERD image
    - Primary LLM generates DDL aligned with templates
    - Synthetic data uses dbldatagen for realistic volumes
    - Self-correction: re-prompt on SQL execution errors (up to MAX_RETRIES)
    - Phase-aware: execution driven by pipeline_step_phases_config table
    - Supports resume from failed phase without re-running completed phases

See docs/design_phase2.md Section 4.3, prompt 01_create_data_layer.md.
"""

import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class DataLayerCreator:
    """Pipeline Step 1: Create data layer from ERD.

    Phases:
        A. Parse ERD image -> ParsedERD (vision model)
        B. Generate DDL notebook (primary LLM + template)
        C. Generate synthetic data notebook (primary LLM + template)
        D. Execute notebooks via Jobs API and validate
    """

    def __init__(self, config, services: dict, llm_client):
        """Initialize step.

        Args:
            config: AcceleratorConfig.
            services: {"workspace", "sql", "jobs"} service instances.
            llm_client: LLMClient for model calls.
        """
        self._config = config
        self._ws = services["workspace"]
        self._sql = services["sql"]
        self._jobs = services["jobs"]
        self._llm = llm_client

    # Map phase_name -> handler method name for this step
    PHASE_HANDLERS = {
        "parse_erd": "_parse_erd",
        "generate_ddl": "_generate_ddl_notebook",
        "generate_synthetic": "_generate_synthetic_notebook",
        "execute_validate": "_execute_and_validate",
    }

    def execute(self, phases: Optional[list] = None,
               resume_from_phase: Optional[str] = None,
               phase_callback: Optional[Callable] = None) -> list:
        """Execute the data layer creation step with phase-level tracking.

        Args:
            phases: List of phase config dicts from RunStore.get_phase_config().
                If None, falls back to executing all phases sequentially.
            resume_from_phase: Phase name to resume from (skip earlier phases).
                Previously completed phases are skipped, their artifacts are
                reconstructed from disk.
            phase_callback: Callback for phase lifecycle events.
                Signature: callback(phase_name, event, **kwargs)
                Events: 'started', 'completed', 'failed', 'skipped'
                kwargs for 'completed': duration_ms, artifacts
                kwargs for 'failed': duration_ms, error, error_detail

        Returns:
            List of artifact paths (notebooks, erd_parsed.yaml).

        Raises:
            Exception on unrecoverable failure.
        """
        # Skip for brownfield
        if self._config.data_source.type == "live_schema":
            logger.info("Step 1 skipped: data_source.type=live_schema (brownfield)")
            return []

        if not self._config.data_source.greenfield_enabled:
            logger.info("Step 1 skipped: greenfield.enabled=false")
            return []

        # Phase execution context — carries state between phases
        self._ctx = {
            "parsed_erd": None,
            "artifacts": [],
        }

        # Determine phase list
        if phases is None:
            # Fallback: default phase order (for backward compatibility)
            phases = [
                {"phase_name": "parse_erd", "phase_index": 0, "phase_label": "Parse ERD Image"},
                {"phase_name": "generate_ddl", "phase_index": 1, "phase_label": "Generate DDL Notebook"},
                {"phase_name": "generate_synthetic", "phase_index": 2, "phase_label": "Generate Synthetic Data"},
                {"phase_name": "execute_validate", "phase_index": 3, "phase_label": "Execute & Validate"},
            ]

        # Find resume index
        resume_index = 0
        if resume_from_phase:
            for i, p in enumerate(phases):
                if p["phase_name"] == resume_from_phase:
                    resume_index = i
                    break
            # Reconstruct context from previously completed phases
            self._reconstruct_context(phases[:resume_index])

        # Execute phases
        for i, phase in enumerate(phases):
            phase_name = phase["phase_name"]

            # Skip phases before resume point
            if i < resume_index:
                if phase_callback:
                    phase_callback(phase_name, "skipped")
                continue

            # Skip synthetic if not configured
            if phase_name == "generate_synthetic" and not self._config.data_source.synthetic_data:
                if phase_callback:
                    phase_callback(phase_name, "skipped")
                continue

            # Emit phase started
            if phase_callback:
                phase_callback(phase_name, "started")

            # Execute the phase
            start_ms = time.time() * 1000
            try:
                self._run_phase(phase_name)
                duration_ms = int(time.time() * 1000 - start_ms)
                if phase_callback:
                    phase_callback(phase_name, "completed",
                                   duration_ms=duration_ms,
                                   artifacts=self._ctx["artifacts"])
                logger.info(f"Phase '{phase_name}' completed in {duration_ms}ms")
            except Exception as e:
                duration_ms = int(time.time() * 1000 - start_ms)
                if phase_callback:
                    phase_callback(phase_name, "failed",
                                   duration_ms=duration_ms,
                                   error=str(e),
                                   error_detail=self._format_error_detail(e))
                logger.error(f"Phase '{phase_name}' failed after {duration_ms}ms: {e}")
                raise

        return self._ctx["artifacts"]

    def _run_phase(self, phase_name: str) -> None:
        """Execute a single phase by name, updating self._ctx."""
        if phase_name == "parse_erd":
            parsed_erd = self._parse_erd()
            erd_path = f"{self._config.output_folder}/erd_parsed.yaml"
            self._ws.write_yaml(erd_path, parsed_erd)
            self._ctx["parsed_erd"] = parsed_erd
            self._ctx["artifacts"].append(erd_path)

        elif phase_name == "generate_ddl":
            parsed_erd = self._ctx["parsed_erd"]
            if parsed_erd is None:
                raise RuntimeError("Cannot generate DDL: parsed_erd not available (Phase A must complete first)")
            ddl_path = self._generate_ddl_notebook(parsed_erd)
            self._ctx["artifacts"].append(ddl_path)

        elif phase_name == "generate_synthetic":
            parsed_erd = self._ctx["parsed_erd"]
            if parsed_erd is None:
                raise RuntimeError("Cannot generate synthetic data: parsed_erd not available")
            synth_path = self._generate_synthetic_notebook(parsed_erd)
            self._ctx["artifacts"].append(synth_path)

        elif phase_name == "execute_validate":
            self._execute_and_validate(self._ctx["artifacts"])

        else:
            raise ValueError(f"Unknown phase: {phase_name}")

    def _reconstruct_context(self, completed_phases: list) -> None:
        """Reconstruct phase context from previously completed phases.

        Used on resume to load artifacts/state from prior successful phases
        without re-executing them.
        """
        import yaml

        for phase in completed_phases:
            phase_name = phase["phase_name"]

            if phase_name == "parse_erd":
                # Re-read parsed ERD from disk
                erd_path = f"{self._config.output_folder}/erd_parsed.yaml"
                try:
                    content = self._ws.read_file(erd_path)
                    self._ctx["parsed_erd"] = yaml.safe_load(content)
                    self._ctx["artifacts"].append(erd_path)
                    logger.info(f"Resume: reconstructed parsed_erd from {erd_path}")
                except Exception as e:
                    raise RuntimeError(
                        f"Cannot resume: failed to read prior phase artifact {erd_path}: {e}"
                    ) from e

            elif phase_name == "generate_ddl":
                notebook_name = self._config.assets.ddl_notebook or "01_ddl_create_tables"
                ddl_path = f"{self._config.output_folder}/notebooks/{notebook_name}"
                self._ctx["artifacts"].append(ddl_path)
                logger.info(f"Resume: using existing DDL notebook at {ddl_path}")

            elif phase_name == "generate_synthetic":
                notebook_name = self._config.assets.synthetic_notebook or "02_synthetic_data"
                synth_path = f"{self._config.output_folder}/notebooks/{notebook_name}"
                self._ctx["artifacts"].append(synth_path)
                logger.info(f"Resume: using existing synthetic notebook at {synth_path}")

    @staticmethod
    def _format_error_detail(exc: Exception) -> str:
        """Format exception with traceback for storage."""
        import traceback
        return ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    # ------------------------------------------------------------------
    # Phase A: Parse ERD
    # ------------------------------------------------------------------

    def _parse_erd(self) -> dict:
        """Parse ERD image using vision model.

        Uses a single-pass approach with GPT 5.5 which has strong OCR
        capabilities for reading table names and columns from ERD images.

        Returns:
            Parsed ERD as dict (tables, relationships).
        """
        erd_image_path = f"{self._config.example_dir}/{self._config.data_source.erd_image}"
        image_content = self._ws.read_binary(erd_image_path)

        import yaml
        import re

        def _clean_and_parse_yaml(text):
            """Strip fences and parse YAML."""
            text = text.strip()
            text = re.sub(r'^```(?:yaml|yml)?\s*\n', '', text)
            text = re.sub(r'\n```\s*$', '', text)
            # Remove leading comment lines (e.g., # table_count: 8)
            lines = text.split('\n')
            yaml_start = next(
                (i for i, l in enumerate(lines) if l.strip().startswith('tables:')), 0
            )
            return yaml.safe_load('\n'.join(lines[yaml_start:]))

        # Build prompt
        from llm.prompts import erd_parser_prompt
        system_msg, user_msg = erd_parser_prompt(
            catalog_source=self._config.catalog.source,
            domain_description=self._config.domain_description
        )

        # Call vision model (16K tokens for complex ERDs with many tables/columns)
        result = self._llm.chat_with_vision(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            image_bytes=image_content,
            max_tokens=16384
        )

        if isinstance(result, str):
            try:
                parsed = _clean_and_parse_yaml(result)
            except yaml.YAMLError as e:
                # YAML parsing failed — retry with explicit instruction
                logger.warning(f"ERD YAML parse failed: {e}. Retrying...")
                retry_result = self._llm.chat_with_vision(
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg + "\n\nIMPORTANT: Your previous response had invalid YAML. Return COMPLETE valid YAML for ALL tables. Do not truncate."},
                    ],
                    image_bytes=image_content,
                    max_tokens=16384
                )
                try:
                    parsed = _clean_and_parse_yaml(retry_result)
                except yaml.YAMLError as e2:
                    raise RuntimeError(f"ERD parsing failed after retry: {e2}") from e2
        else:
            parsed = result

        # Log extraction results
        table_count = len(parsed.get('tables', []))
        table_names = [t.get('name', '?') for t in parsed.get('tables', []) if isinstance(t, dict)]
        logger.info(f"ERD extraction: {table_count} tables found: {table_names}")
        if table_count < 3:
            logger.warning("ERD extraction found very few tables — vision model may have missed some")

        return parsed

    # ------------------------------------------------------------------
    # Phase B: Generate DDL
    # ------------------------------------------------------------------

    def _generate_ddl_notebook(self, parsed_erd: dict) -> str:
        """Generate DDL notebook from parsed ERD.

        Args:
            parsed_erd: Output from Phase A.

        Returns:
            Workspace path of the generated notebook.
        """
        # Read template
        template_path = f"{self._config.framework_root}/templates/ddl_notebook.py.template"
        template = self._ws.read_file(template_path)

        # Build prompt
        from llm.prompts import ddl_generator_prompt
        table_suffix = getattr(self._config, 'version_suffix', '') or ''
        system_msg, user_msg = ddl_generator_prompt(
            parsed_erd=parsed_erd,
            template=template,
            target_schema=self._config.catalog.source,
            table_suffix=table_suffix
        )

        # Generate notebook content (16K tokens for complex multi-table schemas)
        notebook_content = self._llm.chat(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            max_tokens=16384
        )

        # Clean LLM output: strip markdown fences and ensure SQL format
        import re
        notebook_content = notebook_content.strip()
        notebook_content = re.sub(r'^```(?:sql)?\s*\n', '', notebook_content)
        notebook_content = re.sub(r'\n```\s*$', '', notebook_content)
        # If LLM returned Python format, convert to SQL format
        if notebook_content.startswith('# Databricks notebook source'):
            notebook_content = notebook_content.replace('# Databricks notebook source', '-- Databricks notebook source')
            notebook_content = notebook_content.replace('# COMMAND ----------', '-- COMMAND ----------')
            # Remove # MAGIC %sql prefixes and # MAGIC prefixes
            notebook_content = re.sub(r'^# MAGIC %sql\s*\n?', '', notebook_content, flags=re.MULTILINE)
            notebook_content = re.sub(r'^# MAGIC ', '', notebook_content, flags=re.MULTILINE)
            notebook_content = re.sub(r'^# DBTITLE', '-- DBTITLE', notebook_content, flags=re.MULTILINE)
        # Ensure it starts with Databricks notebook header
        if not notebook_content.startswith('-- Databricks notebook source'):
            notebook_content = '-- Databricks notebook source\n' + notebook_content

        # Write notebook
        notebook_name = self._config.assets.ddl_notebook or "01_ddl_create_tables"
        notebook_path = f"{self._config.output_folder}/notebooks/{notebook_name}"
        self._ws.import_notebook(notebook_path, notebook_content, language="SQL")

        return notebook_path

    # ------------------------------------------------------------------
    # Phase C: Synthetic Data
    # ------------------------------------------------------------------

    def _generate_synthetic_notebook(self, parsed_erd: dict) -> str:
        """Generate synthetic data notebook using dbldatagen.

        Args:
            parsed_erd: Output from Phase A.

        Returns:
            Workspace path of the generated notebook.
        """
        # Read template
        template_path = f"{self._config.framework_root}/templates/dbldatagen_notebook.py.template"
        template = self._ws.read_file(template_path)

        # Build prompt
        from llm.prompts import synthetic_data_prompt
        table_suffix = getattr(self._config, 'version_suffix', '') or ''
        system_msg, user_msg = synthetic_data_prompt(
            parsed_erd=parsed_erd,
            template=template,
            target_schema=self._config.catalog.source,
            volume_config=self._config.data_source.volume,
            table_suffix=table_suffix
        )

        # Generate notebook content (16K tokens for complex multi-table schemas)
        notebook_content = self._llm.chat(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            max_tokens=16384
        )

        # Clean LLM output: strip markdown fences
        import re
        notebook_content = notebook_content.strip()
        notebook_content = re.sub(r'^```(?:python)?\s*\n', '', notebook_content)
        notebook_content = re.sub(r'\n```\s*$', '', notebook_content)
        notebook_content = notebook_content.strip()

        # Guard: if LLM returned empty or trivial content, retry up to 3 times
        max_gen_retries = 3
        for retry_attempt in range(max_gen_retries):
            if len(notebook_content) >= 100 and 'DataGenerator' in notebook_content:
                break  # Content looks valid
            logger.warning(
                f"Synthetic notebook too short ({len(notebook_content)} chars) or missing DataGenerator. "
                f"Retry {retry_attempt + 1}/{max_gen_retries}..."
            )
            import time
            time.sleep(5 * (retry_attempt + 1))  # Progressive backoff: 5s, 10s, 15s
            notebook_content = self._llm.chat(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg + "\n\nCRITICAL: Return the FULL Python notebook with dbldatagen DataGenerator code for ALL tables. Do NOT return empty or placeholder content."}
                ],
                max_tokens=16384
            )
            notebook_content = notebook_content.strip()
            notebook_content = re.sub(r'^```(?:python)?\s*\n', '', notebook_content)
            notebook_content = re.sub(r'\n```\s*$', '', notebook_content)
            notebook_content = notebook_content.strip()

        if len(notebook_content) < 100:
            raise RuntimeError(
                f"LLM failed to generate synthetic data notebook after {max_gen_retries + 1} attempts "
                f"(only {len(notebook_content)} chars). "
                "Check LLM endpoint availability and token limits."
            )

        # Ensure notebook header
        if not notebook_content.startswith('# Databricks notebook source'):
            notebook_content = '# Databricks notebook source\n' + notebook_content

        # Validate Python syntax before importing
        notebook_content = self._validate_python_notebook(notebook_content, messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ])

        # Write notebook
        notebook_name = self._config.assets.synthetic_notebook or "02_synthetic_data"
        notebook_path = f"{self._config.output_folder}/notebooks/{notebook_name}"
        self._ws.import_notebook(notebook_path, notebook_content, language="PYTHON")

        return notebook_path

    # ------------------------------------------------------------------
    # Phase D: Execute & Validate
    # ------------------------------------------------------------------

    def _validate_python_notebook(self, notebook_content: str, messages: list, max_retries: int = 2) -> str:
        """Validate Python syntax of notebook content. Retry with LLM if invalid.

        Parses each cell independently (cells separated by '# COMMAND ----------').
        If syntax errors found, asks LLM to fix them.

        Args:
            notebook_content: Full notebook source content.
            messages: Original LLM messages (for retry context).
            max_retries: Max correction attempts.

        Returns:
            Valid notebook content (original or corrected).
        """
        import ast

        def _check_syntax(content: str) -> str:
            """Check syntax of notebook cells. Returns error string or empty."""
            cells = content.split('# COMMAND ----------')
            for i, cell in enumerate(cells):
                # Strip notebook markers and magic commands
                code = cell.strip()
                code = '\n'.join(
                    line for line in code.split('\n')
                    if not line.strip().startswith('# Databricks notebook source')
                    and not line.strip().startswith('# DBTITLE')
                    and not line.strip().startswith('# MAGIC')
                    and not line.strip().startswith('%')  # skip magic commands (%pip, %sql, etc.)
                )
                if not code.strip():
                    continue
                try:
                    ast.parse(code)
                except SyntaxError as e:
                    return f"Cell {i+1}, line {e.lineno}: {e.msg}"
            return ""

        # Safety: dbldatagen throws ZeroDivisionError if rows=0
        import re as _re
        notebook_content = _re.sub(r'rows\s*=\s*0\b', 'rows=1000', notebook_content)

        # Safety: dbldatagen TimestampType requires '%Y-%m-%d %H:%M:%S' format
        # Fix date-only begin/end values on lines containing TimestampType
        # Safety: dbldatagen DateType requires '%Y-%m-%d' format ONLY (no time component)
        # LLM sometimes generates begin='2020-01-01 00:00:00' for DateType — strip time part
        # Handles: '2020-01-01 00:00:00', '2020-01-01T00:00:00', '2020-01-01 00:00:00.000'
        # Also handles multi-line withColumn where DateType is on previous line
        fixed_lines = []
        in_datetype_context = False
        for line in notebook_content.split('\n'):
            if 'TimestampType' in line:
                in_datetype_context = False
                line = _re.sub(
                    r"(begin|end)(\s*=\s*)[\"'](\d{4}-\d{2}-\d{2})[\"']",
                    r'\1\2"\3 00:00:00"',
                    line
                )
            elif 'DateType' in line:
                in_datetype_context = True
                # Strip any time component (space/T separator, optional milliseconds)
                line = _re.sub(
                    r"(begin|end)(\s*=\s*)[\"'](\d{4}-\d{2}-\d{2})[T\s][\d:.]+[\"']",
                    r'\1\2"\3"',
                    line
                )
            elif in_datetype_context and ('begin' in line or 'end' in line):
                # Multi-line withColumn: begin/end on line after DateType
                line = _re.sub(
                    r"(begin|end)(\s*=\s*)[\"'](\d{4}-\d{2}-\d{2})[T\s][\d:.]+[\"']",
                    r'\1\2"\3"',
                    line
                )
            elif '.withColumn' in line or '.build()' in line:
                in_datetype_context = False
            fixed_lines.append(line)
        notebook_content = '\n'.join(fixed_lines)

        error = _check_syntax(notebook_content)
        if not error:
            return notebook_content

        logger.warning(f"Syntax error in generated notebook: {error}")

        # Quick fix: try auto-balancing brackets and strings per cell
        cells = notebook_content.split('# COMMAND ----------')
        fixed_cells = []
        for cell in cells:
            # Count unbalanced brackets
            open_parens = cell.count('(') - cell.count(')')
            open_brackets = cell.count('[') - cell.count(']')
            open_braces = cell.count('{') - cell.count('}')
            # Fix unterminated triple-quoted strings
            triple_double = cell.count('"""')
            triple_single = cell.count("'''")
            suffix = ''
            if open_parens > 0 or open_brackets > 0 or open_braces > 0:
                suffix += ')' * max(open_parens, 0) + ']' * max(open_brackets, 0) + '}' * max(open_braces, 0)
            if triple_double % 2 == 1:
                suffix += '"""'
            if triple_single % 2 == 1:
                suffix += "'''"
            # Fix unterminated single-line strings (check last non-empty line)
            cell_lines = cell.rstrip().split('\n')
            if cell_lines:
                last_line = cell_lines[-1]
                # Count unmatched quotes on last line (simple heuristic)
                single_q = last_line.count("\'") - 2 * last_line.count("\\\'")
                double_q = last_line.count('\"') - 2 * last_line.count('\\\"')
                if single_q % 2 == 1:
                    suffix += "\'"
                elif double_q % 2 == 1:
                    suffix += '\"'
            if suffix:
                cell = cell.rstrip() + suffix + '\n'
            fixed_cells.append(cell)
        auto_fixed = '# COMMAND ----------'.join(fixed_cells)

        error = _check_syntax(auto_fixed)
        if not error:
            logger.info("Syntax fixed via auto bracket-balancing")
            return auto_fixed

        notebook_content = auto_fixed  # use partially fixed version for LLM retry

        # Retry: ask LLM to fix
        for attempt in range(max_retries):
            fix_messages = messages + [
                {"role": "assistant", "content": notebook_content},
                {"role": "user", "content": (
                    f"The generated notebook has a Python syntax error: {error}\n"
                    f"Please fix the error and return the complete corrected notebook. "
                    f"Do NOT wrap in code fences."
                )}
            ]
            notebook_content = self._llm.chat(messages=fix_messages, max_tokens=8192)
            # Clean fences again
            import re
            notebook_content = notebook_content.strip()
            notebook_content = re.sub(r'^```(?:python)?\s*\n', '', notebook_content)
            notebook_content = re.sub(r'\n```\s*$', '', notebook_content)
            if not notebook_content.startswith('# Databricks notebook source'):
                notebook_content = '# Databricks notebook source\n' + notebook_content

            error = _check_syntax(notebook_content)
            if not error:
                logger.info(f"Syntax fixed after {attempt + 1} correction(s)")
                return notebook_content
            logger.warning(f"Syntax still invalid (attempt {attempt + 1}): {error}")

        # Return last attempt even if still invalid (will fail at execution with clear error)
        logger.error(f"Could not fix syntax after {max_retries} retries: {error}")
        return notebook_content

    def _patch_notebook_before_execution(self, nb_path: str) -> None:
        """Apply runtime fixes to a saved notebook before executing it.

        Handles the rerun case where a notebook was generated in a prior run
        and contains DateType columns with time components that cause
        ValueError: unconverted data remains.
        """
        import re
        try:
            content = self._ws.read_file(nb_path)
            if not content or 'DateType' not in content:
                return

            original = content
            fixed_lines = []
            in_datetype_ctx = False
            for line in content.split('\n'):
                if 'TimestampType' in line:
                    in_datetype_ctx = False
                elif 'DateType' in line:
                    in_datetype_ctx = True
                    line = re.sub(
                        r"(begin|end)(\s*=\s*)[\"'](\d{4}-\d{2}-\d{2})[T\s][\d:.]+[\"']",
                        r'\1\2"\3"',
                        line
                    )
                elif in_datetype_ctx and ('begin' in line or 'end' in line):
                    line = re.sub(
                        r"(begin|end)(\s*=\s*)[\"'](\d{4}-\d{2}-\d{2})[T\s][\d:.]+[\"']",
                        r'\1\2"\3"',
                        line
                    )
                elif '.withColumn' in line or '.build()' in line:
                    in_datetype_ctx = False
                fixed_lines.append(line)
            content = '\n'.join(fixed_lines)

            if content != original:
                logger.info(f"Patched DateType values in {nb_path} before execution")
                self._ws.import_notebook(nb_path, content, language="PYTHON")
        except Exception as e:
            logger.warning(f"Could not patch notebook {nb_path}: {e}")

    def _execute_and_validate(self, notebook_paths: list) -> None:
        """Execute generated notebooks and validate tables exist.

        Args:
            notebook_paths: List of notebook workspace paths.
        """
        for path in notebook_paths:
            if not path.endswith(".yaml"):  # Skip non-notebook artifacts
                # Detect language from notebook name convention:
                # DDL notebooks (01_ddl_*) are SQL; synthetic/others are Python
                name = path.split("/")[-1].lower()
                if "ddl" in name or name.startswith("01_"):
                    lang = "SQL"
                else:
                    lang = "PYTHON"
                    # Patch known issues before execution (critical for reruns
                    # where the notebook was generated in a prior run)
                    self._patch_notebook_before_execution(path)
                logger.info(f"Executing notebook: {path} (language={lang})")
                result = self._jobs.run_and_wait(path, timeout_s=600.0, language=lang)
                if result.result_state != "SUCCESS":
                    raise RuntimeError(
                        f"Notebook execution failed: {path} "
                        f"(state={result.result_state}, error={result.error})"
                    )

        # Validate: check that expected tables exist
        if self._config.catalog.source:
            logger.info(f"Validating tables in {self._config.catalog.source}...")
            # Simple existence check (detailed validation in Step 2)
            schema_fqn = self._config.catalog.source
            result = self._sql.execute_and_wait(f"SHOW TABLES IN {schema_fqn}")
            table_count = result.row_count
            if table_count == 0:
                raise RuntimeError(
                    f"No tables found in {schema_fqn} after DDL execution"
                )
            logger.info(f"Validation passed: {table_count} tables in {schema_fqn}")

