import pytest

from utils import component_capture as capture


def anchor(locator, count=1):
    return {'locator': locator, 'ancestor_levels': 0, 'count': count}


def config():
    return {'strategy': 'component_region', 'target': anchor('#canvas'),
            'edges': {'left': anchor('#tools'), 'bottom': anchor('#thumbs')},
            'ready': {'visible': [anchor('#selected')], 'hidden': ['#loading']},
            'stable_ms': 400, 'sample_ms': 100}


def test_clip_uses_component_edges_not_absolute_page_coordinates():
    rect = {'x': 100.2, 'y': 20.5, 'width': 900, 'height': 700}
    edges = {'left': [{'x': 110, 'y': 30, 'width': 80.5, 'height': 100}],
             'bottom': [{'x': 200, 'y': 600.8, 'width': 300, 'height': 100}]}
    result = capture.resolve_clip(rect, edges, {'width': 1200, 'height': 800})
    assert result == {'x': 191, 'y': 21, 'width': 809, 'height': 579}
    moved = lambda b: dict(b, x=b['x'] + 50, y=b['y'] + 30)
    shifted = capture.resolve_clip(moved(rect), {k: [moved(b) for b in v] for k, v in edges.items()},
                                   {'width': 1400, 'height': 900})
    assert shifted == dict(result, x=241, y=51)


def test_bottom_boundary_uses_earliest_of_split_screen_toolbars():
    result = capture.resolve_clip({'x': 0, 'y': 0, 'width': 900, 'height': 700},
        {'bottom': [{'x': 0, 'y': 600, 'width': 300, 'height': 50},
                    {'x': 450, 'y': 550, 'width': 300, 'height': 50}]},
        {'width': 900, 'height': 700})
    assert result['height'] == 550


def test_page_region_keeps_header_but_ends_at_canvas_right_edge():
    result = capture.resolve_clip({'x': 0, 'y': 0, 'width': 2561, 'height': 1398},
        {'right': [{'x': 0, 'y': 84.5, 'width': 1831, 'height': 1314}]},
        {'width': 2561, 'height': 1398}, {'right': 'right'})
    assert result == {'x': 0, 'y': 0, 'width': 1831, 'height': 1398}


@pytest.mark.parametrize('box', [
    {'x': -1, 'y': 0, 'width': 100, 'height': 100},
    {'x': 0, 'y': 0, 'width': 1001, 'height': 100},
    {'x': 0, 'y': 0, 'width': 23, 'height': 100},
    {'x': float('nan'), 'y': 0, 'width': 100, 'height': 100},
    {'x': 0, 'y': 0, 'width': 100, 'height': -1},
])
def test_invalid_geometry_fails_closed(box):
    with pytest.raises(capture.ComponentCaptureError, match='STEP_CAPTURE_GEOMETRY'):
        capture.resolve_clip(box, {}, {'width': 1000, 'height': 800})


@pytest.mark.parametrize('mutation', [
    lambda c: c.update(extra=True),
    lambda c: c['target'].update(count=2),
    lambda c: c['target'].update(ancestor_levels=True),
    lambda c: c['edges'].update(unknown=anchor('#bad')),
    lambda c: c['edges']['left'].update(side='top'),
    lambda c: c['ready'].update(visible=[]),
    lambda c: c['ready'].update(hidden=['']),
    lambda c: c.update(sample_ms=0),
    lambda c: c.update(stable_ms=100),
])
def test_invalid_config_rejected(mutation):
    value = config()
    mutation(value)
    with pytest.raises(capture.ComponentCaptureError, match='STEP_CAPTURE_CONFIG'):
        capture.validate_component_capture(value)


class FakeLocator:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, i):
        return FakeLocator([self.items[i]])

    def locator(self, selector):
        assert selector == 'xpath=..'
        return self

    def is_visible(self):
        return self.items[0].get('visible', True)

    def bounding_box(self):
        return {k: self.items[0][k] for k in ('x', 'y', 'width', 'height')}


class FakePage:
    def __init__(self):
        self.now = 0
        self.calls = []
        self.frames = [b'frame']
        self.nonblank = True
        self.state = {'width': 1000, 'height': 800, 'scrollX': 0, 'scrollY': 0, 'fontsReady': True}
        self.boxes = {'#canvas': [{'x': 0, 'y': 0, 'width': 900, 'height': 700}],
                      '#tools': [{'x': 10, 'y': 20, 'width': 100, 'height': 100}],
                      '#thumbs': [{'x': 200, 'y': 600, 'width': 300, 'height': 50}],
                      '#selected': [{'x': 20, 'y': 20, 'width': 60, 'height': 30}], '#loading': []}

    def locator(self, selector):
        return FakeLocator(self.boxes[selector])

    def evaluate(self, script, *args):
        if args:
            import base64
            value = {b'loading': 0, b'rotating': 50, b'ready': 100}.get(base64.b64decode(args[0]), 100)
            return {'nonblank': self.nonblank, 'pixels': [value,value,value,255] * (64 * 64)}
        return dict(self.state)

    def screenshot(self, **kwargs):
        self.calls.append(kwargs)
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def wait_for_timeout(self, ms):
        self.now += ms / 1000


def test_waits_for_same_geometry_and_rendered_frame(monkeypatch):
    page = FakePage()
    page.frames = [b'loading', b'rotating', b'ready']
    monkeypatch.setattr(capture.time, 'monotonic', lambda: page.now)
    png, evidence = capture.capture_component_region(page, config(), 2000)
    assert png == b'ready'
    assert evidence['samples'] >= 7
    assert evidence['stable_ms'] >= 400
    assert page.calls[-1]['clip'] == {'x': 110, 'y': 0, 'width': 790, 'height': 600}
    assert page.calls[-1]['scale'] == 'css'


@pytest.mark.parametrize('problem', ['blank', 'missing', 'duplicate', 'loading', 'scrolled', 'fonts', 'no-selected'])
def test_not_ready_never_returns_image(monkeypatch, problem):
    page = FakePage()
    if problem == 'blank': page.nonblank = False
    if problem == 'missing': page.boxes['#tools'] = []
    if problem == 'duplicate': page.boxes['#canvas'] *= 2
    if problem == 'loading': page.boxes['#loading'] = page.boxes['#tools']
    if problem == 'scrolled': page.state['scrollY'] = 30
    if problem == 'fonts': page.state['fontsReady'] = False
    if problem == 'no-selected': page.boxes['#selected'] = []
    monkeypatch.setattr(capture.time, 'monotonic', lambda: page.now)
    with pytest.raises(capture.ComponentCaptureError, match='STEP_CAPTURE_NOT_READY'):
        capture.capture_component_region(page, config(), 1000)
    if problem != 'blank': assert not page.calls


def test_changing_geometry_never_returns_image(monkeypatch):
    page = FakePage()
    original = page.screenshot
    def moving(**kwargs):
        result = original(**kwargs)
        page.boxes['#canvas'][0]['width'] -= 1
        return result
    page.screenshot = moving
    monkeypatch.setattr(capture.time, 'monotonic', lambda: page.now)
    with pytest.raises(capture.ComponentCaptureError, match='layout changed'):
        capture.capture_component_region(page, config(), 1000)


def test_timeout_must_allow_stability_window():
    with pytest.raises(capture.ComponentCaptureError, match='timeout shorter'):
        capture.capture_component_region(FakePage(), config(), 100)


def test_frame_difference_detects_motion_but_allows_tiny_raster_noise():
    first = [100, 100, 100, 255] * (64 * 64)
    noise = first.copy()
    noise[0] += 1
    mean, fraction = capture.frame_difference(first, noise)
    assert mean < .5 and fraction == 0
    moving = [110, 110, 110, 255] * (64 * 64)
    assert capture.frame_difference(first, moving) == (10, 1)


def test_042_profile_has_explicit_state_and_no_ambiguous_angle_selector():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'test_assets/vision_capture_profiles/TC-IMAGE-042.json'
    profile = json.loads(path.read_text(encoding='utf-8'))
    assert len(profile['references']) == 10
    for config in profile['references'].values():
        capture.validate_component_capture(config)
        assert config['ready']['hidden']
        assert all(a['locator'] != 'text=0°' for a in config['ready']['visible'])
    split = profile['references']['step_013_FenPing.png']
    assert split['edges']['bottom']['count'] == 2
    assert any('ant-radio-button-wrapper-checked' in a['locator'] for a in split['ready']['visible'])
    for name in ('step_005_page_loaded.png', 'step_014_JingXiang.png'):
        cfg = profile['references'][name]
        assert cfg['target']['locator'] == 'body'
        assert cfg['edges']['right']['side'] == 'right'
