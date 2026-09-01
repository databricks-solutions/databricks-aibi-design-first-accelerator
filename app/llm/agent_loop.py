"""AgentLoop - Runs framework prompts with tool-calling, identical to Genie Code.

This is the core mechanism that makes the app work exactly like Genie Code:
1. Load a framework prompt file (e.g. 01_create_data_layer.md)
2. Inject context variables (CATALOG, SCHEMA, VERSION_SUFFIX, etc.)
3. Send to LLM with tool definitions
4. LLM returns tool_calls -> execute them -> feed results back
5. Loop until LLM calls report_step_complete or stops calling tools

Design notes:
    - Same prompts, same tools, same behavior as Genie Code
    - Progress callbacks emit events for SSE streaming to UI
    - Max iterations prevent infinite loops
    - Each iteration is logged for debugging
"""

import json
import logging
import time
from typing import Optional, Callable
from dataclasses import dataclass, field

from llm.tools import TOOL_DEFINITIONS
from llm.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


# Max agent loop iterations before forced stop (bounded for cost control)
# Data layer step alone needs ~40+ iterations: config reads, vision model, ERD parsing,
# semantic model, DDL notebook create+execute, synthetic data spec, synthetic notebook
# create+execute, validation SQL queries, plus report_progress calls at each phase.
# Metric views step needs ~30+ with greenfield fast-path (or 50+ without).
# Dashboard step needs ~25-30 for design + dataset + create + publish.
MAX_ITERATIONS = 80

# Context window management — prevents OOM on long-running steps.
# The agent loop accumulates messages (assistant + tool results) each iteration.
# Without trimming, a 37-minute Data Layer step with 60+ tool calls can grow
# the messages list to 200K+ tokens, exhausting MEDIUM compute RAM.
#
# Strategy: keep the first 2 messages (system + user prompt) and the last
# CONTEXT_KEEP_RECENT messages intact. For messages in between, truncate
# tool result content to CONTEXT_TRIM_LENGTH chars. This preserves the
# LLM's ability to reference recent work while freeing memory from old results.
CONTEXT_MAX_CHARS = 300_000       # Total chars before trimming kicks in
CONTEXT_KEEP_RECENT = 12          # Messages to keep untouched at the tail
CONTEXT_TRIM_LENGTH = 200         # Truncated tool result length (chars)

# Max consecutive tool errors before hard fail (prevents token waste on unfixable issues)
MAX_CONSECUTIVE_ERRORS = 3

# Critical tools: a single failure is immediately fatal because skipping
# leaves the system in an inconsistent state that cannot self-correct.
# The LLM must NOT be allowed to silently adapt around these failures.
CRITICAL_TOOLS = {
    "execute_sql",            # DDL failures (CREATE SCHEMA, CREATE TABLE) = broken data layer
    "execute_python",         # Python code generates artifacts (YAML, configs) needed downstream
    "execute_notebook",       # Notebook execution (data generation, ETL) = missing data
    "create_notebook",        # Can't create the notebook = can't proceed
    "write_file",             # File writes produce artifacts required by later phases
    "create_dashboard",       # Dashboard creation failure = step cannot complete
}

# Read-only tools: errors are counted toward consecutive_errors (resets on success)
# but NOT toward per_tool_errors (permanent). This prevents transient workspace API
# errors or wrong-path attempts from triggering hard-fail on read-only operations.
READ_ONLY_TOOLS = {
    "read_workspace_file",
    "list_workspace_directory",
    "describe_table",
}

# Critical error patterns: even for non-critical tools, certain error messages
# indicate unrecoverable state (e.g., permission denied, quota exceeded).
CRITICAL_ERROR_PATTERNS = [
    "PermissionDenied",
    "PERMISSION_DENIED",
    "RESOURCE_EXHAUSTED",
    "QUOTA_EXCEEDED",
    "INTERNAL_ERROR",
    "schema already exists",   # Shouldn't hit this but if we do, something is off
]


@dataclass
class AgentResult:
    """Result of an agent loop execution."""
    success: bool
    summary: str = ""
    artifacts: list = field(default_factory=list)
    iterations: int = 0
    error: Optional[str] = None
    tool_calls_made: int = 0


class AgentLoop:
    """Runs a framework prompt through LLM with tool-calling.

    This replicates what happens when Genie Code reads a framework prompt
    and executes it step by step using its tools. The app does the same
    thing programmatically.

    Usage:
        agent = AgentLoop(llm_client, tool_executor, config)
        result = agent.run(
            prompt_path="framework/prompts/01_create_data_layer.md",
            context_vars={"CATALOG": "my_catalog", ...},
            callback=my_progress_handler,
        )
    """

    def __init__(self, llm_client, tool_executor: ToolExecutor, config):
        """Initialize agent loop.

        Args:
            llm_client: LLMClient instance (wraps Foundation Model API).
            tool_executor: ToolExecutor instance (executes tool calls).
            config: AcceleratorConfig with paths, catalog, etc.
        """
        self._llm = llm_client
        self._executor = tool_executor
        self._config = config

    def run(
        self,
        prompt_content: str,
        context_vars: dict,
        system_supplement: str = "",
        callback: Optional[Callable] = None,
        max_iterations: int = MAX_ITERATIONS,
    ) -> AgentResult:
        """Execute a framework prompt through the agent loop.

        Args:
            prompt_content: The full prompt markdown content.
            context_vars: Variable substitutions to inject into prompt.
                Example: {"CATALOG": "my_catalog", "SCHEMA": "my_schema",
                         "VERSION_SUFFIX": "_v5", "OUTPUT_FOLDER": "..."}
            system_supplement: Additional system context (e.g. lakeview_dashboard_api.md).
            callback: Progress callback for UI streaming.
                Signature: callback(event_type: str, data: dict)
            max_iterations: Safety limit on agent loop iterations.

        Returns:
            AgentResult with success status, summary, and artifacts.
        """
        # Inject context variables into prompt
        rendered_prompt = self._inject_variables(prompt_content, context_vars)

        # Build initial messages
        system_msg = self._build_system_message(context_vars, system_supplement)
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": rendered_prompt},
        ]

        iterations = 0
        tool_calls_made = 0
        step_complete = False
        final_result = None
        consecutive_errors = 0  # Tracks consecutive tool errors for hard-fail budget
        per_tool_errors = {}   # Tracks total failures per tool name (not reset on success)

        while iterations < max_iterations and not step_complete:
            iterations += 1

            if callback:
                callback("agent_iteration", {
                    "iteration": iterations,
                    "tool_calls_so_far": tool_calls_made,
                })

            # --- Context trimming gate ---
            # Prevent OOM by compressing old tool results when context grows too large.
            messages = self._trim_context(messages)

            # Call LLM with tools
            try:
                response = self._llm.chat_with_tools(
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    max_tokens=16384,
                )
            except Exception as e:
                logger.error(f"LLM call failed at iteration {iterations}: {e}")
                return AgentResult(
                    success=False,
                    error=f"LLM call failed: {str(e)}",
                    iterations=iterations,
                    tool_calls_made=tool_calls_made,
                )

            # Check if LLM wants to call tools
            tool_calls = response.get("tool_calls", [])
            assistant_content = response.get("content", "")

            # Emit LLM reasoning (the text content between tool calls)
            if assistant_content and callback:
                callback("llm_reasoning", {
                    "iteration": iterations,
                    "content": assistant_content[:1000],  # Truncate for SSE
                })

            if not tool_calls:
                # LLM finished without calling report_step_complete
                # Treat as implicit completion
                logger.info(f"Agent loop ended at iteration {iterations} (no more tool calls)")
                return AgentResult(
                    success=True,
                    summary=assistant_content[:500] if assistant_content else "Step completed.",
                    iterations=iterations,
                    tool_calls_made=tool_calls_made,
                )

            # Add assistant message with tool calls to conversation
            messages.append({
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": tool_calls,
            })

            # Execute each tool call
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}

                tool_calls_made += 1

                # Emit detailed tool call event (with arguments)
                if callback:
                    callback("tool_call", {
                        "tool": tool_name,
                        "iteration": iterations,
                        "args_summary": self._summarize_tool_args(tool_name, tool_args),
                    })

                # Execute the tool
                start_ts = time.time()
                result_str = self._executor.execute(tool_name, tool_args)
                duration_ms = int((time.time() - start_ts) * 1000)

                # Track errors for cost control (three mechanisms)
                is_error = result_str.startswith("ERROR") or result_str.startswith("SQL ERROR") or result_str.startswith("NOTEBOOK ERROR")
                if is_error:
                    consecutive_errors += 1
                    # Read-only tools don't accumulate per_tool_errors (transient
                    # API failures or wrong-path attempts shouldn't hard-fail)
                    if tool_name not in READ_ONLY_TOOLS:
                        per_tool_errors[tool_name] = per_tool_errors.get(tool_name, 0) + 1

                    # --- CRITICAL TOOL CHECK (immediate halt) ---
                    # Certain tools leave the system inconsistent if they fail;
                    # the LLM must NOT be allowed to silently adapt around them.
                    # Exception: read-only SQL (SELECT/SHOW/DESCRIBE) is non-critical.
                    is_critical = False
                    if tool_name in CRITICAL_TOOLS:
                        # For execute_sql, only DDL/DML is critical (not reads)
                        if tool_name == "execute_sql":
                            stmt = tool_args.get("statement", "").strip().upper()
                            is_critical = not stmt.startswith(("SELECT", "SHOW", "DESCRIBE", "DESC"))
                        else:
                            is_critical = True

                    # Check for critical error patterns (any tool)
                    if not is_critical:
                        for pattern in CRITICAL_ERROR_PATTERNS:
                            if pattern in result_str:
                                is_critical = True
                                break

                    if is_critical:
                        logger.error(
                            f"CRITICAL tool failure — halting immediately. "
                            f"Tool: {tool_name}, Error: {result_str[:500]}"
                        )
                        if callback:
                            callback("critical_failure", {
                                "tool": tool_name,
                                "error": result_str[:1000],
                                "iteration": iterations,
                            })
                        return AgentResult(
                            success=False,
                            error=f"Critical failure in '{tool_name}': {result_str[:1000]}",
                            iterations=iterations,
                            tool_calls_made=tool_calls_made,
                        )

                    # --- NON-CRITICAL: budget-based halt ---
                    # Hard fail: 3 consecutive errors OR same tool failed 3 times total
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.error(
                            f"Agent hit {MAX_CONSECUTIVE_ERRORS} consecutive errors — hard failing. "
                            f"Last error: {result_str[:500]}"
                        )
                        return AgentResult(
                            success=False,
                            error=f"Hard fail after {MAX_CONSECUTIVE_ERRORS} consecutive tool errors. Last: {result_str[:1000]}",
                            iterations=iterations,
                            tool_calls_made=tool_calls_made,
                        )
                    if per_tool_errors.get(tool_name, 0) >= MAX_CONSECUTIVE_ERRORS:
                        logger.error(
                            f"Tool '{tool_name}' failed {per_tool_errors.get(tool_name, 0)} times total — hard failing. "
                            f"Last error: {result_str[:500]}"
                        )
                        return AgentResult(
                            success=False,
                            error=f"Hard fail: '{tool_name}' failed {per_tool_errors.get(tool_name, 0)} times. Last: {result_str[:1000]}",
                            iterations=iterations,
                            tool_calls_made=tool_calls_made,
                        )
                else:
                    # Tool succeeded — reset consecutive counter (making progress)
                    consecutive_errors = 0

                # Emit tool result event
                if callback:
                    callback("tool_result", {
                        "tool": tool_name,
                        "iteration": iterations,
                        "duration_ms": duration_ms,
                        "success": not is_error,
                        "result_summary": result_str[:1000],  # Keep more for errors
                        "consecutive_errors": consecutive_errors,
                    })

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

                # Check if step_complete was signaled
                if tool_name == "report_step_complete":
                    step_complete = True
                    try:
                        final_result = json.loads(result_str)
                    except json.JSONDecodeError:
                        final_result = {"summary": result_str, "artifacts": []}
                    break

        if step_complete and final_result:
            status = final_result.get("status", "success")
            summary = final_result.get("summary", "")
            # Detect failure from explicit status OR from failure indicators in summary
            failure_indicators = ["❌", "HALTED", "FAILED", "ABORT", "ERROR"]
            is_success = (status == "success" and
                          not any(ind in summary.upper() for ind in ["HALTED", "FAILED", "ABORT"]))
            if status == "failed" or status == "partial":
                is_success = False

            return AgentResult(
                success=is_success,
                summary=summary,
                error=summary if not is_success else None,
                artifacts=final_result.get("artifacts", []),
                iterations=iterations,
                tool_calls_made=tool_calls_made,
            )

        # Hit max iterations
        return AgentResult(
            success=False,
            error=f"Agent loop hit max iterations ({max_iterations})",
            iterations=iterations,
            tool_calls_made=tool_calls_made,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _trim_context(messages: list) -> list:
        """Compress old messages when total context exceeds CONTEXT_MAX_CHARS.

        Keeps:
          - messages[0:2] (system + user prompt) always intact
          - messages[-CONTEXT_KEEP_RECENT:] always intact
          - Everything in between: tool results are truncated to CONTEXT_TRIM_LENGTH

        This prevents OOM crashes on long-running steps (e.g., 37-min Data Layer)
        where messages can accumulate 200K+ chars of tool results.
        """
        total_chars = sum(len(m.get("content", "") or "") for m in messages)
        if total_chars < CONTEXT_MAX_CHARS:
            return messages  # No trimming needed

        # Determine safe boundaries
        head = 2  # system + user prompt
        tail = CONTEXT_KEEP_RECENT
        if len(messages) <= head + tail:
            return messages  # Not enough messages to trim

        trimmed_count = 0
        chars_freed = 0

        # Trim the middle section (old tool results)
        for i in range(head, len(messages) - tail):
            msg = messages[i]
            content = msg.get("content", "") or ""

            if msg.get("role") == "tool" and len(content) > CONTEXT_TRIM_LENGTH:
                original_len = len(content)
                # Keep the first CONTEXT_TRIM_LENGTH chars + a truncation marker
                msg["content"] = (
                    content[:CONTEXT_TRIM_LENGTH]
                    + f"\n... [trimmed {original_len - CONTEXT_TRIM_LENGTH} chars for context management]"
                )
                trimmed_count += 1
                chars_freed += original_len - len(msg["content"])

            elif msg.get("role") == "assistant" and len(content) > 1000:
                # Also trim very long assistant reasoning from old iterations
                original_len = len(content)
                msg["content"] = content[:500] + "\n... [reasoning trimmed]"
                chars_freed += original_len - len(msg["content"])

        if trimmed_count > 0:
            logger.info(
                f"Context trimmed: {trimmed_count} tool results compressed, "
                f"~{chars_freed // 1024}KB freed "
                f"(total was {total_chars // 1024}KB, "
                f"now ~{(total_chars - chars_freed) // 1024}KB)"
            )

        return messages

    # Max length for tool summaries shown in the UI's "What's happening" panel.
    _MAX_SUMMARY_LEN = 80

    def _summarize_tool_args(self, tool_name: str, args: dict) -> str:
        """Create a human-readable summary of tool arguments for the UI.

        These summaries appear in the 'What's happening' section of the phase
        detail panel, so they should be concise (≤80 chars) and informative
        about WHAT is being processed — not raw SQL dumps.
        """
        MAX = self._MAX_SUMMARY_LEN

        if tool_name == "execute_sql":
            sql = args.get("statement", "")
            return self._summarize_sql(sql, MAX)
        elif tool_name == "read_workspace_file":
            path = args.get("path", "")
            # Show last 2 path segments (e.g., "v3/erd_parsed.yaml")
            parts = path.rstrip("/").split("/")
            return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        elif tool_name == "write_workspace_file":
            path = args.get("path", "")
            size = len(args.get("content", ""))
            parts = path.rstrip("/").split("/")
            short = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
            return f"{short} ({size:,} bytes)"[:MAX]
        elif tool_name == "create_dashboard":
            return args.get("display_name", "")[:MAX]
        elif tool_name == "publish_dashboard":
            return f"ID: {args.get('dashboard_id', '')[:12]}"
        elif tool_name == "describe_table":
            table = args.get("table_name", "")
            # Show just schema.table for brevity
            parts = table.split(".")
            return ".".join(parts[-2:]) if len(parts) >= 2 else table
        elif tool_name == "execute_python":
            code = args.get("code", "")
            return code.split("\n")[0][:MAX]
        elif tool_name == "call_vision_model":
            img = args.get("image_path", "")
            return img.split("/")[-1] if img else "Processing image"
        elif tool_name == "import_notebook":
            path = args.get("path", "")
            return path.split("/")[-1][:MAX] if path else ""
        elif tool_name == "execute_notebook":
            path = args.get("path", "")
            return path.split("/")[-1][:MAX] if path else ""
        elif tool_name == "list_workspace_directory":
            path = args.get("path", "")
            parts = path.rstrip("/").split("/")
            return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        elif tool_name == "report_step_complete":
            return args.get("summary", "")[:MAX]
        return str(args)[:MAX]

    @staticmethod
    def _summarize_sql(sql: str, max_len: int) -> str:
        """Extract a short, human-readable summary from a SQL statement.

        Goals:
          - Identify the verb + target (table name or key object)
          - Cap at max_len chars so the UI doesn't overflow
          - Never show raw multi-line SQL
        """
        import re
        # Get first meaningful line
        lines = [l.strip() for l in sql.split("\n") if l.strip() and not l.strip().startswith("--")]
        first = lines[0] if lines else sql[:max_len]
        upper = first.upper()

        # DESCRIBE TABLE <fqn>
        if upper.startswith("DESCRIBE"):
            # Extract table name (strip backticks, get last 2 segments)
            clean = re.sub(r'[`"\']', '', first)
            m = re.search(r'(?:TABLE\s+(?:EXTENDED\s+)?)?([\w.]+)\s*$', clean[8:].strip(), re.I)
            table = m.group(1) if m else clean[9:60].strip()
            parts = table.split('.')
            short = '.'.join(parts[-2:]) if len(parts) >= 2 else table
            return f"DESCRIBE {short}"[:max_len]

        # SELECT COUNT(*) ... FROM <table>
        if "COUNT" in upper and "FROM" in upper:
            clean = re.sub(r'[`"\']', '', first)
            m = re.search(r'FROM\s+([\w.]+)', clean, re.I)
            table = m.group(1) if m else ''
            if table:
                parts = table.split('.')
                short = '.'.join(parts[-2:]) if len(parts) >= 2 else table
                return f"Row count: {short}"[:max_len]
            return first[:max_len]

        # SELECT ... FROM <table> — show "Query: <table> ..."
        if upper.startswith("SELECT"):
            m = re.search(r'FROM\s+[`"\']?([\w.`]+)', first, re.I)
            table = m.group(1).strip('`') if m else ''
            if table:
                # Extract short table (last 2 segments)
                parts = table.split('.')
                short_table = '.'.join(parts[-2:]) if len(parts) >= 2 else table
                return f"Query: {short_table}"[:max_len]
            return first[:max_len]

        # CREATE TABLE / CREATE OR REPLACE
        if upper.startswith("CREATE"):
            m = re.search(r'(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?([\w.`]+)', first, re.I)
            table = m.group(1).strip('`') if m else ''
            if table:
                parts = table.split('.')
                short_table = '.'.join(parts[-2:]) if len(parts) >= 2 else table
                return f"CREATE {short_table}"[:max_len]
            return first[:max_len]

        # DROP TABLE
        if upper.startswith("DROP"):
            m = re.search(r'(?:TABLE|VIEW)\s+(?:IF\s+EXISTS\s+)?[`"\']?([\w.`]+)', first, re.I)
            table = m.group(1).strip('`') if m else ''
            if table:
                parts = table.split('.')
                short_table = '.'.join(parts[-2:]) if len(parts) >= 2 else table
                return f"DROP {short_table}"[:max_len]
            return first[:max_len]

        # INSERT / MERGE
        if upper.startswith("INSERT") or upper.startswith("MERGE"):
            m = re.search(r'INTO\s+[`"\']?([\w.`]+)', first, re.I)
            table = m.group(1).strip('`') if m else ''
            verb = 'INSERT' if upper.startswith('INSERT') else 'MERGE'
            if table:
                parts = table.split('.')
                short_table = '.'.join(parts[-2:]) if len(parts) >= 2 else table
                return f"{verb}: {short_table}"[:max_len]
            return first[:max_len]

        # SHOW TABLES / SHOW SCHEMAS etc.
        if upper.startswith("SHOW"):
            return first[:max_len]

        # Fallback — truncate first line
        return first[:max_len]

    def _inject_variables(self, prompt: str, context_vars: dict) -> str:
        """Replace {variable} placeholders in prompt with actual values."""
        result = prompt
        for key, value in context_vars.items():
            # Support both {key} and {workspace.key} style placeholders
            result = result.replace("{" + key + "}", str(value))
        return result

    def _build_system_message(self, context_vars: dict, supplement: str = "") -> str:
        """Build the system message with execution context and tool mapping.

        The tool mapping bridges between the prompt's prose instructions
        (which are environment-agnostic) and the actual tools available
        in App mode. This keeps prompts portable to Genie Code.
        """
        parts = [
            "You are an AI/BI Studio pipeline agent executing a framework prompt.",
            "",
            "TOOL MAPPING (how to accomplish what the prompt instructs):",
            "  When the prompt says...              Use this tool:",
            "  'parse/read the ERD image'       --> call_vision_model(image_path, prompt)",
            "  'read a file / load config'      --> read_workspace_file(path)",
            "  'write a file / save artifact'   --> write_workspace_file(path, content)",
            "  'create/import a notebook'       --> import_notebook(path, content, language)",
            "  'execute/run the notebook'       --> execute_notebook(path)",
            "  'execute SQL / run DDL'          --> execute_sql(statement)",
            "  'create dashboard'               --> create_dashboard(...)",
            "  'list directory'                 --> list_workspace_directory(path)",
            "  'clean/remove output folder'     --> cleanup_path(path, recursive)",
            "  'describe table'                 --> describe_table(table_name)",
            "",
            "CRITICAL EXECUTION RULES:",
            "- Execute ALL steps in the prompt sequentially. No shortcuts or merging.",
            "- VISION: When the prompt requires parsing an ERD image, you MUST call",
            "  call_vision_model. Do NOT use read_workspace_file on image files.",
            "  Do NOT reuse erd_parsed.yaml from a prior run — always parse fresh.",
            "- NOTEBOOKS: DDL and synthetic data MUST be SEPARATE notebooks.",
            "  Create each via import_notebook, then execute each via execute_notebook.",
            "  Never combine multiple pipeline steps into a single notebook.",
            "- NOTEBOOK CELL STRUCTURE: Notebooks use '# COMMAND ----------' as cell",
            "  separators. The FIRST executable cell MUST be '%pip install ...' followed",
            "  by 'dbutils.library.restartPython()' — this cell installs dependencies.",
            "  The SECOND cell (after # COMMAND ----------) does 'import dbldatagen'.",
            "  NEVER put %pip install and import in the same cell — the Python restart",
            "  happens between cells. Violating this causes 'No module named' errors.",
            "- TEMPLATES: When the prompt says 'populate from template', first read the",
            "  template file via read_workspace_file, then use it as a structural guide",
            "  for the notebook content you generate via import_notebook. PRESERVE the",
            "  template's cell structure, helper functions, and safety patches exactly.",
            "  Generate table-specific code ONLY in the final cells after the template",
            "  boilerplate (setup, helpers, discover_tables).",
            "- SELF-CORRECTION: If a tool returns an error, read the error, fix the",
            "  issue, and retry. You have up to 3 attempts before hard failure.",
            "- When done, call report_step_complete with summary and artifacts list.",
            "",
            "PROGRESS REPORTING (MANDATORY):",
            "- Call report_progress at EVERY logical phase boundary.",
            "- Call with status='started' when you BEGIN a phase.",
            "- Call with status='completed' when a phase FINISHES (include findings & stats).",
            "- Call with status='failed' if a phase encounters an error.",
            "- Optionally call status='update' mid-phase to report interim progress.",
            "- Include: current_task (what you're doing now), happenings (bullet list of",
            "  sub-activities), findings (key facts discovered), stats (numeric metrics).",
            "- This drives the real-time UI regardless of execution environment.",
            "- Phase IDs should match prompt section names (e.g., 'load_config', 'parse_erd',",
            "  'build_semantic_model', 'generate_ddl', 'generate_synthetic_data', 'validate_data').",
            "",
            "EXECUTION CONTEXT:",
            f"  CATALOG: {context_vars.get('CATALOG', 'N/A')}",
            f"  SCHEMA: {context_vars.get('SCHEMA', 'N/A')}",
            f"  VERSION_SUFFIX: {context_vars.get('VERSION_SUFFIX', '')}",
            f"  OUTPUT_FOLDER: {context_vars.get('OUTPUT_FOLDER', 'N/A')}",
            f"  SQL_WAREHOUSE_ID: {context_vars.get('sql_warehouse_id', 'N/A')}",
            f"  DEPLOY_ROOT: {context_vars.get('deploy_root', 'N/A')}",
        ]

        # Add domain-specific paths if available (from PipelineRunner extra_context)
        domain_name = context_vars.get('DOMAIN_NAME')
        if domain_name:
            parts.append("")
            parts.append("DOMAIN PATHS (use these exact paths for tool calls):")
            parts.append(f"  DOMAIN_NAME: {domain_name}")
            parts.append(f"  ACCELERATOR_YAML: {context_vars.get('ACCELERATOR_YAML_PATH', 'N/A')}")
            parts.append(f"  ERD_IMAGE: {context_vars.get('ERD_IMAGE_PATH', 'N/A')}")
            parts.append(f"  KPI_SPEC: {context_vars.get('KPI_SPEC_PATH', 'N/A')}")
            parts.append(f"  DDL_TEMPLATE: {context_vars.get('DDL_TEMPLATE_PATH', 'N/A')}")
            parts.append(f"  DBLDATAGEN_TEMPLATE: {context_vars.get('DBLDATAGEN_TEMPLATE_PATH', 'N/A')}")
            parts.append("")
            parts.append("  FIRST ACTION: call read_workspace_file on ACCELERATOR_YAML to load config.")
            parts.append("  THEN: call call_vision_model with image_path=ERD_IMAGE to parse the schema.")

        # Add step-specific efficiency hints
        step_name = context_vars.get('STEP_NAME', '')
        if step_name in ('create_metric_views', 'create_dashboards', 'create_genie_space'):
            parts.append("")
            parts.append("EFFICIENCY RULES (for downstream steps):")
            parts.append("- For GREENFIELD (data_source.type = erd): prior step artifacts")
            parts.append("  (erd_parsed.yaml, semantic_model.yaml, data_layer_validation.yaml)")
            parts.append("  already contain full schema info. DO NOT re-profile tables individually.")
            parts.append("- Read the contract files ONCE and use them as schema source.")
            parts.append("- Confirm tables exist with ONE information_schema query, not per-table DESCRIBE.")
            parts.append("- Minimize tool calls: batch SQL when possible, write files in one pass.")
            parts.append("- Call report_progress(status='completed') as soon as a phase finishes.")

        if step_name == 'create_data_layer':
            parts.append("")
            parts.append("DATA LAYER EFFICIENCY RULES (CRITICAL):")
            parts.append("- BATCH VALIDATION: Combine ALL PK/FK/row-count checks into 2-3 SQL calls.")
            parts.append("  Use UNION ALL: SELECT 'table_name' t, COUNT(*) rows, COUNT(DISTINCT pk) pk_distinct FROM ... UNION ALL ...")
            parts.append("  Do NOT run one SQL per table or per FK relationship.")
            parts.append("- WRITE ONCE: Write erd_parsed.yaml, semantic_model.yaml, synthetic_data_spec.yaml")
            parts.append("  each in ONE write_workspace_file call. Do not append incrementally.")
            parts.append("- SINGLE NOTEBOOK: Generate ONE synthetic data notebook with ALL tables.")
            parts.append("  Do not create separate notebooks per table.")

        if step_name == 'create_metric_views':
            parts.append("")
            parts.append("METRIC VIEW EFFICIENCY RULES (CRITICAL):")
            parts.append("- GREENFIELD FAST PATH: When erd_parsed.yaml + semantic_model.yaml + ")
            parts.append("  data_layer_validation.yaml(PASS) exist, derive schema_profile.yaml directly.")
            parts.append("  Do NOT loop DESCRIBE TABLE on each table.")
            parts.append("- ONE information_schema query to confirm tables exist.")
            parts.append("- BATCH METRIC VIEW VALIDATION: After creating views, validate ALL in one SQL:")
            parts.append("  SELECT 'mv1' mv, COUNT(*) FROM mv1 UNION ALL SELECT 'mv2', COUNT(*) FROM mv2")
            parts.append("- NO CHAINED JOINS: 'on' clauses may only reference source.* or own_join_name.*")
            parts.append("  References to other join aliases cause UNRESOLVED_COLUMN.")

        if step_name == 'create_dashboards':
            parts.append("")
            parts.append("DASHBOARD EFFICIENCY RULES (CRITICAL — saves 15+ tool calls):")
            parts.append("- BATCH DATASET VALIDATION: Do NOT validate datasets one-by-one.")
            parts.append("  Combine validation into 2-3 SQL calls using UNION ALL:")
            parts.append("  SELECT 'ds_name_1' AS ds, * FROM (dataset_1_sql) LIMIT 3")
            parts.append("  UNION ALL SELECT 'ds_name_2' AS ds, * FROM (dataset_2_sql) LIMIT 3")
            parts.append("  UNION ALL ... (group datasets with compatible column shapes)")
            parts.append("  For incompatible shapes, group into 2-3 batches max.")
            parts.append("- PROFILE ONCE: Run ONE DESCRIBE per metric view, not per dataset.")
            parts.append("  Cache the column list and reuse for all dataset SQL referencing that view.")
            parts.append("- WRITE YAML ONCE: Accumulate all dataset validations in memory,")
            parts.append("  then write dashboard_dataset_validation.yaml in ONE write_workspace_file call.")
            parts.append("- NO CHAINED JOINS: Metric views do NOT support joins where one join's")
            parts.append("  'on' clause references another join alias (UNRESOLVED_COLUMN error).")
            parts.append("  Only source.col and <own_join_name>.col are allowed in 'on' clauses.")

        if step_name == 'create_genie_space':
            parts.append("")
            parts.append("GENIE SPACE EFFICIENCY RULES (CRITICAL):")
            parts.append("- FAST PATH: metric_view_design.yaml ALREADY has all measures/dimensions.")
            parts.append("  Do NOT call DESCRIBE TABLE on metric views again.")
            parts.append("  ONE SQL for row counts. ONE SQL for categorical value profiling.")
            parts.append("- BATCH SQL VALIDATION: Validate 15-20 example SQLs in 2-3 batch calls,")
            parts.append("  NOT one at a time. Use UNION ALL with compatible shapes.")
            parts.append("- WRITE FILES ONCE: Write genie_semantic_inventory.yaml in one call.")
            parts.append("  Write benchmark YAML in one call. Do not append line by line.")

        if step_name == 'generate_documentation':
            parts.append("")
            parts.append("DOCUMENTATION EFFICIENCY RULES:")
            parts.append("- Read all artifact files in Steps 1-2, then write the README in ONE call.")
            parts.append("- Do NOT read-write-read-write iteratively.")
            parts.append("- Compose the full document in memory, then write once.")
            parts.append("- VALIDATION (Step 6): Do NOT re-read artifact files for factual consistency.")
            parts.append("  All artifacts are ALREADY in context from Steps 1-2. Validate from memory.")
            parts.append("  Total Step 6 tool calls: 2-3 max (write readme + write manifest + report_progress).")
            parts.append("- If you find yourself calling read_workspace_file during validation, STOP.")
            parts.append("  You already have that data. Use it from context.")

        # Inject RESUME_CONTEXT when resuming from a prior checkpoint (App-mode optimization).
        # The step prompts already encode artifact-as-state verification unconditionally.
        # This context accelerates the process by pre-identifying what's done.
        resume_context = context_vars.get('RESUME_CONTEXT')
        if resume_context:
            parts.append("")
            parts.append("RESUME_CONTEXT (App-mode optimization — pre-identified completed work):")
            parts.append(f"  run_id: {resume_context.get('run_id', 'N/A')}")
            parts.append(f"  last_completed_step: {resume_context.get('last_completed_step', 'N/A')}")
            parts.append(f"  current_step: {resume_context.get('current_step', 'N/A')}")
            artifacts = resume_context.get('artifacts_written', [])
            if artifacts:
                parts.append("  artifacts_written (verify these exist, skip phases if valid):")
                for a in artifacts:
                    parts.append(f"    - {a}")
            findings = resume_context.get('prior_findings', [])
            if findings:
                parts.append("  prior_findings:")
                for f in findings:
                    parts.append(f"    - {f}")
            parts.append("")
            parts.append("  Use this context to skip listing the output folder — verify the")
            parts.append("  artifacts above directly, then continue from the first incomplete phase.")

        if supplement:
            parts.append("")
            parts.append("SUPPLEMENTARY REFERENCE:")
            parts.append(supplement)

        return "\n".join(parts)
