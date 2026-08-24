"""Event Marker Parser — Extracts structured UI events from LLM output.

The LLM emits structured progress blocks as fenced code blocks with the
`@progress` language tag. This format is prompt-driven and works in both:

1. **Genie Code**: Renders as a formatted code block in chat output (readable)
2. **App Supervisor**: Parsed into real-time UI events for the pipeline monitor

Progress block format (defined in 00_master_prompt.md §5):

    ```@progress
    {
      "step": "Data Layer",
      "step_order": 3,
      "substep": {"id": "parse_erd", "name": "Parse ERD", "status": "completed", "detail": "..."},
      "progress": 73,
      "currentTask": "Generating DDL for fact_claim_detail",
      "stats": [{"value": "8/14", "label": "Tables"}],
      "happenings": ["Populating fact table", "Applying FK constraints"],
      "findings": ["14 schemas validated", "9 FK relationships resolved"],
      "decisions": [{"title": "Fact table selected", "detail": "...", "confidence": "high"}]
    }
    ```

The parser extracts these blocks and converts them into the event types
the pipeline monitor UI expects: substep_update, finding, decision, artifact.
"""

import json
import re
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Regex: matches ```@progress ... ``` fenced code blocks
PROGRESS_BLOCK_PATTERN = re.compile(
    r'```@progress\s*\n(\{.*?\})\s*\n```',
    re.MULTILINE | re.DOTALL,
)


def parse_event_markers(text: str) -> List[Dict[str, Any]]:
    """Parse all @progress blocks from LLM text.

    Args:
        text: LLM response content or tool result string.

    Returns:
        List of parsed progress block dicts.
    """
    if not text:
        return []

    blocks = []
    for match in PROGRESS_BLOCK_PATTERN.finditer(text):
        json_str = match.group(1)
        try:
            data = json.loads(json_str)
            blocks.append(data)
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse @progress JSON: {json_str[:200]}, error: {e}")
            continue

    return blocks


def strip_markers(text: str) -> str:
    """Remove all @progress blocks from text (for clean display)."""
    return PROGRESS_BLOCK_PATTERN.sub('', text).strip()


def progress_blocks_to_events(
    blocks: List[Dict[str, Any]],
    tool_name: str = "",
    step_name: str = "",
) -> List[Tuple[str, Dict[str, Any]]]:
    """Convert parsed @progress blocks into supervisor UI events.

    Each @progress block can produce multiple events:
        - substep_update (from the "substep" field)
        - substep_update with progress (from progress/currentTask/stats/happenings/findings)
        - decision events (from the "decisions" array)
        - finding events (from the "findings" array — as typed findings)

    Returns:
        List of (event_type, event_data) tuples ready to emit.
    """
    events = []

    for block in blocks:
        step = block.get("step", step_name)
        step_order = block.get("step_order", 0)

        # --- Substep update ---
        substep = block.get("substep")
        if substep:
            event_data = {
                "id": substep.get("id", tool_name),
                "name": substep.get("name", step),
                "status": _map_status(substep.get("status", "running")),
                "statusLabel": _map_status_label(substep.get("status", "running")),
                "detail": substep.get("detail", ""),
                "step_order": step_order,
            }
            if "duration" in substep:
                event_data["duration"] = substep["duration"]
            events.append(("substep_update", event_data))

        # --- Progress update (with rich detail) ---
        if any(k in block for k in ["progress", "currentTask", "stats", "happenings"]):
            progress_data = {
                "id": substep.get("id", tool_name) if substep else tool_name,
                "name": substep.get("name", step) if substep else step,
                "status": "running",
                "statusLabel": "In Progress",
                "step_order": step_order,
            }
            if "progress" in block:
                progress_data["progress"] = block["progress"]
            if "currentTask" in block:
                progress_data["currentTask"] = block["currentTask"]
            if "stats" in block:
                progress_data["stats"] = block["stats"]
            if "happenings" in block:
                progress_data["happenings"] = block["happenings"]
            if "findings" in block:
                progress_data["findings"] = block["findings"]

            # Only emit a separate progress event if substep status is "running"
            if not substep or substep.get("status") == "running":
                events.append(("substep_update", progress_data))

        # --- Decisions ---
        for decision in block.get("decisions", []):
            events.append(("decision", {
                "title": decision.get("title", ""),
                "detail": decision.get("detail", ""),
                "confidence": decision.get("confidence", "high"),
                "step": step,
                "step_order": step_order,
            }))

        # --- Findings (as typed events for the Artifacts/Activity tab) ---
        for finding_text in block.get("findings", []):
            events.append(("finding", {
                "text": finding_text,
                "type": "validation",
                "step": step,
                "step_order": step_order,
            }))

    return events


# For backward compat — alias used by supervisor.py
def markers_to_events(
    blocks: List[Dict[str, Any]],
    tool_name: str = "",
    step_name: str = "",
) -> List[Tuple[str, Dict[str, Any]]]:
    """Alias for progress_blocks_to_events."""
    return progress_blocks_to_events(blocks, tool_name, step_name)


def _map_status(status: str) -> str:
    """Map prompt status values to UI status codes."""
    mapping = {
        "running": "running",
        "completed": "done",
        "failed": "failed",
        "skipped": "cancelled",
    }
    return mapping.get(status, "running")


def _map_status_label(status: str) -> str:
    """Map prompt status values to UI display labels."""
    mapping = {
        "running": "In Progress",
        "completed": "Completed",
        "failed": "Failed",
        "skipped": "Skipped",
    }
    return mapping.get(status, "In Progress")


def _stats_to_list(stats) -> list:
    """Normalize stats to UI list format [{value, label}].

    The manifest stores stats as a dict (easier to merge).
    The UI expects a list of {value, label} for rendering.
    """
    if isinstance(stats, list):
        return stats
    if isinstance(stats, dict):
        return [
            {"value": str(v), "label": k.replace("_", " ").title()}
            for k, v in stats.items()
        ]
    return []


def _format_duration_s(duration_s) -> str:
    """Format seconds to human-readable duration."""
    if duration_s is None:
        return ""
    if duration_s < 60:
        return f"{duration_s}s"
    mins = int(duration_s // 60)
    secs = int(duration_s % 60)
    return f"{mins}m {secs:02d}s"


# ---------------------------------------------------------------------------
# Manifest Accumulator — builds run_manifest.json progressively
# ---------------------------------------------------------------------------

class ManifestAccumulator:
    """Progressively builds run_manifest.json from @progress blocks.

    The manifest is the single source of truth for what happened during a run.
    Each @progress block emitted by the LLM updates the manifest in memory.
    At the end, finalize() produces the complete manifest for writing to disk.

    Accumulation rules:
    - substep: appended or updated in the step's substeps list
    - findings: appended (deduplicated)
    - decisions: appended or updated (by title)
    - stats: merged (latest values win)
    - status: step finalized when completed/failed/skipped

    Usage:
        acc = ManifestAccumulator(run_id, domain, config)
        for marker in parse_event_markers(content):
            acc.apply(marker)
        manifest = acc.finalize()
    """

    def __init__(self, run_id: str, domain: str, config: dict):
        from datetime import datetime, timezone
        self._start_time = datetime.now(timezone.utc)
        self._manifest = {
            "run_id": run_id,
            "domain": domain,
            "data_source_type": config.get("data_source_type", "erd"),
            "version": config.get("version"),
            "version_suffix": config.get("version_suffix", ""),
            "asset_suffix": config.get("asset_suffix", ""),
            "output_folder": config.get("output_folder", ""),
            "status": "running",
            "started_at": self._start_time.isoformat(),
            "completed_at": None,
            "elapsed_s": None,
            "catalog": {
                "source_catalog": config.get("catalog", ""),
                "source_schema": config.get("schema", ""),
                "target_catalog": config.get("catalog", ""),
                "target_schema": config.get("schema", ""),
            },
            "steps": [],
            "validation": {},
            "assets_created": {
                "tables": [], "metric_views": [], "dashboards": [], "genie_space": None
            },
            "artifact_paths": {},
            "kpi_summary": {
                "total": 0, "implemented_and_validated": 0, "skipped": 0, "failed": 0
            },
            "error": None,
        }

    def apply(self, marker: Dict[str, Any]):
        """Apply a single @progress block to the manifest."""
        step_order = marker.get("step_order", 0)
        if not step_order:
            return

        step_entry = self._ensure_step(step_order, marker)

        # Substep: upsert
        substep = marker.get("substep", {})
        if substep and substep.get("id"):
            self._upsert_substep(step_entry, substep)

        # Findings: append (deduplicate)
        for finding in marker.get("findings", []):
            if finding not in step_entry["findings"]:
                step_entry["findings"].append(finding)

        # Decisions: upsert by title
        for decision in marker.get("decisions", []):
            existing = next(
                (d for d in step_entry["decisions"]
                 if d.get("title") == decision.get("title")), None
            )
            if existing:
                existing.update(decision)
            else:
                step_entry["decisions"].append(decision)

        # Stats: merge (dict)
        stats = marker.get("stats", {})
        if isinstance(stats, dict):
            step_entry["stats"].update(stats)
        elif isinstance(stats, list):
            # Convert list [{value,label}] to dict for merging
            for s in stats:
                key = s.get("label", "").lower().replace(" ", "_")
                if key:
                    step_entry["stats"][key] = s.get("value", "")

        # Status: finalize step when completed/failed
        step_status = marker.get("status", "")
        if step_status in ("completed", "failed", "skipped"):
            step_entry["status"] = "PASS" if step_status == "completed" else step_status.upper()
            from datetime import datetime, timezone
            step_entry["completed_at"] = datetime.now(timezone.utc).isoformat()
            if step_entry["started_at"]:
                from datetime import datetime as dt
                try:
                    start = dt.fromisoformat(step_entry["started_at"])
                    step_entry["duration_s"] = int(
                        (datetime.now(timezone.utc) - start).total_seconds()
                    )
                except (ValueError, TypeError):
                    pass

    def finalize(self, final_status: str = "completed", error: str = None) -> dict:
        """Finalize the manifest with completion metadata."""
        from datetime import datetime, timezone
        from copy import deepcopy
        now = datetime.now(timezone.utc)
        self._manifest["status"] = final_status
        self._manifest["completed_at"] = now.isoformat()
        self._manifest["elapsed_s"] = int((now - self._start_time).total_seconds())
        self._manifest["error"] = error

        # Compute validation from step statuses
        step_map = {
            "create_data_layer": "data_layer",
            "create_metric_views": "metric_views",
            "create_dashboards": "dashboards",
            "create_genie_space": "genie",
        }
        for step in self._manifest["steps"]:
            key = step_map.get(step.get("step_name"), "")
            if key:
                self._manifest["validation"][key] = step.get("status", "UNKNOWN")

        return deepcopy(self._manifest)

    @property
    def manifest(self) -> dict:
        """Current manifest state (for real-time polling)."""
        from copy import deepcopy
        return deepcopy(self._manifest)

    def _ensure_step(self, step_order: int, marker: dict) -> dict:
        """Ensure step entry exists."""
        for step in self._manifest["steps"]:
            if step.get("step_order") == step_order:
                return step

        from datetime import datetime, timezone
        step_entry = {
            "step_order": step_order,
            "step_name": _step_name_from_order(step_order),
            "label": marker.get("step", ""),
            "status": "RUNNING",
            "duration_s": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "substeps": [],
            "findings": [],
            "decisions": [],
            "stats": {},
            "error": None,
        }
        self._manifest["steps"].append(step_entry)
        self._manifest["steps"].sort(key=lambda s: s.get("step_order", 0))
        return step_entry

    def _upsert_substep(self, step_entry: dict, substep: dict):
        """Insert or update a substep."""
        substep_id = substep.get("id")
        existing = next(
            (s for s in step_entry["substeps"] if s.get("id") == substep_id), None
        )
        if existing:
            existing.update({
                "name": substep.get("name", existing.get("name", "")),
                "status": substep.get("status", existing.get("status", "running")),
                "detail": substep.get("detail", existing.get("detail", "")),
                "duration_s": substep.get("duration_s", existing.get("duration_s")),
            })
        else:
            step_entry["substeps"].append({
                "id": substep_id,
                "name": substep.get("name", ""),
                "status": substep.get("status", "running"),
                "detail": substep.get("detail", ""),
                "duration_s": substep.get("duration_s"),
            })


def _step_name_from_order(order: int) -> str:
    """Map step_order to canonical step_name."""
    return {
        1: "load_and_resolve_config",
        2: "setup_environment",
        3: "create_data_layer",
        4: "create_metric_views",
        5: "create_dashboards",
        6: "create_genie_space",
        7: "generate_documentation",
        8: "create_secured_dashboards",
        9: "write_run_manifest",
    }.get(order, f"step_{order}")
