"""Fail closed on broken CJK glyph advances without changing the tested page."""
from __future__ import annotations

import json
import math


class BrowserFontHealthError(RuntimeError):
    """The browser cannot lay out ordinary CJK vertical text reliably."""


_FONT_STACKS = ("sans-serif", "Arial, sans-serif",
                "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, Noto Sans, sans-serif",
                "WenQuanYi Zen Hei, sans-serif")
_HTML = """<!doctype html><html lang="LANGUAGE"><meta charset="utf-8">
<style>span{font-family:FONTSTACK;font-size:16px;line-height:24px;
letter-spacing:0;white-space:nowrap;display:inline-block}
#vertical{writing-mode:vertical-rl}</style>
<span id="horizontal">模式图谱诊断图谱</span><span id="vertical">模式图谱诊断图谱</span></html>"""

_MEASURE = """() => {
 const measure=id=>{const e=document.getElementById(id),t=e.firstChild;
  const chars=[];for(let i=0;i<t.length;i++){const r=document.createRange();
   r.setStart(t,i);r.setEnd(t,i+1);const b=r.getBoundingClientRect();
   chars.push({x:b.x,y:b.y,width:b.width,height:b.height});}
  return {fontSize:parseFloat(getComputedStyle(e).fontSize),chars};};
 return {horizontal:measure('horizontal'),vertical:measure('vertical')};
}"""


def validate_font_metrics(metrics: dict) -> None:
    """Check actual glyph offsets, not model opinions or font-file presence."""
    for direction, axis in (("horizontal", "x"), ("vertical", "y")):
        try:
            entry = metrics[direction]
            size = float(entry["fontSize"])
            chars = entry["chars"]
            advances = [float(b[axis]) - float(a[axis]) for a, b in zip(chars, chars[1:])]
            valid = (math.isfinite(size) and size > 0 and len(chars) == 8
                     and all(math.isfinite(v) and size * .7 <= v <= size * 1.5 for v in advances))
        except (KeyError, TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise BrowserFontHealthError(
                f"BROWSER_CJK_FONT_METRICS_INVALID: {direction} Chinese glyph advances are invalid. "
                "Use the validated Runner with Noto CJK fonts; do not change reference images or page CSS."
            )


def check_browser_font_health(browser) -> dict:
    """Probe a separate blank context: no business navigation, login or model call."""
    context = browser.new_context(locale="zh-CN", viewport={"width": 600, "height": 300}, device_scale_factor=1)
    try:
        page = context.new_page()
        results = []
        for language in ("zh-CN", "en", ""):
            for stack in _FONT_STACKS:
                page.set_content(_HTML.replace("LANGUAGE", language).replace("FONTSTACK", stack),
                                 wait_until="load", timeout=5000)
                metrics = page.evaluate(_MEASURE)
                validate_font_metrics(metrics)
                results.append({"language": language, "font_stack": stack, "metrics": metrics})
        return {"checks": results}
    finally:
        context.close()


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            print(json.dumps(check_browser_font_health(browser)))
        finally:
            browser.close()
