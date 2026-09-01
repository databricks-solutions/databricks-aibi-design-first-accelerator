"""ToolExecutor - Executes tool calls from the LLM agent loop.

Maps tool names to service calls against Databricks APIs.
This is the bridge between what the LLM wants to do and the actual
Databricks SDK/API calls that make it happen.

Design notes:
    - Each tool handler returns a string result (success message or error)
    - Errors are returned as tool results (not exceptions) so the LLM
      can self-correct
    - All handlers are idempotent where possible
    - Timeout and retries are handled at the service layer
"""

import json
import logging

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tool calls using Databricks services."""

    def __init__(self, config, services: dict, llm_client=None):
        self._config = config
        self._ws = services.get("workspace")
        self._sql = services.get("sql")
        self._lakeview = services.get("lakeview")
        self._genie = services.get("genie")
        self._jobs = services.get("jobs")
        self._llm = llm_client

    def execute(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool call and return the result string."""
        handler = getattr(self, f"_handle_{tool_name}", None)
        if not handler:
            return f"ERROR: Unknown tool"

        try:
            return handler(arguments)
        except Exception as e:
            error_msg = f"ERROR executing {tool_name}: {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg

    def _handle_execute_sql(self, args: dict) -> str:
        statement = args["statement"]
        try:
            result = self._sql.execute_and_wait(statement)
        except Exception as e:
            return f"SQL ERROR: {str(e)}"

        if result.status == "SUCCEEDED":
            columns = [c.name for c in result.columns] if result.columns else []
            rows = result.data or []
            if columns and rows:
                header = " | ".join(columns)
                row_strs = [" | ".join(str(v) for v in row) for row in rows[:50]]
                return f"SUCCESS ({len(rows)} rows):\n{header}\n" + "\n".join(row_strs)
            return f"SUCCESS (statement executed, {result.row_count} rows affected)"
        elif result.status == "FAILED":
            return f"SQL ERROR: {result.error or 'Unknown error'}"
        return f"SQL status: {result.status}"

    def _handle_read_workspace_file(self, args: dict) -> str:
        path = args["path"]
        # Detect binary files by extension
        binary_exts = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.pdf', '.zip', '.tar', '.gz')
        if path.lower().endswith(binary_exts):
            try:
                data = self._ws.read_binary(path)
                return f"SUCCESS: Binary file ({len(data)} bytes). Cannot display content."
            except Exception as e:
                return f"ERROR: {str(e)}"
        try:
            content = self._ws.read_file(path)
            if content is None:
                return f"FILE_NOT_FOUND: {path} does not exist yet. Create it if needed, or skip if optional."
            return content
        except Exception as e:
            err_str = str(e).lower()
            err_type = type(e).__name__.lower()
            # Distinguish file-not-found from other errors
            # SDK raises ResourceDoesNotExist with message "doesn't exist" (apostrophe)
            if any(hint in err_str for hint in ('not found', 'does not exist', "doesn't exist", '404', 'resource_does_not_exist')):
                return f"FILE_NOT_FOUND: {path} does not exist yet. Create it if needed, or skip if optional."
            if 'doesnotexist' in err_type or 'notfound' in err_type:
                return f"FILE_NOT_FOUND: {path} does not exist yet. Create it if needed, or skip if optional."
            # Fallback: might be binary with unexpected extension
            if 'codec' in err_str or 'decode' in err_str:
                try:
                    data = self._ws.read_binary(path)
                    return f"SUCCESS: Binary file ({len(data)} bytes). Cannot display content."
                except Exception:
                    pass
            return f"ERROR: WorkspaceError [read_file] {path}: {str(e)}"

    def _handle_write_workspace_file(self, args: dict) -> str:
        path = args["path"]
        content = args["content"]
        self._ws.write_file(path, content)
        return f"SUCCESS: Written {len(content)} bytes to {path}"

    def _handle_list_workspace_directory(self, args: dict) -> str:
        path = args["path"]
        try:
            entries = self._ws.list_dir(path)
            if not entries:
                return f"DIRECTORY_EMPTY: {path} exists but is empty."
            lines = [f"  {e.path.split('/')[-1]} ({e.object_type})" for e in entries]
            return "\n".join(lines)
        except Exception as e:
            err_str = str(e).lower()
            if any(hint in err_str for hint in ('not found', 'does not exist', '404', 'resource_does_not_exist', 'no such file')):
                return f"DIRECTORY_NOT_FOUND: {path} does not exist yet. It will be created when needed."
            return f"ERROR: {str(e)}"

    def _handle_create_dashboard(self, args: dict) -> str:
        display_name = args["display_name"]
        serialized = args["serialized_dashboard"]
        warehouse_id = args["warehouse_id"]
        dashboard_id = args.get("dashboard_id")
        # Resolve parent_path: use output_folder from config so the app SP
        # creates dashboards under the project folder where it has CAN_MANAGE.
        # Without this, the API defaults to the calling identity's home path
        # which causes PermissionDenied when SP lacks access to user's home.
        parent_path = args.get("parent_path") or getattr(self._config, 'output_folder', None) or getattr(self._config, 'deploy_root', None)
        if dashboard_id:
            # Explicit update of existing dashboard
            result = self._lakeview.update_dashboard(
                dashboard_id=dashboard_id, display_name=display_name,
                serialized_dashboard=serialized, warehouse_id=warehouse_id)
        else:
            # Create new — if name already exists, delete old and recreate
            existing = self._lakeview.find_by_name(display_name)
            if existing:
                self._lakeview.delete_dashboard(existing.dashboard_id)
            result = self._lakeview.create_dashboard(
                display_name=display_name, serialized_dashboard=serialized,
                warehouse_id=warehouse_id, parent_path=parent_path)
        # Result is a Dashboard dataclass — use attribute access
        new_id = getattr(result, 'dashboard_id', None) or getattr(result, 'id', 'unknown')
        return f"SUCCESS: Dashboard ID: {new_id}"

    def _handle_publish_dashboard(self, args: dict) -> str:
        self._lakeview.publish_dashboard(
            dashboard_id=args["dashboard_id"], warehouse_id=args["warehouse_id"])
        return f"SUCCESS: Dashboard published."

    def _handle_create_genie_space(self, args: dict) -> str:
        """Redirect: Genie space creation uses the template notebook pattern."""
        return (
            "ERROR: create_genie_space tool is disabled. "
            "Use the template notebook pattern instead (same as synthetic data generation): "
            "1) Read the genie_space_notebook.py.template from the templates directory. "
            "2) Populate cells 1-7 with the configuration (title, instructions, sample questions, example SQL, benchmarks). "
            "3) Copy cells 8-10 verbatim (helpers, create/update API, validate). "
            "4) Use import_notebook to save the notebook to the output folder. "
            "5) Use execute_notebook to run it as a job (cells 8-10 call the Genie API). "
            "This is the ONLY supported path for Genie space creation."
        )

    def _handle_describe_table(self, args: dict) -> str:
        return self._handle_execute_sql({"statement": f"DESCRIBE TABLE EXTENDED {args['table_name']}"})

    def _handle_execute_python(self, args: dict) -> str:
        """Run a Python snippet in a subprocess and return its stdout.

        Environment setup:
          - cwd=/tmp (writable — os.makedirs works for local temp files)
          - Inherits parent env + DATABRICKS_HOST/TOKEN for SDK usage
          - sys.path includes app source so imports work
        """
        import subprocess as _sp
        import sys
        import os

        code = args.get("code", "")
        if not code.strip():
            return "ERROR: No code provided."

        # Build environment: inherit parent + ensure workspace access
        env = os.environ.copy()
        # Ensure /tmp exists as working directory
        work_dir = "/tmp/pipeline_python"
        os.makedirs(work_dir, exist_ok=True)

        try:
            proc = _sp.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=120,
                cwd=work_dir, env=env,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                # Provide actionable guidance for common errors
                if "makedirs" in stderr and "Workspace" in stderr:
                    stderr += (
                        "\n\nHINT: /Workspace paths are not local filesystem paths. "
                        "Use the write_workspace_file tool instead of os.makedirs + open()."
                    )
                return f"ERROR: {stderr}"
            return proc.stdout.strip() or "SUCCESS: executed (no output)."
        except _sp.TimeoutExpired:
            return "ERROR: Python execution timed out (120s limit)."
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    def _handle_call_vision_model(self, args: dict) -> str:
        image_path = args["image_path"]
        prompt = args["prompt"]

        if not self._llm:
            return "ERROR: Vision model not configured (no LLM client)"

        # Read image as binary
        try:
            image_bytes = self._ws.read_binary(image_path)
        except Exception as e:
            return f"ERROR reading image: {str(e)}"

        if not image_bytes:
            return f"ERROR: Image file is empty: {image_path}"

        # Call vision model with high token limit for detailed ERD output.
        # CRITICAL: databricks-gpt-5-5 is a reasoning model — internal thinking
        # tokens consume the max_tokens budget. Use 32000 to leave room for both
        # reasoning (~8-12k tokens) and the actual structured ERD output (~10-15k).
        messages = [
            {"role": "system", "content": "You are an expert at analyzing database diagrams and schemas. Extract complete, detailed schema information."},
            {"role": "user", "content": prompt},
        ]
        # Use config max_tokens if available, default to 32000 for vision
        vision_max_tokens = getattr(self._config, 'max_tokens', None) or 32000
        try:
            result = self._llm.chat_with_vision(
                messages=messages,
                image_bytes=image_bytes,
                max_tokens=vision_max_tokens,
            )
            return result
        except Exception as e:
            return f"ERROR calling vision model: {str(e)}"

    def _handle_report_progress(self, args: dict) -> str:
        """Handle progress reporting from the LLM.

        This tool is called by the LLM at phase boundaries to signal what
        logical step is happening (e.g., Parse ERD, Build Semantic Model).
        The structured data flows to both:
        - App UI via SSE events (real-time)
        - run_manifest.json via event_callback (persistent)

        Returns a JSON string that the agent_event_bridge parses and
        re-emits as a 'phase_update' event.
        """
        import json
        progress = {
            "__progress_event__": True,  # Marker for agent_event_bridge
            "phase_id": args.get("phase_id", ""),
            "phase_name": args.get("phase_name", ""),
            "status": args.get("status", "update"),
            "current_task": args.get("current_task"),
            "progress_pct": args.get("progress_pct"),
            "stats": args.get("stats", {}),
            "happenings": args.get("happenings", []),
            "findings": args.get("findings", []),
        }
        logger.info(f"Progress: {progress['phase_name']} [{progress['status']}]")
        return json.dumps(progress)


    def _handle_report_step_complete(self, args: dict) -> str:
        return json.dumps({
            "step_complete": True,
            "summary": args["summary"],
            "artifacts": args.get("artifacts", []),
            "status": args.get("status", "success"),
        })

    def _handle_import_notebook(self, args: dict) -> str:
        """Import a notebook to workspace using the Workspace API."""
        path = args["path"]
        nb_content = args["content"]
        language = args.get("language", "PYTHON").upper()

        try:
            # Use workspace service to import notebook
            # The content is in Databricks notebook source format
            self._ws.import_notebook(path, nb_content, language=language)
            return f"SUCCESS: Notebook imported to {path} ({len(nb_content)} chars, {language})"
        except Exception as e:
            return f"ERROR importing notebook: {str(e)}"

    def _handle_execute_notebook(self, args: dict) -> str:
        """Execute a notebook via Jobs API and wait for result.

        Includes a py_compile pre-flight gate for Python notebooks:
        reads the notebook source, splits into cells, and compiles each
        Python cell. If any cell has a SyntaxError, returns the error
        immediately WITHOUT submitting a job run (saves time + compute).
        """
        path = args["path"]
        timeout_minutes = args.get("timeout_minutes", 15)

        if not self._jobs:
            return "ERROR: Jobs service not configured (no jobs client available)"

        try:
            # Determine language from file extension
            language = "PYTHON"
            if path.endswith(".sql"):
                language = "SQL"

            # --- PY_COMPILE GATE (Python notebooks only) ---
            if language == "PYTHON":
                compile_error = self._py_compile_check(path)
                if compile_error:
                    return compile_error

            # Submit the run
            run_id = self._jobs.run_notebook(path, language=language)

            # Wait for completion
            result = self._jobs.wait_for_run(run_id, timeout_s=timeout_minutes * 60)

            if result.result_state == "SUCCESS":
                duration_str = f" ({result.duration_s:.1f}s)" if result.duration_s else ""
                output = result.output or "No output captured."
                return f"SUCCESS: Notebook executed{duration_str}. Output: {output}"
            else:
                error_detail = result.error or "Unknown error"
                return f"NOTEBOOK ERROR (run_id={run_id}): {error_detail}"
        except Exception as e:
            return f"ERROR executing notebook: {str(e)}"

    def _py_compile_check(self, path: str) -> str | None:
        """Pre-flight syntax check for Python notebooks.

        Dual-strategy gate:
        1. compile() — catches general SyntaxErrors (undefined names won't be
           caught, but malformed syntax will).
        2. Regex f-string backslash detector — catches the specific pattern
           of backslashes inside f-string {expressions} which is illegal on
           Python 3.11 (serverless compute) but allowed on 3.12+ (where this
           app server may run). Without this, compile() would miss it on 3.12.

        Returns an error string if any cell fails, or None if all pass.
        """
        import re

        try:
            source = self._ws.read_file(path)
            if not source:
                return None  # Empty notebook, let it run (will fail gracefully)
        except Exception:
            return None  # Can't read = let the job run and report its own error

        # Split into cells (Databricks source format)
        cell_separator = "# COMMAND ----------"
        cells = source.split(cell_separator)

        errors = []
        for idx, cell in enumerate(cells):
            cell_stripped = cell.strip()
            if not cell_stripped:
                continue

            # Skip non-Python cells (magic commands)
            first_line = cell_stripped.split('\n')[0].strip()
            if first_line.startswith('%') and not first_line.startswith('%%'):
                if any(first_line.startswith(f'%{m}') for m in ['pip', 'sql', 'md', 'sh', 'r', 'scala', 'fs']):
                    continue

            # Skip cells that are pure comments/titles
            code_lines = [l for l in cell_stripped.split('\n')
                         if l.strip() and not l.strip().startswith('#')]
            if not code_lines:
                continue

            # Gate 1: compile() for general syntax errors
            try:
                compile(cell_stripped, f'<cell_{idx + 1}>', 'exec')
            except SyntaxError as e:
                line_info = f", line {e.lineno}" if e.lineno else ""
                text_info = f"\n  Code: {e.text.strip()}" if e.text else ""
                errors.append(
                    f"Cell {idx + 1}{line_info}: {e.msg}{text_info}"
                )
                continue  # Skip Gate 2 if compile already failed

            # Gate 2: f-string backslash detector (Python 3.11 compat)
            # compile() on 3.12+ won't catch this, but serverless runs 3.11
            fstring_issues = self._check_fstring_backslash(cell_stripped)
            for lineno, line_text, expr in fstring_issues:
                errors.append(
                    f"Cell {idx + 1}, line {lineno}: "
                    f"f-string expression contains backslash (illegal in Python 3.11)\n"
                    f"  Code: {line_text}\n"
                    f"  Expr: {{{expr}}}\n"
                    f"  Fix: Assign to variable first, e.g.: sep = '\\n'; f\"{{sep.join(...)}}\""
                )

        if errors:
            error_list = "\n".join(errors)
            return (
                f"SYNTAX_ERROR (pre-flight py_compile gate): "
                f"Notebook has {len(errors)} syntax error(s). "
                f"Fix these BEFORE re-running:\n{error_list}"
            )

        return None  # All cells passed

    @staticmethod
    def _check_fstring_backslash(source: str) -> list:
        """Detect backslashes inside f-string {expressions}.

        Returns list of (lineno, line_text, expr) tuples for violations.
        This is illegal in Python 3.11 (serverless compute).
        """
        import re
        issues = []
        lines = source.split('\n')

        for lineno, line in enumerate(lines, 1):
            if '\\' not in line:
                continue
            if not re.search(r'''[fF]['"]''', line):
                continue

            # Find f-string starts and check their {expr} parts
            for m in re.finditer(r'''[fF](['"]{{1,3}})''', line):
                quote = m.group(1)
                start = m.end()
                depth = 0
                expr_start = None
                i = start
                while i < len(line):
                    ch = line[i]
                    if ch == '{' and (i + 1 >= len(line) or line[i + 1] != '{'):
                        if depth == 0:
                            expr_start = i
                        depth += 1
                    elif ch == '}' and (i + 1 >= len(line) or line[i + 1] != '}'):
                        depth -= 1
                        if depth == 0 and expr_start is not None:
                            expr = line[expr_start + 1:i]
                            if '\\' in expr:
                                issues.append((lineno, line.strip(), expr.strip()))
                            expr_start = None
                    elif ch == quote[0] and depth == 0:
                        break
                    i += 1

        return issues

    def _handle_cleanup_path(self, args: dict) -> str:
        """Remove a workspace file or directory for re-generation."""
        path = args["path"]
        recursive = args.get("recursive", False)

        try:
            self._ws.delete(path, recursive=recursive)
            return f"SUCCESS: Removed {path}"
        except Exception as e:
            return f"ERROR removing path: {str(e)}"

