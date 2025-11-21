# ETF 策略启动脚本

## 安装依赖

```bash
pip install pyyaml
```

## 使用方法

### 新的统一启动方式

1. **使用策略模式启动**（推荐）：
   ```bash
   python run_etf.py --strategy stg3l  # 3倍做多
   python run_etf.py --strategy stg3s  # 3倍做空
   python run_etf.py --strategy stg5l  # 5倍做多
   python run_etf.py --strategy stg5s  # 5倍做空
   ```

2. **使用便捷脚本**：
   ```bash
   ./scripts/run_stg3l.sh
   ./scripts/run_stg3s.sh
   ./scripts/run_stg5l.sh
   ./scripts/run_stg5s.sh
   ```

3. **对比原启动方式**：
   ```bash
   # 原始方式（仍然可用）
   python run_etf_stg3l.py
   python run_etf_stg3s.py
   python run_etf_stg5l.py
   python run_etf_stg5s.py
   ```

### 命令行参数覆盖

使用策略模式时，仍然可以通过命令行参数覆盖配置：

```bash
# 覆盖买卖价差
python run_etf.py --strategy stg3l --bid-ask-spread 0.02

# 覆盖洗盘间隔
python run_etf.py --strategy stg3s --washing-interval 3

# 使用测试环境
python run_etf.py --strategy stg5l --env qa
```

### 验证配置

运行验证脚本确保新旧配置一致：

```bash
python scripts/validate_config.py
```

## 策略特点

| 策略 | 杠杆 | 方向 | 主循环间隔 | 洗盘间隔 | 买卖价差 | 特殊行为 |
|------|------|------|-----------|---------|---------|----------|
| STG3L | 3x | 做多 | 5秒 | 5秒 | 1% | - |
| STG3S | 3x | 做空 | 1秒 | 1秒 | 1% | - |
| STG5L | 5x | 做多 | 1秒 | 1秒 | 1% | 启动时取消所有订单 |
| STG5S | 5x | 做空 | 1秒 | 1秒 | 5% | 特殊的订单取消逻辑 |

## 脚本分类（8个核心脚本）

### 开发环境（1个）
- `dev_start.sh` - 开发环境启动脚本（同时启动净值计算和交易）

### 部署和维护（6个）
- `deploy.sh` - 生产环境部署脚本
- `rollback.sh` - 版本回滚脚本
- `package.sh` - 项目打包脚本
- `setup_uv.sh` - uv包管理器环境设置
- `check_dependencies.sh` - 依赖完整性检查
- `run_tests.sh` - 测试套件执行

### 工具脚本（1个）
- `account.sh` - 账户余额和持仓查询

### 其他工具（Python脚本放在项目根目录）
- `encrypt_apikeys.py` - API密钥加密工具（根目录）
- `validate_config.py` - 策略配置验证工具（根目录）
- `init_database.py` - PostgreSQL数据库初始化（根目录）
- `init_net_value_tables.py` - 净值表结构初始化（根目录）
- `start_monitor.py` - 启动完整监控系统（根目录）
- `monitor_last_amount.py` - 持仓数量实时监控（根目录）
- `monitor_net_value_persistence.py` - 净值持久化监控（根目录）

## 清理历史

### 2025-11-21 第二轮清理（14:16）
**移除冗余包装脚本**（已移至 `archive/scripts_deprecated/`）：

**策略运行脚本**（9个）：
- `run_stg3l.sh` / `run_stg3s.sh` / `run_stg5l.sh` / `run_stg5s.sh`
- `run_net_value_stg3l.sh` / `run_net_value_stg3s.sh` / `run_net_value_stg5l.sh` / `run_net_value_stg5s.sh`
- `run_strategy.sh`

**清理原因**：
- ❌ 不必要的抽象层：仅仅是 `python run_etf.py --strategy <name>` 的包装
- ❌ 增加维护负担：每个策略需要单独的脚本文件
- ❌ PM2不需要：直接调用Python更简洁
- ✅ KISS原则：保持简单，去掉中间层

**替代方案**：
```bash
# 直接运行（推荐）
python run_etf.py --strategy stg3l
python run_net_value.py --strategy stg3l

# PM2管理（生产环境）
pm2 start ecosystem.config.js --only etf-stg3l

# 开发环境（保留）
./scripts/dev_start.sh stg3l  # 同时启动净值+交易
```

### 2025-11-21 第一轮清理（14:00）
**废弃脚本归档**（已移至 `archive/scripts_deprecated/`）：
- `check_natural_kline.sh` - TON3S自然K线诊断脚本（问题已解决）
- `diagnose_natural_kline.sh` - 自然K线完整诊断（已不再使用）
- `restart_ton3l.sh` - TON3L策略重启脚本（可用通用方式替代）
- `generate_synthetic_trades.py` - 合成成交数据生成器（未在生产使用）

**数据分析脚本重组**（已移至 `analysis/`）：
- `analyze_trades.py` - 成交数据分析工具（一次性分析用途）

**清理原因**：
1. TON3S策略相关问题已通过代码修复解决，诊断脚本不再需要
2. 合成成交数据生成器为研究性质工具，不属于生产运维脚本
3. 数据分析工具更适合放在专门的 `analysis/` 目录中

### 2025-10-29 清理记录
**已删除的调试脚本**（问题已解决）：
- `diagnose_websocket.py` - WebSocket连接诊断（已通过 WEBSOCKET_INTEGRATION.md 解决）
- `diagnose_orderbook.py` - 订单簿数据诊断（已通过 EVENT_LOOP_FIX.md 解决）
- `debug_order_matching.py` - 订单匹配调试（问题已修复）
- `monitor_orderbook.py` - 临时订单簿监控（已集成到主系统）
- `verify_timezone_fix.py` - 时区修复验证（已通过 TIMEZONE_FIX.md 解决）
- `test_alert.py` - 告警系统一次性测试

**已删除的一次性查询脚本**：
- `query_orders.py` - 订单查询工具（功能已集成）
- `quick_check_orders.sh` - 快速订单检查脚本
- `check_live_orders.py` - 活跃订单检查（功能已集成）

**已移到 tests/ 目录的测试脚本**：
- `test_update_net_worth.py` - 净值更新测试
- `test_order_recorder_fix.py` - 订单记录器修复测试
- `test_net_value_db_init.py` - 净值数据库初始化测试
- `test_net_value_persistence.py` - 净值持久化测试
- `test_db_integration.py` - 数据库集成测试

相关问题的解决方案详见：
- WebSocket集成：`docs/WEBSOCKET_INTEGRATION.md`
- 事件循环修复：`docs/EVENT_LOOP_FIX.md`
- 时区问题修复：`docs/TIMEZONE_FIX.md`
- 异步数据库修复：`docs/ASYNC_DB_FIX.md`
- 净值API故障排查：`docs/NET_VALUE_API_TROUBLESHOOTING.md`

## 注意事项

1. 新的策略模式完全保持了原有的参数值和行为
2. STG5S 的特殊订单取消逻辑已在代码中处理
3. 使用策略模式时会初始化余额（与单独文件行为一致）
4. 所有 API 密钥配置保持不变
5. 测试相关脚本已统一移至 `tests/` 目录进行管理
6. 保留的监控脚本都是生产环境运维所需的工具