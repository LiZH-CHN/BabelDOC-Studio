#!/bin/bash
# BabelDOC Studio - 一键环境配置 (Linux/macOS)

set -e

echo "============================================"
echo "  BabelDOC Studio - 一键环境配置"
echo "============================================"
echo ""

# 检查 Python
echo "[1/5] 检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "❌ 未检测到 Python3，请先安装 Python 3.12"
    exit 1
fi
python3 --version
echo ""

# 检查 Python 版本
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "当前 Python 版本: $PY_VERSION"
echo ""

# 检查并安装 uv
echo "[2/5] 检查 uv 工具..."
if ! command -v uv &> /dev/null; then
    echo "📦 正在安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # 刷新 shell 环境
    source ~/.bashrc 2>/dev/null || source ~/.zshrc 2>/dev/null || true
    export PATH="$HOME/.cargo/bin:$PATH"
    echo "✅ uv 安装完成"
else
    echo "✅ uv 已安装"
fi
uv --version
echo ""

# 创建虚拟环境
echo "[3/5] 创建虚拟环境..."
if [ -d ".venv" ]; then
    echo "⚠️ 检测到已存在 .venv 虚拟环境"
    read -p "是否删除并重新创建? (y/N) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf .venv
        uv venv --python 3.12
    else
        echo "跳过虚拟环境重建"
    fi
else
    uv venv --python 3.12
fi
echo "✅ 虚拟环境创建完成"
echo ""

# 安装依赖
echo "[4/5] 同步依赖..."
uv sync
echo "✅ 依赖安装完成"
echo ""

# 验证安装
echo "[5/5] 验证安装..."
source .venv/bin/activate
python -c "import babeldoc; print('✅ BabelDOC 导入成功')" 2>/dev/null || echo "⚠️ BabelDOC 导入验证失败"
echo ""

echo "============================================"
echo "🎉 环境配置完成！"
echo ""
echo "启动方式:"
echo "  1. 开发模式:   source .venv/bin/activate && python main.py"
echo "  2. 运行 GUI:   source .venv/bin/activate && python -m BabelDOC_Studio"
echo "  3. 命令行:     uv run babeldoc --help"
echo "============================================"