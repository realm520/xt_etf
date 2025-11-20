# 异步数据库写入事件循环修复

## 问题描述

在 `etf/net_value_improved.py` 中，使用 `asyncio.run()` 在同步代码中执行异步数据库写入操作，导致以下错误：

```
RuntimeError: Event loop is closed
Task got Future attached to a different loop
coroutine 'Connection._cancel' was never awaited
```

## 根本原因

`asyncio.run()` 会：
1. 创建新的事件循环
2. 运行协程
3. **关闭事件循环**

这导致了与 SQLAlchemy 的 asyncpg 连接池冲突，因为：
- asyncpg 连接池需要持久的事件循环
- 每次 `asyncio.run()` 都会创建和关闭循环
- 连接池尝试使用已关闭的循环进行清理操作

## 解决方案

### 1. 创建持久事件循环

```python
def _get_or_create_event_loop(self) -> asyncio.AbstractEventLoop:
    """获取或创建持久的事件循环（用于异步数据库操作）"""
    if not hasattr(self, '_event_loop') or self._event_loop is None or self._event_loop.is_closed():
        import threading

        # 创建新的事件循环和线程
        self._event_loop = asyncio.new_event_loop()

        def run_loop():
            """在独立线程中运行事件循环"""
            asyncio.set_event_loop(self._event_loop)
            self._event_loop.run_forever()

        self._loop_thread = threading.Thread(
            target=run_loop,
            daemon=True,
            name="async_db_loop"
        )
        self._loop_thread.start()
        logger.debug(f"{self.strategy_name}: 创建持久事件循环用于异步数据库操作")

    return self._event_loop
```

### 2. 使用 `run_coroutine_threadsafe`

将 `asyncio.run()` 替换为 `asyncio.run_coroutine_threadsafe()`：

**之前（错误）：**
```python
def _run_async_db_write(self, formatted_data: Dict):
    try:
        import asyncio
        asyncio.run(self.db_recorder.record_net_value(formatted_data))
    except Exception as e:
        logger.debug(f"后台数据库写入失败: {e}")
```

**之后（正确）：**
```python
def _run_async_db_write(self, formatted_data: Dict):
    try:
        # 使用事件循环线程安全方式提交任务
        loop = self._get_or_create_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self.db_recorder.record_net_value(formatted_data),
            loop
        )
        # 不等待结果，让它在后台完成
    except Exception as e:
        logger.debug(f"后台数据库写入失败（正常，将由批量处理）: {e}")
```

### 3. 清理异步资源

在程序退出时正确清理：

```python
def _cleanup_async_resources(self):
    """清理异步资源（事件循环、数据库连接等）"""
    try:
        # 刷新数据库缓冲
        if self.db_recorder:
            logger.info(f"{self.strategy_name}: 正在刷新数据库缓冲...")
            loop = self._get_or_create_event_loop()
            future = asyncio.run_coroutine_threadsafe(
                self.db_recorder.flush_all(),
                loop
            )
            # 等待刷新完成（最多10秒）
            future.result(timeout=10)

            # 关闭数据库连接
            future = asyncio.run_coroutine_threadsafe(
                self.db_recorder.close(),
                loop
            )
            future.result(timeout=5)

        # 停止事件循环
        if hasattr(self, '_event_loop') and self._event_loop and not self._event_loop.is_closed():
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            if hasattr(self, '_loop_thread') and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=5)

        # 关闭线程池
        if hasattr(self, '_db_thread_pool'):
            self._db_thread_pool.shutdown(wait=True, cancel_futures=False)
        if hasattr(self, '_event_thread_pool'):
            self._event_thread_pool.shutdown(wait=True, cancel_futures=False)

        logger.info(f"{self.strategy_name}: 所有异步资源已清理")

    except Exception as e:
        logger.error(f"{self.strategy_name}: 清理异步资源时出错: {e}", exc_info=True)
```

## 技术要点

### `asyncio.run()` vs `run_coroutine_threadsafe()`

| 特性 | `asyncio.run()` | `run_coroutine_threadsafe()` |
|------|----------------|------------------------------|
| 事件循环生命周期 | 创建 → 运行 → **关闭** | 使用现有循环 |
| 适用场景 | 程序入口点 | 从同步代码调用异步代码 |
| 线程安全 | 否（需在主线程） | 是（可从任意线程） |
| 连接池兼容 | 不兼容（循环会关闭） | 兼容（循环持久） |

### 线程模型

```
主线程 (同步代码)
├─ ThreadPoolExecutor (db_writer)
│  └─ _run_async_db_write()
│     └─ run_coroutine_threadsafe() →
│                                      ↓
独立事件循环线程 (async_db_loop) ←────┘
├─ event_loop.run_forever()
├─ NetValueRecorder.record_net_value()
└─ PostgreSQL asyncpg 连接池
```

## 受影响的方法

1. `_run_async_db_write()` - 净值数据写入
2. `_run_async_event_write()` - 异常事件写入
3. `_cleanup_async_resources()` - 资源清理（新增）

## 测试验证

运行 `ton3l` 策略验证修复：

```bash
python run_net_value.py --strategy ton3l --env qa
```

**预期结果**：
- ✅ 不再出现 `RuntimeError: Event loop is closed`
- ✅ 不再出现 `got Future attached to a different loop`
- ✅ 不再出现 `coroutine was never awaited` 警告
- ✅ 数据库批量写入正常工作
- ✅ 程序退出时正确清理资源

## 相关文件

- `etf/net_value_improved.py:115-137` - `_get_or_create_event_loop()`
- `etf/net_value_improved.py:139-175` - `_cleanup_async_resources()`
- `etf/net_value_improved.py:355-368` - `_run_async_db_write()` (修复)
- `etf/net_value_improved.py:384-397` - `_run_async_event_write()` (修复)
- `etf/storage/net_value_recorder.py` - NetValueRecorder 类

## 最佳实践

在 Python 中混合同步和异步代码时：

1. **持久事件循环**: 创建长期运行的事件循环，不要频繁创建销毁
2. **线程安全**: 使用 `run_coroutine_threadsafe()` 从同步代码调用异步代码
3. **资源管理**: 确保在程序退出时正确清理所有异步资源
4. **避免 `asyncio.run()`**: 除非在程序入口点，否则不要使用
5. **独立线程**: 将事件循环放在独立的守护线程中

## 参考资料

- [asyncio - Developing with asyncio](https://docs.python.org/3/library/asyncio-dev.html)
- [asyncio.run_coroutine_threadsafe()](https://docs.python.org/3/library/asyncio-task.html#asyncio.run_coroutine_threadsafe)
- [SQLAlchemy AsyncIO](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
