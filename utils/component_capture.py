"""Fail-closed, DOM-anchored screenshot regions; no image matching or UI mutation.

The configured boundaries define the comparison scope, not a way to remove a
detected difference. Baseline PNGs and their reference crops remain immutable.
"""
from __future__ import annotations

import base64
import hashlib
import math
import time
from typing import Any


class ComponentCaptureError(RuntimeError):
    pass


def _selector(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_anchor(anchor: Any, *, target: bool = False, allow_side: bool = False) -> None:
    required = {'locator', 'ancestor_levels', 'count'}
    optional = {'side'} if allow_side else set()
    if not isinstance(anchor, dict) or not required <= set(anchor) or not set(anchor) <= required | optional:
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: anchor requires locator, ancestor_levels, count')
    if not _selector(anchor['locator']):
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: empty locator')
    if type(anchor['ancestor_levels']) is not int or not 0 <= anchor['ancestor_levels'] <= 8:
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: ancestor_levels must be 0..8')
    if type(anchor['count']) is not int or not 1 <= anchor['count'] <= 8 or (target and anchor['count'] != 1):
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: invalid expected count')


def validate_component_capture(config: Any) -> dict:
    fields = {'strategy', 'target', 'edges', 'ready', 'stable_ms', 'sample_ms'}
    if not isinstance(config, dict) or set(config) != fields or config.get('strategy') != 'component_region':
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: invalid component_region fields')
    _validate_anchor(config['target'], target=True)
    edges = config['edges']
    if not isinstance(edges, dict) or not set(edges) <= {'left', 'top', 'right', 'bottom'}:
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: invalid edges')
    for edge, anchor in edges.items():
        _validate_anchor(anchor, allow_side=True)
        if 'side' in anchor and anchor['side'] not in ({'left', 'right'} if edge in ('left', 'right') else {'top', 'bottom'}):
            raise ComponentCaptureError('STEP_CAPTURE_CONFIG: boundary side must use the same axis')
    ready = config['ready']
    if not isinstance(ready, dict) or set(ready) != {'visible', 'hidden'}:
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: ready requires visible and hidden')
    if not isinstance(ready['visible'], list) or not ready['visible']:
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: explicit visible state required')
    for anchor in ready['visible']:
        _validate_anchor(anchor)
    if not isinstance(ready['hidden'], list) or any(not _selector(s) for s in ready['hidden']):
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: invalid hidden selectors')
    stable, sample = config['stable_ms'], config['sample_ms']
    if type(sample) is not int or not 50 <= sample <= 1000:
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: sample_ms must be 50..1000')
    if type(stable) is not int or not max(200, 2 * sample) <= stable <= 5000:
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: invalid stable_ms')
    return config


def resolve_clip(target: dict, edges: dict[str, list[dict]], viewport: dict,
                 sides: dict[str, str] | None = None) -> dict:
    """Intersect inward DOM edges; reject inverted, offscreen or tiny regions.

    Left/top boundaries use the far edge of the excluded component; right/bottom
    boundaries use its near edge. Multiple anchors must all be outside the ROI.
    """
    for box in [target, *(b for boxes in edges.values() for b in boxes)]:
        if not all(type(box.get(k)) in (int, float) and math.isfinite(box[k]) for k in ('x', 'y', 'width', 'height')):
            raise ComponentCaptureError('STEP_CAPTURE_GEOMETRY: invalid rectangle')
        if box['width'] <= 0 or box['height'] <= 0:
            raise ComponentCaptureError('STEP_CAPTURE_GEOMETRY: empty rectangle')
    x, y = target['x'], target['y']
    right, bottom = x + target['width'], y + target['height']
    for edge, boxes in edges.items():
        if not boxes:
            raise ComponentCaptureError('STEP_CAPTURE_GEOMETRY: missing boundary')
        if edge not in ('left', 'top', 'right', 'bottom'):
            raise ComponentCaptureError('STEP_CAPTURE_GEOMETRY: unknown boundary')
        default_side = {'left': 'right', 'top': 'bottom', 'right': 'left', 'bottom': 'top'}[edge]
        side = (sides or {}).get(edge, default_side)
        axis = 'x' if edge in ('left', 'right') else 'y'
        size = 'width' if axis == 'x' else 'height'
        values = [b[axis] + (b[size] if side in ('right', 'bottom') else 0) for b in boxes]
        if edge == 'left': x = max(x, *values)
        elif edge == 'top': y = max(y, *values)
        elif edge == 'right': right = min(right, *values)
        elif edge == 'bottom': bottom = min(bottom, *values)
    # Inward rounding never accidentally includes a neighboring control.
    x, y, right, bottom = math.ceil(x), math.ceil(y), math.floor(right), math.floor(bottom)
    if x < 0 or y < 0 or right > viewport['width'] or bottom > viewport['height']:
        raise ComponentCaptureError('STEP_CAPTURE_GEOMETRY: region outside viewport')
    if right - x < 24 or bottom - y < 24:
        raise ComponentCaptureError('STEP_CAPTURE_GEOMETRY: region too small or inverted')
    return {'x': x, 'y': y, 'width': right - x, 'height': bottom - y}


def _boxes(page, anchor: dict) -> list[dict]:
    matches = page.locator(anchor['locator'])
    count = matches.count()
    if count != anchor['count']:
        raise ComponentCaptureError(
            f"STEP_CAPTURE_STATE: anchor {anchor['locator']!r} expected {anchor['count']} matches, got {count}"
        )
    result = []
    for index in range(anchor['count']):
        item = matches.nth(index)
        for _ in range(anchor['ancestor_levels']):
            item = item.locator('xpath=..')
        if not item.is_visible():
            raise ComponentCaptureError('STEP_CAPTURE_STATE: required component not visible')
        box = item.bounding_box()
        if box is None:
            raise ComponentCaptureError('STEP_CAPTURE_STATE: component has no box')
        if box in result:
            raise ComponentCaptureError('STEP_CAPTURE_STATE: multiple anchors resolve to same component')
        result.append(box)
    return result


def _geometry(page, config: dict) -> tuple[dict, dict]:
    state = page.evaluate('''() => ({width:innerWidth,height:innerHeight,
        scrollX,scrollY,fontsReady:document.fonts.status === 'loaded'})''')
    if state['scrollX'] != 0 or state['scrollY'] != 0:
        raise ComponentCaptureError('STEP_CAPTURE_STATE: viewport must not be scrolled')
    if not state['fontsReady']:
        raise ComponentCaptureError('STEP_CAPTURE_STATE: fonts not loaded')
    for selector in config['ready']['hidden']:
        matches = page.locator(selector)
        if any(matches.nth(i).is_visible() for i in range(matches.count())):
            raise ComponentCaptureError('STEP_CAPTURE_STATE: loading indicator still visible')
    for anchor in config['ready']['visible']:
        _boxes(page, anchor)
    target = _boxes(page, config['target'])[0]
    edges = {edge: _boxes(page, anchor) for edge, anchor in config['edges'].items()}
    sides = {edge: anchor['side'] for edge, anchor in config['edges'].items() if 'side' in anchor}
    clip = resolve_clip(target, edges, state, sides)
    return clip, {'viewport': {'width': state['width'], 'height': state['height']},
                  'target': target, 'edges': edges, 'clip': clip}


_FRAME_SAMPLE = '''async data => {
    const blob = await (await fetch('data:image/png;base64,' + data)).blob();
    const image = await createImageBitmap(blob);
    const canvas = document.createElement('canvas'); canvas.width=64; canvas.height=64;
    const ctx=canvas.getContext('2d'); ctx.drawImage(image,0,0,64,64); image.close();
    const p=ctx.getImageData(0,0,64,64).data;
    let different=0;
    for(let i=0;i<p.length;i+=4)
        if(Math.max(Math.abs(p[i]-p[0]),Math.abs(p[i+1]-p[1]),Math.abs(p[i+2]-p[2]))>12) different++;
    return {nonblank:different >= 40, pixels:Array.from(p)};
}'''


def frame_difference(first: list[int], current: list[int]) -> tuple[float, float]:
    """Readiness only, never the baseline verdict. Compare to the window's first
    frame, not the previous frame, so slow cumulative motion cannot pass.
    A tiny allowance covers WebGL raster noise; ordinary visual checks follow.
    """
    if len(first) != len(current) or len(first) != 64 * 64 * 4:
        raise ComponentCaptureError('STEP_CAPTURE_FRAME: invalid decoded frame')
    total, changed = 0, 0
    for i in range(0, len(first), 4):
        delta = [abs(first[i + j] - current[i + j]) for j in range(3)]
        total += sum(delta)
        changed += max(delta) > 8
    return total / (64 * 64 * 3), changed / (64 * 64)


def capture_component_region(page, config: dict, timeout_ms: int) -> tuple[bytes, dict]:
    """Require bounded state + geometry + stable rendered frames before use.

    Stability is not proof of semantic correctness: blank frames are rejected,
    and the ordinary model comparison still evaluates the captured subject.
    """
    validate_component_capture(config)
    if timeout_ms <= config['stable_ms']:
        raise ComponentCaptureError('STEP_CAPTURE_CONFIG: timeout shorter than stability window')
    deadline = time.monotonic() + timeout_ms / 1000
    last_key, stable_since, observations = None, None, 0
    first_pixels = None
    last_reason = 'no samples'
    last_failure = ''
    while time.monotonic() < deadline:
        try:
            clip, evidence = _geometry(page, config)
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            try:
                png = page.screenshot(type='png', full_page=False, clip=clip, scale='css',
                                      animations='disabled', caret='hide', timeout=remaining)
            except Exception as exc:
                raise ComponentCaptureError('STEP_CAPTURE_SCREENSHOT: capture timed out or failed') from exc
            after_clip, after = _geometry(page, config)
            if after_clip != clip or after != evidence:
                raise ComponentCaptureError('STEP_CAPTURE_STATE: layout changed during screenshot')
            digest = hashlib.sha256(png).hexdigest()
            frame = page.evaluate(_FRAME_SAMPLE, base64.b64encode(png).decode('ascii'))
            if not frame['nonblank']:
                raise ComponentCaptureError('STEP_CAPTURE_BLANK: blank/flat region')
            key = repr(evidence)
            now = time.monotonic()
            observations += 1
            mean_delta, changed_fraction = frame_difference(first_pixels or frame['pixels'], frame['pixels'])
            if key != last_key or mean_delta > .5 or changed_fraction > .005:
                last_key, stable_since = key, now
                first_pixels = frame['pixels']
            elif now - stable_since >= config['stable_ms'] / 1000:
                evidence.update({'strategy': 'component_region', 'sha256': digest,
                                 'stable_ms': round((now - stable_since) * 1000),
                                 'samples': observations, 'mean_channel_delta': mean_delta,
                                 'changed_sample_fraction': changed_fraction})
                return png, evidence
            last_reason = 'rendered frames not yet stable'
        except ComponentCaptureError as exc:
            last_reason = str(exc)
            # A final screenshot may exhaust the remaining deadline. Keep the
            # earlier actionable state/blank diagnosis instead of hiding it.
            if 'STEP_CAPTURE_SCREENSHOT' not in last_reason or not last_failure:
                last_failure = last_reason
            last_key, stable_since = None, None
            first_pixels = None
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            break
        page.wait_for_timeout(min(config['sample_ms'], remaining))
    raise ComponentCaptureError('STEP_CAPTURE_NOT_READY: ' + (last_failure or last_reason))
