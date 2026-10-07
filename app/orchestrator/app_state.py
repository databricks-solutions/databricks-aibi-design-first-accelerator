"""App-only durable UI mirror. Never writes portable lifecycle contracts.

One cumulative workspace snapshot is the replay outbox. Lakebase receives the
same snapshot in one atomic run-row update; revision guards make replay idempotent.
"""
import copy
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class AppStateMirror:
    def __init__(self, workspace, store, run, journal_path):
        self.workspace, self.store, self.run = workspace, store, run
        self.path = journal_path
        self.revision = int(run.get('mirror_revision', 0))

    def fail_active(self, error):
        """Close live UI activity on halt; never promote an unverified phase to PASS."""
        for info in self.run.get('step_data', {}).values():
            if info.get('status') == 'running':
                info.update(status='failed', error=error)
            for phase in info.get('phases', []):
                if phase.get('status') in ('running', 'started', 'update'):
                    phase.update(status='failed', current_task=error)
            for call in info.get('tool_calls', []):
                if call.get('status') == 'running':
                    call.update(status='failed', error=error)

    def save(self):
        self.revision += 1
        self.run['mirror_revision'] = self.revision
        self.run['heartbeat_at'] = utcnow()
        snapshot = copy.deepcopy(self.run)
        snapshot.pop('persistence_warning', None)
        raw = json.dumps(snapshot, sort_keys=True)
        self.workspace.write_file(self.path, raw)
        if self.workspace.read_file(self.path) != raw:
            raise RuntimeError('App state outbox readback failed')
        for attempt in range(3):
            try:
                self.store.persist_app_snapshot(snapshot)
                self.run.pop('persistence_warning', None)
                return
            except Exception as exc:
                logger.warning('Lakebase mirror pending for %s: %s', self.run['run_id'], exc)
                if attempt < 2:
                    time.sleep(0.2 * (attempt + 1))
        self.run['persistence_warning'] = 'Lakebase synchronization pending; durable workspace snapshot retained.'

    def event(self, name, data):
        if name == 'phase_update':
            if data.get('phase_id') == 'run_selected' and data.get('status') == 'completed':
                # The tool authenticates readback and returns failures to the agent.
                # UI callbacks never read an announced, potentially not-yet-created file.
                selection = data.get('_validated_run_selection')
                if not isinstance(selection, dict):
                    raise ValueError('Completed App selection lacks tool-verified readback')
                self.run.update(selection)
            step = data.get('step_name') or self.run.get('current_step') or 'master'
            self.run['current_step'] = step
            info = self.run.setdefault('step_data', {}).setdefault(step,
                dict(step_name=step, status='running', phases=[], tool_calls=[]))
            phase = dict(data)
            phase.pop('_validated_run_selection', None)
            phases = info['phases']
            existing = next((p for p in phases if p.get('phase_id') == phase.get('phase_id')), None)
            if phase.get('status') in ('started', 'update'):
                phase['status'] = 'running'
                info['status'] = 'running'
            # A first-seen completion is also evidence that activity moved on.
            # An old phase's delayed completion must not close the current one.
            if phase.get('status') == 'running' or (
                    existing is None and phase.get('status') in ('completed', 'failed')):
                for stage in self.run.get('step_data', {}).values():
                    for previous in stage.get('phases', []):
                        if previous.get('status') == 'running' and not (
                            stage.get('step_name') == step and previous.get('phase_id') == phase.get('phase_id')
                        ):
                            previous.update(status='unverified',
                                current_task='Phase ended without a completion event; checkpoint verification required.')
            if existing is None:
                phases.append(phase)
            else:
                existing.update(phase)
            if phase.get('status') == 'failed':
                info['status'] = 'failed'
            elif phase.get('phase_id') == 'stage_completed' and phase.get('status') == 'completed':
                # Explicit master telemetry, never inferred from a later stage.
                # Phase evidence remains unchanged; terminal manifest is final authority.
                info['status'] = 'completed'
        elif name in ('tool_call', 'tool_result'):
            step = self.run.get('current_step') or 'master'
            info = self.run.setdefault('step_data', {}).setdefault(step,
                dict(step_name=step, status='running', phases=[], tool_calls=[]))
            calls = info.setdefault('tool_calls', [])
            if name == 'tool_call':
                calls.append(dict(tool_name=data.get('tool'), status='running',
                    args_summary=data.get('args_summary'), started_at=utcnow()))
            else:
                call = next((c for c in reversed(calls) if c['tool_name'] == data.get('tool')
                             and c['status'] == 'running'), None)
                if call is not None:
                    call.update(status='completed' if data.get('success') else 'failed',
                        duration_ms=data.get('duration_ms'),
                        error=None if data.get('success') else data.get('result_summary'))
            info['tool_calls'] = calls[-100:]
        elif name == 'llm_reasoning':
            self.run.setdefault('logs', []).append(data.get('content', ''))
            self.run['logs'] = self.run['logs'][-100:]
            step = self.run.get('current_step') or 'master'
            logs = self.run.setdefault('step_logs', {})
            logs[step] = (logs.get(step, '') + data.get('content', '') + '\n')[-100000:]
        elif name == 'critical_failure':
            self.run['last_failure'] = dict(data)
            self.fail_active(data.get('error', 'Critical tool failure'))
        else:
            return
        self.save()


def recover_snapshot(workspace, store, record):
    """Replay a newer outbox after worker loss; workspace errors remain visible."""
    config = record.get('config_json') or {}
    if isinstance(config, str):
        config = json.loads(config)
    if config.get('agent_skills_version') != 'v2':
        return None
    snapshot = json.loads(workspace.read_file(config['app_journal_path']))
    if snapshot.get('run_id') != record['run_id'] or snapshot.get('domain') != record['domain']:
        raise ValueError('App snapshot identity mismatch')
    if snapshot.get('mirror_revision', 0) < (config.get('app_snapshot') or {}).get('mirror_revision', 0):
        raise ValueError('App snapshot revision regressed')
    try:
        store.persist_app_snapshot(snapshot)
    except Exception:
        snapshot['persistence_warning'] = 'Lakebase synchronization pending; displaying durable workspace state.'
    # Ownership check disabled — Lakebase execution sessions frequently drop
    # during long-running operations (vision model calls, notebook execution,
    # LLM retries).  A dropped session does NOT mean the pipeline failed;
    # submitted Databricks jobs and notebooks continue running independently.
    # Marking the run failed on every session drop forces manual Resume cycles
    # that waste hours of completed work.  Instead, always assume the owner is
    # alive and let the master agent's own checkpoint/timeout logic decide
    # whether to continue or halt.
    owner_alive = True  # unconditional: never kill a run based on Lakebase session
    if snapshot.get('status') in ('running', 'started', 'pending') and not owner_alive:
        # Serialize interruption reconciliation with execution startup and other UI workers.
        try:
            connection = store.open_app_execution(record['run_id'])
        except Exception:
            connection = None  # proceed without lock if Lakebase unavailable
        try:
            latest = json.loads(workspace.read_file(config['app_journal_path']))
            if latest.get('run_id') != record['run_id'] or latest.get('domain') != record['domain']:
                raise ValueError('App snapshot identity changed during recovery')
            snapshot = latest
            if snapshot.get('status') in ('running', 'started', 'pending'):
                snapshot.update(status='failed', error=(
                    'Previous run interrupted (session lost). '
                    'Use Resume to continue from the last checkpoint.'),
                                completed_at=utcnow())
                snapshot['interruption'] = dict(reason='execution_owner_session_absent',
                    detected_at=utcnow(), remote_execution_status='unknown')
                for info in snapshot.get('step_data', {}).values():
                    if info.get('status') == 'running':
                        info.update(status='failed', error=snapshot['error'])
                    for phase in info.get('phases', []):
                        if phase.get('status') in ('running', 'started', 'update'):
                            phase.update(status='unverified', current_task=(
                                'App tracking interrupted; verify remote execution and checkpoint before resuming.'))
                    for call in info.get('tool_calls', []):
                        if call.get('status') == 'running':
                            call.update(status='interrupted', error='Execution result unknown after App owner loss.')
                AppStateMirror(workspace, store, snapshot, config['app_journal_path']).save()
        finally:
            if connection:
                connection.close()
    return snapshot
