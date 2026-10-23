# 视觉标准截图

> 安全边界：本仓库为公开仓库，不提交真实人脸、客户影像或对应标注集。
> 当前仅保留目录契约；标准图必须经过脱敏或得到明确公开授权，并通过人工审核后才可发布。

每条使用 `vision_compare_reference` 的用例按以下固定路径放置一张经过人工审核的 PNG 和元数据：

```text
test_assets/vision_baselines/<用例ID>/reference.png
test_assets/vision_baselines/<用例ID>/reference.meta.json
```

例如 `TC-IMAGE-006`：

```text
test_assets/vision_baselines/TC-IMAGE-006/reference.png
```

标准图必须与 Excel「断言定位器」截取的是同一区域，并使用相同的浏览器窗口、缩放比例和稳定测试数据。提交前请移除或遮挡姓名、手机号、账号、编号等个人信息。元数据必须记录标准图 SHA-256、尺寸、截图定位器、人工批准状态及允许忽略的动态差异；图片或定位器变化但元数据未同步时，Harness 会失败关闭。

回归测试只读取标准图及其元数据。文件缺失会明确失败，Harness 不会自动创建、更新或覆盖它们。

## 组件级截图（候选配置）

`current_capture.strategy = "component_region"` 用实际 DOM 边界定位当前区域，
避免整页绝对像素坐标随布局变化截进旁边控件。示例配置在
`test_assets/vision_capture_profiles/TC-IMAGE-042.json`；该文件本身不会自动改变现有 Run。

- `target`：定位器、向上层数、预期数量（目标必须唯一）。
- `edges`：可选 left/top/right/bottom 边界锚点。left/top 取锚点远边，right/bottom 取近边；
  多个锚点必须达到声明数量，分屏时取最内侧边界。不会隐藏、删除控件或自动缩放图片。
  可用 `side` 显式指定同一坐标轴上的锚点边：例如页面截图的 right 边界取 Canvas 的
  `side=right`，这样保留顶部“返回”按钮，而不会把右侧数据面板纳入比较。
- `ready.visible`：必须存在的组件/选中状态；`ready.hidden`：必须消失的加载提示。
- `stable_ms` / `sample_ms`：边界与渲染稳定窗口/采样间隔。还检查字体已加载、区域非空白，
  页面不得滚动，区域必须在视口内。缺失、多匹配、越界、未稳定一律失败，不调用模型。
- 图像稳定性使用 64×64 像素采样，窗口内对比首帧，平均 RGB 差值不超过 0.5/255、
  差值大于 8/255 的采样点比例不超过 0.5%。仅用于截图时机，不用于判断标准图是否通过。

标准图的 `crop_box`、SHA-256、允许差异和视觉判定规则保持不变。
面部角度等 Canvas 语义仍由既有视觉比较检查；DOM 存在或画面静止不是功能正确的证明。
页面结构/标识变化时应修正截图配置并审核，不要扩大允许差异来掩盖失败。

将现有私有图片包迁移成独立候选包：

```powershell
python scripts/prepare_capture_baselines.py --source <原私有基线目录> --profile test_assets/vision_capture_profiles/TC-IMAGE-042.json --output <新的候选目录>
```

工具拒绝原地覆盖、已有输出目录及错误图片哈希，只更新当前截图策略，并输出迁移摘要。
先设置 `VISION_BASELINE_DIR` 指向候选目录进行回归，人工检查新旧裁剪区域语义一致，
再按平台供应链流程发布完整 Runner 包及相应私有资源版本；不覆盖已发布的内容寻址目录。

维护者可运行 `python scripts/verify_component_capture.py`，使用不联网的合成页面检查
组件移动、空白画面与缺失状态；它不证明真实用例已通过，也不评估视觉模型准确率。
