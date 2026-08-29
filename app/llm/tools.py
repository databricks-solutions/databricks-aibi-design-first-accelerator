"""Tool definitions for the LLM agent loop.

These mirror the capabilities that Genie Code has when executing
framework prompts. The LLM calls these tools to interact with
Databricks APIs (SQL, Workspace Files, Lakeview, Genie).

The tool schemas follow OpenAI function-calling format, which is
supported by Databricks Foundation Model API endpoints.
"""

# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": (
                "Execute a SQL statement on the configured SQL warehouse. "
                "Use for DDL (CREATE TABLE, CREATE VIEW), DML (INSERT), and queries (SELECT). "
                "Returns column names and up to 1000 result rows for queries. "
                "For DDL/DML, returns affected row count or success status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "statement": {
                        "type": "string",
                        "description": "The SQL statement to execute."
                    },
                    "wait_timeout": {
                        "type": "string",
                        "description": "Max wait time (e.g. '30s', '50s'). Default '50s'.",
                        "default": "50s"
                    }
                },
                "required": ["statement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_workspace_file",
            "description": (
                "Read the content of a workspace file. Use to load templates, "
                "configurations (accelerator.yaml, kpi_spec.md), prompt files, "
                "or previously generated artifacts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute workspace path (e.g. /Workspace/Users/user/project/file.md)"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_workspace_file",
            "description": (
                "Write content to a workspace file. Creates the file if it doesn't exist, "
                "overwrites if it does. Use for generating artifacts (YAML, JSON, SQL, notebooks)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute workspace path for the file."
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace_directory",
            "description": (
                "List files and folders in a workspace directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute workspace directory path."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_dashboard",
            "description": (
                "Create or update a Lakeview dashboard. Provide the full serialized_dashboard "
                "JSON string. If dashboard_id is provided, updates existing; otherwise creates new."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "display_name": {
                        "type": "string",
                        "description": "Dashboard display name."
                    },
                    "serialized_dashboard": {
                        "type": "string",
                        "description": "Full Lakeview serialized_dashboard JSON string."
                    },
                    "dashboard_id": {
                        "type": "string",
                        "description": "Existing dashboard ID to update. Omit to create new."
                    },
                    "warehouse_id": {
                        "type": "string",
                        "description": "SQL warehouse ID for the dashboard."
                    }
                },
                "required": ["display_name", "serialized_dashboard", "warehouse_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "publish_dashboard",
            "description": "Publish a draft dashboard to make it visible to users.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dashboard_id": {
                        "type": "string",
                        "description": "The dashboard ID to publish."
                    },
                    "warehouse_id": {
                        "type": "string",
                        "description": "SQL warehouse ID for published execution."
                    }
                },
                "required": ["dashboard_id", "warehouse_id"]
            }
        }
    },
    # NOTE: create_genie_space removed — Genie space creation is prompt-driven
    # via the template notebook (import_notebook + execute_notebook pattern),
    # same as synthetic data generation. See 04_create_genie_space.md.
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": (
                "Run DESCRIBE TABLE EXTENDED on a Unity Catalog table or metric view. "
                "Returns column names, types, comments, and table properties."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Fully qualified table name (catalog.schema.table)."
                    }
                },
                "required": ["table_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": (
                "Execute a short Python snippet in a local subprocess (NO Spark, NO SDK). "
                "Use ONLY for: JSON/YAML manipulation, string formatting, UUID generation, "
                "simple math/logic. "
                "Do NOT use for: PySpark/DataFrames, dbldatagen, Databricks SDK calls "
                "(w.lakeview.*, w.api_client.*), /Workspace file I/O, or API calls. "
                "For PySpark/dbldatgen: use import_notebook + execute_notebook. "
                "For dashboards: use create_dashboard/publish_dashboard tools. "
                "For files: use read_workspace_file/write_workspace_file tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute."
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "call_vision_model",
            "description": (
                "Send an image to the vision model for analysis. "
                "Use this to parse ERD diagrams, read schema images, or extract "
                "structured information from visual inputs. Provide the workspace "
                "path to the image file and a text prompt describing what to extract."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Absolute workspace path to the image file (PNG/JPEG)."
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Instructions for the vision model describing what to extract "
                            "from the image. Be specific about output format."
                        )
                    }
                },
                "required": ["image_path", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "import_notebook",
            "description": (
                "Import a Python or SQL notebook to the workspace. Creates a notebook file "
                "that can later be executed via execute_notebook. Use this for generated "
                "DDL scripts, synthetic data generators, or any multi-cell notebook content. "
                "Content should be in Databricks notebook source format (# COMMAND ---------- separators)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute workspace path for the notebook (e.g. /Workspace/Users/user/project/notebooks/ddl.py)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Full notebook source content."
                    },
                    "language": {
                        "type": "string",
                        "enum": ["PYTHON", "SQL"],
                        "description": "Notebook language. Default: PYTHON."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_notebook",
            "description": (
                "Execute a notebook via the Jobs API (one-time run). Returns the output "
                "or full error traceback. Use after import_notebook to run DDL, synthetic "
                "data generation, or any notebook that needs Spark compute. Waits for "
                "completion (up to timeout_minutes)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute workspace path of the notebook to execute."
                    },
                    "timeout_minutes": {
                        "type": "integer",
                        "description": "Max execution time in minutes. Default: 15.",
                        "default": 15
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cleanup_path",
            "description": (
                "Remove a workspace file or directory for re-generation purposes. "
                "Use before re-creating notebooks or clearing output folders for a fresh "
                "pipeline start. Only works within the configured output folder scope."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute workspace path to remove."
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "If true, remove directory and all contents. Default: false."
                    }
                },
                "required": ["path"]
            }
        }
    },
        {
        "type": "function",
        "function": {
            "name": "report_progress",
            "description": (
                "Report progress on the current pipeline phase. Call this tool at EVERY "
                "phase transition to signal the UI what logical step is happening. "
                "Call with status='started' when beginning a phase, status='update' for "
                "interim progress, and status='completed' when a phase finishes. "
                "Include findings (key facts discovered), stats (numeric metrics), "
                "and happenings (what is currently being done) for live UI display."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phase_id": {
                        "type": "string",
                        "description": "Identifier for the phase (e.g., 'parse_erd', 'build_semantic_model', 'generate_ddl', 'generate_synthetic_data', 'validate_data')."
                    },
                    "phase_name": {
                        "type": "string",
                        "description": "Human-readable name (e.g., 'Parse ERD', 'Build Semantic Model')."
                    },
                    "status": {
                        "type": "string",
                        "enum": ["started", "update", "completed", "failed"],
                        "description": "Phase lifecycle status."
                    },
                    "current_task": {
                        "type": "string",
                        "description": "Brief label of what is currently being done (e.g., 'Extracting table structures')."
                    },
                    "progress_pct": {
                        "type": "integer",
                        "description": "Estimated progress percentage (0-100) within this phase."
                    },
                    "stats": {
                        "type": "object",
                        "description": "Key numeric metrics (e.g., {'tables_found': 14, 'relationships': 9}).",
                        "additionalProperties": True
                    },
                    "happenings": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of what is currently happening or was done (shown as bullet points in UI)."
                    },
                    "findings": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key facts discovered or validated (shown with checkmarks in UI)."
                    }
                },
                "required": ["phase_id", "phase_name", "status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "report_step_complete",
            "description": (
                "Signal that the current pipeline step is complete. "
                "Provide a summary and list of artifacts generated."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of what was accomplished."
                    },
                    "artifacts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of artifact paths generated."
                    },
                    "status": {
                        "type": "string",
                        "enum": ["success", "partial", "failed"],
                        "description": "Step completion status."
                    }
                },
                "required": ["summary", "artifacts", "status"]
            }
        }
    }
]


# ---------------------------------------------------------------------------
# Tool name lookup
# ---------------------------------------------------------------------------

def get_tool_names() -> list:
    """Return list of all tool names."""
    return [t["function"]["name"] for t in TOOL_DEFINITIONS]


def get_tool_by_name(name: str) -> dict:
    """Get a tool definition by name."""
    for t in TOOL_DEFINITIONS:
        if t["function"]["name"] == name:
            return t
    return None
