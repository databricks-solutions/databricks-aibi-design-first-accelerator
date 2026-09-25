# Genie — Guardrails

> **Always loaded.** This file contains normative prohibitions and hard stops for `create_genie_space`. Historical incidents and fixes live only in the failure runbook.

## Prohibited Actions

1. DO NOT bypass the notebook template — ALWAYS use `v2_genie_space_notebook.py.template`
2. DO NOT use `createAsset(assetType="genie")` — it creates blank title-only spaces
3. DO NOT use raw SUM/COUNT/AVG in example SQL — ALWAYS use MEASURE() syntax
4. DO NOT skip SQL validation for example queries
5. DO NOT use column names or metric semantics from spec text — use live DESCRIBE and SHOW CREATE output
6. DO NOT create a Genie space with fewer sample questions than frozen `run_context.validation.min_sample_questions`
7. DO NOT create a Genie space with empty instructions
8. DO NOT skip the post-deploy API readback
9. DO NOT write the manifest without `validation_source: api_readback`
10. DO NOT report success if the API readback shows fewer sample questions than frozen `run_context.validation.min_sample_questions`
11. DO NOT use generic placeholder questions ("What is the total?")
12. DO NOT duplicate questions between sample_questions and benchmarks
13. DO NOT skip the benchmark questions — they evaluate Genie accuracy
14. DO NOT catch or suppress `GateCheckError` exceptions
15. DO NOT skip writing the Genie notebook to the output folder
16. DO NOT create spaces with instructions shorter than frozen `run_context.validation.min_instruction_chars`
17. DO NOT skip the pre-deploy configuration validation (Cell 8)
18. DO NOT use `"tables"` key in `serialized_space.data_sources` — MUST use `"metric_views"` (causes "zip archive contains no items" error)
19. DO NOT add `"column_configs"` field to metric view entries in `serialized_space`
20. DO NOT rewrite `build_serialized_space` — copy it VERBATIM from the template
21. DO NOT modify or reconstruct `step_handoff.yaml` in the Genie stage
22. DO NOT derive Metric View FQNs or the Genie title from the plan, accelerator config, folder name, or memory
23. DO NOT let `metric_view_design.yaml`, `genie_semantic_inventory.yaml`, or LLM output override the deployed Metric View definition
24. DO NOT treat POST/PATCH acceptance or a returned `space_id` as deployment success
25. DO NOT use a manifest as proof of current Genie content — use it only to locate the asset, then GET live state with `include_serialized_space=true`
26. DO NOT import `gate_checks` or Genie helpers from a fixed/ambient `sys.path`, a shared non-digest-qualified temp directory, or an unattested output-folder copy
27. DO NOT manually reproduce or fall back around the canonical pinned `validate_genie_from_api` validator
28. DO NOT consume auto-produced Metric View handoff entries without the complete G-3 checkpoint, hashes, full entry tuples, capability tuple, and separate durable producer-phase record
29. DO NOT accept a Metric View plan or validation for either strategy unless its top-level `run_id`, `asset_suffix`, and `metric_view_strategy` exactly match the other artifact, current run context, and handoff
30. DO NOT define or fall back to a Genie threshold outside the approved source contract and
    Step-0-frozen effective snapshot
31. DO NOT hardcode benchmark comparators, actions, manifest permission, validation status, or stage
    status outside frozen `run_context.validation.benchmark_outcomes`

---
