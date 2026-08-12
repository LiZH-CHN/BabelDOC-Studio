"""主窗口模块"""
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QComboBox, QLineEdit, QPushButton,
    QCheckBox, QSpinBox, QProgressBar, QTextEdit,
    QFileDialog, QMessageBox, QFrame, QSizePolicy,
    QApplication, QSplitter
)

from babeldoc.translator.translator import OpenAITranslator
from gui.quality_dialogs import QualityDialog
from gui.core import TermInjector, create_default_replacer, SmartTermMatcher
from gui.core import (
    CostAnalyzer, MultiEngineTranslator, AdaptiveMT, ImageTranslator,
    MODEL_PRICING
)
from gui.fault_tolerance import (
    HeartbeatWatchdog, WorkerHeartbeat, APIGuardian,
    FileUnlockManager, SafeShutdownManager, DEFAULT_RETRY_CONFIG
)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


# ============================================================
# 预设模型配置（按供应商分组）- 基于各平台最新 API 文档
# ============================================================
PRESET_MODELS = {
    # ==================== DeepSeek ====================
    "DeepSeek-V4-Pro": {
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1",
        "provider": "DeepSeek",
        "context": "1M",
        "note": "旗舰级，1.6T MoE，49B 激活",
    },
    "DeepSeek-V4-Flash": {
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
        "provider": "DeepSeek",
        "context": "1M",
        "note": "快速模式，284B MoE，13B 激活",
    },
    "DeepSeek-V3-0324": {
        "model": "deepseek-v3-0324",
        "base_url": "https://api.deepseek.com/v1",
        "provider": "DeepSeek",
        "context": "64K",
        "note": "V3 系列稳定版",
    },
    "DeepSeek-R1-0528": {
        "model": "deepseek-r1-0528",
        "base_url": "https://api.deepseek.com/v1",
        "provider": "DeepSeek",
        "context": "64K",
        "note": "R1 推理系列",
    },
    "DeepSeek-V3.1-Terminus": {
        "model": "deepseek-v3.1-terminus",
        "base_url": "https://api.deepseek.com/v1",
        "provider": "DeepSeek",
        "context": "64K",
        "note": "V3.1 终版",
    },
    # ==================== GLM (智谱) ====================
    "GLM-5.2": {
        "model": "glm-5.2",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "1M",
        "note": "最新旗舰，Coding 开源 SOTA",
    },
    "GLM-5.1": {
        "model": "glm-5.1",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "200K",
        "note": "Coding 对齐 Claude Opus 4.6",
    },
    "GLM-5": {
        "model": "glm-5",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "200K",
        "note": "编程对齐 Claude Opus 4.5",
    },
    "GLM-5-Turbo": {
        "model": "glm-5-turbo",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "200K",
        "note": "复杂长任务优化",
    },
    "GLM-4.7": {
        "model": "glm-4.7",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "200K",
        "note": "通用对话/推理/智能体",
    },
    "GLM-4.7-Flash": {
        "model": "glm-4.7-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "200K",
        "note": "轻量高速版本",
    },
    "GLM-4.7-FlashX": {
        "model": "glm-4.7-flashx",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "200K",
        "note": "小尺寸强能力，写作/翻译",
    },
    "GLM-4.6": {
        "model": "glm-4.6",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "200K",
        "note": "高级编码/复杂推理",
    },
    "GLM-4.5-Air": {
        "model": "glm-4.5-air",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "128K",
        "note": "高性价比轻量模型",
    },
    "GLM-4.5-AirX": {
        "model": "glm-4.5-airx",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM",
        "context": "128K",
        "note": "高性价比极速版",
    },
    # === GLM 视觉模型 ===
    "GLM-5V-Turbo": {
        "model": "glm-5v-turbo",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM-Vision",
        "context": "200K",
        "note": "多模态 Coding",
    },
    "GLM-4.6V": {
        "model": "glm-4.6v",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM-Vision",
        "context": "128K",
        "note": "视觉语言模型",
    },
    "GLM-4.6V-FP8": {
        "model": "glm-4.6v-fp8",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM-Vision",
        "context": "128K",
        "note": "视觉模型量化版",
    },
    "GLM-4.1V-Thinking": {
        "model": "glm-4.1v-thinking",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM-Vision",
        "context": "128K",
        "note": "视觉推理模型",
    },
    "GLM-OCR": {
        "model": "glm-ocr",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "provider": "GLM-Vision",
        "context": "128K",
        "note": "OCR 专用模型",
    },
    # ==================== Kimi (月之暗面) ====================
    "Kimi-K3": {
        "model": "kimi-k3",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "1M",
        "note": "旗舰，2.8T 参数，原生视觉",
    },
    "Kimi-K2.7-Code": {
        "model": "kimi-k2.7-code",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "256K",
        "note": "Coding 模型，长上下文指令遵循",
    },
    "Kimi-K2.7-Code-Highspeed": {
        "model": "kimi-k2.7-code-highspeed",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "256K",
        "note": "高速版，~180 Tokens/s",
    },
    "Kimi-K2.6": {
        "model": "kimi-k2.6",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "256K",
        "note": "视觉+文本，思考/非思考模式",
    },
    "Moonshot-V1-8K": {
        "model": "moonshot-v1-8k",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "8K",
        "note": "短文本生成",
    },
    "Moonshot-V1-32K": {
        "model": "moonshot-v1-32k",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "32K",
        "note": "长文本生成",
    },
    "Moonshot-V1-128K": {
        "model": "moonshot-v1-128k",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "128K",
        "note": "超长文本生成",
    },
    "Moonshot-V1-8K-Vision": {
        "model": "moonshot-v1-8k-vision-preview",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "8K",
        "note": "视觉模型",
    },
    "Moonshot-V1-32K-Vision": {
        "model": "moonshot-v1-32k-vision-preview",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "32K",
        "note": "视觉模型",
    },
    "Moonshot-V1-128K-Vision": {
        "model": "moonshot-v1-128k-vision-preview",
        "base_url": "https://api.moonshot.cn/v1",
        "provider": "Kimi",
        "context": "128K",
        "note": "视觉模型",
    },
    # ==================== OpenAI ====================
    "GPT-5.6-Sol": {
        "model": "gpt-5.6-sol",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "1M",
        "note": "旗舰，复杂推理与编码",
    },
    "GPT-5.6-Terra": {
        "model": "gpt-5.6-terra",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "1M",
        "note": "均衡，智能与成本平衡",
    },
    "GPT-5.6-Luna": {
        "model": "gpt-5.6-luna",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "1M",
        "note": "轻量，成本敏感高吞吐",
    },
    "GPT-5.5-Pro": {
        "model": "gpt-5.5-pro",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "1M",
        "note": "专业版",
    },
    "GPT-5.4-Mini": {
        "model": "gpt-5.4-mini",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "512K",
        "note": "小型模型",
    },
    "GPT-5.4-Nano": {
        "model": "gpt-5.4-nano",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "256K",
        "note": "纳米级模型",
    },
    "GPT-5.3-Codex": {
        "model": "gpt-5.3-codex",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "1M",
        "note": "最强 Agentic 编码模型",
    },
    "GPT-5.2-Codex": {
        "model": "gpt-5.2-codex",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "1M",
        "note": "编码模型",
    },
    "O3-Pro": {
        "model": "o3-pro",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "200K",
        "note": "最强推理模型",
    },
    "GPT-4.1": {
        "model": "gpt-4.1",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "1M",
        "note": "最强非推理模型",
    },
    "GPT-4.1-Mini": {
        "model": "gpt-4.1-mini",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "512K",
        "note": "小型快速版本",
    },
    "GPT-4o": {
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "128K",
        "note": "快速智能 GPT",
    },
    "GPT-4o-Mini": {
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "provider": "OpenAI",
        "context": "128K",
        "note": "小型专注模型",
    },
    # ==================== 通义千问 (阿里) ====================
    "Qwen3-Max": {
        "model": "qwen3-max",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "256K",
        "note": "通用旗舰，推理能力最强",
    },
    "Qwen3.7-Max": {
        "model": "qwen3.7-max",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "256K",
        "note": "推荐模型",
    },
    "Qwen3.8-Max": {
        "model": "qwen3.8-max",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "256K",
        "note": "原生视觉语言旗舰",
    },
    "Qwen3.7-Plus": {
        "model": "qwen3.7-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "1M",
        "note": "推荐模型",
    },
    "Qwen-Plus": {
        "model": "qwen-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "1M",
        "note": "性价比之王，日常通用",
    },
    "Qwen3.6-Plus-Preview": {
        "model": "qwen3.6-plus-preview",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "1M",
        "note": "Agent/长上下文，最新预览",
    },
    "Qwen3.5-Plus": {
        "model": "qwen3.5-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "1M",
        "note": "通用模型",
    },
    "Qwen3.5-397B-A17B": {
        "model": "qwen3.5-397b-a17b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "256K",
        "note": "视觉-语言多模态旗舰",
    },
    "Qwen3.5-122-A10B": {
        "model": "qwen3.5-122-a10b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "中型尺寸",
    },
    "Qwen3.5-35B-A3B": {
        "model": "qwen3.5-35b-a3b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "中型尺寸",
    },
    "Qwen3.5-27B": {
        "model": "qwen3.5-27b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "262K",
        "note": "中型尺寸",
    },
    "Qwen3.5-9B": {
        "model": "qwen3.5-9b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "小尺寸",
    },
    "Qwen3.5-4B": {
        "model": "qwen3.5-4b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "小尺寸",
    },
    "Qwen3.5-2B": {
        "model": "qwen3.5-2b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "小尺寸",
    },
    "Qwen3.5-0.8B": {
        "model": "qwen3.5-0.8b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "小尺寸",
    },
    "Qwen-Flash": {
        "model": "qwen-flash",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "1M",
        "note": "极速响应，轻量任务",
    },
    "Qwen3.6-Flash": {
        "model": "qwen3.6-flash",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "1M",
        "note": "推荐轻量模型",
    },
    "Qwen-Turbo": {
        "model": "qwen-turbo",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "轻量极速版本",
    },
    "Qwen-Long": {
        "model": "qwen-long",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "10M",
        "note": "超长文本",
    },
    "Qwen3-Coder-Next": {
        "model": "qwen3-coder-next",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "256K",
        "note": "代码专精，仓库级理解",
    },
    "Qwen-Coder": {
        "model": "qwen-coder",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "代码专项模型",
    },
    "Qwen-VL": {
        "model": "qwen-vl",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "视觉语言模型",
    },
    "Qwen3-VL-235B": {
        "model": "qwen3-vl-235b",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "顶级视觉+语言",
    },
    "Qwen2.5-VL-72B-Instruct": {
        "model": "qwen2.5-vl-72b-instruct",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "视觉语言模型",
    },
    "Qwen-Omni": {
        "model": "qwen-omni",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "全模态模型",
    },
    "Qwen2.5-Omni": {
        "model": "qwen2.5-omni",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "音视频多模态",
    },
    "Qwen-Math": {
        "model": "qwen-math",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "数学推理模型",
    },
    "Qwen-Image-3.0": {
        "model": "qwen-image-3.0",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "图像生成模型",
    },
    "Qwen-Image-3.0-Pro": {
        "model": "qwen-image-3.0-pro",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "provider": "Qwen",
        "context": "128K",
        "note": "图像生成专业版",
    },
    # ==================== LongCat (美团) ====================
    "LongCat-2.0": {
        "model": "LongCat-2.0",
        "base_url": "https://api.longcat.chat/openai/v1",
        "provider": "LongCat",
        "context": "1M",
        "note": "1.6T MoE，Agentic Coding 旗舰",
    },
    # ==================== 自定义 ====================
    "自定义": {
        "model": "",
        "base_url": "",
        "provider": "Custom",
        "context": "",
        "note": "手动配置 OpenAI 兼容端点",
    },
}

# 供应商列表（用于筛选）
PROVIDERS = ["全部", "DeepSeek", "GLM", "GLM-Vision", "Kimi", "OpenAI", "Qwen", "LongCat", "自定义"]

# 默认 API Key 存储（按供应商）
PROVIDER_API_KEYS = {}

# 翻译阶段名称映射（用于进度显示）
TRANSLATION_STAGES = {
    # 内部阶段
    "init": "初始化",
    "loading_model": "加载模型",
    "translating": "翻译中",
    "finish": "完成",
    # BabelDOC 阶段
    "Parse PDF and Create Intermediate Representation": "解析 PDF 结构",
    "DetectScannedFile": "检测扫描文件",
    "LayoutParser": "分析页面布局",
    "TableParser": "解析表格",
    "ParagraphFinder": "识别段落",
    "StylesAndFormulas": "处理样式与公式",
    "AutomaticTermExtractor": "提取术语表",
    "ILTranslator": "翻译内容",
    "Typesetting": "排版处理",
    "FontMapper": "字体映射",
    "PDFCreater": "生成 PDF",
    "SUBSET_FONT_STAGE_NAME": "字体子集化",
    "SAVE_PDF_STAGE_NAME": "保存 PDF",
}

# 语言选项
LANGUAGES = {
    "自动检测": "auto",
    "中文": "zh",
    "English": "en",
    "日本語": "ja",
    "한국어": "ko",
    "Français": "fr",
    "Deutsch": "de",
    "Español": "es",
    "Русский": "ru",
}


class TranslationWorker(QThread):
    """翻译工作线程 - 增强版，支持术语替换、心跳、容错"""
    # 信号定义
    progress_updated = pyqtSignal(str, int)  # 进度文本, 进度百分比
    stage_changed = pyqtSignal(str, str)     # 阶段名称(中文), 阶段描述
    log_message = pyqtSignal(str)
    token_updated = pyqtSignal(int, int, int)  # prompt_tokens, completion_tokens, total_tokens
    time_updated = pyqtSignal(float, float)    # 已用时间(秒), 预估剩余时间(秒)
    term_replaced = pyqtSignal(int)            # 术语替换数量
    heartbeat = pyqtSignal()                   # 心跳信号（防假死）
    retry_happened = pyqtSignal(int, float, str)  # 重试信号（次数, 延迟, 错误）
    finished_success = pyqtSignal(str, dict)   # 输出文件路径, 统计信息
    finished_error = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self._is_cancelled = False
        self._start_time = 0
        self._stage_start_time = 0
        self._current_stage = ""
        # 术语替换相关
        self._enable_term_replacement = config.get("enable_term_replacement", False)
        self._glossary_terms = config.get("glossary_terms", [])
        self._term_replacer = create_default_replacer()
        self._term_injector = TermInjector()
        self._smart_matcher = SmartTermMatcher()
        # 容错机制
        self._heartbeat = WorkerHeartbeat(interval=3.0)
        self._heartbeat.connect(self.heartbeat)
        self._api_guardian = APIGuardian()
        # 高级功能
        self._enable_multi_engine = config.get("enable_multi_engine", False)
        self._multi_strategy = config.get("multi_engine_strategy", "balanced")
        self._multi_model2 = config.get("multi_engine_model2", "glm-4-air")
        self._enable_adaptive_mt = config.get("enable_adaptive_mt", True)
        self._enable_ocr = config.get("enable_ocr", True)
        # 自适应 MT
        self._amt = AdaptiveMT() if self._enable_adaptive_mt else None
        # 成本分析
        self._cost_analyzer = CostAnalyzer()
        # 翻译统计
        self._model_name = config.get("model", "unknown")

    def cancel(self):
        self._is_cancelled = True

    def _translate_stage(self, stage_name: str) -> str:
        """将英文阶段名称翻译为中文"""
        return TRANSLATION_STAGES.get(stage_name, stage_name)

    def _format_time(self, seconds: float) -> str:
        """格式化时间显示"""
        if seconds < 60:
            return f"{int(seconds)}秒"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}分{secs}秒"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}时{minutes}分"

    def _check_resume_translation(self):
        """探针 5 阶段加固：断点续翻检查。

        扫描 output 目录，若已有同名翻译结果 PDF，说明上次翻译中断。
        BabelDOC 自带句对级 cache（cache.py），重启后相同句对会从缓存读取，
        此处仅做日志提示与页面级跳过预检。
        """
        try:
            from pathlib import Path

            output_dir = self.config.get("output_dir")
            if not output_dir:
                return

            output_path = Path(output_dir)
            if not output_path.exists():
                return

            input_file = Path(self.config["input_file"])
            input_stem = input_file.stem
            lang_out = self.config.get("lang_out", "zh")

            # BabelDOC 输出命名模式：{stem}.{lang_out}.pdf / {stem}.dual.pdf
            expected_patterns = [
                f"{input_stem}.{lang_out}.pdf",
                f"{input_stem}.dual.pdf",
                f"{input_stem}.mono.pdf",
            ]

            existing_results = []
            for pattern in expected_patterns:
                candidate = output_path / pattern
                if candidate.exists():
                    existing_results.append(candidate)

            if existing_results:
                self.log_message.emit(
                    f"📦 检测到已有翻译结果 {len(existing_results)} 个文件，"
                    "将利用缓存断点续翻（句对级缓存自动生效）"
                )
                for r in existing_results:
                    self.log_message.emit(f"  已存在: {r.name} ({r.stat().st_size // 1024} KB)")
            else:
                self.log_message.emit("首次翻译，无历史缓存")

        except Exception as e:
            # 断点续翻检查失败不应阻断翻译流程
            self.log_message.emit(f"断点续翻检查跳过: {e}")

    def run(self):
        import time
        import traceback
        import threading
        self._start_time = time.monotonic()

        # 独立心跳线程：确保长 API 调用期间看门狗不会误判超时
        self._heartbeat_active = True
        def _heartbeat_thread():
            while self._heartbeat_active:
                time.sleep(30)
                if self._heartbeat_active:
                    self.heartbeat.emit()
        heartbeat_thread = threading.Thread(target=_heartbeat_thread, daemon=True)
        heartbeat_thread.start()

        try:
            self.log_message.emit("=" * 50)
            self.log_message.emit("正在初始化翻译器...")
            self.progress_updated.emit("初始化翻译器...", 1)
            self.stage_changed.emit("init", "初始化...")

            # 验证输入文件存在
            if not self.config.get("input_file"):
                self.finished_error.emit("未选择输入文件")
                return
            if not Path(self.config["input_file"]).exists():
                self.finished_error.emit(f"输入文件不存在: {self.config['input_file']}")
                return

            # 验证 API Key
            if not self.config.get("api_key"):
                self.finished_error.emit("API Key 为空")
                return

            # 创建翻译器
            translator = OpenAITranslator(
                lang_in=self.config["lang_in"],
                lang_out=self.config["lang_out"],
                model=self.config["model"],
                base_url=self.config["base_url"],
                api_key=self.config["api_key"],
            )

            # 配置术语替换
            glossary_terms = self.config.get("glossary_terms", [])
            if self._enable_term_replacement and glossary_terms:
                # 保存原始 prompt 方法
                original_prompt = translator.prompt

                # 构建术语提示
                term_hint = self._term_injector.build_term_hint(glossary_terms, max_terms=15)

                # 包装 prompt 方法，添加术语指导
                def enhanced_prompt(text, _original=original_prompt, _hint=term_hint):
                    messages = _original(text)
                    # 在 system prompt 中添加术语指导
                    if _hint and messages:
                        messages[0]["content"] += _hint
                    return messages

                translator.prompt = enhanced_prompt

                # 保存原始 translate 方法
                original_translate = translator.translate

                # 包装 translate 方法，后处理术语
                def enhanced_translate(text, _original=original_translate,
                                       _terms=glossary_terms,
                                       _replacer=self._term_replacer):
                    # 翻译前：替换术语为占位符
                    pre_processed = _replacer.pre_translate(text, _terms)

                    # 执行翻译
                    translated = _replacer.post_translate(_original(pre_processed))

                    return translated

                # 注意：这里不覆盖 translate，因为 BabelDOC 内部调用的是 do_translate
                # 我们在 do_translate 层面处理
                original_do_translate = translator.do_translate

                def enhanced_do_translate(text, rate_limit_params=None,
                                          _original=original_do_translate,
                                          _terms=glossary_terms,
                                          _replacer=self._term_replacer,
                                          _self=self):
                    # 翻译前：替换术语为占位符
                    pre_processed = _replacer.pre_translate(text, _terms)

                    # 执行翻译
                    translated = _original(pre_processed, rate_limit_params)

                    # 翻译后：还原占位符为术语翻译
                    result = _replacer.post_translate(translated)

                    # 发送替换数量信号
                    count = _replacer.get_replacement_count()
                    if count > 0:
                        _self.term_replaced.emit(count)

                    return result

                translator.do_translate = enhanced_do_translate

                self.log_message.emit(f"术语替换已启用: {len(glossary_terms)} 条术语")
            else:
                if not glossary_terms:
                    self.log_message.emit("术语库为空，跳过术语替换")
                else:
                    self.log_message.emit("术语替换已禁用")

            # 配置自适应 MT
            if self._enable_adaptive_mt and self._amt:
                adaptive_addon = self._amt.get_adaptive_prompt_addon(
                    self.config["lang_in"], self.config["lang_out"],
                    self.config["model"]
                )
                if adaptive_addon:
                    # 保存原始 prompt 方法
                    orig_prompt = translator.prompt

                    def enhanced_prompt_with_amt(text, _orig=orig_prompt, _addon=adaptive_addon):
                        messages = _orig(text)
                        if messages:
                            messages[0]["content"] += _addon
                        return messages

                    translator.prompt = enhanced_prompt_with_amt
                    amt_stats = self._amt.get_stats()
                    self.log_message.emit(f"自适应学习已启用: {amt_stats['total_rules']} 条规则")

            self.log_message.emit(f"翻译器就绪: {self.config['model']}")
            self.log_message.emit(f"语言: {self.config['lang_in']} → {self.config['lang_out']}")
            self.progress_updated.emit("初始化完成...", 3)
            self.stage_changed.emit("init", "初始化完成")
            self._heartbeat.beat()

            # 导入 BabelDOC 核心模块
            self.log_message.emit("导入 BabelDOC 核心模块...")
            from babeldoc.format.pdf.high_level import async_translate
            from babeldoc.format.pdf.translation_config import TranslationConfig
            from babeldoc.docvision.doclayout import DocLayoutModel

            self.log_message.emit("加载文档布局模型...")
            self.progress_updated.emit("加载布局模型...", 5)
            self.stage_changed.emit("loading_model", "加载布局模型...")
            self._heartbeat.beat()

            # 加载布局模型（可能耗时较长）
            try:
                doc_layout_model = DocLayoutModel.load_onnx()
                self.log_message.emit("布局模型加载完成")
                self._heartbeat.beat()
            except Exception as e:
                self.log_message.emit(f"布局模型加载失败: {e}")
                self.finished_error.emit(f"无法加载文档布局模型: {e}")
                return

            self.log_message.emit(f"开始翻译: {Path(self.config['input_file']).name}")
            self.progress_updated.emit("开始翻译...", 8)
            self.stage_changed.emit("translating", "翻译中...")
            self._heartbeat.beat()

            # 探针 5 阶段加固：断点续翻检查
            # 扫描 output 目录，若已有翻译结果则利用 BabelDOC 句对缓存续翻
            self._check_resume_translation()

            # 创建翻译配置
            translation_config = TranslationConfig(
                translator=translator,
                input_file=self.config["input_file"],
                lang_in=self.config["lang_in"],
                lang_out=self.config["lang_out"],
                doc_layout_model=doc_layout_model,
                pages=self.config.get("pages"),
                output_dir=self.config.get("output_dir"),
                no_dual=self.config.get("no_dual", False),
                no_mono=self.config.get("no_mono", False),
                qps=self.config.get("qps", 4),
                # OCR 配置
                ocr_workaround=self.config.get("enable_ocr", False),
                auto_enable_ocr_workaround=self.config.get("enable_ocr", False),
            )

            # 异步翻译并追踪进度
            import asyncio

            async def run_translation():
                result = None
                last_progress = 8
                stage_progress_map = {}  # 记录每个阶段的进度

                async for event in async_translate(translation_config):
                    if self._is_cancelled:
                        return None

                    # 发送心跳（防假死）- 直接发射信号
                    self.heartbeat.emit()

                    event_type = event.get("type", "")
                    now = time.monotonic()
                    elapsed = now - self._start_time

                    if event_type == "progress_start":
                        stage_name = event.get("stage", "")
                        self._current_stage = stage_name
                        self._stage_start_time = now
                        stage_cn = self._translate_stage(stage_name)
                        desc = f"开始: {stage_cn}"
                        self.stage_changed.emit(stage_name, desc)
                        self.log_message.emit(f"▶ {stage_cn}")

                    elif event_type == "progress_update":
                        stage_progress = event.get("stage_progress", 0)  # 0-100 百分比
                        stage_name = event.get("stage", "")
                        stage_cn = self._translate_stage(stage_name)

                        # 计算整体进度 (8% - 95%)
                        overall = int(8 + stage_progress * 0.87)
                        overall = min(overall, 95)
                        overall = max(overall, last_progress)
                        last_progress = overall

                        # 计算预估时间
                        if stage_progress > 0:
                            stage_elapsed = now - self._stage_start_time
                            stage_remaining = stage_elapsed * (100 - stage_progress) / stage_progress
                            # 简单估算：假设剩余阶段按当前速度
                            total_estimate = elapsed + stage_remaining * 3
                            remaining = max(0, total_estimate - elapsed)
                            self.time_updated.emit(elapsed, remaining)

                        self.progress_updated.emit(stage_cn, overall)

                    elif event_type == "progress_end":
                        stage_name = event.get("stage", "")
                        stage_cn = self._translate_stage(stage_name)
                        stage_elapsed = now - self._stage_start_time
                        self.stage_changed.emit(stage_name, f"完成: {stage_cn}")
                        self.log_message.emit(f"✓ {stage_cn} ({self._format_time(stage_elapsed)})")

                        # 发送 Token 统计
                        if hasattr(translator, 'token_count'):
                            self.token_updated.emit(
                                translator.prompt_token_count.value,
                                translator.completion_token_count.value,
                                translator.token_count.value,
                            )

                    elif event_type == "finish":
                        result = event.get("result")

                    elif event_type == "error":
                        error_obj = event.get("error", "未知错误")
                        error_msg = str(error_obj) if not isinstance(error_obj, str) else error_obj
                        self.finished_error.emit(error_msg)
                        return None

                return result

            # 运行异步翻译
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(run_translation())
                loop.close()
            except Exception as e:
                self.log_message.emit(f"翻译过程异常: {e}")
                self.finished_error.emit(f"翻译失败: {e}")
                return

            if self._is_cancelled:
                self.log_message.emit("翻译已取消")
                return

            if result:
                self.progress_updated.emit("翻译完成!", 100)
                self.stage_changed.emit("finish", "翻译完成!")

                # 收集统计信息
                stats = {
                    "total_time": time.monotonic() - self._start_time,
                    "prompt_tokens": translator.prompt_token_count.value,
                    "completion_tokens": translator.completion_token_count.value,
                    "total_tokens": translator.token_count.value,
                    "model": self.config.get("model", "unknown"),
                }

                # 获取输出文件路径
                output_path = None
                if hasattr(result, 'dual_pdf_path') and result.dual_pdf_path:
                    output_path = str(result.dual_pdf_path)
                elif hasattr(result, 'mono_pdf_path') and result.mono_pdf_path:
                    output_path = str(result.mono_pdf_path)

                # 输出最终统计
                self.log_message.emit("=" * 50)
                self.log_message.emit(f"翻译完成! 总耗时: {self._format_time(stats['total_time'])}")
                self.log_message.emit(f"Token 使用: prompt={stats['prompt_tokens']}, completion={stats['completion_tokens']}, total={stats['total_tokens']}")

                if hasattr(result, 'total_valid_character_count') and result.total_valid_character_count:
                    self.log_message.emit(f"翻译字符数: {result.total_valid_character_count}")

                self.finished_success.emit(output_path or "翻译完成", stats)
            else:
                self.finished_error.emit("翻译结果为空")

        except Exception as e:
            # 捕获完整异常信息，避免闪退
            import traceback
            error_detail = traceback.format_exc()
            error_msg = f"{type(e).__name__}: {str(e)}"
            # 发送详细错误日志
            self.log_message.emit(f"❌ 翻译异常:\n{error_detail}")
            self.finished_error.emit(error_msg)


class ApiVerifyWorker(QThread):
    """API 验证工作线程（异步，不阻塞 UI）"""
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)

    def __init__(self, api_key, base_url, model):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def run(self):
        try:
            translator = OpenAITranslator(
                lang_in="en",
                lang_out="zh",
                model=self.model,
                base_url=self.base_url,
                api_key=self.api_key,
            )
            result = translator.translate("Hello, world!")
            self.finished_ok.emit(result)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {str(e)}")


class MainWindow(QMainWindow):
    """BabelDOC PDF 翻译工具主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BabelDOC PDF 翻译工具")
        
        # 响应式窗口大小：默认为屏幕的 70%
        from PyQt6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().availableGeometry()
        default_w = min(int(screen.width() * 0.7), 1200)
        default_h = min(int(screen.height() * 0.8), 900)
        self.setMinimumSize(600, 500)
        self.resize(default_w, default_h)

        self.input_file = None
        self.output_dir = None
        self.worker = None
        self.settings_file = PROJECT_ROOT / "gui_settings.json"
        self._pdf_page_count = 0


        # 加载已保存的供应商 API Key
        self._load_provider_keys()

        self._setup_ui()
        self._load_settings()
        self._update_adaptive_stats()

    def _update_adaptive_stats(self):
        """更新自适应学习统计标签"""
        try:
            amt = AdaptiveMT()
            stats = amt.get_stats()
            if hasattr(self, 'amt_label'):
                self.amt_label.setText(f"已学习: {stats['total_rules']} 条规则")
        except Exception:
            pass

    def _setup_ui(self):
        # 使用 QScrollArea 实现内容区域可滚动，适配小屏幕
        from PyQt6.QtWidgets import QScrollArea
        
        # 中央部件
        central = QWidget()
        self.setCentralWidget(central)
        
        # 主布局
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # 滚动内容部件
        scroll_content = QWidget()
        scroll.setWidget(scroll_content)
        
        main_layout = QVBoxLayout(scroll_content)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ---- 模型配置区域 ----
        main_layout.addWidget(self._create_model_group())

        # ---- 翻译设置区域 ----
        main_layout.addWidget(self._create_settings_group())

        # ---- 文件处理区域 ----
        main_layout.addWidget(self._create_file_group())

        # ---- 高级功能区域 ----
        main_layout.addWidget(self._create_advanced_group())

        # ---- 进度和日志区域（固定底部，不随滚动）----
        # 从主布局中移除，放在滚动区域下方
        main_layout.addStretch()  # 弹性空间

        outer_layout.addWidget(scroll, 1)  # 滚动区域占主要空间
        
        # 底部固定区域（进度+按钮）
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(12, 6, 12, 12)
        bottom_layout.setSpacing(6)
        bottom_layout.addWidget(self._create_progress_group())
        bottom_layout.addWidget(self._create_button_bar())
        outer_layout.addWidget(bottom_widget)

        # 设置样式
        self._apply_styles()

    def _create_model_group(self) -> QGroupBox:
        group = QGroupBox("模型配置")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 第一行：供应商筛选 + 模型选择
        select_row = QHBoxLayout()
        select_row.setSpacing(6)
        select_row.addWidget(QLabel("供应商:"))

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(PROVIDERS)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.provider_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        select_row.addWidget(self.provider_combo, 1)

        select_row.addWidget(QLabel("选择模型:"))

        self.model_combo = QComboBox()
        self.model_combo.addItems(list(PRESET_MODELS.keys()))

        self.model_combo.setMaxVisibleItems(20)
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        select_row.addWidget(self.model_combo, 2)

        # 添加/删除自定义模型按钮
        self.add_model_btn = QPushButton("+")
        self.add_model_btn.setFixedWidth(24)
        self.add_model_btn.setToolTip("添加当前配置为自定义模型")
        self.add_model_btn.clicked.connect(self._add_custom_model)
        select_row.addWidget(self.add_model_btn)

        self.del_model_btn = QPushButton("-")
        self.del_model_btn.setFixedWidth(24)
        self.del_model_btn.setToolTip("删除选中的自定义模型")
        self.del_model_btn.clicked.connect(self._remove_custom_model)
        select_row.addWidget(self.del_model_btn)

        layout.addLayout(select_row)

        # 第二行：API Key
        api_row = QHBoxLayout()
        api_row.setSpacing(6)
        api_row.addWidget(QLabel("API Key:"))

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("请输入您的 API Key...")
        self.api_key_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        api_row.addWidget(self.api_key_edit, 1)

        # 显示/隐藏 API Key
        self.show_key_btn = QPushButton("👁")
        self.show_key_btn.setFixedWidth(28)
        self.show_key_btn.setCheckable(True)
        self.show_key_btn.toggled.connect(self._toggle_api_key_visibility)
        api_row.addWidget(self.show_key_btn)

        self.verify_btn = QPushButton("验证")
        self.verify_btn.setFixedWidth(50)
        self.verify_btn.clicked.connect(self._verify_api)
        api_row.addWidget(self.verify_btn)

        layout.addLayout(api_row)

        # 第三行：Base URL + 模型名称
        param_row = QHBoxLayout()
        param_row.setSpacing(6)
        param_row.addWidget(QLabel("Base URL:"))

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1")
        param_row.addWidget(self.base_url_edit, 1)

        param_row.addWidget(QLabel("自定义模型名:"))

        self.model_name_edit = QLineEdit()
        self.model_name_edit.setPlaceholderText("model-name")
        self.model_name_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        param_row.addWidget(self.model_name_edit, 1)

        # 上下文长度显示
        param_row.addWidget(QLabel("上下文:"))
        self.context_label = QLabel("--")
        self.context_label.setStyleSheet("color: #555; font-size: 9pt; padding: 1px 4px; background-color: #f0f0f0; border-radius: 3px;")
        self.context_label.setMinimumWidth(50)
        param_row.addWidget(self.context_label)

        layout.addLayout(param_row)

        # 第四行：API Key 管理（按供应商保存）
        key_mgmt_row = QHBoxLayout()
        key_mgmt_row.setSpacing(6)
        self.save_key_btn = QPushButton("💾 保存 Key")
        self.save_key_btn.setToolTip("保存当前 API Key 到对应供应商")
        self.save_key_btn.clicked.connect(self._save_api_key_for_provider)
        key_mgmt_row.addWidget(self.save_key_btn)

        self.clear_key_btn = QPushButton("🗑 清除")
        self.clear_key_btn.setToolTip("清除当前输入的 API Key")
        self.clear_key_btn.clicked.connect(self._clear_api_key)
        key_mgmt_row.addWidget(self.clear_key_btn)

        key_mgmt_row.addStretch()

        # 显示已保存的 Key 状态
        self.key_status_label = QLabel("")
        self.key_status_label.setStyleSheet("color: #4CAF50; font-size: 8pt;")
        key_mgmt_row.addWidget(self.key_status_label)

        layout.addLayout(key_mgmt_row)
        return group

    def _create_settings_group(self) -> QGroupBox:
        group = QGroupBox("翻译设置")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 第一行：语言选择
        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        lang_row.addWidget(QLabel("源语言:"))
        self.lang_in_combo = QComboBox()
        self.lang_in_combo.addItems(LANGUAGES.keys())
        self.lang_in_combo.setCurrentText("English")
        self.lang_in_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lang_row.addWidget(self.lang_in_combo, 1)

        lang_row.addWidget(QLabel("目标语言:"))
        self.lang_out_combo = QComboBox()
        self.lang_out_combo.addItems(LANGUAGES.keys())
        self.lang_out_combo.setCurrentText("中文")
        self.lang_out_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lang_row.addWidget(self.lang_out_combo, 1)
        layout.addLayout(lang_row)

        # 第二行：页面范围 + 输出选项
        opt_row = QHBoxLayout()
        opt_row.setSpacing(6)
        opt_row.addWidget(QLabel("页面:"))
        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText("留空=全部, 如: 1-10,15")
        self.pages_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        opt_row.addWidget(self.pages_edit, 1)

        self.dual_checkbox = QCheckBox("双语")
        self.dual_checkbox.setChecked(True)
        opt_row.addWidget(self.dual_checkbox)

        self.mono_checkbox = QCheckBox("纯译文")
        self.mono_checkbox.setChecked(True)
        opt_row.addWidget(self.mono_checkbox)

        opt_row.addStretch()
        layout.addLayout(opt_row)
        return group

    def _create_advanced_group(self) -> QGroupBox:
        """创建高级功能设置区域"""
        group = QGroupBox("高级功能")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # === 第一行：成本分析 ===
        cost_row = QHBoxLayout()
        cost_row.setSpacing(4)
        cost_row.addWidget(QLabel("💰:"))

        self.cost_estimate_label = QLabel("未估算")
        self.cost_estimate_label.setStyleSheet("""
            color: #E65100; font-weight: bold; font-size: 8pt;
            padding: 2pt 6pt; background-color: #FFF3E0; border-radius: 3px;
        """)
        cost_row.addWidget(self.cost_estimate_label)

        self.cost_estimate_btn = QPushButton("估算")
        self.cost_estimate_btn.setFixedWidth(45)
        self.cost_estimate_btn.clicked.connect(self._estimate_translation_cost)
        cost_row.addWidget(self.cost_estimate_btn)

        self.cost_compare_btn = QPushButton("对比")
        self.cost_compare_btn.setFixedWidth(45)
        self.cost_compare_btn.clicked.connect(self._show_cost_comparison)
        cost_row.addWidget(self.cost_compare_btn)

        self.cost_report_btn = QPushButton("报告")
        self.cost_report_btn.setFixedWidth(45)
        self.cost_report_btn.clicked.connect(self._show_cost_report)
        cost_row.addWidget(self.cost_report_btn)

        cost_row.addStretch()
        layout.addLayout(cost_row)

        # === 第二行：多引擎对比 ===
        multi_row = QHBoxLayout()
        multi_row.setSpacing(4)
        multi_row.addWidget(QLabel("🔄:"))

        self.multi_engine_check = QCheckBox("多引擎")
        self.multi_engine_check.setToolTip("同时使用多个模型翻译，选择最佳结果")
        multi_row.addWidget(self.multi_engine_check)

        multi_row.addWidget(QLabel("策略:"))
        self.multi_strategy_combo = QComboBox()
        self.multi_strategy_combo.addItems(["balanced", "quality", "cost", "latency"])
        self.multi_strategy_combo.setCurrentText("balanced")
        self.multi_strategy_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        multi_row.addWidget(self.multi_strategy_combo, 1)

        layout.addLayout(multi_row)

        # 对比模型行
        multi_model_row = QHBoxLayout()
        multi_model_row.setSpacing(4)
        multi_model_row.addWidget(QLabel("对比模型:"))
        self.multi_model2_combo = QComboBox()
        self.multi_model2_combo.addItems([
            "deepseek-chat", "glm-4-air", "glm-4", "gpt-4o-mini",
            "moonshot-v1-8k", "qwen-plus", "qwen-turbo"
        ])
        self.multi_model2_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        multi_model_row.addWidget(self.multi_model2_combo, 1)
        layout.addLayout(multi_model_row)

        # === 第三行：自适应 MT ===
        amt_row = QHBoxLayout()
        amt_row.setSpacing(4)
        amt_row.addWidget(QLabel("🧠:"))

        self.amt_check = QCheckBox("自适应")
        self.amt_check.setToolTip("从用户反馈中学习翻译风格，越用越准")
        self.amt_check.setChecked(True)
        amt_row.addWidget(self.amt_check)

        self.amt_rules_btn = QPushButton("规则")
        self.amt_rules_btn.setFixedWidth(45)
        self.amt_rules_btn.clicked.connect(self._show_adaptive_rules)
        amt_row.addWidget(self.amt_rules_btn)

        self.amt_stats_btn = QPushButton("统计")
        self.amt_stats_btn.setFixedWidth(45)
        self.amt_stats_btn.clicked.connect(self._show_adaptive_stats)
        amt_row.addWidget(self.amt_stats_btn)

        self.amt_label = QLabel("已学习: 0 条")
        self.amt_label.setStyleSheet("color: #666; font-size: 8pt;")
        amt_row.addWidget(self.amt_label)

        amt_row.addStretch()
        layout.addLayout(amt_row)

        # === 第四行：OCR / 扫描件处理 ===
        ocr_row = QHBoxLayout()
        ocr_row.setSpacing(4)
        ocr_row.addWidget(QLabel("📷:"))

        self.ocr_check = QCheckBox("OCR")
        self.ocr_check.setToolTip(
            "启用 OCR 扫描件翻译。\n"
            "对应 BabelDOC 参数: config.ocr_workaround = True\n"
            "使用 PaddleOCR/Tesseract 识别扫描版 PDF"
        )
        self.ocr_check.setChecked(False)
        self.ocr_check.toggled.connect(self._on_ocr_toggled)
        ocr_row.addWidget(self.ocr_check)

        # 视觉模型选择
        ocr_row.addWidget(QLabel("模型:"))
        self.ocr_model_combo = QComboBox()
        self.ocr_model_combo.addItems([
            "glm-4.6v",
            "glm-4.1v-flashx",
            "kimi-vision",
        ])
        self.ocr_model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ocr_model_combo.setEnabled(False)
        self.ocr_model_combo.setToolTip(
            "选择用于 OCR 的视觉模型。\n"
            "GLM-4.6V: 视觉推理增强，支持工具调用\n"
            "GLM-4.1V: 轻量视觉推理，适合高并发\n"
            "Kimi Vision: 支持图片理解"
        )
        ocr_row.addWidget(self.ocr_model_combo, 1)

        self.ocr_status_label = QLabel("未启用")
        self.ocr_status_label.setStyleSheet("""
            color: #999; font-size: 11px; padding: 2px 6px;
            background-color: #F5F5F5; border-radius: 3px;
        """)
        ocr_row.addWidget(self.ocr_status_label)

        self.ocr_test_btn = QPushButton("检测扫描件")
        self.ocr_test_btn.setFixedWidth(90)
        self.ocr_test_btn.clicked.connect(self._test_ocr_detection)
        ocr_row.addWidget(self.ocr_test_btn)

        ocr_row.addStretch()
        layout.addLayout(ocr_row)

        # === 第五行：图片/表格处理提示 ===
        info_row = QHBoxLayout()
        info_icon = QLabel("ℹ️")
        info_row.addWidget(info_icon)

        info_label = QLabel(
            "图片/表格由 BabelDOC 自动处理排版 | "
            "请勿在翻译前将 PDF 转为图片 | "
            "复杂图表建议使用视觉模型补充描述"
        )
        info_label.setStyleSheet("""
            color: #1976D2; font-size: 10px;
            padding: 3px 8px; background-color: #E3F2FD;
            border-radius: 3px;
        """)
        info_label.setWordWrap(True)
        info_row.addWidget(info_label, 1)

        layout.addLayout(info_row)

        return group

    def _on_ocr_toggled(self, checked: bool):
        """OCR 开关变化"""
        self.ocr_model_combo.setEnabled(checked)
        if checked:
            self.ocr_status_label.setText("已启用")
            self.ocr_status_label.setStyleSheet("""
                color: #4CAF50; font-weight: bold; font-size: 11px;
                padding: 2px 6px; background-color: #E8F5E9; border-radius: 3px;
            """)
        else:
            self.ocr_status_label.setText("未启用")
            self.ocr_status_label.setStyleSheet("""
                color: #999; font-size: 11px; padding: 2px 6px;
                background-color: #F5F5F5; border-radius: 3px;
            """)

    def _create_file_group(self) -> QGroupBox:
        group = QGroupBox("文件处理")
        group.setAcceptDrops(True)
        layout = QVBoxLayout(group)

        # 拖拽区域
        self.drop_frame = QFrame()
        self.drop_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        self.drop_frame.setMinimumHeight(80)
        self.drop_frame.setAcceptDrops(True)
        self.drop_frame.dragEnterEvent = self._on_drag_enter
        self.drop_frame.dropEvent = self._on_drop

        drop_layout = QVBoxLayout(self.drop_frame)
        self.drop_label = QLabel("📄 拖拽 PDF 文件到这里")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet("font-size: 14px; color: #888;")
        drop_layout.addWidget(self.drop_label)

        self.file_info_label = QLabel("")
        self.file_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.file_info_label)

        layout.addWidget(self.drop_frame)

        # 浏览按钮行
        btn_row = QHBoxLayout()
        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.clicked.connect(self._browse_file)
        btn_row.addWidget(self.browse_btn)

        self.output_dir_btn = QPushButton("选择输出目录...")
        self.output_dir_btn.clicked.connect(self._browse_output_dir)
        btn_row.addWidget(self.output_dir_btn)

        self.output_dir_label = QLabel("默认: 同输入文件目录")
        self.output_dir_label.setStyleSheet("color: #666;")
        btn_row.addWidget(self.output_dir_label, 1)

        btn_row.addSpacing(10)

        # QPS 设置（带模型建议）
        btn_row.addWidget(QLabel("QPS:"))
        self.qps_spin = QSpinBox()
        self.qps_spin.setRange(1, 20)
        self.qps_spin.setValue(2)
        self.qps_spin.setToolTip(
            "每秒请求数限制。不同模型建议值：\n"
            "  DeepSeek: 4-10\n"
            "  GLM-4:    3-5（免费版较慢）\n"
            "  Kimi:     5-10\n"
            "  GPT-4o:   2-4（注意 RPM 限制）\n"
            "  免费模型: 1-2"
        )
        btn_row.addWidget(self.qps_spin)

        # QPS 建议标签
        self.qps_tip_label = QLabel("💡 根据模型额度调整")
        self.qps_tip_label.setStyleSheet("color: #999; font-size: 10px;")
        btn_row.addWidget(self.qps_tip_label)

        btn_row.addSpacing(15)

        # 文档领域选择
        btn_row.addWidget(QLabel("领域:"))
        self.domain_combo = QComboBox()
        self.domain_combo.addItem("自动识别", "")
        from gui.core.ai_glossary import get_domains as _get_domains
        for d in _get_domains():
            self.domain_combo.addItem(d, d)
        self.domain_combo.setToolTip("选择文档专业领域以加载对应术语库，或让系统自动识别")
        btn_row.addWidget(self.domain_combo)

        btn_row.addSpacing(10)

        # 术语替换
        self.term_replace_check = QCheckBox("术语替换")
        self.term_replace_check.setToolTip("启用后自动使用术语库替换专业术语")
        self.term_replace_check.setChecked(True)
        btn_row.addWidget(self.term_replace_check)

        # 导入术语库按钮
        self.import_glossary_btn = QPushButton("导入AI术语")
        self.import_glossary_btn.setToolTip("导入预置的 AI/计算机科学术语库")
        self.import_glossary_btn.clicked.connect(self._import_ai_glossary)
        btn_row.addWidget(self.import_glossary_btn)

        layout.addLayout(btn_row)
        return group

    def _create_progress_group(self) -> QGroupBox:
        group = QGroupBox("进度与日志")
        layout = QVBoxLayout(group)
        layout.setSpacing(4)

        # === 进度条 ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat(" %p% ")
        self.progress_bar.setFixedHeight(24)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: center;
                font-size: 9pt;
                font-weight: bold;
                padding: 2px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # === 状态信息行（阶段 + Token + 时间）===
        status_row = QHBoxLayout()
        status_row.setSpacing(4)

        # 当前阶段
        stage_box = QHBoxLayout()
        stage_box.setSpacing(2)
        stage_box.addWidget(QLabel("阶段:"))
        self.stage_label = QLabel("等待开始")
        self.stage_label.setStyleSheet("""
            color: #1976D2; font-weight: bold; font-size: 8pt;
            padding: 1pt 4pt; background-color: #E3F2FD; border-radius: 3px;
        """)
        stage_box.addWidget(self.stage_label)
        stage_box.addStretch()
        status_row.addLayout(stage_box, 2)

        # Token 统计
        token_box = QHBoxLayout()
        token_box.setSpacing(2)
        token_box.addWidget(QLabel("Token:"))
        self.token_label = QLabel("0/0/0")
        self.token_label.setStyleSheet("""
            color: #7B1FA2; font-family: Consolas, monospace; font-size: 8pt;
            padding: 1pt 4pt; background-color: #F3E5F5; border-radius: 3px;
        """)
        token_box.addWidget(self.token_label)
        token_box.addStretch()
        status_row.addLayout(token_box, 1)

        # 时间信息
        time_box = QHBoxLayout()
        time_box.setSpacing(2)
        time_box.addWidget(QLabel("时间:"))
        self.time_label = QLabel("0秒/--")
        self.time_label.setStyleSheet("""
            color: #E65100; font-family: Consolas, monospace; font-size: 8pt;
            padding: 1pt 4pt; background-color: #FFF3E0; border-radius: 3px;
        """)
        time_box.addWidget(self.time_label)
        time_box.addStretch()
        status_row.addLayout(time_box, 1)

        layout.addLayout(status_row)

        # === 详细进度文本 ===
        self.progress_label = QLabel("就绪")
        self.progress_label.setStyleSheet("color: #555; font-size: 11px;")
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)

        # === 分隔线 ===
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)

        # === 日志区域 ===
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(100)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: #fafafa;
            }
        """)
        layout.addWidget(self.log_text)

        return group

    def _create_button_bar(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.start_btn = QPushButton("▶ 开始翻译")
        self.start_btn.setMinimumWidth(100)
        self.start_btn.setMinimumHeight(28)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                font-weight: bold; font-size: 10pt; border-radius: 4px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #ccc; color: #999; }
        """)
        self.start_btn.clicked.connect(self._start_translation)
        layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setMinimumWidth(60)
        self.cancel_btn.setMinimumHeight(28)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_translation)
        layout.addWidget(self.cancel_btn)

        self.open_output_btn = QPushButton("📁 输出目录")
        self.open_output_btn.setMinimumWidth(80)
        self.open_output_btn.setMinimumHeight(28)
        self.open_output_btn.clicked.connect(self._open_output_dir)
        layout.addWidget(self.open_output_btn)

        layout.addStretch()

        # 质量管理按钮
        self.quality_btn = QPushButton("🔍 质量")
        self.quality_btn.setMinimumWidth(60)
        self.quality_btn.setMinimumHeight(28)
        self.quality_btn.setToolTip("翻译记忆库、术语库、QA 检查")
        self.quality_btn.clicked.connect(self._open_quality_dialog)
        layout.addWidget(self.quality_btn)

        # 保存配置按钮
        self.save_btn = QPushButton("💾 保存")
        self.save_btn.setMinimumWidth(60)
        self.save_btn.setMinimumHeight(28)
        self.save_btn.clicked.connect(self._save_settings)
        layout.addWidget(self.save_btn)

        return widget

    def _apply_styles(self):
        # 使用 pt 单位而非 px，自动适配 DPI
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 10pt;
                border: 1px solid #ddd;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 14px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #555;
            }
            QPushButton {
                padding: 5pt 10pt;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: #f8f8f8;
                font-size: 9pt;
                min-height: 18pt;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
                border-color: #aaa;
            }
            QPushButton:pressed {
                background-color: #ddd;
            }
            QPushButton:disabled {
                background-color: #eee;
                color: #999;
            }
            QLineEdit, QSpinBox {
                padding: 4pt;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
                font-size: 9pt;
                min-height: 16pt;
            }
            QComboBox {
                padding: 4pt 24pt 4pt 4pt;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
                font-size: 9pt;
                min-height: 16pt;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #4CAF50;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20pt;
                border: none;
            }
            QComboBox::down-arrow {
                width: 10pt;
                height: 10pt;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                border: 1px solid #ccc;
                selection-background-color: #4CAF50;
                selection-color: white;
                outline: 0;
            }
            QComboBox QAbstractItemView::item {
                min-height: 22px;
                padding: 4px;
            }
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: #fafafa;
                font-size: 9pt;
            }
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: center;
                font-size: 9pt;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
            QLabel {
                color: #333;
                font-size: 9pt;
            }
            QCheckBox {
                font-size: 9pt;
                spacing: 4pt;
            }
            QCheckBox::indicator {
                width: 13pt;
                height: 13pt;
            }
            QScrollBar:vertical {
                width: 12pt;
            }
            QScrollBar:horizontal {
                height: 12pt;
            }
        """)

        # 拖拽区域特殊样式
        self.drop_frame.setStyleSheet("""
            QFrame {
                border: 2px dashed #aaa;
                border-radius: 8px;
                background-color: #fafafa;
                min-height: 60pt;
            }
        """)

    # ============================================================
    # 事件处理
    # ============================================================

    def _on_provider_changed(self, provider: str):
        """供应商筛选变化时更新模型列表"""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()

        # "自定义" 供应商对应 provider 值 "Custom"
        filter_provider = "Custom" if provider == "自定义" else provider

        if provider == "全部":
            self.model_combo.addItems(list(PRESET_MODELS.keys()))
        else:
            for name, config in PRESET_MODELS.items():
                if config.get("provider") == filter_provider:
                    self.model_combo.addItem(name)

        self.model_combo.blockSignals(False)
        # 触发模型变化事件
        self._on_model_changed(self.model_combo.currentText())

    def _on_model_changed(self, text: str):
        """模型选择变化时更新 URL 和模型名称"""
        if not text:
            return

        config = PRESET_MODELS.get(text, {})
        self.base_url_edit.setText(config.get("base_url", ""))
        self.model_name_edit.setText(config.get("model", ""))

        # 更新上下文长度显示
        context = config.get("context", "")
        if hasattr(self, 'context_label'):
            self.context_label.setText(context or "--")

        # 自定义模型时启用编辑
        is_custom = (text == "自定义" or config.get("provider") == "Custom")
        self.base_url_edit.setReadOnly(not is_custom)
        self.model_name_edit.setReadOnly(not is_custom)

        # 更新删除按钮状态
        self.del_model_btn.setEnabled(is_custom)

        # 尝试加载该供应商已保存的 API Key
        provider = config.get("provider", "")
        if provider in PROVIDER_API_KEYS and PROVIDER_API_KEYS[provider]:
            self.api_key_edit.setText(PROVIDER_API_KEYS[provider])
            self.key_status_label.setText(f"✓ 已加载 {provider} 的 Key")
        else:
            self.key_status_label.setText("")

    def _toggle_api_key_visibility(self, checked: bool):
        """切换 API Key 显示/隐藏"""
        if checked:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_btn.setText("🙈")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_btn.setText("👁")

    def _save_api_key_for_provider(self):
        """保存当前 API Key 到对应供应商"""
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "提示", "API Key 为空，无法保存")
            return

        model_name = self.model_combo.currentText()
        config = PRESET_MODELS.get(model_name, {})
        provider = config.get("provider", "")

        if not provider or provider == "Custom":
            # 自定义模型时按模型名称存储
            provider = f"Custom:{model_name}"

        PROVIDER_API_KEYS[provider] = api_key
        self._save_provider_keys()

        self.key_status_label.setText(f"✓ 已保存 {provider} 的 Key")
        QMessageBox.information(self, "保存成功", f"API Key 已保存到: {provider}")

    def _clear_api_key(self):
        """清除当前输入的 API Key"""
        self.api_key_edit.clear()
        self.key_status_label.setText("")

    def _add_custom_model(self):
        """添加当前配置为自定义模型"""
        model_name, ok = QLineEdit().text(), True
        # 使用输入对话框
        from PyQt6.QtWidgets import QInputDialog
        model_name, ok = QInputDialog.getText(
            self, "添加自定义模型", "输入模型显示名称:"
        )
        if not ok or not model_name.strip():
            return

        model_name = model_name.strip()
        base_url = self.base_url_edit.text().strip()
        model_id = self.model_name_edit.text().strip()

        if not base_url or not model_id:
            QMessageBox.warning(self, "提示", "请先填写 Base URL 和模型名称")
            return

        # 添加到预设列表
        PRESET_MODELS[model_name] = {
            "model": model_id,
            "base_url": base_url,
            "provider": "Custom",
        }

        # 更新 UI
        self._refresh_model_list()
        self.model_combo.setCurrentText(model_name)
        QMessageBox.information(self, "添加成功", f"自定义模型 '{model_name}' 已添加")

    def _remove_custom_model(self):
        """删除选中的自定义模型"""
        model_name = self.model_combo.currentText()
        config = PRESET_MODELS.get(model_name, {})

        if config.get("provider") != "Custom":
            QMessageBox.warning(self, "提示", "只能删除自定义模型")
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除自定义模型 '{model_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            del PRESET_MODELS[model_name]
            self._refresh_model_list()

    def _refresh_model_list(self):
        """刷新模型列表"""
        current_provider = self.provider_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()

        # "自定义" 供应商对应 provider 值 "Custom"
        filter_provider = "Custom" if current_provider == "自定义" else current_provider

        if current_provider == "全部":
            self.model_combo.addItems(list(PRESET_MODELS.keys()))
        else:
            for name, config in PRESET_MODELS.items():
                if config.get("provider") == filter_provider:
                    self.model_combo.addItem(name)

        self.model_combo.blockSignals(False)
        if self.model_combo.count() > 0:
            self._on_model_changed(self.model_combo.currentText())

    def _save_provider_keys(self):
        """保存供应商 API Key 到配置文件"""
        import json
        key_file = PROJECT_ROOT / "provider_keys.json"
        try:
            with open(key_file, 'w', encoding='utf-8') as f:
                json.dump(PROVIDER_API_KEYS, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _load_provider_keys(self):
        """从配置文件加载供应商 API Key"""
        import json
        key_file = PROJECT_ROOT / "provider_keys.json"
        if key_file.exists():
            try:
                with open(key_file, 'r', encoding='utf-8') as f:
                    PROVIDER_API_KEYS.update(json.load(f))
            except Exception:
                pass

    def _on_drag_enter(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _on_drop(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith('.pdf'):
                self._set_input_file(file_path)
            else:
                QMessageBox.warning(self, "格式错误", "请拖入 PDF 文件")

    def _browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 PDF 文件", "", "PDF Files (*.pdf)"
        )
        if file_path:
            self._set_input_file(file_path)

    def _set_input_file(self, file_path: str):
        self.input_file = file_path
        path = Path(file_path)
        size_mb = path.stat().st_size / (1024 * 1024)
        self.drop_label.setText(f"✓ {path.name}")
        self.drop_label.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold;")

        # 清空旧的输出目录，在启动翻译时根据时间戳重新生成
        self.output_dir = None
        self.output_dir_label.setText("输出: 将在翻译启动时自动创建")

        # 确保按钮可用（切换文件后可能残留禁用状态）
        self.start_btn.setEnabled(True)

        # 尝试获取页数并检测扫描件
        try:
            import pymupdf
            doc = pymupdf.open(file_path)
            page_count = len(doc)
            doc.close()
            self._pdf_page_count = page_count
            self.file_info_label.setText(f"大小: {size_mb:.1f} MB | 页数: {page_count}")
        except Exception:
            self._pdf_page_count = 0
            self.file_info_label.setText(f"大小: {size_mb:.1f} MB")

        # 自动检测扫描件
        if hasattr(self, 'ocr_check') and self.ocr_check.isChecked():
            try:
                img_translator = ImageTranslator()
                if img_translator.detect_scanned_pdf(file_path):
                    self.ocr_status_label.setText("⚠️ 扫描件")
                    self.ocr_status_label.setStyleSheet("""
                        color: #D32F2F; font-weight: bold; font-size: 11px;
                        padding: 2px 6px; background-color: #FFEBEE; border-radius: 3px;
                    """)
                else:
                    self.ocr_status_label.setText("✅ 文字版")
                    self.ocr_status_label.setStyleSheet("""
                        color: #4CAF50; font-weight: bold; font-size: 11px;
                        padding: 2px 6px; background-color: #E8F5E9; border-radius: 3px;
                    """)
            except Exception:
                pass

    def _browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_dir = dir_path
            self.output_dir_label.setText(f"输出: {dir_path}")

    def _verify_api(self):

        """验证 API Key 是否有效（异步，不阻塞 UI）"""
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        model = self.model_name_edit.text().strip()

        if not api_key:
            QMessageBox.warning(self, "提示", "请输入 API Key")
            return
        if not base_url:
            QMessageBox.warning(self, "提示", "请输入 Base URL")
            return
        if not model:
            QMessageBox.warning(self, "提示", "请输入模型名称")
            return

        self.verify_btn.setEnabled(False)
        self.verify_btn.setText("验证中...")

        self._api_verify_worker = ApiVerifyWorker(api_key, base_url, model)
        self._api_verify_worker.finished_ok.connect(self._on_api_verify_success)
        self._api_verify_worker.finished_err.connect(self._on_api_verify_error)
        self._api_verify_worker.start()

    def _on_api_verify_success(self, result):
        self.verify_btn.setEnabled(True)
        self.verify_btn.setText("验证")
        QMessageBox.information(
            self, "验证成功",
            f"API 连接成功！\n\n测试翻译: \"Hello, world!\"\n结果: \"{result}\""
        )

    def _on_api_verify_error(self, error_msg):
        self.verify_btn.setEnabled(True)
        self.verify_btn.setText("验证")
        QMessageBox.critical(self, "验证失败", f"API 连接失败:\n\n{error_msg}")

    # ============================================================
    # 翻译控制
    # ============================================================

    def _start_translation(self):
        """开始翻译"""
        # 验证输入
        if not self.input_file:
            QMessageBox.warning(self, "提示", "请选择 PDF 文件")
            return

        api_key = self.api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "提示", "请输入 API Key")
            return

        # 收集配置
        lang_in = LANGUAGES.get(self.lang_in_combo.currentText(), "auto")
        lang_out = LANGUAGES.get(self.lang_out_combo.currentText(), "zh")

        if lang_in == "auto":
            lang_in = "en"  # BabelDOC 需要具体语言代码

        # 加载术语库（带领域过滤和自动识别）
        glossary_terms = []
        detected_domain = ""
        if hasattr(self, 'term_replace_check') and self.term_replace_check.isChecked():
            try:
                from gui.core import GlossaryManager
                from gui.core.ai_glossary import get_sub_domains
                from gui.core.domain_detector import get_best_domain
                gm = GlossaryManager()
                selected_domain = self.domain_combo.currentData() if hasattr(self, 'domain_combo') else ""

                if selected_domain:
                    detected_domain = selected_domain
                    sub_domains = get_sub_domains(selected_domain)
                    for sd in sub_domains:
                        glossary_terms.extend(gm.get_all_terms(lang_in, lang_out, domain=sd))
                else:
                    # 自动识别：扫描前几页确定领域
                    try:
                        import pymupdf
                        doc = pymupdf.open(self.input_file)
                        sample_text = ""
                        for i, page in enumerate(doc):
                            if i >= 5:
                                break
                            sample_text += page.get_text() + " "
                        doc.close()
                        detected_domain = get_best_domain(sample_text, threshold=0.02)
                    except Exception:
                        pass

                    if detected_domain:
                        sub_domains = get_sub_domains(detected_domain)
                        for sd in sub_domains:
                            glossary_terms.extend(gm.get_all_terms(lang_in, lang_out, domain=sd))
                    else:
                        glossary_terms = gm.get_all_terms(lang_in, lang_out)
            except Exception:
                pass

        # 输出目录：在输入文件同目录下创建 "{目标语言}_{时间}" 文件夹

        lang_display = self.lang_out_combo.currentText()
        timestamp = datetime.now().strftime("%Y.%m.%d %H.%M")
        output_folder_name = f"{lang_display}_{timestamp}"
        input_path = Path(self.input_file)
        actual_output_dir = input_path.parent / output_folder_name
        actual_output_dir.mkdir(exist_ok=True)
        actual_output_dir = str(actual_output_dir)
        self.output_dir_label.setText(f"输出: {actual_output_dir}")

        config = {
            "api_key": api_key,
            "base_url": self.base_url_edit.text().strip(),
            "model": self.model_name_edit.text().strip(),
            "lang_in": lang_in,
            "lang_out": lang_out,
            "input_file": self.input_file,
            "output_dir": actual_output_dir,
            "pages": self.pages_edit.text().strip() or None,
            "no_dual": not self.dual_checkbox.isChecked(),
            "no_mono": not self.mono_checkbox.isChecked(),
            "qps": self.qps_spin.value(),
            "enable_term_replacement": hasattr(self, 'term_replace_check') and self.term_replace_check.isChecked(),
            "glossary_terms": glossary_terms,
            "detected_domain": detected_domain,
            # 高级功能
            "enable_multi_engine": hasattr(self, 'multi_engine_check') and self.multi_engine_check.isChecked(),
            "multi_engine_strategy": self.multi_strategy_combo.currentText() if hasattr(self, 'multi_strategy_combo') else "balanced",
            "multi_engine_model2": self.multi_model2_combo.currentText() if hasattr(self, 'multi_model2_combo') else "glm-4-air",
            "enable_adaptive_mt": hasattr(self, 'amt_check') and self.amt_check.isChecked(),
            "enable_ocr": hasattr(self, 'ocr_check') and self.ocr_check.isChecked(),
        }

        # 更新 UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.stage_label.setText("准备中...")
        self.progress_label.setText("正在准备翻译...")

        # 确保旧 worker 已停止，避免信号干扰
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)

        # 启动工作线程
        self.worker = TranslationWorker(config)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.stage_changed.connect(self._on_stage_changed)
        self.worker.log_message.connect(self._on_log)
        self.worker.token_updated.connect(self._on_token_updated)
        self.worker.time_updated.connect(self._on_time_updated)
        self.worker.term_replaced.connect(self._on_term_replaced)
        self.worker.heartbeat.connect(self._on_heartbeat)
        self.worker.retry_happened.connect(self._on_retry_happened)
        self.worker.finished_success.connect(self._on_translation_success)
        self.worker.finished_error.connect(self._on_translation_error)
        
        # 启动心跳看门狗
        self._watchdog = HeartbeatWatchdog(timeout=300.0)
        self._watchdog.start(callback=self._on_watchdog_timeout)

        # 启动看门狗定时器（每 2 秒检查心跳）
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.timeout.connect(self._check_watchdog)
        self._watchdog_timer.start(2000)
        
        # 启动定时器：每秒更新时间显示

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)  # 1 秒
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)
        self._elapsed_timer.start()
        
        # 记录开始时间（用于定时器更新）
        import time
        self._start_time = time.monotonic()
        self._last_remaining = -1

        # 立即显示初始状态，避免"等待开始"卡住
        self._on_log("🚀 翻译任务已启动")
        if self._pdf_page_count > 0:
            self._on_log(f"📄 文档页数: {self._pdf_page_count} 页")
        if detected_domain:
            self._on_log(f"🏷 文档领域: {detected_domain}")
        if glossary_terms:
            self._on_log(f"📖 已加载 {len(glossary_terms)} 条领域术语")
        self.progress_bar.setValue(1)
        
        self.worker.start()

    def _cancel_translation(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            # 停止看门狗和定时器
            if self._watchdog:
                self._watchdog.stop()
            if hasattr(self, '_watchdog_timer'):
                self._watchdog_timer.stop()
            if hasattr(self, '_elapsed_timer'):
                self._elapsed_timer.stop()
            self.cancel_btn.setEnabled(False)
            self._on_log("正在取消翻译...")

    def _on_progress(self, text: str, percent: int):
        self.progress_label.setText(text)
        self.progress_bar.setValue(percent)

    def _on_stage_changed(self, stage_name: str, description: str):
        """阶段变化时更新阶段标签"""
        stage_cn = TRANSLATION_STAGES.get(stage_name, stage_name)
        self.stage_label.setText(stage_cn)

    def _on_token_updated(self, prompt_tokens: int, completion_tokens: int, total_tokens: int):
        """Token 统计更新"""
        self.token_label.setText(f"{prompt_tokens} / {completion_tokens} / {total_tokens}")

    def _on_time_updated(self, elapsed: float, remaining: float):
        """时间统计更新（由 worker 发出，动态估算剩余时间）"""
        self._last_remaining = remaining

        def fmt_time(seconds):
            if seconds < 60:
                return f"{int(seconds)}秒"
            elif seconds < 3600:
                m = int(seconds // 60)
                s = int(seconds % 60)
                return f"{m}分{s}秒"
            else:
                h = int(seconds // 3600)
                m = int((seconds % 3600) // 60)
                return f"{h}时{m}分"

        elapsed_str = fmt_time(elapsed)
        remaining_str = fmt_time(remaining) if remaining > 0 else "--"
        self.time_label.setText(f"{elapsed_str} / 预计 {remaining_str}")

    def _on_term_replaced(self, count: int):
        """术语替换数量更新"""
        if count > 0:
            self._on_log(f"📖 已应用 {count} 条术语替换")

    def _on_heartbeat(self):
        """心跳信号处理 - 重置看门狗"""
        if self._watchdog:
            self._watchdog.heartbeat()

    def _check_watchdog(self):
        """看门狗定时检查（由 QTimer 驱动）"""
        if self._watchdog:
            self._watchdog.check_and_act()

    def _on_retry_happened(self, attempt: int, delay: float, error: str):
        """重试信号处理 - 更新日志"""
        self._on_log(f"⚠️ 检测到限流/超时，第 {attempt} 次自动重试（等待 {delay:.1f}s）: {error[:80]}")

    def _on_watchdog_timeout(self):
        """看门狗超时 - 安全停止"""
        self._on_log("❌ 翻译任务超时（300秒无响应），执行安全停止...")
        self._cancel_translation()
        QMessageBox.warning(self, "超时", "翻译任务长时间无响应，已自动停止。\n请检查网络连接或降低 QPS 设置后重试。")

    def _on_log(self, message: str):
        from PyQt6.QtCore import QTime
        timestamp = QTime.currentTime().toString("hh:mm:ss")
        self.log_text.append(f"[{timestamp}] {message}")

    def _update_elapsed_time(self):
        """定时更新已用时间显示（基于 Worker 动态估算的剩余时间）"""
        if hasattr(self, '_start_time') and self._start_time > 0:
            import time
            elapsed = time.monotonic() - self._start_time

            def fmt_time(seconds):
                if seconds < 60:
                    return f"{int(seconds)}秒"
                elif seconds < 3600:
                    m = int(seconds // 60)
                    s = int(seconds % 60)
                    return f"{m}分{s}秒"
                else:
                    h = int(seconds // 3600)
                    m = int((seconds % 3600) // 60)
                    return f"{h}时{m}分"

            elapsed_str = fmt_time(elapsed)
            remaining = getattr(self, '_last_remaining', -1)
            if remaining > 0:
                remaining = max(0, remaining - 1)
                self._last_remaining = remaining
                remaining_str = fmt_time(remaining)
                self.time_label.setText(f"{elapsed_str} / 预计 {remaining_str}")
            else:
                self.time_label.setText(f"{elapsed_str} / --")

    def _on_translation_success(self, output_path: str, stats: dict):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.stage_label.setText("完成")
        self.progress_label.setText("翻译完成!")
        
        # 停止心跳看门狗和定时器，清零倒计时
        if self._watchdog:
            self._watchdog.stop()
        if hasattr(self, '_watchdog_timer'):
            self._watchdog_timer.stop()
        if hasattr(self, '_elapsed_timer'):
            self._elapsed_timer.stop()
        self._start_time = 0
        self._last_remaining = -1
        self.time_label.setText("完成")

        # 格式化统计信息
        total_time = stats.get("total_time", 0)
        total_tokens = stats.get("total_tokens", 0)
        prompt_tokens = stats.get("prompt_tokens", 0)
        completion_tokens = stats.get("completion_tokens", 0)
        model = stats.get("model", "unknown")

        self._on_log(f"✅ 翻译完成!")
        self._on_log(f"⏱ 总耗时: {int(total_time)}秒")
        self._on_log(f"📊 Token: {total_tokens}")
        self._on_log(f"📄 输出: {output_path}")

        # 记录成本
        try:
            analyzer = CostAnalyzer()
            record = analyzer.record_translation(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=stats.get("cached_tokens", 0),
                file_name=Path(self.input_file).name if self.input_file else "",
            )
            self._on_log(f"💰 费用: ¥{record.total_cost:.4f}")
        except Exception:
            pass

        # 更新自适应统计 + 文件解锁
        self._update_adaptive_stats()
        FileUnlockManager.release_all_handles()

        self.output_path = output_path

        QMessageBox.information(self, "完成", f"翻译已完成!\n\n输出文件: {output_path}")

    def _on_translation_error(self, error_msg: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.stage_label.setText("错误")
        self.progress_label.setText("翻译失败")
        self._on_log(f"❌ 错误: {error_msg}")
        
        # 停止心跳看门狗和定时器，清零倒计时
        if self._watchdog:
            self._watchdog.stop()
        if hasattr(self, '_watchdog_timer'):
            self._watchdog_timer.stop()
        if hasattr(self, '_elapsed_timer'):
            self._elapsed_timer.stop()
        self._start_time = 0
        self._last_remaining = -1
        self.time_label.setText("错误")
        
        # 文件解锁（即使失败也要释放文件句柄）
        FileUnlockManager.release_all_handles()

        QMessageBox.critical(self, "翻译失败", error_msg)

    def _open_output_dir(self):
        """打开输出目录（安全模式）"""
        try:
            # 1. 优先使用用户选择的输出目录
            if self.output_dir:
                output_dir = Path(self.output_dir)
                if output_dir.exists():
                    subprocess.Popen(['explorer', str(output_dir)], shell=False)
                    return

            # 2. 回退到已翻译的输出文件所在目录
            output_path = getattr(self, 'output_path', None)
            if output_path:
                output_path = Path(output_path)
                if output_path.exists():
                    subprocess.Popen(['explorer', '/select,', str(output_path)], shell=False)
                    return
                # 输出文件不存在，尝试其父目录
                if output_path.parent.exists():
                    subprocess.Popen(['explorer', str(output_path.parent)], shell=False)
                    return

            # 3. 回退到输入文件所在目录
            if self.input_file:
                input_dir = Path(self.input_file).parent
                if input_dir.exists():
                    subprocess.Popen(['explorer', str(input_dir)], shell=False)
                    return

            # 4. 都没有则提示
            QMessageBox.information(self, "提示", "暂无输出目录，请先选择输入文件")

        except FileNotFoundError:
            QMessageBox.warning(self, "错误", "找不到文件资源管理器 (explorer.exe)")
        except PermissionError:
            QMessageBox.warning(self, "错误", "权限不足，无法打开目录")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"打开目录失败:\n{type(e).__name__}: {str(e)}")

    def _open_quality_dialog(self):
        """打开质量管理对话框"""
        dialog = QualityDialog(self)
        dialog.exec()

    def _import_ai_glossary(self):
        """导入预置多领域术语库"""
        from gui.core.ai_glossary import get_all_terms, get_domains, get_sub_domains
        from gui.core import GlossaryManager

        all_domains = get_domains()
        domain_list = "\n".join(f"  - {d}" for d in all_domains)

        # 让用户选择要导入的领域
        from PyQt6.QtWidgets import QInputDialog
        domain_choices = ["全部领域"] + all_domains
        chosen, ok = QInputDialog.getItem(
            self, "导入术语库",
            f"选择要导入的术语领域：\n\n可选领域:\n{domain_list}",
            domain_choices, 0, False,
        )
        if not ok:
            return

        try:
            gm = GlossaryManager()
            count = 0
            if chosen == "全部领域":
                terms = get_all_terms()
            else:
                sub_domains = get_sub_domains(chosen)
                terms = []
                for sd in sub_domains:
                    terms.extend(get_all_terms(domain=sd))

            for term_data in terms:
                if gm.add_term(**term_data):
                    count += 1

            QMessageBox.information(
                self, "导入完成",
                f"成功导入 {count} 条术语！\n领域: {chosen}\n"
                f"可在「质量管理」→「术语库」中查看和管理。"
            )
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _estimate_translation_cost(self):
        """估算当前文件的翻译成本"""
        if not self.input_file:
            QMessageBox.warning(self, "提示", "请先选择 PDF 文件")
            return

        try:
            # 获取文件字符数
            import pymupdf
            doc = pymupdf.open(self.input_file)
            total_chars = 0
            for page in doc:
                total_chars += len(page.get_text())
            doc.close()

            if total_chars == 0:
                total_chars = 5000  # 默认值

            model = self.model_name_edit.text().strip()
            lang_in = LANGUAGES.get(self.lang_in_combo.currentText(), "en")
            lang_out = LANGUAGES.get(self.lang_out_combo.currentText(), "zh")

            analyzer = CostAnalyzer()
            estimate = analyzer.estimate_cost(total_chars, model, lang_in, lang_out)

            pricing = estimate["pricing"]
            self.cost_estimate_label.setText(
                f"≈ ¥{estimate['estimated_total_cost']:.4f} "
                f"({estimate['estimated_total_tokens']} tokens)"
            )
            self.cost_estimate_label.setStyleSheet("""
                color: #E65100;
                font-weight: bold;
                font-size: 12px;
                padding: 2px 8px;
                background-color: #FFF3E0;
                border-radius: 3px;
            """)

            QMessageBox.information(
                self, "成本估算",
                f"文件字符数: {total_chars:,}\n"
                f"模型: {model}\n"
                f"语言: {lang_in} → {lang_out}\n\n"
                f"预估 Token 数:\n"
                f"  Prompt: {estimate['estimated_prompt_tokens']:,}\n"
                f"  Completion: {estimate['estimated_completion_tokens']:,}\n"
                f"  总计: {estimate['estimated_total_tokens']:,}\n\n"
                f"预估费用:\n"
                f"  输入: ¥{estimate['estimated_input_cost']:.4f}\n"
                f"  输出: ¥{estimate['estimated_output_cost']:.4f}\n"
                f"  总计: ¥{estimate['estimated_total_cost']:.4f}\n\n"
                f"单价: input ¥{pricing['input']}/1K, output ¥{pricing['output']}/1K"
            )
        except Exception as e:
            QMessageBox.critical(self, "估算失败", str(e))

    def _show_cost_comparison(self):
        """显示模型成本对比"""
        try:
            analyzer = CostAnalyzer()
            comparisons = analyzer.get_model_comparison(10000)

            text = "📊 10000 字符翻译成本对比:\n\n"
            text += f"{'模型':<30} {'Token':<12} {'费用':<10} {'性价比'}\n"
            text += "-" * 65 + "\n"

            for c in comparisons[:15]:
                cost_bar = "█" * int(c["total_cost"] * 1000)
                text += f"{c['model']:<30} {c['total_tokens']:<12} ¥{c['total_cost']:.4f}  {cost_bar}\n"

            text += f"\n共 {len(comparisons)} 个模型\n"
            text += f"最便宜: {comparisons[0]['model']} (¥{comparisons[0]['total_cost']:.4f})\n"
            text += f"最贵: {comparisons[-1]['model']} (¥{comparisons[-1]['total_cost']:.4f})\n"

            QMessageBox.information(self, "模型成本对比", text)
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _show_cost_report(self):
        """显示成本报告"""
        try:
            analyzer = CostAnalyzer()
            summary = analyzer.get_summary()

            if summary.record_count == 0:
                QMessageBox.information(self, "成本报告", "暂无翻译记录")
                return

            text = "📈 翻译成本报告\n\n"
            text += f"总费用: ¥{summary.total_cost:.4f}\n"
            text += f"总 Token: {summary.total_tokens:,}\n"
            text += f"  输入: {summary.total_prompt_tokens:,}\n"
            text += f"  输出: {summary.total_completion_tokens:,}\n"
            text += f"  缓存命中: {summary.total_cached_tokens:,}\n"
            text += f"翻译次数: {summary.record_count}\n\n"

            if summary.by_model:
                text += "按模型统计:\n"
                for model, data in sorted(summary.by_model.items(), key=lambda x: x[1]["cost"], reverse=True):
                    text += f"  {model}: ¥{data['cost']:.4f} ({data['count']} 次)\n"

            if summary.by_project:
                text += "\n按项目统计:\n"
                for proj, data in sorted(summary.by_project.items(), key=lambda x: x[1]["cost"], reverse=True):
                    text += f"  {proj}: ¥{data['cost']:.4f} ({data['count']} 次)\n"

            # 导出选项
            reply = QMessageBox.question(
                self, "导出报告",
                text + "\n\n是否导出 JSON 报告？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                filepath, _ = QFileDialog.getSaveFileName(
                    self, "导出成本报告", "cost_report.json",
                    "JSON Files (*.json)"
                )
                if filepath:
                    report = analyzer.export_report(filepath)
                    QMessageBox.information(self, "导出成功", f"报告已保存到: {filepath}")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _show_adaptive_rules(self):
        """显示自适应学习规则"""
        try:
            amt = AdaptiveMT()
            rules = amt.get_style_rules(min_hits=1)

            if not rules:
                QMessageBox.information(self, "自适应规则", "暂无学习到的规则")
                return

            text = "🧠 自适应学习规则:\n\n"
            for pattern, replacement, hits in rules:
                text += f"  [{hits}次] \"{pattern}\" → \"{replacement}\"\n"

            QMessageBox.information(self, "自适应规则", text)
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _show_adaptive_stats(self):
        """显示自适应学习统计"""
        try:
            amt = AdaptiveMT()
            stats = amt.get_stats()

            text = "🧠 自适应学习统计:\n\n"
            text += f"反馈总数: {stats['total_feedback']}\n"
            text += f"学习规则: {stats['total_rules']}\n"

            if stats["top_rules"]:
                text += "\n高频规则:\n"
                for pattern, replacement, hits in stats["top_rules"]:
                    text += f"  [{hits}次] \"{pattern}\" → \"{replacement}\"\n"

            QMessageBox.information(self, "学习统计", text)

            # 更新标签
            self.amt_label.setText(f"已学习: {stats['total_rules']} 条规则")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _test_ocr_detection(self):
        """测试 OCR 扫描件检测"""
        if not self.input_file:
            QMessageBox.warning(self, "提示", "请先选择 PDF 文件")
            return

        try:
            translator = ImageTranslator()
            is_scanned = translator.detect_scanned_pdf(self.input_file)

            if is_scanned:
                self.ocr_status_label.setText("⚠️ 检测到扫描件")
                self.ocr_status_label.setStyleSheet("""
                    color: #D32F2F;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 2px 6px;
                    background-color: #FFEBEE;
                    border-radius: 3px;
                """)
                QMessageBox.warning(
                    self, "扫描件检测",
                    "检测到该 PDF 可能是扫描件。\n\n"
                    "建议:\n"
                    "1. 确保启用 OCR 功能\n"
                    "2. 使用支持视觉的模型（如 GLM-4.6V）\n"
                    "3. 翻译质量可能受影响"
                )
            else:
                self.ocr_status_label.setText("✅ 文字版 PDF")
                self.ocr_status_label.setStyleSheet("""
                    color: #4CAF50;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 2px 6px;
                    background-color: #E8F5E9;
                    border-radius: 3px;
                """)
                QMessageBox.information(
                    self, "扫描件检测",
                    "该 PDF 是文字版，可直接翻译。"
                )
        except Exception as e:
            self.ocr_status_label.setText("❓ 检测失败")
            QMessageBox.critical(self, "错误", str(e))

    # ============================================================
    # 配置持久化
    # ============================================================

    def _save_settings(self):
        """保存当前配置"""
        import json
        settings = {
            "provider": self.provider_combo.currentText(),
            "model": self.model_combo.currentText(),
            "api_key": self.api_key_edit.text(),
            "base_url": self.base_url_edit.text(),
            "model_name": self.model_name_edit.text(),
            "lang_in": self.lang_in_combo.currentText(),
            "lang_out": self.lang_out_combo.currentText(),
            "pages": self.pages_edit.text(),
            "dual": self.dual_checkbox.isChecked(),
            "mono": self.mono_checkbox.isChecked(),
            "qps": self.qps_spin.value(),
            "output_dir": self.output_dir,
        }
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "保存成功", f"配置已保存到:\n{self.settings_file}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _load_settings(self):
        """加载已保存的配置"""
        import json
        if not self.settings_file.exists():
            # 默认选中 DeepSeek-Chat
            self.provider_combo.setCurrentText("DeepSeek")
            self._on_model_changed("DeepSeek-Chat")
            return

        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            # 恢复供应商筛选
            saved_provider = settings.get("provider", "全部")
            self.provider_combo.setCurrentText(saved_provider)

            self.model_combo.setCurrentText(settings.get("model", "DeepSeek-Chat"))
            self.api_key_edit.setText(settings.get("api_key", ""))
            self.base_url_edit.setText(settings.get("base_url", ""))
            self.model_name_edit.setText(settings.get("model_name", ""))
            self.lang_in_combo.setCurrentText(settings.get("lang_in", "English"))
            self.lang_out_combo.setCurrentText(settings.get("lang_out", "中文"))
            self.pages_edit.setText(settings.get("pages", ""))
            self.dual_checkbox.setChecked(settings.get("dual", True))
            self.mono_checkbox.setChecked(settings.get("mono", True))
            self.qps_spin.setValue(settings.get("qps", 2))

            if settings.get("output_dir"):
                self.output_dir = settings["output_dir"]
                self.output_dir_label.setText(f"输出: {self.output_dir}")

            self._on_model_changed(settings.get("model", "DeepSeek-Chat"))
        except Exception:
            self.provider_combo.setCurrentText("DeepSeek")
            self._on_model_changed("DeepSeek-Chat")

    def closeEvent(self, event):
        """关闭窗口时停止工作线程"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        event.accept()