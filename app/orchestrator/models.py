"""Data models for the step-tool pipeline architecture.

This module defines the structured types that flow between the orchestrator,
step-tools, and the UI event stream. Each pipeline step (Data Layer, Metric
Views, Dashboards, Genie) is composed of sub-steps that execute sequentially.

The LLM orchestrates *which* step to run and handles error recovery,
but the heavy logic lives in Python inside each step-tool.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import time


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StepStatus(str, Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNRESOLVED = "unresolved"


class FindingType(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


# ---------------------------------------------------------------------------
# Sub-step results
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    """A key decision made during a sub-step (shown in Decisions tab)."""
    title: str
    description: str
    confidence: Confidence
    evidence: list = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class Finding:
    """A discovery or validation result during execution."""
    message: str
    finding_type: FindingType = FindingType.INFO
    details: Optional[str] = None


@dataclass
class SubStepProgress:
    """Progress update from an active sub-step."""
    percent: int = 0  # 0-100
    current_task: str = ""
    what_happening: list = field(default_factory=list)  # List of current activities
    stats: dict = field(default_factory=dict)  # e.g. {"tables_completed": 8, "total_tables": 14}


@dataclass
class SubStepResult:
    """Result of a completed sub-step."""
    status: StepStatus
    summary: str
    elapsed_seconds: float = 0.0
    findings: list = field(default_factory=list)  # List[Finding]
    decisions: list = field(default_factory=list)  # List[Decision]
    artifacts: list = field(default_factory=list)  # List of file paths
    stats: dict = field(default_factory=dict)
    error: Optional[str] = None
    output_data: dict = field(default_factory=dict)  # Structured output for next sub-step


# ---------------------------------------------------------------------------
# Step & Sub-step Definitions
# ---------------------------------------------------------------------------

@dataclass
class SubStepDef:
    """Definition of a sub-step within a pipeline step."""
    id: str  # e.g. "parse_erd"
    name: str  # e.g. "Parse ERD"
    description: str  # e.g. "Reading ERD image and extracting entities"
    order: int


@dataclass
class StepDef:
    """Definition of a top-level pipeline step."""
    id: str  # e.g. "data_layer"
    name: str  # e.g. "Data Layer"
    description: str
    order: int
    sub_steps: list = field(default_factory=list)  # List[SubStepDef]


# ---------------------------------------------------------------------------
# Runtime State
# ---------------------------------------------------------------------------

@dataclass
class SubStepState:
    """Runtime state of a sub-step."""
    definition: SubStepDef
    status: StepStatus = StepStatus.WAITING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[SubStepResult] = None
    progress: Optional[SubStepProgress] = None

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at


@dataclass
class StepState:
    """Runtime state of a top-level step."""
    definition: StepDef
    status: StepStatus = StepStatus.WAITING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    sub_steps: list = field(default_factory=list)  # List[SubStepState]

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def completed_sub_steps(self) -> int:
        return sum(1 for ss in self.sub_steps if ss.status == StepStatus.COMPLETED)

    @property
    def total_sub_steps(self) -> int:
        return len(self.sub_steps)


@dataclass
class PipelineState:
    """Full runtime state of a pipeline run."""
    run_id: str
    domain: str
    status: StepStatus = StepStatus.WAITING
    steps: list = field(default_factory=list)  # List[StepState]
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    events: list = field(default_factory=list)  # Event dicts for UI polling

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def current_step(self) -> Optional[StepState]:
        for step in self.steps:
            if step.status == StepStatus.IN_PROGRESS:
                return step
        return None

    @property
    def progress_percent(self) -> int:
        total = sum(s.total_sub_steps for s in self.steps)
        completed = sum(s.completed_sub_steps for s in self.steps)
        if total == 0:
            return 0
        return int((completed / total) * 100)


# ---------------------------------------------------------------------------
# Pipeline Step Definitions Registry
# ---------------------------------------------------------------------------

DATA_LAYER_SUBSTEPS = [
    SubStepDef(id="parse_erd", name="Parse ERD", description="Reading ERD image and extracting entities", order=1),
    SubStepDef(id="build_semantic_model", name="Build Semantic Model", description="Identifying grains, keys and relationships", order=2),
    SubStepDef(id="generate_ddl", name="Generate DDL", description="Generating Delta table DDL notebooks", order=3),
    SubStepDef(id="generate_synthetic_data", name="Generate Synthetic Data", description="Populating tables with referential integrity", order=4),
    SubStepDef(id="validate_data", name="Validate Data", description="Running data quality and integrity checks", order=5),
    SubStepDef(id="publish_data_layer", name="Publish Data Layer", description="Register tables and update catalog", order=6),
]

METRIC_VIEWS_SUBSTEPS = [
    SubStepDef(id="analyze_kpis", name="Analyze KPIs", description="Mapping KPI spec to table schema", order=1),
    SubStepDef(id="generate_metric_views", name="Generate Metric Views", description="Building CREATE METRIC VIEW statements", order=2),
    SubStepDef(id="execute_metric_views", name="Execute Metric Views", description="Creating metric views in Unity Catalog", order=3),
    SubStepDef(id="validate_metrics", name="Validate Metrics", description="Testing metric view queries", order=4),
]

DASHBOARD_SUBSTEPS = [
    SubStepDef(id="design_layout", name="Design Layout", description="Planning dashboard structure and widgets", order=1),
    SubStepDef(id="generate_dashboard", name="Generate Dashboard", description="Building Lakeview dashboard JSON", order=2),
    SubStepDef(id="create_dashboard", name="Create Dashboard", description="Creating dashboard via API", order=3),
    SubStepDef(id="publish_dashboard", name="Publish Dashboard", description="Publishing dashboard for users", order=4),
]

GENIE_SPACE_SUBSTEPS = [
    SubStepDef(id="generate_instructions", name="Generate Instructions", description="Creating Genie space instructions and sample questions", order=1),
    SubStepDef(id="create_genie_space", name="Create Genie Space", description="Creating Genie space via API", order=2),
]

PIPELINE_STEPS = [
    StepDef(id="config", name="Config", description="Loading and validating configuration", order=1, sub_steps=[]),
    StepDef(id="setup", name="Setup", description="Ensuring schema and prerequisites", order=2, sub_steps=[]),
    StepDef(id="data_layer", name="Data Layer", description="Creating a governed analytical data model", order=3, sub_steps=DATA_LAYER_SUBSTEPS),
    StepDef(id="metrics", name="Metrics", description="Building metric views from KPI spec", order=4, sub_steps=METRIC_VIEWS_SUBSTEPS),
    StepDef(id="dashboards", name="Dashboards", description="Creating Lakeview dashboards", order=5, sub_steps=DASHBOARD_SUBSTEPS),
    StepDef(id="genie", name="Genie", description="Creating Genie data room", order=6, sub_steps=GENIE_SPACE_SUBSTEPS),
    StepDef(id="docs", name="Docs", description="Generating documentation", order=7, sub_steps=[]),
]


def create_pipeline_state(run_id: str, domain: str) -> PipelineState:
    """Create initial pipeline state with all steps in WAITING."""
    steps = []
    for step_def in PIPELINE_STEPS:
        sub_step_states = [
            SubStepState(definition=ss_def)
            for ss_def in step_def.sub_steps
        ]
        steps.append(StepState(definition=step_def, sub_steps=sub_step_states))

    return PipelineState(
        run_id=run_id,
        domain=domain,
        steps=steps,
    )
