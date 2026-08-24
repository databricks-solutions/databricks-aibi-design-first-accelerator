"""Dynamic Tool Parser — Extracts tool definitions from master prompt @tool tags.

Reads the master prompt markdown and parses HTML comment blocks tagged with
`@tool` to dynamically build OpenAI function-calling tool definitions.

This makes the framework generic: the master prompt defines what tools exist,
and different projects/domains can have different tool sets without code changes.

Tag Format (invisible to Genie Code — HTML comments):

    <!-- @tool
    name: parse_erd
    description: Extract schema from ERD image using vision model
    type: vision
    inputs:
      - name: erd_image_path
        type: string
        description: Workspace path to ERD image file
      - name: config_context
        type: string
        description: JSON config context from load_config step
    outputs:
      - name: erd_schema
        type: string
        description: YAML schema extracted from ERD
    -->

Supported tool types:
    - config:  Read/validate configuration files
    - vision:  Call vision model with image input
    - sql:     Generate and execute SQL statements
    - llm:     Focused LLM generation call (SQL, JSON, code)
    - api:     Call external API (Lakeview, Genie, etc.)
    - python:  Execute Python code (dbldatagen, validation)
    - file:    Read/write workspace files
"""

import re
import yaml
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ToolInput:
    """A single input parameter for a tool."""
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True


@dataclass
class ToolOutput:
    """A single output from a tool."""
    name: str
    type: str = "string"
    description: str = ""


@dataclass
class ToolDefinition:
    """Parsed tool definition from a @tool tag."""
    name: str
    description: str
    tool_type: str  # vision, sql, llm, api, python, config, file
    inputs: list = field(default_factory=list)  # List[ToolInput]
    outputs: list = field(default_factory=list)  # List[ToolOutput]
    step_order: int = 0  # Position in pipeline
    step_section: str = ""  # The markdown section this tool belongs to
    prompt_context: str = ""  # The prose instructions following the tag (for internal LLM calls)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Regex to match <!-- @tool ... --> blocks
_TOOL_TAG_PATTERN = re.compile(
    r'<!--\s*@tool\s*\n(.*?)-->',
    re.DOTALL
)

# Regex to match markdown section headers (## or # )
_SECTION_PATTERN = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)


def parse_tools_from_prompt(prompt_content: str) -> list:
    """Parse all @tool tags from a master prompt.

    Args:
        prompt_content: Full markdown content of the master prompt.

    Returns:
        List of ToolDefinition objects in order of appearance.
    """
    tools = []
    order = 0

    for match in _TOOL_TAG_PATTERN.finditer(prompt_content):
        order += 1
        tag_body = match.group(1)
        tag_start = match.start()

        try:
            # Parse YAML content inside the tag
            tag_data = yaml.safe_load(tag_body)
            if not isinstance(tag_data, dict):
                logger.warning(f"@tool tag at position {tag_start} is not a valid YAML dict")
                continue

            # Extract inputs
            inputs = []
            for inp in tag_data.get("inputs", []):
                if isinstance(inp, dict):
                    inputs.append(ToolInput(
                        name=inp.get("name", ""),
                        type=inp.get("type", "string"),
                        description=inp.get("description", ""),
                        required=inp.get("required", True),
                    ))
                elif isinstance(inp, str):
                    inputs.append(ToolInput(name=inp))

            # Extract outputs
            outputs = []
            for out in tag_data.get("outputs", []):
                if isinstance(out, dict):
                    outputs.append(ToolOutput(
                        name=out.get("name", ""),
                        type=out.get("type", "string"),
                        description=out.get("description", ""),
                    ))
                elif isinstance(out, str):
                    outputs.append(ToolOutput(name=out))

            # Find the section header this tool belongs to
            section = _find_enclosing_section(prompt_content, tag_start)

            # Extract prose context after the tag (until next section or next @tool)
            tag_end = match.end()
            prose_context = _extract_prose_context(prompt_content, tag_end)

            tool = ToolDefinition(
                name=tag_data.get("name", f"tool_{order}"),
                description=tag_data.get("description", ""),
                tool_type=tag_data.get("type", "llm"),
                inputs=inputs,
                outputs=outputs,
                step_order=order,
                step_section=section,
                prompt_context=prose_context,
            )
            tools.append(tool)
            logger.info(f"Parsed tool #{order}: {tool.name} (type={tool.tool_type})")

        except yaml.YAMLError as e:
            logger.error(f"Failed to parse @tool tag at position {tag_start}: {e}")
            continue

    logger.info(f"Parsed {len(tools)} tool definitions from master prompt")
    return tools


def tools_to_openai_schema(tools: list) -> list:
    """Convert parsed ToolDefinitions to OpenAI function-calling format.

    Args:
        tools: List of ToolDefinition objects.

    Returns:
        List of dicts in OpenAI tools format, ready for the LLM.
    """
    openai_tools = []

    for tool in tools:
        # Build parameters schema
        properties = {}
        required = []

        for inp in tool.inputs:
            properties[inp.name] = {
                "type": inp.type if inp.type in ("string", "number", "boolean", "array", "object") else "string",
                "description": inp.description or inp.name,
            }
            if inp.required:
                required.append(inp.name)

        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        })

    return openai_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_enclosing_section(content: str, position: int) -> str:
    """Find the nearest markdown section header before a given position."""
    best_section = ""
    for m in _SECTION_PATTERN.finditer(content):
        if m.start() < position:
            best_section = m.group(2).strip()
        else:
            break
    return best_section


def _extract_prose_context(content: str, start_pos: int, max_chars: int = 4000) -> str:
    """Extract prose instructions after a tool tag (until next section or tag).

    This gives the tool executor context about what the tool should do,
    useful for internal LLM calls within the tool.
    """
    # Find next @tool tag or section header
    remaining = content[start_pos:start_pos + max_chars]

    # Stop at next @tool tag
    next_tool = remaining.find('<!-- @tool')
    if next_tool > 0:
        remaining = remaining[:next_tool]

    # Stop at next major section (# or ##)
    next_section = re.search(r'^#{1,2}\s+', remaining, re.MULTILINE)
    if next_section:
        remaining = remaining[:next_section.start()]

    return remaining.strip()


def get_tool_by_name(tools: list, name: str) -> Optional[ToolDefinition]:
    """Look up a tool definition by name."""
    for t in tools:
        if t.name == name:
            return t
    return None


def get_tools_summary(tools: list) -> str:
    """Generate a human-readable summary of available tools."""
    lines = ["Available pipeline tools:"]
    for t in tools:
        lines.append(f"  {t.step_order}. {t.name} [{t.tool_type}] — {t.description}")
    return "\n".join(lines)
