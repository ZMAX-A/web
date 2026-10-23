import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('capture_migration', Path(__file__).resolve().parents[1] / 'scripts/prepare_capture_baselines.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def setup_bundle(tmp_path):
    source = tmp_path / 'source'
    steps = source / 'TC-IMAGE-042/steps'
    steps.mkdir(parents=True)
    image = b'immutable reference'
    (steps / 'step_010_L90.png').write_bytes(image)
    entry = {'image_sha256': hashlib.sha256(image).hexdigest(), 'image_width': 800,
             'image_height': 600, 'crop_box': [0, 0, 500, 400], 'current_crop_box': [20, 20, 500, 400]}
    meta = {'case_id': 'TC-IMAGE-042', 'approved_for_visual_testing': True,
            'references': {'step_010_L90.png': entry}}
    (steps / 'steps.meta.json').write_text(json.dumps(meta))
    anchor = {'locator': 'canvas', 'ancestor_levels': 0, 'count': 1}
    config = {'strategy': 'component_region', 'target': anchor, 'edges': {},
              'ready': {'visible': [anchor], 'hidden': []}, 'stable_ms': 600, 'sample_ms': 200}
    profile = {'profile_version': 1, 'status': 'candidate', 'case_id': 'TC-IMAGE-042',
               'references': {'step_010_L90.png': config}}
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(profile))
    return source, path, meta


def test_migration_preserves_reference_images_crops_and_source(tmp_path):
    source, profile, before = setup_bundle(tmp_path)
    original = (source / 'TC-IMAGE-042/steps/steps.meta.json').read_bytes()
    output = tmp_path / 'candidate'
    receipt = migration.prepare(source, profile, output)
    assert (source / 'TC-IMAGE-042/steps/steps.meta.json').read_bytes() == original
    assert (output / 'TC-IMAGE-042/steps/step_010_L90.png').read_bytes() == b'immutable reference'
    after = json.loads((output / 'TC-IMAGE-042/steps/steps.meta.json').read_text())
    assert after['references']['step_010_L90.png']['crop_box'] == before['references']['step_010_L90.png']['crop_box']
    assert 'current_crop_box' not in after['references']['step_010_L90.png']
    assert receipt['status'] == 'candidate-not-deployed'
    with pytest.raises(ValueError, match='new, separate'):
        migration.prepare(source, profile, output)


@pytest.mark.parametrize('relative', ['source', 'source/new'])
def test_migration_refuses_in_place_or_nested_output(tmp_path, relative):
    source, profile, _ = setup_bundle(tmp_path)
    with pytest.raises(ValueError, match='new, separate'):
        migration.prepare(source, profile, tmp_path / relative)


def test_migration_rejects_changed_reference_before_creating_output(tmp_path):
    source, profile, _ = setup_bundle(tmp_path)
    (source / 'TC-IMAGE-042/steps/step_010_L90.png').write_bytes(b'changed')
    output = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='hash mismatch'):
        migration.prepare(source, profile, output)
    assert not output.exists()
