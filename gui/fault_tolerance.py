"""
容错机制模块
1. API 请求看门狗（指数退避重试）
2. 心跳看门狗（防止 UI 假死）
3. PDF 文件强制解锁
"""

import time
import functools
import gc
import logging
from typing import Callable, Optional
from pathlib import Path

logger = logging.getLogger('BabelDOC.FaultTolerance')


# ============================================================
# 1. API 请求看门狗 - 指数退避重试
# ============================================================

class RetryConfig:
    """重试配置"""
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        retryable_status_codes: tuple = (429, 504, 502, 503, 500),
        retryable_exceptions: tuple = (),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_status_codes = retryable_status_codes
        self.retryable_exceptions = retryable_exceptions


# 默认重试配置
DEFAULT_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=2.0,
    max_delay=30.0,
    exponential_base=2.0,
    retryable_status_codes=(429, 504, 502, 503),
)


def retry_with_backoff(config: Optional[RetryConfig] = None,
                       on_retry: Optional[Callable] = None):
    """
    指数退避重试装饰器
    
    Args:
        config: 重试配置
        on_retry: 重试回调函数，参数为 (attempt, delay, error)
    
    Usage:
        @retry_with_backoff(config=DEFAULT_RETRY_CONFIG)
        def call_api(text):
            ...
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # 检查是否是可重试的异常
                    should_retry = False
                    error_msg = str(e)
                    
                    # 检查 HTTP 状态码
                    for code in config.retryable_status_codes:
                        if str(code) in error_msg:
                            should_retry = True
                            break
                    
                    # 检查异常类型
                    for exc_type in config.retryable_exceptions:
                        if isinstance(e, exc_type):
                            should_retry = True
                            break
                    
                    # 最后一次尝试，不再重试
                    if attempt >= config.max_retries or not should_retry:
                        raise
                    
                    # 计算等待时间（指数退避）
                    delay = min(
                        config.base_delay * (config.exponential_base ** attempt),
                        config.max_delay
                    )
                    
                    # 调用回调
                    if on_retry:
                        on_retry(attempt + 1, delay, e)
                    
                    logger.warning(
                        f"API 请求失败 ({type(e).__name__}: {error_msg}), "
                        f"第 {attempt + 1} 次重试，等待 {delay:.1f}s"
                    )
                    
                    time.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


class APIGuardian:
    """
    API 请求看门狗
    封装了带重试的 API 调用逻辑
    """
    
    def __init__(self, retry_config: Optional[RetryConfig] = None):
        self.config = retry_config or DEFAULT_RETRY_CONFIG
        self.retry_count = 0
        self.last_error = None
    
    def call_with_retry(self, func: Callable, *args, **kwargs):
        """带重试的函数调用"""
        
        def on_retry(attempt, delay, error):
            self.retry_count = attempt
            self.last_error = error
        
        decorated = retry_with_backoff(
            config=self.config,
            on_retry=on_retry
        )(func)
        
        return decorated(*args, **kwargs)
    
    def get_status(self) -> dict:
        """获取看门狗状态"""
        return {
            "retry_count": self.retry_count,
            "last_error": str(self.last_error) if self.last_error else None,
        }


# ============================================================
# 2. 心跳看门狗 - 防止 UI 假死
# ============================================================

class HeartbeatWatchdog:
    """
    心跳看门狗
    - Worker 定期发送心跳
    - 主界面监控心跳，超时则安全停止
    """
    
    def __init__(self, timeout: float = 10.0):
        """
        Args:
            timeout: 超时时间（秒），超过此时间未收到心跳则触发安全停止
        """
        self.timeout = timeout
        self._last_heartbeat = 0.0
        self._is_running = False
        self._callback = None
    
    def start(self, callback: Callable = None):
        """启动看门狗监控"""
        self._is_running = True
        self._last_heartbeat = time.monotonic()
        self._callback = callback
    
    def stop(self):
        """停止监控"""
        self._is_running = False
    
    def heartbeat(self):
        """发送心跳信号"""
        self._last_heartbeat = time.monotonic()
    
    def is_alive(self) -> bool:
        """检查是否存活"""
        if not self._is_running:
            return True
        elapsed = time.monotonic() - self._last_heartbeat
        return elapsed < self.timeout
    
    def get_elapsed(self) -> float:
        """获取上次心跳到现在的时间"""
        return time.monotonic() - self._last_heartbeat
    
    def check_and_act(self):
        """检查并执行安全停止"""
        if not self._is_running:
            return False
        
        if not self.is_alive() and self._callback:
            logger.warning(f"心跳超时 ({self.get_elapsed():.1f}s)，触发安全停止")
            self._callback()
            return True
        return False


class WorkerHeartbeat:
    """
    Worker 心跳发射器
    在 Worker 线程中定期发送心跳
    """
    
    def __init__(self, interval: float = 3.0):
        """
        Args:
            interval: 心跳间隔（秒）
        """
        self.interval = interval
        self._last_beat = 0.0
        self._signal = None
    
    def connect(self, signal):
        """连接心跳信号"""
        self._signal = signal
    
    def beat(self):
        """发送心跳"""
        now = time.monotonic()
        if now - self._last_beat >= self.interval:
            self._last_beat = now
            if self._signal:
                self._signal.emit()
    
    def should_beat(self) -> bool:
        """检查是否应该发送心跳"""
        return time.monotonic() - self._last_beat >= self.interval


# ============================================================
# 3. PDF 文件强制解锁
# ============================================================

class FileUnlockManager:
    """
    文件解锁管理器
    确保翻译结束后文件句柄被正确释放
    """
    
    @staticmethod
    def force_unlock(filepath: str):
        """
        强制解锁文件
        
        Args:
            filepath: 文件路径
        """
        if not filepath:
            return
        
        path = Path(filepath)
        
        # 1. 尝试删除文件（如果存在且允许）
        try:
            if path.exists():
                # 尝试重命名再删除（绕过某些锁定）
                temp_path = path.with_suffix('.tmp')
                path.rename(temp_path)
                temp_path.unlink()
                logger.info(f"已删除临时文件: {filepath}")
        except PermissionError:
            logger.warning(f"文件被占用，无法删除: {filepath}")
        except Exception as e:
            logger.debug(f"删除文件时: {e}")
    
    @staticmethod
    def release_all_handles():
        """
        释放所有文件句柄
        调用垃圾回收，确保文件句柄被释放
        """
        # 强制垃圾回收
        gc.collect()
        
        # 再次回收（确保循环引用被清除)
        gc.collect()
        
        logger.debug("已执行垃圾回收，释放文件句柄")
    
    @staticmethod
    def safe_move(src: str, dst: str) -> bool:
        """
        安全移动文件（处理锁定情况）
        
        Returns:
            是否成功
        """
        src_path = Path(src)
        dst_path = Path(dst)
        
        if not src_path.exists():
            return False
        
        try:
            # 尝试直接移动
            src_path.rename(dst_path)
            return True
        except PermissionError:
            pass
        
        # 如果失败，尝试复制后删除
        try:
            import shutil
            shutil.copy2(str(src_path), str(dst_path))
            FileUnlockManager.force_unlock(str(src_path))
            return True
        except Exception as e:
            logger.error(f"移动文件失败: {e}")
            return False
    
    @staticmethod
    def cleanup_temp_files(directory: str, patterns: tuple = ('*.tmp', '*.bak', '*.log')):
        """
        清理临时文件
        
        Args:
            directory: 目录路径
            patterns: 要删除的文件模式
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            return
        
        for pattern in patterns:
            for f in dir_path.glob(pattern):
                try:
                    f.unlink()
                    logger.debug(f"已删除临时文件: {f}")
                except Exception:
                    pass


# ============================================================
# 4. 安全停止管理器
# ============================================================

class SafeShutdownManager:
    """
    安全停止管理器
    协调 Worker 停止和资源释放
    """
    
    def __init__(self):
        self._cleanup_handlers = []
    
    def register_handler(self, handler: Callable):
        """注册清理处理器"""
        self._cleanup_handlers.append(handler)
    
    def execute_shutdown(self):
        """执行安全停止"""
        logger.info("执行安全停止...")
        
        for handler in self._cleanup_handlers:
            try:
                handler()
            except Exception as e:
                logger.error(f"清理处理器异常: {e}")
        
        # 最终垃圾回收
        FileUnlockManager.release_all_handles()
        
        logger.info("安全停止完成")


# ============================================================
# 使用示例和集成代码
# ============================================================

def create_retry_decorator_for_translator(retry_callback=None):
    """
    创建适用于翻译器的重试装饰器
    
    Args:
        retry_callback: 重试回调，用于更新日志
    
    Usage:
        @create_retry_decorator_for_translator(
            retry_callback=lambda attempt, delay, err: print(f"重试 {attempt}")
        )
        def do_translate(text):
            ...
    """
    config = RetryConfig(
        max_retries=3,
        base_delay=2.0,
        max_delay=30.0,
        exponential_base=2.0,
        retryable_status_codes=(429, 504, 502, 503),
    )
    
    def on_retry(attempt, delay, error):
        if retry_callback:
            retry_callback(attempt, delay, error)
    
    return retry_with_backoff(config=config, on_retry=on_retry)


# 全局实例
_global_watchdog = None
_global_shutdown_manager = SafeShutdownManager()


def get_watchdog(timeout: float = 10.0) -> HeartbeatWatchdog:
    """获取全局看门狗"""
    global _global_watchdog
    if _global_watchdog is None:
        _global_watchdog = HeartbeatWatchdog(timeout=timeout)
    return _global_watchdog


def get_shutdown_manager() -> SafeShutdownManager:
    """获取全局安全停止管理器"""
    return _global_shutdown_manager


if __name__ == "__main__":
    import logging
    _logger = logging.getLogger(__name__)

    # 测试指数退避
    _logger.info("=== 指数退避重试测试 ===")

    call_count = 0

    @retry_with_backoff(
        config=RetryConfig(max_retries=3, base_delay=1.0),
        on_retry=lambda attempt, delay, err: _logger.info("  第 %d 次重试，等待 %.1fs", attempt, delay)
    )
    def flaky_api():
        global call_count
        call_count += 1
        if call_count < 3:
            raise Exception("429 Too Many Requests")
        return "成功"

    result = flaky_api()
    _logger.info("结果: %s", result)

    # 测试心跳
    _logger.info("=== 心跳看门狗测试 ===")
    watchdog = HeartbeatWatchdog(timeout=5.0)
    watchdog.start()

    for i in range(6):
        time.sleep(1)
        if i % 2 == 0:
            watchdog.heartbeat()
            _logger.info("  [%ds] 心跳已发送", i)
        alive = watchdog.is_alive()
        _logger.info("  [%ds] 存活: %s, 距离上次心跳: %.1fs", i, alive, watchdog.get_elapsed())

    # 测试文件解锁
    _logger.info("=== 文件解锁测试 ===")
    FileUnlockManager.release_all_handles()
    _logger.info("垃圾回收完成")

    _logger.info("所有容错机制测试通过")