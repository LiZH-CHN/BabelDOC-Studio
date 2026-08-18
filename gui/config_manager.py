r"""
配置持久化模块
- 保存/加载用户设置到 %APPDATA%\BabelDOC-GUI\config.toml
- 支持 API Key 加密存储
- 记住上次会话的所有配置
"""

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


# ============================================================
# 配置路径
# ============================================================

def get_config_dir() -> Path:
    """获取配置目录。

    根据操作系统返回对应的配置目录路径：
    - Windows: %APPDATA%\\BabelDOC-GUI
    - macOS/Linux: ~/.config/babeldoc-gui

    Returns:
        配置目录路径
    """
    if os.name == 'nt':  # Windows
        appdata = os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')
        config_dir = Path(appdata) / 'BabelDOC-GUI'
    else:  # macOS / Linux
        config_dir = Path.home() / '.config' / 'babeldoc-gui'

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """获取配置文件路径。

    Returns:
        配置文件完整路径
    """
    return get_config_dir() / 'config.toml'


# ============================================================
# 安全存储（使用 keyring 或回退到简单加密）
# ============================================================

class SecureStorage:
    """
    安全存储管理器
    优先使用 keyring（系统密钥存储），不可用时回退到 SimpleEncryptor
    """

    def __init__(self) -> None:
        self._keyring_available: bool = False
        self._encryptor: SimpleEncryptor = SimpleEncryptor()
        self._keyring: Any = None

        try:
            import keyring

            self._keyring = keyring
            self._keyring_available = True
            # 测试 keyring 是否可用
            keyring.get_password("BabelDOC-GUI", "__test__")
        except Exception:
            self._keyring_available = False

    def save_secret(self, name: str, value: str) -> bool:
        """安全保存 API Key。

        优先使用 keyring 存储，失败时返回 False。

        Args:
            name: 密钥名称
            value: 密钥值

        Returns:
            是否保存成功
        """
        if self._keyring_available:
            try:
                self._keyring.set_password("BabelDOC-GUI", name, value)
                return True
            except Exception:
                pass
        # 回退：使用 SimpleEncryptor 加密后保存到配置文件
        return False

    def get_secret(self, name: str) -> Optional[str]:
        """安全读取 API Key。

        Args:
            name: 密钥名称

        Returns:
            密钥值，不存在时返回 None
        """
        if self._keyring_available:
            try:
                value = self._keyring.get_password("BabelDOC-GUI", name)
                if value:
                    return value
            except Exception:
                pass
        return None

    def delete_secret(self, name: str) -> bool:
        """删除 API Key。

        Args:
            name: 密钥名称

        Returns:
            是否删除成功
        """
        if self._keyring_available:
            try:
                self._keyring.delete_password("BabelDOC-GUI", name)
                return True
            except Exception:
                pass
        return False


class SimpleEncryptor:
    """
    简单加密器
    使用 XOR + Base64 编码
    注意：这不是强加密，只是防止明文存储敏感信息
    生产环境建议使用 Windows Credential Manager 或 keyring
    """

    def __init__(self, key: Optional[str] = None) -> None:
        if key is None:
            # 使用机器特定的密钥（基于用户名和机器名）
            import platform
            key = f"{platform.node()}-{os.getlogin()}-BabelDOC-2024"
        self.key: str = key

    def encrypt(self, plaintext: str) -> str:
        """加密字符串。

        使用 XOR + Base64 编码对明文进行加密。

        Args:
            plaintext: 明文字符串

        Returns:
            加密后的 Base64 编码字符串
        """
        if not plaintext:
            return ""

        key_bytes = self.key.encode('utf-8')
        text_bytes = plaintext.encode('utf-8')

        # XOR 加密
        encrypted = bytearray()
        for i, b in enumerate(text_bytes):
            encrypted.append(b ^ key_bytes[i % len(key_bytes)])

        # Base64 编码
        return base64.b64encode(bytes(encrypted)).decode('utf-8')

    def decrypt(self, ciphertext: str) -> str:
        """解密字符串。

        使用 Base64 解码 + XOR 对密文进行解密。

        Args:
            ciphertext: 加密后的 Base64 编码字符串

        Returns:
            解密后的明文字符串，失败时返回空字符串
        """
        if not ciphertext:
            return ""

        try:
            # Base64 解码
            encrypted = base64.b64decode(ciphertext.encode('utf-8'))

            key_bytes = self.key.encode('utf-8')

            # XOR 解密
            decrypted = bytearray()
            for i, b in enumerate(encrypted):
                decrypted.append(b ^ key_bytes[i % len(key_bytes)])

            return bytes(decrypted).decode('utf-8')
        except Exception:
            return ""


# ============================================================
# Windows 凭据管理器集成
# ============================================================

class WindowsCredentialManager:
    """Windows 凭据管理器"""

    def __init__(self):
        self.available = False
        if os.name == 'nt':
            try:
                import ctypes
                self.available = True
            except ImportError:
                pass

    def save_credential(self, name: str, value: str) -> bool:
        """保存凭据到 Windows 凭据管理器"""
        if not self.available:
            return False

        try:
            import ctypes
            import ctypes.wintypes

            # 使用 CredWrite API
            CRED_TYPE_GENERIC = 1
            CRED_PERSIST_LOCAL_MACHINE = 2

            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ("Flags", ctypes.wintypes.DWORD),
                    ("Type", ctypes.wintypes.DWORD),
                    ("TargetName", ctypes.wintypes.LPWSTR),
                    ("Comment", ctypes.wintypes.LPWSTR),
                    ("LastWritten", ctypes.wintypes.FILETIME),
                    ("CredentialBlobSize", ctypes.wintypes.DWORD),
                    ("CredentialBlob", ctypes.LPVOID),
                    ("Persist", ctypes.wintypes.DWORD),
                    ("AttributeCount", ctypes.wintypes.DWORD),
                    ("Attributes", ctypes.LPVOID),
                    ("TargetAlias", ctypes.wintypes.LPWSTR),
                    ("UserName", ctypes.wintypes.LPWSTR),
                ]

            blob = value.encode('utf-16-le')
            blob_size = len(blob)

            cred = CREDENTIAL()
            cred.Type = CRED_TYPE_GENERIC
            cred.TargetName = f"BabelDOC-GUI/{name}"
            cred.CredentialBlobSize = blob_size
            cred.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob), ctypes.LPVOID)
            cred.Persist = CRED_PERSIST_LOCAL_MACHINE
            cred.UserName = "BabelDOC-GUI"

            result = ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0)
            return result != 0

        except Exception:
            return False

    def read_credential(self, name: str) -> Optional[str]:
        """从 Windows 凭据管理器读取凭据"""
        if not self.available:
            return None

        try:
            import ctypes
            import ctypes.wintypes

            CRED_TYPE_GENERIC = 1

            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ("Flags", ctypes.wintypes.DWORD),
                    ("Type", ctypes.wintypes.DWORD),
                    ("TargetName", ctypes.wintypes.LPWSTR),
                    ("Comment", ctypes.wintypes.LPWSTR),
                    ("LastWritten", ctypes.wintypes.FILETIME),
                    ("CredentialBlobSize", ctypes.wintypes.DWORD),
                    ("CredentialBlob", ctypes.LPVOID),
                    ("Persist", ctypes.wintypes.DWORD),
                    ("AttributeCount", ctypes.wintypes.DWORD),
                    ("Attributes", ctypes.LPVOID),
                    ("TargetAlias", ctypes.wintypes.LPWSTR),
                    ("UserName", ctypes.wintypes.LPWSTR),
                ]

            cred_ptr = ctypes.POINTER(CREDENTIAL)()

            target = f"BabelDOC-GUI/{name}"
            result = ctypes.windll.advapi32.CredReadW(
                target, CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr)
            )

            if result == 0:
                return None

            cred = cred_ptr.contents
            blob_size = cred.CredentialBlobSize
            blob_ptr = cred.CredentialBlob

            blob = ctypes.string_at(blob_ptr, blob_size)
            value = blob.decode('utf-16-le')

            ctypes.windll.kernel32.LocalFree(ctypes.c_void_p.from_param(blob_ptr))

            return value

        except Exception:
            return None

    def delete_credential(self, name: str) -> bool:
        """删除凭据"""
        if not self.available:
            return False

        try:
            import ctypes
            target = f"BabelDOC-GUI/{name}"
            result = ctypes.windll.advapi32.CredDeleteW(target, 1, 0)
            return result != 0
        except Exception:
            return False


# ============================================================
# 配置数据类
# ============================================================

@dataclass
class LastSession:
    """上次会话配置"""
    provider: str = "DeepSeek"
    model: str = "deepseek-chat"
    api_key: str = ""
    lang_in: str = "en"
    lang_out: str = "zh"
    qps: int = 4
    enable_glossary: bool = True
    enable_tm: bool = True
    enable_adaptive_mt: bool = True
    enable_qa: bool = True
    enable_ocr: bool = False
    enable_multi_engine: bool = False
    skip_references: bool = True
    engine2_model: str = ""
    multi_strategy: str = "balanced"
    output_dir: str = ""
    window_width: int = 900
    window_height: int = 700
    last_used: float = 0.0
    auto_open_output_dir: bool = True


@dataclass
class CustomProviders:
    """自定义供应商 Base URL"""
    urls: dict = field(default_factory=dict)


@dataclass
class AppConfig:
    """应用完整配置"""
    last_session: LastSession = field(default_factory=LastSession)
    custom_providers: CustomProviders = field(default_factory=CustomProviders)
    recent_files: list = field(default_factory=list)
    auto_save: bool = True
    check_updates: bool = True
    log_level: str = "INFO"
    theme: str = "light"


# ============================================================
# 配置管理器
# ============================================================

class ConfigManager:
    """
    配置管理器
    负责加载、保存、加密/解密配置
    """

    def __init__(self) -> None:
        self.config_path: Path = get_config_path()
        self.config_dir: Path = get_config_dir()
        self.encryptor: SimpleEncryptor = SimpleEncryptor()
        self.win_cred: WindowsCredentialManager = WindowsCredentialManager()
        self.config: AppConfig = AppConfig()
        self._load()

    def _load_api_key(self, encrypted_key: str) -> str:
        """加载 API Key（优先从 Windows 凭据管理器读取，否则解密）

        Args:
            encrypted_key: 加密的 API Key

        Returns:
            解密后的 API Key
        """
        # 优先从 Windows 凭据管理器读取
        if self.win_cred.available:
            cred = self.win_cred.read_credential('api_key')
            if cred:
                return cred

        # 回退到解密
        if encrypted_key:
            return self.encryptor.decrypt(encrypted_key)

        return ""

    def _load(self) -> None:
        """加载配置文件到内存"""
        if not self.config_path.exists():
            self.config = AppConfig()
            return

        try:
            # 尝试使用 toml 库
            try:
                import toml
                data = toml.load(str(self.config_path))
            except ImportError:
                # 回退到 JSON 格式
                import json
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            # 解析 LastSession
            ls_data = data.get('LastSession', {})
            self.config.last_session = LastSession(
                provider=ls_data.get('provider', 'DeepSeek'),
                model=ls_data.get('model', 'deepseek-chat'),
                api_key=self._load_api_key(ls_data.get('api_key', '')),
                lang_in=ls_data.get('lang_in', 'en'),
                lang_out=ls_data.get('lang_out', 'zh'),
                qps=ls_data.get('qps', 4),
                enable_glossary=ls_data.get('enable_glossary', True),
                enable_tm=ls_data.get('enable_tm', True),
                enable_adaptive_mt=ls_data.get('enable_adaptive_mt', True),
                enable_qa=ls_data.get('enable_qa', True),
                enable_ocr=ls_data.get('enable_ocr', False),
                enable_multi_engine=ls_data.get('enable_multi_engine', False),
                skip_references=ls_data.get('skip_references', True),
                engine2_model=ls_data.get('engine2_model', ''),
                multi_strategy=ls_data.get('multi_strategy', 'balanced'),
                output_dir=ls_data.get('output_dir', ''),
                window_width=ls_data.get('window_width', 900),
                window_height=ls_data.get('window_height', 700),
                last_used=ls_data.get('last_used', 0.0),
                auto_open_output_dir=ls_data.get('auto_open_output_dir', True),
            )

            # 解析 CustomProviders
            cp_data = data.get('CustomProviders', {})
            self.config.custom_providers = CustomProviders(
                urls=cp_data.get('urls', {})
            )

            # 其他配置
            self.config.recent_files = data.get('recent_files', [])[-10:]  # 最多 10 个
            self.config.auto_save = data.get('auto_save', True)
            self.config.check_updates = data.get('check_updates', True)
            self.config.log_level = data.get('log_level', 'INFO')
            self.config.theme = data.get('theme', 'light')

        except Exception as e:
            logger.error("加载配置失败: %s，使用默认配置", e)
            self.config = AppConfig()

    def save(self) -> bool:
        """保存配置到文件。

        API Key 优先保存到 Windows 凭据管理器，否则加密存储。

        Returns:
            是否保存成功
        """
        try:
            # 优先将 API Key 保存到 Windows 凭据管理器
            api_key = self.config.last_session.api_key
            if api_key and self.win_cred.available:
                self.win_cred.save_credential('api_key', api_key)
                # 保存成功后，配置文件中只保存占位符
                encrypted_key = "***"
            else:
                # 回退到加密存储
                encrypted_key = self.encryptor.encrypt(api_key)

            data = {
                'LastSession': {
                    'provider': self.config.last_session.provider,
                    'model': self.config.last_session.model,
                    'api_key': encrypted_key,
                    'lang_in': self.config.last_session.lang_in,
                    'lang_out': self.config.last_session.lang_out,
                    'qps': self.config.last_session.qps,
                    'enable_glossary': self.config.last_session.enable_glossary,
                    'enable_tm': self.config.last_session.enable_tm,
                    'enable_adaptive_mt': self.config.last_session.enable_adaptive_mt,
                    'enable_qa': self.config.last_session.enable_qa,
                    'enable_ocr': self.config.last_session.enable_ocr,
                    'enable_multi_engine': self.config.last_session.enable_multi_engine,
                    'skip_references': self.config.last_session.skip_references,
                    'engine2_model': self.config.last_session.engine2_model,
                    'multi_strategy': self.config.last_session.multi_strategy,
                    'output_dir': self.config.last_session.output_dir,
                    'window_width': self.config.last_session.window_width,
                    'window_height': self.config.last_session.window_height,
                    'last_used': time.time(),
                    'auto_open_output_dir': self.config.last_session.auto_open_output_dir,
                },
                'CustomProviders': {
                    'urls': self.config.custom_providers.urls,
                },
                'recent_files': self.config.recent_files[-10:],
                'auto_save': self.config.auto_save,
                'check_updates': self.config.check_updates,
                'log_level': self.config.log_level,
                'theme': self.config.theme,
            }

            # 尝试使用 toml 库
            try:
                import toml
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    toml.dump(data, f)
            except ImportError:
                # 回退到 JSON 格式
                import json
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

            return True

        except Exception as e:
            logger.error("保存配置失败: %s", e)
            return False

    def update_last_session(self, **kwargs: Any) -> None:
        """更新上次会话配置。

        Args:
            **kwargs: 要更新的字段键值对
        """
        for key, value in kwargs.items():
            if hasattr(self.config.last_session, key):
                setattr(self.config.last_session, key, value)
        self.config.last_session.last_used = time.time()

        if self.config.auto_save:
            self.save()

    def add_recent_file(self, file_path: str) -> None:
        """添加最近文件（最多保留 10 个）。

        Args:
            file_path: 文件路径
        """
        if file_path in self.config.recent_files:
            self.config.recent_files.remove(file_path)
        self.config.recent_files.insert(0, file_path)
        self.config.recent_files = self.config.recent_files[:10]  # 最多 10 个

        if self.config.auto_save:
            self.save()

    def set_custom_provider_url(self, provider: str, url: str) -> None:
        """设置自定义供应商 URL。

        Args:
            provider: 供应商名称
            url: 供应商 Base URL
        """
        self.config.custom_providers.urls[provider] = url
        if self.config.auto_save:
            self.save()

    def get_custom_provider_url(self, provider: str) -> Optional[str]:
        """获取自定义供应商 URL。

        Args:
            provider: 供应商名称

        Returns:
            供应商 Base URL，不存在时返回 None
        """
        return self.config.custom_providers.urls.get(provider)

    def clear_all(self) -> None:
        """清除所有配置（包括 Windows 凭据）"""
        self.config = AppConfig()
        if self.config_path.exists():
            self.config_path.unlink()

        # 清除 Windows 凭据
        if self.win_cred.available:
            self.win_cred.delete_credential('api_key')

    def export_config(self, filepath: str) -> None:
        """导出配置（不含 API Key）。

        Args:
            filepath: 导出文件路径
        """
        data = {
            'LastSession': {
                'provider': self.config.last_session.provider,
                'model': '***',
                'api_key': '***',
                'lang_in': self.config.last_session.lang_in,
                'lang_out': self.config.last_session.lang_out,
                'qps': self.config.last_session.qps,
            },
            'CustomProviders': {
                'urls': self.config.custom_providers.urls,
            },
            'recent_files': self.config.recent_files,
        }

        try:
            import toml
            with open(filepath, 'w', encoding='utf-8') as f:
                toml.dump(data, f)
        except ImportError:
            import json
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def import_config(self, filepath: str) -> bool:
        """导入配置。

        Args:
            filepath: 导入文件路径

        Returns:
            是否导入成功
        """
        try:
            try:
                import toml
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = toml.load(f)
            except ImportError:
                import json
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            ls_data = data.get('LastSession', {})
            if ls_data.get('provider'):
                self.config.last_session.provider = ls_data['provider']
            if ls_data.get('lang_in'):
                self.config.last_session.lang_in = ls_data['lang_in']
            if ls_data.get('lang_out'):
                self.config.last_session.lang_out = ls_data['lang_out']

            cp_data = data.get('CustomProviders', {})
            if cp_data.get('urls'):
                self.config.custom_providers.urls.update(cp_data['urls'])

            self.save()
            return True
        except Exception:
            return False


# ============================================================
# 全局配置实例
# ============================================================

_config_manager = None


def get_config() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


if __name__ == "__main__":
    # 测试
    from gui.logger_utils import get_logger
    _logger = get_logger(__name__)

    config = get_config()

    _logger.info("配置目录: %s", get_config_dir())
    _logger.info("配置文件: %s", get_config_path())
    _logger.info("当前模型: %s", config.config.last_session.model)
    _logger.info("当前语言: %s → %s", config.config.last_session.lang_in, config.config.last_session.lang_out)

    # 测试加密
    encryptor = SimpleEncryptor()
    test_key = "sk-test-api-key-12345"
    encrypted = encryptor.encrypt(test_key)
    decrypted = encryptor.decrypt(encrypted)
    _logger.info("加密测试:")
    _logger.info("  原文: %s", test_key)
    _logger.info("  加密: %s...", encrypted[:30])
    _logger.info("  解密: %s", decrypted)
    _logger.info("  匹配: %s", test_key == decrypted)

    # 测试保存
    config.config.last_session.model = "glm-4.7"
    config.config.last_session.api_key = "sk-test-key"
    config.save()
    _logger.info("配置已保存")

    # 测试加载
    config2 = ConfigManager()
    _logger.info("加载后模型: %s", config2.config.last_session.model)
    _logger.info("加载后 Key: %s", config2.config.last_session.api_key)