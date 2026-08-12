"""BabelDOC PDF 翻译工具 - GUI 入口"""
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gui.main_window import MainWindow
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


def main():
    # 启用高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("BabelDOC PDF 翻译工具")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("BabelDOC")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()