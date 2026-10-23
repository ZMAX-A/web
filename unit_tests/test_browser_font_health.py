import pytest
from utils.browser_font_health import BrowserFontHealthError, check_browser_font_health, validate_font_metrics


def healthy():
    return {direction: {"fontSize": 16, "chars": [{axis: 8 + i * 16} for i in range(8)]}
            for direction, axis in (("horizontal", "x"), ("vertical", "y"))}


def test_regular_cjk_advances_pass():
    validate_font_metrics(healthy())


@pytest.mark.parametrize('advance', [0, 2.561, -16, float('nan'), float('inf'), 32])
def test_collapsed_or_invalid_vertical_advances_fail(advance):
    data = healthy()
    data['vertical']['chars'] = [{'y': i * advance} for i in range(8)]
    with pytest.raises(BrowserFontHealthError, match='BROWSER_CJK_FONT_METRICS_INVALID'):
        validate_font_metrics(data)


@pytest.mark.parametrize('data', [{}, {'horizontal': None}, {'horizontal': {'fontSize': 0, 'chars': []}}])
def test_missing_evidence_fails(data):
    with pytest.raises(BrowserFontHealthError):
        validate_font_metrics(data)


@pytest.mark.parametrize('broken', [False, True])
def test_probe_uses_and_closes_separate_context(broken):
    class Page:
        samples = []
        def set_content(self, html, **kwargs):
            assert 'writing-mode:vertical-rl' in html
            assert 'http' not in html
            self.samples.append(html)
        def evaluate(self, script):
            return {} if broken else healthy()
    class Context:
        closed = False
        def new_page(self): return Page()
        def close(self): self.closed = True
    class Browser:
        context = Context()
        def new_context(self, **kwargs):
            assert kwargs['locale'] == 'zh-CN'
            return self.context
    browser = Browser()
    if broken:
        with pytest.raises(BrowserFontHealthError): check_browser_font_health(browser)
    else:
        check_browser_font_health(browser)
        assert len(Page.samples) == 12
        assert any('WenQuanYi Zen Hei' in html for html in Page.samples)
        assert any('lang="en"' in html for html in Page.samples)
    assert browser.context.closed
