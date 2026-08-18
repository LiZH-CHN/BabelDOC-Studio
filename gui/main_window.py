"""主窗口模块"""
import threading
import time
import traceback
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt6.QtGui import QFont, QIcon, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QComboBox, QLineEdit, QPushButton,
    QCheckBox, QSpinBox, QProgressBar, QTextEdit,
    QFileDialog, QMessageBox, QFrame, QSizePolicy,
    QApplication, QSplitter
)

from babeldoc.translator.translator import OpenAITranslator, parse_context_length
from gui.config_manager import get_config, ConfigManager
from gui.preset_models import get_preset_models, get_model_config
from gui.quality_dialogs import QualityDialog
from gui.translation_worker import TranslationWorker
from gui.core import (
    TermInjector, create_default_replacer, SmartTermMatcher,
    CostAnalyzer, MultiEngineTranslator, AdaptiveMT, ImageTranslator,
    MODEL_PRICING
)
from gui.fault_tolerance import (
    HeartbeatWatchdog, WorkerHeartbeat, APIGuardian,
    FileUnlockManager, SafeShutdownManager, DEFAULT_RETRY_CONFIG
)
from gui.notify import send_notification

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


# ============================================================
# 窗口尺寸常量
# ============================================================
# 默认窗口大小占屏幕的比例
DEFAULT_WINDOW_WIDTH_RATIO: float = 0.7
DEFAULT_WINDOW_HEIGHT_RATIO: float = 0.8
# 默认窗口最大尺寸限制
MAX_WINDOW_WIDTH: int = 1200
MAX_WINDOW_HEIGHT: int = 900
# 窗口最小尺寸限制
MIN_WINDOW_WIDTH: int = 450
MIN_WINDOW_HEIGHT: int = 400


# ============================================================
# 定时器间隔常量（毫秒）
# ============================================================
MODEL_VERIFY_DELAY_MS: int = 500  # 启动时模型验证延迟
WATCHDOG_CHECK_INTERVAL_MS: int = 2000  # 看门狗检查间隔
ELAPSED_TIMER_INTERVAL_MS: int = 1000  # 已用时间更新间隔


# ============================================================
# 超时时间常量（秒）
# ============================================================
WATCHDOG_TIMEOUT_S: float = 300.0  # 看门狗超时时间（5分钟）
WORKER_WAIT_TIMEOUT_MS: int = 5000  # Worker 等待超时
THREAD_WAIT_TIMEOUT_MS: int = 1000  # 线程等待超时
CLOSE_WAIT_TIMEOUT_MS: int = 3000  # 关闭窗口时等待超时


# ============================================================
# 进度与日志常量
# ============================================================
MAX_LOG_BLOCK_COUNT: int = 5000  # 日志最大行数
PROGRESS_BAR_MAX: int = 100  # 进度条最大值


# ============================================================
# 翻译配置常量
# ============================================================
DEFAULT_CHAR_COUNT: int = 5000  # 默认字符数（用于成本估算）
COMPARISON_CHAR_COUNT: int = 10000  # 成本对比字符数
MAX_FILE_PREFIX_LENGTH: int = 50  # 输出文件夹名中文件名最大长度


# ============================================================
# 预设模型配置（动态加载）
# ============================================================
_models_dict: Dict[str, Dict[str, Any]] = {}


def _get_preset_models_dict() -> Dict[str, Dict[str, Any]]:
    """获取预设模型配置字典（动态加载自配置文件）

    Returns:
        预设模型配置字典
    """
    global _models_dict
    if not _models_dict:
        try:
            _models_dict = get_preset_models()
        except Exception:
            _models_dict = {}
    return _models_dict


def _reload_preset_models() -> Dict[str, Dict[str, Any]]:
    """重新加载预设模型配置

    Returns:
        重新加载后的预设模型配置字典
    """
    global _models_dict
    _models_dict = {}
    return _get_preset_models_dict()


# 供应商列表（用于筛选）
PROVIDERS = ["全部", "DeepSeek", "GLM", "GLM-Vision", "OpenAI", "Qwen", "LongCat", "自定义"]

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



class ApiVerifyWorker(QThread):
    """API 验证工作线程（异步，不阻塞 UI）"""
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        super().__init__()
        self.api_key: str = api_key
        self.base_url: str = base_url
        self.model: str = model

    def run(self) -> None:
        """执行 API 验证"""
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


@dataclass
class ModelVerifyResult:
    """模型验证结果数据类"""
    model_name: str
    is_available: bool
    error_message: str = ""
    verify_time: float = 0.0


class ModelAvailabilityChecker(QObject):
    """模型可用性检查器 - 批量验证模型是否可用"""
    finished = pyqtSignal(dict)

    def __init__(self, api_key: str, timeout: float = 5.0) -> None:
        super().__init__()
        self.api_key: str = api_key
        self.timeout: float = timeout

    def verify_model(self, model_name: str, base_url: str) -> ModelVerifyResult:
        """验证单个模型的可用性。

        Args:
            model_name: 模型名称
            base_url: API Base URL

        Returns:
            模型验证结果
        """
        import time
        start_time = time.time()
        try:
            translator = OpenAITranslator(
                lang_in="en",
                lang_out="zh",
                model=model_name,
                base_url=base_url,
                api_key=self.api_key,
            )
            # 使用简单的测试消息验证
            result = translator.translate("Hi")
            elapsed = time.time() - start_time
            if result and len(result) > 0:
                return ModelVerifyResult(
                    model_name=model_name,
                    is_available=True,
                    verify_time=elapsed,
                )
            else:
                return ModelVerifyResult(
                    model_name=model_name,
                    is_available=False,
                    error_message="Empty response",
                    verify_time=elapsed,
                )
        except Exception as e:
            elapsed = time.time() - start_time
            return ModelVerifyResult(
                model_name=model_name,
                is_available=False,
                error_message=f"{type(e).__name__}: {str(e)}",
                verify_time=elapsed,
            )

    def verify_all(self, models: List[Dict[str, Any]]) -> Dict[str, bool]:
        """批量验证多个模型，返回 {model_name: is_available} 字典。

        Args:
            models: 模型信息列表，每个元素包含 name, base_url, model 键

        Returns:
            模型名称到可用性的映射字典
        """
        results: Dict[str, bool] = {}
        for model_info in models:
            name = model_info["name"]
            base_url = model_info["base_url"]
            model_id = model_info["model"]
            result = self.verify_model(model_id, base_url)
            results[name] = result.is_available
        # 发射完成信号
        self.finished.emit(results)
        return results


class MainWindow(QMainWindow):
    """BabelDOC PDF 翻译工具主窗口"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BabelDOC PDF 翻译工具")

        # 响应式窗口大小：默认为屏幕的 70%
        from PyQt6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().availableGeometry()
        default_w = min(int(screen.width() * DEFAULT_WINDOW_WIDTH_RATIO), MAX_WINDOW_WIDTH)
        default_h = min(int(screen.height() * DEFAULT_WINDOW_HEIGHT_RATIO), MAX_WINDOW_HEIGHT)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(default_w, default_h)

        self.input_file: Optional[str] = None
        self.output_dir: Optional[str] = None
        self.worker: Optional[TranslationWorker] = None
        self.settings_file: Path = PROJECT_ROOT / "gui_settings.json"
        self._pdf_page_count: int = 0
        self.config_manager: ConfigManager = get_config()
        self._model_verify_results: Dict[str, bool] = {}
        self._watchdog: Optional[HeartbeatWatchdog] = None
        self._start_time: float = 0.0
        self._last_remaining: float = -1.0
        self.output_path: Optional[str] = None

        self._setup_ui()
        self._load_settings()
        self._update_adaptive_stats()
        self._schedule_model_verification()

    def _schedule_model_verification(self) -> None:
        """调度启动时的模型可用性验证（延迟执行，不阻塞UI）"""
        api_key = self.config_manager.config.last_session.api_key
        if not api_key:
            return
        # 延迟启动验证，确保UI已完全加载
        QTimer.singleShot(MODEL_VERIFY_DELAY_MS, self._verify_all_models)

    def _verify_all_models(self) -> None:
        """验证所有DeepSeek模型的可用性"""
        try:
            from gui.main_window import ModelAvailabilityChecker

            api_key = self.config_manager.config.last_session.api_key
            if not api_key:
                return

            # 收集所有DeepSeek模型
            deepseek_models: List[Dict[str, str]] = [
                {"name": name, "base_url": info["base_url"], "model": info["model"]}
                for name, info in _get_preset_models_dict().items()
                if info.get("provider") == "DeepSeek"
            ]
            if not deepseek_models:
                return

            # 在后台线程中验证
            self._model_checker = ModelAvailabilityChecker(api_key)
            self._model_verify_thread = QThread()
            self._model_checker.moveToThread(self._model_verify_thread)
            self._model_verify_thread.started.connect(
                lambda: self._model_checker.verify_all(deepseek_models)
            )
            self._model_checker.finished.connect(self._on_model_verify_finished)
            self._model_verify_thread.start()
        except Exception as e:
            logging.getLogger(__name__).warning("模型验证启动失败: %s", e)

    def _on_model_verify_finished(self, results: Dict[str, bool]) -> None:
        """模型验证完成后的回调。

        Args:
            results: 模型名称到可用性的映射
        """
        try:
            self._model_verify_results = results
            unavailable = [name for name, ok in results.items() if not ok]
            if unavailable:
                logging.getLogger(__name__).info(
                    "以下DeepSeek模型不可用，已从列表移除: %s", unavailable
                )
                # 更新模型下拉列表
                self._filter_unavailable_models(unavailable)
            # 清理线程
            if hasattr(self, '_model_verify_thread'):
                self._model_verify_thread.quit()
                self._model_verify_thread.wait(THREAD_WAIT_TIMEOUT_MS)
        except Exception as e:
            logging.getLogger(__name__).warning("模型验证结果处理失败: %s", e)

    def _filter_unavailable_models(self, unavailable_models: List[str]) -> None:
        """从下拉列表中移除不可用的模型。

        Args:
            unavailable_models: 不可用的模型名称列表
        """
        try:
            model_combo = self.model_combo
            # 获取当前选中的模型
            current_model = model_combo.currentText()
            # 移除不可用模型
            for model_name in unavailable_models:
                index = model_combo.findText(model_name)
                if index >= 0:
                    model_combo.removeItem(index)
            # 如果当前选中的模型被移除，重置为第一个可用模型
            if current_model in unavailable_models:
                model_combo.setCurrentIndex(0)
        except Exception as e:
            logging.getLogger(__name__).warning("过滤不可用模型失败: %s", e)

    def _update_adaptive_stats(self) -> None:
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
        layout.setSpacing(4)
        layout.setContentsMargins(8, 6, 8, 6)

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
        self.model_combo.addItems(list(_get_preset_models_dict().keys()))

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

        # 第三行：Base URL + 上下文长度（小屏友好）
        param_row = QHBoxLayout()
        param_row.setSpacing(4)
        param_row.addWidget(QLabel("Base URL:"))

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1")
        self.base_url_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        param_row.addWidget(self.base_url_edit, 2)

        # 上下文长度（预设模型只读，自定义模型可编辑）
        self.context_label = QLabel("上下文:")
        param_row.addWidget(self.context_label)
        self.context_edit = QLineEdit()
        self.context_edit.setPlaceholderText("1M/128K/64K")
        self.context_edit.setFixedWidth(70)
        self.context_edit.setToolTip(
            "预设模型自动填充，自定义模型请手动填写上下文长度\n"
            "格式: 1M / 128K / 64K 等"
        )
        param_row.addWidget(self.context_edit, 0)

        layout.addLayout(param_row)

        # 模型名存储（隐藏，用于保存自定义模型名）
        self.model_name_edit = QLineEdit()
        self.model_name_edit.setVisible(False)

        # 第四行：API Key 管理（按供应商保存）
        key_mgmt_row = QHBoxLayout()
        key_mgmt_row.setSpacing(6)
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

        self.skip_references_check = QCheckBox("跳过引用")
        self.skip_references_check.setChecked(True)
        self.skip_references_check.setToolTip(
            "跳过 References/参考文献 列表翻译，保持原文。"
        )
        opt_row.addWidget(self.skip_references_check)

        self.auto_open_output_check = QCheckBox("自动打开输出目录")
        self.auto_open_output_check.setChecked(True)
        self.auto_open_output_check.setToolTip(
            "翻译完成后自动打开输出文件所在目录。"
        )
        opt_row.addWidget(self.auto_open_output_check)

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
        cost_row.addWidget(QLabel("费用:"))

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
        multi_row.addWidget(QLabel("多引擎:"))

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

    def _toggle_smart_mode(self, checked: bool):
        """智能并发开关变化（方案D）"""
        self.qps_spin.setEnabled(not checked)
        if checked:
            self.qps_tip_label.setText("[智能] 智能模式已启用，自动优化并发数")
            self.qps_tip_label.setStyleSheet("color: #1976D2; font-size: 10px; font-weight: bold;")
        else:
            self.qps_tip_label.setText("[提示] 免费模型建议 1-3，商用/本地模型可拉满 50")
            self.qps_tip_label.setStyleSheet("color: #D32F2F; font-size: 10px; font-weight: bold;")

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

        # QPS 设置（带模型建议）— 该值大幅影响处理速度，需醒目提示
        qps_label = QLabel("QPS:")
        qps_label.setStyleSheet("color: #D32F2F; font-weight: bold; font-size: 11px;")
        btn_row.addWidget(qps_label)

        # 智能并发复选框（方案D：默认启用智能模式）
        self.smart_mode_check = QCheckBox("智能并发")
        self.smart_mode_check.setChecked(True)
        self.smart_mode_check.setToolTip("启用后自动根据模型性能和网络状况动态调整并发数\n禁用后可手动设置QPS值")
        self.smart_mode_check.toggled.connect(self._toggle_smart_mode)
        btn_row.addWidget(self.smart_mode_check)

        self.qps_spin = QSpinBox()
        self.qps_spin.setRange(1, 50)
        self.qps_spin.setValue(10)  # 默认值改为10，更保守
        self.qps_spin.setEnabled(False)  # 默认禁用（智能模式启用时）
        self.qps_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #D32F2F;
                border-radius: 3px;
                padding: 2px 4px;
                font-weight: bold;
                color: #D32F2F;
            }
            QSpinBox:disabled {
                border-color: #999;
                color: #999;
            }
        """)
        self.qps_spin.setToolTip(
            "每秒请求数限制。该值越大翻译越快，但可能触发 API 限流。\n"
            "不同模型建议值：\n"
            "  DeepSeek-V4: 20-50（高并发无限制）\n"
            "  DeepSeek-Flash: 20-50\n"
            "  GLM-5:      10-25（企业版）/ 3-10（免费版）\n"
            "  Kimi-K3:    10-20\n"
            "  GPT-5:      5-15（注意 RPM 限额）\n"
            "  GPT-4o:     3-10（严格 RPM 限制）\n"
            "  Qwen3-Max:  20-50（高并发）\n"
            "  LongCat-2.0: 20-50\n"
            "  免费/限速模型: 1-5（避免触发限流）\n"
            "  本地部署模型: 50（无 API 限额）\n"
            "  智能模式: 自动动态调整并发数"
        )
        btn_row.addWidget(self.qps_spin)

        # QPS 建议标签
        self.qps_tip_label = QLabel("[智能] 智能模式已启用，自动优化并发数")
        self.qps_tip_label.setStyleSheet("color: #1976D2; font-size: 10px; font-weight: bold;")
        btn_row.addWidget(self.qps_tip_label)

        btn_row.addSpacing(15)

        # 术语替换与领域选择（合并为一个下拉框，默认关闭）
        btn_row.addWidget(QLabel("术语:"))
        self.term_domain_combo = QComboBox()
        self.term_domain_combo.addItem("关闭（跳过术语替换）", "off")
        self.term_domain_combo.addItem("自动识别领域", "auto")
        self.term_domain_combo.insertSeparator(100)
        from gui.core.ai_glossary import get_sub_domains as _get_sub_domains
        for sd in _get_sub_domains("AI"):
            self.term_domain_combo.addItem(f"  {sd}", sd)
        self.term_domain_combo.insertSeparator(100)
        for sd in _get_sub_domains("医学"):
            self.term_domain_combo.addItem(f"  {sd}", sd)
        self.term_domain_combo.insertSeparator(100)
        for sd in _get_sub_domains("金融"):
            self.term_domain_combo.addItem(f"  {sd}", sd)
        self.term_domain_combo.insertSeparator(100)
        for sd in _get_sub_domains("法律"):
            self.term_domain_combo.addItem(f"  {sd}", sd)
        self.term_domain_combo.insertSeparator(100)
        for sd in _get_sub_domains("工程"):
            self.term_domain_combo.addItem(f"  {sd}", sd)
        self.term_domain_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.term_domain_combo.setToolTip(
            "启用术语替换会增加约 1 倍处理时间，建议在专业文献翻译时开启。\n"
            "关闭 = 不进行术语预处理替换\n"
            "自动识别 = 系统扫描前几页判断领域\n"
            "选择具体领域 = 加载对应术语库进行预处理替换"
        )
        btn_row.addWidget(self.term_domain_combo, 1)

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
        self.log_text.setMinimumHeight(80)
        self.log_text.document().setMaximumBlockCount(MAX_LOG_BLOCK_COUNT)
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
        self.start_btn.setMinimumHeight(28)
        self.start_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                font-weight: bold; font-size: 10pt; border-radius: 4px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #ccc; color: #999; }
        """)
        self.start_btn.clicked.connect(self._start_translation)
        layout.addWidget(self.start_btn, 2)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setMinimumHeight(28)
        self.cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_translation)
        layout.addWidget(self.cancel_btn, 1)

        self.open_output_btn = QPushButton("📁 输出")
        self.open_output_btn.setMinimumHeight(28)
        self.open_output_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.open_output_btn.clicked.connect(self._open_output_dir)
        layout.addWidget(self.open_output_btn, 1)

        self.quality_btn = QPushButton("质量检查")
        self.quality_btn.setMinimumHeight(28)
        self.quality_btn.setToolTip("翻译记忆库、术语库、QA 检查")
        self.quality_btn.clicked.connect(self._open_quality_dialog)
        layout.addWidget(self.quality_btn, 1)

        self.save_btn = QPushButton("保存配置")
        self.save_btn.setMinimumHeight(28)
        self.save_btn.clicked.connect(self._save_settings)
        layout.addWidget(self.save_btn, 1)

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
            self.model_combo.addItems(list(_get_preset_models_dict().keys()))
        else:
            for name, config in _get_preset_models_dict().items():
                if config.get("provider") == filter_provider:
                    self.model_combo.addItem(name)

        self.model_combo.blockSignals(False)
        # 触发模型变化事件
        self._on_model_changed(self.model_combo.currentText())

    def _on_model_changed(self, text: str):
        """模型选择变化时更新 URL 和模型名称"""
        if not text:
            return

        config = _get_preset_models_dict().get(text, {})
        self.base_url_edit.setText(config.get("base_url", ""))
        self.model_name_edit.setText(config.get("model", ""))

        # 更新上下文长度（预设模型自动填充，自定义模型可编辑）
        context = config.get("context", "")
        if hasattr(self, 'context_edit'):
            self.context_edit.setText(context or "")
            # 自定义模型时可编辑，预设模型时只读
            is_custom = (text == "自定义" or config.get("provider") == "Custom")
            self.context_edit.setReadOnly(not is_custom)

        # 自定义模型时启用编辑
        is_custom = (text == "自定义" or config.get("provider") == "Custom")
        self.base_url_edit.setReadOnly(not is_custom)
        self.model_name_edit.setReadOnly(not is_custom)

        # 更新删除按钮状态
        self.del_model_btn.setEnabled(is_custom)

    def _toggle_api_key_visibility(self, checked: bool):
        """切换 API Key 显示/隐藏"""
        if checked:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_btn.setText("🙈")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_btn.setText("👁")

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
        _get_preset_models_dict()[model_name] = {
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
        config = _get_preset_models_dict().get(model_name, {})

        if config.get("provider") != "Custom":
            QMessageBox.warning(self, "提示", "只能删除自定义模型")
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除自定义模型 '{model_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            del _get_preset_models_dict()[model_name]
            self._refresh_model_list()

    def _refresh_model_list(self):
        """刷新模型列表"""
        current_provider = self.provider_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()

        # "自定义" 供应商对应 provider 值 "Custom"
        filter_provider = "Custom" if current_provider == "自定义" else current_provider

        if current_provider == "全部":
            self.model_combo.addItems(list(_get_preset_models_dict().keys()))
        else:
            for name, config in _get_preset_models_dict().items():
                if config.get("provider") == filter_provider:
                    self.model_combo.addItem(name)

        self.model_combo.blockSignals(False)
        if self.model_combo.count() > 0:
            self._on_model_changed(self.model_combo.currentText())

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
                    self.ocr_status_label.setText("[警告] 扫描件")
                    self.ocr_status_label.setStyleSheet("""
                        color: #D32F2F; font-weight: bold; font-size: 11px;
                        padding: 2px 6px; background-color: #FFEBEE; border-radius: 3px;
                    """)
                else:
                    self.ocr_status_label.setText("[成功] 文字版")
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
        term_domain = self.term_domain_combo.currentData() if hasattr(self, 'term_domain_combo') else "off"

        if term_domain != "off":
            try:
                from gui.core import GlossaryManager
                from gui.core.ai_glossary import get_sub_domains
                from gui.core.domain_detector import get_best_domain
                gm = GlossaryManager()

                if term_domain == "auto":
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
                else:
                    # 选定了具体领域（顶级或子领域）
                    detected_domain = term_domain
                    if "/" in term_domain:
                        # 子领域（如 "AI/NLP"）
                        glossary_terms.extend(gm.get_all_terms(lang_in, lang_out, domain=term_domain))
                    else:
                        # 顶级领域（如 "AI"），加载其全部子领域
                        sub_domains = get_sub_domains(term_domain)
                        for sd in sub_domains:
                            glossary_terms.extend(gm.get_all_terms(lang_in, lang_out, domain=sd))
            except Exception:
                pass

        # 输出目录：在输入文件同目录下创建 "{目标语言}_{文件名前50字符}" 文件夹

        lang_display = self.lang_out_combo.currentText()
        input_path = Path(self.input_file)
        file_prefix = input_path.stem[:MAX_FILE_PREFIX_LENGTH]
        output_folder_name = f"{lang_display}_{file_prefix}"
        actual_output_dir = input_path.parent / output_folder_name
        actual_output_dir.mkdir(exist_ok=True)
        actual_output_dir = str(actual_output_dir)
        self.output_dir_label.setText(f"输出: {actual_output_dir}")

        context = ""
        for preset_name, preset_cfg in _get_preset_models_dict().items():
            if preset_cfg.get("model") == self.model_name_edit.text().strip():
                context = preset_cfg.get("context", "")
                break

        config = {
            "api_key": api_key,
            "base_url": self.base_url_edit.text().strip(),
            "model": self.model_name_edit.text().strip(),
            "context": context,
            "lang_in": lang_in,
            "lang_out": lang_out,
            "input_file": self.input_file,
            "output_dir": actual_output_dir,
            "pages": self.pages_edit.text().strip() or None,
            "no_dual": not self.dual_checkbox.isChecked(),
            "no_mono": not self.mono_checkbox.isChecked(),
            "qps": self.qps_spin.value() if not self.smart_mode_check.isChecked() else 20,
            "smart_mode": self.smart_mode_check.isChecked(),
            "enable_term_replacement": (
                hasattr(self, 'term_domain_combo')
                and self.term_domain_combo.currentData() != "off"
            ),
            "glossary_terms": glossary_terms,
            "detected_domain": detected_domain,
            # 高级功能
            "enable_multi_engine": hasattr(self, 'multi_engine_check') and self.multi_engine_check.isChecked(),
            "multi_engine_strategy": self.multi_strategy_combo.currentText() if hasattr(self, 'multi_strategy_combo') else "balanced",
            "multi_engine_model2": self.multi_model2_combo.currentText() if hasattr(self, 'multi_model2_combo') else "glm-4-air",
            "enable_adaptive_mt": hasattr(self, 'amt_check') and self.amt_check.isChecked(),
            "enable_ocr": hasattr(self, 'ocr_check') and self.ocr_check.isChecked(),
            "skip_references": hasattr(self, 'skip_references_check') and self.skip_references_check.isChecked(),
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
            self.worker.wait(WORKER_WAIT_TIMEOUT_MS)

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
        self.worker.network_paused.connect(self._on_network_paused)
        self.worker.network_resumed.connect(self._on_network_resumed)
        self.worker.finished_success.connect(self._on_translation_success)
        self.worker.finished_error.connect(self._on_translation_error)
        
        # 启动心跳看门狗
        self._watchdog = HeartbeatWatchdog(timeout=WATCHDOG_TIMEOUT_S)
        self._watchdog.start(callback=self._on_watchdog_timeout)

        # 启动看门狗定时器（每 2 秒检查心跳）
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.timeout.connect(self._check_watchdog)
        self._watchdog_timer.start(WATCHDOG_CHECK_INTERVAL_MS)
        
        # 启动定时器：每秒更新时间显示

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(ELAPSED_TIMER_INTERVAL_MS)  # 1 秒
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)
        self._elapsed_timer.start()
        
        # 记录开始时间（用于定时器更新）
        import time
        self._start_time = time.monotonic()
        self._last_remaining = -1

        # 立即显示初始状态，避免"等待开始"卡住
        self._on_log("[信息] 翻译任务已启动")
        if self._pdf_page_count > 0:
            self._on_log(f"[信息] 文档页数: {self._pdf_page_count} 页")
        if detected_domain:
            self._on_log(f"[标签] 文档领域: {detected_domain}")
        if glossary_terms:
            self._on_log(f"[术语] 已加载 {len(glossary_terms)} 条领域术语")
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
            self._on_log(f"[术语] 已应用 {count} 条术语替换")

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
        self._on_log(f"[警告] 检测到限流/超时，第 {attempt} 次自动重试（等待 {delay:.1f}s）: {error[:80]}")

    def _on_network_paused(self, reason: str):
        """网络暂停信号处理 - 弹窗警告"""
        self._on_log(f"[错误] 网络异常：{reason}。翻译已暂停，等待网络恢复...")
        # 显示非模态提示（不阻塞翻译线程）
        QMessageBox.warning(
            self,
            "网络异常 - 翻译已暂停",
            f"检测到网络连接异常，翻译已自动暂停。\n\n"
            f"原因：{reason}\n\n"
            f"翻译将在网络恢复后自动继续，请检查网络连接。",
        )

    def _on_network_resumed(self):
        """网络恢复信号处理"""
        self._on_log("[成功] 网络恢复，继续翻译（将自动重试失败的段落）")

    def _on_watchdog_timeout(self):
        """看门狗超时 - 安全停止"""
        self._on_log("[错误] 翻译任务超时（300秒无响应），执行安全停止...")
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

        self._on_log(f"[成功] 翻译完成!")
        self._on_log(f"[统计] 总耗时: {int(total_time)}秒")
        self._on_log(f"[统计] Token: {total_tokens}")
        self._on_log(f"[统计] 输出: {output_path}")

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
            self._on_log(f"[费用] ¥{record.total_cost:.4f}")
        except Exception:
            pass

        # 缓存命中率
        translator = getattr(self.worker, 'translator', None)
        cache_hits = getattr(translator, "translate_cache_call_count", 0) if translator else 0
        total_calls = getattr(translator, "translate_call_count", 0) if translator else 0
        if total_calls > 0:
            hit_rate = cache_hits / total_calls * 100
            self._on_log(f"[缓存] 缓存命中: {cache_hits}/{total_calls} ({hit_rate:.1f}%)")

        # 更新自适应统计 + 文件解锁
        self._update_adaptive_stats()
        FileUnlockManager.release_all_handles()

        self.output_path = output_path

        # 系统通知（窗口非活跃时提醒用户）
        send_notification(
            "BabelDOC 翻译完成",
            f"文件: {Path(output_path).name}\n耗时: {int(total_time)}秒 | Token: {total_tokens}",
        )

        QMessageBox.information(self, "完成", f"翻译已完成!\n\n输出文件: {output_path}")

    def _on_translation_error(self, error_msg: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.stage_label.setText("错误")
        self.progress_label.setText("翻译失败")
        self._on_log(f"[错误] {error_msg}")
        
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

        # 系统通知（窗口非活跃时提醒用户）
        send_notification("BabelDOC 翻译失败", f"错误: {error_msg[:100]}")

        QMessageBox.critical(self, "翻译失败", error_msg)

    def _open_output_dir(self):
        """打开输出目录（安全模式）"""
        if not self.auto_open_output_check.isChecked():
            QMessageBox.information(
                self, "提示", "自动打开输出目录功能已禁用。\n请在设置中启用后再试。"
            )
            return
        try:
            # 1. 优先使用用户选择的输出目录
            if self.output_dir:
                output_dir = Path(self.output_dir)
                if output_dir.exists():
                    subprocess.Popen(
                        ["explorer", str(output_dir)],
                        shell=False,
                        creationflags=0,
                    )
                    return

            # 2. 回退到已翻译的输出文件所在目录
            output_path = getattr(self, "output_path", None)
            if output_path:
                output_path = Path(output_path)
                if output_path.exists():
                    subprocess.Popen(
                        ["explorer", "/select,", str(output_path)],
                        shell=False,
                        creationflags=0,
                    )
                    return
                # 输出文件不存在，尝试其父目录
                if output_path.parent.exists():
                    subprocess.Popen(
                        ["explorer", str(output_path.parent)],
                        shell=False,
                        creationflags=0,
                    )
                    return

            # 3. 回退到输入文件所在目录
            if self.input_file:
                input_dir = Path(self.input_file).parent
                if input_dir.exists():
                    subprocess.Popen(
                        ["explorer", str(input_dir)],
                        shell=False,
                        creationflags=0,
                    )
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
                total_chars = DEFAULT_CHAR_COUNT  # 默认值

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
            comparisons = analyzer.get_model_comparison(COMPARISON_CHAR_COUNT)

            text = f"[统计] {COMPARISON_CHAR_COUNT} 字符翻译成本对比:\n\n"
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
                self.ocr_status_label.setText("[警告] 检测到扫描件")
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
                self.ocr_status_label.setText("[成功] 文字版 PDF")
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

    def _save_settings(self, silent: bool = False):
        """保存当前配置

        Args:
            silent: 为静默保存（不显示弹窗），用于关闭窗口时自动保存
        """
        import json
        settings = {
            "provider": self.provider_combo.currentText(),
            "model": self.model_combo.currentText(),
            "base_url": self.base_url_edit.text(),
            "model_name": self.model_name_edit.text(),
            "lang_in": self.lang_in_combo.currentText(),
            "lang_out": self.lang_out_combo.currentText(),
            "pages": self.pages_edit.text(),
            "dual": self.dual_checkbox.isChecked(),
            "mono": self.mono_checkbox.isChecked(),
            "qps": self.qps_spin.value(),
            "output_dir": self.output_dir,
            "auto_open_output_dir": self.auto_open_output_check.isChecked(),
        }
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            # 使用 config_manager 保存 API key 和设置
            api_key = self.api_key_edit.text()
            self.config_manager.update_last_session(
                api_key=api_key,
                auto_open_output_dir=self.auto_open_output_check.isChecked(),
            )
            self.config_manager.save()
            if not silent:
                QMessageBox.information(self, "保存成功", f"配置已保存到:\n{self.settings_file}")
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, "保存失败", str(e))
            else:
                logging.getLogger(__name__).warning("保存设置失败: %s", e)

    def _load_settings(self):
        """加载已保存的配置"""
        import json

        # 无论 settings_file 是否存在，都先从 config_manager 加载 API Key
        api_key_from_config = self.config_manager.config.last_session.api_key

        if not self.settings_file.exists():
            # 默认选中 LongCat-2.0
            self.provider_combo.setCurrentText("LongCat")
            self._on_model_changed("LongCat-2.0")
            # 加载保存的 API Key
            if api_key_from_config:
                self.api_key_edit.setText(api_key_from_config)
            return

        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            # 恢复供应商筛选
            saved_provider = settings.get("provider", "全部")
            self.provider_combo.setCurrentText(saved_provider)

            self.model_combo.setCurrentText(settings.get("model", "LongCat-2.0"))
            # 优先从 config_manager 加载 API Key（更安全）
            if api_key_from_config:
                self.api_key_edit.setText(api_key_from_config)
            else:
                # 回退到 settings_file 中的 API Key
                self.api_key_edit.setText(settings.get("api_key", ""))
            self.base_url_edit.setText(settings.get("base_url", ""))
            self.model_name_edit.setText(settings.get("model_name", ""))
            self.lang_in_combo.setCurrentText(settings.get("lang_in", "English"))
            self.lang_out_combo.setCurrentText(settings.get("lang_out", "中文"))
            self.pages_edit.setText(settings.get("pages", ""))
            self.dual_checkbox.setChecked(settings.get("dual", True))
            self.mono_checkbox.setChecked(settings.get("mono", True))
            self.qps_spin.setValue(settings.get("qps", 10))
            self.auto_open_output_check.setChecked(
                settings.get("auto_open_output_dir", True)
            )

            if settings.get("output_dir"):
                self.output_dir = settings["output_dir"]
                self.output_dir_label.setText(f"输出: {self.output_dir}")

            self._on_model_changed(settings.get("model", "LongCat-2.0"))
        except Exception:
            self.provider_combo.setCurrentText("LongCat")
            self._on_model_changed("LongCat-2.0")
            if api_key_from_config:
                self.api_key_edit.setText(api_key_from_config)

    def closeEvent(self, event):
        """关闭窗口时停止工作线程并自动保存设置"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(CLOSE_WAIT_TIMEOUT_MS)
        # 自动保存设置（静默保存，不阻塞关闭）
        try:
            self._save_settings(silent=True)
        except Exception as e:
            logging.getLogger(__name__).warning("关闭时保存设置失败: %s", e)
        event.accept()