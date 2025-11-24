# 净值推送配置总结

## ✅ 完成的改进

已将净值推送配置从**单策略配置**重构为**全局配置**，实现统一管理。

## 📍 配置位置

**文件**: `config/strategies.yaml`

**位置**: 文件顶部的全局配置区域（`database` 配置之前）

```yaml
# 全局配置
# ========================================

# 净值推送配置（推送到交易所）
net_value_push:
  enabled: false            # 全局开关：是否启用推送到交易所（默认关闭）
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

## 🎯 配置说明

### 1. **全局开关** (`enabled`)
- **默认**: `false` (关闭)
- **作用**: 一键控制所有策略的推送功能
- **修改**: 改为 `true` 即可启用推送

### 2. **推送间隔** (`interval`)
- **默认**: `60` 秒
- **作用**: 控制推送频率（每60秒推送一次）
- **建议**: 保持60秒，平衡实时性和API成本

### 3. **重试机制** (`retry_count` & `retry_backoff`)
- **重试次数**: 3次
- **退避策略**: 1秒 → 2秒 → 4秒（指数退避）
- **作用**: 自动处理网络抖动和临时故障

### 4. **环境配置** (`environments`)
- **QA环境**: `https://sapi.xt-qa2.com`
- **生产环境**: `https://sapi.xt.com`
- **自动切换**: 根据 `--env qa/prod` 参数自动选择

### 5. **Symbol映射** (`symbol_mapping`)
- **可选配置**: 可以不配置，系统自动生成
- **自动规则**: `{币种大写}{杠杆}{L/S}_USDT`
  - 例如: `ton3l` → `TON3L_USDT`
  - 例如: `stg5s` → `STG5S_USDT`

## 🚀 快速启用推送

### 方法1: 启用所有策略的推送（推荐）

```bash
# 1. 修改配置文件
vim config/strategies.yaml

# 找到这一行:
#   enabled: false
# 改为:
#   enabled: true

# 2. 运行任意策略
python run_net_value.py --strategy ton3l --env qa
```

### 方法2: 使用 sed 快速修改

```bash
# 启用推送
sed -i '' 's/enabled: false/enabled: true/' config/strategies.yaml

# 禁用推送
sed -i '' 's/enabled: true/enabled: false/' config/strategies.yaml
```

## 📊 多久推送一次？

**答案**: 每 60 秒推送一次（默认配置）

**时间线示例**:
```
10:00:00 ─ 首次推送（立即）
10:01:00 ─ 第2次推送（60秒后）
10:02:00 ─ 第3次推送（60秒后）
10:03:00 ─ 第4次推送（60秒后）
...
```

**修改推送频率**:
```yaml
net_value_push:
  interval: 30    # 改为30秒（更频繁）
  # 或
  interval: 120   # 改为120秒（更保守）
```

## 📝 查看推送日志

### 日志内容示例

**启动日志**:
```log
INFO - 启动净值计算器 - 策略: ton3l
INFO - ✅ 净值推送已启用 - 主机: https://sapi.xt-qa2.com, 推送间隔: 60秒
```

**推送成功日志** (每60秒一次):
```log
INFO - 正在推送净值到交易所 (尝试 1/3): TON3L_USDT = 1.023456
INFO - ✅ 净值推送成功: TON3L_USDT = 1.023456, 响应: {'rc': 0, 'mc': 'SUCCESS'}
```

**推送失败日志** (带重试):
```log
ERROR - ❌ 推送净值失败 (尝试 1/3): 502 Bad Gateway
ERROR - 🚨 净值推送失败（已重试3次）:
ERROR -   交易对: TON3L_USDT
ERROR -   净值: 1.023456
ERROR -   错误: 502 Bad Gateway
```

### 查看日志方法

```bash
# 方法1: 实时查看（推荐）
python run_net_value.py --strategy ton3l --env qa

# 方法2: 查看日志文件
tail -f logs/ton3l/net_value.log | grep "推送"

# 方法3: 统计推送成功次数
grep -c "✅ 净值推送成功" logs/ton3l/net_value.log
```

## 🔍 推送状态检查

### 检查1: 确认配置已启用

```bash
# 查看全局配置
grep -A 20 "net_value_push:" config/strategies.yaml | head -21

# 应该看到: enabled: true
```

### 检查2: 查看最近推送记录

```bash
# 查看Redis中的净值数据
redis-cli GET "netvalue_ton3l_detail"

# 查看历史记录（最近10次）
redis-cli LRANGE "netvalue_ton3l_history" 0 10
```

### 检查3: 验证推送日志

```bash
# 查看最近的推送成功记录
grep "✅ 净值推送成功" logs/ton3l/net_value.log | tail -5

# 查看是否有推送失败
grep "🚨 净值推送失败" logs/ton3l/net_value.log
```

## ⚙️ 全局配置的优势

### ✅ 优点

| 特性 | 全局配置 | 单策略配置 |
|-----|---------|-----------|
| 修改便捷性 | ✅ 修改1处 | ❌ 修改4-6处 |
| 配置一致性 | ✅ 保证一致 | ❌ 容易不一致 |
| 环境切换 | ✅ 自动切换 | ❌ 手动配置 |
| 维护成本 | ✅ 低 | ❌ 高 |
| Symbol管理 | ✅ 统一映射 | ❌ 重复配置 |

### 📍 配置对比

**全局配置**（当前实现）:
```yaml
# 顶部全局配置（修改一处）
net_value_push:
  enabled: true
  interval: 60
  environments: {...}
  symbol_mapping: {...}

# 各策略无需配置
strategies:
  ton3l: {...}  # ← 无推送配置
  stg3l: {...}  # ← 无推送配置
```

**单策略配置**（旧方案，已废弃）:
```yaml
strategies:
  ton3l:
    net_value_push:  # ← 重复配置1
      enabled: true
      interval: 60

  stg3l:
    net_value_push:  # ← 重复配置2
      enabled: true
      interval: 60
  # ... 需要在每个策略重复配置
```

## 🎯 常见操作

### 操作1: 启用推送（全局）

```yaml
net_value_push:
  enabled: true  # ← 改这里
```

### 操作2: 修改推送间隔（全局）

```yaml
net_value_push:
  interval: 30  # ← 改为30秒，影响所有策略
```

### 操作3: 自定义某个策略的Symbol

```yaml
net_value_push:
  symbol_mapping:
    ton3l: "TON_3X_LONG_USDT"  # ← 自定义
    # 其他策略自动生成
```

### 操作4: 添加新环境

```yaml
net_value_push:
  environments:
    qa: {...}
    prod: {...}
    staging:  # ← 新增staging环境
      host: "https://sapi.xt-staging.com"
```

## 📖 相关文档

- **完整指南**: `docs/NET_VALUE_PUSH_GUIDE.md`
- **配置示例**: `docs/NET_VALUE_PUSH_CONFIG_EXAMPLE.yaml`
- **测试脚本**: `tests/test_update_net_worth.py`

## 💡 最佳实践

1. ✅ **全局配置**: 使用全局配置，避免重复
2. ✅ **60秒间隔**: 保持默认60秒推送间隔
3. ✅ **测试优先**: 先在QA环境测试
4. ✅ **监控日志**: 定期检查推送成功率
5. ✅ **自动生成**: 使用自动Symbol生成，减少配置

## 🚀 下一步

1. 修改 `config/strategies.yaml` 中的 `enabled: false` 为 `enabled: true`
2. 运行 `python run_net_value.py --strategy ton3l --env qa`
3. 观察日志，确认推送成功
4. 验证推送是否每60秒执行一次
