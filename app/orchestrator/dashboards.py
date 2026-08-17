"""DashboardCreator — Step 3: Metric Views -> Lakeview Dashboards.

Creates AI/BI Lakeview dashboards from metric view profiles:
    Phase A: Profile metric view(s) to understand available measures/dimensions
    Phase B: Generate dashboard spec via LLM (datasets, pages, widgets)
    Phase C: Create dashboard via Lakeview API and publish

Design notes:
    - Uses the Lakeview REST API (not CLI notebooks)
    - Dashboard spec is the serialized JSON (pages, widgets, datasets)
    - LLM maps KPIs to appropriate chart types (bar, line, stat, table)
    - Follows lakeview_dashboard_api.md guidance for widget encoding
    - Phase-aware: execution driven by pipeline_step_phases_config table
    - Supports resume from failed phase without re-running completed phases

See docs/design_phase2.md Section 4.3, prompt 03_create_dashboards.md.
"""

import json
import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class DashboardCreator:
    """Pipeline Step 3: Create Lakeview dashboards.

    Phase-aware step. Phases are driven by pipeline_step_phases_config:
        design_layout     (0) -> profile metric views, plan layout
        generate_dashboard (1) -> generate spec JSON via LLM, test SQL
        publish_dashboard  (2) -> create via Lakeview API and publish

    Supports:
        - Phase-level progress events via phase_callback
        - Resume from failed phase (skips completed phases)
        - Context reconstruction from disk artifacts on resume
    """

    # Phase name -> handler method name
    PHASE_HANDLERS = {
        "design_layout": "_phase_design_layout",
        "generate_dashboard": "_phase_generate_dashboard",
        "publish_dashboard": "_phase_publish_dashboard",
    }

    def __init__(self, config, services: dict, llm_client):
        """Initialize step.

        Args:
            config: AcceleratorConfig.
            services: {"workspace", "sql", "lakeview"} service instances.
            llm_client: LLMClient for model calls.
        """
        self._config = config
        self._ws = services["workspace"]
        self._sql = services["sql"]
        self._lakeview = services["lakeview"]
        self._llm = llm_client
        # Inter-phase context (populated during execution or on resume)
        self._ctx = {"mv_profile": None, "dashboard_specs": [], "manifests": [], "artifacts": []}

    def execute(self, phases=None, resume_from_phase=None,
                phase_callback: Optional[Callable] = None) -> list:
        """Execute the dashboard creation step.

        Creates ALL dashboards listed in config.assets.dashboards.
        Each dashboard gets its own spec generation, SQL testing, and publication.

        Args:
            phases: Ordered list of phase dicts from pipeline_step_phases_config.
                    Falls back to PHASE_HANDLERS keys if None (backward compat).
            resume_from_phase: Phase name to resume from (skips prior phases).
            phase_callback: Callable(phase_name, event, **kwargs) for progress.

        Returns:
            List of artifact paths (manifests, spec JSONs).
        """
        # Reset context
        self._ctx = {"mv_profile": None, "dashboard_specs": [], "manifests": [], "artifacts": []}

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
        import yaml

        if "design_layout" in completed_phases:
            profile_path = f"{self._config.output_folder}/mv_profile.yaml"
            try:
                content = self._ws.read_file(profile_path)
                self._ctx["mv_profile"] = yaml.safe_load(content)
                self._ctx["artifacts"].append(profile_path)
                logger.info("Reconstructed mv_profile from disk")
            except Exception as e:
                logger.warning(f"Failed to reconstruct mv_profile: {e}")

        if "generate_dashboard" in completed_phases:
            # Reload dashboard specs from disk
            dashboard_configs = self._config.assets.dashboards or [
                {"id": "main", "name": self._config.assets.dashboard}
            ]
            for dash_config in dashboard_configs:
                dash_name = dash_config.get("name", f"{self._config.domain_name}_{dash_config.get('id', 'main')}_dashboard")
                spec_path = f"{self._config.output_folder}/manifests/{dash_name}_spec.json"
                try:
                    content = self._ws.read_file(spec_path)
                    spec = json.loads(content)
                    self._ctx["dashboard_specs"].append({
                        "spec": spec,
                        "dash_config": dash_config,
                        "spec_path": spec_path,
                    })
                    self._ctx["artifacts"].append(spec_path)
                    logger.info(f"Reconstructed dashboard spec '{dash_name}' from disk")
                except Exception as e:
                    logger.warning(f"Failed to reconstruct spec for '{dash_name}': {e}")

    @staticmethod
    def _format_error_detail(exc: Exception) -> str:
        """Format full traceback for error persistence."""
        import traceback
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    # ------------------------------------------------------------------
    # Phase handler methods (called by _run_phase dispatcher)
    # ------------------------------------------------------------------

    def _phase_design_layout(self) -> None:
        """Phase handler: profile metric views and store in context."""
        mv_profile = self._profile_metric_views()
        self._ctx["mv_profile"] = mv_profile

        # Persist profile for resume
        profile_path = f"{self._config.output_folder}/mv_profile.yaml"
        self._ws.write_yaml(profile_path, mv_profile)
        self._ctx["artifacts"].append(profile_path)
        logger.info(f"Phase design_layout: profiled {len(mv_profile.get('columns', []))} columns")

    def _phase_generate_dashboard(self) -> None:
        """Phase handler: generate dashboard spec(s) + test SQL."""
        mv_profile = self._ctx["mv_profile"]
        if not mv_profile:
            raise RuntimeError(
                "Cannot generate dashboard — mv_profile not available. "
                "Ensure design_layout phase completed first."
            )

        # Determine dashboard list (from config)
        dashboard_configs = self._config.assets.dashboards
        if not dashboard_configs:
            dashboard_configs = [{"id": "main", "name": self._config.assets.dashboard}]

        logger.info(f"Generating {len(dashboard_configs)} dashboard(s): "
                    f"{[d.get('id', d.get('name', '?')) for d in dashboard_configs]}")

        for dash_config in dashboard_configs:
            dash_id = dash_config.get("id", "main")
            dash_name = dash_config.get("name", f"{self._config.domain_name}_{dash_id}_dashboard")
            # Use snake_case name directly (includes version suffix)
            display_name = dash_name

            # Generate spec
            dashboard_spec = self._generate_dashboard_spec(mv_profile, dash_id=dash_id,
                                                            dash_name=display_name)
            spec_path = f"{self._config.output_folder}/manifests/{dash_name}_spec.json"
            self._ws.write_file(spec_path, json.dumps(dashboard_spec, indent=2))
            self._ctx["artifacts"].append(spec_path)

            # Test dataset SQL
            dashboard_spec = self._test_dataset_queries(dashboard_spec)
            logger.info(f"Phase generate_dashboard [{dash_id}]: spec generated, "
                        f"{len(dashboard_spec.get('datasets', []))} datasets tested")

            self._ctx["dashboard_specs"].append({
                "spec": dashboard_spec,
                "dash_config": dash_config,
                "spec_path": spec_path,
            })

    def _phase_publish_dashboard(self) -> None:
        """Phase handler: create and publish all dashboards."""
        if not self._ctx["dashboard_specs"]:
            raise RuntimeError(
                "Cannot publish — no dashboard specs available. "
                "Ensure generate_dashboard phase completed first."
            )

        for entry in self._ctx["dashboard_specs"]:
            dash_config = entry["dash_config"]
            dashboard_spec = entry["spec"]
            dash_id = dash_config.get("id", "main")
            dash_name = dash_config.get("name", f"{self._config.domain_name}_{dash_id}_dashboard")
            # Use snake_case name directly as display name (includes version suffix)
            display_name = dash_name

            dashboard = self._create_and_publish(dashboard_spec, display_name=display_name)
            manifest = {
                "id": dash_id,
                "dashboard_id": dashboard.dashboard_id,
                "display_name": dashboard.display_name,
                "path": dashboard.path,
                "warehouse_id": self._config.sql_warehouse_id,
            }
            self._ctx["manifests"].append(manifest)
            logger.info(f"Phase publish_dashboard [{dash_id}]: published (id={dashboard.dashboard_id})")

        # Write combined manifest
        manifest_path = f"{self._config.output_folder}/manifests/dashboards_manifest.yaml"
        self._ws.write_yaml(manifest_path, {"dashboards": self._ctx["manifests"]})
        self._ctx["artifacts"].append(manifest_path)

    # ------------------------------------------------------------------
    # Phase A: Profile Metric Views
    # ------------------------------------------------------------------

    def _profile_metric_views(self) -> dict:
        """Profile metric view columns (schema only, no data queries).

        Multi-source metric views cannot be queried with SELECT * or COUNT(*).
        We use DESCRIBE to get column info and classify by type.

        Returns:
            Dict with columns, measures, dimensions.
        """
        target = self._config.catalog.target
        mv_name = self._config.assets.metric_view
        fqn = f"{target}.{mv_name}" if target and mv_name else None

        if not fqn:
            raise RuntimeError("Cannot profile: missing catalog.target or assets.metric_view")

        # Use get_table_schema (DESCRIBE) — works on metric views
        columns = self._sql.get_table_schema(fqn)

        # Classify columns as measures vs dimensions by type
        measures = []
        dimensions = []
        for col in columns:
            col_type = col.type.lower()
            if any(t in col_type for t in ["int", "float", "double", "decimal", "bigint"]):
                measures.append(col.name)
            else:
                dimensions.append(col.name)

        return {
            "fqn": fqn,
            "columns": [{"name": c.name, "type": c.type} for c in columns],
            "measures": measures,
            "dimensions": dimensions,
            "sample_rows": [],  # Cannot sample multi-source metric views
            "row_count": -1     # Cannot count multi-source metric views
        }

    # ------------------------------------------------------------------
    # Phase B: Generate Dashboard Spec
    # ------------------------------------------------------------------

    def _generate_dashboard_spec(self, mv_profile: dict, dash_id: str = "main",
                                    dash_name: str = None) -> dict:
        """Generate Lakeview dashboard serialized JSON via LLM.

        Reads framework/prompts/03_create_dashboards.md as system prompt.
        Reads framework/inputs/lakeview_dashboard_api.md as API reference.

        Args:
            mv_profile: Metric view profile from Phase A.
            dash_id: Dashboard identifier from accelerator.yaml (e.g. 'kpis', 'utilization').
            dash_name: Display name for the dashboard.

        Returns:
            Dashboard specification dict (pages, datasets, widgets).
        """
        if not dash_name:
            dash_name = self._resolve_dashboard_name()

        # Read the framework prompt as system message
        system_prompt = self._ws.read_file(
            f"{self._config.framework_root}/prompts/03_create_dashboards.md"
        )

        # Read the Lakeview API reference (mandatory per the prompt)
        lakeview_guide = ""
        try:
            lakeview_guide = self._ws.read_file(
                f"{self._config.framework_root}/inputs/lakeview_dashboard_api.md"
            )
        except Exception as e:
            logger.warning(f"Could not read lakeview_dashboard_api.md: {e}")

        # Read metric view query reference (MEASURE() syntax)
        query_reference = ""
        try:
            query_reference = self._ws.read_file(
                f"{self._config.framework_root}/inputs/metric_view_query_reference.md"
            )
        except Exception:
            logger.debug("metric_view_query_reference.md not found")

        # Read KPI spec for dashboard mapping
        kpi_spec = ""
        try:
            kpi_spec = self._ws.read_file(f"{self._config.inputs_dir}/kpi_spec.md")
        except Exception as e:
            logger.debug(f"No kpi_spec.md found: {e}")

        # Build user message with runtime context
        import json as _json
        fqn = mv_profile.get("fqn", f"{self._config.catalog.target}.{self._config.assets.metric_view}")
        columns = mv_profile.get("columns", [])
        measures = mv_profile.get("measures", [])
        dimensions = mv_profile.get("dimensions", [])

        col_list = "\n".join([f"  - {c['name']} ({c['type']})" for c in columns[:40]])

        user_msg = (
            f"## Runtime Context\n\n"
            f"**Dashboard ID:** `{dash_id}`\n"
            f"**Dashboard display name:** `{dash_name}`\n"
            f"**Metric view FQN:** `{fqn}`\n"
            f"**Warehouse ID:** `{self._config.sql_warehouse_id}`\n\n"
            f"## Lakeview Dashboard API Reference\n\n{lakeview_guide}\n\n"
            f"## How to Query Metric Views (MUST FOLLOW)\n\n{query_reference}\n\n"
            f"## KPI Specification (see Dashboard Mapping section)\n\n{kpi_spec}\n\n"
            f"## Metric View Columns\n\n{col_list}\n\n"
            f"Measures: {', '.join(measures[:15])}\n"
            f"Dimensions: {', '.join(dimensions[:15])}\n\n"
            f"## CRITICAL: Query Syntax for Metric Views\n\n"
            f"This is a multi-source metric view. ALL dataset queries MUST use MEASURE() syntax:\n"
            f"```sql\n"
            f"SELECT dim1, dim2, MEASURE(measure_name) AS alias\n"
            f"FROM {fqn}\n"
            f"GROUP BY dim1, dim2\n"
            f"```\n"
            f"- Dimensions (fields) can be selected directly\n"
            f"- Measures MUST be wrapped in MEASURE(): `MEASURE(total_revenue)`\n"
            f"- Every query with measures MUST have GROUP BY on all non-measure columns\n"
            f"- NEVER use SELECT * — it will fail\n\n"
            f"Generate the `serialized_dashboard` JSON for dashboard ID `{dash_id}` "
            f"named '{dash_name}'. All dataset queries MUST use `{fqn}` as the source table "
            f"with MEASURE() syntax for all measures. "
            f"Return ONLY the raw JSON object — no markdown fences, no explanation."
        )

        last_error = None
        for attempt in range(3):
            response = self._llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                max_tokens=16384
            )

            try:
                spec = self._parse_json_response(response)
                self._validate_dashboard_spec(spec)
                return spec
            except (json.JSONDecodeError, ValueError, RuntimeError) as e:
                last_error = e
                logger.warning(f"Dashboard spec failed (attempt {attempt+1}/3): {e}")
                user_msg += (
                    f"\n\nYour previous response had an error: {e}"
                    f"\nFix the issue and return ONLY the corrected JSON."
                )

        raise RuntimeError(f"Failed to generate valid dashboard spec after 3 attempts: {last_error}")

    def _validate_dashboard_spec(self, spec: dict) -> None:
        """Validate and auto-fix the spec to match Lakeview API requirements.

        Fixes common LLM generation issues:
            - Converts queryLines string to list
            - Removes widgets missing both spec AND multilineTextboxSpec
            - Converts text-like widgets (no queries) to multilineTextboxSpec format
            - Ensures position exists on every layout item
        """
        if not isinstance(spec, dict):
            raise RuntimeError("Spec must be a dict")
        if 'datasets' not in spec:
            raise RuntimeError("Missing 'datasets' key")
        if 'pages' not in spec:
            raise RuntimeError("Missing 'pages' key")

        # Validate/fix datasets
        for ds in spec['datasets']:
            if 'name' not in ds or 'queryLines' not in ds:
                raise RuntimeError(f"Dataset missing name/queryLines: {ds.get('name','?')}")
            if not isinstance(ds['queryLines'], list):
                ds['queryLines'] = [ds['queryLines']]

        # Validate/fix pages and widgets
        for page in spec['pages']:
            if 'layout' not in page:
                page['layout'] = []
                continue
            if not isinstance(page['layout'], list):
                raise RuntimeError(f"Page layout must be a list: {page.get('name','?')}")

            valid_items = []
            for item in page['layout']:
                if 'widget' not in item:
                    continue  # Skip malformed items
                if 'position' not in item:
                    item['position'] = {"x": 0, "y": 0, "width": 6, "height": 2}

                widget = item['widget']

                # Check if widget has required content spec
                has_spec = 'spec' in widget
                has_textbox = 'multilineTextboxSpec' in widget or 'textbox_spec' in widget
                has_image = 'imageSpec' in widget

                if has_spec or has_textbox or has_image:
                    valid_items.append(item)
                elif 'queries' not in widget and not has_spec:
                    # Text widget without multilineTextboxSpec — auto-fix
                    title = widget.get('name', 'Section')
                    widget['multilineTextboxSpec'] = {
                        "lines": [f"## {title}\n"]
                    }
                    # Remove spec if it was set to None or empty
                    widget.pop('spec', None)
                    valid_items.append(item)
                    logger.info(f"Auto-fixed text widget: {widget.get('name')}")
                elif 'queries' in widget and not has_spec:
                    # Chart/counter widget missing spec — skip it
                    logger.warning(
                        f"Dropping widget '{widget.get('name')}' — has queries but no spec"
                    )
                else:
                    logger.warning(
                        f"Dropping widget '{widget.get('name')}' — missing spec/textbox/image"
                    )

            page['layout'] = valid_items

    # ------------------------------------------------------------------
    # Phase C: Create & Publish
    # ------------------------------------------------------------------

    def _create_and_publish(self, dashboard_spec: dict, display_name: str = None) -> object:
        """Create the dashboard via Lakeview API and publish.

        Args:
            dashboard_spec: Serialized dashboard JSON.
            display_name: Optional dashboard display name.

        Returns:
            Dashboard object.
        """
        if not display_name:
            display_name = self._resolve_dashboard_name()

        dashboard = self._lakeview.create_and_publish(
            display_name=display_name,
            warehouse_id=self._config.sql_warehouse_id,
            serialized_dashboard=json.dumps(dashboard_spec),
            parent_path=self._config.output_folder,
            replace_existing=True
        )

        return dashboard

    # ------------------------------------------------------------------
    # Dataset SQL Testing (prompt Step 5)
    # ------------------------------------------------------------------

    def _test_dataset_queries(self, spec: dict) -> dict:
        """Validate dataset queries. Skip metric view queries.

        Multi-source metric views CANNOT be queried via Statement Execution
        API. The Lakeview engine handles them internally. Only test queries
        that do NOT reference the metric view.
        """
        mv_fqn = ""
        try:
            mv_fqn = f"{self._config.catalog.target}.{self._config.assets.metric_view}".lower()
        except Exception:
            pass

        valid_datasets = []
        for ds in spec.get("datasets", []):
            query_lines = ds.get("queryLines", [])
            sql = "".join(query_lines).strip()
            if not sql:
                continue

            sql_lower = sql.lower()

            # Skip metric view queries — Lakeview handles them
            if (mv_fqn and mv_fqn in sql_lower) or "measure(" in sql_lower:
                logger.info(f"Dataset '{ds.get('displayName')}' → metric view (skip test)")
                valid_datasets.append(ds)
                continue

            # Test non-metric-view queries
            try:
                test_sql = sql.rstrip().rstrip(";")
                if "LIMIT" not in test_sql.upper().split("ORDER BY")[-1]:
                    test_sql += " LIMIT 1"
                self._sql.execute_and_wait(test_sql, timeout_s=30.0)
                valid_datasets.append(ds)
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Dataset '{ds.get('displayName')}' failed: {error_msg[:200]}")
                fixed_ds = self._fix_dataset_sql(ds, error_msg)
                if fixed_ds:
                    valid_datasets.append(fixed_ds)
                else:
                    logger.error(f"Dropping dataset '{ds.get('displayName')}'")

        spec["datasets"] = valid_datasets
        return spec


    def _fix_dataset_sql(self, dataset: dict, error: str) -> dict:
        """Attempt to fix a failing dataset SQL via LLM."""
        sql = "".join(dataset.get("queryLines", []))
        fix_prompt = (
            f"This SQL query failed with error:\n{error[:500]}\n\n"
            f"Original SQL:\n{sql}\n\n"
            f"Fix the SQL to resolve the error. Return ONLY the corrected SQL, no explanation."
        )
        try:
            fixed_sql = self._llm.chat(
                messages=[{"role": "user", "content": fix_prompt}],
                max_tokens=2048
            ).strip()
            # Remove code fences if present
            if fixed_sql.startswith("```"):
                lines = fixed_sql.split("\n")
                fixed_sql = "\n".join(lines[1:-1])
            # Test the fix
            test_sql = f"SELECT * FROM ({fixed_sql}) _t LIMIT 1"
            self._sql.execute_and_wait(test_sql)
            dataset["queryLines"] = [fixed_sql]
            return dataset
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_dashboard_name(self) -> str:
        """Build display name for the dashboard."""
        base = self._config.assets.dashboard or f"{self._config.domain_name}_dashboard"
        if self._config.short_name:
            return f"{base}_{self._config.short_name}"
        return base

    @staticmethod
    def _parse_json_response(response: str) -> dict:
        """Extract JSON from LLM response (handles code fences, prose).

        Handles:
            - Raw JSON
            - JSON in ```json ... ``` fences
            - Prose before/after JSON
            - Empty responses (raises ValueError)
        """
        if not response or not response.strip():
            raise ValueError("LLM returned empty response")

        text = response.strip()

        # Remove code fences
        if "```" in text:
            # Find content between first ``` and last ```
            parts = text.split("```")
            if len(parts) >= 3:
                inner = parts[1]
                # Remove language tag on first line (e.g. "json")
                if inner.startswith("json"):
                    inner = inner[4:]
                text = inner.strip()
            else:
                # Single fence pair (opening without closing or vice versa)
                text = text.replace("```json", "").replace("```", "").strip()

        # Try to find JSON object/array boundaries
        start_obj = text.find("{")
        start_arr = text.find("[")
        if start_obj == -1 and start_arr == -1:
            raise ValueError(f"No JSON object or array found in response: {text[:200]}")

        # Use whichever comes first
        if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
            # Object
            start = start_obj
            end = text.rfind("}") + 1
        else:
            # Array
            start = start_arr
            end = text.rfind("]") + 1

        if end <= start:
            raise ValueError(f"Incomplete JSON in response: {text[:200]}")

        json_text = text[start:end]
        return json.loads(json_text)
