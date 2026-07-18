"""Dev versioning system for detectors, behaviors, and strategies.

Snapshot, list, restore, and diff versions of framework components.
Each component type stores versions in a `versions/` subdirectory.
"""
import json
import os
import re
import shutil
from datetime import datetime, timezone


# ── Path resolution ────────────────────────────────────────────────

_REGIME_DIR = os.path.join(os.path.dirname(__file__), 'regime')
_BEHAVIORS_DIR = os.path.join(_REGIME_DIR, 'behaviors')
_STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), '..', 'strategies')

_COMPONENT_PATHS = {
    'detector': {
        'source_dir': _REGIME_DIR,
        'versions_dir': os.path.join(_REGIME_DIR, 'versions'),
    },
    'behavior': {
        'source_dir': _BEHAVIORS_DIR,
        'versions_dir': os.path.join(_BEHAVIORS_DIR, 'versions'),
    },
}


def _resolve_detector_file(name: str) -> str:
    """Map a detector short name to its source filename (without .py)."""
    from openquant.regime.composite import _DETECTOR_REGISTRY
    if name in _DETECTOR_REGISTRY:
        # e.g. 'openquant.regime.supertrend_detector.SuperTrendDetector'
        dotted = _DETECTOR_REGISTRY[name]
        module_name = dotted.rsplit('.', 1)[0].rsplit('.', 1)[1]
        return module_name
    return name


def _resolve_behavior_file(name: str) -> str:
    """Map a behavior short name to its source filename (without .py)."""
    from openquant.regime.composite import _BEHAVIOR_REGISTRY
    if name in _BEHAVIOR_REGISTRY:
        dotted = _BEHAVIOR_REGISTRY[name]
        module_name = dotted.rsplit('.', 1)[0].rsplit('.', 1)[1]
        return module_name
    return name


def _get_source_path(component_type: str, name: str) -> str:
    """Get the source .py file path for a component."""
    paths = _COMPONENT_PATHS[component_type]
    if component_type == 'detector':
        filename = _resolve_detector_file(name)
    else:
        filename = _resolve_behavior_file(name)
    return os.path.join(paths['source_dir'], f'{filename}.py')


def _get_versions_dir(component_type: str) -> str:
    return _COMPONENT_PATHS[component_type]['versions_dir']


def _get_versions_json(component_type: str) -> str:
    return os.path.join(_get_versions_dir(component_type), 'versions.json')


def _get_strategy_dir(name: str) -> str:
    return os.path.normpath(os.path.join(_STRATEGIES_DIR, name))


def _get_strategy_versions_dir(name: str) -> str:
    return os.path.join(_get_strategy_dir(name), 'versions')


def _get_strategy_versions_json(name: str) -> str:
    return os.path.join(_get_strategy_versions_dir(name), 'versions.json')


# ── Metadata ───────────────────────────────────────────────────────

def _load_versions_json(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, 'r') as f:
        return json.load(f)


def _save_versions_json(path: str, data: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


# ── Class renaming ─────────────────────────────────────────────────

_CLASS_PATTERN = re.compile(r'^(class\s+)(\w+)(\s*[\(:])', re.MULTILINE)


def _find_class_name(source: str) -> str | None:
    """Find the first class name in Python source."""
    match = _CLASS_PATTERN.search(source)
    return match.group(2) if match else None


def _rename_class(source: str, old_name: str, new_name: str) -> str:
    """Rename a class in Python source code."""
    return source.replace(f'class {old_name}', f'class {new_name}', 1)


# ── Snapshot ───────────────────────────────────────────────────────

def snapshot_component(component_type: str, name: str, tag: str,
                       description: str = '') -> str:
    """Snapshot a detector or behavior to versions/ with a tag.

    Returns the path of the created snapshot file.
    """
    source_path = _get_source_path(component_type, name)
    if not os.path.exists(source_path):
        raise FileNotFoundError(f'{component_type} source not found: {source_path}')

    versions_dir = _get_versions_dir(component_type)
    os.makedirs(versions_dir, exist_ok=True)

    # Read source and rename class
    with open(source_path, 'r') as f:
        source = f.read()

    class_name = _find_class_name(source)
    if class_name:
        new_class_name = f'{class_name}_{tag}'
        source = _rename_class(source, class_name, new_class_name)

    # Determine versioned filename: {name}__{tag}.py
    if component_type == 'detector':
        base = _resolve_detector_file(name)
    else:
        base = _resolve_behavior_file(name)
    versioned_filename = f'{base}__{tag}.py'
    dest_path = os.path.join(versions_dir, versioned_filename)

    with open(dest_path, 'w') as f:
        f.write(source)

    # Update versions.json
    json_path = _get_versions_json(component_type)
    versions = _load_versions_json(json_path)
    # Remove existing entry with same name+tag
    versions = [v for v in versions
                if not (v.get('name') == name and v.get('tag') == tag)]
    versions.append({
        'name': name,
        'tag': tag,
        'file': versioned_filename,
        'source_file': os.path.basename(source_path),
        'class_name': f'{class_name}_{tag}' if class_name else None,
        'original_class': class_name,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'description': description,
    })
    _save_versions_json(json_path, versions)

    # Create __init__.py if missing
    init_path = os.path.join(versions_dir, '__init__.py')
    if not os.path.exists(init_path):
        with open(init_path, 'w') as f:
            f.write('')

    return dest_path


def snapshot_strategy(name: str, tag: str, description: str = '') -> str:
    """Snapshot a strategy directory to versions/{tag}/."""
    strategy_dir = _get_strategy_dir(name)
    if not os.path.isdir(strategy_dir):
        raise FileNotFoundError(f'Strategy not found: {strategy_dir}')

    versions_dir = _get_strategy_versions_dir(name)
    dest_dir = os.path.join(versions_dir, tag)

    # Remove existing snapshot with same tag
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)

    os.makedirs(dest_dir, exist_ok=True)

    # Copy all files except versions/ and __pycache__/
    for item in os.listdir(strategy_dir):
        if item in ('versions', '__pycache__'):
            continue
        src = os.path.join(strategy_dir, item)
        dst = os.path.join(dest_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy2(src, dst)

    # Update versions.json
    json_path = _get_strategy_versions_json(name)
    versions = _load_versions_json(json_path)
    versions = [v for v in versions
                if not (v.get('name') == name and v.get('tag') == tag)]
    versions.append({
        'name': name,
        'tag': tag,
        'directory': tag,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'description': description,
    })
    _save_versions_json(json_path, versions)

    return dest_dir


# ── List versions ──────────────────────────────────────────────────

def list_versions(component_type: str, name: str) -> list:
    """List all versioned snapshots for a component."""
    if component_type == 'strategy':
        json_path = _get_strategy_versions_json(name)
    else:
        json_path = _get_versions_json(component_type)

    versions = _load_versions_json(json_path)
    return [v for v in versions if v.get('name') == name]


# ── Restore ────────────────────────────────────────────────────────

def restore_component(component_type: str, name: str, tag: str) -> str:
    """Restore a versioned snapshot back to the main source file.

    Returns the path of the restored file.
    """
    json_path = _get_versions_json(component_type)
    versions = _load_versions_json(json_path)
    entry = next((v for v in versions
                  if v.get('name') == name and v.get('tag') == tag), None)
    if entry is None:
        raise ValueError(f'No version "{tag}" found for {component_type} "{name}"')

    versions_dir = _get_versions_dir(component_type)
    versioned_path = os.path.join(versions_dir, entry['file'])
    if not os.path.exists(versioned_path):
        raise FileNotFoundError(f'Versioned file not found: {versioned_path}')

    # Read versioned source and rename class back
    with open(versioned_path, 'r') as f:
        source = f.read()

    if entry.get('class_name') and entry.get('original_class'):
        source = _rename_class(source, entry['class_name'], entry['original_class'])

    dest_path = _get_source_path(component_type, name)
    with open(dest_path, 'w') as f:
        f.write(source)

    return dest_path


def restore_strategy(name: str, tag: str) -> str:
    """Restore a strategy snapshot back to the main directory.

    Returns the path of the restored directory.
    """
    json_path = _get_strategy_versions_json(name)
    versions = _load_versions_json(json_path)
    entry = next((v for v in versions
                  if v.get('name') == name and v.get('tag') == tag), None)
    if entry is None:
        raise ValueError(f'No version "{tag}" found for strategy "{name}"')

    versions_dir = _get_strategy_versions_dir(name)
    snapshot_dir = os.path.join(versions_dir, entry['directory'])
    if not os.path.isdir(snapshot_dir):
        raise FileNotFoundError(f'Snapshot directory not found: {snapshot_dir}')

    strategy_dir = _get_strategy_dir(name)

    # Remove existing files (except versions/ and __pycache__/)
    for item in os.listdir(strategy_dir):
        if item in ('versions', '__pycache__'):
            continue
        path = os.path.join(strategy_dir, item)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    # Copy snapshot files back
    for item in os.listdir(snapshot_dir):
        src = os.path.join(snapshot_dir, item)
        dst = os.path.join(strategy_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    return strategy_dir


# ── Diff ───────────────────────────────────────────────────────────

def diff_versions(component_type: str, name: str,
                  tag_a: str, tag_b: str) -> str:
    """Return a unified diff between two versioned snapshots."""
    import difflib

    if component_type == 'strategy':
        return _diff_strategy_versions(name, tag_a, tag_b)

    json_path = _get_versions_json(component_type)
    versions = _load_versions_json(json_path)
    versions_dir = _get_versions_dir(component_type)

    def _get_source(tag):
        entry = next((v for v in versions
                      if v.get('name') == name and v.get('tag') == tag), None)
        if entry is None:
            raise ValueError(f'No version "{tag}" found for {component_type} "{name}"')
        path = os.path.join(versions_dir, entry['file'])
        with open(path, 'r') as f:
            return f.readlines()

    lines_a = _get_source(tag_a)
    lines_b = _get_source(tag_b)

    diff = difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f'{name} ({tag_a})',
        tofile=f'{name} ({tag_b})',
    )
    return ''.join(diff)


def _diff_strategy_versions(name: str, tag_a: str, tag_b: str) -> str:
    """Diff two strategy version snapshots (all files)."""
    import difflib

    versions_dir = _get_strategy_versions_dir(name)
    dir_a = os.path.join(versions_dir, tag_a)
    dir_b = os.path.join(versions_dir, tag_b)

    if not os.path.isdir(dir_a):
        raise FileNotFoundError(f'Snapshot not found: {dir_a}')
    if not os.path.isdir(dir_b):
        raise FileNotFoundError(f'Snapshot not found: {dir_b}')

    all_files = sorted(set(os.listdir(dir_a)) | set(os.listdir(dir_b)))
    parts = []

    for filename in all_files:
        if filename == '__pycache__':
            continue
        path_a = os.path.join(dir_a, filename)
        path_b = os.path.join(dir_b, filename)

        lines_a = []
        lines_b = []
        if os.path.isfile(path_a):
            with open(path_a, 'r') as f:
                lines_a = f.readlines()
        if os.path.isfile(path_b):
            with open(path_b, 'r') as f:
                lines_b = f.readlines()

        diff = difflib.unified_diff(
            lines_a, lines_b,
            fromfile=f'{tag_a}/{filename}',
            tofile=f'{tag_b}/{filename}',
        )
        diff_text = ''.join(diff)
        if diff_text:
            parts.append(diff_text)

    return '\n'.join(parts) if parts else 'No differences found.'


# ── Auto-registration ──────────────────────────────────────────────

def discover_versioned_components() -> dict:
    """Scan versions/ directories and return registry entries.

    Returns:
        {
            'detectors': {'supertrend_v5__stable': 'openquant.regime.versions.supertrend_detector__stable.SuperTrendDetector_stable'},
            'behaviors': {'bb_mean_reversion__stable': 'openquant.regime.behaviors.versions.bb_mean_reversion__stable.BBMeanReversionBehavior_stable'},
        }
    """
    result = {'detectors': {}, 'behaviors': {}}

    # Scan detector versions
    det_versions_dir = _get_versions_dir('detector')
    det_json = _get_versions_json('detector')
    if os.path.exists(det_json):
        for entry in _load_versions_json(det_json):
            name = entry.get('name')
            tag = entry.get('tag')
            class_name = entry.get('class_name')
            filename = entry.get('file', '').replace('.py', '')
            if name and tag and class_name and filename:
                registry_key = f'{name}__{tag}'
                import_path = f'openquant.regime.versions.{filename}.{class_name}'
                result['detectors'][registry_key] = import_path

    # Scan behavior versions
    beh_versions_dir = _get_versions_dir('behavior')
    beh_json = _get_versions_json('behavior')
    if os.path.exists(beh_json):
        for entry in _load_versions_json(beh_json):
            name = entry.get('name')
            tag = entry.get('tag')
            class_name = entry.get('class_name')
            filename = entry.get('file', '').replace('.py', '')
            if name and tag and class_name and filename:
                registry_key = f'{name}__{tag}'
                import_path = f'openquant.regime.behaviors.versions.{filename}.{class_name}'
                result['behaviors'][registry_key] = import_path

    return result
