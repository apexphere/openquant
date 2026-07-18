"""Tests for the dev versioning system."""
import json
import os
import shutil
import tempfile

import pytest

from openquant.versioning import (
    _find_class_name,
    _rename_class,
    snapshot_component,
    snapshot_strategy,
    list_versions,
    restore_component,
    restore_strategy,
    diff_versions,
    discover_versioned_components,
)


# ── Class manipulation tests ──────────────────────────────────────

def test_find_class_name():
    source = 'class SuperTrendDetector:\n    pass\n'
    assert _find_class_name(source) == 'SuperTrendDetector'


def test_find_class_name_with_parent():
    source = 'class MyDetector(BaseDetector):\n    pass\n'
    assert _find_class_name(source) == 'MyDetector'


def test_find_class_name_none():
    source = '# no class here\nx = 1\n'
    assert _find_class_name(source) is None


def test_rename_class():
    source = 'class SuperTrendDetector:\n    pass\n'
    result = _rename_class(source, 'SuperTrendDetector', 'SuperTrendDetector_stable')
    assert 'class SuperTrendDetector_stable:' in result
    assert 'class SuperTrendDetector:' not in result


# ── Detector snapshot/restore tests ──────────────────────────────

@pytest.fixture
def temp_detector_env(tmp_path, monkeypatch):
    """Set up a temporary detector environment."""
    regime_dir = tmp_path / 'regime'
    regime_dir.mkdir()
    versions_dir = regime_dir / 'versions'
    versions_dir.mkdir()
    (versions_dir / '__init__.py').write_text('')

    # Create a fake detector
    detector_source = (
        '"""Test detector."""\n'
        'class FakeDetector:\n'
        '    def detect(self, candles):\n'
        '        return "trending-up"\n'
    )
    (regime_dir / 'fake_detector.py').write_text(detector_source)

    # Monkeypatch the module-level paths
    import openquant.versioning as v
    monkeypatch.setattr(v, '_COMPONENT_PATHS', {
        'detector': {
            'source_dir': str(regime_dir),
            'versions_dir': str(versions_dir),
        },
        'behavior': {
            'source_dir': str(regime_dir),
            'versions_dir': str(versions_dir),
        },
    })

    # Monkeypatch resolver to return our fake name
    monkeypatch.setattr(v, '_resolve_detector_file', lambda name: 'fake_detector')

    return {
        'regime_dir': regime_dir,
        'versions_dir': versions_dir,
        'source_file': regime_dir / 'fake_detector.py',
    }


def test_snapshot_creates_versioned_file(temp_detector_env):
    path = snapshot_component('detector', 'fake', 'stable', 'first stable version')

    assert os.path.exists(path)
    assert path.endswith('fake_detector__stable.py')

    with open(path) as f:
        content = f.read()
    assert 'class FakeDetector_stable:' in content
    assert 'class FakeDetector:' not in content


def test_snapshot_creates_versions_json(temp_detector_env):
    snapshot_component('detector', 'fake', 'stable')

    json_path = os.path.join(str(temp_detector_env['versions_dir']), 'versions.json')
    assert os.path.exists(json_path)

    with open(json_path) as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]['name'] == 'fake'
    assert data[0]['tag'] == 'stable'
    assert data[0]['class_name'] == 'FakeDetector_stable'
    assert data[0]['original_class'] == 'FakeDetector'


def test_snapshot_overwrites_same_tag(temp_detector_env):
    snapshot_component('detector', 'fake', 'stable', 'v1')
    snapshot_component('detector', 'fake', 'stable', 'v2')

    json_path = os.path.join(str(temp_detector_env['versions_dir']), 'versions.json')
    with open(json_path) as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]['description'] == 'v2'


def test_list_versions(temp_detector_env):
    snapshot_component('detector', 'fake', 'stable')
    snapshot_component('detector', 'fake', 'experiment1')

    entries = list_versions('detector', 'fake')
    assert len(entries) == 2
    tags = {e['tag'] for e in entries}
    assert tags == {'stable', 'experiment1'}


def test_restore_component(temp_detector_env):
    # Snapshot original
    snapshot_component('detector', 'fake', 'stable')

    # Modify the source file
    source_file = temp_detector_env['source_file']
    source_file.write_text(
        'class FakeDetector:\n'
        '    def detect(self, candles):\n'
        '        return "ranging"\n'
    )

    # Restore from stable
    restore_component('detector', 'fake', 'stable')

    with open(str(source_file)) as f:
        content = f.read()
    assert 'return "trending-up"' in content
    assert 'class FakeDetector:' in content  # class name restored


def test_restore_missing_version(temp_detector_env):
    with pytest.raises(ValueError, match='No version'):
        restore_component('detector', 'fake', 'nonexistent')


# ── Strategy snapshot/restore tests ──────────────────────────────

@pytest.fixture
def temp_strategy_env(tmp_path, monkeypatch):
    """Set up a temporary strategy environment."""
    strategies_dir = tmp_path / 'strategies'
    strategy_dir = strategies_dir / 'TestStrategy'
    strategy_dir.mkdir(parents=True)

    (strategy_dir / '__init__.py').write_text(
        'class TestStrategy:\n    config_file = "config.yaml"\n'
    )
    (strategy_dir / 'config.yaml').write_text(
        'detector:\n  type: adx\nregimes:\n  trending-up: trend_follow\n'
    )

    import openquant.versioning as v
    monkeypatch.setattr(v, '_STRATEGIES_DIR', str(strategies_dir))

    return {'strategies_dir': strategies_dir, 'strategy_dir': strategy_dir}


def test_snapshot_strategy(temp_strategy_env):
    path = snapshot_strategy('TestStrategy', 'stable')

    assert os.path.isdir(path)
    assert os.path.exists(os.path.join(path, '__init__.py'))
    assert os.path.exists(os.path.join(path, 'config.yaml'))


def test_restore_strategy(temp_strategy_env):
    snapshot_strategy('TestStrategy', 'stable')

    # Modify the strategy
    init_path = temp_strategy_env['strategy_dir'] / '__init__.py'
    init_path.write_text('class TestStrategy:\n    config_file = "modified.yaml"\n')

    # Restore
    restore_strategy('TestStrategy', 'stable')

    with open(str(init_path)) as f:
        content = f.read()
    assert 'config.yaml' in content
    assert 'modified.yaml' not in content


def test_list_strategy_versions(temp_strategy_env):
    snapshot_strategy('TestStrategy', 'stable')
    snapshot_strategy('TestStrategy', 'experiment1')

    entries = list_versions('strategy', 'TestStrategy')
    assert len(entries) == 2


# ── Diff tests ───────────────────────────────────────────────────

def test_diff_versions(temp_detector_env):
    # Snapshot v1
    snapshot_component('detector', 'fake', 'v1')

    # Modify source and snapshot v2
    source_file = temp_detector_env['source_file']
    source_file.write_text(
        '"""Test detector."""\n'
        'class FakeDetector:\n'
        '    def detect(self, candles):\n'
        '        return "ranging"\n'
    )
    snapshot_component('detector', 'fake', 'v2')

    result = diff_versions('detector', 'fake', 'v1', 'v2')
    assert 'trending-up' in result
    assert 'ranging' in result


def test_diff_strategy_versions(temp_strategy_env):
    snapshot_strategy('TestStrategy', 'v1')

    # Modify and snapshot again
    config_path = temp_strategy_env['strategy_dir'] / 'config.yaml'
    config_path.write_text(
        'detector:\n  type: ema_adx\nregimes:\n  trending-up: trend_follow\n'
    )
    snapshot_strategy('TestStrategy', 'v2')

    result = diff_versions('strategy', 'TestStrategy', 'v1', 'v2')
    assert 'adx' in result
    assert 'ema_adx' in result


# ── Auto-discovery tests ─────────────────────────────────────────

def test_discover_versioned_components(temp_detector_env):
    snapshot_component('detector', 'fake', 'stable')

    discovered = discover_versioned_components()
    assert 'fake__stable' in discovered['detectors']
    assert 'FakeDetector_stable' in discovered['detectors']['fake__stable']
