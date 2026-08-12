"""
翻译质量与记忆管理对话框
包括：翻译记忆库管理、术语库管理、QA 设置
"""

from pathlib import Path
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QLineEdit, QPushButton, QTableView,
    QMessageBox, QFileDialog, QComboBox, QTextEdit,
    QCheckBox, QSpinBox, QGroupBox, QHeaderView,
    QFormLayout, QWidget, QSplitter, QTextBrowser,
)

from gui.core import TranslationMemory, GlossaryManager, TMEntry, GlossaryEntry
from gui.core.quality import QAChecker, QualityScorer, Severity


class TMTableModel(QAbstractTableModel):
    """翻译记忆表格模型"""

    def __init__(self, entries: list = None):
        super().__init__()
        self.entries = entries or []
        self.headers = ["ID", "源文本", "译文", "语言对", "领域", "使用次数", "评分"]

    def rowCount(self, parent=QModelIndex()):
        return len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.entries):
            return None

        entry = self.entries[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return entry.id
            elif col == 1:
                return entry.source_text[:80] + "..." if len(entry.source_text) > 80 else entry.source_text
            elif col == 2:
                return entry.target_text[:80] + "..." if len(entry.target_text) > 80 else entry.target_text
            elif col == 3:
                return f"{entry.lang_in} → {entry.lang_out}"
            elif col == 4:
                return entry.domain or "-"
            elif col == 5:
                return entry.used_count
            elif col == 6:
                return f"{entry.score:.2f}"

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None


class GlossaryTableModel(QAbstractTableModel):
    """术语库表格模型"""

    def __init__(self, entries: list = None):
        super().__init__()
        self.entries = entries or []
        self.headers = ["ID", "术语", "翻译", "语言对", "领域", "描述"]

    def rowCount(self, parent=QModelIndex()):
        return len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.entries):
            return None

        entry = self.entries[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return entry.id
            elif col == 1:
                return entry.term
            elif col == 2:
                return entry.translation
            elif col == 3:
                return f"{entry.lang_in} → {entry.lang_out}"
            elif col == 4:
                return entry.domain or "-"
            elif col == 5:
                return entry.description[:50] if entry.description else "-"

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None


class QualityDialog(QDialog):
    """翻译质量管理主对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("翻译质量与记忆管理")
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)

        # 初始化核心模块
        self.tm = TranslationMemory()
        self.glossary = GlossaryManager()
        self.qa_checker = QAChecker()
        self.quality_scorer = QualityScorer()

        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 标签页
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_tm_tab(), "翻译记忆库")
        self.tabs.addTab(self._create_glossary_tab(), "术语库")
        self.tabs.addTab(self._create_qa_tab(), "QA 检查与评分")
        self.tabs.addTab(self._create_stats_tab(), "统计信息")
        layout.addWidget(self.tabs)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setMinimumWidth(80)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    # ============================================================
    # 翻译记忆库标签页
    # ============================================================

    def _create_tm_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 工具栏
        toolbar = QHBoxLayout()

        self.tm_search = QLineEdit()
        self.tm_search.setPlaceholderText("搜索源文本或译文...")
        self.tm_search.textChanged.connect(self._filter_tm)
        toolbar.addWidget(self.tm_search, 1)

        toolbar.addWidget(QLabel("语言:"))
        self.tm_lang_filter = QComboBox()
        self.tm_lang_filter.addItems(["全部", "en → zh", "zh → en", "ja → zh", "ko → zh"])
        self.tm_lang_filter.currentTextChanged.connect(self._filter_tm)
        toolbar.addWidget(self.tm_lang_filter)

        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._add_tm_entry)
        toolbar.addWidget(add_btn)

        import_btn = QPushButton("导入")
        import_btn.clicked.connect(self._import_tm)
        toolbar.addWidget(import_btn)

        export_btn = QPushButton("导出")
        export_btn.clicked.connect(self._export_tm)
        toolbar.addWidget(export_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_tm)
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        # 表格
        self.tm_table = QTableView()
        self.tm_table.setAlternatingRowColors(True)
        self.tm_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tm_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.tm_table.horizontalHeader().setStretchLastSection(True)
        self.tm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tm_table.setStyleSheet("""
            QTableView {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            QTableView::item:selected {
                background-color: #E3F2FD;
            }
        """)
        layout.addWidget(self.tm_table)

        return widget

    def _filter_tm(self):
        """过滤 TM 条目"""
        search_text = self.tm_search.text().lower()
        lang_filter = self.tm_lang_filter.currentText()

        all_entries = self.tm.get_stats()  # 简化：实际应该获取所有条目
        # 这里简化处理，实际应该从数据库获取
        filtered = []
        # TODO: 实现完整过滤逻辑

        model = TMTableModel(filtered)
        self.tm_table.setModel(model)

    def _add_tm_entry(self):
        """添加 TM 条目"""
        dialog = AddTMDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if self.tm.add_translation(**data):
                QMessageBox.information(self, "成功", "翻译记忆条目已添加")
                self._load_data()
            else:
                QMessageBox.warning(self, "失败", "添加失败，请检查输入")

    def _import_tm(self):
        """导入翻译记忆"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入翻译记忆", "",
            "JSON Files (*.json);;CSV Files (*.csv);;TMX Files (*.tmx);;All Files (*)"
        )
        if filepath:
            count = self.tm.import_tm(filepath)
            QMessageBox.information(self, "导入完成", f"成功导入 {count} 条翻译记忆")
            self._load_data()

    def _export_tm(self):
        """导出翻译记忆"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出翻译记忆", "",
            "JSON Files (*.json);;CSV Files (*.csv);;TMX Files (*.tmx)"
        )
        if filepath:
            ext = Path(filepath).suffix.lower()
            fmt = {"json": "json", "csv": "csv", "tmx": "tmx"}.get(ext[1:], "json")
            self.tm.export_tm(filepath, fmt)
            QMessageBox.information(self, "导出完成", f"已导出到: {filepath}")

    def _clear_tm(self):
        """清空翻译记忆"""
        reply = QMessageBox.question(
            self, "确认清空",
            "确定要清空所有翻译记忆吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tm.clear()
            self._load_data()

    # ============================================================
    # 术语库标签页
    # ============================================================

    def _create_glossary_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 工具栏
        toolbar = QHBoxLayout()

        self.glossary_search = QLineEdit()
        self.glossary_search.setPlaceholderText("搜索术语...")
        self.glossary_search.textChanged.connect(self._filter_glossary)
        toolbar.addWidget(self.glossary_search, 1)

        add_btn = QPushButton("添加术语")
        add_btn.clicked.connect(self._add_glossary_entry)
        toolbar.addWidget(add_btn)

        import_btn = QPushButton("导入")
        import_btn.clicked.connect(self._import_glossary)
        toolbar.addWidget(import_btn)

        export_btn = QPushButton("导出")
        export_btn.clicked.connect(self._export_glossary)
        toolbar.addWidget(export_btn)

        layout.addLayout(toolbar)

        # 表格
        self.glossary_table = QTableView()
        self.glossary_table.setAlternatingRowColors(True)
        self.glossary_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.glossary_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.glossary_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.glossary_table)

        return widget

    def _filter_glossary(self):
        """过滤术语"""
        search_text = self.glossary_search.text().lower()
        # 重新加载并过滤
        entries = self.glossary.get_all_terms()
        if search_text:
            entries = [e for e in entries
                       if search_text in e.term.lower() or search_text in e.translation.lower()]
        model = GlossaryTableModel(entries)
        self.glossary_table.setModel(model)

    def _add_glossary_entry(self):
        """添加术语"""
        dialog = AddGlossaryDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if self.glossary.add_term(**data):
                QMessageBox.information(self, "成功", "术语已添加")
                self._load_data()
            else:
                QMessageBox.warning(self, "失败", "添加失败")

    def _import_glossary(self):
        """导入术语库"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入术语库", "",
            "CSV Files (*.csv);;JSON Files (*.json);;TBX Files (*.tbx);;All Files (*)"
        )
        if filepath:
            count = self.glossary.import_glossary(filepath)
            QMessageBox.information(self, "导入完成", f"成功导入 {count} 条术语")
            self._load_data()

    def _export_glossary(self):
        """导出术语库"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出术语库", "",
            "CSV Files (*.csv);;JSON Files (*.json)"
        )
        if filepath:
            ext = Path(filepath).suffix.lower()
            fmt = "csv" if ext == ".csv" else "json"
            self.glossary.export_glossary(filepath, fmt)
            QMessageBox.information(self, "导出完成", f"已导出到: {filepath}")

    # ============================================================
    # QA 检查标签页
    # ============================================================

    def _create_qa_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # QA 规则配置
        rules_group = QGroupBox("QA 检查规则")
        rules_layout = QVBoxLayout(rules_group)

        self.qa_rules = {
            "空翻译检查": QCheckBox("检查空翻译（源文有内容但译文为空）"),
            "长度异常检查": QCheckBox("检查译文长度异常（过长或过短）"),
            "数字一致性": QCheckBox("检查数字在译文中是否一致"),
            "标点符号": QCheckBox("检查标点符号一致性"),
            "格式标签": QCheckBox("检查 HTML/格式标签一致性"),
            "重复词语": QCheckBox("检查译文中是否有重复词语"),
            "未翻译检测": QCheckBox("检测可能未翻译的内容"),
            "空格一致性": QCheckBox("检查首尾空格一致性"),
        }

        for name, checkbox in self.qa_rules.items():
            checkbox.setChecked(True)
            rules_layout.addWidget(checkbox)

        layout.addWidget(rules_group)

        # 快速测试区域
        test_group = QGroupBox("快速测试")
        test_layout = QVBoxLayout(test_group)

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("源文:"))
        self.qa_source = QLineEdit()
        self.qa_source.setPlaceholderText("输入源文本...")
        input_row.addWidget(self.qa_source)
        test_layout.addLayout(input_row)

        input_row2 = QHBoxLayout()
        input_row2.addWidget(QLabel("译文:"))
        self.qa_target = QLineEdit()
        self.qa_target.setPlaceholderText("输入译文...")
        input_row2.addWidget(self.qa_target)
        test_layout.addLayout(input_row2)

        test_btn = QPushButton("执行 QA 检查")
        test_btn.clicked.connect(self._run_qa_test)
        test_layout.addWidget(test_btn)

        # 结果显示
        self.qa_result = QTextBrowser()
        self.qa_result.setReadOnly(True)
        self.qa_result.setMaximumHeight(150)
        self.qa_result.setStyleSheet("""
            QTextBrowser {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: #fafafa;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        test_layout.addWidget(self.qa_result)

        layout.addWidget(test_group)
        layout.addStretch()

        return widget

    def _run_qa_test(self):
        """执行 QA 测试"""
        source = self.qa_source.text().strip()
        target = self.qa_target.text().strip()

        if not source:
            QMessageBox.warning(self, "提示", "请输入源文本")
            return

        issues = self.qa_checker.check(source, target)

        if not issues:
            self.qa_result.setHtml(
                '<p style="color: #4CAF50;">✅ 未发现质量问题</p>'
            )
            return

        html = ["<p><b>发现问题:</b></p><ul>"]
        for issue in issues:
            color = {
                Severity.CRITICAL: "#D32F2F",
                Severity.ERROR: "#F57C00",
                Severity.WARNING: "#FBC02D",
                Severity.INFO: "#1976D2",
            }.get(severity := issue.severity, "#333")

            html.append(
                f'<li style="color: {color};">'
                f'<b>[{issue.severity.value.upper()}] {issue.rule_name}</b>: '
                f'{issue.message}'
                f'{f"<br/><i>建议: {issue.suggestion}</i>" if issue.suggestion else ""}'
                f'</li>'
            )
        html.append("</ul>")

        self.qa_result.setHtml("".join(html))

    # ============================================================
    # 统计信息标签页
    # ============================================================

    def _create_stats_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # TM 统计
        tm_group = QGroupBox("翻译记忆库统计")
        tm_layout = QVBoxLayout(tm_group)
        self.tm_stats_label = QLabel()
        self.tm_stats_label.setStyleSheet("font-size: 13px; line-height: 1.6;")
        tm_layout.addWidget(self.tm_stats_label)
        layout.addWidget(tm_group)

        # 术语库统计
        gl_group = QGroupBox("术语库统计")
        gl_layout = QVBoxLayout(gl_group)
        self.gl_stats_label = QLabel()
        self.gl_stats_label.setStyleSheet("font-size: 13px; line-height: 1.6;")
        gl_layout.addWidget(self.gl_stats_label)
        layout.addWidget(gl_group)

        layout.addStretch()
        return widget

    def _load_data(self):
        """加载数据"""
        # 加载术语库
        entries = self.glossary.get_all_terms()
        model = GlossaryTableModel(entries)
        self.glossary_table.setModel(model)

        # 更新统计
        tm_stats = self.tm.get_stats()
        self.tm_stats_label.setText(
            f"总条目数: {tm_stats['total_entries']}<br>"
            f"总使用次数: {tm_stats['total_usage']}<br>"
            f"语言对: {', '.join(f'{l[0]}→{l[1]}({l[2]})' for l in tm_stats['by_language'][:5])}<br>"
            f"领域: {', '.join(f'{d[0]}({d[1]})' for d in tm_stats['by_domain'][:5])}"
        )

        gl_stats = self.glossary.get_stats()
        self.gl_stats_label.setText(
            f"总术语数: {gl_stats['total_terms']}<br>"
            f"语言对: {', '.join(f'{l[0]}→{l[1]}({l[2]})' for l in gl_stats['by_language'][:5])}<br>"
            f"领域: {', '.join(f'{d[0]}({d[1]})' for d in gl_stats['by_domain'][:5])}"
        )


class AddTMDialog(QDialog):
    """添加翻译记忆条目对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加翻译记忆")
        self.setMinimumWidth(500)
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)

        self.source_edit = QTextEdit()
        self.source_edit.setMaximumHeight(80)
        self.source_edit.setPlaceholderText("源文本...")
        layout.addRow("源文本:", self.source_edit)

        self.target_edit = QTextEdit()
        self.target_edit.setMaximumHeight(80)
        self.target_edit.setPlaceholderText("译文...")
        layout.addRow("译文:", self.target_edit)

        self.lang_in = QComboBox()
        self.lang_in.addItems(["en", "zh", "ja", "ko", "fr", "de", "es", "ru"])
        layout.addRow("源语言:", self.lang_in)

        self.lang_out = QComboBox()
        self.lang_out.addItems(["zh", "en", "ja", "ko", "fr", "de", "es", "ru"])
        self.lang_out.setCurrentText("zh")
        layout.addRow("目标语言:", self.lang_out)

        self.domain_edit = QLineEdit()
        self.domain_edit.setPlaceholderText("领域（如：医学、法律、IT）")
        layout.addRow("领域:", self.domain_edit)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def get_data(self) -> dict:
        return {
            "source": self.source_edit.toPlainText().strip(),
            "target": self.target_edit.toPlainText().strip(),
            "lang_in": self.lang_in.currentText(),
            "lang_out": self.lang_out.currentText(),
            "domain": self.domain_edit.text().strip(),
        }


class AddGlossaryDialog(QDialog):
    """添加术语对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加术语")
        self.setMinimumWidth(450)
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)

        self.term_edit = QLineEdit()
        self.term_edit.setPlaceholderText("术语...")
        layout.addRow("术语:", self.term_edit)

        self.translation_edit = QLineEdit()
        self.translation_edit.setPlaceholderText("翻译...")
        layout.addRow("翻译:", self.translation_edit)

        self.lang_in = QComboBox()
        self.lang_in.addItems(["en", "zh", "ja", "ko", "fr", "de", "es", "ru"])
        layout.addRow("源语言:", self.lang_in)

        self.lang_out = QComboBox()
        self.lang_out.addItems(["zh", "en", "ja", "ko", "fr", "de", "es", "ru"])
        self.lang_out.setCurrentText("zh")
        layout.addRow("目标语言:", self.lang_out)

        self.domain_edit = QLineEdit()
        self.domain_edit.setPlaceholderText("领域（可选）")
        layout.addRow("领域:", self.domain_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("描述（可选）")
        layout.addRow("描述:", self.desc_edit)

        self.case_sensitive = QCheckBox("区分大小写")
        layout.addRow("", self.case_sensitive)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def get_data(self) -> dict:
        return {
            "term": self.term_edit.text().strip(),
            "translation": self.translation_edit.text().strip(),
            "lang_in": self.lang_in.currentText(),
            "lang_out": self.lang_out.currentText(),
            "domain": self.domain_edit.text().strip(),
            "description": self.desc_edit.text().strip(),
            "case_sensitive": self.case_sensitive.isChecked(),
        }