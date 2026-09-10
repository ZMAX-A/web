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
