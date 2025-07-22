# -*- coding:utf-8 -*-

"""
ETF系统性能基准测试

Author: Claude Code
Date: 2025-01-22
"""

import time
import pytest
import redis
from unittest.mock import MagicMock, patch
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.risk import RiskController
from etf.washing import WashController
from etf.orderbook import get_orderbook, Orderbook
from tests.test_config import (
    assert_performance_threshold,
    create_mock_orders,
    create_mock_depth_data
)


class TestOrderbookPerformance:
    """订单簿性能测试"""

    def test_orderbook_generation_performance(self, benchmark_runner):
        """测试订单簿生成性能"""
        def generate_orderbook():
            return get_orderbook(mid_price=1000.0, bid_ask_spread=0.01)
        
        result = benchmark_runner.run_benchmark(
            "orderbook_generation",
            generate_orderbook,
            iterations=1000
        )
        
        # 验证生成时间在合理范围内
        avg_time = benchmark_runner.results["orderbook_generation"]["avg_time"]
        assert_performance_threshold(avg_time, 0.01)  # 10ms内
        
        # 验证结果正确性
        bid_orders, ask_orders = result
        assert len(bid_orders) == 30
        assert len(ask_orders) == 30

    def test_large_orderbook_performance(self, benchmark_runner):
        """测试大订单簿性能"""
        def generate_large_orderbook():
            orderbook = Orderbook(
                bid_0=999.0,
                ask_0=1001.0,
                layer=100,  # 大层数
                prec_price=4,
                prec_amount=2
            )
            
            return orderbook.make(
                direction="bid",
                make_price=orderbook.power2,
                make_amount=orderbook.powera,
                price_percent=0.01,
                mean=50,
                scale=10,
                sparse=0.001
            )
        
        result = benchmark_runner.run_benchmark(
            "large_orderbook_generation",
            generate_large_orderbook,
            iterations=100
        )
        
        # 大订单簿生成时间应该在50ms内
        avg_time = benchmark_runner.results["large_orderbook_generation"]["avg_time"]
        assert_performance_threshold(avg_time, 0.05)
        
        # 验证结果
        assert len(result) == 100

    def test_orderbook_calculation_methods(self, benchmark_runner):
        """测试订单簿计算方法性能"""
        orderbook = Orderbook(bid_0=1000.0, ask_0=1001.0, layer=50, prec_price=4)
        
        # 测试不同计算方法的性能
        methods = [
            ("linear", lambda: orderbook.linear("bid", 0.1)),
            ("power", lambda: orderbook.power("bid", 0.01)),
            ("power2", lambda: orderbook.power2("bid", 0.01)),
        ]
        
        for method_name, method_func in methods:
            benchmark_runner.run_benchmark(
                f"orderbook_{method_name}",
                method_func,
                iterations=1000
            )
            
            # 每种方法都应该在1ms内完成
            avg_time = benchmark_runner.results[f"orderbook_{method_name}"]["avg_time"]
            assert_performance_threshold(avg_time, 0.001)


class TestOrderManagerPerformance:
    """订单管理器性能测试"""

    @pytest.fixture
    def order_manager_setup(self):
        """订单管理器设置"""
        client = MagicMock()
        client.get_open_orders.return_value = []
        client.batch_orders.return_value = {"success": True}
        client.cancel_order.return_value = {"success": True}
        client.batch_cancel.return_value = {"success": True}
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            return OrderManager(client, strategy_name="perf_test")

    def test_batch_order_creation_performance(self, benchmark_runner, order_manager_setup):
        """测试批量订单创建性能"""
        order_manager = order_manager_setup
        
        # 测试不同批量大小的性能
        batch_sizes = [10, 50, 100]
        
        for batch_size in batch_sizes:
            orders_data = []
            for i in range(batch_size):
                orders_data.append({
                    "symbol": "BTCUSDT",
                    "side": "BUY" if i % 2 == 0 else "SELL",
                    "type": "LIMIT",
                    "price": 50000.0 + i,
                    "quantity": 0.001,
                    "clientOrderId": f"perf_test_{i}"
                })
            
            def batch_order_test():
                return order_manager.add_orders_batch(orders_data, batch_id=12345)
            
            benchmark_runner.run_benchmark(
                f"batch_orders_{batch_size}",
                batch_order_test,
                iterations=100
            )
            
            # 批量订单处理时间应该在合理范围内
            avg_time = benchmark_runner.results[f"batch_orders_{batch_size}"]["avg_time"]
            expected_threshold = 0.001 + (batch_size * 0.00001)  # 基础时间 + 每订单时间
            assert_performance_threshold(avg_time, expected_threshold)

    def test_temp_id_generation_performance(self, benchmark_runner, order_manager_setup):
        """测试临时ID生成性能"""
        order_manager = order_manager_setup
        
        def generate_temp_id():
            return order_manager.create_temp_id()
        
        benchmark_runner.run_benchmark(
            "temp_id_generation",
            generate_temp_id,
            iterations=10000
        )
        
        # ID生成应该非常快
        avg_time = benchmark_runner.results["temp_id_generation"]["avg_time"]
        assert_performance_threshold(avg_time, 0.0001)  # 0.1ms内

    def test_order_manager_memory_usage(self, order_manager_setup):
        """测试订单管理器内存使用"""
        import psutil
        import os
        
        order_manager = order_manager_setup
        process = psutil.Process(os.getpid())
        
        # 测试前内存使用
        memory_before = process.memory_info().rss
        
        # 创建大量订单数据
        for i in range(1000):
            order_data = {
                f"order_{i}": {
                    "symbol": "BTCUSDT",
                    "orderId": f"mem_test_{i}",
                    "price": 50000.0 + i,
                    "quantity": 0.001
                }
            }
            order_manager.open_orders.update(order_data)
        
        # 测试后内存使用
        memory_after = process.memory_info().rss
        memory_increase = memory_after - memory_before
        
        # 内存增长应该在合理范围内（少于10MB）
        assert memory_increase < 10 * 1024 * 1024


class TestRiskControllerPerformance:
    """风控控制器性能测试"""

    @pytest.fixture
    def risk_controller_setup(self):
        """风控控制器设置"""
        client = MagicMock()
        client.get_depth.return_value = create_mock_depth_data()
        client.get_tickers.return_value = [{"p": "1.0000"}]
        client.get_kline.return_value = [{"c": str(1.0 + i * 0.001)} for i in range(100)]
        
        risk_params = {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        }
        
        return RiskController(client, risk_params, strategy_name="perf_test")

    def test_volatility_calculation_performance(self, benchmark_runner, risk_controller_setup):
        """测试波动率计算性能"""
        risk_controller = risk_controller_setup
        
        # 测试不同数据量的波动率计算
        data_sizes = [10, 100, 1000]
        
        for size in data_sizes:
            close_prices = [1000.0 + i * 0.1 for i in range(size)]
            
            def calculate_volatility():
                return risk_controller.calculate_volatility(close_prices)
            
            benchmark_runner.run_benchmark(
                f"volatility_calculation_{size}",
                calculate_volatility,
                iterations=100
            )
            
            # 波动率计算时间应该与数据量成线性关系
            avg_time = benchmark_runner.results[f"volatility_calculation_{size}"]["avg_time"]
            expected_threshold = 0.001 + (size * 0.000001)
            assert_performance_threshold(avg_time, expected_threshold)

    def test_risk_monitoring_performance(self, benchmark_runner, risk_controller_setup):
        """测试风险监控性能"""
        risk_controller = risk_controller_setup
        
        def risk_monitor():
            return risk_controller.risk_monitor("btc3l_usdt")
        
        benchmark_runner.run_benchmark(
            "risk_monitoring",
            risk_monitor,
            iterations=100
        )
        
        # 风险监控应该在50ms内完成
        avg_time = benchmark_runner.results["risk_monitoring"]["avg_time"]
        assert_performance_threshold(avg_time, 0.05)

    def test_mid_price_queue_performance(self, benchmark_runner, risk_controller_setup):
        """测试中间价队列性能"""
        risk_controller = risk_controller_setup
        
        def add_mid_price():
            return risk_controller.mid_price_deviation(1000.0 + time.time() % 100)
        
        benchmark_runner.run_benchmark(
            "mid_price_queue",
            add_mid_price,
            iterations=1000
        )
        
        # 中间价处理应该非常快
        avg_time = benchmark_runner.results["mid_price_queue"]["avg_time"]
        assert_performance_threshold(avg_time, 0.0001)


class TestMarketMakerPerformance:
    """市场做市器性能测试"""

    @pytest.fixture
    def market_maker_setup(self):
        """市场做市器设置"""
        client = MagicMock()
        client.get_open_orders.return_value = []
        client.batch_orders.return_value = {"success": True}
        client.batch_cancel.return_value = {"success": True}
        
        try:
            r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
            r.ping()
            r.flushdb()
        except:
            pytest.skip("Redis not available")
        
        with patch("etf.market_making.redis.Redis", return_value=r), \
             patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            
            order_manager = OrderManager(client, strategy_name="perf_test")
            market_maker = MarketMaker(order_manager)
            
            return market_maker, r

    def test_order_placement_performance(self, benchmark_runner, market_maker_setup):
        """测试订单下单性能"""
        market_maker, redis_client = market_maker_setup
        
        # 设置测试数据
        redis_client.set("netvalue_perf_test", "1.0000")
        
        config = {
            "netvalue": "netvalue_perf_test",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.1,
            "anti_pin_usdt": 1000,
            "precision": 4,
            "prec_amount": 2
        }
        
        def place_orders():
            with patch("etf.market_making.get_orderbook") as mock_orderbook:
                mock_orderbook.return_value = (
                    [{"direction": "bid", "price": 0.9999, "amount": 100,
                      "min_price": 0.9998, "max_price": 1.0000}],
                    [{"direction": "ask", "price": 1.0001, "amount": 100,
                      "min_price": 1.0000, "max_price": 1.0002}]
                )
                
                return market_maker.place_orders(config, symbol="perf_test_usdt")
        
        benchmark_runner.run_benchmark(
            "order_placement",
            place_orders,
            iterations=50
        )
        
        # 订单下单应该在100ms内完成
        avg_time = benchmark_runner.results["order_placement"]["avg_time"]
        assert_performance_threshold(avg_time, 0.1)
        
        redis_client.flushdb()

    def test_large_order_processing(self, benchmark_runner, market_maker_setup):
        """测试大订单量处理性能"""
        market_maker, redis_client = market_maker_setup
        
        # 设置大量现有订单
        large_order_list = create_mock_orders(500, "perf_test_usdt", 1.0)
        market_maker.order_manager.client.get_open_orders.return_value = large_order_list
        
        redis_client.set("netvalue_perf_test", "1.0000")
        
        config = {
            "netvalue": "netvalue_perf_test",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.1,
            "anti_pin_usdt": 1000,
            "precision": 4,
            "prec_amount": 2
        }
        
        def process_large_orders():
            with patch("etf.market_making.get_orderbook") as mock_orderbook:
                mock_orderbook.return_value = ([], [])
                return market_maker.place_orders(config, symbol="perf_test_usdt")
        
        benchmark_runner.run_benchmark(
            "large_order_processing",
            process_large_orders,
            iterations=10
        )
        
        # 大订单量处理应该在1秒内完成
        avg_time = benchmark_runner.results["large_order_processing"]["avg_time"]
        assert_performance_threshold(avg_time, 1.0)
        
        redis_client.flushdb()


class TestWashControllerPerformance:
    """洗盘控制器性能测试"""

    @pytest.fixture
    def wash_controller_setup(self):
        """洗盘控制器设置"""
        order_manager = MagicMock()
        order_manager.add_orders_batch.return_value = {"success": True}
        
        market_maker = MagicMock()
        market_maker.best_sell = 1.0001
        market_maker.best_buy = 0.9999
        
        try:
            r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
            r.ping()
            r.flushdb()
        except:
            pytest.skip("Redis not available")
        
        with patch("etf.washing.redis.Redis", return_value=r):
            wash_controller = WashController(order_manager, market_maker)
            
        return wash_controller, r

    def test_wash_trading_performance(self, benchmark_runner, wash_controller_setup):
        """测试洗盘交易性能"""
        wash_controller, redis_client = wash_controller_setup
        
        def wash_trade():
            return wash_controller.wash(
                symbol="perf_test_usdt",
                last_mid_price=1.0000,
                mid_price=1.0001,
                prec=4,
                prec_amount=2,
                interval=60
            )
        
        benchmark_runner.run_benchmark(
            "wash_trading",
            wash_trade,
            iterations=100
        )
        
        # 洗盘交易应该在10ms内完成
        avg_time = benchmark_runner.results["wash_trading"]["avg_time"]
        assert_performance_threshold(avg_time, 0.01)
        
        redis_client.flushdb()

    def test_price_calculation_performance(self, benchmark_runner, wash_controller_setup):
        """测试价格计算性能"""
        wash_controller, redis_client = wash_controller_setup
        
        redis_client.set("netvalue_perf_test", "1.0000")
        
        config = {
            "netvalue": "netvalue_perf_test",
            "bid_ask_spread": 0.01,
            "precision": 6,
            "wash": "mid_price"
        }
        
        def get_washing_price():
            return wash_controller.get_washing_price(config)
        
        benchmark_runner.run_benchmark(
            "washing_price_calculation",
            get_washing_price,
            iterations=1000
        )
        
        # 价格计算应该非常快
        avg_time = benchmark_runner.results["washing_price_calculation"]["avg_time"]
        assert_performance_threshold(avg_time, 0.001)
        
        redis_client.flushdb()


class TestSystemIntegrationPerformance:
    """系统集成性能测试"""

    def test_end_to_end_performance(self, benchmark_runner):
        """测试端到端性能"""
        try:
            r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
            r.ping()
            r.flushdb()
        except:
            pytest.skip("Redis not available")
        
        # 设置模拟组件
        mock_client = MagicMock()
        mock_client.get_depth.return_value = create_mock_depth_data()
        mock_client.get_tickers.return_value = [{"p": "1.0000"}]
        mock_client.get_kline.return_value = [{"c": "1.0000"}] * 10
        mock_client.get_open_orders.return_value = []
        mock_client.batch_orders.return_value = {"success": True}
        
        r.set("netvalue_e2e_test", "1.0000")
        
        def end_to_end_cycle():
            with patch("etf.market_making.redis.Redis", return_value=r), \
                 patch("etf.washing.redis.Redis", return_value=r), \
                 patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
                
                # 创建组件
                order_manager = OrderManager(mock_client, strategy_name="e2e_test")
                market_maker = MarketMaker(order_manager)
                risk_controller = RiskController(mock_client, {
                    "stop_loss": {"enabled": False},
                    "orderbook_threshold": [0.8, 0.6, 0.4],
                    "base_bid_volume": 100.0,
                    "base_ask_volume": 100.0,
                    "price_deviation_threshold": [0.05, 0.03, 0.01]
                })
                wash_controller = WashController(order_manager, market_maker)
                
                config = {
                    "symbol": "e2e_test_usdt",
                    "netvalue": "netvalue_e2e_test",
                    "bid_ask_spread": 0.01,
                    "anti_pin_rate": 0.1,
                    "anti_pin_usdt": 1000,
                    "precision": 4,
                    "prec_amount": 2,
                    "wash": "mid_price"
                }
                
                # 执行完整周期
                risk_controller.risk_monitor(config["symbol"])
                
                with patch("etf.market_making.get_orderbook") as mock_orderbook:
                    mock_orderbook.return_value = ([], [])
                    market_maker.place_orders(config)
                
                wash_controller.wash(
                    symbol=config["symbol"],
                    last_mid_price=1.0000,
                    mid_price=1.0000,
                    prec=config["precision"],
                    prec_amount=config["prec_amount"],
                    interval=60
                )
                
                return True
        
        benchmark_runner.run_benchmark(
            "end_to_end_cycle",
            end_to_end_cycle,
            iterations=20
        )
        
        # 完整周期应该在200ms内完成
        avg_time = benchmark_runner.results["end_to_end_cycle"]["avg_time"]
        assert_performance_threshold(avg_time, 0.2)
        
        r.flushdb()

    def test_concurrent_performance(self, benchmark_runner):
        """测试并发性能"""
        import threading
        import queue
        
        try:
            r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
            r.ping()
            r.flushdb()
        except:
            pytest.skip("Redis not available")
        
        def concurrent_operation(thread_id, results_queue):
            try:
                mock_client = MagicMock()
                mock_client.get_open_orders.return_value = []
                mock_client.batch_orders.return_value = {"success": True}
                
                r.set(f"netvalue_concurrent_{thread_id}", "1.0000")
                
                with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
                    order_manager = OrderManager(mock_client, strategy_name=f"concurrent_{thread_id}")
                
                # 执行订单操作
                orders_data = [{
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "price": 50000.0,
                    "quantity": 0.001,
                    "clientOrderId": f"concurrent_{thread_id}"
                }]
                
                start_time = time.perf_counter()
                result = order_manager.add_orders_batch(orders_data)
                end_time = time.perf_counter()
                
                results_queue.put(end_time - start_time)
                
            except Exception as e:
                results_queue.put(None)
        
        def concurrent_test():
            results_queue = queue.Queue()
            threads = []
            
            # 启动多个并发线程
            for i in range(10):
                thread = threading.Thread(
                    target=concurrent_operation,
                    args=(i, results_queue)
                )
                threads.append(thread)
                thread.start()
            
            # 等待所有线程完成
            for thread in threads:
                thread.join()
            
            # 收集结果
            times = []
            while not results_queue.empty():
                result = results_queue.get()
                if result is not None:
                    times.append(result)
            
            return len(times) == 10  # 所有线程都成功完成
        
        benchmark_runner.run_benchmark(
            "concurrent_operations",
            concurrent_test,
            iterations=5
        )
        
        # 并发操作应该在合理时间内完成
        avg_time = benchmark_runner.results["concurrent_operations"]["avg_time"]
        assert_performance_threshold(avg_time, 2.0)  # 2秒内完成所有并发操作
        
        r.flushdb()


def test_performance_report(benchmark_runner):
    """生成性能报告"""
    # 运行一些基本基准测试以生成报告
    def simple_operation():
        return sum(range(1000))
    
    benchmark_runner.run_benchmark("simple_sum", simple_operation, iterations=1000)
    
    # 打印性能报告
    print("\n" + "="*60)
    print("ETF系统性能基准测试报告")
    print("="*60)
    
    if benchmark_runner.results:
        for name, stats in benchmark_runner.results.items():
            print(f"\n{name}:")
            print(f"  平均时间: {stats['avg_time']*1000:.3f}ms")
            print(f"  最小时间: {stats['min_time']*1000:.3f}ms")
            print(f"  最大时间: {stats['max_time']*1000:.3f}ms")
            print(f"  总时间:   {stats['total_time']*1000:.3f}ms")
            print(f"  迭代次数: {stats['iterations']}")
    else:
        print("暂无性能数据")
    
    print("="*60)


if __name__ == "__main__":
    # 运行性能测试
    pytest.main([__file__, "-v", "-s"])