# ETF交易系统文档中心

**最后更新**: 2025-01-24
**维护者**: ETF Trading System Team

---

## 📚 文档导航

### 🎯 快速开始

| 文档 | 说明 | 适用人群 |
|------|------|---------|
| [用户指南](USER_GUIDE.md) | 系统使用指南和基础操作 | 新用户 |
| [部署指南](DEPLOYMENT_GUIDE.md) | 完整的部署流程和配置说明 | 运维人员 |
| [环境配置](ENV_CONFIGURATION.md) | 环境变量和配置文件说明 | 开发者/运维 |
| [故障排查](TROUBLESHOOTING.md) | 常见问题和解决方案 | 所有人 |

---

## 📖 核心文档

### 项目管理

| 文档 | 说明 | 状态 |
|------|------|------|
| [项目进度报告](PROJECT_PROGRESS_REPORT.md) | 完整的项目现状、架构和功能清单 | ✅ 最新 |
| [技术债务跟踪](TECHNICAL_DEBT.md) | TODO清单和优化计划 | ✅ 活跃 |
| [开发路线图](DEVELOPMENT_ROADMAP.md) | Phase 1-4完整规划和里程碑 | ✅ 活跃 |
| [ETF做市系统技术文档](ETF做市系统技术文档.md) | 中文技术文档（系统架构和设计） | ⚠️ 需更新 |

### 系统架构

| 文档 | 说明 |
|------|------|
| [技术栈说明](etf_strategy_technical_stack.md) | 使用的技术和框架 |
| [做市策略](etf_market_making_strategies.md) | 市场做市策略详解 |
| [API参考](API_REFERENCE.md) | 系统API接口文档 |

---

## 🚀 功能指南

### 核心功能

| 文档 | 功能 | 复杂度 |
|------|------|--------|
| [风险控制实施](RISK_CONTROL_IMPLEMENTATION.md) | 风险等级评估、止损管理 | ⭐⭐⭐ |
| [止损机制](STOP_LOSS_MECHANISM.md) | 固定/移动/时间止损详解 | ⭐⭐⭐ |
| [订单簿使用](ORDERBOOK_USAGE.md) | 智能订单簿算法系统 | ⭐⭐ |
| [K线微交易](KLINE_MICRO_TRADES_IMPLEMENTATION.md) | 模拟真实交易的K线系统 | ⭐⭐ |
| [低频策略](LOW_FREQUENCY_STRATEGY.md) | 低频交易策略配置 | ⭐ |

### 订单簿系统

| 文档 | 说明 |
|------|------|
| [订单簿使用指南](ORDERBOOK_USAGE.md) | 订单簿系统完整使用说明 |
| [订单簿集成完成](ORDERBOOK_INTEGRATION_COMPLETE.md) | 集成实施总结 |
| [快速开始 (新订单簿)](QUICK_START_NEW_ORDERBOOK.md) | 快速上手新订单簿系统 |
| [TON3L订单簿使用](TON3L_ORDERBOOK_USAGE.md) | TON3L策略订单簿配置 |
| [等值订单簿](EQUAL_VALUE_ORDERBOOK.md) | 等值订单簿算法 |

### 净值系统

| 文档 | 说明 | 状态 |
|------|------|------|
| ⏳ [净值系统指南](NET_VALUE_SYSTEM_GUIDE.md) | 综合指南（规划中） | 🚧 待创建 |

**已归档** (查看 `archived/netvalue/`):
- `NET_VALUE_PERSISTENCE_IMPLEMENTATION.md` - 数据持久化实施
- `net_value_migration_guide.md` - 迁移指南
- 其他8个净值相关文档

### WebSocket集成

| 文档 | 说明 | 状态 |
|------|------|------|
| ⏳ [WebSocket集成指南](WEBSOCKET_INTEGRATION_GUIDE.md) | 综合指南（规划中） | 🚧 待创建 |

**已归档** (查看 `archived/websocket/`):
- `WEBSOCKET_INTEGRATION.md` - 深度集成文档
- `WEBSOCKET_INTEGRATION_SUMMARY.md` - 总结版
- `WEBSOCKET_ORDER_SYNC.md` - 订单同步专题
- `ORDER_STATE_MANAGEMENT_FIX_SUMMARY.md` - 订单状态管理

---

## 🗄️ 数据库和存储

### 数据库设置

| 文档 | 说明 | 状态 |
|------|------|------|
| [PostgreSQL设置](POSTGRESQL_SETUP.md) | PostgreSQL安装和配置 | ✅ 活跃 |
| ⏳ [数据库设置指南](DATABASE_SETUP_GUIDE.md) | 综合指南（规划中） | 🚧 待创建 |

**已归档** (查看 `archived/database/`):
- `QUICKSTART_POSTGRESQL.md` - 快速开始
- `NET_VALUE_DATABASE_SETUP.md` - 净值数据库

### 余额和监控

| 文档 | 说明 |
|------|------|
| [余额检查指南](BALANCE_CHECK_GUIDE.md) | 余额监控和对账 |
| [可观测性](OBSERVABILITY.md) | 系统监控和日志 |
| [Prometheus指标](PROMETHEUS_METRICS_GUIDE.md) | Prometheus集成 |

---

## 🔐 安全和配置

| 文档 | 说明 |
|------|------|
| [API密钥安全](API_KEY_SECURITY.md) | API密钥管理和安全实践 |
| [环境配置](ENV_CONFIGURATION.md) | 环境变量详细说明 |
| [UV使用指南](uv_guide.md) | UV包管理器使用 |

---

## 🛠️ 运维和部署

| 文档 | 说明 |
|------|------|
| [部署指南](DEPLOYMENT_GUIDE.md) | 完整部署流程 |
| [故障排查](TROUBLESHOOTING.md) | 常见问题解决 |

**已归档**:
- `PACKAGING_DEPLOYMENT.md` - 打包部署（内容已合并）

---

## 📝 历史文档

### 修复历史

查看 `archived/fixes/` 目录:
- 订单簿问题修复
- 事件循环修复
- 时区修复
- 异步数据库修复
- 其他bug修复

### 订单簿历史

查看 `archived/orderbook/` 目录:
- TON3S订单溢出修复
- 订单簿分布优化
- 订单簿性能优化
- 执行器集成

---

## 🔗 相关资源

### 项目文件

- [`CLAUDE.md`](../CLAUDE.md) - Claude Code开发指南
- [`README.md`](../README.md) - 项目README（如果存在）

### 外部文档

- XT交易所API文档: https://doc.xt.com/
- Binance API文档: https://binance-docs.github.io/apidocs/

---

## 📊 文档统计

**核心文档数量**: ~30
**已归档文档**: ~30
**总文档数**: ~60

**最近更新**:
- 2025-01-24: 文档整理，归档重复文档
- 2025-01-24: 创建文档索引和导航
- 2024-11-24: 订单簿和风险控制更新

---

## 🚧 待完成文档

以下文档正在规划中:

1. ⏳ **WebSocket集成指南** - 合并3个WebSocket文档为综合指南
2. ⏳ **净值系统指南** - 合并8个净值文档为完整指南
3. ⏳ **数据库设置指南** - 合并3个数据库文档
4. ⏳ **订单簿修复历史** - 整理6个订单簿修复文档

查看 [`DOCUMENTATION_CLEANUP_2025-01-24.md`](DOCUMENTATION_CLEANUP_2025-01-24.md) 了解详细计划。

---

## 📖 如何贡献

### 添加新文档

1. 在 `docs/` 目录创建文档
2. 遵循Markdown格式规范
3. 更新此README的相应章节
4. 提交PR

### 更新现有文档

1. 修改文档内容
2. 更新文档中的"最后更新"日期
3. 如有重大变更，更新此README
4. 提交PR

### 文档规范

- **标题**: 使用清晰的层级结构
- **代码块**: 使用语法高亮
- **链接**: 使用相对路径
- **日期**: 格式为 `YYYY-MM-DD`
- **状态标记**: ✅ (活跃) | ⚠️ (需更新) | 🚧 (开发中) | ⏳ (计划中)

---

## ❓ 常见问题

### Q: 找不到某个文档？
A: 可能已被归档到 `archived/` 目录，或已合并到其他文档。查看 [`DOCUMENTATION_CLEANUP_2025-01-24.md`](DOCUMENTATION_CLEANUP_2025-01-24.md)

### Q: 文档内容过时了？
A: 请提交Issue或PR更新文档，并标注 ⚠️ 状态

### Q: 如何快速上手？
A: 按顺序阅读：[用户指南](USER_GUIDE.md) → [部署指南](DEPLOYMENT_GUIDE.md) → [环境配置](ENV_CONFIGURATION.md)

---

**文档维护**: ETF Trading System Team
**联系方式**: huangyongjie088@gmail.com
**最后审核**: 2025-01-24
