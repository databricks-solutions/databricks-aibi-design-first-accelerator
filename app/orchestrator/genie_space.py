"""GenieSpaceCreator — Step 4: Create Genie Space via template notebook.

Generates the Genie space configuration content via LLM and executes
the configuration notebook to create a fully populated Genie space.

Design notes:
    - Genie spaces are created via a template notebook (not direct API)
    - The notebook template has cells that configure instructions,
      benchmark questions, sample questions, and example SQLs
    - LLM generates the content; template handles API calls
    - Validates: >= min_benchmark_questions, >= 15 sample questions, etc.
    - Phase-aware: execution driven by pipeline_step_phases_config table
    - Supports resume from failed phase without re-running completed phases

See docs/design_phase2.md Section 4.3, prompt 04_create_genie_space.md.
"""

import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class GenieSpaceCreator:
    """Pipeline Step 4: Create and configure a Genie space.

    Phase-aware step. Phases are driven by pipeline_step_phases_config:
        configure_space (0) -> generate content via LLM + populate template notebook
        create_space    (1) -> execute notebook + validate space

    Supports:
        - Phase-level progress events via phase_callback
        - Resume from failed phase (skips completed phases)
        - Context reconstruction from disk artifacts on resume
    """

    # Phase name -> handler method name
    PHASE_HANDLERS = {
        "configure_space": "_phase_configure_space",
        "create_space": "_phase_create_space",
    }

    def __init__(self, config, services: dict, llm_client):
        """Initialize step.

        Args:
            config: AcceleratorConfig.
            services: {"workspace", "sql", "genie", "jobs"} service instances.
            llm_client: LLMClient for model calls.
        """
        self._config = config
        self._ws = services["workspace"]
        self._sql = services["sql"]
        self._genie = services["genie"]
        self._jobs = services["jobs"]
        self._llm = llm_client
        # Inter-phase context (populated during execution or on resume)
        self._ctx = {"genie_content": None, "notebook_path": None, "artifacts": []}

    def execute(self, phases=None, resume_from_phase=None,
                phase_callback: Optional[Callable] = None) -> list:
        """Execute the Genie space creation step.

        Args:
            phases: Ordered list of phase dicts from pipeline_step_phases_config.
                    Falls back to PHASE_HANDLERS keys if None (backward compat).
            resume_from_phase: Phase name to resume from (skips prior phases).
            phase_callback: Callable(phase_name, event, **kwargs) for progress.

        Returns:
            List of artifact paths.
        """
        # Reset context
        self._ctx = {"genie_content": None, "notebook_path": None, "artifacts": []}

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
                if phase_callback:
                    phase_callback(phase_name, "skipped")
                continue

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
        """Rebuild self._ctx from disk artifacts for completed phases."""
        if "configure_space" in completed_phases:
            content_path = f"{self._config.output_folder}/manifests/genie_content.yaml"
            try:
                self._ctx["genie_content"] = self._ws.read_yaml(content_path)
                self._ctx["artifacts"].append(content_path)
                logger.info("Reconstructed genie_content from disk")
            except Exception as e:
                logger.warning(f"Failed to reconstruct genie_content: {e}")

            # Reconstruct notebook path
            notebook_name = self._config.assets.genie_notebook or "04_genie_space_config"
            notebook_path = f"{self._config.output_folder}/notebooks/{notebook_name}"
            if self._ws.file_exists(notebook_path):
                self._ctx["notebook_path"] = notebook_path
                self._ctx["artifacts"].append(notebook_path)
                logger.info(f"Reconstructed notebook_path: {notebook_path}")

    @staticmethod
    def _format_error_detail(exc: Exception) -> str:
        """Format full traceback for error persistence."""
        import traceback
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    # ------------------------------------------------------------------
    # Phase handler methods (called by _run_phase dispatcher)
    # ------------------------------------------------------------------

    def _phase_configure_space(self) -> None:
        """Phase handler: generate content via LLM + populate template notebook."""
        # Generate content
        genie_content = self._generate_content()
        content_path = f"{self._config.output_folder}/manifests/genie_content.yaml"
        self._ws.write_yaml(content_path, genie_content)
        self._ctx["genie_content"] = genie_content
        self._ctx["artifacts"].append(content_path)
        logger.info("Phase configure_space: Genie content generated")

        # Populate template notebook
        notebook_path = self._populate_template(genie_content)
        self._ctx["notebook_path"] = notebook_path
        self._ctx["artifacts"].append(notebook_path)
        logger.info(f"Phase configure_space: Template populated at {notebook_path}")

    def _phase_create_space(self) -> None:
        """Phase handler: execute notebook + validate space."""
        notebook_path = self._ctx["notebook_path"]
        if not notebook_path:
            raise RuntimeError(
                "Cannot create space — notebook_path not available. "
                "Ensure configure_space phase completed first."
            )

        # Execute notebook
        result = self._jobs.run_and_wait(notebook_path, timeout_s=300.0, language="PYTHON")
        if result.result_state != "SUCCESS":
            raise RuntimeError(
                f"Genie notebook execution failed: state={result.result_state}, "
                f"error={result.error}"
            )
        logger.info("Phase create_space: Genie notebook executed successfully")

        # Try to extract space_id from notebook exit value (most reliable)
        notebook_space_id = None
        if result.output:
            import json as _json
            try:
                output = _json.loads(result.output)
                notebook_space_id = output.get("space_id")
                logger.info(f"Phase create_space: Got space_id from notebook: {notebook_space_id}")
            except (ValueError, TypeError, AttributeError):
                logger.debug("Could not parse notebook exit output as JSON")

        # Validate — use notebook output if available, fall back to title search
        validation = self._validate_space(space_id=notebook_space_id)
        if validation.get("passed"):
            logger.info("Phase create_space: Validation passed")
        else:
            issues = validation.get('issues', [])
            # Space not found is a hard failure; content quality issues are warnings
            not_found = [i for i in issues if "not found" in i.lower()]
            if not_found:
                raise RuntimeError(
                    f"Genie space creation failed — space not found after notebook execution. "
                    f"Issues: {issues}"
                )
            logger.warning(f"Phase create_space: Validation issues (non-fatal): {issues}")

    # ------------------------------------------------------------------
    # Phase A: Generate Content
    # ------------------------------------------------------------------

    def _generate_content(self) -> dict:
        """Generate Genie space content via LLM.

        Returns:
            Dict with general_instructions, metric_view_descriptions,
            benchmark_questions, sample_questions, example_sqls.
        """
        # Load inputs
        kpi_spec = self._ws.read_file(f"{self._config.inputs_dir}/kpi_spec.md")

        # Read Genie space configuration guide (per 04_create_genie_space.md)
        genie_guide = ""
        try:
            genie_guide = self._ws.read_file(
                f"{self._config.framework_root}/inputs/genie_space_configuration.md"
            )
        except Exception:
            logger.debug("genie_space_configuration.md not found — continuing without it")

        # Read schema profile (output of Step 2)
        profile_path = f"{self._config.output_folder}/schema_profile.yaml"
        schema_profile = {}
        if self._ws.file_exists(profile_path):
            schema_profile = self._ws.read_yaml(profile_path)

        # Read the framework prompt as system message
        system_prompt = self._ws.read_file(
            f"{self._config.framework_root}/prompts/04_create_genie_space.md"
        )

        metric_view_fqn = f"{self._config.catalog.target}.{self._config.assets.metric_view}"
        import yaml as _yaml
        profile_str = _yaml.dump(schema_profile, default_flow_style=False) if schema_profile else ""

        # Build user message with all runtime context
        user_msg = (
            f"## Runtime Context\n\n"
            f"**Domain:** {self._config.domain_name}\n"
            f"**Metric view FQN:** `{metric_view_fqn}`\n"
            f"**Genie space name:** `{self._config.assets.genie_space}`\n\n"
            f"## Genie Space Configuration Guide\n\n{genie_guide}\n\n"
            f"## KPI Specification\n\n{kpi_spec}\n\n"
            f"## Schema Profile\n\n```yaml\n{profile_str}\n```\n\n"
            f"Generate the Genie space configuration YAML. Return ONLY valid YAML — "
            f"no markdown fences, no backticks, no explanation."
        )

        # Retry loop: generate → parse → fix on error (up to 3 attempts)
        import yaml
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            response = self._llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                max_tokens=8192
            )

            try:
                clean = self._extract_yaml_content(response)
                result = yaml.safe_load(clean)
                if not isinstance(result, dict):
                    raise ValueError(f"Expected dict, got {type(result).__name__}")
                return result
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Genie content generation failed (attempt {attempt+1}/{max_retries}): {last_error[:200]}")
                # Feed error back to LLM on next iteration
                user_msg += (
                    f"\n\nYour previous response caused an error: {last_error}\n"
                    f"Fix the issue. Return ONLY valid YAML — no code fences, no backticks, no prose."
                )

        raise RuntimeError(f"Genie content generation failed after {max_retries} attempts: {last_error}")

    def _extract_yaml_content(self, response: str) -> str:
        """Extract YAML from LLM response, stripping fences and prose."""
        clean = response.strip()
        if "```" in clean:
            lines = clean.split("\n")
            start_idx = None
            end_idx = None
            for i, line in enumerate(lines):
                if line.strip().startswith("```") and start_idx is None:
                    start_idx = i + 1
                elif line.strip().startswith("```") and start_idx is not None:
                    end_idx = i
                    break
            if start_idx is not None:
                end_idx = end_idx or len(lines)
                clean = "\n".join(lines[start_idx:end_idx])
        return clean

    # ------------------------------------------------------------------
    # Phase B: Populate Template
    # ------------------------------------------------------------------

    def _populate_template(self, genie_content: dict) -> str:
        """Fill Genie space template notebook with generated content.

        Args:
            genie_content: Generated content dict.

        Returns:
            Workspace path of the populated notebook.
        """
        # Read template
        template_path = (
            f"{self._config.framework_root}/templates/genie_space_notebook.py.template"
        )
        template = self._ws.read_file(template_path)

        # Replace placeholders
        import json
        metric_view_fqn = f"{self._config.catalog.target}.{self._config.assets.metric_view}"

        # Navigate YAML structure — LLM generates content in varying structures:
        #   1. Nested under 'genie_space' key
        #   2. Directly at root level
        #   3. Under 'configuration' key (most common in recent outputs)
        # Handle all structures robustly.
        space_cfg = genie_content.get("genie_space", {})
        config_cfg = genie_content.get("configuration", {})

        def _get(key, default=None):
            """Try space_cfg, then configuration, then root-level genie_content."""
            val = space_cfg.get(key)
            if val is not None:
                return val
            val = config_cfg.get(key)
            if val is not None:
                return val
            val = genie_content.get(key)
            if val is not None:
                return val
            return default

        # Build metric_view_descriptions dict
        mv_descriptions = _get("metric_view_descriptions", {})
        if not mv_descriptions:
            mv_descriptions = {
                metric_view_fqn: f"Primary metric view for {self._config.domain_name} analytics"
            }

        # Build space description — LLM uses varying key names:
        # 'space_description', 'description', or nested under 'space.description'
        space_description = _get("space_description", "") or _get("description", "")
        if not space_description:
            # Try nested 'space' key (LLM sometimes puts it there)
            space_block = genie_content.get("space", {})
            if isinstance(space_block, dict):
                space_description = space_block.get("description", "")
            # Also try assets.genie.space_description
            assets_genie = genie_content.get("assets", {}).get("genie", {})
            if not space_description and isinstance(assets_genie, dict):
                space_description = assets_genie.get("space_description", "")
        if not space_description:
            space_description = f"Analytics space for {self._config.domain_name} domain powered by metric views."

        # Determine parent path for space creation
        parent_path = getattr(self._config, 'output_folder', '') or f"/Users/{self._config.user_name}"

        # Convert example_question_sqls from [{question, sql}] dicts to [[q, sql]] tuples
        raw_examples = _get("example_question_sqls", [])
        example_tuples = []
        for item in raw_examples:
            if isinstance(item, dict):
                example_tuples.append([item.get("question", ""), item.get("sql", "")])
            elif isinstance(item, (list, tuple)):
                example_tuples.append(list(item))

        # Convert benchmark_questions from [{question, sql}] dicts to [[q, sql]] tuples
        raw_benchmarks = _get("benchmark_questions", [])
        benchmark_tuples = []
        for item in raw_benchmarks:
            if isinstance(item, dict):
                benchmark_tuples.append([item.get("question", ""), item.get("sql", "")])
            elif isinstance(item, (list, tuple)):
                benchmark_tuples.append(list(item))

        # Sample questions are plain strings
        sample_questions = _get("sample_questions", [])

        # General instructions
        general_instructions = _get("general_instructions", "")

        logger.info(
            f"Template population: description={len(space_description)} chars, "
            f"instructions={len(general_instructions)} chars, "
            f"samples={len(sample_questions)}, examples={len(example_tuples)}, "
            f"benchmarks={len(benchmark_tuples)}"
        )

        replacements = {
            "{{DOMAIN_NAME}}": self._config.domain_name,
            "{{SPACE_TITLE}}": self._resolve_space_title(),
            "{{SPACE_DESCRIPTION}}": space_description,
            "{{WAREHOUSE_ID}}": self._config.sql_warehouse_id,
            "{{PARENT_PATH}}": parent_path,
            "{{TABLE_IDENTIFIERS}}": json.dumps([metric_view_fqn]),
            "{{GENERAL_INSTRUCTIONS}}": general_instructions,
            "{{METRIC_VIEW_DESCRIPTIONS}}": json.dumps(mv_descriptions),
            "{{BENCHMARK_QUESTIONS}}": json.dumps(benchmark_tuples),
            "{{SAMPLE_QUESTIONS}}": json.dumps(sample_questions),
            "{{EXAMPLE_SQLS}}": json.dumps(example_tuples),
        }

        notebook_content = template
        for placeholder, value in replacements.items():
            notebook_content = notebook_content.replace(placeholder, value)

        # Write notebook
        notebook_name = self._config.assets.genie_notebook or "04_genie_space_config"
        notebook_path = f"{self._config.output_folder}/notebooks/{notebook_name}"
        self._ws.import_notebook(notebook_path, notebook_content, language="PYTHON")

        return notebook_path

    # ------------------------------------------------------------------
    # Phase D: Validate
    # ------------------------------------------------------------------

    def _validate_space(self, space_id: str = None) -> dict:
        """Validate the created Genie space has required content.

        Args:
            space_id: If provided, skip title search and use this ID directly.

        Returns:
            Validation dict with passed/issues.
        """
        title = self._resolve_space_title()
        issues = []

        if space_id:
            # Notebook gave us the space_id directly — trust it
            logger.info(f"Validating space by ID: {space_id}")
        else:
            # Fall back to title search with retry (eventual consistency)
            space = None
            for attempt in range(5):
                space = self._genie.find_by_title(title)
                if space:
                    space_id = space.space_id
                    break
                logger.info(f"Space not found yet (attempt {attempt+1}/5), waiting 5s...")
                time.sleep(5)

            if not space:
                issues.append(f"Genie space not found with title: {title}")
                return {"passed": False, "issues": issues}

        # Content file validation (from genie_content.yaml)
        content_path = f"{self._config.output_folder}/manifests/genie_content.yaml"
        if self._ws.file_exists(content_path):
            content = self._ws.read_yaml(content_path)
            benchmarks = content.get("benchmark_questions", [])
            samples = content.get("sample_questions", [])
            sqls = content.get("example_sqls", [])
            instructions = content.get("general_instructions", "")

            if len(benchmarks) < 5:
                issues.append(f"Too few benchmark questions: {len(benchmarks)} (min 5)")
            if len(samples) < 15:
                issues.append(f"Too few sample questions: {len(samples)} (min 15)")
            if len(sqls) < 15:
                issues.append(f"Too few example SQLs: {len(sqls)} (min 15)")
            if len(instructions) < 500:
                issues.append(f"Instructions too short: {len(instructions)} chars (min 500)")

        return {"passed": len(issues) == 0, "issues": issues, "space_id": space_id}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_space_title(self) -> str:
        """Build Genie space title."""
        base = self._config.assets.genie_space or f"{self._config.domain_name}_genie"
        if self._config.short_name:
            return f"{base}_{self._config.short_name}"
        return base
