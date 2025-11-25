# ETF 做市系统文档

本目录包含 ETF 做市系统的完整技术文档。

## 文档分类

### 核心文档

| 文档 | 说明 |
|------|------|
| [ETF做市系统技术文档.md](ETF做市系统技术文档.md) | 系统核心技术文档，包含架构、做市策略、订单管理、净值计算、对冲机制等 |
| [USER_GUIDE.md](USER_GUIDE.md) | 用户指南，包含安装、配置、运行、监控说明 |
| [API_REFERENCE.md](API_REFERENCE.md) | API 参考文档，核心模块接口说明 |
| [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | 部署指南，开发/测试/生产环境部署说明 |

### 风险控制

| 文档 | 说明 |
|------|------|
| [RISK_CONTROL_IMPLEMENTATION.md](RISK_CONTROL_IMPLEMENTATION.md) | 风险控制系统实施说明，包含主循环风险控制、策略配置 |
| [STOP_LOSS_MECHANISM.md](STOP_LOSS_MECHANISM.md) | 止损机制详解，三种止损类型和价格异常保护机制 |

### 子系统文档

| 文档 | 说明 |
|------|------|
| [ORDERBOOK_USAGE.md](ORDERBOOK_USAGE.md) | 订单簿模块使用指南 |
| [INITIALIZATION_SYSTEM.md](INITIALIZATION_SYSTEM.md) | 系统初始化机制说明 |
| [LOW_FREQUENCY_STRATEGY.md](LOW_FREQUENCY_STRATEGY.md) | 低频交易策略参数说明 |
| [KLINE_MICRO_TRADES_IMPLEMENTATION.md](KLINE_MICRO_TRADES_IMPLEMENTATION.md) | K线质量优化和微交易实现 |
| [BALANCE_CHECK_GUIDE.md](BALANCE_CHECK_GUIDE.md) | 余额检查功能指南 |

### 运维配置

| 文档 | 说明 |
|------|------|
| [ENV_CONFIGURATION.md](ENV_CONFIGURATION.md) | 环境变量配置说明 |
| [API_KEY_SECURITY.md](API_KEY_SECURITY.md) | API 密钥安全管理 |
| [POSTGRESQL_SETUP.md](POSTGRESQL_SETUP.md) | PostgreSQL 数据库配置 |
| [PROMETHEUS_METRICS_GUIDE.md](PROMETHEUS_METRICS_GUIDE.md) | Prometheus 监控指标指南 |
| [uv_guide.md](uv_guide.md) | uv 包管理器使用指南 |

### 参考资料

| 文档 | 说明 |
|------|------|
| [ETF定价和对冲.pdf](ETF定价和对冲.pdf) | ETF 定价和对冲理论参考 |

## 快速入门

1. **新手入门**: 先阅读 [USER_GUIDE.md](USER_GUIDE.md)
2. **部署上线**: 参考 [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
3. **理解系统**: 阅读 [ETF做市系统技术文档.md](ETF做市系统技术文档.md)
4. **风险控制**: 了解 [STOP_LOSS_MECHANISM.md](STOP_LOSS_MECHANISM.md)

## 文档版本

- **最后更新**: 2025-11-25
- **维护者**: ETF Trading Team
