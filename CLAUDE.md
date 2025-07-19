# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a cryptocurrency ETF trading system that integrates with Binance and XT exchanges. It implements automated market-making strategies, risk management, and order execution for leveraged ETF products (3x and 5x, both long and short).

## Language Notes

- 支持中文交互和代码注释，以便更好地与中文开发团队沟通
- 用中文对话可以提高代码理解和协作效率

## Development Commands

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

### Building and Installation
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

# Override parameters
python run_etf.py --strategy stg3l --bid-ask-spread 0.02
python run_etf.py --strategy stg5s --env qa
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
# Using PM2 (production)
pm2 start run.sh

# Run specific components
python net_value_stg3l.py  # Net value calculation
python hedging_stg3l.py    # Hedging operations
```

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