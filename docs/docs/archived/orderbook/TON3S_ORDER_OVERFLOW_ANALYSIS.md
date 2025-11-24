# TON3S 订单数超过700档问题分析报告

## 问题描述

ton3s策略配置了500档订单（买250+卖250），但实际运行时订单数超过700档。

## 根本原因

### 1. 订单匹配算法缺陷

**位置**: `etf/utils/optimization.py:optimize_order_matching()`

**问题**：
- 算法只匹配**价格范围内**的订单（`min_price ~ max_price`）
- 价格范围外的旧订单不会被识别和取消
- 每次价格变化时，只有部分订单被更新，其余订单累积

### 2. 实际运行数据

从日志 `logs/ton3s/ton3s.log` 分析：

```
2025-11-24 07:32:52 | 订单操作计划 - 新增: 57, 取消: 4
2025-11-24 07:33:34 | 订单操作计划 - 新增: 59, 取消: 4
2025-11-24 07:35:29 | 订单操作计划 - 新增: 58, 取消: 6
2025-11-24 07:37:13 | 订单操作计划 - 新增: 59, 取消: 5
```

**关键发现**：
- ✅ 每次新增约57-60个订单
- ❌ 每次只取消0-7个订单
- ⚠️ 净增加约50-60个订单/次
- 🔥 价格频繁变化（每20-60秒触发一次更新）

### 3. 价格变化频率

```
价格变化 0.2038% 超过阈值 0.0500%  → 触发更新
价格变化 0.2030% 超过阈值 0.0500%  → 触发更新
价格变化 0.4092% 超过阈值 0.0500%  → 触发更新
```

**阈值设置**: `self.price_change_threshold = 0.0005` (0.05%)

**实际变化**: 通常0.2%-0.4%，远超阈值 → 频繁触发

### 4. 累积效应计算

假设：
- 初始：500档订单
- 每次更新：新增58档，取消5档 → 净增53档
- 更新10次后：500 + 53×10 = **1030档** ❌

实际情况：
- 部分订单被真实交易撤销
- 最终稳定在700+档

## 算法逻辑分析

### `optimize_order_matching` 核心逻辑

```python
for goal in goal_orders:
    goal_min_price = goal["min_price"]
    goal_max_price = goal["max_price"]

    # ❌ 问题：只查找价格范围内的订单
    valid_market_orders = find_orders_in_price_range(
        price_index, goal_min_price, goal_max_price
    )

    # 超出范围的订单不会被处理 → 累积
```

### 示例说明

**场景**：净值从1.00变化到1.02 (2%变化)

**目标订单簿**（500档）：
- 买盘：0.970 ~ 1.010 (250档)
- 卖盘：1.030 ~ 1.070 (250档)

**旧订单簿**（500档，基于净值1.00）：
- 买盘：0.950 ~ 0.990 (250档)
- 卖盘：1.010 ~ 1.050 (250档)

**匹配结果**：
- 重叠区：0.970~0.990 (买) + 1.010~1.050 (卖) ≈ 60档
- 取消：重叠区内多余的订单 ≈ 5档
- 新增：新范围内缺少的订单 ≈ 58档
- **遗漏**：旧订单中 0.950~0.970 区间的订单 ≈ 50档 ❌

## 为什么没有订单数量检查？

### 当前代码检查点

1. **OrderbookConfig 验证** (`etf/orderbook/base.py:36-37`)
   ```python
   if self.layer < 10 or self.layer > 1_000_000:
       raise ValueError(f"layer must be in [10, 1000000], got {self.layer}")
   ```
   ✅ 检查目标档位数（配置层面）

2. **自然算法验证** (`etf/orderbook/natural.py:47-50`)
   ```python
   if not (min_layer <= layer <= max_layer):
       raise ValueError(
           f"Natural algorithm supports {min_layer}-{max_layer} layers, "
           f"got {layer}"
       )
   ```
   ✅ 检查算法支持的档位数（10-1,000,000）

3. **❌ 缺失**：运行时实际挂单数量检查
   - 没有检查 `len(current_orders)` 是否超过配置的 `layer`
   - 没有告警机制
   - 没有强制清理逻辑

## 解决方案

### 方案1: 修复订单匹配算法（推荐）

**位置**: `etf/utils/optimization.py`

**改进**：
```python
def optimize_order_matching(
    current_orders: List[Dict[str, Any]],
    goal_orders: List[Dict[str, Any]],
    max_layer: int = 500  # 新增参数
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    优化的订单匹配算法 + 订单数量控制
    """
    # ... 原有匹配逻辑 ...

    # 新增：检查是否超过最大档位数
    if len(current_orders) > max_layer * 1.5:  # 150% 阈值
        # 强制清理：取消所有超出范围的订单
        for order in current_orders:
            price = float(order['price'])
            if price < global_min_price or price > global_max_price:
                cancel_orders.append(order)

    return add_orders, cancel_orders
```

**优点**：
- ✅ 彻底解决累积问题
- ✅ 自动清理超范围订单
- ✅ 保持算法效率

### 方案2: 定期全量清理（临时方案）

**位置**: `etf/market_making.py:place_orders()`

**改进**：
```python
# 在 place_orders 开始时添加
if len(current_orders) > orderbook_cfg.layer * 1.2:  # 120% 阈值
    logging.warning(
        f"订单数量异常: {len(current_orders)} > {orderbook_cfg.layer}, "
        f"执行全量清理"
    )
    # 取消所有订单，重新下单
    self.order_manager.client.cancel_all_orders(symbol=symbol)
    time.sleep(1)
    current_orders = []
```

**优点**：
- ✅ 实现简单
- ✅ 立即可用

**缺点**：
- ❌ 短暂影响流动性
- ❌ 治标不治本

### 方案3: 增加订单数量监控（建议配合方案1）

**新增**: `etf/monitoring/order_monitor.py`

```python
class OrderCountMonitor:
    """订单数量监控器"""

    def __init__(self, max_layer: int, alert_threshold: float = 1.2):
        self.max_layer = max_layer
        self.alert_threshold = alert_threshold

    def check(self, current_orders: List[Dict]) -> bool:
        """检查订单数量是否超标"""
        count = len(current_orders)
        threshold = self.max_layer * self.alert_threshold

        if count > threshold:
            logging.error(
                f"🚨 订单数量超标: {count} > {threshold:.0f} "
                f"(配置: {self.max_layer})"
            )
            return False

        return True
```

**集成点**: 在 `MarketMaker.place_orders()` 中调用

## 实施步骤

### 立即执行（紧急修复）

1. **手动清理ton3s订单**
   ```bash
   # 登录交易所后台，取消所有ton3s订单
   ```

2. **临时增加价格变化阈值**（减少更新频率）
   ```python
   # etf/market_making.py:64
   self.price_change_threshold: float = 0.002  # 从0.05%改为0.2%
   ```

### 短期修复（1-2天）

3. **实施方案2**：添加全量清理逻辑
4. **实施方案3**：添加订单数量监控

### 长期优化（1周）

5. **实施方案1**：修复订单匹配算法
6. **添加单元测试**：覆盖订单累积场景
7. **性能测试**：验证修复后的稳定性

## 预期效果

### 修复前
- 订单数：500 → 700+ （持续增长）
- 更新频率：20-60秒/次
- 每次净增：约50档

### 修复后
- 订单数：稳定在500档 (±5%)
- 更新频率：可选优化（提高阈值）
- 每次操作：新增≈取消（净增≈0）

## 技术债务记录

- [ ] 订单匹配算法完善（高优先级）
- [ ] 订单数量监控系统（中优先级）
- [ ] 价格变化阈值动态调整（低优先级）
- [ ] 单元测试覆盖订单累积场景（中优先级）

---

**生成时间**: 2025-11-24
**分析工具**: Claude Code
**问题严重性**: 🔴 高（影响系统稳定性和成本）
**修复紧急性**: 🔥 紧急（建议24小时内实施临时方案）
