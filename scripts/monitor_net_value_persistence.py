#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
净值数据库持久化监控脚本

用于生产环境监控净值数据持久化状态：
1. 检查最近数据更新时间
2. 验证数据写入频率
3. 检测异常事件
4. 生成健康报告
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import sessionmaker
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


def check_redis_status(strategy_names: List[str]) -> Dict[str, Any]:
    """检查 Redis 状态"""
    print("=" * 70)
    print("📊 Redis 状态检查")
    print("=" * 70)
    
    results = {}
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    
    for strategy in strategy_names:
        print(f"\n策略: {strategy}")
        try:
            # 简单净值
            net_value = r.get(f"netvalue_{strategy}")
            
            # 详细数据
            detail_data = r.get(f"netvalue_{strategy}_detail")
            detail = None
            if detail_data:
                import json
                detail = json.loads(detail_data)
            
            # 历史记录
            history_count = r.llen(f"netvalue_{strategy}_history")
            
            if net_value:
                print(f"  ✅ 净值: {net_value}")
            else:
                print(f"  ❌ 净值数据缺失")
            
            if detail:
                last_update = datetime.fromtimestamp(detail.get('last_update_ts', 0))
                now = datetime.now()
                age = (now - last_update).total_seconds()
                
                print(f"  📅 最后更新: {last_update.strftime('%Y-%m-%d %H:%M:%S')} ({age:.0f}秒前)")
                print(f"  🔢 更新次数: {detail.get('update_count', 0)}")
                print(f"  💰 累计手续费: {detail.get('total_fee_deducted', 0)}")
                print(f"  📜 历史记录数: {history_count}")
                
                # 检查更新是否及时
                if age > 60:
                    print(f"  ⚠️  数据更新延迟: {age:.0f}秒")
                    status = "delayed"
                else:
                    print(f"  ✅ 数据更新正常")
                    status = "ok"
            else:
                print(f"  ❌ 详细数据缺失")
                status = "missing"
            
            results[strategy] = {
                "status": status,
                "net_value": net_value,
                "detail": detail,
                "history_count": history_count
            }
            
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            results[strategy] = {"status": "error", "error": str(e)}
    
    return results


def check_postgresql_status(strategy_names: List[str]) -> Dict[str, Any]:
    """检查 PostgreSQL 状态"""
    print("\n" + "=" * 70)
    print("🗄️  PostgreSQL 状态检查")
    print("=" * 70)
    
    results = {}
    
    try:
        engine, Session = get_db_connection()
        
        for strategy in strategy_names:
            print(f"\n策略: {strategy}")
            
            with Session() as session:
                # 统计记录数
                count_result = session.execute(
                    select(func.count(NetValueHistory.id))
                    .where(NetValueHistory.strategy_name == strategy)
                )
                total_count = count_result.scalar() or 0
                
                print(f"  📊 总记录数: {total_count}")
                
                if total_count == 0:
                    print(f"  ⚠️  没有历史记录")
                    results[strategy] = {"status": "no_data", "count": 0}
                    continue
                
                # 最新记录
                latest_result = session.execute(
                    select(NetValueHistory)
                    .where(NetValueHistory.strategy_name == strategy)
                    .order_by(NetValueHistory.recorded_at.desc())
                    .limit(1)
                )
                latest = latest_result.scalar()
                
                if latest:
                    now = datetime.now()
                    age = (now - latest.recorded_at).total_seconds()
                    
                    print(f"  📅 最新记录: {latest.recorded_at.strftime('%Y-%m-%d %H:%M:%S')} ({age:.0f}秒前)")
                    print(f"  💰 最新净值: {latest.net_value}")
                    print(f"  💸 累计手续费: {latest.cumulative_fee}")
                    
                    # 检查更新频率
                    if age > 300:  # 5分钟
                        print(f"  ⚠️  数据写入延迟: {age:.0f}秒")
                        status = "delayed"
                    else:
                        print(f"  ✅ 数据写入正常")
                        status = "ok"
                    
                    # 最近1小时写入频率
                    hour_ago = now - timedelta(hours=1)
                    hour_count_result = session.execute(
                        select(func.count(NetValueHistory.id))
                        .where(NetValueHistory.strategy_name == strategy)
                        .where(NetValueHistory.recorded_at >= hour_ago)
                    )
                    hour_count = hour_count_result.scalar() or 0
                    
                    print(f"  📈 最近1小时: {hour_count} 条记录 (平均 {hour_count/60:.1f}/分钟)")
                    
                    results[strategy] = {
                        "status": status,
                        "count": total_count,
                        "latest": latest.recorded_at,
                        "net_value": float(latest.net_value),
                        "hour_count": hour_count
                    }
                else:
                    print(f"  ❌ 无法读取最新记录")
                    results[strategy] = {"status": "error", "count": total_count}
                
    except Exception as e:
        print(f"\n❌ 数据库连接错误: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
    
    return results


def check_abnormal_events(strategy_names: List[str], hours: int = 24) -> Dict[str, List]:
    """检查异常事件（最近N小时）"""
    print("\n" + "=" * 70)
    print(f"⚠️  异常事件检查（最近 {hours} 小时）")
    print("=" * 70)
    
    results = {}
    
    try:
        engine, Session = get_db_connection()
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        for strategy in strategy_names:
            print(f"\n策略: {strategy}")
            
            with Session() as session:
                events_result = session.execute(
                    select(NetValueEvent)
                    .where(NetValueEvent.strategy_name == strategy)
                    .where(NetValueEvent.event_time >= cutoff_time)
                    .order_by(NetValueEvent.event_time.desc())
                )
                events = events_result.scalars().all()
                
                if not events:
                    print(f"  ✅ 无异常事件")
                    results[strategy] = []
                    continue
                
                print(f"  ⚠️  发现 {len(events)} 个异常事件:")
                
                event_list = []
                for event in events:
                    print(f"     - {event.event_type:15s} | {event.severity:8s} | {event.event_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    event_list.append({
                        "type": event.event_type,
                        "severity": event.severity,
                        "time": event.event_time,
                        "old_price": float(event.old_price) if event.old_price else None,
                        "new_price": float(event.new_price) if event.new_price else None,
                        "change_rate": float(event.change_rate) if event.change_rate else None,
                        "gap_seconds": event.gap_seconds
                    })
                
                results[strategy] = event_list
                
    except Exception as e:
        print(f"\n❌ 事件查询错误: {e}")
        return {"error": str(e)}
    
    return results


def generate_health_report(
    redis_status: Dict,
    pg_status: Dict,
    events: Dict
) -> Dict[str, str]:
    """生成健康报告"""
    print("\n" + "=" * 70)
    print("🏥 健康状态报告")
    print("=" * 70)
    
    health_scores = {}
    
    for strategy in set(list(redis_status.keys()) + list(pg_status.keys())):
        print(f"\n策略: {strategy}")
        
        issues = []
        score = 100
        
        # Redis 检查
        redis_info = redis_status.get(strategy, {})
        if redis_info.get("status") == "missing":
            issues.append("Redis 数据缺失")
            score -= 30
        elif redis_info.get("status") == "delayed":
            issues.append("Redis 数据更新延迟")
            score -= 10
        elif redis_info.get("status") == "error":
            issues.append(f"Redis 错误: {redis_info.get('error')}")
            score -= 20
        
        # PostgreSQL 检查
        pg_info = pg_status.get(strategy, {})
        if pg_info.get("status") == "no_data":
            issues.append("PostgreSQL 无数据")
            score -= 30
        elif pg_info.get("status") == "delayed":
            issues.append("PostgreSQL 写入延迟")
            score -= 10
        elif pg_info.get("status") == "error":
            issues.append("PostgreSQL 错误")
            score -= 20
        
        # 异常事件检查
        strategy_events = events.get(strategy, [])
        critical_events = [e for e in strategy_events if e.get('severity') == 'critical']
        if critical_events:
            issues.append(f"{len(critical_events)} 个严重事件")
            score -= len(critical_events) * 5
        
        # 数据一致性检查
        if redis_info.get("net_value") and pg_info.get("net_value"):
            redis_val = float(redis_info["net_value"])
            pg_val = pg_info["net_value"]
            if abs(redis_val - pg_val) > 0.0001:
                issues.append(f"数据不一致 (Redis:{redis_val:.6f} vs PG:{pg_val:.6f})")
                score -= 15
        
        # 生成评级
        if score >= 90:
            health = "🟢 健康"
        elif score >= 70:
            health = "🟡 警告"
        else:
            health = "🔴 异常"
        
        print(f"  健康评分: {score}/100")
        print(f"  状态: {health}")
        
        if issues:
            print(f"  问题:")
            for issue in issues:
                print(f"    - {issue}")
        else:
            print(f"  ✅ 运行正常")
        
        health_scores[strategy] = health
    
    return health_scores


def main():
    """主函数"""
    # 从环境变量或配置文件读取策略列表
    strategies = os.getenv("STRATEGIES", "ton3l,stg3l,stg3s,stg5l,stg5s").split(",")
    
    print("🔍 净值数据库持久化监控")
    print(f"监控策略: {', '.join(strategies)}")
    print()
    
    # 检查 Redis
    redis_status = check_redis_status(strategies)
    
    # 检查 PostgreSQL
    pg_status = check_postgresql_status(strategies)
    
    # 检查异常事件
    events = check_abnormal_events(strategies, hours=24)
    
    # 生成健康报告
    health_scores = generate_health_report(redis_status, pg_status, events)
    
    # 总结
    print("\n" + "=" * 70)
    print("📋 监控总结")
    print("=" * 70)
    
    healthy_count = sum(1 for h in health_scores.values() if "健康" in h)
    warning_count = sum(1 for h in health_scores.values() if "警告" in h)
    error_count = sum(1 for h in health_scores.values() if "异常" in h)
    
    print(f"总策略数: {len(strategies)}")
    print(f"健康: {healthy_count}")
    print(f"警告: {warning_count}")
    print(f"异常: {error_count}")
    
    if error_count > 0:
        print("\n⚠️  发现异常，请检查日志！")
        return 1
    elif warning_count > 0:
        print("\n⚠️  有警告项，建议关注。")
        return 0
    else:
        print("\n✅ 所有策略运行正常！")
        return 0


if __name__ == "__main__":
    sys.exit(main())
