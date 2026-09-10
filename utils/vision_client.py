"""视觉模型客户端 —— 通过 OpenAI 兼容接口调用多模态模型（Qwen-VL 等）

用于影像阅览页等 canvas 绘制内容的 UI 验证：
  1. 截图 → base64
  2. 调用模型（图片 + prompt）→ 模型返回理解结果
  3. 结构化输出（JSON）用于断言

配置（.env）：
    VISION_API_KEY=sk-xxx
    VISION_BASE_URL=http://xxx/api        # OpenAI 兼容网关
    VISION_MODEL=qwen-vl-max              # 模型名
    VISION_TIMEOUT=60                     # 单次调用超时（秒），可选
    VISION_THINKING_BUDGET=16384          # 思考 token 预算（拉满），设为 0 关闭思考
    VISION_ENABLE_THINKING=               # 留空沿用本地 vLLM；百炼官网填 true/false
    VISION_SYSTEM_PROMPT=                 # 自定义 system prompt（留空用内置纪律 prompt）
"""
import base64
import logging
import os
from urllib.parse import urlparse

import requests

logger = logging.getLogger("vision_client")


class VisionError(RuntimeError):
    """视觉模型调用失败时抛出的明确异常，防止测试静默继续。"""


def _discipline_prompt() -> str:
    """纪律 system prompt：约束模型只报告可见内容、缺失答"不存在"，禁止脑补。

    2026-08-28 A/B 实验验证（构造登录页 mock，15px 小字 ground truth）：
      - 定向逐字提问模式 4/4 命中小字（账号、toast 文案、按钮、标题），1.9s
      - 幻觉诱导（问不存在的元素）明确回答"图中不存在"，不编造
    """
    env = os.getenv("VISION_SYSTEM_PROMPT", "").strip()
    if env:
        return env
    return (
        "你只做截图内容识别。严格规则："
        "只报告图中真实可见的文字与元素；"
        "除非用户问题明确要求，否则不要转录姓名、手机号、账号、编号等个人信息；"
        "看不清、不存在或超出可见范围的内容，必须回答\"看不清\"或\"不存在\"，"
        "禁止推测、禁止补全、禁止用常识脑补缺失部分。"
    )


def _config() -> dict:
    api_key = os.getenv("VISION_API_KEY", "").strip()
    base_url = os.getenv("VISION_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("VISION_MODEL", "").strip()
    timeout = float(os.getenv("VISION_TIMEOUT", "60").strip() or 60)
    try:
        thinking_budget = int(os.getenv("VISION_THINKING_BUDGET", "16384").strip() or 0)
    except ValueError:
        thinking_budget = 16384
    enable_thinking_raw = os.getenv("VISION_ENABLE_THINKING", "").strip().lower()
    if enable_thinking_raw in {"", "auto"}:
        enable_thinking = None
    elif enable_thinking_raw in {"1", "true", "yes", "on"}:
        enable_thinking = True
    elif enable_thinking_raw in {"0", "false", "no", "off"}:
        enable_thinking = False
    else:
        raise VisionError(
            "VISION_ENABLE_THINKING 仅支持 true/false（或留空沿用本地 vLLM 配置）"
        )
    missing = [name for name, val in
               (("VISION_API_KEY", api_key), ("VISION_BASE_URL", base_url), ("VISION_MODEL", model))
               if not val]
    if missing:
        raise VisionError("视觉模型配置缺失: " + ", ".join(missing))
    parsed = urlparse(base_url)
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        logger.warning(
            "VISION_BASE_URL 使用非本机 HTTP，API 密钥与截图不会被传输层加密；"
            "真实客户影像应改用 HTTPS/VPN 内网网关"
        )
    return {
        "api_key": api_key, "base_url": base_url, "model": model,
        "timeout": timeout, "thinking_budget": thinking_budget,
        "enable_thinking": enable_thinking,
    }


def analyze_image(
    image_bytes: bytes,
    prompt: str,
    system_prompt: str = "",
    discipline: bool = True,
    json_mode: bool = False,
) -> str:
    """发送图片 + prompt 到视觉模型，返回模型文本回答。

    :param image_bytes: 图片原始字节（png/jpg）
    :param prompt: 用户问题（验证内容描述）
    :param system_prompt: 系统提示（行为约束）；为空时用内置纪律 prompt
    :param discipline: 是否启用内置纪律 prompt（只报可见内容、缺失答"不存在"）。
                       调用方自带 system_prompt 时此参数无效果
    :param json_mode: 是否要求 JSON 结构化输出
    """
    # 避免 pytest showlocals 在失败回溯中展开截图二进制。
    __tracebackhide__ = True
    return analyze_images(
        [image_bytes],
        prompt,
        image_labels=["当前截图"],
        system_prompt=system_prompt,
        discipline=discipline,
        json_mode=json_mode,
    )


def analyze_images(
    images: list[bytes] | tuple[bytes, ...],
    prompt: str,
    image_labels: list[str] | tuple[str, ...] | None = None,
    system_prompt: str = "",
    discipline: bool = True,
    json_mode: bool = False,
) -> str:
    """一次请求发送一张或多张图片，按给定顺序返回模型文本回答。

    双图基线回归固定使用“标准截图、当前截图”的顺序。标签作为独立文本块放在
    对应图片之前，避免模型混淆两张图片。调用方仍需对返回 JSON 做严格校验。
    """
    # pytest 开启 showlocals 时会打印本函数的局部变量；其中包含认证请求头。
    # 隐藏该栈帧，并在网络异常时切断底层异常链，避免失败日志泄露密钥。
    __tracebackhide__ = True

    if not isinstance(images, (list, tuple)) or not images:
        raise VisionError("视觉模型请求至少需要一张图片")
    normalized_images: list[bytes] = []
    for index, image_bytes in enumerate(images, start=1):
        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            raise VisionError(f"第 {index} 张图片为空或不是二进制数据")
        normalized_images.append(bytes(image_bytes))

    if image_labels is None:
        labels = [f"图片{index}" for index in range(1, len(normalized_images) + 1)]
    else:
        labels = [str(label).strip() for label in image_labels]
        if len(labels) != len(normalized_images) or any(not label for label in labels):
            raise VisionError("图片标签必须与图片数量一致且不能为空")

    cfg = _config()

    messages = []
    if system_prompt or discipline:
        messages.append({"role": "system", "content": system_prompt or _discipline_prompt()})
    request_prompt = prompt
    if json_mode:
        # 百炼 JSON mode 会检查 messages 中是否显式包含英文小写 json。
        request_prompt += "\nOutput must be a valid json object."
    content = [{"type": "text", "text": request_prompt}]
    for label, image_bytes in zip(labels, normalized_images):
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        content.extend([
            {"type": "text", "text": f"【{label}】"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ])
    messages.append({"role": "user", "content": content})

    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.1,  # 视觉校验要确定性，尽量低温
        "max_tokens": 16384,  # 思考 token 计入 completion，需给足上限
    }
    # 百炼 OpenAI 兼容接口要求 enable_thinking/thinking_budget 位于请求体顶层；
    # 未显式配置时保留原有本地 vLLM chat_template_kwargs 行为。
    if cfg["enable_thinking"] is not None:
        payload["enable_thinking"] = cfg["enable_thinking"]
        if cfg["enable_thinking"] and cfg["thinking_budget"] > 0:
            payload["thinking_budget"] = cfg["thinking_budget"]
    elif cfg["thinking_budget"] > 0:
        payload["chat_template_kwargs"] = {
            "enable_thinking": True,
            "thinking_budget": cfg["thinking_budget"],
        }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    url = cfg["base_url"] + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }

    total_bytes = sum(len(image_bytes) for image_bytes in normalized_images)
    logger.info(
        "调用视觉模型 %s（%d 张图片，共 %d 字节）...",
        cfg["model"],
        len(normalized_images),
        total_bytes,
    )
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=cfg["timeout"])
    except requests.RequestException as exc:
        raise VisionError(f"视觉模型请求失败: {exc}") from None

    if resp.status_code != 200:
        raise VisionError(
            f"视觉模型返回 {resp.status_code}: {resp.text[:300]}"
        )
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise VisionError(f"视觉模型响应解析失败: {exc} | {resp.text[:300]}") from exc
