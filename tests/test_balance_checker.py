"""
资金检查器单元测试

测试功能:
1. 资金状态判断（充足/警告/危急/不足）
2. 告警逻辑
3. 策略停止建议
4. 配置参数验证
"""

import pytest
from unittest.mock import Mock, MagicMock
from etf.balance_checker import BalanceChecker, BalanceStatus


class TestBalanceChecker:
    """资金检查器测试"""
    
    @pytest.fixture
    def checker(self):
        """创建测试用的资金检查器"""
        return BalanceChecker(
            strategy_name="test_strategy",
            warning_threshold=0.3,
            critical_threshold=0.2,
            insufficient_threshold=0.1,
        )
    
    def test_init(self, checker):
        """测试初始化"""
        assert checker.strategy_name == "test_strategy"
        assert checker.warning_threshold == 0.3
        assert checker.critical_threshold == 0.2
        assert checker.insufficient_threshold == 0.1
        assert checker.last_status == BalanceStatus.SUFFICIENT
    
    def test_sufficient_balance(self, checker):
        """测试资金充足情况"""
        # 可用余额60%，应该是充足状态
        status, message = checker.check_balance(
            available_balance=6000.0,
            total_balance=10000.0,
            pending_order_value=0.0,
        )
        
        assert status == BalanceStatus.SUFFICIENT
        assert "SUFFICIENT" in message
        assert not checker.should_stop_strategy(status)
    
    def test_warning_balance(self, checker):
        """测试资金警告情况"""
        # 可用余额25%，应该是警告状态
        status, message = checker.check_balance(
            available_balance=2500.0,
            total_balance=10000.0,
            pending_order_value=0.0,
        )
        
        assert status == BalanceStatus.WARNING
        assert "WARNING" in message
        assert "建议" in message
        assert not checker.should_stop_strategy(status)
    
    def test_critical_balance(self, checker):
        """测试资金危急情况"""
        # 可用余额15%，应该是危急状态
        status, message = checker.check_balance(
            available_balance=1500.0,
            total_balance=10000.0,
            pending_order_value=0.0,
        )
        
        assert status == BalanceStatus.CRITICAL
        assert "CRITICAL" in message
        assert "建议" in message
        assert not checker.should_stop_strategy(status)
    
    def test_insufficient_balance(self, checker):
        """测试资金不足情况"""
        # 可用余额5%，应该是不足状态
        status, message = checker.check_balance(
            available_balance=500.0,
            total_balance=10000.0,
            pending_order_value=0.0,
        )
        
        assert status == BalanceStatus.INSUFFICIENT
        assert "INSUFFICIENT" in message
        assert "停止策略" in message
        assert checker.should_stop_strategy(status)
    
    def test_insufficient_balance_below_min_order(self, checker):
        """测试余额低于最小订单金额"""
        # 可用余额低于最小订单金额，应该是不足状态
        status, message = checker.check_balance(
            available_balance=1.0,  # 低于最小订单1.2 USDT
            total_balance=100.0,
            pending_order_value=0.0,
        )
        
        assert status == BalanceStatus.INSUFFICIENT
        assert checker.should_stop_strategy(status)
    
    def test_pending_orders_deduction(self, checker):
        """测试挂单占用金额扣除"""
        # 总余额10000，可用6000，挂单3000
        # 实际可用 = 6000 - 3000 = 3000 (30%)
        status, message = checker.check_balance(
            available_balance=6000.0,
            total_balance=10000.0,
            pending_order_value=3000.0,
        )
        
        # 实际可用30%，应该等于警告阈值边界
        assert status == BalanceStatus.WARNING
        assert "挂单占用: 3000.00" in message
        assert "实际可用: 3000.00" in message
    
    def test_calculate_pending_order_value(self, checker):
        """测试计算挂单占用金额"""
        # 模拟挂单数据
        open_orders = {
            "order1": {
                "symbol": "TON3L_USDT",
                "side": "BUY",
                "origQty": 100,
                "price": 5.0,
            },
            "order2": {
                "symbol": "TON3L_USDT",
                "side": "BUY",
                "origQty": 50,
                "price": 4.8,
            },
            "order3": {
                "symbol": "TON3L_USDT",
                "side": "SELL",
                "origQty": 80,
                "price": 5.2,
            },
        }
        
        pending_value = checker.calculate_pending_order_value(
            open_orders, "TON3L_USDT"
        )
        
        # 只计算买单：100*5.0 + 50*4.8 = 500 + 240 = 740
        assert pending_value == 740.0
    
    def test_get_balance_info(self, checker):
        """测试获取余额信息"""
        # 模拟客户端
        mock_client = Mock()
        mock_client.balances.return_value = {
            "assets": [
                {
                    "currency": "usdt",
                    "totalAmount": "10000.50",
                    "availableAmount": "6000.25",
                    "frozenAmount": "4000.25",
                }
            ]
        }
        
        balance_info = checker.get_balance_info(mock_client, "usdt")
        
        assert balance_info["balance"] == 10000.50
        assert balance_info["available"] == 6000.25
        assert balance_info["frozen"] == 4000.25
    
    def test_get_balance_info_not_found(self, checker):
        """测试获取不存在的币种余额"""
        mock_client = Mock()
        mock_client.balances.return_value = {
            "assets": [
                {
                    "currency": "btc",
                    "totalAmount": "1.0",
                    "availableAmount": "1.0",
                    "frozenAmount": "0.0",
                }
            ]
        }
        
        balance_info = checker.get_balance_info(mock_client, "usdt")
        
        # 未找到应返回0
        assert balance_info["balance"] == 0.0
        assert balance_info["available"] == 0.0
        assert balance_info["frozen"] == 0.0
    
    def test_state_change_tracking(self, checker):
        """测试状态变化跟踪"""
        # 第一次检查：充足
        status1, _ = checker.check_balance(6000.0, 10000.0, 0.0)
        assert status1 == BalanceStatus.SUFFICIENT
        assert checker.last_status == BalanceStatus.SUFFICIENT
        
        # 第二次检查：警告
        status2, _ = checker.check_balance(2500.0, 10000.0, 0.0)
        assert status2 == BalanceStatus.WARNING
        assert checker.last_status == BalanceStatus.WARNING
        assert checker.warning_count == 1
        
        # 第三次检查：危急
        status3, _ = checker.check_balance(1500.0, 10000.0, 0.0)
        assert status3 == BalanceStatus.CRITICAL
        assert checker.last_status == BalanceStatus.CRITICAL
        assert checker.critical_count == 1
        
        # 第四次检查：不足
        status4, _ = checker.check_balance(500.0, 10000.0, 0.0)
        assert status4 == BalanceStatus.INSUFFICIENT
        assert checker.last_status == BalanceStatus.INSUFFICIENT
    
    def test_custom_thresholds(self):
        """测试自定义阈值"""
        checker = BalanceChecker(
            strategy_name="custom",
            warning_threshold=0.5,  # 50%
            critical_threshold=0.3,  # 30%
            insufficient_threshold=0.2,  # 20%
        )
        
        # 40%可用应该是警告
        status, _ = checker.check_balance(4000.0, 10000.0, 0.0)
        assert status == BalanceStatus.WARNING
        
        # 25%可用应该是危急
        status, _ = checker.check_balance(2500.0, 10000.0, 0.0)
        assert status == BalanceStatus.CRITICAL
        
        # 15%可用应该是不足
        status, _ = checker.check_balance(1500.0, 10000.0, 0.0)
        assert status == BalanceStatus.INSUFFICIENT


class TestBalanceCheckerIntegration:
    """集成测试"""
    
    def test_real_scenario_gradual_depletion(self):
        """测试真实场景：资金逐渐耗尽"""
        checker = BalanceChecker("scenario_test")
        
        # 初始资金充足
        status, _ = checker.check_balance(8000.0, 10000.0, 0.0)
        assert status == BalanceStatus.SUFFICIENT
        
        # 资金减少到警告线
        status, _ = checker.check_balance(2800.0, 10000.0, 0.0)
        assert status == BalanceStatus.WARNING
        
        # 资金继续减少到危急线
        status, _ = checker.check_balance(1800.0, 10000.0, 0.0)
        assert status == BalanceStatus.CRITICAL
        
        # 资金耗尽到不足
        status, msg = checker.check_balance(800.0, 10000.0, 0.0)
        assert status == BalanceStatus.INSUFFICIENT
        assert checker.should_stop_strategy(status)
    
    def test_real_scenario_with_pending_orders(self):
        """测试真实场景：考虑挂单占用"""
        checker = BalanceChecker("pending_test")
        
        # 可用6000，但挂单占用3500，实际可用2500 (25%)
        status, msg = checker.check_balance(
            available_balance=6000.0,
            total_balance=10000.0,
            pending_order_value=3500.0,
        )
        
        # 应该是警告状态
        assert status == BalanceStatus.WARNING
        assert "挂单占用: 3500.00" in msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
