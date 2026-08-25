"""PipelineRunner — Central orchestrator for the AI/BI Studio pipeline.

Manages sequential execution of pipeline steps, progress tracking,
error handling, and event emission for real-time UI updates.

Design notes:
    - Steps execute sequentially (each depends on prior outputs)
    - Each step contains multiple phases driven by pipeline_step_phases_config
    - Progress is emitted via callback (supports SSE streaming)
    - Phase-level events (phase_started, phase_completed, phase_failed) for UI
    - Fail-fast: any phase failure stops the step and pipeline
    - LLM self-correction happens WITHIN each step (not here)
    - Cancellation is cooperative (checked between steps)
    - Rerun re-executes the full failed step (no phase-level resume — avoids inconsistent state)

See docs/design_phase2.md Section 4.1 for full reference.
"""

import time
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Models
# ---------------------------------------------------------------------------

class PipelineStatus(str, Enum):
    """Pipeline lifecycle states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Individual step states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PhaseStatus(str, Enum):
    """Individual phase states within a step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PhaseResult:
    """Result of a single phase execution within a step."""
    phase_name: str
    status: PhaseStatus
    duration_ms: int = 0
    artifacts: list = field(default_factory=list)
    error: Optional[str] = None
    error_detail: Optional[str] = None


@dataclass
class StepResult:
    """Result of a single pipeline step execution."""
    step_name: str
    status: StepStatus
    duration_s: float = 0.0
    artifacts: list = field(default_factory=list)  # paths to generated files
    error: Optional[str] = None
    suggestion: Optional[str] = None
    phases: list = field(default_factory=list)  # list[PhaseResult]


@dataclass
class PipelineEvent:
    """Event emitted during pipeline execution for UI streaming."""
    event_type: str  # step_started, step_completed, step_failed, log, pipeline_completed
    data: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class PipelineRun:
    """Full state of a pipeline execution."""
    run_id: str
    domain: str
    status: PipelineStatus = PipelineStatus.PENDING
    current_step: Optional[str] = None
    steps: list = field(default_factory=list)  # list[StepResult]
    events: list = field(default_factory=list)  # list[PipelineEvent]
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_s: float = 0.0
    error: Optional[str] = None
    config: Optional[dict] = None

    def to_dict(self) -> dict:
        """Serialize for API response."""
        return {
            "run_id": self.run_id,
            "domain": self.domain,
            "status": self.status.value,
            "current_step": self.current_step,
            "steps": [
                {
                    "name": s.step_name,
                    "status": s.status.value,
                    "duration_s": s.duration_s,
                    "artifacts": s.artifacts,
                    "error": s.error,
                    "phases": [
                        {
                            "name": p.phase_name,
                            "status": p.status.value,
                            "duration_ms": p.duration_ms,
                            "error": p.error,
                        }
                        for p in s.phases
                    ],
                }
                for s in self.steps
            ],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": self.duration_s,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Pipeline Runner
# ---------------------------------------------------------------------------

class PipelineRunner:
    """Orchestrates the full pipeline execution across all steps.

    Usage:
        runner = PipelineRunner(config, services, llm_client)
        run = runner.run(domain="member_claims", callback=my_sse_emitter)
    """

    # Step registry (order matters)
    STEP_NAMES = [
        "environment_setup",
        "create_data_layer",
        "create_metric_views",
        "create_dashboards",
        "create_genie_space",
        "generate_documentation",
    ]

    def __init__(self, config, services: dict, llm_client, run_store=None):
        """Initialize the pipeline runner.

        Args:
            config: AcceleratorConfig (parsed from accelerator.yaml + databricks.yml).
            services: Dict of service instances keyed by name:
                      {"workspace": WorkspaceService, "sql": SQLService,
                       "lakeview": LakeviewService, "genie": GenieService,
                       "jobs": JobsService}
            llm_client: LLMClient instance for Foundation Model API calls.
            run_store: Optional RunStore instance for phase-level persistence.
                       If provided, enables phase-aware execution and persistence.
        """
        self._config = config
        self._services = services
        self._llm_client = llm_client
        self._run_store = run_store
        self._cancelled = False
        self._steps = self._build_steps()

    def _build_steps(self) -> dict:
        """Lazy-import and instantiate step modules.

        Uses agent-loop-driven steps (AgentStep) which read the framework
        prompt files and execute them via LLM with tools — identical to
        how Genie Code executes the same prompts.

        The EnvironmentSetup step remains non-LLM (pure config resolution).
        DocumentationGenerator also uses the agent loop.
        """
        from orchestrator.environment_setup import EnvironmentSetup
        from orchestrator.agent_step import (
            DataLayerAgentStep,
            MetricViewAgentStep,
            DashboardAgentStep,
            GenieSpaceAgentStep,
            DocumentationAgentStep,
        )

        return {
            "environment_setup": EnvironmentSetup(self._config, self._services),
            "create_data_layer": DataLayerAgentStep(self._config, self._services, self._llm_client),
            "create_metric_views": MetricViewAgentStep(self._config, self._services, self._llm_client),
            "create_dashboards": DashboardAgentStep(self._config, self._services, self._llm_client),
            "create_genie_space": GenieSpaceAgentStep(self._config, self._services, self._llm_client),
            "generate_documentation": DocumentationAgentStep(self._config, self._services, self._llm_client),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        domain: str,
        steps: list = None,
        callback: Callable[[PipelineEvent], None] = None,
        resume_from: Optional[dict] = None,
        run_id: Optional[str] = None,
    ) -> PipelineRun:
        """Execute the full pipeline (or selected steps).

        Args:
            domain: Example domain name (e.g. "member_claims").
            steps: Optional list of step names to execute. If None, runs all.
            callback: Optional function called with each PipelineEvent for
                      real-time progress streaming (SSE).
            resume_from: Optional dict {"step_name": str} to resume from a
                         failed step. Steps before it are skipped (already
                         completed). The resumed step re-runs ALL phases from
                         scratch to avoid inconsistent intermediate state.
            run_id: Optional run_id to reuse (for reruns). If None, generates new UUID.

        Returns:
            PipelineRun with full execution history and results.
        """
        run = PipelineRun(
            run_id=run_id or str(uuid.uuid4()),
            domain=domain,
            status=PipelineStatus.RUNNING,
            started_at=datetime.utcnow().isoformat(),
            config=self._config.to_dict() if hasattr(self._config, "to_dict") else None
        )

        self._cancelled = False
        self._current_run_id = run.run_id
        steps_to_run = steps or self.STEP_NAMES
        total_steps = len(steps_to_run)

        # Build domain context for AgentStep — these paths tell the LLM
        # WHERE to find the ERD image, accelerator.yaml, KPI spec, and templates.
        # Without this, the LLM has no way to locate domain-specific files.
        domain_root = f"{self._config.deploy_root}/kpi_domains/{domain}"
        self._domain_context = {
            "DOMAIN_NAME": domain,
            "DOMAIN_ROOT": domain_root,
            "ACCELERATOR_YAML_PATH": f"{domain_root}/accelerator.yaml",
            "ERD_IMAGE_PATH": f"{domain_root}/inputs/erd.png",
            "KPI_SPEC_PATH": f"{domain_root}/inputs/kpi_spec.md",
            "TEMPLATES_DIR": f"{self._config.framework_root}/templates",
            "DDL_TEMPLATE_PATH": f"{self._config.framework_root}/templates/ddl_notebook.py.template",
            "DBLDATAGEN_TEMPLATE_PATH": f"{self._config.framework_root}/templates/dbldatagen_notebook.py.template",
        }

        # Determine resume step (skip completed steps on rerun)
        resume_step = resume_from.get("step_name") if resume_from else None
        resume_step_reached = (resume_step is None)  # True if no resume = run all

        # Build RESUME_CONTEXT for the LLM if resuming from a prior checkpoint
        self._resume_context = None
        if resume_from:
            self._resume_context = self._build_resume_context(run.run_id, resume_from)

        logger.info(
            f"Pipeline started: run_id={run.run_id}, domain={domain}, "
            f"steps={steps_to_run}, resume_from={resume_from}"
        )

        try:
            for idx, step_name in enumerate(steps_to_run):
                # Check for cancellation
                if self._cancelled:
                    run.status = PipelineStatus.CANCELLED
                    self._emit(callback, "pipeline_cancelled", {"run_id": run.run_id})
                    break

                # Skip unknown steps
                if step_name not in self._steps:
                    logger.warning(f"Unknown step: {step_name}, skipping")
                    continue

                # Skip steps before the resume point
                if not resume_step_reached:
                    if step_name == resume_step:
                        resume_step_reached = True
                    else:
                        # Emit as step_completed (not skipped) so UI shows green
                        # These steps were previously completed in the original run
                        run.steps.append(StepResult(
                            step_name=step_name,
                            status=StepStatus.COMPLETED,
                        ))
                        self._emit(callback, "step_skipped", {
                            "step": step_name,
                            "previously_completed": True,
                        })
                        continue

                # On rerun, always re-execute the full step from scratch.
                # Phase-level resume is intentionally disabled — partial phase
                # outputs may leave data in an inconsistent state.

                # Execute step
                run.current_step = step_name
                self._emit(callback, "step_started", {
                    "step": step_name,
                    "index": idx,
                    "total": total_steps
                })

                step_result = self._execute_step(step_name, callback, resume_from_phase=None)
                run.steps.append(step_result)

                if step_result.status == StepStatus.FAILED:
                    run.status = PipelineStatus.FAILED
                    run.error = step_result.error
                    self._emit(callback, "step_failed", {
                        "step": step_name,
                        "error": step_result.error,
                        "suggestion": step_result.suggestion,
                        "phases": [{"name": p.phase_name, "status": p.status.value, "duration_ms": p.duration_ms} for p in step_result.phases]
                    })
                    break

                self._emit(callback, "step_completed", {
                    "step": step_name,
                    "duration_s": step_result.duration_s,
                    "artifacts": step_result.artifacts,
                    "phases": [{"name": p.phase_name, "status": p.status.value, "duration_ms": p.duration_ms} for p in step_result.phases]
                })

            # Mark completed if not already failed/cancelled
            if run.status == PipelineStatus.RUNNING:
                run.status = PipelineStatus.COMPLETED

        except Exception as e:
            run.status = PipelineStatus.FAILED
            run.error = str(e)
            logger.exception(f"Pipeline unexpected error: {e}")

        # Finalize
        run.completed_at = datetime.utcnow().isoformat()
        run.current_step = None
        if run.started_at:
            start_dt = datetime.fromisoformat(run.started_at)
            end_dt = datetime.fromisoformat(run.completed_at)
            run.duration_s = (end_dt - start_dt).total_seconds()

        self._emit(callback, "pipeline_completed", {
            "run_id": run.run_id,
            "status": run.status.value,
            "duration_s": run.duration_s,
            "error": run.error,
            "steps_completed": len([s for s in run.steps if s.status == StepStatus.COMPLETED])
        })

        logger.info(f"Pipeline {run.status.value}: run_id={run.run_id}, duration={run.duration_s:.1f}s")
        return run

    def cancel(self) -> None:
        """Request cooperative cancellation (checked between steps)."""
        self._cancelled = True
        logger.info("Pipeline cancellation requested")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _execute_step(self, step_name: str, callback,
                      resume_from_phase: Optional[str] = None) -> StepResult:
        """Execute a single step with phase-level tracking.

        On rerun (user clicks Rerun), the entire step re-executes all phases
        from scratch — no phase-level resume, avoids inconsistent state.

        Args:
            step_name: Name of the step to execute.
            callback: SSE event callback.
            resume_from_phase: Phase name to resume from (None = run all).

        Returns:
            StepResult with phase-level detail.
        """
        step = self._steps[step_name]
        start = time.time()
        phase_results = []

        # Get phase config from RunStore, falling back to step's PHASE_HANDLERS
        phases = None
        if self._run_store:
            phases = self._run_store.get_phase_config(step_name)

        # If config table has nothing, derive phases from the step's own PHASE_HANDLERS
        if not phases and hasattr(step, 'PHASE_HANDLERS'):
            handlers = step.PHASE_HANDLERS
            # PHASE_HANDLERS can be a dict {name: method} or list [(name, method)]
            if isinstance(handlers, dict):
                handler_items = list(handlers.items())
            else:
                handler_items = list(handlers)
            phases = [
                {"phase_name": name, "phase_index": i, "phase_label": name.replace('_', ' ').title()}
                for i, (name, _method) in enumerate(handler_items)
            ]

        # Build phase callback that emits SSE events and persists to RunStore
        def phase_callback(phase_name, event, **kwargs):
            if event == "started":
                self._emit(callback, "phase_started", {
                    "step": step_name,
                    "phase": phase_name,
                })
                if self._run_store:
                    self._run_store.update_phase(
                        run_id=self._current_run_id,
                        step_name=step_name,
                        phase_name=phase_name,
                        status="running"
                    )

            elif event == "completed":
                duration_ms = kwargs.get("duration_ms", 0)
                artifacts = kwargs.get("artifacts", [])
                phase_results.append(PhaseResult(
                    phase_name=phase_name,
                    status=PhaseStatus.COMPLETED,
                    duration_ms=duration_ms,
                    artifacts=artifacts,
                ))
                self._emit(callback, "phase_completed", {
                    "step": step_name,
                    "phase": phase_name,
                    "duration_ms": duration_ms,
                })
                if self._run_store:
                    self._run_store.update_phase(
                        run_id=self._current_run_id,
                        step_name=step_name,
                        phase_name=phase_name,
                        status="completed",
                        duration_ms=duration_ms,
                        artifacts=artifacts,
                    )

            elif event == "failed":
                duration_ms = kwargs.get("duration_ms", 0)
                error = kwargs.get("error", "")
                error_detail = kwargs.get("error_detail", "")
                phase_results.append(PhaseResult(
                    phase_name=phase_name,
                    status=PhaseStatus.FAILED,
                    duration_ms=duration_ms,
                    error=error,
                    error_detail=error_detail,
                ))
                self._emit(callback, "phase_failed", {
                    "step": step_name,
                    "phase": phase_name,
                    "duration_ms": duration_ms,
                    "error": error,
                })
                if self._run_store:
                    self._run_store.update_phase(
                        run_id=self._current_run_id,
                        step_name=step_name,
                        phase_name=phase_name,
                        status="failed",
                        duration_ms=duration_ms,
                        error=error,
                        error_detail=error_detail,
                    )

            elif event == "skipped":
                phase_results.append(PhaseResult(
                    phase_name=phase_name,
                    status=PhaseStatus.SKIPPED,
                ))
                self._emit(callback, "phase_skipped", {
                    "step": step_name,
                    "phase": phase_name,
                })
                if self._run_store:
                    self._run_store.update_phase(
                        run_id=self._current_run_id,
                        step_name=step_name,
                        phase_name=phase_name,
                        status="skipped",
                    )

        try:
            self._emit(callback, "log", {
                "level": "info",
                "message": f"Starting step: {step_name}"
            })

            # Create phase records in RunStore if available
            if self._run_store and phases:
                if resume_from_phase:
                    self._run_store.reset_phases_for_rerun(
                        self._current_run_id, step_name, resume_from_phase
                    )
                else:
                    self._run_store.create_phases(
                        self._current_run_id, step_name, phases
                    )

            # Execute step — dispatch by signature type
            if hasattr(step, 'execute') and callable(step.execute):
                import inspect
                sig = inspect.signature(step.execute)
                if 'callback' in sig.parameters and 'extra_context' in sig.parameters:
                    # Phase 4 AgentStep: bridge agent events to SSE queue.
                    # AgentLoop emits: tool_call, tool_result, llm_reasoning, agent_iteration
                    # AgentStep emits: step_started, step_completed, step_failed
                    # UI expects: tool_started, tool_completed, tool_failed, llm_reasoning
                    def agent_event_bridge(event_type, data):
                        d = data if isinstance(data, dict) else {}
                        d["step"] = step_name

                        if event_type == "tool_call":
                            tool_name = d.get("tool", "")
                            # Suppress tool_started for report_progress (UI handles phase_update)
                            if tool_name == "report_progress":
                                return
                            self._emit(callback, "tool_started", {
                                "step": step_name,
                                "tool_name": tool_name,
                                "step_name": tool_name,
                                "args_summary": d.get("args_summary", ""),
                            })
                        elif event_type == "tool_result":
                            tool_name = d.get("tool", "")
                            result_summary = d.get("result_summary", "")

                            # Check if this is a report_progress result
                            if tool_name == "report_progress" and d.get("success", True):
                                # Parse the structured progress JSON and emit as phase_update
                                try:
                                    import json
                                    progress = json.loads(result_summary)
                                    if progress.get("__progress_event__"):
                                        progress.pop("__progress_event__", None)
                                        progress["step"] = step_name
                                        logger.info(f"Emitting phase_update: {progress.get('phase_name')} [{progress.get('status')}]")
                                        self._emit(callback, "phase_update", progress)
                                    else:
                                        logger.warning(f"report_progress result missing __progress_event__ marker: {result_summary[:200]}")
                                except (json.JSONDecodeError, TypeError) as e:
                                    logger.warning(f"Failed to parse report_progress JSON: {e}, raw: {result_summary[:200]}")
                                return  # Don't emit tool_completed for progress reports

                            # Normal tool result handling
                            if d.get("success", True):
                                self._emit(callback, "tool_completed", {
                                    "step": step_name,
                                    "tool_name": tool_name,
                                    "step_name": tool_name,
                                    "duration_ms": d.get("duration_ms", 0),
                                    "result_summary": result_summary[:200],
                                })
                            else:
                                self._emit(callback, "tool_failed", {
                                    "step": step_name,
                                    "tool_name": tool_name,
                                    "step_name": tool_name,
                                    "duration_ms": d.get("duration_ms", 0),
                                    "error": result_summary[:500],
                                })
                        elif event_type == "llm_reasoning":
                            self._emit(callback, "llm_reasoning", d)
                        else:
                            # Pass through other events (step_started, etc.)
                            self._emit(callback, event_type, d)

                    result = step.execute(
                        callback=agent_event_bridge,
                        extra_context=self._domain_context,
                    )
                    # AgentStep returns AgentResult; extract artifacts
                    artifacts = getattr(result, 'artifacts', []) or []
                    if hasattr(result, 'success') and not result.success:
                        raise RuntimeError(result.error or "Agent step failed")
                elif 'phases' in sig.parameters:
                    # Legacy phase-aware step (e.g., EnvironmentSetup)
                    artifacts = step.execute(
                        phases=phases,
                        resume_from_phase=resume_from_phase,
                        phase_callback=phase_callback,
                    )
                else:
                    # Minimal step (no special params)
                    artifacts = step.execute()

            duration = time.time() - start

            return StepResult(
                step_name=step_name,
                status=StepStatus.COMPLETED,
                duration_s=round(duration, 2),
                artifacts=artifacts or [],
                phases=phase_results,
            )

        except Exception as e:
            import traceback
            duration = time.time() - start
            error_msg = str(e)
            suggestion = getattr(e, "suggestion", None)

            logger.error(f"Step {step_name} failed after {duration:.1f}s: {error_msg}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")

            return StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                duration_s=round(duration, 2),
                error=error_msg,
                suggestion=suggestion,
                phases=phase_results,
            )

    def _build_resume_context(self, run_id: str, resume_from: dict) -> dict:
        """Build RESUME_CONTEXT dict for the LLM when resuming from a checkpoint.

        Queries the run_store (Lakebase) for completed phases and their findings,
        constructs a context object that tells the LLM what was already done.

        Args:
            run_id: Current run ID.
            resume_from: Dict with at least {"step_name": str}.

        Returns:
            Dict suitable for injection into agent_loop system message.
        """
        if not self._run_store:
            return None

        try:
            run_data = self._run_store.get_run(run_id)
            if not run_data:
                return None

            # Find last completed step and phase
            completed_steps = []
            all_findings = []
            artifacts_written = []

            steps_data = run_data.get('steps', {})
            for sname, sinfo in steps_data.items():
                if isinstance(sinfo, dict) and sinfo.get('status') == 'completed':
                    completed_steps.append(sname)

            # Collect phase findings from completed phases
            phases_data = run_data.get('phases', {})
            for key, pinfo in phases_data.items():
                if isinstance(pinfo, dict) and pinfo.get('status') == 'completed':
                    findings = pinfo.get('findings')
                    if findings:
                        if isinstance(findings, list):
                            all_findings.extend(findings)
                        elif isinstance(findings, str):
                            all_findings.append(findings)

            # Derive artifacts from step name conventions
            artifact_map = {
                'create_data_layer': [
                    'erd_parsed.yaml', 'semantic_model.yaml',
                    'data_layer_validation.yaml'
                ],
                'create_metric_views': [
                    'schema_profile.yaml', 'kpi_metric_mapping.yaml',
                    'metric_view_design.yaml', 'metric_view_validation.yaml'
                ],
                'create_dashboards': [
                    'dashboard_design.yaml', 'dashboard_dataset_validation.yaml'
                ],
                'create_genie_space': [
                    'genie_semantic_inventory.yaml'
                ],
                'generate_documentation': [
                    'readme.md', 'run_manifest.json'
                ],
            }
            for step in completed_steps:
                artifacts_written.extend(artifact_map.get(step, []))

            last_completed_step = completed_steps[-1] if completed_steps else None
            resume_step = resume_from.get('step_name', '')

            return {
                'run_id': run_id,
                'last_completed_step': last_completed_step,
                'last_completed_phase': None,  # Phase-level resume not yet implemented
                'current_step': f"{resume_step} (restarting from beginning of step)",
                'artifacts_written': artifacts_written,
                'prior_findings': all_findings[:20],  # Cap at 20 to avoid token bloat
            }

        except Exception as e:
            logger.warning(f"Failed to build RESUME_CONTEXT: {e}")
            return None

    def _emit(self, callback, event_type: str, data: dict) -> None:
        """Emit a pipeline event via callback (if provided)."""
        if callback:
            event = PipelineEvent(event_type=event_type, data=data)
            try:
                callback(event)
            except Exception as e:
                logger.warning(f"Event callback error: {e}")
