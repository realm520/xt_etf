"""
K线自然化改进测试

测试内容：
1. 盘口不对称机制：买一卖一距离净值的偏移
2. K线价格分散：同一分钟内的洗盘价格在区间内错落分布
"""

import pytest
import time
from unittest.mock import MagicMock
from decimal import Decimal

# 测试盘口不对称机制
class TestOrderbookAsymmetry:
    """测试盘口不对称机制"""
    
    def test_asymmetry_bias_initialization(self):
        """测试不对称偏移初始化"""
        from etf.orderbook.layered import LayeredOrderbookAlgorithm, LayeredOrderbookConfig, LayerConfig
        
        near = LayerConfig(distance_threshold=0.005, layer_count=20, budget_ratio=0.6)
        trans = LayerConfig(distance_range=(0.005, 0.02), layer_count=30, budget_ratio=0.3)
        far = LayerConfig(distance_range=(0.02, 0.05), layer_count=50, budget_ratio=0.1)

        config = LayeredOrderbookConfig(
            total_budget=10000,
            layer=100,
            mid_price=1.0,
            bid_ask_spread=0.008,
            symbol='TEST',
            price_precision=6,
            quantity_precision=2,
            near_book=near,
            transition_zone=trans,
            far_book=far
        )

        algo = LayeredOrderbookAlgorithm(config)
        
        # 检查初始值
        assert algo.asymmetry_bias == 0.0
        assert algo.last_bias_update == 0.0
        assert algo.bias_update_interval == 60.0
    
    def test_asymmetry_bias_update(self):
        """测试不对称偏移更新"""
        from etf.orderbook.layered import LayeredOrderbookAlgorithm, LayeredOrderbookConfig, LayerConfig
        
        near = LayerConfig(distance_threshold=0.005, layer_count=20, budget_ratio=0.6)
        trans = LayerConfig(distance_range=(0.005, 0.02), layer_count=30, budget_ratio=0.3)
        far = LayerConfig(distance_range=(0.02, 0.05), layer_count=50, budget_ratio=0.1)

        config = LayeredOrderbookConfig(
            total_budget=10000,
            layer=100,
            mid_price=1.0,
            bid_ask_spread=0.008,
            symbol='TEST',
            price_precision=6,
            quantity_precision=2,
            near_book=near,
            transition_zone=trans,
            far_book=far
        )

        algo = LayeredOrderbookAlgorithm(config)
        
        # 生成近盘口订单（会触发偏移更新）
        bids, asks = algo.generate_layer_orders('near_book', 1.0)
        
        # 偏移应该已更新
        assert algo.last_bias_update > 0
        assert -0.5 <= algo.asymmetry_bias <= 0.5
    
    def test_asymmetry_creates_different_spreads(self):
        """测试不对称偏移创建不同的买卖价差"""
        from etf.orderbook.layered import LayeredOrderbookAlgorithm, LayeredOrderbookConfig, LayerConfig
        
        near = LayerConfig(distance_threshold=0.005, layer_count=20, budget_ratio=0.6)
        trans = LayerConfig(distance_range=(0.005, 0.02), layer_count=30, budget_ratio=0.3)
        far = LayerConfig(distance_range=(0.02, 0.05), layer_count=50, budget_ratio=0.1)

        config = LayeredOrderbookConfig(
            total_budget=10000,
            layer=100,
            mid_price=1.0,
            bid_ask_spread=0.008,
            symbol='TEST',
            price_precision=6,
            quantity_precision=2,
            near_book=near,
            transition_zone=trans,
            far_book=far
        )

        algo = LayeredOrderbookAlgorithm(config)
        netvalue = 1.0
        
        # 收集多次生成的价差
        spreads = []
        for _ in range(5):
            # 强制更新偏移
            algo.last_bias_update = 0
            bids, asks = algo.generate_layer_orders('near_book', netvalue)
            
            best_bid = float(bids[0].price)
            best_ask = float(asks[0].price)
            
            bid_distance = netvalue - best_bid
            ask_distance = best_ask - netvalue
            
            spreads.append({
                'bid_distance': bid_distance,
                'ask_distance': ask_distance,
                'bias': algo.asymmetry_bias
            })
        
        # 应该有不同的偏移值
        biases = [s['bias'] for s in spreads]
        assert len(set([round(b, 2) for b in biases])) > 1, "偏移值应该有变化"


class TestKlinePriceDispersion:
    """测试K线价格分散机制"""
    
    def setup_method(self):
        """每个测试前初始化"""
        self.order_manager = MagicMock()
        self.market_maker = MagicMock()
        self.market_maker.best_sell = 1.002
        self.market_maker.best_buy = 0.998
    
    def test_kline_pattern_variety(self):
        """测试K线形态多样性"""
        from etf.washing import WashController
        
        controller = WashController(self.order_manager, self.market_maker)
        
        config = {
            'wash_pairs_count': 3,
        }
        
        safe_min = 0.9981
        safe_max = 1.0019
        full_range = safe_max - safe_min
        
        # 收集多次洗盘的波动幅度
        spreads = []
        for _ in range(20):
            trades = controller.generate_micro_trades(
                buy_price=safe_min,
                sell_price=safe_max,
                total_amount=100,
                prec=6,
                prec_amount=2,
                config=config
            )
            
            prices = [t['price'] for t in trades if t.get('is_pair_start', True)]
            spread = max(prices) - min(prices)
            spread_ratio = spread / full_range
            spreads.append(spread_ratio)
        
        # 波动幅度应该有多样性（不都是接近100%）
        small_spreads = [s for s in spreads if s < 0.3]  # 小于30%的
        large_spreads = [s for s in spreads if s > 0.5]  # 大于50%的
        
        assert len(small_spreads) > 0, "应该有窄幅波动的K线"
        assert len(spreads) - len(small_spreads) - len(large_spreads) > 0 or len(large_spreads) > 0, "应该有中等或宽幅波动"
    
    def test_price_not_always_at_boundary(self):
        """测试价格不总是贴近边界"""
        from etf.washing import WashController
        
        controller = WashController(self.order_manager, self.market_maker)
        
        config = {
            'wash_pairs_count': 3,
        }
        
        safe_min = 0.9981
        safe_max = 1.0019
        full_range = safe_max - safe_min
        
        # 收集多次洗盘的边界距离
        boundary_distances = []
        for _ in range(20):
            trades = controller.generate_micro_trades(
                buy_price=safe_min,
                sell_price=safe_max,
                total_amount=100,
                prec=6,
                prec_amount=2,
                config=config
            )
            
            prices = [t['price'] for t in trades if t.get('is_pair_start', True)]
            high = max(prices)
            low = min(prices)
            
            # 计算距离边界的最小距离
            dist_to_top = safe_max - high
            dist_to_bottom = low - safe_min
            min_dist = min(dist_to_top, dist_to_bottom)
            boundary_distances.append(min_dist / full_range)
        
        # 应该有一些情况距离边界较远（>20%的区间宽度）
        far_from_boundary = [d for d in boundary_distances if d > 0.15]
        assert len(far_from_boundary) >= 5, f"至少25%的情况应该远离边界，实际只有{len(far_from_boundary)}次"
    
    def test_pattern_distribution(self):
        """测试K线形态分布"""
        from etf.washing import WashController
        
        controller = WashController(self.order_manager, self.market_maker)
        
        config = {
            'wash_pairs_count': 3,
        }
        
        safe_min = 0.9981
        safe_max = 1.0019
        mid_price = (safe_min + safe_max) / 2
        
        # 收集价格中心位置
        centers = []
        for _ in range(30):
            trades = controller.generate_micro_trades(
                buy_price=safe_min,
                sell_price=safe_max,
                total_amount=100,
                prec=6,
                prec_amount=2,
                config=config
            )
            
            prices = [t['price'] for t in trades if t.get('is_pair_start', True)]
            avg_price = sum(prices) / len(prices)
            center_position = (avg_price - safe_min) / (safe_max - safe_min)
            centers.append(center_position)
        
        # 应该有高位、中位、低位的分布
        low_positions = [c for c in centers if c < 0.35]
        mid_positions = [c for c in centers if 0.35 <= c <= 0.65]
        high_positions = [c for c in centers if c > 0.65]
        
        # 各种位置都应该出现
        assert len(low_positions) > 0, "应该有低位K线"
        assert len(mid_positions) > 0, "应该有中位K线"
        assert len(high_positions) > 0, "应该有高位K线"


class TestKlineNaturalEffect:
    """测试K线自然化整体效果"""
    
    def test_price_range_utilization(self):
        """测试价格区间利用率"""
        from etf.washing import WashController
        from unittest.mock import MagicMock
        
        order_manager = MagicMock()
        market_maker = MagicMock()
        market_maker.best_sell = 1.002
        market_maker.best_buy = 0.998
        
        controller = WashController(order_manager, market_maker)
        
        config = {
            'wash_pairs_count': 3,
            'kline_price_volatility': 0.001
        }
        
        safe_min = 0.9981
        safe_max = 1.0019
        available_range = safe_max - safe_min
        
        # 收集所有价格
        all_prices = []
        for _ in range(10):
            trades = controller.generate_micro_trades(
                buy_price=safe_min,
                sell_price=safe_max,
                total_amount=100,
                prec=6,
                prec_amount=2,
                config=config
            )
            prices = [t['price'] for t in trades if t.get('is_pair_start', True)]
            all_prices.extend(prices)
        
        actual_range = max(all_prices) - min(all_prices)
        utilization = actual_range / available_range
        
        # 区间利用率应该超过50%
        assert utilization > 0.5, f"区间利用率({utilization:.2%})应超过50%"
        
        # 所有价格都在安全区间内
        assert all(safe_min <= p <= safe_max for p in all_prices), "所有价格应在安全区间内"
