# 颜佳AI-web自动化测试

> 基于 Playwright + pytest + Allure 的数据驱动自动化测试框架。
> **不需要编程知识**，只需编辑 Excel 即可新增/修改测试用例。

---

## 📦 项目结构

```
颜佳AI-web自动化测试/
├── run_tests.bat              ← 一键运行（双击即可）
├── requirements.txt           ← Python 依赖列表
├── .env                       ← 测试环境配置（账号密码）
├── .env.example               ← 配置模板
│
├── test_cases/
│   └── test_case.xlsx         ← ★ 测试用例（编辑这个文件）
│
├── pages/                     ← 页面对象（一般不需要动）
│   ├── base_page.py
│   ├── login_page.py
│   ├── home_page.py
│   ├── case_list_page.py
│   ├── add_case_page.py
│   ├── settings_page.py
│   ├── customer_list_page.py
│   └── ...（共 13 个页面对象）
│
├── tests/
│   ├── conftest.py            ← 测试配置（自动截图、回写 Excel）
│   └── test_core_cases.py     ← 测试执行引擎（通用）
│
├── utils/
│   ├── excel_handler.py       ← Excel 读写与批量回写
│   ├── case_validator.py      ← Excel 用例预校验
│   ├── step_executor.py       ← 严格操作执行器
│   └── assertion_executor.py  ← 严格断言执行器
│
├── unit_tests/                ← 离线框架回归测试
├── reports/                   ← 测试报告（自动生成）
├── screenshots/               ← 失败截图（自动生成）
├── test_case_writing_guide.md ← 用例编写规范（必读）
└── README.md                  ← 本文件
```

---

## 🚀 快速开始（3 分钟上手）

### 第 1 步：安装 Python（仅首次，约 5 分钟）

> 如果你的电脑已经有 Python（CMD 输入 `python --version` 有输出），跳过此步。

1. 打开浏览器访问：https://www.python.org/downloads/
2. 点击黄色 **Download Python 3.12.x** 按钮下载
3. **运行安装程序，务必勾选 ✅ `Add Python to PATH`**
4. 验证：按 `Win + R` → 输入 `cmd` → 输入 `python --version`，显示版本号即成功

### 第 2 步：配置账号（仅首次，1 分钟）

1. 在项目文件夹内，找到 `.env.example` 文件
2. **复制一份**，重命名为 `.env`（去掉 .example）
3. 右键 `.env` → 打开方式 → 记事本，填入真实信息：

```
BASE_URL=https://m3dtest-yanjia-ai.xiaofutech.com/login
TEST_USERNAME=你的账号
TEST_PASSWORD=你的密码
```

> 💡 或者直接双击 `run_tests.bat`，它会自动检测并引导你填写

### 第 3 步：编辑测试用例（每次新增/修改用）

打开 `test_cases/test_case.xlsx`，按以下格式填写新行：

| 用例ID | 模块 | 测试场景 | 测试点 | 优先级 | 前置条件 | 操作类型 | 元素定位器 | 输入数据 | 断言类型 | 验证点 |
|-------|------|---------|--------|-------|---------|---------|-----------|---------|---------|-------|
| TC-LOGIN-002 | 账号登录 | 登录失败-错误密码 | 验证错误密码提示 | P0 | 打开登录页 | input,input,click,click | #username,#password,.ant-select-selector,button[type='submit'] | admin\|wrong123 | text_contains | '登录失败' |

📖 **完整编写规范见 [test_case_writing_guide.md](test_case_writing_guide.md)**，里面包含详细的操作类型说明、断言类型说明、选择器写法示例。

### 第 4 步：一键运行

**双击 `run_tests.bat`**，脚本会自动完成一切：

| 阶段 | 耗时 | 说明 |
|------|------|------|
| ① 创建虚拟环境 | ~30 秒 | 仅首次 |
| ② 安装依赖 | ~3 分钟 | 仅首次 |
| ③ 安装 Playwright 浏览器 | ~2 分钟 | 仅首次 |
| ④ 离线校验框架和 Excel | <10 秒 | 有配置错误时不会启动浏览器 |
| ⑤ 执行全部测试用例 | 5~30 分钟 | 取决于用例数量 |
| ⑥ 批量回写测试结果到 Excel | 自动 | 包含 setup/teardown 失败 |
| ⑦ 生成测试报告 | 自动 | 需安装 Allure（可选） |

> 首次运行约 **10 分钟**，之后每次只需 **测试执行时间**。

---

## 📊 查看测试结果

### 方式 1：直接看 Excel（最快）

打开 `test_cases/test_case.xlsx`，翻到最右侧的「实际结果」列：

- ✅ `pass` — 测试通过
- ❌ `fail: 具体原因` — 测试失败，后面跟着失败原因

### 方式 2：HTML 可视化报告（推荐，需要安装 Allure）

Allure 报告包含：通过率统计、失败截图、详细步骤、执行时间线。

**安装 Allure（仅首次，5 分钟）：**

**方法一（推荐，1 分钟）：**
```powershell
# 按 Win+X → Windows Terminal (管理员) → 粘贴运行：
winget install Allure.Allure
```

**方法二（手动）：**
1. 安装 Java JDK 17+：https://adoptium.net/
2. 下载 Allure：https://github.com/allure-framework/allure2/releases
3. 解压，将 `allure/bin` 目录添加到系统 PATH 环境变量
4. 验证：打开 CMD 输入 `allure --version`

安装后，双击 `run_tests.bat` 会自动生成 HTML 报告并打开浏览器。

---

## 🔄 完整工作流（一张图）

```
┌────────────────────────────────────────────────────┐
│  ① 编辑 Excel                                     │
│     test_cases/test_case.xlsx                      │
│     - 新增行 / 修改现有行                           │
└────────────────────┬───────────────────────────────┘
                     ↓
┌────────────────────┴───────────────────────────────┐
│  ② 双击 run_tests.bat                              │
│     自动：安装环境 → 执行测试 → 回写结果             │
└────────────────────┬───────────────────────────────┘
                     ↓
┌────────────────────┴───────────────────────────────┐
│  ③ 查看结果                                        │
│     - Excel →「实际结果」列直接看 pass/fail          │
│     - 失败原因见 Excel 或 screenshots/ 截图          │
│     - Allure 报告（如已安装）                        │
└────────────────────────────────────────────────────┘
```

---

## ❓ 常见问题

### Q：双击 `run_tests.bat` 没反应？
→ 检查是否安装了 Python，安装时是否勾选了 "Add Python to PATH"。

### Q：运行报错 "账号或密码错误"？
→ 打开 `.env` 文件，检查 `TEST_USERNAME` 和 `TEST_PASSWORD` 是否正确。

### Q：测试结果怎么看？
→ 最简单：打开 `test_cases/test_case.xlsx`，看「实际结果」列。

### Q：失败原因在哪里看？
→ Excel 的「实际结果」列会写 `fail: 具体原因`。同时 `screenshots/` 文件夹下有失败时的页面截图。

### Q：想只跑某几个用例怎么办？
→ 双击 `run_one_case.bat`，输入用例ID（例如 `TC-DETAIL-004`）。不要为了筛选用例删除 Excel 行。

### Q：Mac / Linux 怎么用？
→ 项目支持，但需要从终端运行命令。暂时没有提供 .sh 脚本，如有需要可以联系我们。

### Q：运行时提示 "磁盘空间不足"？
→ 删除 `.venv` 文件夹可释放约 200MB，下次运行会重新创建。

---

## 📚 参考文档

| 文档 | 说明 |
|------|------|
| [test_case_writing_guide.md](test_case_writing_guide.md) | ★ **必读** 用例编写完整规范 |
| [test_cases/test_case.xlsx](test_cases/test_case.xlsx) | 测试用例文件（实际编辑这个） |
| [generate_allure_report.bat](generate_allure_report.bat) | 单独生成 Allure 报告（已安装 Allure 时使用） |
