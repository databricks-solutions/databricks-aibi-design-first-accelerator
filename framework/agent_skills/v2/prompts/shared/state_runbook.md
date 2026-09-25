# State and Resume — Failure Runbook

> **FAILURE/RECOVERY ONLY.** Do not load during a normal successful run. Authenticate the frozen shared-runbook tuple before use.

### Genie Code State Recovery (User Asks "What's my run status?")

```text
User: "What's the status of my member_claims pipeline?"

LLM:
1. Run the shared resolver against the exact registry path and read only its selected run_context_path
2. Reconcile registry/run-context lifecycle identity; in the App, reconcile the optional UI mirror separately without making Lakebase portable lifecycle authority
3. Report: run_id, status, phases_completed, current_step
4. If status=running but no conversation is active, execution may be interrupted; inspect persisted ownership and remote SQL/job IDs before deciding. Conversation absence does not prove remote work stopped.
5. Offer: "Would you like to resume from phase X?"
```


### RUN_SELECTION_NOT_ACKNOWLEDGED / Missing newly allocated run_context.yaml

Apply shared G-12. Allocation returns a future locator. During the same active
bootstrap, finish the master's freeze/write/readback steps before completion progress.
Do not write an empty placeholder, guess another path, or allocate another version
as an automatic repair. An orphan from a previous interrupted allocation follows
the resolver's existing recovery policy. Check access errors separately from absence.

### WORKSPACE_UPLOAD_FORMAT_REQUIRED / Archive error on a plain-file upload

Apply shared G-8 and the frozen workspace file-I/O input. Inspect the failing call's
format and payload type. A pre-execution rejection may be corrected and resubmitted;
a runtime archive error requires checking earlier writes before retrying. Keep
notebook imports separate from plain-file writes and never bypass permissions.

### Downstream failure versus changed release

Classify these separately before invalidating any phase:

1. Same frozen release, failed downstream artifact: authenticate earlier phase records
   and current readbacks under the Resume Skip Gate. Preserve those that pass. Repair
   the owning phase and invalidate only that phase plus its transitive dependents.
   A Dashboard problem alone does not require new ERD extraction, table creation,
   synthetic appends, or Metric View replacement.
2. Producer PASS output exists but its checkpoint is missing: verify the complete
   producer evidence and use that phase's checkpoint-only recovery where authorized.
   Do not rerun a successful notebook merely to produce a progress event.
3. Submitted SQL/job outcome unknown: reconcile the original execution ID before any
   retry. A notebook timeout is not proof that no data was appended or asset created.
4. Release file differs from its frozen digest: this is release drift, not bad input
   data. Never update run-context hashes, substitute an ambient helper, or re-create
   upstream assets to hide it. Resume requires the exact frozen bytes at their frozen
   locators. If unavailable, report that the old run cannot resume under its contract;
   a new release/run requires the normal master selection policy, not in-place rehashing.

A fresh run under corrected prompts is not evidence that an old run was repaired.
An old frozen run does not automatically adopt a dashboard fix from the current repo.
Retain original diagnostic evidence and identify which release each result used.
