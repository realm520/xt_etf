# 文档整理计划

**日期**: 2025-01-24
**执行人**: Claude Code
**状态**: 规划中

---

## 整理原则

1. **消除重复**: 合并内容重复的文档
2. **归档过时**: 将不再相关的文档移到 `docs/archived/`
3. **优化结构**: 按主题组织文档
4. **创建索引**: 提供清晰的文档导航

---

## 📋 重复文档处理

### 1. 订单簿问题修复 (保留1个,归档2个)

**保留**:
- ✅ `EMPTY_ORDERBOOK_FIX.md` - 最完整的修复文档 (9.6KB)

**归档**:
- ⏳ `FIX_SUMMARY_EMPTY_ORDERBOOK.md` → `archived/` - 简化版本,与主文档重复
- ⏳ `ORDERBOOK_ISSUE_ANALYSIS.md` → `archived/` - 问题分析,已包含在主文档中

**理由**: `EMPTY_ORDERBOOK_FIX.md` 包含完整的问题分析、解决方案和测试验证

---

### 2. WebSocket集成 (合并为1个综合文档)

**保留**:
- ✅ `WEBSOCKET_INTEGRATION_GUIDE.md` (新建) - 综合指南

**归档**:
- ⏳ `WEBSOCKET_INTEGRATION.md` - 深度集成 (438行)
- ⏳ `WEBSOCKET_INTEGRATION_SUMMARY.md` - 总结版 (423行)
- ⏳ `WEBSOCKET_ORDER_SYNC.md` - 订单同步 (715行)

**操作**: 提取各文档精华,创建统一的 WebSocket 集成指南

**新文档结构**:
```
1. 概述
   - 系统架构
   - 核心组件
2. Depth WebSocket (市场数据)
   - 协议说明
   - 集成示例
   - 性能对比
3. Order WebSocket (订单同步)
   - 实时订单更新
   - 集成示例
   - 降级策略
4. 配置和监控
5. 故障排查
```

---

### 3. 净值系统 (合并为1个指南)

**保留**:
- ✅ `NET_VALUE_SYSTEM_GUIDE.md` (新建) - 综合系统指南

**归档**:
- ⏳ `NET_VALUE_PERSISTENCE_IMPLEMENTATION.md` - 实施总结 (1078行)
- ⏳ `net_value_migration_guide.md` - 迁移指南 (约500行)
- ⏳ `NET_VALUE_PUSH_INTEGRATION.md` - 推送集成
- ⏳ `NET_VALUE_PUSH_GUIDE.md` - 推送指南
- ⏳ `NET_VALUE_PUSH_CONFIG_SUMMARY.md` - 配置总结
- ⏳ `NET_VALUE_ENV_CONFIG_UPDATE.md` - 环境配置更新
- ⏳ `NET_VALUE_API_TROUBLESHOOTING.md` - API故障排查
- ⏳ `redis_last_amount_migration.md` - Redis迁移

**新文档结构**:
```
1. 系统概述
2. 核心功能
   - 实时计算
   - 数据持久化
   - API推送
3. 部署指南
   - 数据库设置
   - 环境配置
   - 迁移步骤
4. 配置参考
5. 故障排查
```

---

### 4. 数据库设置 (合并为1个指南)

**保留**:
- ✅ `DATABASE_SETUP_GUIDE.md` (新建) - 综合数据库指南

**归档**:
- ⏳ `POSTGRESQL_SETUP.md` - PostgreSQL安装 (446行)
- ⏳ `QUICKSTART_POSTGRESQL.md` - 快速开始 (367行)
- ⏳ `NET_VALUE_DATABASE_SETUP.md` - 净值数据库 (571行)

**新文档结构**:
```
1. 概述
   - 数据库架构
   - 表结构设计
2. 安装和配置
   - PostgreSQL安装
   - 数据库初始化
   - 权限设置
3. 应用集成
   - 净值数据持久化
   - 订单记录
4. 运维管理
   - 备份恢复
   - 性能优化
```

---

### 5. 部署文档 (合并为1个)

**保留**:
- ✅ `DEPLOYMENT_GUIDE.md` - 主部署指南 (扩展内容)

**归档**:
- ⏳ `PACKAGING_DEPLOYMENT.md` - 打包部署 (578行)

**操作**: 将 `PACKAGING_DEPLOYMENT.md` 内容合并到 `DEPLOYMENT_GUIDE.md`

---

### 6. 订单簿优化历史 (合并为历史文档)

**保留**:
- ✅ `ORDERBOOK_FIXES_HISTORY.md` (新建) - 订单簿修复历史

**归档**:
- ⏳ `TON3S_ORDERBOOK_FIX.md` - TON3S修复
- ⏳ `TON3S_ORDER_OVERFLOW_FIX_SUMMARY.md` - 溢出修复总结
- ⏳ `TON3S_ORDER_OVERFLOW_ANALYSIS.md` - 溢出分析
- ⏳ `ORDERBOOK_DISTRIBUTION_OPTIMIZATION.md` - 分布优化
- ⏳ `ORDERBOOK_PERFORMANCE_OPTIMIZATION.md` - 性能优化
- ⏳ `ORDERBOOK_EXECUTOR_INTEGRATION.md` - 执行器集成

**新文档结构** (编年史风格):
```
1. 概述
2. 修复历史
   - 2025-XX: TON3S订单溢出修复
   - 2025-XX: 订单簿分布优化
   - 2025-XX: 性能优化
3. 经验总结
4. 最佳实践
```

---

## 🗂️ 新文档结构

```
docs/
├── README.md (新建) - 文档导航和索引
├── archived/ - 归档的旧文档
│   ├── websocket/ - WebSocket相关归档
│   ├── orderbook/ - 订单簿相关归档
│   └── netvalue/ - 净值系统相关归档
│
├── 核心文档/
│   ├── PROJECT_PROGRESS_REPORT.md - 项目进度报告
│   ├── TECHNICAL_DEBT.md - 技术债务跟踪
│   ├── DEVELOPMENT_ROADMAP.md - 开发路线图
│   └── ETF做市系统技术文档.md - 中文技术文档
│
├── 部署和运维/
│   ├── DEPLOYMENT_GUIDE.md - 部署指南
│   ├── DATABASE_SETUP_GUIDE.md - 数据库设置
│   ├── ENV_CONFIGURATION.md - 环境配置
│   └── TROUBLESHOOTING.md - 故障排查
│
├── 功能指南/
│   ├── WEBSOCKET_INTEGRATION_GUIDE.md - WebSocket集成
│   ├── NET_VALUE_SYSTEM_GUIDE.md - 净值系统
│   ├── RISK_CONTROL_IMPLEMENTATION.md - 风险控制
│   ├── STOP_LOSS_MECHANISM.md - 止损机制
│   └── KLINE_MICRO_TRADES_IMPLEMENTATION.md - K线微交易
│
├── 订单簿系统/
│   ├── ORDERBOOK_USAGE.md - 使用指南
│   ├── ORDERBOOK_INTEGRATION_COMPLETE.md - 集成完成
│   └── ORDERBOOK_FIXES_HISTORY.md - 修复历史
│
├── API和安全/
│   ├── API_REFERENCE.md - API参考
│   ├── API_KEY_SECURITY.md - API密钥安全
│   └── USER_GUIDE.md - 用户指南
│
└── 监控和可观测性/
    ├── OBSERVABILITY.md - 可观测性
    ├── PROMETHEUS_METRICS_GUIDE.md - Prometheus指标
    └── BALANCE_CHECK_GUIDE.md - 余额检查
```

---

## 📝 执行步骤

### Phase 1: 归档重复文档 (本次执行)

```bash
mkdir -p docs/archived/{websocket,orderbook,netvalue,fixes}

# 订单簿问题
mv FIX_SUMMARY_EMPTY_ORDERBOOK.md docs/archived/fixes/
mv ORDERBOOK_ISSUE_ANALYSIS.md docs/archived/fixes/

# WebSocket相关
mv WEBSOCKET_INTEGRATION.md docs/archived/websocket/
mv WEBSOCKET_INTEGRATION_SUMMARY.md docs/archived/websocket/
mv WEBSOCKET_ORDER_SYNC.md docs/archived/websocket/

# 净值系统
mv NET_VALUE_PERSISTENCE_IMPLEMENTATION.md docs/archived/netvalue/
mv net_value_migration_guide.md docs/archived/netvalue/
mv NET_VALUE_PUSH_*.md docs/archived/netvalue/
mv redis_last_amount_migration.md docs/archived/netvalue/

# 数据库设置
mv QUICKSTART_POSTGRESQL.md docs/archived/
mv NET_VALUE_DATABASE_SETUP.md docs/archived/netvalue/

# 订单簿优化
mv TON3S_*.md docs/archived/orderbook/
mv ORDERBOOK_DISTRIBUTION_OPTIMIZATION.md docs/archived/orderbook/
mv ORDERBOOK_EXECUTOR_INTEGRATION.md docs/archived/orderbook/
```

### Phase 2: 创建综合指南 (下一步)

1. **WebSocket集成指南** - 合并3个WebSocket文档
2. **净值系统指南** - 合并8个净值相关文档
3. **数据库设置指南** - 合并3个数据库文档
4. **订单簿修复历史** - 整理6个订单簿文档

### Phase 3: 创建文档索引 (最后)

创建 `docs/README.md` 提供清晰的文档导航

---

## ✅ 完成标准

- [x] 重复文档已归档
- [ ] 新综合指南已创建
- [ ] 文档索引已建立
- [ ] 所有链接已更新
- [ ] 文档结构已优化

---

## 📊 预期效果

**Before**:
- 文档数量: 60+
- 重复内容: 高
- 结构: 混乱
- 导航: 困难

**After**:
- 文档数量: ~30 (核心)
- 重复内容: 无
- 结构: 清晰
- 导航: 简单

**减少文档数**: ~50%
**提高可维护性**: 显著

---

**创建时间**: 2025-01-24
**负责人**: Claude Code
**审核状态**: 待执行
