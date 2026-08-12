"""
BabelDOC AI 翻译工具 - 主入口
打包入口点
"""
import sys
import os
import logging
from pathlib import Path

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 设置配置文件目录（打包后也能正确找到）
if getattr(sys, 'frozen', False):
    # 打包后的环境
    os.environ['BABELDOC_CONFIG_DIR'] = str(Path(sys._MEIPASS) / 'data')
else:
    # 开发环境
    pass

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('BabelDOC')


def global_exception_hook(exc_type, exc_value, exc_traceback):
    """全局异常钩子 - 捕获未处理异常，防止闪退"""
    import traceback
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logger.error(f"未捕获的异常:\n{error_msg}")
    
    # 尝试显示错误对话框
    try:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            "程序异常",
            f"发生未预期的错误:\n\n{exc_type.__name__}: {exc_value}\n\n"
            f"请查看日志获取详细信息。"
        )
    except Exception:
        pass  # 如果连对话框都显示失败，至少记录了日志


# 安装全局异常钩子
sys.excepthook = global_exception_hook


# ============================================================
# 探针 5 加固：字体缺失预检机制
# Windows 中文环境下 simsun.ttc 缺失会导致渲染崩溃
# ============================================================

class FontManager:
    """系统字体预检与安全回退管理器"""

    # 安全字体优先级列表（Windows）
    SAFE_FONTS = [
        "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        "C:/Windows/Fonts/msyhbd.ttc",    # 微软雅黑粗体
        "C:/Windows/Fonts/simsun.ttc",    # 宋体
        "C:/Windows/Fonts/simhei.ttf",    # 黑体
        "C:/Windows/Fonts/arial.ttf",     # Arial
    ]

    @classmethod
    def precheck(cls) -> tuple:
        """启动前预检系统字体可用性。

        Returns:
            (ok: bool, fallback_font: str, message: str)
        """
        import os
        import pathlib

        if os.name != 'nt':
            return True, "", "非 Windows 环境，跳过字体预检"

        # 检查宋体（BabelDOC 默认依赖）
        simsun = pathlib.Path("C:/Windows/Fonts/simsun.ttc")
        msyh = pathlib.Path("C:/Windows/Fonts/msyh.ttc")

        if simsun.exists():
            return True, str(simsun), "字体预检通过"

        # 宋体缺失，寻找回退字体
        for font_path in cls.SAFE_FONTS:
            if pathlib.Path(font_path).exists():
                # 强制设置环境变量，让 BabelDOC 回退
                os.environ.setdefault("BABELDOC_FALLBACK_FONT", font_path)
                msg = f"检测到字体缺失（simsun.ttc），已自动切换至安全字体: {font_path}"
                logger.warning(msg)
                return False, font_path, msg

        return False, "", "严重: 未找到任何可用中文字体，渲染可能异常"

    @classmethod
    def install_to_qapplication(cls, app):
        """将安全字体注入 QApplication 作为默认字体"""
        try:
            ok, fallback, _ = cls.precheck()
            if not ok and fallback:
                from PyQt6.QtGui import QFontDatabase, QFont
                font_db = QFontDatabase()
                family = QFontDatabase.families(font_db)
                # 优先使用微软雅黑
                for candidate in ("Microsoft YaHei", "微软雅黑", "SimHei", "黑体"):
                    if candidate in family:
                        app.setFont(QFont(candidate))
                        return
        except Exception as e:
            logger.debug(f"字体注入失败: {e}")


def main():
    """主函数"""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    # 探针 5 加固：启动前字体预检
    font_ok, fallback_font, font_msg = FontManager.precheck()
    if not font_ok:
        logger.warning(font_msg)

    from gui.main_window import MainWindow

    logger.info("启动 BabelDOC AI 翻译工具")

    # 启用高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("BabelDOC AI 翻译工具")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("BabelDOC")

    # 探针 5 加固：注入安全字体
    if not font_ok:
        FontManager.install_to_qapplication(app)

    # 设置应用图标（如果有）
    icon_path = PROJECT_ROOT / "resources" / "icon.ico"
    if icon_path.exists():
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    # 探针 5 加固：字体缺失时弹窗提示
    if not font_ok and fallback_font:
        try:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                window,
                "字体提示",
                f"检测到字体缺失，已自动切换至安全字体:\n{fallback_font}\n\n"
                "翻译功能可正常使用，如需恢复最佳排版请安装宋体字体。",
            )
        except Exception:
            pass

    logger.info("主窗口已显示")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()