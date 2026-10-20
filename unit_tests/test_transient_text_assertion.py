import pytest

from utils.assertion_executor import AssertionExecutor


class TextPage:
    """A page whose message can appear while Playwright yields to the browser."""

    def __init__(self, text_at):
        self.now = 0
        self.text_at = text_at

    def locator(self, selector):
        page = self

        class Element:
            @property
            def first(self):
                return self

            def inner_text(self, timeout=None):
                if selector == "body":
                    return page.text_at(page.now)
                # A missing implicit last-step locator must not consume two seconds.
                page.now += timeout
                raise RuntimeError("element missing")

        return Element()

    def wait_for_timeout(self, milliseconds):
        self.now += milliseconds


def test_contains_waits_for_a_delayed_short_message_with_missing_locator(monkeypatch):
    page = TextPage(lambda now: "账号或密码错误" if 150 <= now < 350 else "登录页")
    monkeypatch.setattr("utils.assertion_executor.time.monotonic", lambda: page.now / 1000)
    assert AssertionExecutor(page, timeout_ms=500).assert_by_type(
        "text_contains", "页面显示'账号或密码错误'", "#missing"
    )
    assert page.now < 350


def test_contains_does_not_pass_for_a_different_message(monkeypatch):
    page = TextPage(lambda now: "请输入账号")
    monkeypatch.setattr("utils.assertion_executor.time.monotonic", lambda: page.now / 1000)
    with pytest.raises(AssertionError, match="文本不包含「账号或密码错误」"):
        AssertionExecutor(page, timeout_ms=350).assert_by_type(
            "text_contains", "页面显示'账号或密码错误'"
        )
    assert page.now == 350


def test_contains_does_not_accept_an_already_expired_message(monkeypatch):
    page = TextPage(lambda now: "登录页")
    monkeypatch.setattr("utils.assertion_executor.time.monotonic", lambda: page.now / 1000)
    with pytest.raises(AssertionError, match="文本不包含"):
        AssertionExecutor(page, timeout_ms=200).assert_by_type(
            "text_contains", "页面显示'账号或密码错误'"
        )
