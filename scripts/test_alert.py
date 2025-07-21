#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试告警功能
"""

import asyncio
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.alert import send_direct_alert, send_alert, AlertLevel


async def test_alerts():
    """测试各种告警"""
    
    # 测试直接告警
    print("1. 测试信息级别告警...")
    success = await send_direct_alert(
        title="测试告警系统",
        content="这是一条测试消息，用于验证 Lark 告警功能是否正常工作。",
        level=AlertLevel.INFO,
        strategy_name="test",
        details={
            "test_type": "direct_alert",
            "timestamp": "2024-01-09"
        }
    )
    print(f"   结果: {'成功' if success else '失败'}")
    
    # 测试警告级别
    print("\n2. 测试警告级别告警...")
    success = await send_alert(
        "api_error",
        {
            "error_type": "TestError",
            "error_message": "这是一个模拟的 API 错误",
            "symbol": "btc_usdt",
            "operation": "test"
        },
        strategy_name="test"
    )
    print(f"   结果: {'成功' if success else '失败'}")
    
    # 测试错误级别
    print("\n3. 测试错误级别告警...")
    success = await send_alert(
        "net_value_spike",
        {
            "net_value_change_rate": 0.08,  # 8% 变化
            "symbol": "stg_usdt",
            "old_net_value": 1.0,
            "new_net_value": 1.08,
            "leverage": 3,
            "direction": "做多"
        },
        strategy_name="stg3l"
    )
    print(f"   结果: {'成功' if success else '失败'}")
    
    # 测试严重级别
    print("\n4. 测试严重级别告警...")
    success = await send_alert(
        "stop_loss_triggered",
        {
            "event_type": "stop_loss",
            "symbol": "stg_usdt",
            "loss_rate": -0.05,
            "position": 10000,
            "action": "close_position"
        },
        strategy_name="stg5l"
    )
    print(f"   结果: {'成功' if success else '失败'}")
    
    # 测试聚合告警
    print("\n5. 测试聚合告警（发送多条相同类型）...")
    for i in range(5):
        await send_alert(
            "api_error",
            {
                "error_type": "XtHttpError",
                "error_message": f"连接超时 #{i+1}",
                "symbol": "stg_usdt",
                "operation": "get_depth"
            },
            strategy_name="test"
        )
        await asyncio.sleep(1)
    print("   聚合告警测试完成")
    
    print("\n测试完成！请检查 Lark 是否收到相应的告警消息。")


def main():
    """主函数"""
    # 检查环境变量
    if not os.getenv("LARK_WEBHOOK_URL"):
        print("错误: 请设置环境变量 LARK_WEBHOOK_URL")
        print("示例: export LARK_WEBHOOK_URL='https://open.larksuite.com/open-apis/bot/v2/hook/xxx'")
        return
        
    # 运行测试
    asyncio.run(test_alerts())


if __name__ == "__main__":
    main()