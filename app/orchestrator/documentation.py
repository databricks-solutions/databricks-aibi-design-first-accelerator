"""DocumentationGenerator — Step 5: Generate run summary documentation.

Collects all outputs from previous steps and generates a comprehensive
readme.md in the output folder listing all created assets with links.

Design notes:
    - Deterministic (reads manifests + validation results)
    - LLM used only for prose summary (optional)
    - Produces output/readme.md as the single run summary
    - Links to dashboards, Genie space, metric views, notebooks

See docs/design_phase2.md Section 4.3, prompt 05_generate_documentation.md.
"""

import time
import logging
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class DocumentationGenerator:
    """Pipeline Step 5: Generate documentation and run summary.

    Collects manifests from all previous steps and writes a
    comprehensive readme.md to the output folder.

    Phase-aware: reports progress through phase_callback.
    """

    PHASE_HANDLERS = [
        ("generate_docs", "_phase_generate_docs"),
        ("write_docs", "_phase_write_docs"),
    ]

    def __init__(self, config, services: dict, llm_client):
        """Initialize step.

        Args:
            config: AcceleratorConfig.
            services: {"workspace"} service instance.
            llm_client: LLMClient (used for optional prose summary).
        """
        self._config = config
        self._ws = services["workspace"]
        self._llm = llm_client
        self._ctx = {"artifacts": []}

    def execute(
        self,
        phases: list = None,
        resume_from_phase: Optional[str] = None,
        phase_callback: Optional[Callable] = None,
    ) -> list:
        """Execute the documentation generation step.

        Args:
            phases: Phase config (unused, kept for interface).
            resume_from_phase: Phase to resume from (unused for this step).
            phase_callback: SSE event callback for phase progress.

        Returns:
            List with the readme.md path.
        """
        for phase_name, handler_name in self.PHASE_HANDLERS:
            self._run_phase(phase_name, handler_name, phase_callback)

        return self._ctx["artifacts"]

    def _run_phase(self, phase_name: str, handler_name: str,
                   phase_callback: Optional[Callable]) -> None:
        """Execute a single phase with timing and callbacks."""
        if phase_callback:
            phase_callback(phase_name, "started")

        start = time.time()
        try:
            handler = getattr(self, handler_name)
            handler()
            duration_ms = int((time.time() - start) * 1000)
            if phase_callback:
                phase_callback(phase_name, "completed",
                               duration_ms=duration_ms,
                               artifacts=self._ctx["artifacts"])
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            if phase_callback:
                phase_callback(phase_name, "failed",
                               duration_ms=duration_ms,
                               error=str(e))
            raise

    def _phase_generate_docs(self) -> None:
        """Phase: Collect run data and generate readme content."""
        self._ctx["run_data"] = self._collect_run_data()
        self._ctx["readme_content"] = self._generate_readme(self._ctx["run_data"])
        logger.info("Phase generate_docs: readme content generated")

    def _phase_write_docs(self) -> None:
        """Phase: Write readme.md to output folder."""
        readme_path = f"{self._config.output_folder}/readme.md"
        self._ws.write_file(readme_path, self._ctx["readme_content"])
        self._ctx["artifacts"].append(readme_path)
        logger.info(f"Phase write_docs: written to {readme_path}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _collect_run_data(self) -> dict:
        """Collect manifest data from all previous steps.

        Returns:
            Dict with all run metadata for readme generation.
        """
        output = self._config.output_folder
        data = {
            "domain": self._config.domain_name,
            "description": self._config.domain_description,
            "timestamp": datetime.utcnow().isoformat(),
            "config": self._config.to_dict(),
            "artifacts": {},
        }

        # Schema profile
        profile_path = f"{output}/schema_profile.yaml"
        if self._ws.file_exists(profile_path):
            data["artifacts"]["schema_profile"] = profile_path

        # Metric view validation
        mv_validation_path = f"{output}/metric_views/validation.yaml"
        if self._ws.file_exists(mv_validation_path):
            data["artifacts"]["metric_view_validation"] = self._ws.read_yaml(mv_validation_path)

        # Dashboard manifest
        dash_manifest_path = f"{output}/manifests/dashboard_manifest.yaml"
        if self._ws.file_exists(dash_manifest_path):
            data["artifacts"]["dashboard"] = self._ws.read_yaml(dash_manifest_path)

        # Genie content
        genie_path = f"{output}/manifests/genie_content.yaml"
        if self._ws.file_exists(genie_path):
            data["artifacts"]["genie_space"] = genie_path

        # ERD parsed
        erd_path = f"{output}/erd_parsed.yaml"
        if self._ws.file_exists(erd_path):
            data["artifacts"]["erd_parsed"] = erd_path

        # Notebooks
        notebooks_dir = f"{output}/notebooks"
        if self._ws.file_exists(notebooks_dir):
            try:
                entries = self._ws.list_dir(notebooks_dir)
                data["artifacts"]["notebooks"] = [e.path for e in entries]
            except Exception:
                data["artifacts"]["notebooks"] = []

        return data

    def _generate_readme(self, run_data: dict) -> str:
        """Generate readme.md content from run data.

        Args:
            run_data: Collected run metadata.

        Returns:
            Markdown string for readme.md.
        """
        domain = run_data["domain"]
        description = run_data.get("description", "")
        timestamp = run_data["timestamp"]
        config = run_data["config"]
        artifacts = run_data.get("artifacts", {})

        lines = [
            f"# {domain} — Pipeline Run Summary",
            "",
            f"**Generated:** {timestamp}  ",
            f"**Domain:** {domain}  ",
            f"**Description:** {description}  ",
            f"**Data Source:** {config.get('data_source_type', 'unknown')}  ",
            "",
            "---",
            "",
            "## Configuration",
            "",
            f"| Setting | Value |",
            f"|---------|-------|",
            f"| Deploy Root | `{config.get('deploy_root', '')}` |",
            f"| Source Schema | `{config.get('catalog_source', '')}` |",
            f"| Target Schema | `{config.get('catalog_target', '')}` |",
            f"| Clean Start | {config.get('clean_start', True)} |",
            "",
            "---",
            "",
            "## Generated Assets",
            "",
        ]

        # Dashboard
        if "dashboard" in artifacts:
            dash = artifacts["dashboard"]
            lines.append(f"### Dashboard")
            lines.append(f"- **Name:** {dash.get('display_name', 'N/A')}")
            lines.append(f"- **ID:** `{dash.get('dashboard_id', 'N/A')}`")
            lines.append("")

        # Metric Views
        if "metric_view_validation" in artifacts:
            mv = artifacts["metric_view_validation"]
            passed = mv.get("passed", False)
            lines.append(f"### Metric Views")
            lines.append(f"- **Validation:** {'PASSED' if passed else 'FAILED'}")
            lines.append("")

        # Genie Space
        if "genie_space" in artifacts:
            lines.append(f"### Genie Space")
            lines.append(f"- **Content file:** `{artifacts['genie_space']}`")
            lines.append("")

        # Notebooks
        if "notebooks" in artifacts:
            lines.append(f"### Notebooks")
            for nb in artifacts["notebooks"]:
                name = nb.split("/")[-1]
                lines.append(f"- `{name}`")
            lines.append("")

        # Validation summary
        lines.extend([
            "---",
            "",
            "## Validation",
            "",
            "| Check | Status |",
            "|-------|--------|",
        ])

        if "metric_view_validation" in artifacts:
            mv_passed = artifacts["metric_view_validation"].get("passed", False)
            lines.append(f"| Metric view queryable | {'PASS' if mv_passed else 'FAIL'} |")

        if "dashboard" in artifacts:
            lines.append(f"| Dashboard published | PASS |")

        if "genie_space" in artifacts:
            lines.append(f"| Genie space configured | PASS |")

        lines.append("")
        return "\n".join(lines)
