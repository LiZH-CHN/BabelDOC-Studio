"""
日志工具模块
提供统一的日志配置和 get_logger() 函数
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


# ============================================================
# 日志配置常量
# ============================================================
DEFAULT_LOG_LEVEL: int = logging.INFO
DEFAULT_LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
DEFAULT_LOG_FILE_BACKUP_COUNT: int = 5


def get_logger(
    name: str,
    level: int = DEFAULT_LOG_LEVEL,
    log_file: Optional[Path] = None,
    fmt: str = DEFAULT_LOG_FORMAT,
) -> logging.Logger:
    """获取配置好的日志记录器。

    为指定名称的 logger 配置控制台输出和可选的文件输出。
    重复调用不会重复添加 handler。

    Args:
        name: logger 名称（通常使用 __name__）
        level: 日志级别，默认为 INFO
        log_file: 日志文件路径，为 None 时只输出到控制台
        fmt: 日志格式字符串

    Returns:
        配置好的 logging.Logger 实例
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(fmt, datefmt=DEFAULT_DATE_FORMAT))
    logger.addHandler(console_handler)

    # 文件 handler（可选）
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=DEFAULT_LOG_FILE_MAX_BYTES,
                backupCount=DEFAULT_LOG_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(logging.Formatter(fmt, datefmt=DEFAULT_DATE_FORMAT))
            logger.addHandler(file_handler)
        except Exception:
            # 文件 handler 创建失败不影响控制台输出
            pass

    return logger


def setup_root_logger(
    level: int = DEFAULT_LOG_LEVEL,
    log_file: Optional[Path] = None,
) -> None:
    """配置根 logger。

    Args:
        level: 日志级别
        log_file: 日志文件路径
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有 handler
    root_logger.handlers.clear()

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(
        logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
    )
    root_logger.addHandler(console_handler)

    # 文件 handler（可选）
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=DEFAULT_LOG_FILE_MAX_BYTES,
                backupCount=DEFAULT_LOG_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(
                logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
            )
            root_logger.addHandler(file_handler)
        except Exception:
            pass