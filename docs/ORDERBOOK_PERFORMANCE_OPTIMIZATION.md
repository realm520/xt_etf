# 订单簿性能优化指南

## 📊 性能基准测试结果

### 不同档位性能表现

根据 `scripts/test_orderbook_performance.py` 的测试结果：

| 档位数 | 生成时间 | 总金额(USDT) | 性能评级 |
|--------|---------|-------------|---------|
| 1,000  | ~12ms   | ~58K        | 🟢 优秀 |
| 5,000  | ~23ms   | ~51K        | 🟢 优秀 |
| 10,000 | ~45ms   | ~48K        | 🟢 优秀 |
| 20,000 | ~96ms   | ~47K        | 🟡 良好 |
| 50,000 | ~239ms  | ~50K        | 🟡 良好 |
| 100,000| ~485ms  | ~48K        | 🟠 可接受 |

**结论**：
- ✅ 5000档（推荐配置）: <25ms，满足生产要求
- ✅ 10000档: <50ms，满足性能要求
- ✅ 100000档: <500ms，满足超大规模需求

---

## 🚀 性能优化策略

### 1. 档位数选择建议

根据账户规模选择合适的档位数：

```python
def suggest_layer(total_budget: float) -> int:
    """根据预算推荐档位数"""
    if total_budget < 500:
        return 1000    # 小账户（<500 USDT）
    elif total_budget < 2000:
        return 5000    # 中账户（500-2000 USDT）⭐ 推荐
    elif total_budget < 10000:
        return 20000   # 大账户（2000-10000 USDT）
    else:
        return 50000   # 机构账户（>10000 USDT）
```

**配置示例**：
```yaml
ton3s:
  orderbook_algorithm: "natural"
  orderbook_preset: "medium"  # 1000 USDT, 5000档
```

---

### 2. 刷新频率控制

订单簿生成较为耗时，建议控制刷新频率：

#### 方案A: 固定间隔（简单）

```yaml
# 策略配置
sleep_interval: 10  # 主循环10秒

# 订单簿刷新间隔（每3个主循环刷新一次）
orderbook_refresh_interval: 3  # 30秒刷新一次
```

#### 方案B: 价格变化触发（已实现✅）

MarketMaker 已内置价格变化检测机制：

```python
# etf/market_making.py
self.price_change_threshold = 0.0005  # 0.05% 阈值

# 仅当价格变化超过阈值时才重新生成订单簿
if change_rate >= self.price_change_threshold:
    # 重新生成订单簿
```

**优势**：
- 避免价格微小波动时的频繁更新
- 减少不必要的订单操作
- 降低系统负载

---

### 3. 缓存优化

对于固定参数，可以缓存订单簿快照：

```python
class CachedOrderbookAlgorithm:
    def __init__(self, algorithm):
        self.algorithm = algorithm
        self.cache = None
        self.cache_time = 0

    def generate_snapshot_cached(self, ttl=30):
        """带缓存的生成（TTL=30秒）"""
        now = time.time()
        if self.cache and (now - self.cache_time) < ttl:
            return self.cache  # 返回缓存

        self.cache = self.algorithm.generate_snapshot()
        self.cache_time = now
        return self.cache
```

**适用场景**：
- 价格变化频率低（如稳定币对）
- 固定预算和档位配置
- 追求极致性能

---

### 4. 内存优化（大档位场景）

#### 问题：50000+档位可能占用较多内存

#### 解决方案1: 惰性生成（Generator）

```python
def generate_levels_lazy(prices, quantities, side):
    """惰性生成订单档位"""
    for price, quantity in zip(prices, quantities):
        yield OrderLevel(
            price=Decimal(str(price)),
            quantity=Decimal(str(quantity)),
            value=Decimal(str(price * quantity)),
            side=side
        )
```

#### 解决方案2: 分批执行（Batch Processing）

```python
# 分批下单，避免单次批量操作过大
BATCH_SIZE = 1000

for i in range(0, len(orders), BATCH_SIZE):
    batch = orders[i:i+BATCH_SIZE]
    await order_manager.add_orders_batch(batch)
```

**MarketMaker已实现**：
```python
# etf/market_making.py:383
max_batch_size = DEFAULT_BATCH_SIZE  # 10
chunked_add_orders = optimize_batch_operations(
    optimized_add_orders, max_batch_size, "add"
)
```

---

### 5. 自然度级别权衡

不同自然度级别的性能对比（5000档）：

| 级别 | 生成时间 | 自然度 | 推荐场景 |
|------|---------|--------|---------|
| low    | ~19ms | 70%  | 快速测试、高频刷新 |
| medium | ~19ms | 85%  | 平衡性能和真实性 |
| high   | ~22ms | 95%  | 生产环境推荐 ⭐ |
| ultra  | ~22ms | 98%  | 大资金、极致真实 |

**结论**：
- high和ultra性能相近（~22ms），推荐直接使用 **high**
- low和medium几乎无性能差异，建议优先选择 **medium**

---

## 📈 性能监控建议

### 1. 关键指标

在生产环境监控以下指标：

```python
# 订单簿生成时间
orderbook_generation_time_ms

# 订单操作耗时
order_matching_time_ms
batch_order_processing_time_ms

# 系统资源
memory_usage_mb
cpu_usage_percent
```

### 2. 性能告警阈值

```yaml
alerts:
  orderbook_generation_slow:
    threshold: 100ms  # 5000档超过100ms告警
    action: "降低档位数或优化算法"

  high_memory_usage:
    threshold: 500MB  # 内存使用超过500MB
    action: "启用惰性生成或降低档位"

  frequent_refresh:
    threshold: 10次/分钟  # 刷新频率过高
    action: "增大价格变化阈值"
```

---

## 🎯 推荐配置方案

### 方案1: 小账户（<500 USDT）

```yaml
ton3s:
  orderbook_algorithm: "natural"
  orderbook_preset: "small"
  orderbook_refresh_interval: 2  # 20秒刷新
```

**预期性能**：
- 1000档，~12ms生成
- 内存占用 <10MB
- CPU占用 <5%

---

### 方案2: 中账户（500-2000 USDT）⭐ 推荐

```yaml
ton3s:
  orderbook_algorithm: "natural"
  orderbook_preset: "medium"
  orderbook_refresh_interval: 3  # 30秒刷新
```

**预期性能**：
- 5000档，~23ms生成
- 内存占用 <30MB
- CPU占用 <10%

**已验证**：
- ✅ 满足生产环境性能要求
- ✅ 自然度高（95%）
- ✅ 资源占用合理

---

### 方案3: 大账户（2000-10000 USDT）

```yaml
ton3s:
  orderbook_algorithm: "natural"
  orderbook_preset: "large"
  orderbook_refresh_interval: 5  # 50秒刷新
```

**预期性能**：
- 20000档，~96ms生成
- 内存占用 <100MB
- CPU占用 <15%

---

### 方案4: 超大账户（>10000 USDT）

```yaml
ton3s:
  orderbook_algorithm: "natural"
  orderbook_config:
    total_budget: 50000
    layer: 50000
    naturalness: "ultra"
  orderbook_refresh_interval: 10  # 100秒刷新（降低频率）
```

**预期性能**：
- 50000档，~239ms生成
- 内存占用 <300MB
- CPU占用 <25%

**优化建议**：
- 启用缓存（ttl=60s）
- 考虑分布式部署
- 监控系统资源

---

## 🔧 troubleshooting

### 问题1: 订单簿生成慢（>100ms）

**可能原因**：
1. 档位数过大（>10000档）
2. 硬件资源不足（CPU、内存）
3. Python GIL竞争（多线程环境）

**解决方案**：
```python
# 1. 降低档位数
layer: 5000  # 从10000降低到5000

# 2. 降低自然度级别
naturalness: "medium"  # 从high降低到medium

# 3. 启用缓存
ttl: 30  # 30秒缓存
```

---

### 问题2: 内存占用过高（>500MB）

**可能原因**：
1. 档位数过大（>50000档）
2. 订单簿快照未及时释放
3. 缓存积累过多

**解决方案**：
```python
# 1. 启用惰性生成
use_lazy_generation: true

# 2. 清理旧快照
del old_snapshot

# 3. 限制缓存大小
max_cache_size: 5
```

---

### 问题3: 订单刷新频率过高

**现象**：日志中频繁出现"价格变化超过阈值，更新订单簿"

**解决方案**：
```python
# 增大价格变化阈值
self.price_change_threshold = 0.001  # 从0.05%增加到0.1%
```

---

## 📝 性能优化清单

生产环境部署前，请确认以下优化措施：

- [ ] 根据账户规模选择合适的档位数
- [ ] 配置合理的订单簿刷新间隔
- [ ] 启用价格变化阈值检测（已默认启用）
- [ ] 监控订单簿生成时间（< 100ms）
- [ ] 监控内存使用（< 500MB）
- [ ] 监控订单刷新频率（< 10次/分钟）
- [ ] 配置性能告警阈值
- [ ] 准备降级方案（fallback到旧订单簿）

---

## 🎓 最佳实践总结

1. **档位数选择**：根据账户规模，5000档是最佳平衡点
2. **刷新策略**：价格变化触发 > 固定时间间隔
3. **自然度级别**：生产环境推荐 `high`（95%真实度，~22ms）
4. **缓存策略**：稳定市场可启用30s缓存
5. **性能监控**：持续监控生成时间和资源占用
6. **降级方案**：准备回退到旧订单簿系统的配置

---

**最后更新**: 2025-11-23
**测试环境**: MacOS, Python 3.11, uv包管理器
**测试脚本**: `scripts/test_orderbook_performance.py`
