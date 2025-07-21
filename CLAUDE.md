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

# 导出依赖
uv pip freeze > requirements.txt
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

# Install with all dependencies
pip install -r requirements.txt
```

### Running the Trading System

#### Recommended Method (New Unified System)
```bash
# Using strategy mode
python run_etf.py --strategy stg3l  # 3x long strategy
python run_etf.py --strategy stg3s  # 3x short strategy
python run_etf.py --strategy stg5l  # 5x long strategy
python run_etf.py --strategy stg5s  # 5x short strategy

# Using convenience scripts
./scripts/run_stg3l.sh  # 3x long
./scripts/run_stg3s.sh  # 3x short
./scripts/run_stg5l.sh  # 5x long
./scripts/run_stg5s.sh  # 5x short

# Development mode (starts both net value and trading)
./scripts/dev_start.sh stg3l  # 3x long with net value service
./scripts/dev_start.sh stg3s  # 3x short with net value service
./scripts/dev_start.sh stg5l  # 5x long with net value service
./scripts/dev_start.sh stg5s  # 5x short with net value service

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

#### Low-Frequency Strategy Monitoring
```bash
# Run monitoring script
python monitor_low_freq.py

# Run tests for low-frequency parameters
pytest tests/test_low_frequency_strategy.py -v
```

#### Legacy Method (Original scripts archived in `legacy/`)
```bash
# Original scripts (still available but not recommended)
python legacy/run_etf_stg3l.py
python legacy/run_etf_stg3s.py
python legacy/run_etf_stg5l.py
python legacy/run_etf_stg5s.py
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

- API keys stored in `APIKey*.json` files (different environments)
- Strategy parameters embedded in individual runner scripts
- Redis connection defaults to localhost:6379
- Logging configured per component with rotation

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
