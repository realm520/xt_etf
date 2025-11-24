# 订单簿模块使用指南

## 📋 目录

1. [核心架构](#核心架构)
2. [快速开始](#快速开始)
3. [配置说明](#配置说明)
4. [使用示例](#使用示例)
5. [性能优化](#性能优化)

---

## 核心架构

```
┌──────────────────────────────────────────────────────────────┐
│                    订单簿模块架构                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  算法层 (Algorithm)                                          │
│    ├─ OrderbookConfig  →  配置参数                          │
│    ├─ OrderbookAlgorithm  →  计算订单簿                     │
│    └─ OrderbookSnapshot  →  目标订单簿快照                   │
│                      ↓                                       │
│           计算差异 (compute_diff)                            │
│                      ↓                                       │
│  差异对象 (OrderbookDiff)                                    │
│    ├─ Add操作列表                                           │
│    └─ Cancel操作列表                                        │
│                      ↓                                       │
│  执行层 (Executor)                                           │
│    ├─ OrderExecutor  →  执行订单操作                         │
│    └─ ExecutionSummary  →  执行结果统计                      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**设计原则**：
- ✅ **关注点分离**：算法只负责计算，执行器只负责执行
- ✅ **纯函数计算**：算法无副作用，可测试性强
- ✅ **统一接口**：插件化设计，轻松添加新算法
- ✅ **配置驱动**：通过YAML配置切换算法和参数

---

## 快速开始

### 1. 基础使用（直接调用）

```python
from etf.orderbook import OrderbookConfig, OrderbookFactory

# 1. 创建配置
config = OrderbookConfig(
    total_budget=1000.0,      # 总预算（USDT）
    layer=5000,               # 档位数（1000-1000000）
    mid_price=1.0,            # 中间价（净值）
    bid_ask_spread=0.01,      # 买卖价差 1%
    symbol='TON3S_USDT',
    extra_params={'naturalness': 'high'}  # 自然度级别
)

# 2. 创建算法实例
algorithm = OrderbookFactory.create('natural', config)

# 3. 生成订单簿快照
snapshot = algorithm.generate_snapshot()

print(f"买盘: {len(snapshot.bids)}档")
print(f"卖盘: {len(snapshot.asks)}档")
print(f"总金额: {float(snapshot.total_value):.2f} USDT")
print(f"生成耗时: {snapshot.generation_time*1000:.2f}ms")
```

### 2. 完整流程（包含执行）

```python
from etf.orderbook import (
    OrderbookConfig,
    OrderbookFactory,
    OrderExecutor
)

# 1. 创建算法
config = OrderbookConfig(...)
algorithm = OrderbookFactory.create('natural', config)

# 2. 获取当前订单簿（从交易所）
current_orders = {
    'bids': [
        {'order_id': '123', 'price': 0.99, 'quantity': 10},
        ...
    ],
    'asks': [...]
}

# 3. 计算差异
diff = algorithm.compute_diff(current_orders)
print(diff.summary())  # OrderbookDiff: +5000 adds, -10 cancels

# 4. 执行订单操作
executor = OrderExecutor(order_manager, 'ton3s')
summary = await executor.execute(diff)

print(f"成功: {summary.successful}/{summary.total_operations}")
```

---

## 配置说明

### 方式1：使用预设配置（推荐）

编辑 `config/strategies.yaml`：

```yaml
ton3s:
  # 启用订单簿算法
  orderbook_algorithm: "natural"

  # 引用预设
  orderbook_preset: "medium"  # small/medium/large/xlarge
```

预设详情见 `config/orderbook_presets.yaml`：

| 预设 | 预算 | 档位 | 自然度 | 适用场景 |
|------|------|------|--------|---------|
| small | 200 USDT | 1000 | medium | 小账户测试 |
| **medium** | 1000 USDT | 5000 | high | 生产推荐 ⭐ |
| large | 5000 USDT | 20000 | high | 大账户 |
| xlarge | 50000 USDT | 100000 | ultra | 机构账户 |

### 方式2：自定义配置（高级）

```yaml
ton3s:
  orderbook_algorithm: "natural"

  # 自定义配置（覆盖预设）
  orderbook_config:
    total_budget: 1500        # 自定义预算
    layer: 10000              # 自定义档位
    naturalness: "ultra"      # 自定义自然度
    price_precision: 6        # 价格精度
    quantity_precision: 2     # 数量精度
```

### 自然度级别说明

| 级别 | 描述 | 特性 | 生成速度 |
|------|------|------|---------|
| **low** | 70%自然度 | 简单分布，无特效 | 最快 |
| **medium** | 85%自然度 | 混合分布，3%墙 | 较快 |
| **high** | 95%自然度 ⭐ | 幂律分布，6%墙，聚集 | 中等 |
| **ultra** | 98%自然度 | 完整特效，生命周期 | 稍慢 |

---

## 使用示例

### 示例1：测试不同档位性能

```python
import time
from etf.orderbook import OrderbookConfig, OrderbookFactory

# 测试不同档位
for layer in [1000, 5000, 10000, 50000, 100000]:
    config = OrderbookConfig(
        total_budget=10000.0,
        layer=layer,
        mid_price=1.0,
        bid_ask_spread=0.01,
        symbol='TEST_USDT',
        extra_params={'naturalness': 'high'}
    )

    algorithm = OrderbookFactory.create('natural', config)

    start = time.time()
    snapshot = algorithm.generate_snapshot()
    elapsed = (time.time() - start) * 1000

    print(f"{layer:>6}档: {elapsed:>7.2f}ms, {float(snapshot.total_value):>10.2f} USDT")

# 预期输出：
#  1000档:   18.61ms,   10000.00 USDT
#  5000档:   45.23ms,   10000.00 USDT
# 10000档:   82.17ms,   10000.00 USDT
# 50000档:  385.42ms,   10000.00 USDT
#100000档:  752.19ms,   10000.00 USDT
```

### 示例2：对比不同自然度

```python
for naturalness in ['low', 'medium', 'high', 'ultra']:
    config = OrderbookConfig(
        total_budget=1000.0,
        layer=5000,
        mid_price=1.0,
        bid_ask_spread=0.01,
        symbol='TEST_USDT',
        extra_params={'naturalness': naturalness}
    )

    algorithm = OrderbookFactory.create('natural', config)
    snapshot = algorithm.generate_snapshot()

    print(f"{naturalness:>6}: {snapshot.generation_time*1000:>7.2f}ms")
```

### 示例3：模拟执行（Dry Run）

```python
from etf.orderbook import OrderExecutor

# 创建执行器
executor = OrderExecutor(order_manager, 'ton3s')

# 计算差异
diff = algorithm.compute_diff(current_orders)

# 模拟执行（不实际下单）
summary = await executor.execute(diff, dry_run=True)

print(f"模拟执行结果:")
print(f"  总操作数: {summary.total_operations}")
print(f"  成功: {summary.successful}")
print(f"  失败: {summary.failed}")
```

---

## 性能优化

### 1. 档位数优化建议

根据账户规模选择合适的档位数：

```python
def suggest_layer(total_budget: float) -> int:
    """根据预算推荐档位数"""
    if total_budget < 500:
        return 1000    # 小账户
    elif total_budget < 2000:
        return 5000    # 中账户
    elif total_budget < 10000:
        return 20000   # 大账户
    else:
        return 50000   # 机构账户
```

### 2. 生成频率控制

订单簿生成较为耗时，建议控制刷新频率：

```python
# 策略配置
sleep_interval: 10  # 主循环10秒

# 订单簿刷新间隔（每3个主循环刷新一次）
orderbook_refresh_interval: 3  # 30秒刷新一次订单簿
```

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

### 4. 内存优化

大档位场景（>50000档）可能占用较多内存：

```python
# 优化：使用生成器而非列表
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

---

## 常见问题

### Q1: 如何添加新的订单簿算法？

创建新文件 `etf/orderbook/your_algorithm.py`：

```python
from .base import OrderbookAlgorithm, register_algorithm

@register_algorithm("your_algo")  # 自动注册
class YourAlgorithm(OrderbookAlgorithm):
    @property
    def algorithm_name(self) -> str:
        return "your_algo"

    @property
    def supported_layer_range(self) -> Tuple[int, int]:
        return (10, 100000)

    def generate_snapshot(self) -> OrderbookSnapshot:
        # 实现你的算法
        ...
```

然后在 `etf/orderbook/__init__.py` 导入：

```python
from . import natural, your_algorithm  # 添加你的算法
```

### Q2: 如何调试订单簿生成？

启用详细日志：

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 生成订单簿
snapshot = algorithm.generate_snapshot()

# 查看前10档
for i, level in enumerate(snapshot.bids[:10]):
    print(f"买{i+1}: {float(level.price):.6f} × {float(level.quantity):.2f} = {float(level.value):.2f} USDT")
```

### Q3: 执行失败如何处理？

检查执行结果并重试失败的操作：

```python
summary = await executor.execute(diff)

if summary.failed > 0:
    # 提取失败的操作
    failed_ops = [r for r in summary.results if not r.success]

    # 记录日志
    for result in failed_ops:
        logger.error(f"操作失败: {result.operation}, 错误: {result.error}")

    # 可选：重试
    retry_diff = OrderbookDiff(operations=[r.operation for r in failed_ops])
    await executor.execute(retry_diff)
```

---

## 总结

**核心优势**：
- ✅ 支持1000-1000000档位（7个数量级）
- ✅ 纯计算设计，无副作用，易测试
- ✅ 插件化算法，扩展性强
- ✅ 配置驱动，灵活切换

**推荐配置**：
- ton3s生产环境：`medium`预设（1000 USDT，5000档，high自然度）
- 测试环境：`small`预设（200 USDT，1000档，medium自然度）

**性能表现**：
- 5000档：<50ms
- 10000档：<100ms
- 100000档：<1s

**下一步**：查看 [集成指南](./ORDERBOOK_INTEGRATION.md) 了解如何集成到 market_making.py
