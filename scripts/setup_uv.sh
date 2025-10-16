#!/bin/bash
# XT ETF 项目 uv 开发环境设置脚本

set -e

echo "🚀 设置 XT ETF 开发环境..."

# 检查是否安装了 uv
if ! command -v uv &> /dev/null; then
    echo "❌ uv 未安装。请先安装 uv："
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "   或"
    echo "   pip install uv"
    exit 1
fi

echo "✅ 检测到 uv 版本: $(uv --version)"

# 创建虚拟环境
echo "📦 创建虚拟环境..."
# 先清理可能存在的旧虚拟环境
if [ -d ".venv" ]; then
    echo "清理旧的虚拟环境..."
    rm -rf .venv
fi
uv venv --python 3.11

# 激活虚拟环境的提示
echo ""
echo "🎯 虚拟环境创建成功！"
echo ""
echo "激活虚拟环境："
echo "  source .venv/bin/activate  # Linux/macOS"
echo "  .venv\\Scripts\\activate     # Windows"

# 安装依赖
echo ""
echo "📥 安装项目依赖..."
source .venv/bin/activate

# 安装项目本身和所有依赖
echo "安装项目及其依赖..."
uv pip install -e .

# 安装开发依赖
echo "安装开发依赖..."
uv pip install -e ".[dev]"

# 安装 pre-commit hooks
echo ""
echo "🔧 设置 pre-commit hooks..."
pre-commit install

# 验证安装
echo ""
echo "✅ 验证安装..."
python -c "import binance; print(f'✅ Binance 模块已安装')" 2>/dev/null || echo "⚠️  Binance 模块安装可能有问题"
python -c "import etf; print('✅ ETF 模块已安装')" 2>/dev/null || echo "⚠️  ETF 模块安装可能有问题"

echo ""
echo "🎉 开发环境设置完成！"
echo ""
echo "常用命令："
echo "  uv pip install -e .          # 安装项目（开发模式）"
echo "  uv pip install -e '.[dev]'   # 安装开发依赖"
echo "  uv pip list                  # 查看已安装的包"
echo "  uv pip sync                  # 同步依赖到虚拟环境"
echo ""
echo "运行测试："
echo "  pytest                       # 运行所有测试"
echo "  pytest -n 10                 # 并行运行测试"
echo "  pytest --cov=binance tests/  # 运行测试并生成覆盖率报告"
echo ""
echo "代码质量检查："
echo "  ruff check .                 # 运行 linter"
echo "  pyright                      # 运行类型检查"
echo "  pre-commit run --all-files   # 运行所有 pre-commit hooks"
