"""
创建桌面快捷方式 - 论文翻译
"""
import os
import sys
from pathlib import Path

def create_desktop_shortcut():
    """创建桌面快捷方式"""
    try:
        import winshell
        from win32com.client import Dispatch
    except ImportError:
        print("安装依赖: pip install pywin32 winshell")
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pywin32', 'winshell'])
        import winshell
        from win32com.client import Dispatch

    # 桌面路径
    desktop = Path(winshell.desktop())
    
    # 项目目录
    project_dir = Path(__file__).parent.resolve()
    main_py = project_dir / "main.py"
    
    # Python 解释器
    python_exe = Path(sys.executable)
    
    # 快捷方式路径
    shortcut_path = desktop / "论文翻译.lnk"
    
    # 创建快捷方式
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = str(python_exe)
    shortcut.Arguments = f'"{main_py}"'
    shortcut.WorkingDirectory = str(project_dir)
    shortcut.Description = "BabelDOC AI 论文翻译工具 v1.0"
    # 图标（可选）
    # shortcut.IconLocation = str(project_dir / "resources" / "icon.ico")
    shortcut.Save()
    
    print(f"✅ 快捷方式已创建: {shortcut_path}")
    print(f"   目标: {python_exe}")
    print(f"   参数: {main_py}")
    print(f"   工作目录: {project_dir}")
    return True


if __name__ == "__main__":
    create_desktop_shortcut()