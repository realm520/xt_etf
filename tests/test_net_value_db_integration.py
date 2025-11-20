"""
测试 ImprovedNetValue 数据库集成

测试内容：
1. ImprovedNetValue 与 NetValueRecorder 的集成
2. 数据库持久化启用/禁用的行为
3. 异常事件的数据库记录
4. 数据流：计算 → Redis + PostgreSQL
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from decimal import Decimal

# 导入被测试的模块
from etf.net_value_improved import ImprovedNetValue
from etf.storage.net_value_recorder import NetValueRecorder


class TestImprovedNetValueDbInit:
    """测试数据库持久化的初始化"""

    def test_init_with_db_persistence_enabled(self):
        """测试启用数据库持久化"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)

        net_value = ImprovedNetValue(
            redis_client=mock_redis,
            symbol="stg",
            leverage=3,
            long=True,
            init_net_value=1.0,
            interval=1,
            daily_fee=0.001,
            rebalance_threshold=0.05,
            max_single_change=0.10,
            max_restart_gap=300,
            enable_db_persistence=True,
            strategy_name="stg3l"
        )

        # 应该创建了数据库记录器
        assert net_value.db_recorder is not None
        assert isinstance(net_value.db_recorder, NetValueRecorder)
        assert net_value.strategy_name == "stg3l"

    def test_init_with_db_persistence_disabled(self):
        """测试禁用数据库持久化"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)

        net_value = ImprovedNetValue(
            redis_client=mock_redis,
            symbol="stg",
            leverage=3,
            long=True,
            init_net_value=1.0,
            interval=1,
            daily_fee=0.001,
            rebalance_threshold=0.05,
            enable_db_persistence=False,
            strategy_name="stg3l"
        )

        # 不应该创建数据库记录器
        assert net_value.db_recorder is None

    def test_init_without_strategy_name_no_db(self):
        """测试未提供策略名称时不启用数据库"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)

        net_value = ImprovedNetValue(
            redis_client=mock_redis,
            symbol="stg",
            leverage=3,
            long=True,
            init_net_value=1.0,
            enable_db_persistence=True,
            # 未提供 strategy_name
        )

        # 即使启用了持久化，没有策略名称也不应该创建记录器
        assert net_value.db_recorder is None


class TestImprovedNetValueDbWriting:
    """测试数据库写入功能"""

    @pytest.mark.asyncio
    async def test_update_with_db_persistence(self):
        """测试更新时同时写入 Redis 和数据库"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)
        mock_redis.lpush = Mock()
        mock_redis.ltrim = Mock()

        # 创建 mock 的数据库记录器
        mock_db_recorder = AsyncMock(spec=NetValueRecorder)
        mock_db_recorder.record_net_value = AsyncMock()

        with patch('etf.net_value_improved.NetValueRecorder', return_value=mock_db_recorder):
            net_value = ImprovedNetValue(
                redis_client=mock_redis,
                symbol="stg",
                leverage=3,
                long=True,
                init_net_value=1.0,
                enable_db_persistence=True,
                strategy_name="stg3l"
            )

            # 执行更新
            current_price = 50000.0
            net_value.update(current_price)

            # 等待异步任务完成
            await asyncio.sleep(0.1)

            # 验证 Redis 写入
            assert mock_redis.set.called
            assert mock_redis.lpush.called

            # 验证数据库写入
            mock_db_recorder.record_net_value.assert_called_once()
            call_args = mock_db_recorder.record_net_value.call_args[0][0]
            assert call_args["net_value"] == 1.0
            assert call_args["underlying_price"] == 50000.0
            assert "recorded_at" in call_args

    def test_update_without_db_persistence(self):
        """测试禁用持久化时只写入 Redis"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)
        mock_redis.lpush = Mock()
        mock_redis.ltrim = Mock()

        net_value = ImprovedNetValue(
            redis_client=mock_redis,
            symbol="stg",
            leverage=3,
            long=True,
            init_net_value=1.0,
            enable_db_persistence=False,
            strategy_name="stg3l"
        )

        # 执行更新
        net_value.update(50000.0)

        # 只应该写入 Redis
        assert mock_redis.set.called
        assert net_value.db_recorder is None


class TestImprovedNetValueEventRecording:
    """测试异常事件的数据库记录"""

    @pytest.mark.asyncio
    async def test_price_spike_event_recorded(self):
        """测试价格突变事件记录到数据库"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)
        mock_redis.lpush = Mock()
        mock_redis.ltrim = Mock()

        mock_db_recorder = AsyncMock(spec=NetValueRecorder)
        mock_db_recorder.record_net_value = AsyncMock()
        mock_db_recorder.record_event = AsyncMock()

        with patch('etf.net_value_improved.NetValueRecorder', return_value=mock_db_recorder):
            net_value = ImprovedNetValue(
                redis_client=mock_redis,
                symbol="stg",
                leverage=3,
                long=True,
                init_net_value=1.0,
                max_single_change=0.10,  # 10% 限制
                enable_db_persistence=True,
                strategy_name="stg3l"
            )

            # 第一次更新
            net_value.update(50000.0)
            await asyncio.sleep(0.1)

            # 价格突变 20%（超过 10% 限制）
            net_value.update(60000.0)
            await asyncio.sleep(0.1)

            # 验证事件被记录
            assert mock_db_recorder.record_event.called
            event_call = mock_db_recorder.record_event.call_args[0][0]
            assert event_call["event_type"] == "price_spike"
            assert event_call["old_price"] == 50000.0
            assert event_call["new_price"] == 60000.0

    @pytest.mark.asyncio
    async def test_long_restart_event_recorded(self):
        """测试长时间重启事件记录"""
        import json

        mock_redis = Mock()
        # 模拟上次更新时间是 10 分钟前
        last_update = time.time() - 600
        detail_data = {
            "net_value": 1.0,
            "last_price": 50000.0,
            "last_update": last_update
        }
        mock_redis.get = Mock(return_value=json.dumps(detail_data))
        mock_redis.set = Mock()
        mock_redis.lpush = Mock()
        mock_redis.ltrim = Mock()

        mock_db_recorder = AsyncMock(spec=NetValueRecorder)
        mock_db_recorder.record_net_value = AsyncMock()
        mock_db_recorder.record_event = AsyncMock()

        with patch('etf.net_value_improved.NetValueRecorder', return_value=mock_db_recorder):
            net_value = ImprovedNetValue(
                redis_client=mock_redis,
                symbol="stg",
                leverage=3,
                long=True,
                init_net_value=1.0,
                max_restart_gap=300,  # 5 分钟限制
                enable_db_persistence=True,
                strategy_name="stg3l"
            )

            # 触发更新（应该检测到长时间重启）
            net_value.update(51000.0)
            await asyncio.sleep(0.1)

            # 验证 long_restart 事件被记录
            event_calls = [call[0][0] for call in mock_db_recorder.record_event.call_args_list]
            restart_events = [e for e in event_calls if e["event_type"] == "long_restart"]
            assert len(restart_events) > 0
            assert restart_events[0]["gap_seconds"] >= 300

    @pytest.mark.asyncio
    async def test_recovery_event_recorded(self):
        """测试恢复事件记录"""
        import json

        mock_redis = Mock()
        # 模拟上次更新时间是 10 分钟前
        last_update = time.time() - 600
        detail_data = {
            "net_value": 1.0,
            "last_price": 50000.0,
            "last_update": last_update,
            "total_fee_deducted": 0.001
        }
        mock_redis.get = Mock(return_value=json.dumps(detail_data))
        mock_redis.set = Mock()
        mock_redis.lpush = Mock()
        mock_redis.ltrim = Mock()

        mock_db_recorder = AsyncMock(spec=NetValueRecorder)
        mock_db_recorder.record_net_value = AsyncMock()
        mock_db_recorder.record_event = AsyncMock()

        with patch('etf.net_value_improved.NetValueRecorder', return_value=mock_db_recorder):
            net_value = ImprovedNetValue(
                redis_client=mock_redis,
                symbol="stg",
                leverage=3,
                long=True,
                init_net_value=1.0,
                max_restart_gap=300,
                enable_db_persistence=True,
                strategy_name="stg3l"
            )

            # 触发更新（应该检测到恢复）
            net_value.update(51000.0)
            await asyncio.sleep(0.1)

            # 验证 recovery 事件被记录
            event_calls = [call[0][0] for call in mock_db_recorder.record_event.call_args_list]
            recovery_events = [e for e in event_calls if e["event_type"] == "recovery"]
            assert len(recovery_events) > 0


class TestImprovedNetValueDataFormat:
    """测试数据格式化"""

    def test_format_db_data_basic(self):
        """测试基本数据格式化"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)

        net_value = ImprovedNetValue(
            redis_client=mock_redis,
            symbol="stg",
            leverage=3,
            long=True,
            init_net_value=1.0,
            enable_db_persistence=True,
            strategy_name="stg3l"
        )

        net_value.update(50000.0)

        formatted = net_value._format_db_data()

        assert formatted["symbol"] == "stg_usdt"
        assert formatted["leverage"] == 3
        assert formatted["long"] is True
        assert formatted["net_value"] == 1.0
        assert formatted["underlying_price"] == 50000.0
        assert "recorded_at" in formatted
        assert isinstance(formatted["recorded_at"], float)

    def test_format_db_data_with_fees(self):
        """测试包含手续费的数据格式化"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)
        mock_redis.lpush = Mock()
        mock_redis.ltrim = Mock()

        net_value = ImprovedNetValue(
            redis_client=mock_redis,
            symbol="stg",
            leverage=3,
            long=True,
            init_net_value=1.0,
            daily_fee=0.001,
            enable_db_persistence=True,
            strategy_name="stg3l"
        )

        net_value.update(50000.0)

        formatted = net_value._format_db_data()

        assert "fee_deducted" in formatted
        assert "cumulative_fee" in formatted
        # 由于是第一次更新，手续费应该很小或为0
        assert formatted["cumulative_fee"] >= 0


class TestImprovedNetValueAsyncErrorHandling:
    """测试异步操作的错误处理"""

    @pytest.mark.asyncio
    async def test_db_write_failure_does_not_block_update(self):
        """测试数据库写入失败不阻塞净值更新"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)
        mock_redis.lpush = Mock()
        mock_redis.ltrim = Mock()

        mock_db_recorder = AsyncMock(spec=NetValueRecorder)
        # 模拟数据库写入失败
        mock_db_recorder.record_net_value = AsyncMock(side_effect=Exception("DB Error"))

        with patch('etf.net_value_improved.NetValueRecorder', return_value=mock_db_recorder):
            net_value = ImprovedNetValue(
                redis_client=mock_redis,
                symbol="stg",
                leverage=3,
                long=True,
                init_net_value=1.0,
                enable_db_persistence=True,
                strategy_name="stg3l"
            )

            # 更新应该成功（即使数据库失败）
            try:
                net_value.update(50000.0)
                await asyncio.sleep(0.1)
                # 不应该抛出异常
            except Exception as e:
                pytest.fail(f"Update should not raise exception: {e}")

            # Redis 应该仍然被更新
            assert mock_redis.set.called

    def test_no_event_loop_graceful_degradation(self):
        """测试无事件循环时的优雅降级"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)

        mock_db_recorder = AsyncMock(spec=NetValueRecorder)
        mock_db_recorder.record_net_value = AsyncMock()

        with patch('etf.net_value_improved.NetValueRecorder', return_value=mock_db_recorder):
            net_value = ImprovedNetValue(
                redis_client=mock_redis,
                symbol="stg",
                leverage=3,
                long=True,
                init_net_value=1.0,
                enable_db_persistence=True,
                strategy_name="stg3l"
            )

            # 在没有事件循环的情况下更新（应该静默失败）
            with patch('asyncio.create_task', side_effect=RuntimeError("No event loop")):
                try:
                    net_value.update(50000.0)
                    # 不应该抛出异常
                except RuntimeError:
                    pytest.fail("Should gracefully handle missing event loop")


class TestImprovedNetValueIntegrationScenarios:
    """集成场景测试"""

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_db_persistence(self):
        """测试完整生命周期（包含数据库）"""
        mock_redis = Mock()
        mock_redis.set = Mock()
        mock_redis.get = Mock(return_value=None)
        mock_redis.lpush = Mock()
        mock_redis.ltrim = Mock()

        mock_db_recorder = AsyncMock(spec=NetValueRecorder)
        mock_db_recorder.record_net_value = AsyncMock()
        mock_db_recorder.record_event = AsyncMock()

        with patch('etf.net_value_improved.NetValueRecorder', return_value=mock_db_recorder):
            net_value = ImprovedNetValue(
                redis_client=mock_redis,
                symbol="stg",
                leverage=3,
                long=True,
                init_net_value=1.0,
                daily_fee=0.001,
                enable_db_persistence=True,
                strategy_name="stg3l"
            )

            # 多次更新
            prices = [50000.0, 50500.0, 51000.0, 50800.0]
            for price in prices:
                net_value.update(price)
                await asyncio.sleep(0.05)

            # 验证所有更新都记录到数据库
            assert mock_db_recorder.record_net_value.call_count == len(prices)

            # 验证 Redis 也被更新
            assert mock_redis.set.call_count >= len(prices)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
