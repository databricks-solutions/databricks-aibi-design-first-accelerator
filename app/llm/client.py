"""LLMClient — Foundation Model API wrapper for AI/BI Studio.

Provides text generation, vision, and structured output via Databricks
serving endpoints. Handles retries, rate limiting, and validation.

Design notes:
    - Wraps WorkspaceClient().serving_endpoints.query()
    - Supports structured output (response_format: json_schema)
    - Vision calls use a separate endpoint (Llama 3.2 90B)
    - Rate limit (429): exponential backoff with jitter
    - Validation retry: appends error context and re-prompts

See docs/design_phase2.md Section 3.1 for full reference.
"""

import json
import time
import random
import logging
from typing import Optional, Type

from databricks.sdk import WorkspaceClient
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Base exception for LLM failures."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when an LLM call exceeds the timeout."""
    pass


class LLMValidationError(LLMError):
    """Raised when structured output fails Pydantic validation."""
    def __init__(self, message: str, raw_response: str = ""):
        self.raw_response = raw_response
        super().__init__(message)


class LLMRateLimitError(LLMError):
    """Raised when rate-limited (429) after max retries."""
    pass


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    """Stateless wrapper around Databricks Foundation Model API.

    Usage:
        llm = LLMClient(endpoint_name="databricks-gpt-5-5")
        response = llm.chat([
            {"role": "system", "content": "You are a SQL expert."},
            {"role": "user", "content": "Generate a CREATE VIEW..."}
        ])
    """

    # Rate limit retry config
    RATE_LIMIT_MAX_RETRIES = 5
    RATE_LIMIT_BACKOFF_BASE = 2.0
    RATE_LIMIT_JITTER_MAX = 1.0

    # Track endpoints that reject temperature (class-level cache)
    _endpoints_no_temperature: set = set()

    def __init__(
        self,
        endpoint_name: str = "databricks-gpt-5-5",
        vision_endpoint_name: str = "databricks-gpt-5-5",
        temperature: float = 0.1,
        max_retries: int = 3,
        client: Optional[WorkspaceClient] = None,
    ):
        """Initialize the LLM client.

        Args:
            endpoint_name: Primary text model serving endpoint name.
            vision_endpoint_name: Vision-capable model endpoint name.
            temperature: Generation temperature (lower = more deterministic).
            max_retries: Max retries for validation failures.
            client: Optional pre-configured WorkspaceClient.
        """
        self._endpoint = endpoint_name
        self._vision_endpoint = vision_endpoint_name
        self._temperature = temperature
        self._max_retries = max_retries
        if client:
            self._client = client
        else:
            # Use extended timeout for LLM calls (default 300s is too short
            # for complex generation tasks like synthetic data notebooks)
            from databricks.sdk.config import Config
            import os
            cfg = Config(
                host=os.environ.get('DATABRICKS_HOST', ''),
                http_timeout_seconds=600,  # 10 minutes
            )
            self._client = WorkspaceClient(config=cfg)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Generate text from a chat conversation.

        Args:
            messages: List of {"role": str, "content": str} dicts.
            max_tokens: Maximum tokens in response.
            response_format: Optional JSON schema for structured output.
            temperature: Override default temperature.

        Returns:
            Generated text string.

        Raises:
            LLMError: On unrecoverable failure.
            LLMRateLimitError: If rate-limited after max retries.
        """
        return self._call_endpoint(
            endpoint=self._endpoint,
            messages=messages,
            max_tokens=max_tokens,
            response_format=response_format,
            temperature=temperature or self._temperature,
        )

    # Max pixel dimension for vision API (Claude limit is 8000px)
    # Use 7500 to stay under limit while preserving detail for complex ERDs
    VISION_MAX_DIMENSION = 4096  # Balance detail vs input token cost for reasoning models

    def chat_with_vision(
        self,
        messages: list,
        image_bytes: bytes,
        max_tokens: int = 16384,
    ) -> str:
        """Generate text from image + text input (vision model).

        Args:
            messages: Chat messages (system + user with text prompt).
            image_bytes: Raw image bytes (PNG/JPEG).
            max_tokens: Maximum tokens in response.

        Returns:
            Generated text string describing/parsing the image.

        Raises:
            LLMError: On failure.
        """
        import base64
        import io
        from PIL import Image

        # Resize if any dimension exceeds limit
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        max_dim = self.VISION_MAX_DIMENSION
        if w > max_dim or h > max_dim:
            scale = min(max_dim / w, max_dim / h)
            new_size = (int(w * scale), int(h * scale))
            logger.info(f"Resizing image from {w}x{h} to {new_size[0]}x{new_size[1]}")
            img = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_bytes = buf.getvalue()

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Build multimodal message
        vision_messages = []
        for msg in messages:
            if msg["role"] == "user":
                # Append image to user message
                vision_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": msg["content"]},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                        }
                    ]
                })
            else:
                vision_messages.append(msg)

        return self._call_endpoint(
            endpoint=self._vision_endpoint,
            messages=vision_messages,
            max_tokens=max_tokens,
            temperature=self._temperature,
        )

    def chat_with_tools(
        self,
        messages: list,
        tools: list,
        max_tokens: int = 16384,
        temperature: Optional[float] = None,
    ) -> dict:
        """Generate a response with tool-calling support.

        This is the core method that enables the agent loop pattern.
        The LLM can return tool_calls in its response, which the caller
        executes and feeds back as tool results.

        Args:
            messages: Chat messages (system, user, assistant, tool roles).
            tools: List of tool definitions (OpenAI function-calling format).
            max_tokens: Maximum tokens in response.
            temperature: Override default temperature.

        Returns:
            Dict with keys:
                - content: str (assistant text, may be empty if tool_calls present)
                - tool_calls: list of {id, function: {name, arguments}} dicts
        """
        body = {
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
        }

        temp = temperature or self._temperature
        include_temp = (temp != 1.0) and (self._endpoint not in self._endpoints_no_temperature)

        for attempt in range(self.RATE_LIMIT_MAX_RETRIES):
            try:
                req_body = {**body}
                if include_temp:
                    req_body["temperature"] = temp

                response = self._client.api_client.do(
                    "POST",
                    f"/serving-endpoints/{self._endpoint}/invocations",
                    body=req_body,
                )

                choices = response.get("choices", [])
                if choices:
                    message = choices[0].get("message", {})
                    content = message.get("content", "") or ""
                    tool_calls = message.get("tool_calls", []) or []
                    return {"content": content, "tool_calls": tool_calls}

                return {"content": "", "tool_calls": []}

            except Exception as e:
                error_str = str(e)
                if "unsupported_value" in error_str and "temperature" in error_str:
                    logger.info(
                        f"Endpoint '{self._endpoint}' does not support temperature. "
                        "Cached for future calls."
                    )
                    self._endpoints_no_temperature.add(self._endpoint)
                    include_temp = False
                    continue
                if "429" in error_str or "rate" in error_str.lower():
                    wait = self.RATE_LIMIT_BACKOFF_BASE ** attempt
                    time.sleep(wait)
                    continue
                raise LLMError(f"Tool-calling endpoint error: {e}") from e

        raise LLMRateLimitError("Rate limited after max retries (chat_with_tools)")

    def chat_structured(
        self,
        messages: list,
        schema: Type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel:
        """Generate structured output and parse into Pydantic model.

        Retries with error context if validation fails.

        Args:
            messages: Chat messages.
            schema: Pydantic model class for response validation.
            max_tokens: Maximum tokens.

        Returns:
            Validated Pydantic model instance.

        Raises:
            LLMValidationError: If parsing fails after max_retries.
        """
        # Build JSON schema for response_format
        json_schema = schema.model_json_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": json_schema,
                "strict": True
            }
        }

        current_messages = list(messages)

        for attempt in range(self._max_retries):
            raw = self.chat(
                messages=current_messages,
                max_tokens=max_tokens,
                response_format=response_format,
            )

            try:
                # Parse JSON
                data = json.loads(raw)
                # Validate with Pydantic
                return schema.model_validate(data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(
                    f"Structured output validation failed (attempt {attempt + 1}): {e}"
                )
                if attempt < self._max_retries - 1:
                    # Append error context for self-correction
                    current_messages.append({"role": "assistant", "content": raw})
                    current_messages.append({
                        "role": "user",
                        "content": (
                            f"Your response failed validation: {e}\n"
                            f"Please fix the output to match the schema exactly."
                        )
                    })

        raise LLMValidationError(
            f"Failed to produce valid {schema.__name__} after {self._max_retries} attempts",
            raw_response=raw
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    # Max retries specifically for empty responses
    EMPTY_RESPONSE_MAX_RETRIES = 3
    EMPTY_RESPONSE_WAIT_SECONDS = 5.0

    def _call_endpoint(
        self,
        endpoint: str,
        messages: list,
        max_tokens: int,
        temperature: float = None,
        response_format: Optional[dict] = None,
    ) -> str:
        """Call a serving endpoint with rate-limit retry.

        Uses raw HTTP POST to avoid SDK serialization issues with
        complex message content (e.g. vision multimodal messages).

        Returns:
            Response text content.
        """
        body = {
            "messages": messages,
            "max_tokens": max_tokens,
        }

        # Temperature handling — skip entirely for endpoints known to reject it
        temp = temperature or self._temperature
        include_temp = (temp != 1.0) and (endpoint not in self._endpoints_no_temperature)

        if response_format:
            body["response_format"] = response_format

        # Log prompt size for debugging (handles multimodal content correctly)
        total_prompt_chars = 0
        for m in messages:
            c = m.get("content", "")
            if isinstance(c, str):
                total_prompt_chars += len(c)
            elif isinstance(c, list):
                # Multimodal: list of {type: text/image_url, ...}
                for part in c:
                    if part.get("type") == "text":
                        total_prompt_chars += len(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        total_prompt_chars += 1000  # Estimate for logging
        logger.debug(f"LLM call to '{endpoint}': {len(messages)} messages, ~{total_prompt_chars} prompt chars, max_tokens={max_tokens}")

        for attempt in range(self.RATE_LIMIT_MAX_RETRIES):
            try:
                req_body = {**body}
                if include_temp:
                    req_body["temperature"] = temp

                response = self._client.api_client.do(
                    "POST",
                    f"/serving-endpoints/{endpoint}/invocations",
                    body=req_body,
                )

                # response is a dict from the raw API
                choices = response.get("choices", [])
                if choices:
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason", "")
                    message = choice.get("message", {})
                    content = ""
                    if message:
                        content = message.get("content", "") or ""
                    else:
                        content = choice.get("text", "") or ""

                    # Empty content handling
                    if not content.strip():
                        # If finish_reason='length', the model exhausted output tokens
                        # before producing content. Retrying is futile — same limit applies.
                        if finish_reason == "length":
                            logger.error(
                                f"LLM returned empty content with finish_reason='length'. "
                                f"The model exhausted max_tokens={max_tokens} without producing output. "
                                f"Input may be too large or max_tokens too low. endpoint='{endpoint}', "
                                f"prompt_chars=~{total_prompt_chars}"
                            )
                            raise LLMError(
                                f"Model exhausted output token limit ({max_tokens} tokens) "
                                f"without producing content. The input may be too large "
                                f"for the configured max_tokens."
                            )

                        # Other empty responses (transient) — retry up to 2 times only
                        if attempt < 2:
                            logger.warning(
                                f"LLM returned empty content (attempt {attempt + 1}/3), "
                                f"finish_reason='{finish_reason}', endpoint='{endpoint}'"
                            )
                            time.sleep(2.0)
                            continue
                        # Give up after 2 retries
                        logger.error(f"LLM returned empty content after 3 attempts. Returning empty.")
                        return content

                    # Check if response was truncated (hit token limit)
                    if finish_reason == "length":
                        logger.warning(
                            f"LLM response truncated (finish_reason='length'). "
                            f"Response has {len(content)} chars. Consider increasing max_tokens."
                        )

                    return content

                # Fallback
                predictions = response.get("predictions")
                if predictions:
                    return str(predictions[0])

                logger.warning(f"Unexpected LLM response format: {str(response)[:200]}")
                return str(response)

            except LLMError:
                raise  # Don't catch our own errors

            except Exception as e:
                error_str = str(e)

                # Temperature not supported — cache this permanently, no warning on future calls
                if "unsupported_value" in error_str and "temperature" in error_str:
                    logger.info(
                        f"Endpoint '{endpoint}' does not support temperature parameter. "
                        "Cached — will not attempt temperature on future calls."
                    )
                    self._endpoints_no_temperature.add(endpoint)
                    include_temp = False
                    continue

                # Rate limit handling
                if "429" in error_str or "rate" in error_str.lower():
                    wait = (
                        self.RATE_LIMIT_BACKOFF_BASE ** attempt
                        + random.uniform(0, self.RATE_LIMIT_JITTER_MAX)
                    )
                    logger.warning(
                        f"Rate limited (attempt {attempt + 1}), "
                        f"waiting {wait:.1f}s..."
                    )
                    time.sleep(wait)
                    continue

                # Non-rate-limit error
                raise LLMError(
                    f"Endpoint '{endpoint}' call failed: {error_str}"
                ) from e

        raise LLMRateLimitError(
            f"Rate limited after {self.RATE_LIMIT_MAX_RETRIES} retries on {endpoint}"
        )
