"""LLM layer — Agentic execution engine (Phase 4 architecture).

This module is the core of the agentic architecture. It replicates
Genie Code behavior: load a prompt, give the LLM tools, let it iterate.

Components:
- LLMClient: Foundation Model API wrapper (text, vision, tool-calling)
- AgentLoop: Multi-turn agent loop with tool dispatch and error budget
- ToolExecutor: Pure tool implementations (execute_sql, read/write files,
               import/execute notebooks, create dashboards, Genie spaces)
- PromptLoader: Reads framework prompts from workspace at runtime
- tools: OpenAI function-calling tool definitions

See docs/phase4-agentic-architecture-redesign.md for full reference.
"""

from llm.client import LLMClient, LLMError, LLMTimeoutError, LLMValidationError
from llm.agent_loop import AgentLoop, AgentResult
from llm.tool_executor import ToolExecutor
from llm.prompt_loader import PromptLoader
from llm.tools import TOOL_DEFINITIONS, get_tool_names

__all__ = [
    # Client
    "LLMClient",
    "LLMError",
    "LLMTimeoutError",
    "LLMValidationError",
    # Agent loop
    "AgentLoop",
    "AgentResult",
    # Tools
    "ToolExecutor",
    "TOOL_DEFINITIONS",
    "get_tool_names",
    # Prompts
    "PromptLoader",
]
