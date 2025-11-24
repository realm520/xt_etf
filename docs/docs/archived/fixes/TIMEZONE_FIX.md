# PostgreSQL 时区问题修复

## 问题描述

在向 PostgreSQL 数据库写入订单和成交记录时，出现以下错误：

```
ERROR | order_recorder.py:465 | ❌ PostgreSQL写入订单失败:
(sqlalchemy.dialects.postgresql.asyncpg.Error) <class 'asyncpg.exceptions.DataError'>:
invalid input for query argument $16: datetime.datetime(2025, 11, 19, 12, 41, ...)
(can't subtract offset-naive and offset-aware datetimes)
```

## 根本原因

1. **数据库字段定义**：`models.py` 中时间字段定义为 `Column(DateTime, ...)`，在 PostgreSQL 中映射为 `TIMESTAMP WITHOUT TIME ZONE`
2. **代码传入值**：`order_recorder.py` 传入的是带时区的 datetime 对象（`tzinfo=datetime.timezone.utc`）
3. **类型不匹配**：PostgreSQL 无法正确处理向 `TIMESTAMP WITHOUT TIME ZONE` 字段插入带时区的 datetime

## 解决方案

### 新增 `to_naive_utc()` 函数

在 `etf/storage/order_recorder.py` 中添加新函数，将任意时间格式转换为 naive UTC datetime：

```python
def to_naive_utc(dt: Any) -> datetime:
    """
    将任意时间格式转换为 naive UTC datetime（无时区信息）
    用于插入 PostgreSQL 的 TIMESTAMP WITHOUT TIME ZONE 字段

    Args:
        dt: datetime 对象或时间戳（可能是 str, int, float, datetime）
    Returns:
        naive UTC datetime 对象（无时区信息）
    """
    # 先确保带有UTC时区
    utc_dt = ensure_utc_timezone(dt)
    # 移除时区信息（保持UTC时间不变）
    return utc_dt.replace(tzinfo=None)
```

### 修改插入逻辑

在所有数据库插入点使用 `to_naive_utc()` 替代 `ensure_utc_timezone()`：

1. **`_batch_write_orders()`** - 批量写入订单
2. **`_insert_orders_one_by_one()`** - 逐条插入订单
3. **`_batch_write_trades()`** - 批量写入成交
4. **`_insert_trades_one_by_one()`** - 逐条插入成交

### 修改示例

**修改前**:
```python
timestamp = order.get("timestamp") or order.get("created_at")
created_at = ensure_utc_timezone(timestamp)  # ❌ 带时区
```

**修改后**:
```python
timestamp = order.get("timestamp") or order.get("created_at")
created_at = to_naive_utc(timestamp)  # ✅ 无时区
```

## 验证测试

运行验证脚本确认修复：

```bash
uv run python scripts/verify_timezone_fix.py
```

**测试结果**：
- ✅ 带UTC时区的datetime正确转换为naive
- ✅ 时间戳正确转换
- ✅ ISO格式字符串正确转换
- ✅ 完整转换链正常工作
- ✅ PostgreSQL兼容性检查通过

## 影响范围

- **修改文件**：`etf/storage/order_recorder.py`
- **影响功能**：所有订单和成交记录的数据库写入
- **测试文件**：
  - `tests/test_order_recorder_timezone_fix.py` - pytest测试套件
  - `scripts/verify_timezone_fix.py` - 独立验证脚本

## 注意事项

1. **时区一致性**：所有时间均使用UTC，移除时区信息不影响数据正确性
2. **向后兼容**：保留 `ensure_utc_timezone()` 函数用于其他需要时区的场景
3. **数据库结构**：未修改数据库表结构，避免迁移风险
4. **CSV降级**：CSV降级机制不受影响，继续正常工作

## 长期优化建议

考虑将数据库字段改为 `TIMESTAMP WITH TIME ZONE`：

```python
# models.py
from sqlalchemy import DateTime

# 当前（保留）
created_at = Column(DateTime, default=func.now())

# 推荐（未来优化）
from sqlalchemy.dialects.postgresql import TIMESTAMP
created_at = Column(TIMESTAMP(timezone=True), default=func.now())
```

**优势**：
- 保留完整时区信息
- 避免时区转换问题
- 更好的国际化支持

**考虑**：
- 需要数据库迁移
- 需要兼容性测试
- 现有数据需要迁移

## 相关链接

- [PostgreSQL DateTime Types](https://www.postgresql.org/docs/current/datatype-datetime.html)
- [SQLAlchemy DateTime](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.DateTime)
- [Python datetime timezone](https://docs.python.org/3/library/datetime.html#aware-and-naive-objects)

---

**修复日期**: 2025-11-19
**修复人员**: Claude Code
**版本**: v1.0
