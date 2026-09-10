"""面向 Playwright 视觉断言的轻量 Harness。

职责边界：
1. 使用「断言定位器」截取最小必要区域，避免整页噪声与无关客户信息；
2. 为不同断言生成固定、版本化的 Prompt；
3. 严格校验模型 JSON，只接受可见事实，不接受模型直接给出的 pass/fail；
4. 由本地确定性代码计算断言结果；
5. 使用截图哈希缓存重复请求，并将脱敏元数据附加到 Allure。

这个模块不会改变视觉模型权重。它提升的是测试判定的一致性、可追踪性和
失败安全性（模型不确定、响应格式错误或服务不可用时绝不静默通过）。
"""
from __future__ import annotations

import hashlib
import base64
import json
import logging
import os
import re
import struct
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import allure

from utils.vision_client import analyze_image

logger = logging.getLogger("vision_harness")

PROMPT_VERSION = "yanjia-vision-harness-v4"
BASELINE_METADATA_VERSION = 1
ITEM_STATUSES = frozenset({"visible", "not_visible", "uncertain"})
PAGE_STATES = frozenset({"image_viewer", "login_page", "customer_list", "loading", "unknown"})
CANVAS_STATES = frozenset({"loaded", "blank", "loading", "error", "unknown"})
REFERENCE_MATCH_STATES = frozenset({"match", "mismatch", "uncertain"})
REFERENCE_USABILITY_STATES = frozenset({"usable", "unusable", "uncertain"})
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SAFE_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SAFE_STEP_FILE = re.compile(r"step_[0-9]{3}_[A-Za-z0-9_-]+[.]png")

_PAGE_ALIASES = {
    "影像阅览页": "image_viewer",
    "阅览页": "image_viewer",
    "image_viewer": "image_viewer",
    "登录页": "login_page",
    "login_page": "login_page",
    "顾客列表页": "customer_list",
    "顾客列表": "customer_list",
    "customer_list": "customer_list",
    "加载页": "loading",
    "加载中": "loading",
    "loading": "loading",
    "未知": "unknown",
    "unknown": "unknown",
}


class VisionHarnessError(RuntimeError):
    """视觉服务、截图或响应契约错误；区别于产品视觉不匹配。"""


class VisionSchemaError(VisionHarnessError):
    """模型返回内容不满足 Harness 的严格 JSON 契约。"""


class VisionAssertionMismatch(AssertionError):
    """模型观察结果有效，但与用例期望不一致。"""


@dataclass(frozen=True)
class VisionInspection:
    """一次视觉观察的可审计结果。"""

    task: str
    image_sha256: str
    reference_sha256: str | None
    model: str
    cached: bool
    latency_ms: int
    observation: dict[str, Any]


@dataclass(frozen=True)
class VisionBaseline:
    """已通过文件、哈希、尺寸、截图范围和批准状态校验的标准图。"""

    path: Path
    image_bytes: bytes
    image_sha256: str
    width: int
    height: int
    metadata: dict[str, Any]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "否"}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (AttributeError, TypeError, ValueError):
        return default
    return value if value > 0 else default


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else text


def _parse_json_object(raw: object) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise VisionSchemaError("视觉模型返回为空或不是文本")
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        raise VisionSchemaError(f"视觉模型未返回合法 JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise VisionSchemaError("视觉模型 JSON 顶层必须是对象")
    return data


def _require_bool(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if type(value) is not bool:  # bool 是 int 子类，必须用精确类型判断。
        raise VisionSchemaError(f"字段 {key} 必须是 boolean")
    return value


def _require_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise VisionSchemaError(f"字段 {key} 必须是非空字符串数组（允许空数组）")
    return [item.strip() for item in value]


def _expected_items(text: str) -> list[str]:
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", str(text or ""))
    values = quoted or re.split(r"[、，,|]", str(text or ""))
    result: list[str] = []
    for item in values:
        cleaned = item.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    if not result:
        raise VisionAssertionMismatch("vision_contains 断言缺少期望项目")
    return result


def _expected_count(text: str) -> tuple[int, bool]:
    numbers = re.findall(r"\d+", str(text or ""))
    if not numbers:
        raise VisionAssertionMismatch("vision_count 断言缺少期望数量")
    return int(numbers[0]), "至少" in str(text) or ">=" in str(text)


def _expected_page_state(text: str) -> str:
    normalized = str(text or "").strip().strip("'\"")
    for label, state in _PAGE_ALIASES.items():
        if label in normalized:
            return state
    allowed = "、".join(sorted(_PAGE_ALIASES))
    raise VisionAssertionMismatch(f"vision_page_state 无法解析期望页面；支持: {allowed}")


class VisionHarness:
    """Playwright 页面到严格视觉断言的轻量执行器。"""

    _cache: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    def __init__(
        self,
        page: Any,
        timeout_ms: int = 5000,
        analyze_fn: Callable[..., str] | None = None,
        compare_analyze_fn: Callable[..., str] | None = None,
        compose_fn: Callable[[bytes, bytes], bytes] | None = None,
        crop_fn: Callable[[bytes, bytes, list[int]], tuple[bytes, bytes]] | None = None,
        case_id: str = "",
    ):
        self.page = page
        self.timeout_ms = max(int(timeout_ms), 1)
        self._analyze_fn = analyze_fn or analyze_image
        self._compare_analyze_fn = compare_analyze_fn or analyze_image
        self._compose_fn = compose_fn
        self._crop_fn = crop_fn
        self.case_id = str(case_id or "").strip()

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    @classmethod
    def load_baseline(cls, case_id: str, locator: str) -> VisionBaseline:
        """加载并验证用例标准图，供回归断言与独立评测共同使用。"""
        normalized_case_id = str(case_id or "").strip()
        normalized_locator = str(locator or "").strip()
        if not normalized_case_id:
            raise VisionHarnessError("缺少用例ID，无法加载视觉标准图")
        if not normalized_locator:
            raise VisionHarnessError("缺少截图区域，无法校验视觉标准图")
        path = cls._baseline_path(normalized_case_id)
        image_bytes = cls._read_baseline(path)
        metadata = cls._read_baseline_metadata(
            path,
            image_bytes,
            normalized_case_id,
            normalized_locator,
        )
        width, height = struct.unpack(">II", image_bytes[16:24])
        return VisionBaseline(
            path=path,
            image_bytes=image_bytes,
            image_sha256=hashlib.sha256(image_bytes).hexdigest(),
            width=width,
            height=height,
            metadata=metadata,
        )

    @classmethod
    def load_step_baseline(cls, reference_key: str, locator: str) -> VisionBaseline:
        """加载步骤标准图；reference_key 格式为 <基线用例ID>/<步骤图片名>。"""
        normalized_key = str(reference_key or "").strip().replace("\\", "/")
        normalized_locator = str(locator or "").strip()
        parts = normalized_key.split("/")
        if (
            len(parts) != 2
            or not _SAFE_CASE_ID.fullmatch(parts[0])
            or not _SAFE_STEP_FILE.fullmatch(parts[1])
        ):
            raise VisionHarnessError(
                "步骤标准图引用格式错误；必须为 <基线用例ID>/step_序号_名称.png"
            )
        if not normalized_locator:
            raise VisionHarnessError("步骤视觉比较缺少截图区域")

        baseline_case_id, filename = parts
        root = cls._baseline_root()
        steps_root = (root / baseline_case_id / "steps").resolve()
        path = (steps_root / filename).resolve()
        if path.parent != steps_root:
            raise VisionHarnessError("步骤视觉基线路径越界")
        image_bytes = cls._read_baseline(path)
        metadata = cls._read_step_baseline_metadata(
            path,
            image_bytes,
            baseline_case_id,
            normalized_locator,
        )
        width, height = struct.unpack(">II", image_bytes[16:24])
        return VisionBaseline(
            path=path,
            image_bytes=image_bytes,
            image_sha256=hashlib.sha256(image_bytes).hexdigest(),
            width=width,
            height=height,
            metadata=metadata,
        )

    def assert_contains(self, expected_text: str, locator: str) -> bool:
        expected = _expected_items(expected_text)
        prompt = self._items_prompt(expected)
        inspection = self._inspect("items", locator, prompt, lambda data: self._validate_items(data, expected))
        checks = inspection.observation["checks"]
        failed = {item: checks[item] for item in expected if checks[item] != "visible"}
        if failed:
            raise VisionAssertionMismatch(
                "视觉区域未清晰显示全部期望项目: "
                + ", ".join(f"{item}={status}" for item, status in failed.items())
            )
        logger.info("  ✅ 视觉项目均可见: %s", expected)
        return True

    def assert_count(self, expected_text: str, locator: str) -> bool:
        expected, at_least = _expected_count(expected_text)
        prompt = self._count_prompt()
        inspection = self._inspect("count", locator, prompt, self._validate_count)
        actual = inspection.observation["count"]
        uncertain = inspection.observation["uncertain"]
        if uncertain:
            raise VisionAssertionMismatch("视觉模型对项目数量不确定，按严格规则判失败")
        matched = actual >= expected if at_least else actual == expected
        if not matched:
            relation = "至少" if at_least else "等于"
            raise VisionAssertionMismatch(f"视觉项目数量不匹配：期望{relation}{expected}，实际{actual}")
        logger.info("  ✅ 视觉项目数量符合预期: %s", actual)
        return True

    def assert_page_state(self, expected_text: str, locator: str) -> bool:
        expected = _expected_page_state(expected_text)
        inspection = self._inspect("page_state", locator, self._page_state_prompt(), self._validate_page_state)
        data = inspection.observation
        if data["uncertain"]:
            raise VisionAssertionMismatch("视觉模型无法确定当前页面类型")
        if data["page_state"] != expected:
            raise VisionAssertionMismatch(
                f"页面视觉状态不匹配：期望 {expected}，实际 {data['page_state']}"
            )
        logger.info("  ✅ 页面视觉状态符合预期: %s", expected)
        return True

    def assert_canvas_ready(self, _expected_text: str, locator: str) -> bool:
        inspection = self._inspect("canvas", locator, self._canvas_prompt(), self._validate_canvas)
        data = inspection.observation
        if data["uncertain"]:
            raise VisionAssertionMismatch("视觉模型无法确定 Canvas 是否完成渲染")
        if data["canvas_state"] != "loaded":
            errors = "、".join(data["error_texts"]) or "无"
            raise VisionAssertionMismatch(
                f"Canvas 未完成有效渲染：状态={data['canvas_state']}，错误文字={errors}"
            )
        logger.info("  ✅ Canvas 已完成有效渲染")
        return True

    def assert_reference_compare(self, expected_text: str, locator: str) -> bool:
        """自动加载当前用例的标准截图，与运行时截图进行双图语义比较。"""
        inspection = self.inspect_reference_compare(expected_text, locator)
        failures = self.reference_compare_failures(inspection.observation)
        if failures:
            raise VisionAssertionMismatch("视觉基线比较不通过：" + "；".join(failures))
        logger.info("  ✅ 视觉基线比较通过: %s", self.case_id)
        return True

    def assert_step_reference(
        self,
        reference_key: str,
        locator: str,
        expected_text: str = "",
    ) -> bool:
        """比较一个操作步骤的红框区域；任何不确定或关键差异都失败。"""
        inspection = self.inspect_step_reference(reference_key, locator, expected_text)
        failures = self.reference_compare_failures(inspection.observation)
        if failures:
            raise VisionAssertionMismatch(
                f"步骤标准图比较不通过[{reference_key}]：" + "；".join(failures)
            )
        logger.info("  ✅ 步骤视觉基线比较通过: %s", reference_key)
        return True

    def inspect_step_reference(
        self,
        reference_key: str,
        locator: str,
        expected_text: str = "",
    ) -> VisionInspection:
        """加载步骤标准图，按元数据红框裁剪标准/当前截图后执行语义比较。"""
        locator = str(locator or "").strip()
        if not locator:
            raise VisionHarnessError("步骤视觉比较必须填写截图定位器")
        baseline = self.load_step_baseline(reference_key, locator)
        current_full = self._capture(locator)
        reference_crop, current_crop = self._crop_step_pair(
            baseline.image_bytes,
            current_full,
            baseline.metadata["crop_box"],
            baseline.metadata.get("current_crop_box"),
        )
        current_capture = baseline.metadata.get("current_capture")
        if current_capture is not None:
            current_crop = self._capture_step_current(current_capture)
        comparison_bytes = (
            self._compose_fn(reference_crop, current_crop)
            if self._compose_fn is not None
            else self._compose_reference_pair(reference_crop, current_crop)
        )
        comparison_bytes = self._validate_image_bytes(comparison_bytes, "步骤自动合成对照图")
        focus = str(expected_text or "").strip() or (
            f"当前操作状态必须与步骤标准图 {baseline.path.name} 的红框内界面一致，"
            "布局和关键元素完整、页面可用且无异常提示"
        )
        prompt = self._reference_compare_prompt(
            focus,
            baseline.metadata.get("allowed_dynamic_differences", []),
        )
        return self._inspect_reference(
            reference_crop,
            current_crop,
            comparison_bytes,
            prompt,
            self._validate_reference_compare,
        )

    def _capture_step_current(self, config: dict[str, Any]) -> bytes:
        """按步骤元数据定位当前 DOM 组件，避免标准图绝对坐标错套到动态布局。"""
        locator = config["locator"]
        ancestor_levels = config["ancestor_levels"]
        required_texts = config["required_texts"]
        try:
            target = self.page.locator(locator).first
            target.wait_for(state="visible", timeout=self.timeout_ms)
            for _ in range(ancestor_levels):
                target = target.locator("xpath=..")
            target.wait_for(state="visible", timeout=self.timeout_ms)
            visible_text = re.sub(
                r"\s+",
                " ",
                target.inner_text(timeout=self.timeout_ms),
            ).strip()
            missing = [text for text in required_texts if text not in visible_text]
            if missing:
                raise VisionHarnessError(
                    "STEP_CURRENT_CAPTURE_TEXT_MISSING: 动态截图组件缺少必需文字："
                    + "、".join(missing)
                )
            image_bytes = target.screenshot(
                type="png",
                animations="disabled",
                caret="hide",
                timeout=self.timeout_ms,
            )
        except VisionHarnessError:
            raise
        except Exception as exc:
            raise VisionHarnessError(
                f"步骤当前组件动态截图失败: {locator}, ancestor_levels={ancestor_levels}: {exc}"
            ) from exc
        return self._validate_image_bytes(image_bytes, "步骤当前组件截图")

    def inspect_reference_compare(self, expected_text: str, locator: str) -> VisionInspection:
        """执行标准图比较并返回结构化观察；不直接给出通过或失败。"""
        if not self.case_id:
            raise VisionHarnessError("vision_compare_reference 缺少当前用例ID，无法查找标准截图")
        locator = str(locator or "").strip()
        if not locator:
            raise VisionHarnessError("视觉断言必须填写独立的「断言定位器」，拒绝发送整页截图")
        baseline = self.load_baseline(self.case_id, locator)
        reference_bytes = baseline.image_bytes
        metadata = baseline.metadata
        current_bytes = self._capture(locator)
        comparison_bytes = (
            self._compose_fn(reference_bytes, current_bytes)
            if self._compose_fn is not None
            else self._compose_reference_pair(reference_bytes, current_bytes)
        )
        comparison_bytes = self._validate_image_bytes(comparison_bytes, "自动合成对照图")
        focus = str(expected_text or "").strip() or "页面布局正常、关键控件完整、页面可用且无异常提示"
        prompt = self._reference_compare_prompt(
            focus,
            metadata.get("allowed_dynamic_differences", []),
        )
        return self._inspect_reference(
            reference_bytes,
            current_bytes,
            comparison_bytes,
            prompt,
            self._validate_reference_compare,
        )

    @staticmethod
    def reference_compare_failures(data: dict[str, Any]) -> list[str]:
        """把已验证的结构化观察转换为确定性的失败原因列表。"""
        failures: list[str] = []
        if data["layout_status"] != "match":
            failures.append(f"布局={data['layout_status']}")
        if data["critical_elements_status"] != "match":
            failures.append(f"关键元素={data['critical_elements_status']}")
        if data["page_usability"] != "usable":
            failures.append(f"页面可用性={data['page_usability']}")
        if data["unexpected_error_visible"]:
            failures.append("出现标准图中没有的错误状态")
        if data["critical_differences"]:
            failures.append("关键差异=" + "；".join(data["critical_differences"]))
        if data["uncertain_reason"]:
            failures.append("不确定=" + data["uncertain_reason"])
        return failures

    def _inspect(
        self,
        task: str,
        locator: str,
        prompt: str,
        validator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> VisionInspection:
        if not str(locator or "").strip():
            raise VisionHarnessError("视觉断言必须填写独立的「断言定位器」，拒绝发送整页截图")

        image_bytes = self._capture(locator.strip())
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        model = os.getenv("VISION_MODEL", "").strip() or "unknown"
        cache_key = hashlib.sha256(
            "\0".join((PROMPT_VERSION, model, task, prompt, image_hash)).encode("utf-8")
        ).hexdigest()

        cached = False
        latency_ms = 0
        observation: dict[str, Any]
        if _env_flag("VISION_CACHE_ENABLED", True) and cache_key in self._cache:
            observation = self._cache[cache_key]
            self._cache.move_to_end(cache_key)
            cached = True
        else:
            started = time.perf_counter()
            raw = self._analyze_fn(image_bytes, prompt, discipline=True, json_mode=True)
            latency_ms = round((time.perf_counter() - started) * 1000)
            observation = validator(_parse_json_object(raw))
            if _env_flag("VISION_CACHE_ENABLED", True):
                self._cache[cache_key] = observation
                self._cache.move_to_end(cache_key)
                max_items = _positive_int_env("VISION_CACHE_MAX_ITEMS", 256)
                while len(self._cache) > max_items:
                    self._cache.popitem(last=False)

        inspection = VisionInspection(
            task=task,
            image_sha256=image_hash,
            reference_sha256=None,
            model=model,
            cached=cached,
            latency_ms=latency_ms,
            observation=observation,
        )
        self._attach_evidence(inspection, image_bytes)
        return inspection

    def _inspect_reference(
        self,
        reference_bytes: bytes,
        current_bytes: bytes,
        comparison_bytes: bytes,
        prompt: str,
        validator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> VisionInspection:
        # pytest 失败回溯不展开截图二进制和拼接图，避免客户影像进入日志。
        __tracebackhide__ = True
        reference_hash = hashlib.sha256(reference_bytes).hexdigest()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        model = os.getenv("VISION_MODEL", "").strip() or "unknown"
        cache_key = hashlib.sha256(
            "\0".join(
                (PROMPT_VERSION, model, "reference_compare", prompt, reference_hash, current_hash)
            ).encode("utf-8")
        ).hexdigest()

        cached = False
        latency_ms = 0
        if _env_flag("VISION_CACHE_ENABLED", True) and cache_key in self._cache:
            observation = self._cache[cache_key]
            self._cache.move_to_end(cache_key)
            cached = True
        else:
            started = time.perf_counter()
            raw = self._compare_analyze_fn(
                comparison_bytes, prompt, discipline=True, json_mode=True
            )
            latency_ms = round((time.perf_counter() - started) * 1000)
            observation = validator(_parse_json_object(raw))
            if _env_flag("VISION_CACHE_ENABLED", True):
                self._cache[cache_key] = observation
                self._cache.move_to_end(cache_key)
                max_items = _positive_int_env("VISION_CACHE_MAX_ITEMS", 256)
                while len(self._cache) > max_items:
                    self._cache.popitem(last=False)

        inspection = VisionInspection(
            task="reference_compare",
            image_sha256=current_hash,
            reference_sha256=reference_hash,
            model=model,
            cached=cached,
            latency_ms=latency_ms,
            observation=observation,
        )
        self._attach_evidence(
            inspection,
            current_bytes,
            reference_bytes,
            comparison_bytes,
        )
        return inspection

    def _compose_reference_pair(self, reference_bytes: bytes, current_bytes: bytes) -> bytes:
        """在当前浏览器内存中把两图纵向拼接，兼容单图输入的视觉网关。"""
        reference_url = "data:image/png;base64," + base64.b64encode(reference_bytes).decode("ascii")
        current_url = "data:image/png;base64," + base64.b64encode(current_bytes).decode("ascii")
        script = """
        async ({ referenceUrl, currentUrl }) => {
          const load = (src) => new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = () => reject(new Error("comparison image decode failed"));
            image.src = src;
          });
          const [reference, current] = await Promise.all([
            load(referenceUrl), load(currentUrl),
          ]);
          const panelWidth = 1600;
          const panelHeight = 900;
          const headerHeight = 48;
          const gap = 20;
          const padding = 20;
          const canvas = document.createElement("canvas");
          canvas.width = panelWidth + padding * 2;
          canvas.height = (headerHeight + panelHeight) * 2 + gap + padding * 2;
          const context = canvas.getContext("2d");
          context.fillStyle = "#111827";
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.font = "bold 26px sans-serif";
          context.textBaseline = "middle";

          const drawPanel = (image, label, top) => {
            context.fillStyle = "#E5E7EB";
            context.fillText(label, padding, top + headerHeight / 2);
            const scale = Math.min(panelWidth / image.width, panelHeight / image.height);
            const width = Math.round(image.width * scale);
            const height = Math.round(image.height * scale);
            const left = padding + Math.round((panelWidth - width) / 2);
            const imageTop = top + headerHeight + Math.round((panelHeight - height) / 2);
            context.drawImage(image, left, imageTop, width, height);
          };

          drawPanel(reference, "REFERENCE / STANDARD", padding);
          drawPanel(current, "CURRENT / ACTUAL", padding + headerHeight + panelHeight + gap);
          return canvas.toDataURL("image/png");
        }
        """
        try:
            data_url = self.page.evaluate(
                script,
                {"referenceUrl": reference_url, "currentUrl": current_url},
            )
        except Exception as exc:
            raise VisionHarnessError(f"标准图与当前图自动合成失败: {exc}") from exc
        prefix = "data:image/png;base64,"
        if not isinstance(data_url, str) or not data_url.startswith(prefix):
            raise VisionHarnessError("浏览器未返回合法的 PNG 对照图")
        try:
            return base64.b64decode(data_url[len(prefix):], validate=True)
        except (ValueError, TypeError) as exc:
            raise VisionHarnessError("浏览器返回的 PNG 对照图无法解码") from exc

    def _crop_step_pair(
        self,
        reference_bytes: bytes,
        current_bytes: bytes,
        crop_box: list[int],
        current_crop_box: list[int] | None = None,
    ) -> tuple[bytes, bytes]:
        """按标准红框与显式实时框分别裁剪，兼容 Canvas 内渲染位置变化。"""
        reference_width, reference_height = struct.unpack(">II", reference_bytes[16:24])
        current_width, current_height = struct.unpack(">II", current_bytes[16:24])
        if (current_width, current_height) != (reference_width, reference_height):
            raise VisionHarnessError(
                "STEP_VIEWPORT_MISMATCH: 步骤标准图与当前截图尺寸不一致："
                f"标准={reference_width}x{reference_height}，当前={current_width}x{current_height}"
            )
        if self._crop_fn is not None:
            reference_crop, default_current_crop = self._crop_fn(
                reference_bytes,
                current_bytes,
                crop_box,
            )
            current_crop = default_current_crop
            if current_crop_box is not None and current_crop_box != crop_box:
                _, current_crop = self._crop_fn(
                    reference_bytes,
                    current_bytes,
                    current_crop_box,
                )
            return (
                self._validate_image_bytes(reference_crop, "步骤标准图红框区域"),
                self._validate_image_bytes(current_crop, "步骤当前图红框区域"),
            )

        reference_url = "data:image/png;base64," + base64.b64encode(reference_bytes).decode("ascii")
        current_url = "data:image/png;base64," + base64.b64encode(current_bytes).decode("ascii")
        script = """
        async ({ referenceUrl, currentUrl, referenceCropBox, currentCropBox }) => {
          const load = (src) => new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = () => reject(new Error('image decode failed'));
            image.src = src;
          });
          const [reference, current] = await Promise.all([
            load(referenceUrl), load(currentUrl)
          ]);
          const crop = (image, cropBox) => {
            const [x, y, width, height] = cropBox;
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const context = canvas.getContext('2d');
            context.drawImage(image, x, y, width, height, 0, 0, width, height);
            return canvas.toDataURL('image/png');
          };
          return {
            reference: crop(reference, referenceCropBox),
            current: crop(current, currentCropBox)
          };
        }
        """
        try:
            result = self.page.evaluate(
                script,
                {
                    "referenceUrl": reference_url,
                    "currentUrl": current_url,
                    "referenceCropBox": crop_box,
                    "currentCropBox": current_crop_box or crop_box,
                },
            )
        except Exception as exc:
            raise VisionHarnessError(f"步骤红框区域自动裁剪失败: {exc}") from exc
        if not isinstance(result, dict):
            raise VisionHarnessError("浏览器未返回步骤红框裁剪结果")
        return (
            self._decode_png_data_url(result.get("reference"), "步骤标准图红框区域"),
            self._decode_png_data_url(result.get("current"), "步骤当前图红框区域"),
        )

    @staticmethod
    def _decode_png_data_url(data_url: object, label: str) -> bytes:
        prefix = "data:image/png;base64,"
        if not isinstance(data_url, str) or not data_url.startswith(prefix):
            raise VisionHarnessError(f"浏览器未返回合法的 {label} PNG")
        try:
            image_bytes = base64.b64decode(data_url[len(prefix):], validate=True)
        except (ValueError, TypeError) as exc:
            raise VisionHarnessError(f"浏览器返回的 {label} PNG 无法解码") from exc
        return VisionHarness._validate_image_bytes(image_bytes, label)

    def _capture(self, locator: str) -> bytes:
        if not locator:
            raise VisionHarnessError("视觉断言必须填写独立的「断言定位器」，拒绝发送整页截图")
        try:
            target = self.page.locator(locator).first
            target.wait_for(state="visible", timeout=self.timeout_ms)
            image_bytes = target.screenshot(
                type="png",
                animations="disabled",
                caret="hide",
                timeout=self.timeout_ms,
            )
        except Exception as exc:
            raise VisionHarnessError(f"视觉断言区域截图失败: {locator}: {exc}") from exc

        return self._validate_image_bytes(image_bytes, "当前截图")

    @staticmethod
    def _validate_image_bytes(image_bytes: object, label: str) -> bytes:
        if not isinstance(image_bytes, (bytes, bytearray)):
            raise VisionHarnessError(f"{label}不是二进制图片")
        image_bytes = bytes(image_bytes)
        minimum = _positive_int_env("VISION_MIN_SCREENSHOT_BYTES", 512)
        if len(image_bytes) < minimum:
            raise VisionHarnessError(f"{label}过小（{len(image_bytes)} 字节），可能为空白或无效")
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n") or len(image_bytes) < 24:
            raise VisionHarnessError(f"{label}必须是 PNG 图片")
        width, height = struct.unpack(">II", image_bytes[16:24])
        if width < 24 or height < 24:
            raise VisionHarnessError(f"{label}尺寸过小: {width}x{height}")
        return image_bytes

    @staticmethod
    def _baseline_root() -> Path:
        raw = os.getenv("VISION_BASELINE_DIR", "test_assets/vision_baselines").strip()
        if not raw:
            raw = "test_assets/vision_baselines"
        root = Path(raw).expanduser()
        if not root.is_absolute():
            root = _PROJECT_ROOT / root
        return root.resolve()

    @classmethod
    def _baseline_path(cls, case_id: str) -> Path:
        if not _SAFE_CASE_ID.fullmatch(case_id):
            raise VisionHarnessError(f"用例ID包含不安全字符，无法解析视觉基线路径: {case_id!r}")
        root = cls._baseline_root()
        candidate = (root / case_id / "reference.png").resolve()
        if candidate.parent.parent != root:
            raise VisionHarnessError("视觉基线路径越界")
        return candidate

    @classmethod
    def _read_baseline(cls, path: Path) -> bytes:
        try:
            image_bytes = path.read_bytes()
        except FileNotFoundError as exc:
            try:
                shown = path.relative_to(_PROJECT_ROOT)
            except ValueError:
                shown = path
            raise VisionHarnessError(
                f"BASELINE_MISSING: 未找到视觉标准图 {shown}；标准图必须预先人工审核，运行时不会自动创建或覆盖"
            ) from exc
        except OSError as exc:
            raise VisionHarnessError(f"视觉标准图读取失败: {path}: {exc}") from exc
        return cls._validate_image_bytes(image_bytes, "视觉标准图")

    @classmethod
    def _read_baseline_metadata(
        cls,
        image_path: Path,
        image_bytes: bytes,
        case_id: str,
        locator: str,
    ) -> dict[str, Any]:
        metadata_path = image_path.with_name("reference.meta.json")
        if not metadata_path.exists():
            if _env_flag("VISION_REQUIRE_BASELINE_METADATA", True):
                raise VisionHarnessError(
                    f"BASELINE_METADATA_MISSING: 未找到 {metadata_path.name}；"
                    "标准图必须记录哈希、尺寸、截图区域和人工批准状态"
                )
            logger.warning("视觉标准图缺少元数据，已按兼容模式继续: %s", metadata_path)
            return {}
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise VisionHarnessError(f"视觉标准图元数据不是合法 JSON: {metadata_path}: {exc.msg}") from exc
        except OSError as exc:
            raise VisionHarnessError(f"视觉标准图元数据读取失败: {metadata_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise VisionHarnessError("视觉标准图元数据顶层必须是对象")

        required = {
            "schema_version", "case_id", "reference_file", "image_sha256",
            "image_width", "image_height", "capture_locator",
            "approved_for_visual_testing", "approval_source", "allowed_dynamic_differences",
        }
        if set(data) != required:
            missing = sorted(required - set(data))
            extra = sorted(set(data) - required)
            raise VisionHarnessError(f"视觉标准图元数据字段不一致：缺少={missing}，多余={extra}")
        if data["schema_version"] != BASELINE_METADATA_VERSION:
            raise VisionHarnessError(
                f"视觉标准图元数据版本不支持: {data['schema_version']!r}"
            )
        if data["case_id"] != case_id:
            raise VisionHarnessError(
                f"视觉标准图元数据用例ID不匹配：期望 {case_id}，实际 {data['case_id']!r}"
            )
        if data["reference_file"] != image_path.name:
            raise VisionHarnessError("视觉标准图元数据 reference_file 与实际文件名不一致")
        actual_hash = hashlib.sha256(image_bytes).hexdigest()
        if not isinstance(data["image_sha256"], str) or data["image_sha256"].lower() != actual_hash:
            raise VisionHarnessError("BASELINE_HASH_MISMATCH: 标准图内容已变化，必须重新人工审核并更新元数据")
        width, height = struct.unpack(">II", image_bytes[16:24])
        if data["image_width"] != width or data["image_height"] != height:
            raise VisionHarnessError(
                f"视觉标准图尺寸元数据不匹配：实际 {width}x{height}"
            )
        if data["capture_locator"] != locator:
            raise VisionHarnessError(
                f"视觉标准图截图区域不匹配：基线={data['capture_locator']!r}，当前={locator!r}"
            )
        if data["approved_for_visual_testing"] is not True:
            raise VisionHarnessError("视觉标准图尚未获准用于自动化测试")
        if not isinstance(data["approval_source"], str) or not data["approval_source"].strip():
            raise VisionHarnessError("视觉标准图元数据 approval_source 必须是非空字符串")
        differences = data["allowed_dynamic_differences"]
        if not isinstance(differences, list) or any(
            not isinstance(item, str) or not item.strip() for item in differences
        ):
            raise VisionHarnessError("allowed_dynamic_differences 必须是非空字符串数组（允许空数组）")
        normalized = dict(data)
        normalized["allowed_dynamic_differences"] = [item.strip() for item in differences]
        return normalized

    @classmethod
    def _read_step_baseline_metadata(
        cls,
        image_path: Path,
        image_bytes: bytes,
        baseline_case_id: str,
        locator: str,
    ) -> dict[str, Any]:
        metadata_path = image_path.parent / "steps.meta.json"
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise VisionHarnessError(
                "STEP_BASELINE_METADATA_MISSING: 步骤标准图必须记录哈希、尺寸、"
                "截图区域、红框坐标和人工批准状态"
            ) from exc
        except json.JSONDecodeError as exc:
            raise VisionHarnessError(
                f"步骤标准图元数据不是合法 JSON: {metadata_path}: {exc.msg}"
            ) from exc
        except OSError as exc:
            raise VisionHarnessError(f"步骤标准图元数据读取失败: {metadata_path}: {exc}") from exc
        required = {
            "schema_version",
            "case_id",
            "capture_locator",
            "approved_for_visual_testing",
            "approval_source",
            "allowed_dynamic_differences",
            "references",
        }
        if not isinstance(data, dict) or set(data) != required:
            actual = set(data) if isinstance(data, dict) else set()
            raise VisionHarnessError(
                "步骤标准图元数据字段不一致："
                f"缺少={sorted(required - actual)}，多余={sorted(actual - required)}"
            )
        if data["schema_version"] != BASELINE_METADATA_VERSION:
            raise VisionHarnessError(
                f"步骤标准图元数据版本不支持: {data['schema_version']!r}"
            )
        if data["case_id"] != baseline_case_id:
            raise VisionHarnessError(
                "步骤标准图元数据用例ID不匹配："
                f"期望 {baseline_case_id}，实际 {data['case_id']!r}"
            )
        if data["capture_locator"] != locator:
            raise VisionHarnessError(
                "步骤标准图截图区域不匹配："
                f"基线={data['capture_locator']!r}，当前={locator!r}"
            )
        if data["approved_for_visual_testing"] is not True:
            raise VisionHarnessError("步骤标准图尚未获准用于自动化测试")
        if not isinstance(data["approval_source"], str) or not data["approval_source"].strip():
            raise VisionHarnessError("步骤标准图元数据 approval_source 必须是非空字符串")
        differences = data["allowed_dynamic_differences"]
        if not isinstance(differences, list) or any(
            not isinstance(item, str) or not item.strip() for item in differences
        ):
            raise VisionHarnessError("步骤 allowed_dynamic_differences 必须是字符串数组")
        references = data["references"]
        if not isinstance(references, dict) or image_path.name not in references:
            raise VisionHarnessError(
                f"步骤标准图元数据未登记文件: {image_path.name}"
            )
        entry = references[image_path.name]
        entry_required = {"image_sha256", "image_width", "image_height", "crop_box"}
        entry_optional = {"current_capture", "current_crop_box"}
        if (
            not isinstance(entry, dict)
            or not entry_required.issubset(entry)
            or not set(entry).issubset(entry_required | entry_optional)
        ):
            actual = set(entry) if isinstance(entry, dict) else set()
            raise VisionHarnessError(
                f"步骤标准图 {image_path.name} 元数据字段不一致："
                f"缺少={sorted(entry_required - actual)}，"
                f"多余={sorted(actual - entry_required - entry_optional)}"
            )
        actual_hash = hashlib.sha256(image_bytes).hexdigest()
        if not isinstance(entry["image_sha256"], str) or entry["image_sha256"].lower() != actual_hash:
            raise VisionHarnessError(
                "STEP_BASELINE_HASH_MISMATCH: 步骤标准图内容已变化，"
                "必须重新人工审核并更新元数据"
            )
        width, height = struct.unpack(">II", image_bytes[16:24])
        if entry["image_width"] != width or entry["image_height"] != height:
            raise VisionHarnessError(
                f"步骤标准图尺寸元数据不匹配：实际 {width}x{height}"
            )
        crop_box = entry["crop_box"]
        if (
            not isinstance(crop_box, list)
            or len(crop_box) != 4
            or any(type(value) is not int for value in crop_box)
        ):
            raise VisionHarnessError("步骤标准图 crop_box 必须是四个整数 [x,y,width,height]")
        x, y, crop_width, crop_height = crop_box
        if (
            x < 0
            or y < 0
            or crop_width < 24
            or crop_height < 24
            or x + crop_width > width
            or y + crop_height > height
        ):
            raise VisionHarnessError(
                f"步骤标准图 crop_box 越界或过小: {crop_box}，图片={width}x{height}"
            )
        current_capture = entry.get("current_capture")
        current_crop_box = entry.get("current_crop_box")
        if current_capture is not None and current_crop_box is not None:
            raise VisionHarnessError(
                "步骤 current_capture 与 current_crop_box 不能同时配置"
            )
        if current_capture is None and current_crop_box is None:
            raise VisionHarnessError(
                "STEP_CURRENT_CAPTURE_STRATEGY_MISSING: 步骤必须显式配置 "
                "current_crop_box 或 current_capture，禁止默认复用标准图裁剪坐标"
            )
        if current_crop_box is not None:
            if (
                not isinstance(current_crop_box, list)
                or len(current_crop_box) != 4
                or any(type(value) is not int for value in current_crop_box)
            ):
                raise VisionHarnessError(
                    "步骤 current_crop_box 必须是四个整数 [x,y,width,height]"
                )
            current_x, current_y, current_width, current_height = current_crop_box
            if (
                current_x < 0
                or current_y < 0
                or current_width < 24
                or current_height < 24
                or current_x + current_width > width
                or current_y + current_height > height
            ):
                raise VisionHarnessError(
                    "步骤 current_crop_box 越界或过小: "
                    f"{current_crop_box}，图片={width}x{height}"
                )
        if current_capture is not None:
            required_capture_fields = {"locator", "ancestor_levels", "required_texts"}
            if not isinstance(current_capture, dict) or set(current_capture) != required_capture_fields:
                actual = set(current_capture) if isinstance(current_capture, dict) else set()
                raise VisionHarnessError(
                    "步骤 current_capture 字段不一致："
                    f"缺少={sorted(required_capture_fields - actual)}，"
                    f"多余={sorted(actual - required_capture_fields)}"
                )
            capture_locator = current_capture["locator"]
            ancestor_levels = current_capture["ancestor_levels"]
            required_texts = current_capture["required_texts"]
            if not isinstance(capture_locator, str) or not capture_locator.strip():
                raise VisionHarnessError("步骤 current_capture.locator 必须是非空字符串")
            if (
                type(ancestor_levels) is not int
                or ancestor_levels < 0
                or ancestor_levels > 8
            ):
                raise VisionHarnessError(
                    "步骤 current_capture.ancestor_levels 必须是 0 至 8 的整数"
                )
            if (
                not isinstance(required_texts, list)
                or not required_texts
                or any(not isinstance(text, str) or not text.strip() for text in required_texts)
            ):
                raise VisionHarnessError(
                    "步骤 current_capture.required_texts 必须是非空字符串数组"
                )
            current_capture = {
                "locator": capture_locator.strip(),
                "ancestor_levels": ancestor_levels,
                "required_texts": [text.strip() for text in required_texts],
            }
        return {
            "reference_file": image_path.name,
            "crop_box": crop_box,
            "current_crop_box": current_crop_box,
            "allowed_dynamic_differences": [item.strip() for item in differences],
            "current_capture": current_capture,
        }

    @staticmethod
    def _validate_items(data: dict[str, Any], expected: list[str]) -> dict[str, Any]:
        if data.get("task") != "items":
            raise VisionSchemaError("items 响应字段 task 必须等于 items")
        checks = data.get("checks")
        if not isinstance(checks, dict):
            raise VisionSchemaError("items 响应字段 checks 必须是对象")
        if set(checks) != set(expected):
            missing = sorted(set(expected) - set(checks))
            extra = sorted(set(checks) - set(expected))
            raise VisionSchemaError(f"checks 键与期望项目不一致：缺少={missing}，多余={extra}")
        for item, status in checks.items():
            if status not in ITEM_STATUSES:
                raise VisionSchemaError(
                    f"checks[{item}] 必须是 visible/not_visible/uncertain，实际={status!r}"
                )
        reason = data.get("uncertain_reason", "")
        if not isinstance(reason, str):
            raise VisionSchemaError("字段 uncertain_reason 必须是字符串")
        return {"task": "items", "checks": dict(checks), "uncertain_reason": reason.strip()}

    @staticmethod
    def _validate_count(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("task") != "count":
            raise VisionSchemaError("count 响应字段 task 必须等于 count")
        count = data.get("count")
        if type(count) is not int or count < 0:
            raise VisionSchemaError("字段 count 必须是非负整数")
        uncertain = _require_bool(data, "uncertain")
        evidence = _require_string_list(data, "evidence")
        if len(evidence) != count:
            raise VisionSchemaError(f"count={count} 与 evidence 项数={len(evidence)} 不一致")
        return {"task": "count", "count": count, "uncertain": uncertain, "evidence": evidence}

    @staticmethod
    def _validate_page_state(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("task") != "page_state":
            raise VisionSchemaError("page_state 响应字段 task 必须等于 page_state")
        state = data.get("page_state")
        if state not in PAGE_STATES:
            raise VisionSchemaError(f"page_state 非法: {state!r}")
        uncertain = _require_bool(data, "uncertain")
        evidence = _require_string_list(data, "evidence")
        return {"task": "page_state", "page_state": state, "uncertain": uncertain, "evidence": evidence}

    @staticmethod
    def _validate_canvas(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("task") != "canvas":
            raise VisionSchemaError("canvas 响应字段 task 必须等于 canvas")
        state = data.get("canvas_state")
        if state not in CANVAS_STATES:
            raise VisionSchemaError(f"canvas_state 非法: {state!r}")
        uncertain = _require_bool(data, "uncertain")
        errors = _require_string_list(data, "error_texts")
        return {"task": "canvas", "canvas_state": state, "uncertain": uncertain, "error_texts": errors}

    @staticmethod
    def _validate_reference_compare(data: dict[str, Any]) -> dict[str, Any]:
        required_core = {
            "task", "layout_status", "critical_elements_status", "page_usability",
            "unexpected_error_visible", "critical_differences", "evidence",
        }
        allowed = required_core | {"uncertain_reason"}
        if not required_core.issubset(data) or not set(data).issubset(allowed):
            missing = sorted(required_core - set(data))
            extra = sorted(set(data) - allowed)
            raise VisionSchemaError(f"reference_compare 字段不一致：缺少={missing}，多余={extra}")
        if data.get("task") != "reference_compare":
            raise VisionSchemaError("reference_compare 响应字段 task 必须等于 reference_compare")
        layout = data.get("layout_status")
        critical = data.get("critical_elements_status")
        usability = data.get("page_usability")
        if layout not in REFERENCE_MATCH_STATES:
            raise VisionSchemaError(f"layout_status 非法: {layout!r}")
        if critical not in REFERENCE_MATCH_STATES:
            raise VisionSchemaError(f"critical_elements_status 非法: {critical!r}")
        if usability not in REFERENCE_USABILITY_STATES:
            raise VisionSchemaError(f"page_usability 非法: {usability!r}")
        unexpected_error = _require_bool(data, "unexpected_error_visible")
        differences = _require_string_list(data, "critical_differences")
        evidence = _require_string_list(data, "evidence")
        reason = data.get("uncertain_reason", "")
        if not isinstance(reason, str):
            raise VisionSchemaError("字段 uncertain_reason 必须是字符串")
        if "uncertain" in {layout, critical, usability} and not reason.strip():
            raise VisionSchemaError("模型返回 uncertain 时必须填写 uncertain_reason")
        return {
            "task": "reference_compare",
            "layout_status": layout,
            "critical_elements_status": critical,
            "page_usability": usability,
            "unexpected_error_visible": unexpected_error,
            "critical_differences": differences,
            "evidence": evidence,
            "uncertain_reason": reason.strip(),
        }

    @staticmethod
    def _items_prompt(expected: list[str]) -> str:
        numbered = "\n".join(f"{index}. {item}" for index, item in enumerate(expected, start=1))
        # 示例使用最保守的 uncertain，防止示例本身诱导模型把未见项目标成 visible。
        example = {item: "uncertain" for item in expected}
        return (
            f"任务版本：{PROMPT_VERSION}\n"
            "你正在检查一张由自动化测试裁剪出的 UI 区域。逐项判断下列候选文字或元素是否在当前截图中清晰可见：\n"
            f"{numbered}\n"
            "只判断当前截图，不根据产品知识补全。完全可读才是 visible；明确没有是 not_visible；"
            "被截断、模糊或无法确定是 uncertain。\n"
            "checks 中每个值必须且只能从 visible、not_visible、uncertain 三个字符串中选择一个，"
            "不能返回布尔值，也不能原样复制多个候选值。"
            "只返回 JSON，不要 Markdown，不要新增或遗漏候选项。以下是保守格式示例，"
            "请根据截图把每项替换为真实状态：\n"
            + json.dumps(
                {"task": "items", "checks": example, "uncertain_reason": ""},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _count_prompt() -> str:
        return (
            f"任务版本：{PROMPT_VERSION}\n"
            "统计截图中重复排列的、当前真实可见的图谱缩略项/卡片项数量。忽略标题、按钮、分组名称和截断到无法确认的项。"
            "evidence 必须按从左到右、从上到下为每一项写一个简短可见特征，数量必须与 count 相同。"
            "无法确定总数时 uncertain=true。只返回 JSON："
            '{"task":"count","count":0,"uncertain":false,"evidence":[]}'
        )

    @staticmethod
    def _page_state_prompt() -> str:
        return (
            f"任务版本：{PROMPT_VERSION}\n"
            "判断截图属于哪一种页面状态，只能选择：image_viewer（影像阅览页）、login_page（登录页）、"
            "customer_list（顾客列表页）、loading（主要内容仍在加载）、unknown。"
            "evidence 只列实际可见的页面级特征；无法确定时 page_state=unknown 且 uncertain=true。只返回 JSON："
            '{"task":"page_state","page_state":"unknown","uncertain":true,"evidence":[]}'
        )

    @staticmethod
    def _canvas_prompt() -> str:
        return (
            f"任务版本：{PROMPT_VERSION}\n"
            "这是一块应显示皮肤影像或诊断图谱的 Canvas/画布区域。判断状态只能选择："
            "loaded（存在完整、非空的有效影像内容）、blank（空白/纯色/无有效内容）、"
            "loading（仍显示加载状态）、error（显示错误或加载失败）、unknown。"
            "error_texts 只填写实际可见错误文字；无法确定时 uncertain=true。只返回 JSON："
            '{"task":"canvas","canvas_state":"unknown","uncertain":true,"error_texts":[]}'
        )

    @staticmethod
    def _reference_compare_prompt(focus: str, allowed_dynamic_differences: list[str] | None = None) -> str:
        dynamic_rule = ""
        if allowed_dynamic_differences:
            dynamic_rule = (
                "本标准图已审核允许以下动态差异，不得仅因此判失败："
                + "、".join(allowed_dynamic_differences)
                + "。\n"
            )
        return (
            f"任务版本：{PROMPT_VERSION}\n"
            "你会收到一张自动生成的纵向对照图：上半部分标记 REFERENCE / STANDARD，是人工审核过的标准正常界面；"
            "下半部分标记 CURRENT / ACTUAL，是当前运行界面。"
            "请比较页面级结构和功能可用性，不要做逐像素比较，也不要因为时间、姓名、编号、具体影像内容、"
            "轻微抗锯齿或无功能影响的颜色差异而判为关键差异。不得转录个人信息。\n"
            f"本用例关注：{focus}\n"
            f"{dynamic_rule}"
            "layout_status 与 critical_elements_status 只能为 match、mismatch、uncertain；"
            "page_usability 只能为 usable、unusable、uncertain；unexpected_error_visible 只能是 boolean。"
            "critical_differences 只列会影响本用例目标或页面使用的真实差异；evidence 只列两图中可核对的界面特征。"
            "任何图片看不清、区域不对应或无法比较时使用 uncertain，并填写 uncertain_reason。"
            "判断确定时 uncertain_reason 也必须返回空字符串，不得省略。"
            "只返回以下字段且不要返回 pass/fail、Markdown 或额外字段："
            '{"task":"reference_compare","layout_status":"uncertain",'
            '"critical_elements_status":"uncertain","page_usability":"uncertain",'
            '"unexpected_error_visible":false,"critical_differences":[],"evidence":[],"uncertain_reason":""}'
        )

    @staticmethod
    def _attach_evidence(
        inspection: VisionInspection,
        image_bytes: bytes,
        reference_bytes: bytes | None = None,
        comparison_bytes: bytes | None = None,
    ) -> None:
        metadata = {
            "prompt_version": PROMPT_VERSION,
            "task": inspection.task,
            "model": inspection.model,
            "image_sha256": inspection.image_sha256,
            "reference_sha256": inspection.reference_sha256,
            "cached": inspection.cached,
            "latency_ms": inspection.latency_ms,
            "observation": inspection.observation,
        }
        try:
            allure.attach(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                name=f"视觉断言_{inspection.task}_结构化结果",
                attachment_type=allure.attachment_type.JSON,
            )
            if _env_flag("VISION_ATTACH_SCREENSHOT", False):
                if reference_bytes is not None:
                    allure.attach(
                        reference_bytes,
                        name=f"视觉断言_{inspection.task}_标准截图",
                        attachment_type=allure.attachment_type.PNG,
                    )
                if comparison_bytes is not None:
                    allure.attach(
                        comparison_bytes,
                        name=f"视觉断言_{inspection.task}_自动合成对照图",
                        attachment_type=allure.attachment_type.PNG,
                    )
                allure.attach(
                    image_bytes,
                    name=f"视觉断言_{inspection.task}_裁剪截图",
                    attachment_type=allure.attachment_type.PNG,
                )
        except Exception as exc:  # 报告附件不能改变测试结论。
            logger.warning("视觉断言 Allure 证据附加失败（不影响断言）: %s", exc)
