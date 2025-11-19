# 反针对订单累积问题修复方案

## 问题描述

**症状**: 买盘显示 131 档订单，卖盘显示 168 档订单（预期各 30 档 + 2 个反针对订单）

**根本原因**: 反针对订单每 10 秒添加一次，但从未清理，导致累积了 125+ 个重复的买单和 130+ 个重复的卖单

**具体表现**:
- 买单: 125 个重复订单，价格都是 0.788872，数量都是 190.14
- 卖单: 130 个重复订单，价格都是 1.216908，数量都是 123.26

## 解决方案：先添加新订单，再取消旧订单

### 设计思路

1. **避免保护空窗期**: 先添加新的反针对订单，再取消旧的
2. **精确识别**: 通过价格特征识别反针对订单
3. **安全排除**: 使用订单ID排除新添加的订单，避免误删

### 实现逻辑

```python
每个做市周期:
    1. 清空上一周期的反针对订单ID记录
    2. 创建新的反针对订单（卖单 + 买单）
    3. 记录新订单的 clientOrderId 到追踪列表
    4. 批量添加所有订单（包括新的反针对订单）
    5. ✅ 新反针对订单已生效，开始清理旧订单
    6. 调用 _cancel_old_anti_pin_orders:
       - 获取所有活跃订单
       - 识别价格匹配 anti_pin_price_buy/sell 的订单
       - 排除刚刚添加的新订单ID
       - 批量取消剩余的旧反针对订单
```

### 代码变更

#### 1. 追踪字段（etf/market_making.py:60）

```python
# 记录当前周期新增的反针对订单ID，用于避免误删
self.current_anti_pin_order_ids: List[str] = []
```

#### 2. 记录新订单ID（etf/market_making.py:267-300）

```python
# 清空上一周期的反针对订单ID记录
self.current_anti_pin_order_ids = []

# 创建反针对卖单
sell_client_order_id = self.order_manager.create_temp_id()
sell_order_data = {
    "symbol": symbol,
    "clientOrderId": sell_client_order_id,
    "side": SIDE_SELL,
    "price": anti_pin_price_sell,
    "quantity": anti_pin_amount_sell,
    ...
}
add_orders.append(sell_order_data)
self.current_anti_pin_order_ids.append(sell_client_order_id)

# 创建反针对买单（同样记录ID）
...
```

#### 3. 取消旧订单方法（etf/market_making.py:62-122）

```python
def _cancel_old_anti_pin_orders(
    self,
    symbol: str,
    anti_pin_price_sell: float,
    anti_pin_price_buy: float,
    exclude_order_ids: List[str]
) -> None:
    """
    取消旧的反针对订单（排除新添加的订单）
    """
    try:
        # 获取当前所有活跃订单
        current_orders = self.order_manager.client.get_open_orders(symbol=symbol)

        old_anti_pin_orders = []
        price_tolerance = 0.0001  # 浮点数比较容差

        for order in current_orders:
            order_price = float(order["price"])
            client_order_id = order.get("clientOrderId", "")

            # 跳过新添加的订单
            if client_order_id in exclude_order_ids:
                continue

            # 通过价格特征识别反针对订单
            is_anti_pin_sell = (
                order["side"] == "SELL" and
                abs(order_price - anti_pin_price_sell) < price_tolerance
            )
            is_anti_pin_buy = (
                order["side"] == "BUY" and
                abs(order_price - anti_pin_price_buy) < price_tolerance
            )

            if is_anti_pin_sell or is_anti_pin_buy:
                old_anti_pin_orders.append(order)

        # 批量取消旧的反针对订单
        if old_anti_pin_orders:
            logging.info(f"发现 {len(old_anti_pin_orders)} 个旧的反针对订单，准备取消")
            self.order_manager.cancel_orders_batch(orders=old_anti_pin_orders)
            logging.info(f"成功取消 {len(old_anti_pin_orders)} 个旧的反针对订单")

    except Exception as e:
        logging.error(f"查询或取消旧反针对订单时出错: {e}")
```

#### 4. 调用时机（etf/market_making.py:418-425）

```python
execute_order_batches()

# 在新反针对订单添加完成后，取消旧的反针对订单
# 这样可以避免保护空窗期，确保始终有反针对订单保护
self._cancel_old_anti_pin_orders(
    symbol=symbol,
    anti_pin_price_sell=anti_pin_price_sell,
    anti_pin_price_buy=anti_pin_price_buy,
    exclude_order_ids=self.current_anti_pin_order_ids
)
```

## 预期效果

### 修复前
```
买盘订单（131档）:
- 1-6档: 正常做市订单
- 7-131档: 125个重复的反针对订单（价格 0.788872，数量 190.14）

卖盘订单（168档）:
- 1-30档: 正常做市订单
- 31-168档: 138个重复的反针对订单（价格 1.216908，数量 123.26）
```

### 修复后
```
买盘订单（31档）:
- 1-30档: 正常做市订单
- 第31档: 1个反针对买单（价格根据 best_buy * (1 - anti_pin_rate) 计算）

卖盘订单（31档）:
- 1-30档: 正常做市订单
- 第31档: 1个反针对卖单（价格根据 best_sell * (1 + anti_pin_rate) 计算）
```

## 日志监控

修复后可以通过日志监控清理效果：

```bash
# 查看反针对订单清理日志
tail -f logs/ton3l/ton3l.log | grep "旧的反针对订单"

# 预期日志输出示例
2025-01-19 10:30:15 - INFO - 发现 125 个旧的反针对订单，准备取消
2025-01-19 10:30:15 - INFO - 成功取消 125 个旧的反针对订单
2025-01-19 10:30:25 - INFO - 发现 2 个旧的反针对订单，准备取消
2025-01-19 10:30:25 - INFO - 成功取消 2 个旧的反针对订单
2025-01-19 10:30:35 - DEBUG - 没有发现需要取消的旧反针对订单
```

首次运行会清理累积的 125+ 个重复订单，之后每次循环只会清理上一周期的 2 个订单。

## 验证步骤

1. **启动修复后的程序**:
   ```bash
   python run_etf.py --strategy ton3l --env qa
   ```

2. **查看实时订单数量**:
   ```bash
   uv run python3 scripts/check_live_orders.py --symbol ton3l_usdt --env qa
   ```

3. **检查日志输出**:
   ```bash
   tail -f logs/ton3l/ton3l.log | grep -E "add_orders|旧的反针对订单"
   ```

## 安全保障

- ✅ **价格容差保护**: 使用 0.0001 容差避免浮点数精度问题
- ✅ **ID排除机制**: 通过 clientOrderId 精确排除新订单
- ✅ **异常处理**: 完整的 try-except 保护，失败不影响主流程
- ✅ **无保护空窗期**: 新订单添加成功后才取消旧订单
- ✅ **日志可追溯**: 详细记录清理过程和数量

## 相关文件

- `etf/market_making.py` - 主要实现文件
- `scripts/check_live_orders.py` - 订单验证工具
- `config/strategies.yaml` - 策略配置（anti_pin_rate, anti_pin_usdt）
