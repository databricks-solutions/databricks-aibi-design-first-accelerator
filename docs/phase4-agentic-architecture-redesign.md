# Phase 4: Agentic Architecture Redesign

## Goal

Rebuild the App orchestrator to mirror **Genie Code agent behavior** — a multi-turn LLM agent loop where:
- The LLM decides what to do based on prompts
- Python code is ONLY tool implementations (zero business logic)
- Context accumulates naturally in conversation history
- All intelligence lives in the prompts and templates

---

## Current Architecture (Problems)

```
Supervisor (agent loop)
  → calls tool by name (e.g. "create_data_layer")
    → GenericToolExecutor.execute()
      → routes by tool_type / execution_type
        → StageAgent.run_notebook_stage()  ← BUSINESS LOGIC HERE
          → loads templates
          → builds instruction (constraints, forbidden lists)
          → calls LLM once (single-shot)
          → writes notebook
          → executes via Jobs API
          → validates
```

**Problems:**
1. Business logic leaks into Python (template loading, instruction building, constraints)
2. Single-shot LLM call — no multi-turn reasoning within a step
3. Python code overrides/contradicts what prompts already define
4. Each error requires Python code changes instead of prompt fixes
5. Context doesn't flow naturally — each step builds its own context in isolation
6. The prompts define a multi-step flow (read ERD → parse → DDL → synthetic data) but the Python forces it into one LLM call

---

## Target Architecture (Genie Code in App)

```
Supervisor (outer agent loop)
  → LLM reads master prompt + conversation history
  → LLM calls a tool (e.g. "create_data_layer")
    → StageExecutor (inner agent loop for this step)
      → Loads stage prompt (01_create_data_layer.md)
      → Runs its OWN multi-turn agent loop with tools:
        - read_file(path) → reads workspace files
        - write_file(path, content) → writes workspace files
        - import_notebook(path, content) → writes notebook
        - execute_notebook(path) → runs via Jobs API, returns output
        - execute_sql(statement) → SQL Statement API
        - call_api(method, endpoint, body) → REST API calls
        - read_image(path) → returns image bytes for vision
      → LLM follows the prompt step-by-step, calling tools as needed
      → Context accumulates in the inner conversation
      → Returns result to supervisor (which adds it to outer conversation)
```

### Key Insight

In **Genie Code mode**, the LLM:
1. Reads the prompt
2. Calls `readAssetById` to load templates, config files
3. Calls `executeCode` to run SQL, write files, call APIs
4. Iterates — reads results, fixes errors, continues

In **App mode**, we replicate this EXACT behavior:
1. LLM reads the prompt (loaded by Python and passed as system/user message)
2. Calls `read_file` tool to load templates, config files
3. Calls `execute_sql`, `import_notebook`, `execute_notebook`, `call_api` tools
4. Iterates — reads results, fixes errors, continues

**The prompts stay IDENTICAL. The tools are equivalent. The only difference is the execution environment.**

---

## Tool Registry

### Tools the LLM needs (derived from prompts)

| Tool | Purpose | Used By Steps | Equivalent in Genie Code |
|------|---------|---------------|-------------------------|
| `read_file` | Read any workspace file (yaml, md, templates, configs) | All | `readAssetById` |
| `write_file` | Write text file to workspace (yaml, md, json, sql) | All | `editAsset` / `executeCode` |
| `read_image` | Read binary image file (ERD) for vision model | 01 | `readAssetById` (binary) |
| `import_notebook` | Write a notebook to workspace (Python or SQL) | 01 | `editAsset` (notebook) |
| `execute_notebook` | Run a notebook via Jobs API, return output/error | 01 | `executeCode` (run cells) |
| `execute_sql` | Execute SQL on warehouse (Statement Execution API) | 01, 02 | `executeCode` (SQL) |
| `call_api` | Call Databricks REST API (Lakeview, Genie, etc.) | 03, 04 | `executeCode` (Python SDK) |
| `list_files` | List directory contents | All | `readAssetById` (directory) |
| `delete_file` | Delete workspace file/folder | 01 (clean_start) | `executeCode` |

### Tool Signatures

```python
def read_file(path: str) -> str:
    """Read a workspace file. Returns content as string."""

def write_file(path: str, content: str) -> str:
    """Write content to a workspace file. Creates dirs if needed. Returns confirmation."""

def read_image(path: str) -> bytes:
    """Read binary file (image). Used with vision model for ERD parsing."""

def import_notebook(path: str, content: str, language: str = "PYTHON") -> str:
    """Import a notebook to workspace. Returns confirmation."""

def execute_notebook(path: str, timeout_minutes: int = 15) -> str:
    """Execute notebook via Jobs API. Returns success message or full error trace."""

def execute_sql(statement: str) -> str:
    """Execute SQL on configured warehouse. Returns result summary or error."""

def call_api(method: str, endpoint: str, body: dict = None) -> str:
    """Call Databricks REST API. Returns response body or error."""

def list_files(path: str) -> str:
    """List directory contents. Returns file/folder names."""

def delete_file(path: str, recursive: bool = False) -> str:
    """Delete workspace file or folder."""
```

---

## Execution Flow

### Supervisor (Outer Loop)

```
1. Load master prompt → system message
2. Build user message (domain, config summary)
3. Agent loop:
   a. Call LLM with conversation history + tools (high-level step tools)
   b. LLM decides which step to execute (e.g. "create_data_layer")
   c. Execute the step → returns result string
   d. Append result to conversation → LLM sees context from previous steps
   e. LLM decides next step (or reports complete)
```

### Stage Executor (Inner Loop — per step)

```
1. Load stage prompt (e.g. 01_create_data_layer.md) → system message
2. Build user message with runtime context:
   - catalog, schema, version_suffix, output_folder, domain_path
   - Previous step results (from supervisor conversation)
3. Inner agent loop (max iterations):
   a. Call LLM with stage conversation + low-level tools
   b. LLM calls tools: read_file, write_file, execute_notebook, etc.
   c. Tool results go back into conversation
   d. LLM continues following the prompt step-by-step
   e. LLM signals completion (returns final result)
4. Return result to supervisor
```

### Context Flow Between Steps (MINIMAL — Optimize for Token Cost)

Each step is **self-sustained**. It does NOT need results from previous steps passed in.
Each prompt already knows how to discover what it needs:

- Step 3 (data layer): reads ERD image, creates tables
- Step 4 (metric views): runs `SHOW TABLES` / `DESCRIBE` to discover tables for its version
- Step 5 (dashboards): reads metric views via SQL, builds dashboards

**What the supervisor passes to each step (runtime context only):**
```yaml
catalog: aw_serverless_stable_catalog
schema: aibi_member_claims
version: 1
version_suffix: _v1
output_folder: /Workspace/.../generated_outputs/v1
domain: member_claims
domain_path: /Workspace/.../kpi_domains/member_claims
deploy_root: /Workspace/.../databricks-aibi-design-first-accelerator
sql_warehouse_id: 2d8e531640ffa469
workspace_host: https://...
```

**What the supervisor does NOT pass:**
- Table lists (each step discovers via `SHOW TABLES IN ... LIKE '%_v1'`)
- Column schemas (each step runs `DESCRIBE TABLE`)
- Previous step artifacts (each step reads files via `read_file` tool if needed)
- Full validation results from prior steps

**Why:** This keeps context minimal. Each step runs in its own conversation. The prompt defines self-contained discovery logic. No token waste on passing data the LLM can query itself.

**Supervisor conversation stays thin:**
```
Step 1 result: "Config loaded. Output folder: .../v1"
Step 2 result: "Schema exists. 0 tables (clean start)."
Step 3 result: "8 tables created, validated. See data_layer_validation.yaml."
Step 4 result: "3 metric views created. See metric_view_validation.yaml."
...
```

Just status summaries — not full data. Each step's prompt knows how to find what it needs.

---

## Architecture Comparison

| Aspect | Current | Target |
|--------|---------|--------|
| Business logic | In Python (stage_agent.py) | In prompts only |
| Template loading | Python loads and injects | LLM calls `read_file` tool |
| Error handling | Python catches and reports | LLM reads error, retries (max 3) then hard fails |
| Multi-step within a stage | Single LLM call | Multi-turn inner loop (bounded) |
| Context between steps | Manually built by Python | Natural conversation history |
| Fixing issues | Change Python code | Change prompts |
| Tool type routing | Python switch/case | LLM decides which tool to call |
| Instruction building | Python f-strings | Prompt defines everything |

---

## Self-Correction & Retry Limits (Cost Control)

The inner agent loop allows self-correction (like Genie Code), but is **bounded** to prevent token waste:

```yaml
# Configurable in accelerator.yaml or StageExecutor
max_tool_errors_per_stage: 3   # Hard fail after 3 consecutive tool errors
max_iterations_per_stage: 30   # Hard fail after 30 tool-calling turns
```

**Behavior:**
- If a tool returns an error, increment error counter
- If LLM successfully calls a different tool (making progress), reset counter
- If error counter hits `max_tool_errors_per_stage` → **HARD FAIL immediately**
- If total iterations hit `max_iterations_per_stage` → **HARD FAIL**
- Return the full error trace to the supervisor for UI display
- Do NOT keep retrying — tokens are expensive

**Example:** Notebook fails with `COLUMN_ALREADY_EXISTS`. LLM reads error, fixes notebook, re-executes. If it fails again (same or different error), tries once more. Third failure → hard error returned to supervisor → pipeline halts → UI shows full error.

This gives 2-3 chances to self-correct (sufficient for fixable issues) without burning tokens on unfixable problems.

---

## File Structure (After Redesign)

```
app/orchestrator/
  supervisor.py          → Outer agent loop (keep mostly as-is)
  stage_executor.py      → Inner agent loop (NEW — replaces stage_agent.py)
  tool_implementations.py → Pure tool functions (NEW — replaces generic_tool_executor.py)
  tool_parser.py         → Keep (parses @tool from master prompt)
  event_parser.py        → Keep (parses @progress markers)
  models.py             → Keep (data models)

DELETE:
  generic_tool_executor.py  → Replaced by tool_implementations.py
  stage_agent.py            → Replaced by stage_executor.py
```

### `tool_implementations.py` (Pure Functions, Zero Logic)

```python
class ToolImplementations:
    """Pure tool implementations. No business logic. Just I/O."""

    def __init__(self, workspace_service, sql_service, config):
        self._ws = workspace_service
        self._sql = sql_service
        self._config = config

    def read_file(self, path: str) -> str: ...
    def write_file(self, path: str, content: str) -> str: ...
    def read_image(self, path: str) -> bytes: ...
    def import_notebook(self, path: str, content: str, language: str) -> str: ...
    def execute_notebook(self, path: str, timeout_minutes: int) -> str: ...
    def execute_sql(self, statement: str) -> str: ...
    def call_api(self, method: str, endpoint: str, body: dict) -> str: ...
    def list_files(self, path: str) -> str: ...
    def delete_file(self, path: str, recursive: bool) -> str: ...
```

### `stage_executor.py` (Inner Agent Loop)

```python
class StageExecutor:
    """Runs a single pipeline stage as a multi-turn agent loop.

    The LLM follows the stage prompt, calling tools as needed.
    Python is ONLY the loop + tool dispatch. Zero business logic.
    """

    def __init__(self, llm_client, tools: ToolImplementations, config):
        self._llm = llm_client
        self._tools = tools
        self._config = config

    def execute_stage(self, stage_prompt: str, runtime_context: str,
                      image_bytes: bytes = None, max_iterations: int = 50) -> str:
        """Run the stage as a multi-turn agent.

        Args:
            stage_prompt: Full content of the stage prompt file (e.g. 01_create_data_layer.md)
            runtime_context: YAML string with catalog, schema, version, output_folder, etc.
            image_bytes: Optional ERD image for vision stages
            max_iterations: Max tool-calling turns

        Returns:
            Final result string from the LLM (validation results, artifact paths, etc.)
        """
        messages = [
            {"role": "system", "content": stage_prompt},
            {"role": "user", "content": runtime_context},
        ]

        for _ in range(max_iterations):
            response = self._call_llm(messages, image_bytes)
            # image only sent on first call
            image_bytes = None

            message = response["choices"][0]["message"]
            messages.append(message)

            tool_calls = message.get("tool_calls", [])
            if not tool_calls:
                # LLM is done — return its final content
                return message.get("content", "")

            # Execute each tool and add results to conversation
            for tc in tool_calls:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])
                result = self._dispatch_tool(name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        return "ERROR: Stage hit max iterations without completing"
```

---

## How Each Step Works (After Redesign)

### Step 3: create_data_layer (example)

Current (single-shot, Python business logic):
```
Python loads template → Python builds instruction → one LLM call → Python writes → Python executes
```

Target (multi-turn, prompt-driven):
```
Turn 1: LLM reads prompt, calls read_file("accelerator.yaml")
Turn 2: LLM reads config, calls read_file("templates/ddl_notebook.py.template")
Turn 3: LLM reads template, calls read_file("inputs/erd.png") [vision]
Turn 4: LLM parses ERD, calls write_file("generated_outputs/v1/contracts/erd_parsed.yaml", ...)
Turn 5: LLM generates DDL, calls import_notebook("generated_outputs/v1/notebooks/ddl_member_claims.ipynb", ...)
Turn 6: LLM calls execute_notebook("generated_outputs/v1/notebooks/ddl_member_claims.ipynb")
Turn 7: LLM sees success, calls read_file("templates/dbldatagen_notebook.py.template")
Turn 8: LLM generates synthetic data notebook, calls import_notebook(...)
Turn 9: LLM calls execute_notebook(...)
Turn 10: LLM sees success, calls execute_sql("SELECT COUNT(*) FROM information_schema.tables...")
Turn 11: LLM validates tables exist, returns final result
```

If Step 9 fails (e.g. duplicate columns), the LLM sees the error in conversation, can:
- Read the notebook it wrote
- Understand the error
- Fix and re-write the notebook
- Re-execute

**This is EXACTLY what Genie Code does.** The LLM self-corrects.

---

## Supervisor Changes

### Current `_execute_tool`:
```python
def _execute_tool(self, tool_name, args, config):
    return self._tool_executor.execute(tool_name, tool_type, args, config, prompt_context)
```

### Target `_execute_tool`:
```python
def _execute_tool(self, tool_name, args, config):
    # Load the stage prompt
    stage_prompt_file = STAGE_PROMPT_MAP.get(tool_name)
    stage_prompt = self._read_file(f"{config.deploy_root}/framework/prompts/{stage_prompt_file}")

    # Build runtime context (just facts, no instructions)
    runtime_context = f"""
    catalog: {config.catalog}
    schema: {config.schema}
    version: {config.version}
    version_suffix: _v{config.version}
    output_folder: {config.output_folder}
    domain: {config.domain}
    domain_path: {config.domain_path}
    deploy_root: {config.deploy_root}
    sql_warehouse_id: {config.sql_warehouse_id}
    workspace_host: {config.workspace_host}
    """

    # Check if vision input needed
    image_bytes = None
    step_config = get_step_config(tool_name, config)
    if step_config.get("vision_input"):
        image_bytes = self._tools.read_image(f"{config.domain_path}/inputs/erd.png")

    # Run the stage as a multi-turn agent
    return self._stage_executor.execute_stage(
        stage_prompt=stage_prompt,
        runtime_context=runtime_context,
        image_bytes=image_bytes,
    )
```

---

## What Stays vs What Goes

### KEEP (infrastructure that works)
- `supervisor.py` outer agent loop structure
- `tool_parser.py` — parses @tool definitions from master prompt
- `event_parser.py` — parses @progress markers for UI
- `models.py` — data models
- `supervisor_routes.py` — Flask routes, version detection
- All prompt files (01-06)
- All template files
- `workspace_file_io.md`

### REWRITE
- `generic_tool_executor.py` → `tool_implementations.py` (pure tool functions)
- `stage_agent.py` → `stage_executor.py` (inner agent loop)

### REMOVE
- All business logic in Python (instruction building, template loading, constraints, forbidden lists)
- `_build_sql_instruction`, `_build_context`, `_load_upstream_artifacts`
- `run_notebook_stage`, `run_sql_stage`, `run_api_stage`, `run_file_stage`
- `_handle_vision`, `_handle_sql`, `_handle_api`, `_handle_file`
- `_get_execution_type` routing

---

## Token / Context Window Considerations

### Per-stage context size
| Stage | Prompt Size | Templates Loaded | Estimated Context |
|-------|-------------|-----------------|-------------------|
| 01 create_data_layer | ~35K chars | ddl_template + dbldatagen_template (~10K) | ~50K chars |
| 02 create_metric_views | ~30K chars | metric_view_yaml header (~2K) | ~35K chars |
| 03 create_dashboards | ~45K chars | lakeview_dashboard_helpers (~5K) | ~55K chars |
| 04 create_genie_space | ~33K chars | genie_space_notebook (~3K) | ~40K chars |
| 05 generate_documentation | ~18K chars | none | ~20K chars |

With multi-turn (10-15 turns per stage), conversation grows. Use `max_tokens: 32768` for generation. Total context per stage: ~100-150K tokens (within GPT-4/5 context windows).

### Mitigation
- Each stage runs in its OWN conversation (inner loop) — resets context per step
- Only the RESULT of each stage flows to the supervisor (outer loop)
- Templates are loaded ON DEMAND by the LLM (via `read_file` tool) — not pre-loaded

---

## Migration Plan

1. **Create `tool_implementations.py`** — pure functions wrapping existing service methods
2. **Create `stage_executor.py`** — inner agent loop with tool dispatch
3. **Update `supervisor.py` `_execute_tool`** — delegate to stage_executor
4. **Remove `generic_tool_executor.py`** and `stage_agent.py`
5. **Update `supervisor_routes.py`** — instantiate new classes
6. **Test** — deploy and run pipeline end-to-end

---

## Benefits

1. **Self-correcting**: LLM sees errors, can fix and retry (like Genie Code)
2. **Prompt-driven**: All changes go to prompts, not Python
3. **Consistent**: Same prompts work in both Genie Code and App mode
4. **Debuggable**: Full conversation history shows exactly what the LLM did
5. **Simpler Python**: ~200 lines of pure tool functions vs 1000+ lines of business logic
6. **No duplicate issues**: LLM follows the prompt's two-notebook flow naturally
