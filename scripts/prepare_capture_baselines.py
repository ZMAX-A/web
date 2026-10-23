"""Generate a separate candidate baseline bundle; never overwrite a release.

Only current-capture metadata is migrated. Reference PNG hashes, dimensions,
reference crops, allowed differences and approval records remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.component_capture import validate_component_capture


def prepare(source: Path, profile_path: Path, output: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    if not source.is_dir() or output.exists() or source == output or source in output.parents or output in source.parents:
        raise ValueError('Output must be a new, separate directory outside the source bundle')
    profile_bytes = profile_path.read_bytes()
    profile = json.loads(profile_bytes)
    if profile.get('profile_version') != 1 or profile.get('status') not in ('candidate', 'validated'):
        raise ValueError('Invalid capture profile')
    case_id = profile['case_id']
    if not isinstance(case_id, str) or not case_id or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for ch in case_id):
        raise ValueError('Unsafe case ID')
    relative = Path(case_id) / 'steps/steps.meta.json'
    original_bytes = (source / relative).read_bytes()
    metadata = json.loads(original_bytes)
    if metadata['case_id'] != case_id or metadata['approved_for_visual_testing'] is not True:
        raise ValueError('Unapproved or wrong baseline')
    profiles = profile['references']
    if not isinstance(profiles, dict) or not profiles or not set(profiles) <= set(metadata['references']):
        raise ValueError('Unknown or empty profile references')
    hashes = {}
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlinks are not permitted in baseline bundles')
        if path.is_file():
            hashes[path.relative_to(source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for filename, config in profiles.items():
        if Path(filename).name != filename or '/' in filename or '\\' in filename:
            raise ValueError('Unsafe reference filename')
        validate_component_capture(config)
        entry = metadata['references'][filename]
        image_path = source / case_id / 'steps' / filename
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != entry['image_sha256']:
            raise ValueError('Reference image hash mismatch')
        entry.pop('current_crop_box', None)
        entry['current_capture'] = config
    updated = (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    shutil.copytree(source, output)
    (output / relative).write_bytes(updated)
    for name, digest in hashes.items():
        if name != relative.as_posix() and hashlib.sha256((output / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Unexpected change to copied baseline asset')
    receipt = {'status': 'candidate-not-deployed', 'case_id': case_id,
               'profile_sha256': hashlib.sha256(profile_bytes).hexdigest(),
               'source_metadata_sha256': hashlib.sha256(original_bytes).hexdigest(),
               'candidate_metadata_sha256': hashlib.sha256(updated).hexdigest(),
               'changed_files': [relative.as_posix()],
               'unchanged_file_count': len(hashes) - 1}
    (output / 'capture-migration.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.profile, args.output)))
