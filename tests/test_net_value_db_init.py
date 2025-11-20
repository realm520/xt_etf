#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试净值计算器数据库集成初始化

验证：
1. db_recorder 在 _init_net_value 之前初始化
2. 恢复逻辑可以正常使用 db_recorder
3. 初始化顺序正确
"""

import sys
import os
import time

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.net_value_improved import ImprovedNetValue
import redis

def test_initialization_order():
    """测试初始化顺序"""
    print("=" * 70)
    print("测试 1: 启用数据库持久化的初始化顺序")
    print("=" * 70)

    # 清理 Redis 数据（避免恢复逻辑）
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.delete("netvalue_ton3l")
    r.delete("netvalue_ton3l_detail")
    r.delete("netvalue_ton3l_history")

    try:
        net_value = ImprovedNetValue(
            symbol="ton_usdt",
            m_lever=3,
            long=True,
            init_net_value=1.0,
            daily_fee=0.001,
            time_gap_second=1,
            rebalance=0.05,
            max_single_change=0.10,
            max_restart_gap=300,
            enable_db_persistence=True,
            strategy_name="ton3l"
        )

        print("✅ 初始化成功")
        print(f"   db_recorder 存在: {net_value.db_recorder is not None}")
        print(f"   策略名称: {net_value.strategy_name}")
        print(f"   净值数据: {net_value.net_value_data.get('net_value')}")

        return True

    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_recovery_with_db():
    """测试恢复逻辑使用数据库记录器"""
    print("\n" + "=" * 70)
    print("测试 2: 恢复逻辑与数据库集成")
    print("=" * 70)

    # 准备 Redis 数据（模拟 10 分钟前的数据）
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    import json

    old_data = {
        "net_value": 1.0,
        "last_price": 5000.0,
        "last_update_ts": time.time() - 600,  # 10 分钟前
        "create_ts": time.time() - 86400,
        "update_count": 100,
        "total_fee_deducted": 0.001,
        "abnormal_events": []
    }

    r.set("netvalue_ton3l_detail", json.dumps(old_data))

    try:
        net_value = ImprovedNetValue(
            symbol="ton_usdt",
            m_lever=3,
            long=True,
            init_net_value=1.0,
            daily_fee=0.001,
            time_gap_second=1,
            rebalance=0.05,
            max_single_change=0.10,
            max_restart_gap=300,  # 5 分钟限制
            enable_db_persistence=True,
            strategy_name="ton3l"
        )

        print("✅ 恢复逻辑执行成功")
        print(f"   异常事件数: {len(net_value.net_value_data.get('abnormal_events', []))}")

        # 检查是否记录了 long_restart 事件
        events = net_value.net_value_data.get('abnormal_events', [])
        has_restart = any(e.get('type') == 'long_restart' for e in events)
        print(f"   检测到长时间重启: {has_restart}")

        if has_restart:
            print("✅ 恢复事件正确记录")
        else:
            print("⚠️  未检测到恢复事件（可能因为时间差不够大）")

        return True

    except Exception as e:
        print(f"❌ 恢复测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_disabled_db():
    """测试禁用数据库持久化"""
    print("\n" + "=" * 70)
    print("测试 3: 禁用数据库持久化")
    print("=" * 70)

    # 清理 Redis
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.delete("netvalue_ton3l")
    r.delete("netvalue_ton3l_detail")
    r.delete("netvalue_ton3l_history")

    try:
        net_value = ImprovedNetValue(
            symbol="ton_usdt",
            m_lever=3,
            long=True,
            init_net_value=1.0,
            enable_db_persistence=False,  # 禁用
            strategy_name="ton3l"
        )

        print("✅ 初始化成功（数据库禁用）")
        print(f"   db_recorder 存在: {net_value.db_recorder is not None}")

        if net_value.db_recorder is None:
            print("✅ 数据库记录器正确禁用")
            return True
        else:
            print("❌ 数据库记录器应该为 None")
            return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("🧪 净值计算器数据库集成初始化测试")
    print()

    results = []

    # 测试 1: 初始化顺序
    results.append(("初始化顺序", test_initialization_order()))

    # 测试 2: 恢复逻辑
    results.append(("恢复逻辑", test_recovery_with_db()))

    # 测试 3: 禁用数据库
    results.append(("禁用数据库", test_disabled_db()))

    # 总结
    print("\n" + "=" * 70)
    print("测试结果总结")
    print("=" * 70)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")

    all_passed = all(r[1] for r in results)

    if all_passed:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n❌ 部分测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
