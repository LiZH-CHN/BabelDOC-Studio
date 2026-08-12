r"""
配置持久化模块
- 保存/加载用户设置到 %APPDATA%\BabelDOC-GUI\config.toml
- 支持 API Key 加密存储
- 记住上次会话的所有配置
"""

import os
import base64
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict


# ============================================================
# 配置路径
# ============================================================

def get_config_dir() -> Path:
    """获取配置目录"""
    if os.name == 'nt':  # Windows
        appdata = os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')
        config_dir = Path(appdata) / 'BabelDOC-GUI'
    else:  # macOS / Linux
        config_dir = Path.home() / '.config' / 'babeldoc-gui'

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """获取配置文件路径"""
    return get_config_dir() / 'config.toml'


# ============================================================
# 简单加密（XOR + Base64）
# ============================================================

class SimpleEncryptor:
    """
    简单加密器
    使用 XOR + Base64 编码
    注意：这不是强加密，只是防止明文存储敏感信息
    生产环境建议使用 Windows Credential Manager 或 keyring
    """

    def __init__(self, key: str = None):
        if key is None:
            # 使用机器特定的密钥（基于用户名和机器名）
            import platform
            key = f"{platform.node()}-{os.getlogin()}-BabelDOC-2024"
        self.key = key

    def encrypt(self, plaintext: str) -> str:
        """加密"""
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
        """解密"""
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
    engine2_model: str = ""
    multi_strategy: str = "balanced"
    output_dir: str = ""
    window_width: int = 900
    window_height: int = 700
    last_used: float = 0.0


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

    def __init__(self):
        self.config_path = get_config_path()
        self.config_dir = get_config_dir()
        self.encryptor = SimpleEncryptor()
        self.win_cred = WindowsCredentialManager()
        self.config = AppConfig()
        self._load()

    def _load(self):
        """加载配置"""
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
                engine2_model=ls_data.get('engine2_model', ''),
                multi_strategy=ls_data.get('multi_strategy', 'balanced'),
                output_dir=ls_data.get('output_dir', ''),
                window_width=ls_data.get('window_width', 900),
                window_height=ls_data.get('window_height', 700),
                last_used=ls_data.get('last_used', 0.0),
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
            print(f"加载配置失败: {e}，使用默认配置")
            self.config = AppConfig()

    def save(self):
        """保存配置"""
        try:
            # 加密 API Key
            encrypted_key = self._save_api_key(self.config.last_session.api_key)

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
                    'engine2_model': self.config.last_session.engine2_model,
                    'multi_strategy': self.config.last_session.multi_strategy,
                    'output_dir': self.config.last_session.output_dir,
                    'window_width': self.config.last_session.window_width,
                    'window_height': self.config.last_session.window_height,
                    'last_used': time.time(),
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
            print(f"保存配置失败: {e}")
            return False

    def _save_api_key(self, api_key: str) -> str:
        """保存 API Key（加密）"""
        if not api_key:
            return ""

        # 优先使用 Windows 凭据管理器
        if self.win_cred.available:
            if self.win_cred.save_credential('api_key', api_key):
                return "__WIN_CRED__"

        # 回退到简单加密
        return self.encryptor.encrypt(api_key)

    def _load_api_key(self, stored: str) -> str:
        """加载 API Key（解密）"""
        if not stored:
            return ""

        if stored == "__WIN_CRED__":
            # 从 Windows 凭据管理器读取
            if self.win_cred.available:
                key = self.win_cred.read_credential('api_key')
                if key:
                    return key
            return ""

        # 解密
        return self.encryptor.decrypt(stored)

    def update_last_session(self, **kwargs):
        """更新上次会话配置"""
        for key, value in kwargs.items():
            if hasattr(self.config.last_session, key):
                setattr(self.config.last_session, key, value)
        self.config.last_session.last_used = time.time()

        if self.config.auto_save:
            self.save()

    def add_recent_file(self, file_path: str):
        """添加最近文件"""
        if file_path in self.config.recent_files:
            self.config.recent_files.remove(file_path)
        self.config.recent_files.insert(0, file_path)
        self.config.recent_files = self.config.recent_files[:10]  # 最多 10 个

        if self.config.auto_save:
            self.save()

    def set_custom_provider_url(self, provider: str, url: str):
        """设置自定义供应商 URL"""
        self.config.custom_providers.urls[provider] = url
        if self.config.auto_save:
            self.save()

    def get_custom_provider_url(self, provider: str) -> Optional[str]:
        """获取自定义供应商 URL"""
        return self.config.custom_providers.urls.get(provider)

    def clear_all(self):
        """清除所有配置"""
        self.config = AppConfig()
        if self.config_path.exists():
            self.config_path.unlink()

        # 清除 Windows 凭据
        if self.win_cred.available:
            self.win_cred.delete_credential('api_key')

    def export_config(self, filepath: str):
        """导出配置（不含 API Key）"""
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

    def import_config(self, filepath: str):
        """导入配置"""
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
    config = get_config()

    print(f"配置目录: {get_config_dir()}")
    print(f"配置文件: {get_config_path()}")
    print(f"当前模型: {config.config.last_session.model}")
    print(f"当前语言: {config.config.last_session.lang_in} → {config.config.last_session.lang_out}")

    # 测试加密
    encryptor = SimpleEncryptor()
    test_key = "sk-test-api-key-12345"
    encrypted = encryptor.encrypt(test_key)
    decrypted = encryptor.decrypt(encrypted)
    print(f"\n加密测试:")
    print(f"  原文: {test_key}")
    print(f"  加密: {encrypted[:30]}...")
    print(f"  解密: {decrypted}")
    print(f"  匹配: {test_key == decrypted}")

    # 测试保存
    config.config.last_session.model = "glm-4.7"
    config.config.last_session.api_key = "sk-test-key"
    config.save()
    print(f"\n配置已保存")

    # 测试加载
    config2 = ConfigManager()
    print(f"加载后模型: {config2.config.last_session.model}")
    print(f"加载后 Key: {config2.config.last_session.api_key}")