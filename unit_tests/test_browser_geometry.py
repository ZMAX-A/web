import pytest

from utils.browser_geometry import initial_case_geometry


@pytest.mark.parametrize("separator", ["x", "X", "×"])
def test_leading_viewport_configures_screen_before_navigation(separator):
    options = initial_case_geometry({
        "操作类型": "set_viewport,click,vision_compare_step",
        "元素定位器": f" 2561 {separator} 1397 ,text=影像,body",
    })
    assert options == {
        "viewport": {"width": 2561, "height": 1397},
        "screen": {"width": 2561, "height": 1397},
        "device_scale_factor": 1,
    }


@pytest.mark.parametrize("case", [None, {}, {"操作类型": "click,set_viewport", "元素定位器": "body,800x600"}])
def test_does_not_move_later_responsive_resize_before_navigation(case):
    assert initial_case_geometry(case) == {}


@pytest.mark.parametrize("size", ["", "invalid", "319x900", "1440x239", "10001x900"])
def test_invalid_startup_geometry_fails_before_browser_creation(size):
    with pytest.raises(ValueError):
        initial_case_geometry({"操作类型": "set_viewport", "元素定位器": size})
