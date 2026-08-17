"""LLM layer — Foundation Model API client, schemas, and prompts.

Components:
- LLMClient: Wraps serving_endpoints.query() with retry + structured output
- schemas: Pydantic models for validated LLM responses
- prompts: System/user prompt builders for each pipeline step

See docs/design_phase2.md Section 3 for full reference.
"""

from llm.client import LLMClient, LLMError, LLMTimeoutError, LLMValidationError

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMTimeoutError",
    "LLMValidationError",
]
