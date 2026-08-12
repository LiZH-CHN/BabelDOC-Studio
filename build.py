"""
一键打包脚本
BabelDOC AI 翻译工具

使用方法:
    python build.py          # 单文件模式（推荐分发）
    python build.py --dir    # 单目录模式（启动更快）
    python build.py --clean  # 清理后重新打包

依赖安装:
    pip install pyinstaller
"""

import sys
import os
import shutil
import subprocess
import argparse
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()


def clean_build():
    """清理构建目录"""
    print("🧹 清理构建目录...")
    
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for d in dirs_to_clean:
        dir_path = PROJECT_ROOT / d
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"  已删除: {d}")
    
    # 删除 .pyc 文件
    for pyc in PROJECT_ROOT.rglob("*.pyc"):
        pyc.unlink()
    for pycache in PROJECT_ROOT.rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache)
    
    print("✅ 清理完成\n")


def install_dependencies():
    """确保 PyInstaller 已安装"""
    try:
        import PyInstaller
        print(f"✅ PyInstaller 版本: {PyInstaller.__version__}\n")
        return True
    except ImportError:
        print("📦 安装 PyInstaller...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pyinstaller'])
        return True


def get_pyinstaller_args(mode: str = 'onefile') -> list:
    """获取 PyInstaller 参数"""
    
    if mode == 'onefile':
        # 单文件模式 - 分发方便
        return [
            '--onefile',
        ]
    else:
        # 单目录模式 - 启动更快
        return [
            '--onedir',
        ]


def build(mode: str = 'onefile'):
    """执行打包"""
    
    print("=" * 60)
    print("  BabelDOC AI 翻译工具 - 打包脚本")
    print("=" * 60)
    print()
    
    # 检查 PyInstaller
    install_dependencies()
    
    # 构建命令
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        *get_pyinstaller_args(mode),
        '--windowed',  # GUI 应用
        '--name', 'BabelDOC_AI_Translator',
        # 数据文件
        '--add-data', f'{PROJECT_ROOT / "babeldoc"}{os.pathsep}babeldoc',
        '--add-data', f'{PROJECT_ROOT / "gui"}{os.pathsep}gui',
        '--add-data', f'{PROJECT_ROOT / "api_config.json"}{os.pathsep}.',
        # 隐藏导入
        '--hidden-import', 'babeldoc',
        '--hidden-import', 'babeldoc.format.pdf.high_level',
        '--hidden-import', 'babeldoc.translator.translator',
        '--hidden-import', 'babeldoc.docvision.doclayout',
        '--hidden-import', 'PyQt6',
        '--hidden-import', 'PyQt6.QtCore',
        '--hidden-import', 'PyQt6.QtGui',
        '--hidden-import', 'PyQt6.QtWidgets',
        '--hidden-import', 'pymupdf',
        '--hidden-import', 'fitz',
        '--hidden-import', 'openai',
        '--hidden-import', 'httpx',
        '--hidden-import', 'numpy',
        '--hidden-import', 'cv2',
        '--hidden-import', 'skimage',
        '--hidden-import', 'sklearn',
        '--hidden-import', 'peewee',
        '--hidden-import', 'sqlite3',
        '--hidden-import', 'tenacity',
        '--hidden-import', 'pydantic',
        '--hidden-import', 'rich',
        '--hidden-import', 'toml',
        '--hidden-import', 'orjson',
        '--hidden-import', 'msgpack',
        '--hidden-import', 'tqdm',
        '--hidden-import', 'chardet',
        '--hidden-import', 'Levenshtein',
        '--hidden-import', 'tiktoken',
        '--hidden-import', 'configargparse',
        '--hidden-import', 'huggingface_hub',
        '--hidden-import', 'PIL',
        '--hidden-import', 'pyzstd',
        '--hidden-import', 'uharfbuzz',
        '--hidden-import', 'freetype',
        '--hidden-import', 'onnxruntime',
        '--hidden-import', 'scipy',
        '--hidden-import', 'bitstring',
        '--hidden-import', 'hyperscan',
        '--hidden-import', 'rtree',
        '--hidden-import', 'charset_normalizer',
        '--hidden-import', 'gui.main_window',
        '--hidden-import', 'gui.quality_dialogs',
        '--hidden-import', 'gui.translator_backend',
        '--hidden-import', 'gui.config_manager',
        '--hidden-import', 'gui.core',
        '--hidden-import', 'gui.core.quality',
        '--hidden-import', 'gui.core.term_replacer',
        '--hidden-import', 'gui.core.ai_glossary',
        '--hidden-import', 'gui.core.advanced_translation',
        # 排除不需要的模块（减小体积）
        '--exclude-module', 'matplotlib',
        '--exclude-module', 'IPython',
        '--exclude-module', 'jupyter',
        '--exclude-module', 'notebook',
        '--exclude-module', 'pytest',
        '--exclude-module', 'setuptools',
        '--exclude-module', 'pip',
        '--exclude-module', '_tkinter',
        '--exclude-module', 'tkinter',
        '--exclude-module', 'unittest',
        # 入口
        str(PROJECT_ROOT / 'main.py'),
    ]
    
    print("📦 开始打包...")
    print(f"   模式: {'单文件' if mode == 'onefile' else '单目录'}")
    print(f"   命令: pyinstaller {' '.join(cmd[:5])}...")
    print()
    
    # 执行打包
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    
    if result.returncode == 0:
        print()
        print("=" * 60)
        print("  ✅ 打包成功!")
        print("=" * 60)
        
        # 显示输出路径
        if mode == 'onefile':
            exe_path = PROJECT_ROOT / 'dist' / 'BabelDOC_AI_Translator.exe'
        else:
            exe_path = PROJECT_ROOT / 'dist' / 'BabelDOC_AI_Translator' / 'BabelDOC_AI_Translator.exe'
        
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"  输出: {exe_path}")
            print(f"  大小: {size_mb:.1f} MB")
        
        print()
        print("  下一步:")
        print("  1. 测试运行 exe 文件")
        print("  2. 如有 ModuleNotFoundError，添加 --hidden-import")
        print("  3. 使用 Inno Setup 或 NSIS 制作安装包")
        print()
    else:
        print()
        print("❌ 打包失败!")
        print("请检查错误信息，常见问题:")
        print("  - ModuleNotFoundError: 添加 --hidden-import")
        print("  - 文件路径错误: 检查 --add-data 参数")
        print("  - 依赖缺失: pip install 缺少的包")
        print()
        return False
    
    return True


def create_installer_script():
    """创建 Inno Setup 安装脚本"""
    iss_content = '''; BabelDOC AI 翻译工具 - Inno Setup 安装脚本
; 需要安装 Inno Setup: https://jrsoftware.org/isdl.php

[Setup]
AppName=BabelDOC AI 翻译工具
AppVersion=1.0.0
AppPublisher=BabelDOC Team
DefaultDirName={autopf}\\BabelDOC_AI_Translator
DefaultGroupName=BabelDOC AI 翻译工具
OutputDir=installer
OutputBaseFilename=BabelDOC_AI_Translator_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\\BabelDOC_AI_Translator.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "api_config.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\\BabelDOC AI 翻译工具"; Filename: "{app}\\BabelDOC_AI_Translator.exe"
Name: "{autodesktop}\\BabelDOC AI 翻译工具"; Filename: "{app}\\BabelDOC_AI_Translator.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\\BabelDOC_AI_Translator.exe"; Description: "{cm:LaunchProgram,BabelDOC AI 翻译工具}"; Flags: nowait postinstall skipifsilent
'''
    
    iss_path = PROJECT_ROOT / 'installer_script.iss'
    with open(iss_path, 'w', encoding='utf-8') as f:
        f.write(iss_content)
    
    print(f"  已创建安装脚本: {iss_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='BabelDOC AI 翻译工具打包脚本')
    parser.add_argument('--dir', action='store_true', help='单目录模式（启动更快）')
    parser.add_argument('--clean', action='store_true', help='清理后重新打包')
    parser.add_argument('--spec', action='store_true', help='使用 .spec 文件打包')
    parser.add_argument('--installer', action='store_true', help='创建安装脚本')
    
    args = parser.parse_args()
    
    mode = 'onedir' if args.dir else 'onefile'
    
    # 创建安装脚本
    if args.installer:
        create_installer_script()
        return
    
    # 清理
    if args.clean:
        clean_build()
    
    # 使用 .spec 文件打包
    if args.spec:
        print("📦 使用 .spec 文件打包...")
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            str(PROJECT_ROOT / 'BabelDOC_AI_Translator.spec'),
        ]
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        if result.returncode == 0:
            print("✅ 打包成功!")
        else:
            print("❌ 打包失败!")
        return
    
    # 标准打包
    build(mode)


if __name__ == "__main__":
    main()