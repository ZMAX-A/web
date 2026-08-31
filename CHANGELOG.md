# 更新日志

本项目使用[Semantic Versioning](https://semver.org/lang/zh-CN/)管理版本。

## [Unreleased]

### 计划新增

- 视觉断言 `vision_contains` 和 `vision_count`。
- 影像阅览页截图裁剪与结果缓存。

## [1.0.0] - 2026-08-31

### 新增

- 基于 Playwright、pytest 和 Allure 的 Excel 数据驱动 Web 自动化框架。
- 单账号、双账号双进程与 `SERIAL` 串行用例执行。
- 启动前用例校验、失败截图、Excel 结果回写和 Allure 报告归档。
- 失败用例自动复跑与双进程结果汇总。
- 登录态复用、中文浏览器环境与测试环境影像页兼容配置。
- 离线单元测试、用例编写规范和发布流程文档。

### 发布边界

- `test_cases/test_case.xlsx` 是 v1.0.0 的用例基线。
- 视觉模型客户端与视觉断言仍属后续功能，不属于 v1.0.0 正式承诺范围。
- 本地运行结果、报告、截图、密钥和 Excel 备份不属于发布产物。

### 发布验证

- 2026-08-31 离线单元测试：23 项全部通过。
- 2026-08-31 双账号全量回归：93 条启用用例全部通过，0 failed、0 broken、0 skipped。
