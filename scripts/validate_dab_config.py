#!/usr/bin/env python3
"""Validate databricks.yml and examples/<domain>/accelerator.yaml consistency."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Install PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
VAR_REF = re.compile(r"\$\{var\.(\w+)\}")
WORKSPACE_USER_REF = "${workspace.current_user.userName}"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def var_default(variables: dict, name: str, resolved: dict) -> str | None:
    node = variables.get(name) or {}
    raw = node.get("default")
    if raw is None:
        return None
    if not isinstance(raw, str):
        return str(raw)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in resolved:
            val = var_default(variables, key, resolved)
            if val is None:
                return match.group(0)
            resolved[key] = val
        return resolved[key]

    out = VAR_REF.sub(repl, raw)
    resolved[name] = out
    return out


def resolve_variables(bundle: dict) -> dict[str, str]:
    variables = bundle.get("variables") or {}
    resolved: dict[str, str] = {}
    for key in variables:
        var_default(variables, key, resolved)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "example_dir",
        type=Path,
        nargs="?",
        default=ROOT / "examples" / "member_claims",
        help="Path to example module (contains accelerator.yaml)",
    )
    args = parser.parse_args()
    example_dir = args.example_dir.resolve()
    accel_path = example_dir / "accelerator.yaml"
    dab_path = ROOT / "databricks.yml"

    if not accel_path.is_file():
        print(f"Missing {accel_path}", file=sys.stderr)
        return 1
    if not dab_path.is_file():
        print(f"Missing {dab_path}", file=sys.stderr)
        return 1

    accel = load_yaml(accel_path)
    dab_bundle = load_yaml(dab_path)
    vars_resolved = resolve_variables(dab_bundle)

    domain_name = (accel.get("domain") or {}).get("name")
    paths = accel.get("paths") or {}
    databricks_rel = paths.get("databricks_yml", "../../databricks.yml")
    example_domain = vars_resolved.get("example_domain", "")
    deploy_root = vars_resolved.get("deploy_root", "")
    warehouse = vars_resolved.get("sql_warehouse_id", "")
    output_subpath = (accel.get("workspace") or {}).get("output_subpath", "output")
    uses_current_user = WORKSPACE_USER_REF in (dab_bundle.get("variables") or {}).get("deploy_root", {}).get("default", "")

    errors: list[str] = []
    if not warehouse or "<" in warehouse:
        errors.append("databricks.yml: set variables.sql_warehouse_id.default")
    if not deploy_root and not uses_current_user:
        errors.append("databricks.yml: could not resolve variables.deploy_root")
    if domain_name and example_domain and domain_name != example_domain:
        errors.append(
            f"domain.name ({domain_name}) must match variables.example_domain ({example_domain})"
        )
    if example_dir.name != domain_name:
        errors.append(
            f"example folder name ({example_dir.name}) must match domain.name ({domain_name})"
        )
    if not paths.get("databricks_yml"):
        errors.append("accelerator.yaml: paths.databricks_yml is required")

    data_source = accel.get("data_source") or {}
    ds_type = data_source.get("type", "erd")
    erd = data_source.get("erd") or {}
    greenfield = data_source.get("greenfield") or {}
    live_schema = data_source.get("live_schema") or {}
    live_schemas = data_source.get("live_schemas") or []
    catalog = accel.get("catalog") or {}
    catalog_source = catalog.get("source") or {}

    if ds_type == "erd":
        if not erd.get("image"):
            errors.append("accelerator.yaml: data_source.erd.image required when type is erd")
        if not greenfield.get("enabled", False):
            errors.append(
                "accelerator.yaml: data_source.greenfield.enabled should be true for type erd"
            )
    elif ds_type == "live_schema":
        if greenfield.get("enabled", False) or greenfield.get("synthetic_data", False):
            errors.append(
                "accelerator.yaml: set greenfield.enabled and synthetic_data to false for live_schema"
            )
        has_live = bool(live_schemas) or (
            live_schema.get("catalog") and live_schema.get("schema")
        )
        has_source = catalog_source.get("catalog") and catalog_source.get("schema")
        if not has_live and not has_source:
            errors.append(
                "accelerator.yaml: live_schema requires live_schemas[], live_schema.catalog/schema, "
                "or catalog.source"
            )
        for i, loc in enumerate(live_schemas):
            if not loc.get("catalog") or not loc.get("schema"):
                errors.append(
                    f"accelerator.yaml: live_schemas[{i}] requires catalog and schema"
                )
    elif ds_type == "erd_and_live_schema":
        if not erd.get("image"):
            errors.append(
                "accelerator.yaml: data_source.erd.image required when type is erd_and_live_schema"
            )
    else:
        errors.append(f"accelerator.yaml: invalid data_source.type ({ds_type})")
    dab_file = (example_dir / databricks_rel).resolve()
    if not dab_file.is_file():
        errors.append(
            f"accelerator.yaml: paths.databricks_yml ({databricks_rel}) must exist; "
            f"expected {dab_file}"
        )

    host = (
        ((dab_bundle.get("targets") or {}).get("dev") or {})
        .get("workspace", {})
        .get("host", "")
    )
    if "your-workspace" in (host or ""):
        errors.append("databricks.yml: set targets.dev.workspace.host (or use databricks.yml.local)")

    expected_output = (
        f"/Workspace/Users/<current_user>/{vars_resolved.get('bundle_name_path', 'aibi-design-first-accelerator')}"
        f"/examples/{domain_name}/{output_subpath}"
        if uses_current_user
        else f"{deploy_root}/examples/{domain_name}/{output_subpath}"
    )

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"OK: {example_dir.name}")
    if uses_current_user:
        print("  user:            ${workspace.current_user.userName} (resolved at deploy / Genie runtime)")
    print(f"  databricks_yml:  {databricks_rel} -> {dab_file}")
    print(f"  sql_warehouse:   {warehouse}")
    print(f"  workspace.host:  {host}")
    print(f"  data_source:     {ds_type}")
    if live_schemas:
        print(f"  live_schemas:    {len(live_schemas)} location(s)")
    print(f"  output_folder:   {expected_output}  (resolved by Genie from databricks.yml)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
