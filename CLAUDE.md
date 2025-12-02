# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a cryptocurrency ETF trading system that integrates with Binance and XT exchanges. It implements automated market-making strategies, risk management, and order execution for leveraged ETF products (3x and 5x, both long and short).

## Language Notes

- 支持中文交互和代码注释，以便更好地与中文开发团队沟通
- 用中文对话可以提高代码理解和协作效率

## Development Commands

### Setting Up Development Environment (推荐使用 uv)

#### 使用 uv 快速设置
```bash
# 安装 uv (如果还没有安装)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 运行设置脚本
./scripts/setup_uv.sh

# 激活虚拟环境
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows
```

#### uv 常用命令
```bash
# 创建虚拟环境
uv venv --python 3.11

# 安装项目和依赖
uv pip install -e .
uv pip install -e ".[dev]"

# 添加新依赖
uv pip install package-name

# 同步依赖
uv pip sync

# 查看已安装的包
uv pip list
```

### Running Tests
```bash
# Run all tests with parallel execution
pytest -n 10

# Run specific test file
pytest tests/test_client.py

# Run with coverage
pytest --cov=binance tests/

# Run tests for specific Python version using tox
tox -e py39
```

### Code Quality
```bash
# Run linter
ruff check .

# Run type checker
pyright

# Run pre-commit hooks
pre-commit run --all-files
```

### Building and Installation (传统方式)
```bash
# Install in development mode
pip install -e .

# Install with all dependencies (包括开发依赖)
pip install -e ".[dev]"
```

### Running the Trading System

#### Recommended Method (New Unified System)
```bash
# Using strategy mode
python run_etf.py --strategy stg3l  # 3x long strategy
python run_etf.py --strategy stg3s  # 3x short strategy
python run_etf.py --strategy stg5l  # 5x long strategy
python run_etf.py --strategy stg5s  # 5x short strategy

# Override parameters
python run_etf.py --strategy stg3l --bid-ask-spread 0.02
python run_etf.py --strategy stg5s --env qa
```

#### Production Deployment (PM2)
```bash
# Start all strategies using PM2
pm2 start ecosystem.config.js

# Start specific strategy
pm2 start ecosystem.config.js --only etf-stg3l
pm2 start ecosystem.config.js --only etf-stg3s
pm2 start ecosystem.config.js --only etf-stg5l
pm2 start ecosystem.config.js --only etf-stg5s

# Monitor all processes
pm2 monit

# View logs
pm2 logs etf-stg3l

# Stop specific strategy
pm2 stop etf-stg3l

# Restart specific strategy
pm2 restart etf-stg3l

# View all processes
pm2 list
```


#### Other Components
```bash
# Run net value calculation (unified with improved version)
python run_net_value.py --strategy stg3l  # 3x long
python run_net_value.py --strategy stg3s  # 3x short
python run_net_value.py --strategy stg5l  # 5x long
python run_net_value.py --strategy stg5s  # 5x short

# Run specific components (legacy)
python hedging_stg3l.py    # Hedging operations
```

#### Improved Net Value Calculator Features

The system now uses `etf.net_value_improved.ImprovedNetValue` which provides:

1. **Automatic Recovery After Restart**
   - Detects program restart and recovers net value during disconnection
   - Calculates missed management fees during downtime
   - Records recovery events for monitoring

2. **Price Spike Protection**
   - Limits single price change to 10% (configurable via `max_single_change`)
   - Records abnormal price events for analysis
   - Prevents calculation errors from extreme market moves

3. **Enhanced Data Persistence**
   - Stores detailed net value data in Redis with timestamps
   - Maintains historical records (last 1000 entries)
   - Tracks total fees deducted and update counts

4. **Monitoring and Debugging**
   - Records abnormal events (price spikes, long restarts, recoveries)
   - Detailed logging with timestamps and context
   - Redis keys:
     - Simple net value: `netvalue_{symbol}{leverage}{l/s}`
     - Detailed data: `netvalue_{symbol}{leverage}{l/s}_detail`
     - History: `netvalue_{symbol}{leverage}{l/s}_history`

5. **Configuration Parameters**
   - `max_single_change`: Maximum allowed single price change (default: 0.10)
   - `max_restart_gap`: Maximum restart gap in seconds (default: 300)
   - All other parameters remain compatible with the original version

## 最近更新 (2025-10-29)

### 🎉 核心改进

#### 1. 动态Symbol配置系统 ⭐
**位置**: `etf/symbol_config.py`

**功能**:
- 从交易所API自动获取精度配置（价格精度、数量精度、最小订单金额）
- 使用Decimal精确计算，避免浮点数精度问题
- 订单金额自动调整（最小值+20%余量）
- 定期配置刷新（1小时）

**解决问题**:
- ✅ 彻底解决ORDER_008精度错误
- ✅ 避免手动维护配置的错误
- ✅ 支持交易所配置动态变化

**使用示例**:
```python
from etf.symbol_config import SymbolConfigManager

config_manager = SymbolConfigManager(client)
await config_manager.load_symbol_config("BTCUSDT")

# 自动格式化订单参数
price = config_manager.format_price("BTCUSDT", 50000.123456)
quantity = config_manager.format_quantity("BTCUSDT", 0.001234567)
```

#### 2. 止损虚假触发修复 🛡️
**位置**: `etf/risk/stop_loss.py`

**价格异常保护机制**:
1. **15%单次变化保护**: 单次价格变化>15%跳过检查（防止数据异常）
2. **20%价格偏离保护**: 价格偏离最高/最低价>20%跳过检查
3. **入场价多重验证**:
   - Delta金额最小阈值（0.05）
   - 价格合理性检查（10倍异常过滤）
   - 多重验证避免错误入场价

**示例场景**:
```python
# 场景1: 数据异常，价格突然从50000跳到60000
# 系统检测到15%变化，跳过止损检查，避免虚假触发

# 场景2: 价格从50000缓慢上涨到52000，然后回落到50500
# 移动止损正常工作，在51480（52000 - 1%）触发

# 场景3: 微小仓位变化（delta_amt < 0.05）
# 保持之前的入场价，避免频繁重新计算
```

**测试验证**: `test_stop_loss_fix.py`

#### 3. 统一日志系统 📊
**位置**: `etf/utils/logger.py`

**特性**:
- **策略级别隔离**: 每个策略独立日志目录（`logs/{strategy_name}/`）
- **日志轮转**:
  - 按日期轮转（midnight）
  - 按大小轮转（10MB）
- **错误日志独立**: `{strategy_name}_error.log`单独记录ERROR/CRITICAL
- **30天自动清理**: 防止磁盘占满

**使用示例**:
```python
from etf.utils.logger import setup_logger

logger = setup_logger("stg3l")
logger.info("订单已下单")
logger.error("订单失败", exc_info=True)
```

#### 4. QA2环境支持 🧪
**新增策略**: ton3l (TON 3x 做多)

**WebSocket配置**:
- QA2: `wss://stream.xt-qa2.com/public`
- 生产: `wss://stream.xt.com/public`

**运行命令**:
```bash
python run_etf.py --strategy ton3l --env qa
```

### 🏗️ 架构更新

#### 风险控制集成到主循环
**位置**: `run_etf.py:700-750`

**流程**:
```
主循环
  ├─ 更新风险等级（RiskController）
  ├─ 更新持仓信息（从Redis）
  ├─ 检查止损条件（StopLossManager）
  │   ├─ 价格异常保护
  │   ├─ 固定止损检查
  │   ├─ 移动止损检查
  │   └─ 时间止损检查
  ├─ 触发止损 → 撤销所有订单 + 60分钟冷却
  └─ 风险等级过高 → 暂停交易
```

#### WebSocket优先，REST降级
**位置**: `etf/risk/controller.py`

**数据源策略**:
```
WebSocket实时深度（优先）
    ↓ (5秒缓存)
缓存深度数据（max_age=5s）
    ↓ (缓存失效)
REST API查询（降级）
```

#### 订单管理增强
**位置**: `etf/order_manager.py`

**新增功能**:
- 订单黑名单机制（永久错误隔离）
- 熔断器机制（连续5次失败触发）
- 动态Symbol配置集成
- 异步订单记录（PostgreSQL + Redis）

### 📚 文档资源

新增3份完整文档，详细说明项目状态和规划：

1. **项目进度报告** - `docs/PROJECT_PROGRESS_REPORT.md`
   - 完整的项目现状分析
   - 已完成功能清单
   - 技术架构详解
   - 后续步骤建议

2. **技术债务跟踪** - `docs/TECHNICAL_DEBT.md`
   - 14项TODO详细分析
   - 优先级和影响评估
   - 实施方案和时间规划
   - 进度跟踪机制

3. **开发路线图** - `docs/DEVELOPMENT_ROADMAP.md`
   - Phase 1-4完整规划
   - 里程碑时间线
   - KPI指标定义
   - 团队分工说明

### 🔧 配置更新

**策略配置优化** (`config/strategies.yaml`):
- 所有策略启用风险控制（`Enable_risk_controller: true`）
- 止损参数按杠杆差异化配置
- 低频交易参数优化（10-60秒间隔）

**风险控制参数**:
```yaml
stop_loss:
  enabled: true
  fixed_threshold: -0.02      # 3x: -2%, 5x: -1.5%/-1%
  trailing_stop: 0.01         # 3x: 1%, 5x: 0.8%/0.5%
  time_stop: 24               # 3x: 24h, 5x: 12h/8h
  cooldown: 60                # 60分钟冷却期
  enable_partial_close: true
```

---

## Architecture Overview

### Core Components

1. **Exchange Integration Layer** (`/binance/`)
   - Modified python-binance library with enhanced WebSocket support
   - Async and sync clients for different use cases
   - Automatic reconnection and error handling
   - Depth cache management for order book data

2. **ETF Trading Engine** (`/etf/`)
   - `market_making.py`: Core market maker logic with dynamic order placement
   - `order_manager.py`: Manages order lifecycle, tracking, and execution
   - `risk.py`: Risk controls including position limits and exposure management
   - `washing.py`: Wash trading controller for liquidity provision
   - `orderbook.py`: Efficient order book data structures
   - `exchange/xt.py`: XT exchange integration wrapper

3. **Strategy Execution**
   - Multiple ETF runners handle different leveraged products
   - Each strategy has corresponding net value calculation and hedging components
   - Strategies communicate via Redis for real-time coordination

### Data Flow

1. **Market Data**: WebSocket streams → Redis → Strategy Components
2. **Order Flow**: Strategy → Order Manager → Exchange API → Confirmation
3. **Risk Management**: Position Monitor → Risk Module → Order Constraints
4. **PnL Tracking**: Trade Events → PnL Calculator → Monitoring Bot
5. **Net Value Storage**: Real-time calculation → Redis only (no file backup)

### Key Design Patterns

- **Async-First Architecture**: Heavy use of asyncio for concurrent operations
- **Event-Driven**: WebSocket streams drive real-time decision making
- **Modular Risk Controls**: Pluggable risk management components
- **Redis as Message Bus**: Inter-process communication and state sharing

### Configuration

#### API密钥配置（推荐使用 .env）

**方式1: 使用 .env 文件（推荐）**

创建项目根目录下的 `.env` 文件：

```bash
# XT Exchange API Keys
access_key=your_access_key_here
secret_key=your_secret_key_here

# OpenTelemetry配置（可选）
ENABLE_OTEL=true
OTLP_ENDPOINT=http://localhost:4317

# WebSocket配置（可选）
ENABLE_WEBSOCKET=true

# 日志配置（可选）
LOG_LEVEL=INFO

# 退出行为配置（可选）
CANCEL_ORDERS_ON_EXIT=true  # true: 退出时撤单, false: 保留订单
```

**优势**:
- ✅ 不会误提交到Git（已在 `.gitignore` 中）
- ✅ 更安全，统一管理
- ✅ 唯一支持的配置方式（APIKey.json 已废弃）

**注意**: `APIKey.json` 和加密文件 `APIKey.enc` 已被废弃，所有 API 密钥配置统一使用 `.env` 文件或环境变量。

#### 其他配置

- Strategy parameters: `config/strategies.yaml`
- Redis connection: localhost:6379
- Logging: Per-component with rotation

### Testing Strategy

- Unit tests for individual components
- Integration tests for exchange connectivity
- Mock WebSocket servers for testing real-time features
- Async test support throughout

## Important Considerations

1. **Exchange Rate Limits**: Both Binance and XT have rate limits - the system implements backoff strategies
2. **WebSocket Reconnection**: Automatic reconnection is built-in but monitor for extended disconnections
3. **Order State Management**: Orders are tracked locally and reconciled with exchange state
4. **Risk Parameters**: Each strategy has hardcoded risk limits that should be reviewed before deployment
5. **Redis Dependency**: The system requires Redis running on localhost:6379 for operation

## Low-Frequency Trading Strategy

### Overview

The system has been optimized for low-frequency trading to reduce costs and improve stability:

- **Trading Intervals**: 10-15 seconds between market maker updates (previously 1-5 seconds)
- **Washing Intervals**: 30-60 seconds between wash trades (previously 1-5 seconds)
- **Bid-Ask Spreads**: Adjusted based on leverage:
  - 3x leverage: 0.8-1.5% spread
  - 5x leverage: 1.5-5% spread

### Strategy Parameters

All strategies are configured in `config/strategies.yaml` with the following key parameters:

```yaml
strategy_name:
  symbol: "BTCUSDT"
  sleep_interval: 10-15  # seconds between updates
  washing_interval: 30-60  # seconds between wash trades
  bid_ask_spread: 0.008-0.05  # varies by leverage
  max_position: 100000  # maximum position size
  stop_loss: 0.02-0.05  # varies by leverage
```

### Monitoring and Alerts

The `monitor_low_freq.py` script monitors key metrics:

- **Washing Frequency**: 60-120 washes per hour expected
- **Real Trade Ratio**: 5-30% of total trades should be real
- **Net Value Deviation**: Alert if >5% deviation from expected
- **Performance Metrics**: Track order placement frequency and success rate

### Testing

Run low-frequency strategy tests:

```bash
pytest tests/test_low_frequency_strategy.py -v
```

This validates:
- Time interval parameters are within expected ranges
- Bid-ask spreads are appropriate for leverage levels
- Risk parameters are correctly configured
- Order lifetime matches low-frequency operation
