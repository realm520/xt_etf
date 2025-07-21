# XT ETF 交易系统

## 项目简介

XT ETF 是一个加密货币 ETF 交易系统，集成了 Binance 和 XT 交易所，实现自动化做市策略、风险管理和订单执行。支持杠杆 ETF 产品（3x 和 5x，多空双向）。

## 快速开始（使用 uv）

### 安装 uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或使用 pip
pip install uv
```

### 设置开发环境

```bash
# 1. 克隆项目
git clone <repository-url>
cd xt_etf

# 2. 运行设置脚本
./scripts/setup_uv.sh

# 3. 激活虚拟环境
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate     # Windows
```

### 运行交易策略

```bash
# 3x 多头策略
./scripts/run_stg3l.sh

# 3x 空头策略
./scripts/run_stg3s.sh

# 5x 多头策略
./scripts/run_stg5l.sh

# 5x 空头策略
./scripts/run_stg5s.sh
```

## 开发指南

### 使用 uv 管理依赖

```bash
# 安装项目（开发模式）
uv pip install -e .

# 安装开发依赖
uv pip install -e ".[dev]"

# 添加新依赖
uv pip install package-name

# 更新依赖列表
uv pip freeze > requirements.txt

# 同步依赖（根据 pyproject.toml）
uv pip sync
```

### 运行测试

```bash
# 运行所有测试
pytest

# 并行运行测试（10个进程）
pytest -n 10

# 运行特定测试文件
pytest tests/test_client.py

# 生成覆盖率报告
pytest --cov=binance tests/
```

### 代码质量检查

```bash
# 运行 linter
ruff check .

# 运行类型检查
pyright

# 运行所有 pre-commit hooks
pre-commit run --all-files
```

## 项目结构

- `binance/` - 修改版 python-binance 库，增强了 WebSocket 支持
- `etf/` - ETF 交易引擎核心组件
- `scripts/` - 便捷脚本和工具
- `tests/` - 单元测试和集成测试
- `config/` - 策略配置文件

## 配置说明

- API 密钥存储在 `APIKey*.json` 文件中
- 策略参数配置在 `config/strategies.yaml`
- Redis 连接默认为 localhost:6379

## useful redis commends
