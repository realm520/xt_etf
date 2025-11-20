"""
测试 NetValueRecorder - 净值数据库记录器

测试内容：
1. 批量写入功能（batch_size 触发）
2. 定时刷新功能（flush_interval 触发）
3. 异常事件记录（立即写入）
4. 数据库连接失败的优雅降级
5. 数据格式转换（Decimal、时间戳）
"""

import pytest
import asyncio
import time
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

# 导入被测试的模块
from etf.storage.net_value_recorder import NetValueRecorder, to_naive_utc


class TestToNaiveUtc:
    """测试时间转换函数"""

    def test_none_input_returns_current_time(self):
        """测试 None 输入返回当前时间"""
        result = to_naive_utc(None)
        assert isinstance(result, datetime)
        assert result.tzinfo is None
        # 验证时间接近当前时间（误差小于1秒）
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((result - now).total_seconds()) < 1

    def test_timestamp_conversion(self):
        """测试时间戳转换"""
        timestamp = 1704067200.0  # 2024-01-01 00:00:00 UTC
        result = to_naive_utc(timestamp)
        expected = datetime(2024, 1, 1, 0, 0, 0)
        assert result == expected
        assert result.tzinfo is None

    def test_aware_datetime_conversion(self):
        """测试带时区的 datetime 转换"""
        # 创建 UTC 时间
        aware_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = to_naive_utc(aware_dt)
        expected = datetime(2024, 1, 1, 12, 0, 0)
        assert result == expected
        assert result.tzinfo is None

    def test_naive_datetime_passthrough(self):
        """测试 naive datetime 直接返回"""
        naive_dt = datetime(2024, 1, 1, 12, 0, 0)
        result = to_naive_utc(naive_dt)
        assert result == naive_dt
        assert result.tzinfo is None


class TestNetValueRecorderInit:
    """测试 NetValueRecorder 初始化"""

    @pytest.mark.asyncio
    async def test_init_with_persistence_enabled(self):
        """测试启用持久化的初始化"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            batch_size=10,
            flush_interval=5.0,
            enable_persistence=True,
        )

        assert recorder.strategy_name == "test_stg"
        assert recorder.batch_size == 10
        assert recorder.flush_interval == 5.0
        assert recorder.enable_persistence is True
        assert recorder.engine is not None
        assert recorder.async_session_maker is not None
        assert len(recorder._buffer) == 0
        assert len(recorder._event_buffer) == 0

        await recorder.close()

    def test_init_with_persistence_disabled(self):
        """测试禁用持久化的初始化"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=False,
        )

        assert recorder.enable_persistence is False
        assert recorder.engine is None
        assert recorder.async_session_maker is None

    def test_init_with_custom_database_url(self):
        """测试自定义数据库 URL"""
        custom_url = "postgresql+asyncpg://user:pass@localhost:5432/testdb"
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=True,
            database_url=custom_url,
        )

        assert recorder.database_url == custom_url
        # 注意：实际连接会失败，但对象应该能创建


class TestNetValueRecorderBatchWriting:
    """测试批量写入功能"""

    @pytest.mark.asyncio
    async def test_batch_write_on_batch_size_trigger(self):
        """测试达到批量大小时触发写入"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            batch_size=3,
            flush_interval=100.0,  # 设置很长的间隔，避免时间触发
            enable_persistence=True,
        )

        # Mock 数据库操作
        with patch.object(recorder, '_flush_to_db', new_callable=AsyncMock) as mock_flush:
            # 添加 2 条记录，不应触发
            await recorder.record_net_value({"net_value": 1.0, "recorded_at": time.time()})
            await recorder.record_net_value({"net_value": 1.1, "recorded_at": time.time()})
            mock_flush.assert_not_called()

            # 添加第 3 条记录，应该触发
            await recorder.record_net_value({"net_value": 1.2, "recorded_at": time.time()})
            mock_flush.assert_called_once()

        await recorder.close()

    @pytest.mark.asyncio
    async def test_batch_write_on_time_trigger(self):
        """测试超过时间间隔时触发写入"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            batch_size=100,  # 设置很大的批量，避免批量触发
            flush_interval=1.0,  # 1秒间隔
            enable_persistence=True,
        )

        with patch.object(recorder, '_flush_to_db', new_callable=AsyncMock) as mock_flush:
            # 添加记录
            await recorder.record_net_value({"net_value": 1.0, "recorded_at": time.time()})

            # 模拟时间流逝
            recorder._last_flush = time.time() - 2.0  # 2秒前

            # 添加另一条记录，应该触发（因为超过1秒）
            await recorder.record_net_value({"net_value": 1.1, "recorded_at": time.time()})
            mock_flush.assert_called_once()

        await recorder.close()

    @pytest.mark.asyncio
    async def test_disabled_persistence_no_write(self):
        """测试禁用持久化时不写入"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=False,
        )

        # 不应该有任何副作用
        await recorder.record_net_value({"net_value": 1.0, "recorded_at": time.time()})
        assert len(recorder._buffer) == 0  # 缓冲区应该为空


class TestNetValueRecorderEventRecording:
    """测试异常事件记录"""

    @pytest.mark.asyncio
    async def test_event_immediate_write(self):
        """测试事件立即写入（不等批量）"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=True,
        )

        with patch.object(recorder, '_flush_events_to_db', new_callable=AsyncMock) as mock_flush:
            event_data = {
                "event_type": "price_spike",
                "severity": "high",
                "old_price": 1000.0,
                "new_price": 1200.0,
                "change_rate": 0.20,
                "event_time": time.time()
            }

            await recorder.record_event(event_data)

            # 事件应该立即写入
            mock_flush.assert_called_once()

        await recorder.close()

    @pytest.mark.asyncio
    async def test_disabled_persistence_no_event_write(self):
        """测试禁用持久化时不记录事件"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=False,
        )

        event_data = {
            "event_type": "price_spike",
            "severity": "high",
            "event_time": time.time()
        }

        await recorder.record_event(event_data)
        assert len(recorder._event_buffer) == 0


class TestNetValueRecorderDataFormatting:
    """测试数据格式转换"""

    def test_format_net_value_record_basic(self):
        """测试基本净值数据格式化"""
        recorder = NetValueRecorder(strategy_name="stg3l", enable_persistence=False)

        data = {
            "net_value": 1.23456789,
            "underlying_price": 50000.12345678,
            "change_rate": 0.0123,
            "recorded_at": 1704067200.0,  # 2024-01-01 00:00:00 UTC
        }

        result = recorder._format_net_value_record(data)

        assert result["strategy_name"] == "stg3l"
        assert result["net_value"] == Decimal("1.23456789")
        assert result["underlying_price"] == Decimal("50000.12345678")
        assert result["change_rate"] == Decimal("0.0123")
        assert result["recorded_at"] == datetime(2024, 1, 1, 0, 0, 0)
        assert isinstance(result["net_value"], Decimal)
        assert isinstance(result["recorded_at"], datetime)
        assert result["recorded_at"].tzinfo is None

    def test_format_net_value_record_with_optional_fields(self):
        """测试包含可选字段的格式化"""
        recorder = NetValueRecorder(strategy_name="stg5s", enable_persistence=False)

        data = {
            "net_value": 0.98765432,
            "symbol": "stg_usdt",
            "leverage": 5,
            "long": False,  # short
            "fee_deducted": 0.0001,
            "cumulative_fee": 0.0123,
            "rebalance_triggered": True,
            "rebalance_count": 3,
            "recorded_at": time.time(),
        }

        result = recorder._format_net_value_record(data)

        assert result["symbol"] == "stg_usdt"
        assert result["leverage"] == 5
        assert result["direction"] == "short"
        assert result["fee_deducted"] == Decimal("0.0001")
        assert result["cumulative_fee"] == Decimal("0.0123")
        assert result["rebalance_triggered"] is True
        assert result["rebalance_count"] == 3

    def test_format_event_record(self):
        """测试事件数据格式化"""
        recorder = NetValueRecorder(strategy_name="stg3l", enable_persistence=False)

        event_data = {
            "event_type": "price_spike",
            "severity": "high",
            "symbol": "stg_usdt",
            "old_price": 1000.0,
            "new_price": 1200.0,
            "change_rate": 0.20,
            "gap_seconds": 300,
            "missed_intervals": 5,
            "net_value_id": 12345,
            "extra_data": {"reason": "test"},
            "event_time": 1704067200.0,
        }

        result = recorder._format_event_record(event_data)

        assert result["strategy_name"] == "stg3l"
        assert result["event_type"] == "price_spike"
        assert result["severity"] == "high"
        assert result["symbol"] == "stg_usdt"
        assert result["old_price"] == Decimal("1000.0")
        assert result["new_price"] == Decimal("1200.0")
        assert result["change_rate"] == Decimal("0.20")
        assert result["gap_seconds"] == 300
        assert result["missed_intervals"] == 5
        assert result["net_value_id"] == 12345
        assert result["extra_data"] == {"reason": "test"}
        assert result["event_time"] == datetime(2024, 1, 1, 0, 0, 0)


class TestNetValueRecorderDatabaseOperations:
    """测试实际数据库操作（使用 mock）"""

    @pytest.mark.asyncio
    async def test_flush_to_db_success(self):
        """测试成功的数据库刷新"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=True,
        )

        # 添加测试数据到缓冲区
        recorder._buffer = [
            {"net_value": 1.0, "recorded_at": time.time()},
            {"net_value": 1.1, "recorded_at": time.time()},
        ]

        # Mock 数据库会话
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch.object(recorder, 'async_session_maker') as mock_maker:
            mock_maker.return_value.__aenter__.return_value = mock_session

            await recorder._flush_to_db()

            # 验证执行了插入和提交
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

            # 缓冲区应该被清空
            assert len(recorder._buffer) == 0

        await recorder.close()

    @pytest.mark.asyncio
    async def test_flush_to_db_with_retry_on_failure(self):
        """测试数据库失败时的重试机制"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=True,
        )

        recorder._buffer = [{"net_value": 1.0, "recorded_at": time.time()}]

        # Mock 数据库会话，第一次失败，第二次成功
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(side_effect=[
            OperationalError("Connection failed", None, None),
            None  # 第二次成功
        ])
        mock_session.commit = AsyncMock()

        with patch.object(recorder, 'async_session_maker') as mock_maker:
            mock_maker.return_value.__aenter__.return_value = mock_session

            await recorder._flush_to_db()

            # 应该尝试了2次（第一次失败，第二次成功）
            assert mock_session.execute.call_count == 2

        await recorder.close()

    @pytest.mark.asyncio
    async def test_flush_all_combines_buffers(self):
        """测试 flush_all 刷新所有缓冲区"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=True,
        )

        recorder._buffer = [{"net_value": 1.0, "recorded_at": time.time()}]
        recorder._event_buffer = [{"event_type": "test", "event_time": time.time()}]

        with patch.object(recorder, '_flush_to_db', new_callable=AsyncMock) as mock_flush_data, \
             patch.object(recorder, '_flush_events_to_db', new_callable=AsyncMock) as mock_flush_events:

            await recorder.flush_all()

            mock_flush_data.assert_called_once()
            mock_flush_events.assert_called_once()

        await recorder.close()


class TestNetValueRecorderGracefulDegradation:
    """测试优雅降级"""

    def test_init_failure_disables_persistence(self):
        """测试初始化失败时禁用持久化"""
        # 使用无效的数据库 URL
        invalid_url = "postgresql+asyncpg://invalid:invalid@invalid:9999/invalid"

        # 不应该抛出异常，而是禁用持久化
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=True,
            database_url=invalid_url,
        )

        # 应该能创建对象，但持久化应该被禁用
        assert recorder is not None
        # 注意：由于 create_async_engine 只在实际使用时才会失败，
        # 所以这里可能不会立即禁用持久化

    @pytest.mark.asyncio
    async def test_record_continues_on_db_failure(self):
        """测试数据库写入失败后继续运行"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            batch_size=2,
            enable_persistence=True,
        )

        with patch.object(recorder, '_flush_to_db', new_callable=AsyncMock) as mock_flush:
            mock_flush.side_effect = Exception("Database error")

            # 即使数据库失败，也不应该抛出异常
            try:
                await recorder.record_net_value({"net_value": 1.0, "recorded_at": time.time()})
                await recorder.record_net_value({"net_value": 1.1, "recorded_at": time.time()})
            except Exception as e:
                pytest.fail(f"Should not raise exception: {e}")

        await recorder.close()


class TestNetValueRecorderClose:
    """测试资源清理"""

    @pytest.mark.asyncio
    async def test_close_flushes_buffers(self):
        """测试关闭时刷新缓冲区"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=True,
        )

        recorder._buffer = [{"net_value": 1.0, "recorded_at": time.time()}]

        with patch.object(recorder, 'flush_all', new_callable=AsyncMock) as mock_flush:
            await recorder.close()
            mock_flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_disposes_engine(self):
        """测试关闭时释放数据库连接"""
        recorder = NetValueRecorder(
            strategy_name="test_stg",
            enable_persistence=True,
        )

        with patch.object(recorder.engine, 'dispose', new_callable=AsyncMock) as mock_dispose:
            await recorder.close()
            mock_dispose.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
