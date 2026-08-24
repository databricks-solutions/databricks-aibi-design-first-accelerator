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
                return f"ERROR: File not found: {path}"
            return content
        except Exception as e:
            # Fallback: might be binary with unexpected extension
            if 'codec' in str(e).lower() or 'decode' in str(e).lower():
                try:
                    data = self._ws.read_binary(path)
                    return f"SUCCESS: Binary file ({len(data)} bytes). Cannot display content."
                except Exception:
                    pass
            return f"ERROR: {str(e)}"

    def _handle_write_workspace_file(self, args: dict) -> str:
        path = args["path"]
        content = args["content"]
        self._ws.write_file(path, content)
        return f"SUCCESS: Written {len(content)} bytes to {path}"

    def _handle_list_workspace_directory(self, args: dict) -> str:
        path = args["path"]
        entries = self._ws.list_dir(path)
        if not entries:
            return f"Directory empty or not found: {path}"
        lines = [f"  {e.path.split('/')[-1]} ({e.object_type})" for e in entries]
        return "\n".join(lines)

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
            result = self._lakeview.update_dashboard(
                dashboard_id=dashboard_id, display_name=display_name,
                serialized_dashboard=serialized, warehouse_id=warehouse_id)
        else:
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
        title = args["title"]
        serialized = args["serialized_space"]
        warehouse_id = args["warehouse_id"]
        space_id = args.get("space_id")
        if space_id:
            result = self._genie.update_space(
                space_id=space_id, title=title,
                serialized_space=serialized, warehouse_id=warehouse_id)
        else:
            result = self._genie.create_space(
                title=title, serialized_space=serialized, warehouse_id=warehouse_id)
        new_id = result.get("space_id", result.get("id", "unknown"))
        return f"SUCCESS: Genie space ID: {new_id}"

    def _handle_describe_table(self, args: dict) -> str:
        return self._handle_execute_sql({"statement": f"DESCRIBE TABLE EXTENDED {args['table_name']}"})

    def _handle_execute_python(self, args: dict) -> str:
        result = self._sql.execute_python(args["code"])
        return result or "SUCCESS: Python code executed."

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
        """Execute a notebook via Jobs API and wait for result."""
        path = args["path"]
        timeout_minutes = args.get("timeout_minutes", 15)

        if not self._jobs:
            return "ERROR: Jobs service not configured (no jobs client available)"

        try:
            # Determine language from file extension
            language = "PYTHON"
            if path.endswith(".sql"):
                language = "SQL"

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

    def _handle_cleanup_path(self, args: dict) -> str:
        """Remove a workspace file or directory for re-generation."""
        path = args["path"]
        recursive = args.get("recursive", False)

        try:
            self._ws.delete(path, recursive=recursive)
            return f"SUCCESS: Removed {path}"
        except Exception as e:
            return f"ERROR removing path: {str(e)}"

