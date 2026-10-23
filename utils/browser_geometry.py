"""Resolve a case's initial browser geometry before its first navigation."""
from __future__ import annotations

import re


def initial_case_geometry(case: dict | None) -> dict:
    """Honor a leading set_viewport before applications read window.screen.

    Only a leading operation declares startup geometry. Later viewport changes
    remain ordinary test steps, so responsive-layout tests keep their semantics.
    """
    if not case:
        return {}
    operations = str(case.get("操作类型") or "").split(",")
    if operations[0].strip() != "set_viewport":
        return {}
    size = str(case.get("元素定位器") or "").split(",")[0].strip()
    match = re.fullmatch(r"(\d+)\s*[xX×]\s*(\d+)", size)
    if not match:
        raise ValueError(f"首次 set_viewport 尺寸必须为 宽x高，实际为 {size!r}")
    width, height = (int(value) for value in match.groups())
    if not (320 <= width <= 10000 and 240 <= height <= 10000):
        raise ValueError("首次 set_viewport 尺寸超出允许范围")
    return {
        "viewport": {"width": width, "height": height},
        "screen": {"width": width, "height": height},
        "device_scale_factor": 1,
    }
