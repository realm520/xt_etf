# 净值推送到交易所功能指南

## 概述

`run_net_value.py` 和 `ImprovedNetValue` 类支持将计算的净值实时推送到交易所。该功能通过**全局配置**管理，所有策略共享相同的推送设置。

## 核心特性

### 1. 全局配置管理 ⭐
- 统一的全局配置，所有策略共享
- 环境自动切换（QA/生产）
- Symbol自动映射或自动生成

### 2. 自动推送
- 根据配置的推送间隔（默认60秒）自动推送净值
- 只在净值更新时推送，避免无效请求
- 推送间隔独立于净值计算间隔

### 3. 智能重试机制
- 失败自动重试（默认3次）
- 指数退避策略（1秒、2秒、4秒）
- 详细的错误日志和异常记录

### 4. 环境支持
- 支持QA和生产环境
- 自动切换API主机地址
- 环境特定的配置管理

### 5. 安全性
- API密钥从配置文件加载
- 支持多策略密钥管理
- 推送前验证净值有效性

## 配置方法

### 步骤1: 修改全局配置文件 ⭐

编辑 `config/strategies.yaml`，在**全局配置区域**（文件顶部）修改 `net_value_push` 配置：

```yaml
# 全局配置
# ========================================

# 净值推送配置（推送到交易所）
net_value_push:
  enabled: true             # 全局开关：是否启用推送到交易所（默认关闭）
  interval: 60              # 推送间隔（秒），建议60秒
  retry_count: 3            # 推送失败重试次数
  retry_backoff: true       # 启用指数退避重试（1s, 2s, 4s）

  # 环境配置（根据 --env 参数自动选择）
  environments:
    qa:
      host: "https://sapi.xt-qa2.com"
    prod:
      host: "https://sapi.xt.com"

  # 策略Symbol映射（可选，不填则自动生成）
  symbol_mapping:
    ton3l: "TON3L_USDT"
    ton3s: "TON3S_USDT"
    stg3l: "STG3L_USDT"
    stg3s: "STG3S_USDT"
    stg5l: "STG5L_USDT"
    stg5s: "STG5S_USDT"
```

**配置说明**：
- ✅ **全局配置**：只需配置一次，影响所有策略
- `enabled`: 全局开关（true=启用，false=禁用）
- `interval`: 推送间隔（秒），建议60秒
- `retry_count`: 失败重试次数（默认3次）
- `environments`: 根据 `--env` 参数自动选择主机
- `symbol_mapping`: 策略名到交易所Symbol的映射（可选）

### 步骤2: 准备API密钥

确保 `APIKey.json` 文件包含有效的API密钥：

**单策略格式**（`APIKey_ton3l.json`）:
```json
{
  "access_key": "your_access_key",
  "secret_key": "your_secret_key"
}
```

**多策略格式**（`APIKey.json`，推荐）:
```json
{
  "xt_ton3l": {
    "access_key": "your_access_key",
    "secret_key": "your_secret_key"
  },
  "xt_stg3l": {
    "access_key": "another_access_key",
    "secret_key": "another_secret_key"
  }
}
```

### 步骤3: 运行净值计算器

```bash
# QA环境（自动使用 https://sapi.xt-qa2.com）
python run_net_value.py --strategy ton3l --env qa

# 生产环境（自动使用 https://sapi.xt.com）
python run_net_value.py --strategy ton3l --env prod
```

## 配置优势（全局 vs 单策略）

### ✅ 全局配置（当前实现）

**优点**：
- 统一管理，修改一处即可
- 环境自动切换，无需手动配置多个主机
- Symbol自动映射，减少重复配置
- 易于维护和升级

**示例**：
```yaml
# 全局配置（顶部）
net_value_push:
  enabled: true
  interval: 60
  environments:
    qa: {...}
    prod: {...}

# 各策略无需单独配置
strategies:
  ton3l: {...}
  stg3l: {...}
```

### ❌ 单策略配置（旧方案）

**缺点**：
- 需要在每个策略中重复配置
- 修改推送间隔需要改4-6个地方
- 容易出现配置不一致
- 维护成本高

## 运行示例

### 示例1: TON 3倍做多（QA环境）

```bash
# 1. 修改全局配置
vim config/strategies.yaml
# 设置 net_value_push.enabled = true

# 2. 运行
python run_net_value.py --strategy ton3l --env qa

# 日志输出:
# 2025-01-20 10:30:00 - INFO - 启动净值计算器 - 策略: ton3l
# 2025-01-20 10:30:00 - INFO - ✅ 净值推送已启用 - 主机: https://sapi.xt-qa2.com, 推送间隔: 60秒
# 2025-01-20 10:30:01 - INFO - 正在推送净值到交易所 (尝试 1/3): TON3L_USDT = 1.023456
# 2025-01-20 10:30:01 - INFO - ✅ 净值推送成功: TON3L_USDT = 1.023456
```

### 示例2: STG 5倍做多（生产环境）

```bash
# 1. 确认全局配置已启用
grep "enabled: true" config/strategies.yaml | head -1

# 2. 运行（自动使用生产环境主机）
python run_net_value.py --strategy stg5l --env prod

# 日志输出:
# 2025-01-20 10:30:00 - INFO - 启动净值计算器 - 策略: stg5l
# 2025-01-20 10:30:00 - INFO - ✅ 净值推送已启用 - 主机: https://sapi.xt.com, 推送间隔: 60秒
# 2025-01-20 10:30:01 - INFO - 正在推送净值到交易所 (尝试 1/3): STG5L_USDT = 0.987654
# 2025-01-20 10:30:01 - INFO - ✅ 净值推送成功: STG5L_USDT = 0.987654
```

## Symbol自动生成规则

如果 `symbol_mapping` 中没有配置策略的Symbol，系统会自动生成：

| 策略名 | 自动生成的Symbol | 规则 |
|-------|-----------------|------|
| `ton3l` | `TON3L_USDT` | `{币种大写}{杠杆}{L/S}_USDT` |
| `ton3s` | `TON3S_USDT` | 做空用 `S` |
| `stg3l` | `STG3L_USDT` | 同上 |
| `stg5s` | `STG5S_USDT` | 5倍杠杆做空 |

## 测试方法

### 1. 使用测试脚本（推荐）

```bash
# 测试QA环境推送
uv run python tests/test_update_net_worth.py \
    --symbol TON3L_USDT \
    --net-worth 1.0234 \
    --env qa

# 测试生产环境推送（谨慎操作）
uv run python tests/test_update_net_worth.py \
    --symbol TON3L_USDT \
    --net-worth 1.0234 \
    --env prod
```

### 2. 本地模拟测试

```bash
# 启动净值计算器（推送功能禁用）
python run_net_value.py --strategy ton3l --env qa

# 观察日志输出，确认净值计算正常
# 然后修改全局配置启用推送，重新启动
```

### 3. 验证推送结果

推送成功后，可以通过以下方式验证：

1. **查看日志**: 确认看到 "✅ 净值推送成功" 消息
2. **检查Redis**: 查看 `netvalue_*_detail` 键的 `abnormal_events` 字段
3. **联系交易所**: 确认交易所后台接收到净值更新

## 监控和告警

### 1. 成功推送日志
```
INFO - ✅ 净值推送成功: TON3L_USDT = 1.023456, 响应: {'rc': 0, 'mc': 'SUCCESS'}
```

### 2. 失败推送日志
```
ERROR - ❌ 推送净值失败 (尝试 1/3): 502 Bad Gateway
ERROR - 🚨 净值推送失败（已重试3次）:
ERROR -   交易对: TON3L_USDT
ERROR -   净值: 1.023456
ERROR -   错误: 502 Bad Gateway
ERROR -   主机: https://sapi.xt-qa2.com
```

### 3. 数据库记录

推送事件会记录到数据库（如果启用了 `enable_db_persistence`）：
- 成功事件: `event_type = 'net_value_push_success'`
- 失败事件: `event_type = 'net_value_push_failed'`

## 常见问题

### Q1: 推送失败，返回502错误
**原因**:
- 接口路径可能不正确
- QA环境该接口可能未部署
- 网络连接问题

**解决方案**:
1. 联系XT技术支持确认接口路径是否为 `/v4/etf/net-worth`
2. 检查全局配置中的 `environments` 主机地址是否正确
3. 尝试使用测试脚本单独测试推送功能

### Q2: 推送失败，返回401/403错误
**原因**:
- API密钥无效或过期
- 缺少ETF净值更新权限
- 签名计算错误

**解决方案**:
1. 检查 `APIKey.json` 中的密钥是否正确
2. 联系XT申请ETF净值更新权限
3. 使用测试脚本验证API密钥有效性

### Q3: 如何修改推送间隔？
**解决方案**:
```yaml
# 全局配置中修改一处即可
net_value_push:
  interval: 30    # 改为30秒（更频繁）
  # 或
  interval: 120   # 改为120秒（更保守）
```

### Q4: 如何只为某个策略自定义Symbol？
**解决方案**:
```yaml
net_value_push:
  symbol_mapping:
    ton3l: "TON_3X_LONG_USDT"  # 自定义Symbol
    # 其他策略保持默认（自动生成）
```

## 性能影响

- **推送开销**: 每次推送约需要100-200ms（包括网络延迟）
- **推送频率**: 建议60秒推送一次，平衡实时性和API调用成本
- **重试开销**: 失败重试最多增加约7秒延迟（1s + 2s + 4s）

## 最佳实践

1. ✅ **全局配置**: 使用全局配置管理，避免重复配置
2. ✅ **推送间隔**: 建议设置为60秒，既保证实时性，又避免过多API调用
3. ✅ **测试优先**: 先在QA环境测试，确认无误后再启用生产环境推送
4. ✅ **监控告警**: 定期检查日志中的推送失败事件，及时处理异常
5. ✅ **密钥管理**: 使用环境变量或密钥管理服务存储敏感信息（生产环境）
6. ✅ **备份方案**: 保留手动推送脚本（`test_update_net_worth.py`）作为备份

## 配置文件位置

```
config/strategies.yaml
├── 全局配置（顶部）
│   ├── net_value_push        ← 净值推送配置（全局）
│   └── database              ← 数据库配置（全局）
└── 策略配置
    ├── ton3l                 ← 无需单独配置推送
    ├── stg3l                 ← 无需单独配置推送
    └── ...
```

## 相关文件

- `run_net_value.py`: 净值计算器主程序
- `etf/net_value_improved.py`: 改进版净值计算类（包含推送逻辑）
- `etf/xt.py`: XT交易所客户端（包含 `update_etf_net_worth` 方法）
- `tests/test_update_net_worth.py`: 净值推送测试脚本
- `config/strategies.yaml`: 全局配置文件
- `APIKey.json`: API密钥配置文件

## 更新日志

- **2025-01-20**: 初始实现净值推送功能
  - 添加自动推送逻辑
  - 实现智能重试机制
  - 支持QA/生产环境
  - 添加详细日志和监控
  - **重构为全局配置管理** ⭐
