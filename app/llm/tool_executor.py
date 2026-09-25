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
        # Artifact-gated phase skip: set of absolute paths that are
        # frozen (completed phases). Writes to these paths return early.
        self._frozen_artifacts: set = set()
        self._diagnostic_run = None  # Observational only; never deployment authority.
        self._diagnostic_details = {}

    def set_frozen_artifacts(self, paths: set):
        """Set the frozen artifact paths for artifact-gated phase skip.

        Paths in this set will be protected from writes — the write handler
        returns a SKIPPED message instead. This is the deterministic safety
        net that prevents the LLM from overwriting completed phase artifacts.

        Args:
            paths: Set of absolute workspace paths to freeze.
        """
        self._frozen_artifacts = set(paths or [])
        if self._frozen_artifacts:
            logger.info(f"Frozen {len(self._frozen_artifacts)} artifacts: {self._frozen_artifacts}")

    def execute(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool call and return the result string."""
        handler = getattr(self, f"_handle_{tool_name}", None)
        if not handler:
            return f"ERROR: Unknown tool"

        before = self._reconciliation_observation()
        self._diagnostic_details = {}
        if tool_name == 'execute_python':
            self._capture_python_source(arguments.get('code'))
        result = None
        try:
            destination = (arguments.get('path') if tool_name == 'write_workspace_file'
                           else arguments.get('dst') if tool_name == 'copy_workspace_file' else None)
            if self._runtime_owned_reconciliation(destination):
                result = ('ERROR: RECONCILIATION_PRODUCER_VIOLATION: direct write/copy to '
                          'runtime-owned schema_reconciliation.yaml is prohibited by DL-G6. '
                          'No write performed. Validate existing producer output; save separate diagnostics.')
            else:
                result = handler(arguments)
        except Exception as e:
            error_msg = f"ERROR executing {tool_name}: {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            result = error_msg
        violation = self._record_producer_diagnostic(tool_name, arguments, before, result)
        if violation:
            return violation + ("\nOriginal tool error: " + result if isinstance(result, str) and result.startswith('ERROR') else '')
        return result

    def _runtime_owned_reconciliation(self, path):
        if not self._diagnostic_run or not isinstance(path, str):
            return False
        import posixpath
        return posixpath.normpath(path) == self._diagnostic_run['output_folder'] + '/schema_reconciliation.yaml'

    def _capture_python_source(self, source):
        """Capture generated code before execution, never process environment or output."""
        if not self._diagnostic_run or not isinstance(source, str):
            return
        import hashlib
        import uuid
        digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        path = (self._diagnostic_run['output_folder'] + '/diagnostics/python/'
                + digest + '-' + uuid.uuid4().hex + '.py')
        try:
            self._ws.write_file(path, source)
            if self._ws.read_file(path) != source:
                raise RuntimeError('Python diagnostic source readback mismatch')
            self._diagnostic_details.update(python_source_path=path, python_source_sha256=digest)
            logger.info('PYTHON_SOURCE_CAPTURED run_id=%s sha256=%s path=%s',
                        self._diagnostic_run['run_id'], digest, path)
        except Exception:
            self._diagnostic_details['python_source_capture'] = 'unavailable'
            logger.warning('PYTHON_SOURCE_CAPTURE_UNAVAILABLE sha256=%s', digest, exc_info=True)

    def _reconciliation_observation(self):
        if not self._diagnostic_run:
            return None
        import hashlib
        path = self._diagnostic_run['output_folder'] + '/schema_reconciliation.yaml'
        try:
            raw = self._ws.read_file(path)
            raw = raw.encode('utf-8') if isinstance(raw, str) else raw
            return dict(state='present', path=path, sha256=hashlib.sha256(raw).hexdigest(), raw=raw)
        except Exception as exc:
            # Preserve uncertainty; never turn a permission/transport error into absence.
            return dict(state='unreadable', path=path, error_type=type(exc).__name__)

    def _record_producer_diagnostic(self, tool, arguments, before, result):
        if not self._diagnostic_run:
            return
        import hashlib
        import uuid
        from datetime import datetime, timezone
        violation = None
        try:
            after = self._reconciliation_observation()
            if (tool != 'execute_notebook' and (before or {}).get('state') == 'present'
                    and (after or {}).get('state') == 'present'
                    and before['sha256'] != after['sha256']):
                violation = (
                    f"ERROR: RECONCILIATION_PRODUCER_VIOLATION: runtime-owned evidence changed across {tool}; "
                    f"path={after['path']}; before={before['sha256']}; after={after['sha256']}. "
                    "Stop checkpoint admission and downstream execution. Preserve evidence and investigate; "
                    "do not restore, rewrite, or rehash the artifact to manufacture VALID state."
                )
            event_id = uuid.uuid4().hex
            root = self._diagnostic_run['output_folder'] + '/diagnostics/reconciliation/'
            def evidence(observation, label):
                if observation is None:
                    return {'state': 'not_observed'}
                item = {k: v for k, v in observation.items() if k != 'raw'}
                if 'raw' in observation:
                    snapshot = root + event_id + '-' + label + '.yaml'
                    self._ws.write_file(snapshot, observation['raw'].decode('utf-8'))
                    item['snapshot_path'] = snapshot
                return item
            before_hash = (before or {}).get('sha256')
            after_hash = (after or {}).get('sha256')
            changed = before_hash != after_hash
            # Save exact bytes on transitions; retain hashes for the entire timeline.
            record = dict(event_id=event_id, observed_at=datetime.now(timezone.utc).isoformat(),
                run_id=self._diagnostic_run['run_id'], tool=tool,
                change_observed=changed,
                attribution='change observed across tool call; not proof of exclusive writer',
                before=evidence(before, 'before') if changed else {k:v for k,v in (before or {}).items() if k!='raw'},
                after=evidence(after, 'after') if changed else {k:v for k,v in (after or {}).items() if k!='raw'},
                execution=self._diagnostic_details, producer_violation=violation)
            # Do not retain arbitrary Python/SQL text, payloads, or credentials.
            record['paths'] = {k: arguments[k] for k in ('path', 'template_path', 'output_path')
                               if isinstance(arguments.get(k), str)}
            record['argument_source_sha256'] = {k: hashlib.sha256(arguments[k].encode()).hexdigest()
                for k in ('code', 'statement', 'content') if isinstance(arguments.get(k), str)}
            record['tool_failed'] = isinstance(result, str) and result.startswith(('ERROR', 'NOTEBOOK ERROR', 'SQL ERROR'))
            location = root + event_id + '.json'
            self._ws.write_file(location, json.dumps(record, sort_keys=True))
            logger.info('RECONCILIATION_DIAGNOSTIC tool=%s changed=%s evidence=%s', tool, changed, location)
        except Exception:
            # Diagnostic transport cannot replace the tool's original outcome.
            logger.warning('RECONCILIATION_DIAGNOSTIC_UNAVAILABLE tool=%s', tool, exc_info=True)
        return violation

    # SQL statements that are unsupported or dangerous in Databricks SQL / UC
    _SQL_BLOCKED_PATTERNS = [
        ('TRUNCATE', 'TRUNCATE TABLE is not supported in Databricks SQL (Unity Catalog). '
                     'Use DELETE FROM <table> instead, or DROP + CREATE.'),
        ('VACUUM',   'VACUUM should not be called by the pipeline agent. '
                     'It is a maintenance operation managed by Databricks.'),
    ]

    def _handle_execute_sql(self, args: dict) -> str:
        statement = args["statement"]

        # Multi-statement detection: Databricks SQL allows only ONE statement per call.
        # If the LLM sends "DROP ...; CREATE ...", split and execute sequentially.
        statements = self._split_sql_statements(statement)
        if len(statements) > 1:
            logger.info(f"Multi-statement SQL detected: splitting into {len(statements)} statements")
            results = []
            for i, stmt in enumerate(statements, 1):
                result = self._handle_execute_sql({"statement": stmt})
                results.append(f"[Statement {i}] {result}")
                if result.startswith("SQL ERROR") or result.startswith("SQL BLOCKED"):
                    results.append(f"(Remaining {len(statements) - i} statement(s) skipped due to error)")
                    break
            return "\n".join(results)

        # Pre-flight: block unsupported/dangerous SQL patterns
        stmt_upper = statement.strip().upper()
        for keyword, message in self._SQL_BLOCKED_PATTERNS:
            if stmt_upper.startswith(keyword):
                logger.warning(f"SQL BLOCKED: {keyword} statement rejected")
                return f"SQL BLOCKED: {message}"

        try:
            result = self._sql.execute_and_wait(statement)
        except Exception as e:
            statement_id = getattr(e, 'statement_id', '')
            self._diagnostic_details['sql_statement_id'] = statement_id or None
            if isinstance(e, TimeoutError) or 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
                code = 'SQL_EXECUTION_UNRESOLVED' if statement_id else 'SQL_SUBMISSION_OUTCOME_UNKNOWN'
                return (f"SQL ERROR: {code}: statement_id={statement_id or 'unavailable'}; {e}. "
                        "A timeout is not terminal SQL failure. Do not resubmit or cancel implicitly. "
                        "Inspect this statement via statement_execution.get_statement using the same workspace; "
                        "reconcile terminal status and target catalog readback before proceeding. "
                        "If no ID is available, return to master for execution reconciliation.")
            return f"SQL ERROR: statement_id={statement_id or 'unavailable'}; {e}"

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

    @staticmethod
    def _split_sql_statements(sql: str) -> list:
        """Split a multi-statement SQL string into individual statements.

        Handles semicolons inside string literals and comments.
        Returns a list of non-empty, stripped statements.
        """
        statements = []
        current = []
        in_single_quote = False
        in_line_comment = False
        in_block_comment = False
        i = 0
        chars = sql

        while i < len(chars):
            c = chars[i]

            # Track string literals
            if c == "'" and not in_line_comment and not in_block_comment:
                in_single_quote = not in_single_quote
                current.append(c)
            # Track line comments (-- ...)
            elif c == '-' and i + 1 < len(chars) and chars[i + 1] == '-' and not in_single_quote and not in_block_comment:
                in_line_comment = True
                current.append(c)
            elif c == '\n' and in_line_comment:
                in_line_comment = False
                current.append(c)
            # Track block comments (/* ... */)
            elif c == '/' and i + 1 < len(chars) and chars[i + 1] == '*' and not in_single_quote and not in_line_comment:
                in_block_comment = True
                current.append(c)
            elif c == '*' and i + 1 < len(chars) and chars[i + 1] == '/' and in_block_comment:
                in_block_comment = False
                current.append(c)
                current.append(chars[i + 1])
                i += 2
                continue
            # Semicolon outside of strings/comments = statement separator
            elif c == ';' and not in_single_quote and not in_line_comment and not in_block_comment:
                stmt = ''.join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
            else:
                current.append(c)
            i += 1

        # Last statement (no trailing semicolon)
        stmt = ''.join(current).strip()
        if stmt:
            statements.append(stmt)

        return statements

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

        # Guard: redirect template-based NOTEBOOK deployment paths to deploy_from_template.
        # This prevents the LLM from bypassing the template by writing notebook
        # content directly (which would allow it to rewrite helper functions).
        # IMPORTANT: Only block .py files (notebook deployments), NOT .yaml/.json
        # config files (dashboard_design.yaml, metric_view_validation.yaml, etc.)
        # which are legitimate LLM-generated artifacts.
        # Also skip .template files and paths in the templates/ directory (source files).
        filename = path.rstrip('/').split('/')[-1].lower()
        is_notebook_output = filename.endswith('.py') or filename.endswith('.ipynb')
        is_template_source = path.endswith('.template') or '/templates/' in path
        if is_notebook_output and not is_template_source:
            for stem in self._TEMPLATE_STEMS:
                if stem in filename:
                    return (
                        f"ERROR: This path contains '{stem}' which indicates "
                        f"a template-based deployment notebook. Per G-16, you MUST use "
                        f"the deploy_from_template tool instead of write_workspace_file. "
                        f"Call deploy_from_template with:\n"
                        f"  template_path: the .py.template file path\n"
                        f"  output_path: {path}\n"
                        f"  placeholders: dict of placeholder KEY -> value\n"
                        f"The tool reads the template verbatim and performs only "
                        f"placeholder substitution — cells 8-10 stay unchanged."
                    )

        # Artifact-gated phase skip: if this path is a frozen completion
        # artifact, refuse the write and tell the agent it's already done.
        if path in self._frozen_artifacts:
            logger.info(f"IDEMPOTENT SKIP: {path} is a frozen artifact from a completed phase")
            return (
                f"SKIPPED: {path} already exists (completed phase artifact). "
                f"This artifact is frozen and cannot be overwritten during resume. "
                f"If you need its content, use read_workspace_file instead."
            )

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
            # Permission/auth errors should be reported as hard errors
            if any(perm in err_str for perm in (
                'permission', 'forbidden', '403', 'unauthorized', '401',
                'access_denied', 'not_allowed',
            )):
                return f"ERROR: {str(e)}"
            # Everything else (not found, invalid path, workspace errors for
            # non-existent dirs) is treated as "directory doesn't exist yet".
            # This is the most common case for list_workspace_directory and
            # is NOT an error condition for the LLM.
            return f"DIRECTORY_NOT_FOUND: {path} does not exist yet. It will be created when needed."

    def _handle_create_dashboard(self, args: dict) -> str:
        """Redirect: Dashboard creation uses the deploy_from_template pattern."""
        return (
            "ERROR: create_dashboard tool is disabled. "
            "Use deploy_from_template instead: "
            "1) Write dashboard_design.yaml to the output folder (declarative spec). "
            "2) Call deploy_from_template with template_path=dashboard_notebook.py.template, "
            "output_path={OUTPUT_FOLDER}/dashboards/dashboard_deployment.ipynb, "
            "placeholders={DOMAIN_NAME, CATALOG, SCHEMA, VERSION_SUFFIX, WAREHOUSE_ID, "
            "PARENT_PATH, OUTPUT_FOLDER, DEPLOY_ROOT, METRIC_VIEW_FQNS, QUALITY_GATES}. "
            "3) Use execute_notebook to run it (template handles Lakeview API calls). "
            "DO NOT use write_workspace_file or import_notebook for dashboard_ notebook paths."
            "This is the ONLY supported path for dashboard creation."
        )

    def _handle_publish_dashboard(self, args: dict) -> str:
        """Redirect: Dashboard publishing is handled by the template notebook."""
        return (
            "ERROR: publish_dashboard tool is disabled. "
            "Dashboard publishing is handled automatically by the template notebook (Cell 7). "
            "Use the template notebook pattern — it deploys AND publishes in one step."
        )

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

        format_error = self._workspace_upload_format_check(code)
        if format_error:
            return format_error

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
                if 'zip archive contains no items' in stderr.lower():
                    stderr += (
                        "\nWORKSPACE_UPLOAD_FORMAT_ERROR: inspect the failing upload's path, bytes, "
                        "and format. Plain YAML/JSON/SQL/Markdown files require explicit "
                        "RAW transport (see agent_transport.md for SDK enum compatibility); do not use SOURCE/DBC or omit format. "
                        "Use the attested WorkspaceStore.write() for lifecycle files. "
                        "Inspect earlier writes before retrying the script."
                    )
                if ('inspect.py' in stderr and any(error in stderr for error in
                        ('is a built-in class', 'could not get source code', 'source code not available'))):
                    stderr += (
                        "\nHELPER_INTROSPECTION_ERROR: source reflection failed; this does not "
                        "establish a Workspace I/O error. Follow shared/agent_transport.md's "
                        "attested file-backed loader and register the module in sys.modules "
                        "before exec_module. Validate source bytes/digest and callable signatures, "
                        "not inspect.getsource. Inspect earlier side effects before a master-admitted retry."
                    )
                # Provide actionable guidance for common errors
                if "makedirs" in stderr and "Workspace" in stderr:
                    stderr += (
                        "\n\nHINT: /Workspace paths are not local filesystem paths. "
                        "Use the write_workspace_file tool instead of os.makedirs + open()."
                    )
                if ("copyfile" in stderr or "copy2" in stderr or "shutil" in stderr) and (
                    "Workspace" in stderr or "No such file" in stderr or "FileNotFoundError" in stderr
                ):
                    stderr += (
                        "\n\nHINT: shutil.copy/copy2 cannot copy /Workspace paths — they are "
                        "API paths, not local filesystem paths. Use the copy_workspace_file "
                        "tool to copy files between workspace paths, or use "
                        "read_workspace_file + write_workspace_file to read then write content."
                    )
                if "yaml" in stderr.lower() and ("dump" in stderr.lower() or "safe_dump" in stderr.lower() or "Representer" in stderr.lower()):
                    stderr += (
                        "\n\nHINT: yaml.safe_dump() cannot serialize complex Python objects "
                        "(SDK responses, custom classes, datetimes). Convert to plain "
                        "dicts/lists/strings first. If you need to write a YAML file to "
                        "/Workspace, use write_workspace_file tool with the YAML string "
                        "instead of execute_python + open()."
                    )
                # Diagnose the failing operation, not unrelated strings in the script.
                if (any(error in stderr for error in ('FileNotFoundError:', 'PermissionError:', 'OSError:'))
                        and '/Workspace/' in stderr and 'open(' in code):
                    stderr += (
                        "\n\nHINT: /Workspace paths are API-backed, not local filesystem. "
                        "Use write_workspace_file tool instead of open() in execute_python."
                    )
                return f"ERROR: {stderr}"
            return proc.stdout.strip() or "SUCCESS: executed (no output)."
        except _sp.TimeoutExpired:
            return "ERROR: Python execution timed out (120s limit)."
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    def _handle_copy_workspace_file(self, args: dict) -> str:
        """Copy a file between workspace paths via the Workspace API.

        This is the ONLY safe way to copy files between /Workspace paths.
        shutil.copy/copy2 will fail because /Workspace paths are API paths,
        not local filesystem paths.
        """
        src = args["src"]
        dst = args["dst"]
        try:
            content = self._ws.read_file(src)
            if content is None:
                return f"FILE_NOT_FOUND: Source file {src} does not exist."
            self._ws.write_file(dst, content)
            return f"SUCCESS: Copied {len(content)} bytes from {src} to {dst}"
        except Exception as e:
            return f"ERROR copying workspace file: {str(e)}"

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

    def _read_run_selection(self, path):
        """Authenticate a completed selection inside the tool's error boundary.

        Resolver allocation returns a future context path; only the master writes
        the context. A progress callback must never try to perform that bootstrap.
        """
        import posixpath
        import yaml
        root = self._config.example_dir.rstrip('/')
        if not isinstance(path, str) or not path:
            raise ValueError(
                'RUN_SELECTION_AUTHORITY_ERROR: stats.run_context_path must be a nonempty plain string; '
                f'received {path!r}. Expected the exact persisted run_context.yaml locator under {root!r}')
        if (posixpath.normpath(path) != path or not path.startswith(root + '/')
                or posixpath.basename(path) != 'run_context.yaml'):
            raise ValueError(
                f'RUN_SELECTION_AUTHORITY_ERROR: invalid domain context locator {path!r}; '
                f'expected a canonical path under {root!r} ending in /run_context.yaml. '
                'Copy the persisted selection locator; do not infer another version or normalize a different path.')
        class UniqueLoader(yaml.SafeLoader):
            pass
        def mapping(loader, node, deep=False):
            result = {}
            for key, value in node.value:
                key = loader.construct_object(key, deep=deep)
                if key in result:
                    raise ValueError('RUN_SELECTION_AUTHORITY_ERROR: duplicate contract key')
                result[key] = loader.construct_object(value, deep=deep)
            return result
        UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        context = yaml.load(self._ws.read_file(path), Loader=UniqueLoader)
        if not isinstance(context, dict):
            raise ValueError('RUN_SELECTION_AUTHORITY_ERROR: context must be a mapping')
        domain, version = context.get('domain'), context.get('version')
        domain = domain.get('name') if isinstance(domain, dict) else domain
        version = version.get('number') if isinstance(version, dict) else version
        if (domain != self._config.domain_name or context.get('created_by') != 'app'
                or context.get('run_context_path') != path
                or context.get('output_folder') != posixpath.dirname(path)
                or type(version) is not int or version < 1
                or not isinstance(context.get('run_id'), str) or not context['run_id']):
            raise ValueError('RUN_SELECTION_AUTHORITY_ERROR: context identity mismatch')
        self._diagnostic_run = dict(run_id=context['run_id'], output_folder=context['output_folder'])
        return dict(canonical_run_id=context['run_id'], run_context_path=path,
                    version=version, output_folder=context['output_folder'])

    def _handle_report_progress(self, args: dict) -> str:
        """Handle progress reporting from the LLM.

        This tool is called by the LLM at phase boundaries to signal what
        logical step is happening (e.g., Parse ERD, Build Semantic Model).
        The structured data flows to both:
        - App UI via SSE events (real-time)
        - App workspace snapshot and Lakebase mirror (persistent UI state)

        The master alone writes the canonical run manifest. Completed v2 selection
        events authenticate their context here so read errors become tool feedback,
        not exceptions escaping the UI callback.

        Returns a JSON string that the agent_event_bridge parses and
        re-emits as a 'phase_update' event.
        """
        import json
        progress = {
            "__progress_event__": True,  # Marker for agent_event_bridge
            "step_name": args.get("step_name"),
            "phase_id": args.get("phase_id", ""),
            "phase_name": args.get("phase_name", ""),
            "status": args.get("status", "update"),
            "current_task": args.get("current_task"),
            "progress_pct": args.get("progress_pct"),
            "stats": args.get("stats", {}),
            "happenings": args.get("happenings", []),
            "findings": args.get("findings", []),
        }
        if (getattr(self._config, 'agent_skills_version', None) == 'v2'
                and progress['phase_id'] == 'run_selected' and progress['status'] == 'completed'):
            try:
                stats = progress['stats']
                if not isinstance(stats, dict):
                    raise ValueError('RUN_SELECTION_AUTHORITY_ERROR: stats must be an object containing run_context_path')
                progress['_validated_run_selection'] = self._read_run_selection(stats.get('run_context_path'))
            except Exception as exc:
                guidance = (
                    "The resolver returns a locator; allocation does not create run_context.yaml. "
                    "Finish the master's freeze-and-persist step only if this invocation has not done so. "
                    if isinstance(exc, FileNotFoundError) else
                    "Check the supplied stats.run_context_path and persisted selection identity; "
                    "this reporting error alone does not establish that bootstrap is incomplete. "
                )
                return (
                    f"ERROR: RUN_SELECTION_NOT_ACKNOWLEDGED: {exc}. " + guidance +
                    "Verify the exact persisted context before reporting run_selected completed. "
                    "Do not allocate another version, invent or overwrite context, or replay setup to fix telemetry. "
                    "Report Setup using step_name=environment_setup and its own phase, not run_selected."
                )
        logger.info(f"Progress: {progress['phase_name']} [{progress['status']}]")
        return json.dumps(progress)


    def _handle_report_step_complete(self, args: dict) -> str:
        return json.dumps({
            "step_complete": True,
            "summary": args["summary"],
            "artifacts": args.get("artifacts", []),
            "status": args.get("status", "success"),
        })

    # --- Template enforcement ---
    # Known template filenames. If import_notebook receives content for a
    # notebook whose filename contains one of these stems, it redirects to
    # deploy_from_template to guarantee the template is used verbatim (G-16).
    _TEMPLATE_STEMS = ('ddl_', 'dbldatagen_', 'metric_view_', 'dashboard_', 'genie_space_')

    def _handle_deploy_from_template(self, args: dict) -> str:
        """Deploy a notebook by reading a template and replacing placeholders.

        This is the ONLY correct way to create deployment notebooks (G-16).
        The LLM provides placeholder values; this tool reads the template
        verbatim and performs deterministic string substitution.
        """
        template_path = args["template_path"]
        output_path = args["output_path"]
        placeholders = args.get("placeholders", {})
        language = args.get("language", "PYTHON").upper()

        # 1. Read the template
        try:
            template_content = self._ws.read_file(template_path)
        except Exception as e:
            return f"ERROR: Cannot read template at {template_path}: {e}"

        if not template_content or not template_content.strip():
            return f"ERROR: Template at {template_path} is empty."

        if getattr(self._config, 'agent_skills_version', None) == 'v2':
            import hashlib
            import posixpath
            import yaml
            release = yaml.safe_load(self._ws.read_file(
                self._config.framework_root + '/agent_skills/v2/contracts/release.yaml'))
            allowed = {posixpath.normpath(self._config.deploy_root+'/'+p)
                       for p in release['templates'].values()}
            if template_path not in allowed:
                return 'ERROR: TEMPLATE_AUTHORITY_ERROR: template is not selected by the v2 release manifest'
            # Persisted artifacts are authority, never an earlier UI event.
            context_path = args.get('run_context_path') or placeholders.get('RUN_CONTEXT_PATH')
            if not context_path and isinstance(placeholders.get('OUTPUT_FOLDER'), str):
                context_path = placeholders['OUTPUT_FOLDER'].rstrip('/') + '/run_context.yaml'
            if not context_path:
                return 'ERROR: TEMPLATE_AUTHORITY_ERROR: provide the persisted run_context_path'
            selection = self._read_run_selection(context_path)
            if (posixpath.normpath(output_path) != output_path
                    or not output_path.startswith(selection['output_folder'].rstrip('/') + '/')):
                return 'ERROR: TEMPLATE_AUTHORITY_ERROR: output path is outside the authenticated run'
            if ('OUTPUT_FOLDER' in placeholders and
                    placeholders['OUTPUT_FOLDER'] != selection['output_folder']):
                return 'ERROR: TEMPLATE_AUTHORITY_ERROR: OUTPUT_FOLDER differs from persisted run context'
            if ('RUN_CONTEXT_PATH' in placeholders and placeholders['RUN_CONTEXT_PATH'] != context_path):
                return 'ERROR: TEMPLATE_AUTHORITY_ERROR: conflicting run context locators'
            context = yaml.safe_load(self._ws.read_file(context_path))
            references = [ref for ref in context.get('templates', {}).values()
                          if isinstance(ref, dict) and ref.get('path') == template_path]
            digest = hashlib.sha256(template_content.encode('utf-8')).hexdigest()
            if len(references) != 1 or references[0].get('sha256') != digest:
                return 'ERROR: TEMPLATE_AUTHORITY_ERROR: template does not match the frozen path/digest'

        # Validate the actual template interface before importing anything.
        import re
        required = set(re.findall(r'\{\{([A-Z_][A-Z0-9_]*)\}\}', template_content))
        invalid = sorted(key for key in required if key not in placeholders
                         or placeholders[key] is None or not str(placeholders[key]).strip())
        if invalid:
            return (f"ERROR: TEMPLATE_BINDING_ERROR: missing or empty placeholders: {invalid}. "
                    f"Bind every placeholder from the authenticated handoff. "
                    f"No notebook was imported. Template: {template_path}")

        # 2. Deterministic placeholder substitution
        result = template_content
        applied = []
        missing = []
        for key, value in placeholders.items():
            placeholder = "{{" + key + "}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
                applied.append(key)
            else:
                missing.append(key)

        # 3. Check for unreplaced placeholders in the result
        import re
        unreplaced = re.findall(r'\{\{([A-Z_][A-Z0-9_]*)\}\}', result)
        if unreplaced:
            unique_unreplaced = sorted(set(unreplaced))
            return (
                f"ERROR: Template has unreplaced placeholders: {unique_unreplaced}. "
                f"Provide values for ALL placeholders. Applied: {applied}. "
                f"Template path: {template_path}"
            )

        # 4. Import as notebook
        import hashlib
        self._diagnostic_details.update(template_sha256=hashlib.sha256(template_content.encode()).hexdigest(),
            rendered_source_sha256=hashlib.sha256(result.encode()).hexdigest())
        try:
            self._ws.import_notebook(output_path, result, language=language)
        except Exception as e:
            return f"ERROR importing notebook from template: {e}"

        template_lines = len(template_content.splitlines())
        result_lines = len(result.splitlines())

        report = (
            f"SUCCESS: Deployed notebook from template.\n"
            f"  Template: {template_path} ({template_lines} lines)\n"
            f"  Output:   {output_path} ({result_lines} lines)\n"
            f"  Placeholders applied: {applied}\n"
            f"  Language: {language}"
        )
        if missing:
            report += f"\n  WARNING: Placeholder keys not found in template: {missing}"

        return report

    def _handle_import_notebook(self, args: dict) -> str:
        """Import a notebook to workspace using the Workspace API.

        For template-based notebooks (DDL, dbldatagen, metric_view, dashboard,
        genie_space), use deploy_from_template instead — it guarantees the
        template is used verbatim per G-16.
        """
        path = args["path"]
        nb_content = args["content"]
        language = args.get("language", "PYTHON").upper()

        # Guard: redirect template notebooks to deploy_from_template
        # Skip for .template files and paths in templates/ directory (source files)
        if not path.endswith('.template') and '/templates/' not in path:
            filename = path.rstrip('/').split('/')[-1].lower()
            for stem in self._TEMPLATE_STEMS:
                if stem in filename:
                    return (
                    f"ERROR: This notebook path contains '{stem}' which indicates "
                    f"a template-based deployment notebook. Per G-16, you MUST use "
                    f"the deploy_from_template tool instead of import_notebook. "
                    f"Call deploy_from_template with:\n"
                    f"  template_path: the .py.template file path\n"
                    f"  output_path: {path}\n"
                    f"  placeholders: dict of {{{{KEY}}}}: value pairs\n"
                    f"This ensures the template is used verbatim with only "
                    f"placeholder substitution — no LLM modification."
                )

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
            if self._diagnostic_run:
                try:
                    import hashlib
                    source = self._ws.read_file(path)
                    self._diagnostic_details['executed_source_sha256'] = hashlib.sha256(
                        source.encode() if isinstance(source, str) else source).hexdigest()
                except Exception as exc:
                    self._diagnostic_details['source_read_error_type'] = type(exc).__name__
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
            self._diagnostic_details['notebook_run_id'] = run_id
            logger.info('NOTEBOOK_SUBMITTED path=%s run_id=%s source_sha256=%s', path, run_id,
                        self._diagnostic_details.get('executed_source_sha256'))

            # Wait for completion
            result = self._jobs.wait_for_run(run_id, timeout_s=timeout_minutes * 60)

            if result.result_state == "SUCCESS":
                duration_str = f" ({result.duration_s:.1f}s)" if result.duration_s else ""
                output = result.output or "No output captured."
                return f"SUCCESS: Notebook executed (run_id={run_id}){duration_str}. Output: {output}"
            else:
                error_detail = result.error or "Unknown error"
                return f"NOTEBOOK ERROR (run_id={run_id}): {error_detail}"
        except Exception as e:
            return f"ERROR executing notebook: {str(e)}"

    @staticmethod
    def _workspace_upload_format_check(code: str) -> str | None:
        """Reject direct SDK writes with omitted formats before execution."""
        import ast
        try:
            tree = ast.parse(code)
        except SyntaxError:
            tree = None  # Let Python return its normal syntax diagnostic below.
        for node in ast.walk(tree) if tree is not None else ():
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('upload', 'import_')
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == 'workspace'
                    and not any(k.arg in ('format', None) for k in node.keywords)):
                return (
                    f"ERROR: WORKSPACE_UPLOAD_FORMAT_REQUIRED at line {node.lineno}. "
                    "Use the attested WorkspaceStore.write() for lifecycle files. "
                    "For other plain files use explicit RAW transport with the older-SDK fallback in agent_transport.md, "
                    "with UTF-8 bytes for upload (base64 text for import_). "
                    "Notebook imports require their explicit SOURCE/language or JUPYTER format. "
                    "No Python code was executed."
                )

        return None

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
                return f"ERROR: NOTEBOOK_PREFLIGHT_ERROR: empty source at {path}; no job submitted."
        except Exception as exc:
            return f"ERROR: NOTEBOOK_PREFLIGHT_ERROR: cannot inspect {path}: {exc}; no job submitted."

        # Split into cells (Databricks source format)
        cell_separator = "# COMMAND ----------"
        cells = source.split(cell_separator)

        errors = []
        for idx, cell in enumerate(cells):
            cell_stripped = cell.strip()
            if not cell_stripped:
                continue

            # Skip non-Python cells (magic commands)
            # Look past DBTITLE / comment-only preamble lines to find the
            # first real code line — it may be a cell magic like %pip.
            cell_lines = cell_stripped.split('\n')
            first_code_line = ''
            for cl in cell_lines:
                stripped = cl.strip()
                if stripped and not stripped.startswith('#'):
                    first_code_line = stripped
                    break
            if first_code_line.startswith('%') and not first_code_line.startswith('%%'):
                if any(first_code_line.startswith(f'%{m}') for m in ['pip', 'sql', 'md', 'sh', 'r', 'scala', 'fs']):
                    continue
            # Also skip if ANY line is a bare magic (e.g. %pip after comments)
            if any(l.strip().startswith('%pip') for l in cell_lines):
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

            format_error = self._workspace_upload_format_check(cell_stripped)
            if format_error:
                return f"{format_error} Notebook: {path}, cell {idx + 1}; no job submitted."

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

        # Gate 3: Detect JSON-style booleans/null (true/false/null instead of True/False/None)
        # LLMs frequently emit JSON booleans in Python code. compile() won't catch these
        # because `true`, `false`, `null` are valid identifiers — they cause NameError at runtime.
        json_bool_errors = self._detect_json_booleans(source)
        errors.extend(json_bool_errors)

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

    @staticmethod
    def _detect_json_booleans(source: str) -> list:
        """Detect JSON-style booleans/null used as Python identifiers.

        LLMs frequently emit `true`/`false`/`null` instead of Python's
        `True`/`False`/`None`. These compile fine (valid identifiers) but
        cause NameError at runtime.

        Returns list of error description strings.
        """
        import re
        issues = []
        cell_separator = "# COMMAND ----------"
        cells = source.split(cell_separator)

        for idx, cell in enumerate(cells):
            for lineno, line in enumerate(cell.split('\n'), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                # Check for bare true/false/null as standalone identifiers
                for json_kw, py_kw in [('true', 'True'), ('false', 'False'), ('null', 'None')]:
                    if re.search(r'\b' + json_kw + r'\b', line):
                        # Exclude occurrences inside string literals (simple heuristic)
                        # Remove single and double quoted strings, then re-check
                        no_strings = re.sub(r'""".*?"""', '', line, flags=re.DOTALL)
                        no_strings = re.sub(r"'''.*?'''", '', no_strings, flags=re.DOTALL)
                        no_strings = re.sub(r'"[^"]*"', '', no_strings)
                        no_strings = re.sub(r"'[^']*'", '', no_strings)
                        if re.search(r'\b' + json_kw + r'\b', no_strings):
                            issues.append(
                                f"Cell {idx + 1}, line {lineno}: "
                                f"JSON-style `{json_kw}` found (causes NameError at runtime). "
                                f"Replace with Python `{py_kw}`.\n"
                                f"  Code: {stripped}"
                            )
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
