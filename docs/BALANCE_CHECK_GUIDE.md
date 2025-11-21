# 资金检查功能使用指南

## 概述

资金检查功能是一个自动监控账户余额的系统，当资金不足时会输出告警日志并建议停止策略，防止因资金不足导致订单失败。

## 功能特性

### 1. 四级资金状态监控

- **充足 (SUFFICIENT)**: 剩余资金 > 30%，正常运行
- **警告 (WARNING)**: 剩余资金 10-30%，输出警告日志
- **危急 (CRITICAL)**: 剩余资金 5-10%，输出错误日志，建议充值
- **不足 (INSUFFICIENT)**: 剩余资金 < 10%，输出告警日志，建议停止策略

### 2. 智能资金计算

- 自动扣除挂单占用的资金
- 计算实际可用资金
- 考虑最小订单金额限制

### 3. 告警机制

- 状态变化时立即告警
- 持续异常状态定期提醒
- 支持多种告警级别

### 4. 下单前检查

- 每次批量下单前自动检查资金
- 资金不足时拒绝下单
- 避免无效订单浪费资源

## 配置说明

### 在 strategies.yaml 中配置

每个策略都可以单独配置资金检查参数：

```yaml
strategies:
  ton3l:
    # ... 其他配置 ...
    
    # 资金检查配置
    balance_check:
      enabled: true                   # 是否启用资金检查
      warning_threshold: 0.3          # 警告阈值（剩余资金比例30%）
      critical_threshold: 0.2         # 危急阈值（剩余资金比例20%）
      insufficient_threshold: 0.1     # 不足阈值（剩余资金比例10%）
      check_interval: 60              # 检查间隔（秒）
```

### 配置参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| enabled | bool | false | 是否启用资金检查 |
| warning_threshold | float | 0.3 | 警告阈值，剩余资金比例 |
| critical_threshold | float | 0.2 | 危急阈值，剩余资金比例 |
| insufficient_threshold | float | 0.1 | 不足阈值，剩余资金比例 |
| check_interval | int | 60 | 检查间隔（秒） |

## 使用示例

### 1. 启用资金检查

在 `config/strategies.yaml` 中设置 `balance_check.enabled: true`：

```yaml
strategies:
  ton3l:
    balance_check:
      enabled: true
```

重启策略后自动生效。

### 2. 查看资金检查日志

启用后会在日志中看到类似输出：

```
INFO - ✅ [ton3l] 资金检查已启用 (警告:30.0%, 危急:20.0%, 不足:10.0%, 间隔:60秒)
```

### 3. 资金状态日志示例

**充足状态**（不输出日志）：
```
# 静默运行，无日志
```

**警告状态**：
```
WARNING - [ton3l] 资金状态异常: [ton3l] 资金状态检查 | 状态: WARNING | 总余额: 10000.00 USDT | 可用余额: 2500.00 USDT | 挂单占用: 0.00 USDT | 实际可用: 2500.00 USDT | 资金使用率: 75.00% | 剩余资金比例: 25.00% | 可下单: 是 | 💡 建议: 关注资金状况
```

**危急状态**：
```
ERROR - [ton3l] 资金状态异常: [ton3l] 资金状态检查 | 状态: CRITICAL | 总余额: 10000.00 USDT | 可用余额: 1500.00 USDT | 挂单占用: 0.00 USDT | 实际可用: 1500.00 USDT | 资金使用率: 85.00% | 剩余资金比例: 15.00% | 可下单: 是 | ⚠️ 建议: 考虑暂停策略或充值
```

**不足状态**：
```
CRITICAL - [ton3l] 资金不足，建议停止策略！[ton3l] 资金状态检查 | 状态: INSUFFICIENT | 总余额: 10000.00 USDT | 可用余额: 500.00 USDT | 挂单占用: 0.00 USDT | 实际可用: 500.00 USDT | 资金使用率: 95.00% | 剩余资金比例: 5.00% | 可下单: 是 | ⚠️ 建议: 立即停止策略并充值
CRITICAL - [ton3l] 资金不足，取消下单！...
```

## 运行测试

### 1. 运行单元测试

```bash
python3 tests/manual_test_balance_checker.py
```

测试输出示例：

```
🚀 开始资金检查器验证测试

============================================================
测试1: 基本功能验证
============================================================

1. 测试资金充足状态 (60%可用)
   状态: sufficient
   应停止策略: False
   ✅ 通过

2. 测试资金警告状态 (25%可用)
   状态: warning
   应停止策略: False
   ✅ 通过

...

🎉 所有测试通过！资金检查器功能正常！
```

### 2. 实际运行验证

启用配置后运行策略：

```bash
python run_etf.py --strategy ton3l
```

观察日志输出，确认资金检查功能正常工作。

## 工作流程

### 主循环集成

```
程序启动
  ↓
读取配置 (balance_check.enabled)
  ↓
启用资金检查器 (如果enabled=true)
  ↓
主循环运行
  ↓
批量下单前
  ↓
检查资金是否充足
  ├─ 充足 → 继续下单
  ├─ 警告/危急 → 记录日志，继续下单
  └─ 不足 → 拒绝下单，输出告警
```

### 资金检查逻辑

```
获取账户余额
  ↓
计算挂单占用金额
  ↓
计算实际可用金额 = 可用余额 - 挂单占用
  ↓
计算剩余资金比例 = 实际可用 / 总余额
  ↓
判断资金状态
  ├─ > 30% → SUFFICIENT (充足)
  ├─ 10-30% → WARNING (警告)
  ├─ 5-10% → CRITICAL (危急)
  └─ < 10% → INSUFFICIENT (不足)
  ↓
输出日志/告警
  ↓
判断是否应停止策略
  └─ INSUFFICIENT → 建议停止
```

## 注意事项

### 1. 检查间隔

- 默认60秒检查一次
- 避免频繁检查影响性能
- 可根据策略特点调整间隔

### 2. 阈值设置

- 默认阈值适用于大多数场景
- 高杠杆策略建议提高阈值（更保守）
- 低频策略可适当降低阈值

### 3. 挂单影响

- 挂单会占用资金，影响可用余额
- 系统自动扣除挂单占用
- 建议留足余量避免频繁触发告警

### 4. 告警处理

- 收到WARNING告警：关注资金状况，考虑充值
- 收到CRITICAL告警：尽快充值或暂停部分策略
- 收到INSUFFICIENT告警：立即停止策略并充值

## 故障排查

### 问题1：配置已启用但没有日志输出

**可能原因**：
- 配置文件格式错误
- 缩进不正确
- 配置未生效（需要重启）

**解决方法**：
1. 检查 `strategies.yaml` 格式
2. 确认 `balance_check.enabled: true`
3. 重启策略进程

### 问题2：频繁触发WARNING告警

**可能原因**：
- 资金确实不足
- 挂单过多占用资金
- 阈值设置过高

**解决方法**：
1. 充值增加资金
2. 减少挂单数量或金额
3. 调整 `warning_threshold` 参数

### 问题3：资金充足但仍触发告警

**可能原因**：
- 挂单占用未正确计算
- 阈值配置错误
- 程序bug

**解决方法**：
1. 检查挂单占用是否正确
2. 确认配置参数
3. 查看详细日志，联系开发

## 技术细节

### 核心文件

- `etf/balance_checker.py`: 资金检查器核心模块
- `etf/order_manager.py`: 集成到订单管理器
- `run_etf.py`: 主循环集成
- `config/strategies.yaml`: 配置文件
- `tests/manual_test_balance_checker.py`: 测试脚本

### 核心类

```python
class BalanceChecker:
    """资金检查器"""
    
    def check_balance(self, available_balance, total_balance, pending_order_value):
        """检查资金充足性"""
        # 返回 (status, message)
    
    def should_stop_strategy(self, status):
        """判断是否应该停止策略"""
        # 返回 True/False
```

### 核心方法

```python
# OrderManager中的方法
def enable_balance_check(self, warning_threshold, critical_threshold, ...):
    """启用资金检查功能"""

def check_balance_before_order(self, symbol, force_check):
    """下单前检查资金是否充足"""
    # 返回 (can_place_order, message)
```

## 总结

资金检查功能提供了完整的资金监控和告警机制，能够有效防止因资金不足导致的订单失败。建议：

1. ✅ 所有生产策略都启用资金检查
2. ✅ 根据策略特点调整阈值
3. ✅ 定期查看日志，关注资金状况
4. ✅ 收到告警及时处理，避免影响交易

---

**相关文档**：
- [项目进度报告](./PROJECT_PROGRESS_REPORT.md)
- [技术债务跟踪](./TECHNICAL_DEBT.md)
- [开发路线图](./DEVELOPMENT_ROADMAP.md)
