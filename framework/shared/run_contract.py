"""Portable lifecycle primitives. The master prompt owns orchestration.

Stores expose byte reads, replace/create-only writes, deletes, and a cooperative
exclusive lock. WorkspaceStore uses authenticated SDK file operations; LocalStore
is for tests and explicitly verified filesystem execution, never remote assumptions.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import posixpath
import tempfile
import uuid
from datetime import datetime, timezone
import yaml


def decode(raw):
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node, deep=False):
        result = {}
        for key, value in node.value:
            key = loader.construct_object(key, deep=deep)
            if key in result:
                raise ValueError(f"Duplicate YAML key: {key}")
            result[key] = loader.construct_object(value, deep=deep)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    result = yaml.load(raw, Loader=UniqueLoader)
    if not isinstance(result, dict):
        raise ValueError("Run contract must be a mapping")
    return result


def encode(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode()


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _path(path):
    if not isinstance(path, str) or not path.startswith('/') or posixpath.normpath(path) != path:
        raise ValueError(f"Expected absolute normalized path: {path!r}")
    return path


def validate_phase_checkpoint_shapes(context):
    """Validate stage-specific record structure; this is not live evidence verification."""
    phases = context.get('phases_completed', [])
    if not isinstance(phases, list):
        raise RuntimeError('CHECKPOINT_PERSISTENCE_ERROR: phases_completed must be a list')
    for record in phases:
        if not isinstance(record, dict):
            raise RuntimeError('CHECKPOINT_PERSISTENCE_ERROR: phase record must be a mapping')
        if (record.get('step'), record.get('phase'), record.get('checkpoint_status')) != (
                'create_data_layer', 'reconcile_schema', 'VALID'):
            continue
        target, version = context.get('target', {}), context.get('version', {})
        output = context.get('output_folder')
        if (not isinstance(target, dict) or not isinstance(version, dict)
                or not all(isinstance(v, str) and v for v in
                           (output, target.get('catalog'), target.get('schema'), version.get('asset_suffix')))):
            raise RuntimeError('CHECKPOINT_PERSISTENCE_ERROR: reconciliation identity bindings missing')
        expected = [
            ('schema_reconciliation_artifact', 'RAW_BYTES', output + '/schema_reconciliation.yaml'),
            ('schema_reconciliation_catalog_readback', 'CATALOG_READBACK',
             f"table_spec:{target['catalog']}.{target['schema']}:{version['asset_suffix']}"),
        ]
        outputs = record.get('output_fingerprints')
        import re
        if (not isinstance(outputs, list) or len(outputs) != len(expected)
                or any(not isinstance(item, dict)
                       or set(item) != {'id', 'kind', 'locator', 'sha256'}
                       or (item.get('id'), item.get('kind'), item.get('locator')) != identity
                       or not isinstance(item.get('sha256'), str)
                       or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])
                       for item, identity in zip(outputs, expected))):
            raise RuntimeError('CHECKPOINT_PERSISTENCE_ERROR: reconcile_schema VALID requires exact '
                               f'output identities {expected!r}; observed={outputs!r}. '
                               'Use authenticated DDL-manifest fingerprints and verify live evidence; '
                               'frozen context authentication alone is not phase validation.')


def frozen_context_sha256(context):
    """Canonical digest from the shared state contract; never mutate the caller."""
    frozen = json.loads(json.dumps(context))
    for key in ('current_step', 'status', 'phases_completed', 'findings',
                'completed_at', 'error', 'retry_attempt'):
        frozen.pop(key, None)
    frozen.setdefault('checkpointing', {}).pop('frozen_run_contract_sha256', None)
    return canonical_sha256(frozen)


def verify_frozen_context(context, path):
    recorded = context.get('checkpointing', {}).get('frozen_run_contract_sha256')
    actual = frozen_context_sha256(context)
    if not recorded or actual != recorded:
        raise RuntimeError(
            f'HANDOFF_AUTHORITY_ERROR: frozen context mismatch; path={path}; '
            f'recorded_sha256={recorded}; actual_sha256={actual}. '
            'Preserve context and writer source; compare with the last authenticated preimage. '
            'Do not recompute the recorded digest to authorize drift.')


def _validate_context_write(path, raw):
    if posixpath.basename(path) == 'run_context.yaml':
        context = decode(raw)
        validate_phase_checkpoint_shapes(context)
        # Bootstrap envelopes may be written before the master freezes them.
        # Once a digest is present, reject inconsistent updates before mutation.
        if 'frozen_run_contract_sha256' in context.get('checkpointing', {}):
            verify_frozen_context(context, path)


class LocalStore:
    def list(self, path):
        try:
            return [str(p) for p in Path(path).iterdir()]
        except FileNotFoundError:
            return []

    def read(self, path):
        try:
            return Path(path).read_bytes()
        except FileNotFoundError:
            return None

    def write(self, path, raw, *, overwrite=True):
        _validate_context_write(path, raw)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if not overwrite:
            with open(path, 'xb') as handle:
                handle.write(raw)
            return
        fd, tmp = tempfile.mkstemp(dir=str(Path(path).parent))
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def delete(self, path):
        Path(path).unlink(missing_ok=True)

    @contextmanager
    def lock(self, path):
        token = str(uuid.uuid4()).encode()
        self.write(path, token, overwrite=False)
        try:
            yield
        finally:
            if self.read(path) != token:
                raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: lock ownership changed')
            self.delete(path)


class WorkspaceStore(LocalStore):
    """No local /Workspace I/O. Not-found alone maps to absent; other errors propagate.

    All writers use the same create-only lock file. A crashed lock is intentionally
    retained for explicit recovery; it is never stolen based on elapsed time.
    """
    def __init__(self, workspace_client):
        self.client = workspace_client

    def list(self, path):
        from databricks.sdk.errors import NotFound
        try:
            return [item.path for item in self.client.workspace.list(path)]
        except NotFound:
            return []

    def read(self, path):
        from databricks.sdk.errors import NotFound
        try:
            with self.client.workspace.download(path) as handle:
                return handle.read()
        except NotFound:
            return None

    def write(self, path, raw, *, overwrite=True):
        from databricks.sdk.service.workspace import ImportFormat
        _validate_context_write(path, raw)
        self.client.workspace.mkdirs(posixpath.dirname(path))
        raw_format = getattr(ImportFormat, 'RAW', None)
        if raw_format is not None:
            self.client.workspace.upload(path, raw, format=raw_format, overwrite=overwrite)
        else:
            # Older notebook SDK enums omit RAW; preserve explicit wire semantics.
            # Select transport before writing, never retry an ambiguous failed upload.
            import base64
            self.client.api_client.do('POST', '/api/2.0/workspace/import', body={
                'path': path, 'format': 'RAW', 'overwrite': overwrite,
                'content': base64.b64encode(raw).decode('ascii'),
            })
        if self.read(path) != raw:
            raise RuntimeError(f'WORKSPACE_IO_ERROR: write readback differs: {path}')

    def delete(self, path):
        from databricks.sdk.errors import NotFound
        try:
            self.client.workspace.delete(path)
        except NotFound:
            pass


def _identity(document):
    domain = document.get('domain')
    version = document.get('version')
    return (
        document.get('lifecycle_contract_version'),
        domain.get('name') if isinstance(domain, dict) else domain,
        version.get('number') if isinstance(version, dict) else version,
        document.get('run_id'), document.get('created_by'),
        document.get('output_folder'), document.get('run_context_path'),
        document.get('status'),
    )


def _checked_write(store, path, raw):
    store.write(path, raw)
    if store.read(path) != raw:
        raise RuntimeError(f'RUN_LIFECYCLE_AUTHORITY_ERROR: readback differs: {path}')


def resolve_version(*, registry_path, domain, output_root, created_by, run_id,
                    store, mode='auto', explicit_version=None):
    """Return the exact immutable selection required by master Step 0.

    A missing registry starts at v1 only if that output path is unallocated.
    Legacy entries cannot resume; they reserve their version numbers. Explicit
    versions select authenticated same-owner running/failed entries only.
    """
    _path(registry_path)
    _path(output_root)
    if mode not in {'auto', 'retry', 'fresh'}:
        raise ValueError('Unknown resolution mode')
    if not domain or not created_by or str(uuid.UUID(run_id)) != run_id:
        raise ValueError('Non-empty domain/owner and canonical candidate UUID required')
    with store.lock(registry_path + '.lock'):
        preimage = store.read(registry_path)
        registry = decode(preimage) if preimage is not None else {'versions': []}
        if preimage is None:
            import re
            registry['versions'] = [
                {'version': int(posixpath.basename(p)[1:]), 'legacy_reserved': True}
                for p in store.list(output_root)
                if re.fullmatch(r'v[1-9][0-9]*', posixpath.basename(p))
            ]
        entries = registry.get('versions')
        if not isinstance(entries, list):
            raise ValueError('Registry versions must be an array')
        numbers = [e.get('version') for e in entries]
        if any(type(v) is not int or v < 1 for v in numbers) or len(set(numbers)) != len(numbers):
            raise ValueError('Invalid/duplicate registry versions')
        candidates = [e for e in entries if e.get('created_by') == created_by
                      and e.get('lifecycle_contract_version') == 1
                      and e.get('status') in ({'running', 'failed'} if mode == 'retry' else {'running'})]
        if explicit_version is not None:
            candidates = [e for e in candidates if e['version'] == explicit_version]
            if len(candidates) != 1 or mode == 'fresh':
                raise ValueError('Explicit version is not an authenticated resumable selection')
        selected = max(candidates, key=lambda e: e['version']) if candidates and mode != 'fresh' else None
        if selected:
            expected_output = f"{output_root}/v{selected['version']}"
            if (selected.get('domain') != domain or selected.get('output_folder') != expected_output
                    or selected.get('run_context_path') != expected_output + '/run_context.yaml'
                    or selected.get('registry_path') != registry_path):
                raise RuntimeError('RUN_SELECTION_AUTHORITY_ERROR: registry binding mismatch')
            marker = expected_output + '/.lifecycle/retry_transition.yaml'
            if store.read(marker) is not None:
                raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: unresolved retry transition')
            context_raw = store.read(selected['run_context_path'])
            if context_raw is None:
                raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: selected context missing')
            context = decode(context_raw)
            if _identity(context) != _identity(selected) or context.get('registry_path') != registry_path:
                raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: registry/context parity')
            manifest_path = expected_output + '/run_manifest.json'
            manifest_raw = store.read(manifest_path)
            if manifest_raw is not None and _identity(decode(manifest_raw)) != _identity(selected):
                raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: manifest parity')
            if selected['status'] == 'failed':
                if manifest_raw is None:
                    raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: failed manifest missing')
                attempt = context.get('retry_attempt', 0)
                if type(attempt) is not int or attempt < 0:
                    raise ValueError('Invalid retry_attempt')
                history = f'{expected_output}/.lifecycle/attempt_{attempt}_manifest.json'
                if store.read(history) is None:
                    store.write(history, manifest_raw, overwrite=False)
                if store.read(history) != manifest_raw:
                    raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: history verification')
                transition = dict(lifecycle_contract_version=1, transition_id=str(uuid.uuid4()),
                    run_id=selected['run_id'], version=selected['version'], created_by=created_by,
                    registry_path=registry_path, output_folder=expected_output,
                    run_context_path=selected['run_context_path'], prior_status='failed', target_status='running',
                    prior_manifest_path=history, prior_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                    retry_attempt_from=attempt, retry_attempt_to=attempt+1,
                    started_at=datetime.now(timezone.utc).isoformat())
                _checked_write(store, marker, encode(transition))
                try:
                    store.delete(manifest_path)
                    context.update(status='running', retry_attempt=attempt+1, completed_at=None, error=None)
                    selected['status'] = 'running'
                    _checked_write(store, selected['run_context_path'], encode(context))
                    if store.read(registry_path) != preimage:
                        raise RuntimeError('Registry preimage changed')
                    _checked_write(store, registry_path, encode(registry))
                    _checked_write(store, history + '.transition.json', encode(transition))
                    store.delete(marker)
                except Exception:
                    # Leave marker if any rollback operation fails.
                    _checked_write(store, selected['run_context_path'], context_raw)
                    _checked_write(store, manifest_path, manifest_raw)
                    _checked_write(store, registry_path, preimage)
                    store.delete(marker)
                    raise
            return dict(selected, version_suffix=f"_v{selected['version']}", is_new=False)
        number = max(numbers, default=0) + 1
        output = f'{output_root}/v{number}'
        if store.read(output + '/run_context.yaml') is not None or store.read(output + '/run_manifest.json') is not None:
            raise RuntimeError('RUN_SELECTION_AUTHORITY_ERROR: unregistered output already exists')
        selected = dict(lifecycle_contract_version=1, domain=domain, version=number,
            run_id=run_id, created_by=created_by, output_folder=output,
            run_context_path=output + '/run_context.yaml', registry_path=registry_path, status='running')
        entries.append(selected)
        if store.read(registry_path) != preimage:
            raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: registry preimage changed')
        _checked_write(store, registry_path, encode(registry))
        return dict(selected, version_suffix=f'_v{number}', is_new=True)


def commit_terminal(*, store, registry_path, run_context_path, manifest):
    """Master-owned terminal decision, persisted under the resolver lock."""
    if manifest.get('status') not in {'completed', 'partial_success', 'failed'}:
        raise ValueError('Invalid terminal status')
    with store.lock(registry_path + '.lock'):
        registry_raw = store.read(registry_path)
        context_raw = store.read(run_context_path)
        registry, context = decode(registry_raw), decode(context_raw)
        entries = [e for e in registry['versions'] if e.get('run_id') == context.get('run_id')]
        if len(entries) != 1 or _identity(entries[0]) != _identity(context):
            raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: pre-terminal parity')
        if _identity(manifest)[:-1] != _identity(context)[:-1]:
            raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: manifest identity')
        manifest_path = context['output_folder'] + '/run_manifest.json'
        old_manifest = store.read(manifest_path)
        if old_manifest is not None and _identity(decode(old_manifest)) != _identity(context):
            raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: prior manifest parity')
        try:
            _checked_write(store, manifest_path, encode(manifest))
            context.update(status=manifest['status'], completed_at=manifest.get('completed_at'), error=manifest.get('error', context.get('error')))
            _checked_write(store, run_context_path, encode(context))
            entries[0]['status'] = manifest['status']
            if store.read(registry_path) != registry_raw:
                raise RuntimeError('Registry preimage changed')
            _checked_write(store, registry_path, encode(registry))
            if not (_identity(decode(store.read(manifest_path))) == _identity(decode(store.read(run_context_path))) == _identity(entries[0])):
                raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: terminal parity')
        except Exception:
            _checked_write(store, run_context_path, context_raw)
            if old_manifest is None:
                store.delete(manifest_path)
            else:
                _checked_write(store, manifest_path, old_manifest)
            _checked_write(store, registry_path, registry_raw)
            raise


def load_attested(store, reference):
    """Load only digest-verified source into a digest-qualified temporary module."""
    import importlib.util
    import sys
    path, digest = _path(reference['path']), reference['sha256']
    raw = store.read(path)
    if raw is None or hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError(f'HELPER_CONTRACT_ERROR: source hash mismatch: {path}')
    directory = Path(tempfile.mkdtemp(prefix='aibi_' + digest[:12] + '_'))
    copy = directory / Path(path).name
    copy.write_bytes(raw)
    if hashlib.sha256(copy.read_bytes()).hexdigest() != digest:
        raise RuntimeError('HELPER_CONTRACT_ERROR: staged source hash mismatch')
    name = 'aibi_' + digest
    spec = importlib.util.spec_from_file_location(name, copy)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != copy.resolve():
        raise RuntimeError('HELPER_CONTRACT_ERROR: loaded module path mismatch')
    return module


def authenticate_context(store, path):
    context = decode(store.read(_path(path)))
    if context.get('run_context_path') != path or context.get('output_folder') != posixpath.dirname(path):
        raise RuntimeError('HANDOFF_AUTHORITY_ERROR: context path mismatch')
    verify_frozen_context(context, path)
    if store.read(context['registry_path'] + '.lock') is not None or store.read(context['output_folder'] + '/.lifecycle/retry_transition.yaml') is not None:
        raise RuntimeError('RUN_LIFECYCLE_AUTHORITY_ERROR: active lifecycle transition')
    validate_phase_checkpoint_shapes(context)
    return context
