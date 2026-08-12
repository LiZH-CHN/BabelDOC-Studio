# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
BabelDOC AI 翻译工具

使用方法:
    pyinstaller BabelDOC_AI_Translator.spec

或使用一键打包脚本:
    python build.py
"""

import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(SPECPATH).resolve()

# ============================================================
# 分析配置
# ============================================================

a = Analysis(
    # 入口脚本
    ['main.py'],
    
    # 搜索路径
    pathex=[str(PROJECT_ROOT)],
    
    # 二进制文件
    binaries=[],
    
    # 数据文件
    datas=[
        # BabelDOC 核心文件
        (str(PROJECT_ROOT / 'babeldoc'), 'babeldoc'),
        # GUI 模块
        (str(PROJECT_ROOT / 'gui'), 'gui'),
        # 配置文件模板
        (str(PROJECT_ROOT / 'api_config.json'), '.'),
    ],
    
    # 隐藏导入（PyInstaller 无法自动检测的模块）
    hiddenimports=[
        # BabelDOC 核心
        'babeldoc',
        'babeldoc.format.pdf.high_level',
        'babeldoc.format.pdf.translation_config',
        'babeldoc.translator.translator',
        'babeldoc.docvision.doclayout',
        
        # GUI
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        
        # 数据处理
        'pymupdf',
        'fitz',
        'numpy',
        'cv2',
        'skimage',
        'sklearn',
        
        # 网络请求
        'openai',
        'httpx',
        'httpcore',
        
        # 工具库',
        'tenacity',
        'pydantic',
        'rich',
        'tqdm',
        'orjson',
        'toml',
        'msgpack',
        
        # 数据库
        'peewee',
        'sqlite3',
        
        # 图像处理
        'PIL',
        'pyzstd',
        'uharfbuzz',
        'freetype',
        
        # 机器学习',
        'onnxruntime',
        
        # 其他',
        'chardet',
        'charset_normalizer',
        'Levenshtein',
        'bitstring',
        'hyperscan',
        'rtree',
        'scipy',
        'tiktoken',
        'configargparse',
        'huggingface_hub',
        
        # 项目内部模块',
        'gui.main_window',
        'gui.quality_dialogs',
        'gui.translator_backend',
        'gui.config_manager',
        'gui.core',
        'gui.core.quality',
        'gui.core.term_replacer',
        'gui.core.ai_glossary',
        'gui.core.advanced_translation',
    ],
    
    # 排除不需要的模块（减小体积）
    excludes=[
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'setuptools',
        'pip',
        '_tkinter',
        'tkinter',
        'unittest',
    ],
    
    # hooks 目录
    hookspath=[],
    
    # hooks 配置
    hooksconfig={},
    
    # 运行时 hooks
    runtime_hooks=[],
    
    # 是否收集子模块
    noarchive=False,
)

# ============================================================
# 可执行文件配置
# ============================================================

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BabelDOC_AI_Translator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windows GUI 应用，无控制台窗口
    
    # 图标（需要 .ico 文件）
    # icon=str(PROJECT_ROOT / 'resources' / 'icon.ico'),
    
    # 版本信息
    version=None,
    
    # 是否单文件
    # 单文件模式启动较慢但分发方便
    # 单目录模式启动快但文件多
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BabelDOC_AI_Translator',
)