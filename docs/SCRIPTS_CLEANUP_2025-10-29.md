# Scripts 目录清理记录

**清理日期**: 2025-10-29
**执行人**: Claude
**目的**: 清理临时调试脚本，整理项目结构

## 清理摘要

- **删除文件**: 9个（调试脚本 + 一次性查询脚本）
- **移动文件**: 5个（测试脚本移至 tests/ 目录）
- **保留文件**: 24个（生产运维所需脚本）
- **更新文档**: scripts/README.md

## 清理详情

### 1. 已删除的调试脚本（6个）

这些脚本用于排查特定问题，问题已通过相关文档解决：

| 脚本名 | 用途 | 解决方案文档 |
|--------|------|-------------|
| diagnose_websocket.py | WebSocket连接诊断 | WEBSOCKET_INTEGRATION.md |
| diagnose_orderbook.py | 订单簿数据诊断 | EVENT_LOOP_FIX.md |
| debug_order_matching.py | 订单匹配调试 | 代码已修复 |
| monitor_orderbook.py | 临时订单簿监控 | 已集成到主系统 |
| verify_timezone_fix.py | 时区修复验证 | TIMEZONE_FIX.md |
| test_alert.py | 告警系统测试 | 一次性测试已完成 |

### 2. 已删除的一次性查询脚本（3个）

这些脚本是临时查询工具，功能已集成到主系统：

| 脚本名 | 用途 | 替代方案 |
|--------|------|---------|
| query_orders.py | 订单查询 | 功能已集成到监控系统 |
| quick_check_orders.sh | 快速订单检查 | 使用 monitor_last_amount.py |
| check_live_orders.py | 活跃订单检查 | 功能已集成到监控系统 |

### 3. 已移到 tests/ 目录的测试脚本（5个）

这些脚本属于测试代码，统一移至测试目录管理：

- `test_update_net_worth.py` - 净值更新测试
- `test_order_recorder_fix.py` - 订单记录器修复测试
- `test_net_value_db_init.py` - 净值数据库初始化测试
- `test_net_value_persistence.py` - 净值持久化测试
- `test_db_integration.py` - 数据库集成测试

### 4. 保留的脚本（24个）

#### 运行脚本（11个）
- `run_stg3l.sh` - 3x做多策略
- `run_stg3s.sh` - 3x做空策略
- `run_stg5l.sh` - 5x做多策略
- `run_stg5s.sh` - 5x做空策略
- `run_net_value_stg3l.sh` - 3x做多净值计算
- `run_net_value_stg3s.sh` - 3x做空净值计算
- `run_net_value_stg5l.sh` - 5x做多净值计算
- `run_net_value_stg5s.sh` - 5x做空净值计算
- `dev_start.sh` - 开发环境启动
- `run_strategy.sh` - 通用策略运行
- `run_tests.sh` - 测试套件执行

#### 部署和维护脚本（5个）
- `deploy.sh` - 生产环境部署
- `rollback.sh` - 版本回滚
- `package.sh` - 项目打包
- `setup_uv.sh` - uv环境设置
- `check_dependencies.sh` - 依赖检查

#### 工具脚本（5个）
- `encrypt_apikeys.py` - API密钥加密
- `validate_config.py` - 配置验证
- `account.sh` - 账户查询
- `init_database.py` - 数据库初始化
- `init_net_value_tables.py` - 净值表初始化

#### 监控脚本（3个）
- `start_monitor.py` - 监控系统启动
- `monitor_last_amount.py` - 持仓数量监控
- `monitor_net_value_persistence.py` - 净值持久化监控

## 清理效果

### 前后对比

| 指标 | 清理前 | 清理后 | 变化 |
|------|--------|--------|------|
| 总文件数 | ~38个 | 24个 | -37% |
| 调试脚本 | 9个 | 0个 | -100% |
| 测试脚本位置 | scripts/ | tests/ | 结构优化 |
| 文档完整性 | 中等 | 完善 | 新增清理说明 |

### 改进点

1. **结构更清晰**: 脚本按功能分类，易于查找和维护
2. **职责分明**: 测试代码移至 tests/ 目录，符合项目规范
3. **减少混淆**: 删除已过时的调试脚本，避免误用
4. **文档完善**: 更新 README.md，添加清理说明和脚本分类

## 维护建议

### 1. 未来添加脚本的原则

- **临时调试脚本**: 问题解决后立即删除，相关知识沉淀到文档
- **测试脚本**: 应统一放在 tests/ 目录
- **生产工具**: 需要完整的文档说明和使用示例
- **一次性脚本**: 完成任务后及时清理

### 2. 定期清理检查项

建议每季度进行一次清理检查：

- [ ] 检查是否有超过3个月未使用的脚本
- [ ] 验证所有保留脚本是否有文档说明
- [ ] 确认测试脚本是否在正确目录
- [ ] 清理 __pycache__ 等临时文件

### 3. 脚本命名规范

- **运行脚本**: `run_*.sh` 或 `start_*.sh`
- **监控脚本**: `monitor_*.py`
- **初始化脚本**: `init_*.py`
- **工具脚本**: 使用动词开头（如 `encrypt_`, `validate_`）
- **测试脚本**: `test_*.py`（统一放在 tests/ 目录）

## 相关文档

清理过程中参考的问题解决方案文档：

- `docs/WEBSOCKET_INTEGRATION.md` - WebSocket集成指南
- `docs/EVENT_LOOP_FIX.md` - 事件循环问题修复
- `docs/TIMEZONE_FIX.md` - 时区问题修复
- `docs/ASYNC_DB_FIX.md` - 异步数据库修复
- `docs/NET_VALUE_API_TROUBLESHOOTING.md` - 净值API故障排查

这些文档记录了问题的根本原因和永久解决方案，避免了保留临时调试脚本的必要性。

## 验证步骤

清理完成后执行以下检查：

```bash
# 1. 检查关键脚本是否存在
ls -la scripts/run_stg*.sh
ls -la scripts/{deploy,rollback,setup_uv}.sh
ls -la scripts/{start_monitor,monitor_last_amount}.py

# 2. 验证测试脚本已移动
ls -la tests/test_*.py | grep -E "net_value|order_recorder|db_integration"

# 3. 确认调试脚本已删除
ls -la scripts/ | grep -E "diagnose|debug|verify" && echo "发现残留调试脚本！" || echo "清理完成"

# 4. 检查文档更新
grep -q "清理说明" scripts/README.md && echo "文档已更新" || echo "文档需要更新"
```

## 总结

本次清理成功精简了 scripts 目录，提高了项目可维护性。保留的24个脚本都是生产环境运维所需的核心工具，文档完善，结构清晰。

清理过程遵循了以下原则：
- ✅ 保留生产必需的运维工具
- ✅ 删除已解决问题的临时脚本
- ✅ 整理测试代码到正确位置
- ✅ 完善文档说明和使用指南

**状态**: 清理完成 ✓
**建议**: 建议每季度进行一次类似的清理和检查
