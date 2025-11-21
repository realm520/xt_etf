# 自然K线模拟器文档

## 🎯 概述

自然K线模拟器 (Natural Kline Simulator) 使用**泊松过程**和**几何布朗运动**模拟真实市场行为，确保K线连续性的同时避免被识别为机器人交易。

## ✨ 核心算法

### 1. 泊松过程 (交易时间随机化)
```
交易间隔服从指数分布: P(T>t) = e^(-λt)
λ = 平均交易间隔
```

### 2. 几何布朗运动 (价格路径生成)
```
S(t+Δt) = S(t) * exp((μ - σ²/2)*Δt + σ*√Δt*Z)
μ = 0 (无趋势)
σ = volatility (波动率)
Z ~ N(0,1) (标准正态分布)
```

### 3. 自适应成交量
```
amount = base_amount * (1 + |price_change| * 10) * random(0.8, 1.2)
价格变动大 → 成交量大
价格变动小 → 成交量小
```

## ⚙️ 配置说明

### YAML 配置 (`config/strategies.yaml`)

```yaml
strategies:
  ton3l:
    natural_kline:
      enabled: true                   # ✅ 必须设置为 true
      kline_period: 60                # K线周期（秒）
      avg_trades_per_period: 3        # 每周期平均交易次数
      volatility: 0.002               # 年化波动率（0.2%）
      min_trade_amount: 5             # 最小交易金额（USDT）
      max_price_change_pct: 0.01      # 单笔最大价格变化（1%）
```

## 🔧 修复过程（2025-11-21）

### 问题诊断

**根因**: `config` 字典未包含 `natural_kline` 配置

```
策略配置加载 ✅ → config字典构建 ❌ → 模拟器无法读取配置
```

### 解决方案

**文件**: `run_etf.py:556-559`

```python
# 添加 natural_kline 配置到 config 字典
if "natural_kline" in strategy_config:
    config["natural_kline"] = strategy_config["natural_kline"]
    logging.info(f"✅ 自然K线配置已加载")
```

### 重启流程

```bash
# 推荐方式（自动处理虚拟环境）
bash scripts/restart_ton3l.sh

# 手动方式
uv run python run_etf.py --strategy ton3l --env qa
```

## ✅ 验证方法

### 快速诊断

```bash
bash scripts/diagnose_natural_kline.sh
```

### 查看日志

```bash
# 实时监控
tail -f logs/ton3l/ton3l_rotating.log | grep "自然K线"

# 查看最近记录
grep "自然K线" logs/ton3l/ton3l_rotating.log | tail -10
```

### 预期输出

**启动日志**:
```
INFO | 自然K线模拟器初始化: 周期=60s, 平均交易数=3, 波动率=0.002
INFO | 自然K线模拟器已配置
INFO | 自然K线模拟器启动
INFO | 自然K线模拟器线程已启动
```

**交易日志**:
```
INFO | 自然K线成交: 价格=0.739336, 数量=8.0600, 金额=5.96 USDT
```

## 📊 性能指标

### 资源占用
- **CPU**: <0.1%
- **内存**: <1MB
- **网络**: 每分钟6个API请求

### 成本估算

```
默认配置: 3笔/分 × 5 USDT × 0.1% 手续费
日成本: 21.6 USDT
月成本: 648 USDT
```

## 🐛 常见问题

### 1. 模拟器未启动

**症状**: 日志中无"自然K线"记录

**解决**:
```bash
# 1. 检查配置
grep -A 6 "natural_kline:" config/strategies.yaml

# 2. 重启进程
bash scripts/restart_ton3l.sh

# 3. 验证日志
tail -f logs/ton3l/ton3l_rotating.log | grep "自然K线"
```

### 2. 交易频率异常

**调整参数**:
```yaml
avg_trades_per_period: 5  # 提高频率
# 或
avg_trades_per_period: 2  # 降低频率
```

### 3. 价格波动过大

**调整参数**:
```yaml
volatility: 0.001            # 降低波动率
max_price_change_pct: 0.005  # 降低单笔变化
```

## 📚 相关文件

- **核心代码**: `etf/natural_kline_simulator.py` (450行)
- **集成代码**: `run_etf.py` (行838-860)
- **配置文件**: `config/strategies.yaml`
- **诊断脚本**: `scripts/diagnose_natural_kline.sh`
- **重启脚本**: `scripts/restart_ton3l.sh`

## 🎓 参考资料

- **几何布朗运动**: [Wikipedia - GBM](https://en.wikipedia.org/wiki/Geometric_Brownian_motion)
- **泊松过程**: [Wikipedia - Poisson Process](https://en.wikipedia.org/wiki/Poisson_point_process)

---

**最后更新**: 2025-11-21  
**版本**: 1.0.0  
**状态**: ✅ 生产就绪
