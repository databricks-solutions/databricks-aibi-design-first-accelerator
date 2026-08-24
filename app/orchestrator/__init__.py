"""Orchestrator layer — Agentic pipeline execution (Phase 4 architecture).

Architecture (see docs/phase4-agentic-architecture-redesign.md):

  PipelineRunner (outer loop)
    → AgentStep per pipeline step (data_layer, metrics, dashboards, genie)
      → AgentLoop (inner multi-turn agent loop with tools)
        → ToolExecutor (pure I/O: execute_sql, read/write files, notebooks, APIs)

Components:
- PipelineRunner: Sequential step orchestration with progress events
- AgentStep: Base class for LLM-driven pipeline steps (loads prompt, runs agent loop)
- ConfigLoader: Parse accelerator.yaml + resolve paths
- VersionResolver: Auto-detect next version suffix
- EventParser: Extract @progress markers from LLM output for UI streaming

DEPRECATED (kept for reference, not used in active flow):
- supervisor.py: Old single-shot supervisor (replaced by pipeline.py + agent_step.py)
- generic_tool_executor.py: Old tool routing (replaced by llm/tool_executor.py)
- stage_agent.py: Old single-shot stage agent (replaced by llm/agent_loop.py)
- step_executor.py: Old phase-based executor (replaced by agent_step.py)
"""

# --- Active architecture (Phase 4) ---
from orchestrator.pipeline import PipelineRunner, PipelineRun, PipelineStatus
from orchestrator.config_loader import ConfigLoader, AcceleratorConfig, ConfigError
from orchestrator.version_resolver import VersionResolver, VersionInfo
from orchestrator.agent_step import (
    AgentStep,
    DataLayerAgentStep,
    MetricViewAgentStep,
    DashboardAgentStep,
    GenieSpaceAgentStep,
    DocumentationAgentStep,
)
from orchestrator.event_parser import parse_event_markers, strip_markers, progress_blocks_to_events

__all__ = [
    # Core pipeline
    "PipelineRunner",
    "PipelineRun",
    "PipelineStatus",
    # Agent steps
    "AgentStep",
    "DataLayerAgentStep",
    "MetricViewAgentStep",
    "DashboardAgentStep",
    "GenieSpaceAgentStep",
    "DocumentationAgentStep",
    # Config
    "ConfigLoader",
    "AcceleratorConfig",
    "ConfigError",
    "VersionResolver",
    "VersionInfo",
    # Events
    "parse_event_markers",
    "strip_markers",
    "progress_blocks_to_events",
]
