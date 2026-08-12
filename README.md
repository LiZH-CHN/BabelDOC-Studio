# BabelDOC Studio — AI 学术论文翻译工作站

> 基于 [BabelDOC](https://github.com/funstory-ai/BabelDOC) 深度定制的 GUI 翻译工具，让 PDF 论文翻译保留完整排版，并集成记忆库、术语库、多模型对比、成本分析等企业级功能。

![版本](https://img.shields.io/badge/version-1.0.0-blue)
![平台](https://img.shields.io/badge/platform-Windows%2010%2B-green)
![许可证](https://img.shields.io/badge/license-AGPL--3.0-orange)

---

**[中文文档](#项目简介)** | **[English Documentation](#english-documentation)**

---

##  项目简介

**BabelDOC-Studio** 是一款面向科研工作者的 PDF 论文翻译软件，在基于 BabelDOC 强大排版与公式无损能力的基础上，提供了：

- **可视化图形界面**（PyQt6），告别命令行
- **7 大主流 AI 模型提供商** 一键切换（DeepSeek / GLM / Kimi / OpenAI / Qwen /  LongCat / 自定义）
- **翻译记忆库（TM）** 与 **术语库（Glossary）**，重复利用优质译文，节省 token 费用（似乎目前不太好用）
- **翻译质量 QA 检查** 与 **自动修复**，确保数字、公式、占位符不丢失
- **多引擎对比模式**，并排对照不同模型翻译结果，辅助人工选优
- **实时成本统计**，让每一笔 API 调用都明明白白
- **OCR 支持**，轻松处理扫描版 PDF（还没测试，后面再说）

无论你是研究生、科研人员还是翻译从业者，BabelDOC Studio 都能帮你**高效、精准、低成本**地完成外文文献翻译。

---

##  功能特性

### 核心翻译引擎
-  基于 BabelDOC，**完整保留 PDF 原始排版**（公式、表格、图表、目录、脚注）
-  支持 **双语对照** 或 **纯译文** 输出
-  可选 **OCR 识别**（基于 PaddleOCR），扫描件也能翻

### 模型配置（多供应商全覆盖）
-  内置 **7 家模型提供商**，下拉即用，无需手写配置：
  - **DeepSeek**（deepseek-v4-pro/flash）
  - **GLM（智谱）**（GLM-5.2 / 5.1 / 5v 等全系列）
  - **Kimi（月之暗面）**（kimi-k3 / k2.7-code 等）
  - **OpenAI**（GPT-5.6 系列 / GPT-4.1 等）
  - **Qwen（通义千问）**（Qwen3-Max / Qwen-Plus / Qwen-Long 等）
  - **LongCat（美团）**（LongCat-2.0）
  - **自定义 OpenAI 兼容**（接入任意第三方或自部署模型）
-  自动填充 **Base URL** 与 **上下文长度**，并可手动编辑
-  实时校验 API Key 有效性

### 翻译增强模块
-  **翻译记忆库（TM）**
  - 本地 SQLite 持久化存储
  - 相似度匹配（Levenshtein，阈值可调），命中则直接复用，**零 token 消耗**
  - 支持导入/导出标准 TMX 格式

-  **术语库（Glossary）**
  - 强制指定术语翻译（如 `Transformer → 变换器`）
  - 支持 CSV/TBX 导入导出，与 Trados 等主流工具兼容

-  **质量保证（QA）**
  - 自动检测数字、公式占位符是否完整
  - 发现缺失时触发**自动修复**，重新调用模型补全

-  **成本分析**
  - 实时统计 Token 消耗与预估费用
  - 支持多模型成本对比

-  **自适应翻译**
  - 模型超时自动切换备用模型
  - 支持多引擎并发对比

---

## 快速开始

### 系统要求

| 项目 | 要求 |
|------|------|
| **操作系统** | Windows 10 专业版 64位 或更高版本 |
| **Python** | 3.12（严格版本） |
| **架构** | x86_64 |
| **网络** | 需要稳定的互联网连接（调用 API） |

> ⚠️ **重要提示**：BabelDOC 要求 **Python 3.12**，其他版本可能导致兼容性问题。

---

### 一键配置（推荐）

项目提供了一键环境配置脚本，**无需手动安装 uv 或创建虚拟环境**：

| 操作系统 | 脚本文件 | 执行方式 |
|----------|----------|----------|
| Windows | `setup.bat` | 双击运行 |
| Linux/macOS | `setup.sh` | `chmod +x setup.sh && ./setup.sh` |

**脚本自动完成以下操作**：

1.  检测 Python 3.12 环境
2.  自动安装 `uv` 工具（如未安装）
3.  创建 Python 虚拟环境（`.venv`）
4.  安装所有项目依赖（`uv sync`）
5.  验证 BabelDOC 导入是否成功

执行完成后，按脚本提示的启动方式运行即可。

---

### 手动配置（可选）

如需手动配置环境，请按以下步骤操作：

#### 1. 安装 Python 3.12

- 官网下载：https://www.python.org/downloads/
- 安装时务必勾选 **"Add Python to PATH"**

#### 2. 安装 uv 工具

```bash
# Windows (PowerShell)
powershell -Command "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 3. 创建虚拟环境并安装依赖

```bash
# 进入项目目录
cd BabelDOC

# 创建虚拟环境（指定 Python 3.12）
uv venv --python 3.12

# 安装依赖
uv sync
```

#### 4. 验证安装

```bash
# Windows
.venv\Scripts\python -c "import babeldoc; print('✅ 安装成功')"

# Linux/macOS
source .venv/bin/activate
python -c "import babeldoc; print('✅ 安装成功')"
```

---

### 从 PyPI 安装（仅使用 BabelDOC 核心）

如果只需要 BabelDOC 命令行工具，无需 GUI 界面：

```bash
# 使用 uv 工具安装
uv tool install --python 3.12 BabelDOC

# 查看帮助
babeldoc --help

# 示例：翻译 PDF
babeldoc --openai --openai-model "gpt-4o-mini" \
    --openai-base-url "https://api.openai.com/v1" \
    --openai-api-key "your-api-key" \
    --files example.pdf
```

---

##  启动应用

配置完成后，按以下方式启动：

### 方式一：双击启动（Windows）
双击项目根目录的 `启动论文翻译.bat`

### 方式二：命令行启动

```bash
# Windows
.venv\Scripts\python main.py

# Linux/macOS
source .venv/bin/activate
python main.py
```

### 方式三：模块方式启动

```bash
# Windows
.venv\Scripts\python -m BabelDOC_Studio

# Linux/macOS
source .venv/bin/activate
python -m BabelDOC_Studio
```

---

##  项目结构

```
BabelDOC/
├── main.py                      # GUI 主入口
├── setup.bat / setup.sh         # 一键环境配置脚本
├── pyproject.toml               # 项目配置与依赖
├── uv.lock                      # uv 锁文件（锁定依赖版本）
├── BabelDOC_Studio.spec         # PyInstaller 打包配置
├── installer_setup.iss          # Inno Setup 安装程序脚本
├── babeldoc/                    # BabelDOC 核心库（源码）
│   ├── format/
│   │   └── pdf/                 # PDF 处理核心
│   │       ├── high_level.py    # 高层 API
│   │       └── translation_config.py
│   └── ...
├── config/                      # 配置文件
│   └── models.json              # 模型预设配置
├── resources/                   # 资源文件
│   └── icon.ico                 # 应用图标
└── docs/                        # 文档
    └── PACKAGING.md             # 打包详细指南
```

---

### 开发环境准备

```bash
# 克隆仓库
git clone https://github.com/LiZH-CHN/BabelDOC-Studio.git
cd BabelDOC-Studio

# 一键配置环境
# Windows: 双击 setup.bat
# Linux/macOS: ./setup.sh

# 激活虚拟环境后启动
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS
python main.py
```

---

##  许可证

本项目基于 [AGPL-3.0](LICENSE) 许可证开源。

BabelDOC 核心库亦采用 AGPL-3.0 许可证，任何修改和分发都需遵守该许可证条款。

---

##  致谢

- [BabelDOC](https://github.com/funstory-ai/BabelDOC) — 核心 PDF 翻译引擎
- [uv](https://github.com/astral-sh/uv) — 极速 Python 包管理工具
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — GUI 框架

---

##  联系方式

- 邮箱：lizihao0104@126.com；欢迎反馈问题

---

## English Documentation

### Overview

**BabelDOC Studio** is a PDF paper translation GUI tool for researchers, built on top of [BabelDOC](https://github.com/funstory-ai/BabelDOC). It delivers layout-preserving translation while integrating enterprise-grade features including Translation Memory, Glossary, multi-model comparison, and cost analysis.

- **Visual GUI** (PyQt6) — no command line needed
- **7+ major AI providers** with one-click switching (DeepSeek / GLM / Kimi / OpenAI / Qwen / LongCat / Custom)
- **Translation Memory (TM)** & **Glossary** — reuse quality translations, save token costs
- **QA checking** & **auto-repair** — ensures numbers, formulas, and placeholders are preserved
- **Multi-engine comparison** — side-by-side model output for manual selection
- **Real-time cost tracking** — transparent API spending
- **OCR support** — handle scanned PDFs with PaddleOCR

Whether you are a graduate student, researcher, or translator, BabelDOC Studio helps you translate foreign literature **efficiently, accurately, and cost-effectively**.

---

### Features

#### Core Translation Engine
- BabelDOC-powered, **full layout preservation** (formulas, tables, charts, TOC, footnotes)
- **Bilingual comparison** or **monolingual** output
- Optional **OCR recognition** via PaddleOCR for scanned documents

#### Model Configuration (Multi-Provider Coverage)
- **9 built-in providers**, select from dropdown — no manual config:
  - **DeepSeek** (deepseek-v4-pro/flash)
  - **GLM (Zhipu)** (GLM-5.2 / 5.1 / 5v series)
  - **Kimi (Moonshot)** (kimi-k3 / k2.7-code, etc.)
  - **OpenAI** (GPT-5.6 series / GPT-4.1, etc.)
  - **Qwen (Alibaba)** (Qwen3-Max / Qwen-Plus / Qwen-Long, etc.)
  - **LongCat** (LongCat-2.0)
  - **Custom OpenAI-compatible** (any third-party or self-hosted model)
- Auto-populates **Base URL** & **context length**, with manual override
- Real-time **API Key validation**

#### Translation Enhancement Modules
- **Translation Memory (TM)**
  - Local SQLite persistent storage
  - Levenshtein similarity matching (configurable threshold), **zero token cost** on hit
  - Import/export standard TMX format

- **Glossary**
  - Enforce term translations (e.g., `Transformer → 变换器`)
  - CSV/TBX import/export, compatible with Trados and other CAT tools

- **Quality Assurance (QA)**
  - Automatic detection of missing numbers, formula placeholders
  - **Auto-repair** triggers model retry when omissions found

- **Cost Analysis**
  - Real-time token consumption and estimated cost tracking
  - Multi-model cost comparison

- **Adaptive Translation**
  - Automatic failover to backup model on timeout
  - Multi-engine concurrent comparison

---

### Quick Start

#### System Requirements

| Item | Requirement |
|------|-------------|
| **OS** | Windows 10 Pro 64-bit or later |
| **Python** | 3.12 (strict version) |
| **Architecture** | x86_64 |
| **Network** | Stable internet connection (for API calls) |

> ⚠️ **Important**: BabelDOC requires **Python 3.12**. Other versions may cause compatibility issues.

---

#### One-Click Setup (Recommended)

Use the provided scripts — **no manual uv or venv setup needed**:

| OS | Script | How to Run |
|----|--------|------------|
| Windows | `setup.bat` | Double-click |
| Linux/macOS | `setup.sh` | `chmod +x setup.sh && ./setup.sh` |

**The script automatically**:

1. Checks Python 3.12 environment
2. Installs `uv` (if not present)
3. Creates Python virtual environment (`.venv`)
4. Installs all dependencies (`uv sync`)
5. Verifies BabelDOC import

Follow the on-screen instructions to launch after completion.

---

#### Manual Setup (Optional)

If you prefer to configure manually:

##### 1. Install Python 3.12

- Download: https://www.python.org/downloads/
- Check **"Add Python to PATH"** during installation

##### 2. Install uv

```bash
# Windows (PowerShell)
powershell -Command "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

##### 3. Create Virtual Environment & Install Dependencies

```bash
cd BabelDOC
uv venv --python 3.12
uv sync
```

##### 4. Verify Installation

```bash
# Windows
.venv\Scripts\python -c "import babeldoc; print('Installation OK')"

# Linux/macOS
source .venv/bin/activate
python -c "import babeldoc; print('Installation OK')"
```

---

#### Install from PyPI (BabelDOC Core Only)

If you only need the BabelDOC CLI without GUI:

```bash
uv tool install --python 3.12 BabelDOC

babeldoc --help

# Example: translate a PDF
babeldoc --openai --openai-model "gpt-4o-mini" \
    --openai-base-url "https://api.openai.com/v1" \
    --openai-api-key "your-api-key" \
    --files example.pdf
```

---

### Launch the Application

#### Method 1: Double-Click (Windows)
Double-click `启动论文翻译.bat` in the project root.

#### Method 2: Command Line

```bash
# Windows
.venv\Scripts\python main.py

# Linux/macOS
source .venv/bin/activate
python main.py
```

#### Method 3: Module Mode

```bash
# Windows
.venv\Scripts\python -m BabelDOC_Studio

# Linux/macOS
source .venv/bin/activate
python -m BabelDOC_Studio
```

---

### Project Structure

```
BabelDOC/
├── main.py                      # GUI entry point
├── setup.bat / setup.sh         # One-click environment setup
├── pyproject.toml               # Project config & dependencies
├── uv.lock                      # uv lock file (pinned versions)
├── BabelDOC_Studio.spec         # PyInstaller packaging config
├── installer_setup.iss          # Inno Setup installer script
├── babeldoc/                    # BabelDOC core library (source)
│   ├── format/
│   │   └── pdf/                 # PDF processing core
│   │       ├── high_level.py    # High-level API
│   │       └── translation_config.py
│   └── ...
├── config/                      # Configuration files
│   └── models.json              # Model preset configuration
├── resources/                   # Resource files
│   └── icon.ico                 # Application icon
└── docs/                        # Documentation
    └── PACKAGING.md             # Packaging guide
```

---

#### Development Setup

```bash
# Clone the repository
git clone https://github.com/LiZH-CHN/BabelDOC-Studio.git
cd BabelDOC-Studio

# One-click environment setup
# Windows: double-click setup.bat
# Linux/macOS: ./setup.sh

# Activate virtual environment and launch
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS
python main.py
```

---

### License

This project is open-sourced under the [AGPL-3.0](LICENSE) license.

The BabelDOC core library is also licensed under AGPL-3.0. Any modifications and distributions must comply with the license terms.

---

### Acknowledgments

- [BabelDOC](https://github.com/funstory-ai/BabelDOC) — Core PDF translation engine
- [uv](https://github.com/astral-sh/uv) — Fast Python package manager
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — GUI framework

---

### Contact

- Email: lizihao0104@126.com — feedback welcome
