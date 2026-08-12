# 打包与分发指南

## BabelDOC AI 翻译工具 - 打包说明

## 快速打包

### 方法一：使用批处理脚本（推荐）
```bash
build.bat
```

### 方法二：使用 Python 脚本
```bash
# 单文件模式（分发方便）
python build.py

# 单目录模式（启动更快）
python build.py --dir

# 使用 .spec 文件
python build.py --spec

# 清理后重新打包
python build.py --clean

# 创建安装脚本
python build.py --installer
```

### 方法三：直接使用 PyInstaller
```bash
pyinstaller --onefile --windowed --name "BabelDOC_AI_Translator" ^
    --add-data "babeldoc;babeldoc" ^
    --add-data "gui;gui" ^
    --add-data "api_config.json;." ^
    --hidden-import babeldoc ^
    main.py
```

## 打包配置说明

### 单文件 vs 单目录

| 模式 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| 单文件 (--onefile) | 分发方便，只有一个文件 | 启动慢（需解压） | 最终用户分发 |
| 单目录 (--onedir) | 启动快 | 文件多 | 开发测试 |

### 隐藏导入（hidden-import）

由于 BabelDOC 依赖较多，需要显式声明：

```python
hiddenimports = [
    'babeldoc',
    'PyQt6',
    'pymupdf',
    'openai',
    'httpx',
    # ... 详见 .spec 文件
]
```

### 排除模块（减小体积）

```python
excludes = [
    'matplotlib', 'IPython', 'jupyter', 'notebook',
    'pytest', 'setuptools', 'pip', 'tkinter', 'unittest'
]
```

## 常见问题

### 1. ModuleNotFoundError
**原因**: PyInstaller 未能自动检测依赖
**解决**: 在 spec 文件或命令行中添加 `--hidden-import`

```bash
pyinstaller --hidden-import=缺失的模块名 main.py
```

### 2. 文件过大
**原因**: 包含了不必要的依赖
**解决**: 使用 `--exclude-module` 排除不需要的模块

### 3. 启动缓慢
**原因**: 单文件模式需要解压到临时目录
**解决**: 使用 `--onedir` 单目录模式

### 4. 配置文件丢失
**原因**: 打包后路径变化
**解决**: 使用 `sys._MEIPASS` 获取打包后路径

```python
if getattr(sys, 'frozen', False):
    base_path = Path(sys._MEIPASS)
else:
    base_path = Path(__file__).parent
```

## 制作安装包

### Inno Setup（推荐）

1. 下载 [Inno Setup](https://jrsoftware.org/isdl.php)
2. 生成安装脚本：`python build.py --installer`
3. 用 Inno Setup 编译 `installer_script.iss`

### NSIS

1. 下载 [NSIS](https://nsis.sourceforge.io/)
2. 创建 NSIS 脚本打包 dist 目录

## 签名与发布

### 代码签名（可选但推荐）
```bash
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com dist\BabelDOC_AI_Translator.exe
```

### 发布渠道
- GitHub Releases
- 百度网盘
- 企业内部分发

## 打包后测试

1. **功能测试**: 验证所有功能正常
2. **路径测试**: 确保配置文件正确读写
3. **API 测试**: 验证各模型 API 调用正常
4. **离线测试**: 在无网络环境下测试启动

## 预估打包大小

| 组件 | 大小 |
|------|------|
| Python 运行时 | ~30 MB |
| PyQt6 | ~35 MB |
| PyTorch (onnxruntime) | ~100 MB |
| 其他依赖 | ~50 MB |
| **总计（单目录）** | **~215 MB** |
| **总计（单文件压缩后）** | **~80-120 MB** |