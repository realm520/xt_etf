#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
净值数据库持久化端到端测试

验证完整的数据流程：
1. ImprovedNetValue 初始化（启用数据库）
2. 计算净值更新
3. 数据同时写入 Redis 和 PostgreSQL
4. 验证数据一致性
5. 清理测试数据
"""

import sys
import os
import time
import asyncio
from datetime import datetime, timedelta

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from etf.net_value_improved import ImprovedNetValue
from etf.storage.models import NetValueHistory, NetValueEvent
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def get_db_connection():
    """获取数据库连接"""
    db_url = (
        f"postgresql://{os.getenv('POSTGRES_USER', 'xtetf')}:"
        f"{os.getenv('POSTGRES_PASSWORD', '12345678')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'xtetf')}"
    )
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    return engine, Session


def cleanup_test_data(strategy_name="test_ton3l"):
    """清理测试数据"""
    print("🧹 清理测试数据...")
    
    # 清理 Redis
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.delete(f"netvalue_{strategy_name}")
    r.delete(f"netvalue_{strategy_name}_detail")
    r.delete(f"netvalue_{strategy_name}_history")
    
    # 清理 PostgreSQL
    try:
        engine, Session = get_db_connection()
        with Session() as session:
            # 删除测试策略的所有记录
            session.execute(
                text("DELETE FROM net_value_history WHERE strategy_name = :name"),
                {"name": strategy_name}
            )
            session.execute(
                text("DELETE FROM net_value_events WHERE strategy_name = :name"),
                {"name": strategy_name}
            )
            session.commit()
            print("   ✅ PostgreSQL 测试数据已清理")
    except Exception as e:
        print(f"   ⚠️  PostgreSQL 清理失败: {e}")
    
    print("   ✅ Redis 测试数据已清理")


def test_basic_initialization():
    """测试 1: 基础初始化"""
    print("\n" + "=" * 70)
    print("测试 1: 基础初始化（启用数据库持久化）")
    print("=" * 70)
    
    cleanup_test_data()
    
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
            strategy_name="test_ton3l"
        )
        
        print("✅ 初始化成功")
        print(f"   策略名称: {net_value.strategy_name}")
        print(f"   db_recorder: {net_value.db_recorder is not None}")
        print(f"   初始净值: {net_value.net_value_data.get('net_value')}")
        
        return True, net_value
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False, None


def test_net_value_calculation(net_value):
    """测试 2: 净值计算和数据写入"""
    print("\n" + "=" * 70)
    print("测试 2: 净值计算和数据写入")
    print("=" * 70)
    
    if not net_value:
        print("❌ 跳过测试（初始化失败）")
        return False
    
    try:
        # 模拟价格更新
        prices = [5000.0, 5010.0, 5005.0, 5015.0, 5020.0]
        
        print(f"📊 模拟 {len(prices)} 次价格更新...")
        for i, price in enumerate(prices):
            new_value = net_value.cal_net_value(price)
            print(f"   更新 {i+1}: 价格={price}, 净值={new_value:.8f}")
            time.sleep(0.5)  # 等待异步写入完成
        
        # 等待批量写入完成
        print("⏳ 等待 3 秒让批量写入完成...")
        time.sleep(3)
        
        print("✅ 净值计算完成")
        return True
    except Exception as e:
        print(f"❌ 净值计算失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_redis_data(strategy_name="test_ton3l"):
    """测试 3: 验证 Redis 数据"""
    print("\n" + "=" * 70)
    print("测试 3: 验证 Redis 数据")
    print("=" * 70)
    
    try:
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        
        # 检查简单净值
        net_value = r.get(f"netvalue_{strategy_name}")
        print(f"   简单净值: {net_value}")
        
        # 检查详细数据
        detail_data = r.get(f"netvalue_{strategy_name}_detail")
        if detail_data:
            import json
            detail = json.loads(detail_data)
            print(f"   详细数据: 净值={detail.get('net_value')}, 更新次数={detail.get('update_count')}")
        
        # 检查历史记录
        history_count = r.llen(f"netvalue_{strategy_name}_history")
        print(f"   历史记录数: {history_count}")
        
        if net_value and detail_data and history_count > 0:
            print("✅ Redis 数据验证通过")
            return True
        else:
            print("❌ Redis 数据不完整")
            return False
    except Exception as e:
        print(f"❌ Redis 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_postgresql_data(strategy_name="test_ton3l"):
    """测试 4: 验证 PostgreSQL 数据"""
    print("\n" + "=" * 70)
    print("测试 4: 验证 PostgreSQL 数据")
    print("=" * 70)
    
    try:
        engine, Session = get_db_connection()
        
        with Session() as session:
            # 查询净值历史记录
            history_result = session.execute(
                select(NetValueHistory)
                .where(NetValueHistory.strategy_name == strategy_name)
                .order_by(NetValueHistory.recorded_at.desc())
            )
            history_records = history_result.scalars().all()
            
            print(f"   净值历史记录数: {len(history_records)}")
            
            if history_records:
                latest = history_records[0]
                print(f"   最新记录:")
                print(f"      策略: {latest.strategy_name}")
                print(f"      净值: {latest.net_value}")
                print(f"      时间: {latest.recorded_at}")
                print(f"      累计手续费: {latest.cumulative_fee}")
            
            # 查询异常事件
            events_result = session.execute(
                select(NetValueEvent)
                .where(NetValueEvent.strategy_name == strategy_name)
                .order_by(NetValueEvent.event_time.desc())
            )
            event_records = events_result.scalars().all()
            
            print(f"   异常事件记录数: {len(event_records)}")
            
            if event_records:
                for event in event_records:
                    print(f"      事件: {event.event_type}, 时间: {event.event_time}")
            
            if len(history_records) >= 5:  # 至少应该有 5 条记录
                print("✅ PostgreSQL 数据验证通过")
                return True
            else:
                print(f"⚠️  PostgreSQL 记录数不足 (期望 >= 5, 实际 {len(history_records)})")
                print("   可能是批量写入还在处理中，等待更长时间...")
                return False
    except Exception as e:
        print(f"❌ PostgreSQL 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_data_consistency(strategy_name="test_ton3l"):
    """测试 5: 数据一致性验证"""
    print("\n" + "=" * 70)
    print("测试 5: Redis 与 PostgreSQL 数据一致性")
    print("=" * 70)
    
    try:
        # 从 Redis 获取最新净值
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        redis_value = float(r.get(f"netvalue_{strategy_name}") or 0)
        
        # 从 PostgreSQL 获取最新净值
        engine, Session = get_db_connection()
        with Session() as session:
            result = session.execute(
                select(NetValueHistory.net_value)
                .where(NetValueHistory.strategy_name == strategy_name)
                .order_by(NetValueHistory.recorded_at.desc())
                .limit(1)
            )
            db_value = result.scalar() or 0
            db_value = float(db_value)
        
        print(f"   Redis 净值: {redis_value:.8f}")
        print(f"   PostgreSQL 净值: {db_value:.8f}")
        print(f"   差异: {abs(redis_value - db_value):.8f}")
        
        # 允许小的浮点数差异
        if abs(redis_value - db_value) < 0.00001:
            print("✅ 数据一致性验证通过")
            return True
        else:
            print("⚠️  数据不一致（可能是批量写入延迟）")
            return False
    except Exception as e:
        print(f"❌ 一致性验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_event_recording():
    """测试 6: 异常事件记录"""
    print("\n" + "=" * 70)
    print("测试 6: 异常事件记录（长时间重启）")
    print("=" * 70)
    
    strategy_name = "test_event_ton3l"
    cleanup_test_data(strategy_name)
    
    try:
        # 准备旧的 Redis 数据（模拟 10 分钟前）
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
        
        r.set(f"netvalue_{strategy_name}_detail", json.dumps(old_data))
        
        # 创建 ImprovedNetValue 实例（应该触发恢复逻辑）
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
            strategy_name=strategy_name
        )
        
        # 等待事件写入
        time.sleep(2)
        
        # 检查 Redis 中的异常事件
        detail_data = r.get(f"netvalue_{strategy_name}_detail")
        if detail_data:
            detail = json.loads(detail_data)
            events = detail.get('abnormal_events', [])
            has_restart = any(e.get('type') == 'long_restart' for e in events)
            print(f"   Redis 异常事件数: {len(events)}")
            print(f"   检测到长时间重启: {has_restart}")
        
        # 检查 PostgreSQL 中的事件记录
        time.sleep(3)  # 等待批量写入
        
        engine, Session = get_db_connection()
        with Session() as session:
            result = session.execute(
                select(NetValueEvent)
                .where(NetValueEvent.strategy_name == strategy_name)
                .where(NetValueEvent.event_type == 'long_restart')
            )
            events = result.scalars().all()
            
            print(f"   PostgreSQL 事件记录数: {len(events)}")
            
            if events:
                event = events[0]
                print(f"      事件类型: {event.event_type}")
                print(f"      严重程度: {event.severity}")
                print(f"      时间间隔: {event.gap_seconds}秒")
                print("✅ 异常事件记录验证通过")
                
                # 清理测试数据
                cleanup_test_data(strategy_name)
                return True
            else:
                print("⚠️  未找到 long_restart 事件（可能还在批量写入队列中）")
                cleanup_test_data(strategy_name)
                return False
    except Exception as e:
        print(f"❌ 事件记录测试失败: {e}")
        import traceback
        traceback.print_exc()
        cleanup_test_data(strategy_name)
        return False


def main():
    """运行所有测试"""
    print("=" * 70)
    print("🧪 净值数据库持久化端到端测试")
    print("=" * 70)
    print()
    
    results = []
    
    # 测试 1 & 2: 初始化和净值计算
    success, net_value = test_basic_initialization()
    results.append(("初始化", success))
    
    if success:
        calc_success = test_net_value_calculation(net_value)
        results.append(("净值计算", calc_success))
        
        # 测试 3: Redis 数据验证
        redis_success = test_redis_data()
        results.append(("Redis 数据", redis_success))
        
        # 测试 4: PostgreSQL 数据验证（多次尝试）
        pg_success = False
        for attempt in range(3):
            if attempt > 0:
                print(f"\n⏳ 第 {attempt + 1} 次尝试验证 PostgreSQL 数据...")
                time.sleep(5)  # 等待批量写入
            
            pg_success = test_postgresql_data()
            if pg_success:
                break
        
        results.append(("PostgreSQL 数据", pg_success))
        
        # 测试 5: 数据一致性
        if redis_success and pg_success:
            consistency_success = test_data_consistency()
            results.append(("数据一致性", consistency_success))
    
    # 测试 6: 异常事件记录
    event_success = test_event_recording()
    results.append(("异常事件记录", event_success))
    
    # 清理测试数据
    cleanup_test_data("test_ton3l")
    
    # 总结
    print("\n" + "=" * 70)
    print("📊 测试结果总结")
    print("=" * 70)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name:20s}: {status}")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    print("\n" + "-" * 70)
    print(f"通过率: {passed}/{total} ({passed*100//total}%)")
    print("-" * 70)
    
    if passed == total:
        print("\n🎉 所有测试通过！净值数据库持久化功能正常工作。")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败，请检查日志。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
