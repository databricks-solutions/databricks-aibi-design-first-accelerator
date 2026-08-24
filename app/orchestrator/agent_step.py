"""AgentStep - Base class for agent-loop-driven pipeline steps.

Each pipeline step (data_layer, metric_views, dashboards, genie_space)
now works by:
1. Loading its framework prompt file
2. Running the AgentLoop (LLM + tools)
3. Collecting artifacts

This replaces the previous phase-based approach with one that is
identical to how Genie Code executes the same prompts.
"""

import logging
import time
from typing import Optional, Callable

from llm.agent_loop import AgentLoop, AgentResult
from llm.prompt_loader import PromptLoader
from llm.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


class AgentStep:
    """Base class for agent-loop-driven pipeline steps.

    Subclasses only need to specify:
        - STEP_NAME: which prompt file to load
        - Any pre/post processing overrides

    Usage:
        step = AgentStep(config, services, llm_client, step_name="create_dashboards")
        result = step.execute(callback=my_handler)
    """

    def __init__(self, config, services: dict, llm_client, step_name: str):
        """Initialize an agent step.

        Args:
            config: AcceleratorConfig.
            services: {"workspace", "sql", "lakeview", "genie"} instances.
            llm_client: LLMClient with chat_with_tools support.
            step_name: Pipeline step name (maps to prompt file).
        """
        self._config = config
        self._services = services
        self._llm = llm_client
        self._step_name = step_name

        # Build components
        self._prompt_loader = PromptLoader(
            workspace_service=services["workspace"],
            framework_root=config.framework_root,
        )
        self._tool_executor = ToolExecutor(config, services, llm_client=llm_client)
        self._agent = AgentLoop(llm_client, self._tool_executor, config)

    def execute(
        self,
        callback: Optional[Callable] = None,
        extra_context: Optional[dict] = None,
    ) -> AgentResult:
        """Execute this pipeline step via the agent loop.

        Args:
            callback: Progress callback for UI streaming.
            extra_context: Additional context vars to inject into prompt.

        Returns:
            AgentResult with success, summary, artifacts.
        """
        start_time = time.time()

        # 1. Load the framework prompt
        try:
            prompt_content = self._prompt_loader.load_step_prompt(self._step_name)
        except (FileNotFoundError, ValueError) as e:
            return AgentResult(
                success=False,
                error=f"Failed to load prompt: {e}",
            )

        # 2. Load supplements (e.g. lakeview_dashboard_api.md)
        supplements = self._prompt_loader.load_supplements(self._step_name)

        # 3. Build context variables
        context_vars = self._prompt_loader.build_context_vars(self._config)
        context_vars["STEP_NAME"] = self._step_name
        if extra_context:
            context_vars.update(extra_context)

        # 4. Run the agent loop
        if callback:
            callback("step_started", {
                "step": self._step_name,
                "prompt_size": len(prompt_content),
            })

        result = self._agent.run(
            prompt_content=prompt_content,
            context_vars=context_vars,
            system_supplement=supplements,
            callback=callback,
        )

        duration_s = time.time() - start_time

        if callback:
            callback("step_completed" if result.success else "step_failed", {
                "step": self._step_name,
                "duration_s": round(duration_s, 1),
                "iterations": result.iterations,
                "tool_calls": result.tool_calls_made,
                "success": result.success,
            })

        logger.info(
            f"Step '{self._step_name}' {'completed' if result.success else 'FAILED'} "
            f"in {duration_s:.1f}s ({result.iterations} iterations, "
            f"{result.tool_calls_made} tool calls)"
        )

        return result


# ---------------------------------------------------------------------------
# Concrete step classes (minimal - just specify step_name)
# ---------------------------------------------------------------------------

class DataLayerAgentStep(AgentStep):
    """Step 1: Create data layer from ERD."""
    def __init__(self, config, services, llm_client):
        super().__init__(config, services, llm_client, step_name="create_data_layer")


class MetricViewAgentStep(AgentStep):
    """Step 2: Create metric views."""
    def __init__(self, config, services, llm_client):
        super().__init__(config, services, llm_client, step_name="create_metric_views")


class DashboardAgentStep(AgentStep):
    """Step 3: Create dashboards."""
    def __init__(self, config, services, llm_client):
        super().__init__(config, services, llm_client, step_name="create_dashboards")


class GenieSpaceAgentStep(AgentStep):
    """Step 4: Create Genie space."""
    def __init__(self, config, services, llm_client):
        super().__init__(config, services, llm_client, step_name="create_genie_space")


class DocumentationAgentStep(AgentStep):
    """Step 5: Generate documentation."""
    def __init__(self, config, services, llm_client):
        super().__init__(config, services, llm_client, step_name="generate_documentation")

