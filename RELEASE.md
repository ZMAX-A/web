# 版本发布规范

## 版本号

项目使用语义化版本 `MAJOR.MINOR.PATCH`：

- `PATCH`：缺陷修复、稳定性优化，不改变现有用法。
- `MINOR`：增加向后兼容的功能、操作或断言。
- `MAJOR`：Excel 结构、命令行、配置或执行协议发生不兼容变化。

`VERSION` 是 Runner 包版本号来源，完整包 Git 标签使用相同版本并添加 `v` 前缀，例如
`v1.0.0`。`TESTOPS_BASELINE_VERSION` 是 Excel Case Baseline 版本号来源，Excel-only 标签直接
使用其值，例如 `case-v1.0.1`。两类已发布标签都不得移动或覆盖。

## 分支约定

- `main`：始终保持可交付。
- `codex/feat-*`：新功能。
- `codex/fix-*`：缺陷修复。
- `codex/release-*`：版本整理与发布验证。

功能分支通过验证后合并到 `main`，只在 `main` 的已验证提交上创建正式版本标签。

## Excel 安全规则

`test_cases/test_case.xlsx` 是受版本管理的用例基线，二进制冲突不做自动合并。

1. Git 操作前关闭 Excel/WPS，检查 `~$*.xlsx` 锁文件。
2. 备份当前工作簿并记录 SHA-256。
3. 只提交有意图的用例定义变更，不提交单纯的运行结果回写。
4. 本地备份使用 `test_cases/*.local-*.xlsx` 或 `test_cases/*.backup-*.xlsx` 命名，不进入 Git。
5. 合并后重新校验工作簿可读性、工作表结构和 SHA-256。

## 发布门禁

每个正式版本至少完成：

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest unit_tests -q -o "addopts="
.\.venv\Scripts\python.exe run_parallel_tests.py --dry-run
```

随后在授权测试环境完成一次正式全量回归，保存运行摘要和 Allure 报告。发布前还必须确认：

- 工作区只包含本次发布的预期变更。
- `.env`、账号、密码、Token、Cookie 和客户数据未进入提交。
- `VERSION`、`CHANGELOG.md` 和 Git 标签的版本号一致。
- 已刷新远端状态，待推送分支没有落后 `origin/main`。

## 发布命令

### 完整 Runner 包

脚本、依赖、测试资源或执行协议发生变化时，必须提升 `VERSION` 并发布完整包。以 `1.0.0` 为例，
在发布提交已合并到 `main` 且验证通过后执行：

```powershell
git tag -a v1.0.0 -m "颜佳AI Web自动化测试框架 v1.0.0"
git push origin main
git push origin v1.0.0
```

### 仅更新 Excel 基线

仅修改 `test_cases/test_case.xlsx`、`TESTOPS_BASELINE_VERSION` 和发布文档时，不提升 `VERSION`，
也不重新构建 Runner 镜像。确认当前 `VERSION` 对应的 `v*` Release 已存在后，提升
`TESTOPS_BASELINE_VERSION`，提交并发布相同名称的 `case-v*` 标签：

首次启用前必须先发布一次 `v1.1.12` 或更高版本的过渡 Runner 包，使 Worker 具备按
`RunSnapshot` 生成隔离运行时 Excel 的能力；工作流会拒绝复用更早的包，避免平台基线与镜像内
旧 Excel 不一致。

```powershell
git tag -a case-v1.0.1 -m "颜佳AI Web用例基线 case-v1.0.1"
git push origin main
git push origin case-v1.0.1
```

工作流会从 `v${VERSION}` Release 读取现有包坐标，验证从该包源提交到当前标签之间只有 Excel
快车道允许的文件变化，然后复用同一个镜像 digest 生成新的不可变基线 Release。只要出现脚本、
依赖或测试资源变化，工作流会拒绝 Excel-only 发布，必须改走完整 Runner 包流程。
