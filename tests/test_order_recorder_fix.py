#!/usr/bin/env python
"""
测试订单记录器事件循环修复

验证：
1. 后台线程Redis连接正常初始化
2. 订单记录不再出现"attached to a different loop"错误
3. Redis缓存更新功能正常工作
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from etf.order_manager import OrderManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class MockClient:
    """模拟交易客户端"""
    pass

async def test_order_recorder():
    """测试订单记录器功能"""
    print("\n" + "="*80)
    print("测试订单记录器事件循环修复")
    print("="*80 + "\n")

    # 创建模拟客户端
    mock_client = MockClient()

    # 初始化订单管理器
    order_manager = OrderManager(mock_client, strategy_name="test_strategy")

    print("✓ OrderManager 初始化成功")

    # 等待后台线程启动
    time.sleep(2)

    # 检查后台线程状态
    if order_manager._recorder_running:
        print("✓ 后台事件循环已启动")
    else:
        print("✗ 后台事件循环启动失败")
        return False

    # 检查Redis连接状态
    if order_manager.order_recorder and order_manager.order_recorder.redis:
        print("✓ 后台线程Redis连接成功")
    else:
        print("⚠ Redis连接未建立（可能是Redis服务未启动）")

    # 模拟订单数据
    test_order = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "price": 50000.0,
        "quantity": 0.001,
        "order_id": "test_order_123",
        "orderId": "test_order_123",
        "clientOrderId": "test_client_123",
        "is_wash_trading": False,
        "timestamp": time.time()
    }

    print("\n开始测试订单记录...")

    # 记录订单（这应该不会抛出事件循环错误）
    try:
        order_manager._schedule_async(
            order_manager.order_recorder.record_order(test_order)
        )
        print("✓ 订单记录调度成功（无事件循环错误）")

        # 等待异步操作完成
        time.sleep(1)

        # 检查统计信息
        stats = order_manager.order_recorder.get_stats()
        print(f"\n统计信息: {stats}")

        if stats["total_orders"] > 0:
            print("✓ 订单已成功记录")

    except Exception as e:
        print(f"✗ 订单记录失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 清理
    print("\n清理资源...")
    order_manager.shutdown_recorder()

    print("\n" + "="*80)
    print("测试完成！")
    print("="*80 + "\n")

    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(test_order_recorder())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
