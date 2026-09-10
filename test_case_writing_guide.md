# Excel 自动化用例编写规范

本项目会在打开浏览器之前校验整张用例表。操作类型、断言类型、等待时间或必要定位器写错时，测试会直接报出 Excel 行号，不再按通过处理。

## 基本规则

- 每行必须填写唯一的「用例ID」。
- 「操作类型」与「元素定位器」按英文逗号 `,` 一一对应；不需要定位器的操作也要保留空位。
- 只有需要数据的操作才从「输入数据」消费一项，多项数据用竖线 `|` 分隔。
- 「超时(秒)」必须是正数，用于当前用例的元素操作和断言等待。
- 每条用例必须有真实断言。未知或空断言会直接失败。
- 「执行分组」只允许 `A`、`B`、`SERIAL`、`AUTO`；留空等同 `AUTO`。
- 建议新增「断言定位器」列。普通断言未提供时，框架兼容使用「元素定位器」中的最后一个非空值；`vision_*` 视觉断言必须填写该列，框架只截取此区域，不允许隐式发送整页截图。

并行分组含义：

| 值 | 含义 |
|---|---|
| `A` | Worker A 使用账号 A 执行 |
| `B` | Worker B 使用账号 B 执行 |
| `SERIAL` | A/B 完成后再串行执行，适合共享数据或全局配置用例 |
| `AUTO` 或空 | 按模块默认映射；未知模块自动分配到当前较少的一组 |

测试数据支持 `${WORKER_ID}` 与 `${TIMESTAMP}` 占位符。例如
`自动化顾客-${WORKER_ID}-${TIMESTAMP}` 会为两个 Worker 生成不同名称。

例如：先等待 0.5 秒，再从输入数据导航到 `/customer`，等待 2 秒后查找顾客：

```text
操作类型:   wait, nav, wait, find_click
元素定位器: 0.5, , 2, 共检测
输入数据:   /customer
```

## 支持的操作类型

| 操作 | 定位器 | 输入数据 | 说明 |
|---|---|---|---|
| `input` | 必填 | 文本 | 清空并输入文本 |
| `click` | 必填 | 无 | 点击元素；失败重试后终止用例 |
| `select` | 必填 | 选项值，可空 | 原生或 Ant Design 下拉选择 |
| `verify` | 必填 | 无 | 验证元素可见 |
| `hover` | 必填 | 无 | 鼠标悬停 |
| `scroll` | 可空 | 无 | 滚动到元素；为空时滚动到底部 |
| `wait` | 秒数 | 无 | 支持小数，如 `0.5` |
| `set_viewport` | `宽x高` | 无 | 固定视觉标准图要求的浏览器视口，例如 `2561x1398` |
| `wait_hidden` | 必填 | 无 | 等待加载提示或遮罩消失，超时即失败 |
| `nav` | 可空 | URL | 支持相对路径，优先读取输入数据 |
| `find_click` | 必填 | 无 | 查找有检测记录的顾客并进入详情 |
| `upload` | 必填 | 文件路径 | 上传文件 |
| `daterange` | 必填 | 日期范围 | 示例 `2026/01/01-2026/06/28` |
| `switch_tab` | 可空 | 无 | 为空切到最新标签页，或填写页码 |
| `vision_compare_step` | 必填，通常为 `body` | `<基线用例ID>/<步骤图片名>` | 在当前位置立即截图，按步骤元数据裁剪红框区域并与人工标准图比较；不确定或不匹配立即失败 |

## 支持的断言类型

| 断言 | 需要定位器 | 说明 |
|---|---|---|
| `text_equals` | 可选 | 元素文本或页面文本完全相等 |
| `text_contains` | 可选 | 元素、页面或 Toast 包含文本 |
| `text_visible` | 否 | 页面展示全部指定文本 |
| `text_not_empty` | 是 | 元素文本非空 |
| `element_visible` | 是 | 元素可见 |
| `element_count` | 是 | 元素数量不少于期望值 |
| `attr_equals` | 是 | 属性相等，如 `value=abc`；也支持 `class包含active` |
| `url_contains` | 否 | URL 包含路径；支持“或”逻辑 |
| `url_matches` | 否 | URL 匹配正则 |
| `empty_list` | 可选 | 列表为空或显示“暂无” |
| `list_contains` | 是 | 列表包含文本 |
| `date_in_range` / `date_format` | 是 | 页面日期格式正确 |
| `value_in_range` | 是 | 页面数值位于期望范围 |
| `age_in_range` | 否 | 根据生日计算年龄并验证范围 |
| `file_verify` | 否 | 指定文件真实存在且非空 |
| `text_optional` | 是 | 字段值允许为空，但字段标签必须可见 |
| `vision_contains` | 是，且必须在「断言定位器」列 | 裁剪指定区域，逐项识别「验证点」中的全部期望文字/元素；看不清或不存在即失败 |
| `vision_count` | 是，且必须在「断言定位器」列 | 识别当前裁剪区域的可见图谱/卡片数量；`至少5项` 表示下限，其余数字表示精确数量 |
| `vision_page_state` | 是，且必须在「断言定位器」列 | 页面类型只能验证影像阅览页、登录页、顾客列表页、加载页或未知 |
| `vision_canvas_ready` | 是，且必须在「断言定位器」列 | Canvas 必须显示完整、非空影像，空白、加载中、错误或不确定均失败 |
| `vision_compare_reference` | 是，且必须在「断言定位器」列 | 按用例 ID 自动加载人工审核的标准截图，与当前截图比较页面结构、关键元素、可用性和错误状态 |
| `vision_step_sequence` | 否 | 校验本用例实际完成的步骤视觉比较次数；次数取「验证点」中的第一个数字 |

历史写法 `visible_text` 仍兼容，但新用例统一使用 `text_visible`。

### 视觉断言示例

视觉模型只返回可见事实，最终 `pass/fail` 由本地代码计算。建议先在影像阅览页稳定父容器上增加 `data-testid`，再填写「断言定位器」；不要使用包含姓名、手机号的整页容器。

```text
断言类型:     vision_contains
断言定位器:   [data-testid='image-mode-toolbar']
验证点:       '冷光','粗纹','毛孔','细纹','凹陷'
```

```text
断言类型:     vision_canvas_ready
断言定位器:   [data-testid='skin-image-canvas']
验证点:       影像画布加载完成
```

### 自动标准图对比

标准截图只需要提前放置一次，运行时不需要人工选择两张图片。目录约定为：

```text
test_assets/vision_baselines/
└─ TC-IMAGE-006/
   ├─ reference.png
   └─ reference.meta.json
```

`TC-IMAGE-006` 可配置为：

```text
用例ID:       TC-IMAGE-006
断言类型:     vision_compare_reference
断言定位器:   [data-testid='image-viewer-shell']
验证点:       页面布局正常，查看案例/查看报告/返回按钮完整可见，页面可用且无异常提示
```

执行时 Harness 会自动用「用例ID」解析标准图，先用 `reference.meta.json` 校验图片哈希、尺寸、截图定位器和人工批准状态，再截取当前区域，并在浏览器内存中自动生成“上方标准截图、下方当前截图”的单张对照图后发送给视觉模型。这兼容单次只允许一张图片的公司视觉网关，运行时不需要人工拼图。模型只返回布局、关键元素、可用性和异常差异等结构化观察；最终结论由本地严格规则计算。标准图缺失会报告 `BASELINE_MISSING`，元数据缺失会报告 `BASELINE_METADATA_MISSING`，图片被替换但未重新批准会报告 `BASELINE_HASH_MISMATCH`。

标准图和当前截图必须使用相同页面区域、浏览器窗口大小与缩放比例。标准图需要人工审核，并应预先移除或遮挡姓名、手机号、编号等动态或个人信息。不要把标准图生成动作放进普通回归流程。

视觉断言需要 `.env` 中配置 `VISION_API_KEY`、`VISION_BASE_URL` 和 `VISION_MODEL`。`VISION_BASELINE_DIR` 可覆盖标准图根目录，`VISION_REQUIRE_BASELINE_METADATA=true` 默认强制基线治理。默认只向 Allure 写入结构化观察结果与当前图/标准图 SHA-256；只有显式设置 `VISION_ATTACH_SCREENSHOT=true` 才保存图片。

视觉失败默认不会进入通用的失败自动复跑改判流程，避免同一模型前后判断不一致时把真实失败改成通过。只有明确接受这一风险时，才设置 `VISION_RERUN_FAILURES=true`。

同一用例需要验证多个中间状态时，在操作序列中交替使用点击、可选等待和
`vision_compare_step`。步骤标准图放在
`test_assets/vision_baselines/<基线用例ID>/steps/`，并由同目录
`steps.meta.json` 固定哈希、尺寸、`body` 截图定位器和红框内部裁剪坐标。
每个 `vision_compare_step` 从「输入数据」按顺序消费一个
`<基线用例ID>/<步骤图片名>`；最终使用 `vision_step_sequence` 校验全部比较均已执行。

## 定位器建议

优先顺序：稳定 ID/属性 → role/label/placeholder → 稳定文本 → CSS 类名。避免依赖构建后会变化的随机类名，也不要用 JS 点击绕过真实页面交互问题。

## 运行方式

- 全量无头运行：双击 `run_tests.bat`
- 全量有头运行：双击 `run_tests_headed.bat`
- 双账号双进程运行：双击 `run_parallel_tests.bat`
- 仅检查双进程分组：`.venv\Scripts\python.exe run_parallel_tests.py --dry-run`
- 单条用例：双击 `run_one_case.bat`，输入用例ID
- 仅离线框架检查：`.venv\Scripts\python.exe -m pytest unit_tests -q -o "addopts="`
- 视觉评测集离线门禁：`.venv\Scripts\python.exe scripts\run_vision_eval.py`
- 真实视觉评测（图片会发送到配置的模型服务）：`.venv\Scripts\python.exe scripts\run_vision_eval.py --run-model --repeat 3`
