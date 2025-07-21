# Redis Last Amount 存储方案（全新市场）

## 概述

为全新市场设计的 `last_amount` Redis 存储方案，提供高性能、可靠性和可扩展性，无需考虑历史数据迁移。

## 背景

### 为什么需要持久化 last_amount？

`last_amount` 的核心作用是计算用户的持仓变化量（delta_amount）：

```python
delta_amount = 当前持仓 - last_amount
# if delta_amount < 0: 用户买入
# if delta_amount > 0: 用户卖出
```

这个变化量用于：
1. 判断用户的交易行为
2. 决定对冲策略
3. 计算对冲数量

### 为什么选择 Redis？

- 内存存储，性能极高
- 原子操作，保证数据一致性
- 易于扩展元数据（如时间戳、价格等）
- 提供统一的监控和管理工具
- 支持持久化，系统重启不丢数据

## 新方案架构

### Redis 存储结构

```
# 简单值（向后兼容）
last_amount:stg3l_usdt -> "499928.28"

# 详细信息（新增）
last_amount:detail:stg3l_usdt -> {
    "amount": 499928.28,
    "timestamp": "2024-01-15T10:30:00",
    "delta_amount": -100.5,
    "delta_position": -1234.56,
    "mid_price": 12.345,
    "source": "normal"
}
```

### 简化的存储流程（全新市场）

1. **首次运行**：使用当前账户余额初始化，delta_amount = 0
2. **正常运行**：从 Redis 读取上次值，计算 delta_amount
3. **Redis 故障**：使用当前余额作为初始值（影响最小）

### 关键特性

- **原子操作**：Redis 保证数据一致性
- **过期时间**：30天自动清理旧数据
- **简化设计**：无需考虑历史数据和文件兼容
- **故障处理**：Redis 不可用时使用当前余额初始化
- **实时监控**：提供监控脚本查看数据状态

## 使用指南

### 1. 直接启动（全新市场无需迁移）

系统会自动初始化，首次运行时：
- 读取当前账户余额作为初始值
- delta_amount 设置为 0
- 存储到 Redis 标记为 "initial"

### 2. 监控数据

实时查看 Redis 中的 last_amount 数据：

```bash
# 实时监控（5秒刷新）
python scripts/monitor_last_amount.py

# 自定义刷新间隔
python scripts/monitor_last_amount.py -i 10

# 查看详细信息
python scripts/monitor_last_amount.py -d
```

### 3. 测试功能

运行单元测试验证功能：

```bash
# 运行测试
python -m pytest tests/test_redis_last_amount.py -v

# 或直接运行
python tests/test_redis_last_amount.py
```

## 代码集成

### 主要修改

1. **hedging_aggregation.py**
   - 添加 `RedisLastAmountStorage` 实例
   - 简化的读取逻辑：Redis → 当前余额初始化
   - 移除文件相关代码

2. **新增文件**
   - `etf/storage/redis_last_amount.py`：Redis 存储管理类
   - `scripts/monitor_last_amount.py`：监控脚本
   - `tests/test_redis_last_amount.py`：单元测试

### API 示例

```python
from etf.storage.redis_last_amount import RedisLastAmountStorage

# 初始化
storage = RedisLastAmountStorage()

# 存储数据
storage.set_last_amount(
    "stg3l_usdt",
    12345.67,
    delta_amount=-100,
    mid_price=1.234
)

# 获取数据
amount = storage.get_last_amount("stg3l_usdt")

# 获取详细信息
detail = storage.get_last_amount_detail("stg3l_usdt")
```

## 运维指南

### Redis 配置

确保 Redis 已启用持久化：

```bash
# 检查 Redis 配置
redis-cli CONFIG GET save
redis-cli CONFIG GET appendonly

# 建议配置
save 900 1      # 15分钟内至少1个key改变则保存
save 300 10     # 5分钟内至少10个key改变则保存
save 60 10000   # 1分钟内至少10000个key改变则保存
appendonly yes  # 开启AOF
```

### 故障处理

1. **Redis 连接失败**
   - 系统使用当前余额初始化（影响最小）
   - 检查 Redis 服务状态：`redis-cli ping`
   - 恢复后会自动使用 Redis

2. **首次运行识别**
   - 监控脚本中 Source 显示为 "initial"
   - delta_amount 为 0

3. **性能问题**
   - 检查 Redis 内存使用：`redis-cli INFO memory`
   - 清理过期数据：自动30天过期

## 全新市场的优势

1. **无历史包袱**：不需要考虑文件迁移和兼容性
2. **简化逻辑**：代码更清晰，维护更容易
3. **故障影响小**：最坏情况只是一次 delta_amount = 0
4. **快速部署**：无需迁移步骤，直接启动即可

## 性能特性

| 操作 | Redis 存储 |
|------|-----------|
| 读取 | <1ms |
| 写入 | <1ms |
| 并发安全 | 是 |
| 原子操作 | 是 |
| 监控能力 | 简单 |

## 注意事项

1. 确保 Redis 服务稳定运行
2. 定期检查 Redis 持久化状态
3. 首次运行会看到所有 delta_amount = 0（正常现象）
4. 监控 Redis 内存使用情况
5. Redis 故障恢复后，可能会有一次额外的 delta_amount = 0
