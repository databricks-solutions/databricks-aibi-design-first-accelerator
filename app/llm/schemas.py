"""Pydantic schemas for structured LLM output.

These models define the expected JSON structure for each pipeline step's
LLM response. Used with LLMClient.chat_structured() for validated output.

Design notes:
    - All schemas use Pydantic v2 (BaseModel with model_validate)
    - Field descriptions guide the LLM via JSON schema
    - Optional fields have sensible defaults
    - Strict mode ensures exact type matching

See docs/design_phase2.md Section 3.2 for full reference.
"""

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Step 1: ERD Parsing (Vision Model Output)
# ---------------------------------------------------------------------------

class ERDColumn(BaseModel):
    """A column in an ERD table."""
    name: str = Field(description="Column name (snake_case)")
    data_type: str = Field(description="SQL data type (e.g. STRING, INT, DECIMAL(10,2))")
    nullable: bool = Field(default=True, description="Whether column allows NULL")
    description: Optional[str] = Field(default=None, description="Column description")


class ERDForeignKey(BaseModel):
    """A foreign key relationship."""
    column: str = Field(description="Column name in this table")
    references_table: str = Field(description="Referenced table name")
    references_column: str = Field(description="Referenced column name")


class ERDTable(BaseModel):
    """A table extracted from the ERD image."""
    name: str = Field(description="Table name (snake_case)")
    table_type: str = Field(
        default="fact",
        description="Table classification: fact, dimension, bridge, aggregate"
    )
    description: Optional[str] = Field(default=None, description="Table purpose")
    columns: list[ERDColumn] = Field(description="List of columns")
    primary_key: Optional[list[str]] = Field(default=None, description="Primary key column(s)")
    foreign_keys: list[ERDForeignKey] = Field(
        default_factory=list, description="Foreign key relationships"
    )


class ERDRelationship(BaseModel):
    """A relationship between two tables."""
    from_table: str = Field(description="Source table name")
    from_column: str = Field(description="Source column")
    to_table: str = Field(description="Target table name")
    to_column: str = Field(description="Target column")
    cardinality: str = Field(
        default="many-to-one",
        description="Relationship cardinality: one-to-one, one-to-many, many-to-one, many-to-many"
    )


class ParsedERD(BaseModel):
    """Complete ERD parsed from an image (Step 1A output)."""
    tables: list[ERDTable] = Field(description="All tables found in the ERD")
    relationships: list[ERDRelationship] = Field(
        default_factory=list, description="Relationships between tables"
    )
    notes: Optional[str] = Field(
        default=None, description="Any additional observations about the ERD"
    )


# ---------------------------------------------------------------------------
# Step 1: Notebook Generation
# ---------------------------------------------------------------------------

class NotebookCell(BaseModel):
    """A single cell in a generated notebook."""
    cell_type: str = Field(
        default="code",
        description="Cell type: code or markdown"
    )
    language: str = Field(
        default="sql",
        description="Cell language: sql, python, or markdown"
    )
    title: Optional[str] = Field(default=None, description="Cell title/heading")
    source: str = Field(description="Cell source code or markdown content")


class NotebookCells(BaseModel):
    """Generated notebook content (Step 1B/C output)."""
    cells: list[NotebookCell] = Field(description="Ordered list of notebook cells")
    description: Optional[str] = Field(default=None, description="Notebook purpose")


# ---------------------------------------------------------------------------
# Step 2: Metric View Design
# ---------------------------------------------------------------------------

class MetricViewColumn(BaseModel):
    """A column in a metric view definition."""
    name: str = Field(description="Column name")
    expression: str = Field(description="SQL expression for the column")
    column_type: str = Field(
        default="dimension",
        description="Column role: dimension, measure, or time_dimension"
    )
    aggregation: Optional[str] = Field(
        default=None,
        description="Aggregation function for measures (SUM, COUNT, AVG, etc.)"
    )
    description: Optional[str] = Field(default=None, description="Business description")


class MetricViewDefinition(BaseModel):
    """A single metric view definition."""
    name: str = Field(description="View name (snake_case)")
    description: str = Field(description="Business purpose of this metric view")
    source_tables: list[str] = Field(description="Fully qualified source table names")
    create_statement: str = Field(description="Full CREATE OR REPLACE VIEW SQL statement")
    columns: list[MetricViewColumn] = Field(description="Column definitions")


class MetricViewYAML(BaseModel):
    """Metric view design output (Step 2B)."""
    views: list[MetricViewDefinition] = Field(description="All metric view definitions")
    design_notes: Optional[str] = Field(
        default=None, description="Design decisions and tradeoffs"
    )


# ---------------------------------------------------------------------------
# Step 3: Dashboard Design
# ---------------------------------------------------------------------------

class DashboardDataset(BaseModel):
    """A dataset (SQL query) for the dashboard."""
    name: str = Field(description="Dataset identifier (used by widgets)")
    query: str = Field(description="SQL query (should use MEASURE() for aggregations)")


class DashboardWidget(BaseModel):
    """A widget on a dashboard page."""
    name: str = Field(description="Widget title")
    widget_type: str = Field(
        description="Widget type: counter, table, bar, line, area, pie, scatter"
    )
    dataset_name: str = Field(description="Reference to dataset name")
    position: Optional[dict] = Field(default=None, description="Grid position {x, y, width, height}")
    encoding: Optional[dict] = Field(default=None, description="Encoding config (axes, colors)")


class DashboardPage(BaseModel):
    """A page in the dashboard."""
    name: str = Field(description="Page display name")
    widgets: list[DashboardWidget] = Field(description="Widgets on this page")


class DashboardSpec(BaseModel):
    """Lakeview dashboard specification (Step 3B output)."""
    pages: list[DashboardPage] = Field(description="Dashboard pages")
    datasets: list[DashboardDataset] = Field(description="SQL datasets")


# ---------------------------------------------------------------------------
# Step 4: Genie Space Content
# ---------------------------------------------------------------------------

class ExampleSQL(BaseModel):
    """An example SQL query for the Genie space."""
    question: str = Field(description="Natural language question")
    sql: str = Field(description="SQL query that answers the question")


class GenieContent(BaseModel):
    """Genie space configuration content (Step 4A output)."""
    general_instructions: str = Field(
        description="Instructions for the Genie agent (>500 chars, domain-specific guidance)"
    )
    metric_view_descriptions: list[dict] = Field(
        default_factory=list,
        description="Per-table descriptions [{table_name, description}]"
    )
    benchmark_questions: list[str] = Field(
        description="Benchmark questions for quality testing (>= 5)"
    )
    sample_questions: list[str] = Field(
        description="Sample questions shown to users (>= 15)"
    )
    example_sqls: list[ExampleSQL] = Field(
        description="Example SQL queries (>= 15)"
    )


# ---------------------------------------------------------------------------
# Step 5: Documentation
# ---------------------------------------------------------------------------

class AssetReference(BaseModel):
    """Reference to a generated asset."""
    asset_type: str = Field(description="Type: dashboard, metric_view, genie_space, notebook")
    name: str = Field(description="Asset display name")
    identifier: Optional[str] = Field(default=None, description="Asset ID or path")
    url: Optional[str] = Field(default=None, description="Direct URL if available")


class RunSummary(BaseModel):
    """Pipeline run summary (Step 5 output)."""
    title: str = Field(description="Run title (domain + timestamp)")
    domain: str = Field(description="Domain name")
    assets_created: list[AssetReference] = Field(description="All generated assets")
    validation_results: dict = Field(
        default_factory=dict, description="Validation pass/fail per step"
    )
    next_steps: list[str] = Field(
        default_factory=list, description="Suggested next actions"
    )
