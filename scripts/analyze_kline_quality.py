#!/usr/bin/env python3
"""
K线质量分析脚本

从PostgreSQL数据库分析洗盘交易生成的K线质量:
1. 价格连续性（跳空检测）
2. 影线分布（全实体vs有影线）
3. 交易频率分布
4. 分笔成交效果
"""

import os
import sys
import psycopg2
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """获取PostgreSQL数据库连接"""
    db_user = os.getenv("POSTGRES_USER", "xtetf")
    db_password = os.getenv("POSTGRES_PASSWORD", "12345678")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "xtetf")

    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_password
    )
    return conn


def analyze_kline_quality(symbol: str = "ton3l_usdt", minutes: int = 15):
    """分析最近N分钟的K线质量"""
    logger.info(f"{'='*80}")
    logger.info(f"开始分析 {symbol} 最近 {minutes} 分钟的K线质量")
    logger.info(f"{'='*80}\n")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 查询最近N分钟的成交数据
    query = """
        SELECT
            price,
            quantity,
            is_wash_trading,
            traded_at,
            created_at
        FROM trades
        WHERE symbol = %s
            AND traded_at >= NOW() - INTERVAL '%s minutes'
        ORDER BY traded_at ASC
    """

    cursor.execute(query, (symbol, minutes))
    trades = cursor.fetchall()

    if not trades:
        logger.warning(f"未找到 {symbol} 的成交记录")
        logger.info("\n💡 提示: 确保订单记录功能已启用:")
        logger.info("   1. 检查 config/strategies.yaml 中 order_persistence.enabled")
        logger.info("   2. 运行系统等待成交数据写入数据库")
        conn.close()
        return

    logger.info(f"总成交数: {len(trades)}")
    logger.info(f"时间范围: {trades[0][3]} ~ {trades[-1][3]}\n")

    # 2. 生成1分钟K线
    klines = defaultdict(lambda: {
        'open': None,
        'high': 0,
        'low': float('inf'),
        'close': None,
        'count': 0,
        'wash_count': 0,
        'real_count': 0,
        'trades': []
    })

    for price, quantity, is_wash, traded_at, created_at in trades:
        price = float(price)
        quantity = float(quantity)

        # 按分钟聚合
        minute_ts = traded_at.replace(second=0, microsecond=0)
        kline = klines[minute_ts]

        kline['trades'].append({
            'price': price,
            'quantity': quantity,
            'is_wash': is_wash,
            'time': traded_at
        })
        kline['count'] += 1

        if is_wash:
            kline['wash_count'] += 1
        else:
            kline['real_count'] += 1

        if kline['open'] is None:
            kline['open'] = price
        kline['close'] = price
        kline['high'] = max(kline['high'], price)
        kline['low'] = min(kline['low'], price)

    # 3. 分析K线质量
    logger.info("K线详细分析:")
    logger.info(f"{'时间':<20} {'开':<10} {'高':<10} {'低':<10} {'收':<10} {'笔数':<6} {'振幅%':<8} {'实体%':<8} {'上影%':<8} {'下影%':<8} {'洗/真'}")
    logger.info("-" * 140)

    total_klines = len(klines)
    full_body_count = 0  # 全实体K线
    has_shadow_count = 0  # 有影线K线
    price_gaps = []  # 价格跳空

    sorted_klines = sorted(klines.items())
    prev_close = None

    for i, (ts, kline) in enumerate(sorted_klines):
        o, h, l, c = kline['open'], kline['high'], kline['low'], kline['close']

        # 计算振幅
        amplitude = ((h - l) / l * 100) if l > 0 else 0

        # 计算实体和影线
        body_size = abs(c - o)
        upper_shadow = h - max(o, c)
        lower_shadow = min(o, c) - l
        total_range = h - l

        body_pct = (body_size / total_range * 100) if total_range > 0 else 0
        upper_pct = (upper_shadow / total_range * 100) if total_range > 0 else 0
        lower_pct = (lower_shadow / total_range * 100) if total_range > 0 else 0

        # 判断是否全实体
        if upper_shadow == 0 and lower_shadow == 0:
            full_body_count += 1
        elif upper_shadow > 0 or lower_shadow > 0:
            has_shadow_count += 1

        # 检查价格跳空
        if prev_close is not None:
            gap = abs(o - prev_close) / prev_close * 100
            if gap > 0.1:  # 0.1%以上算跳空
                price_gaps.append({
                    'time': ts,
                    'prev_close': prev_close,
                    'open': o,
                    'gap_pct': gap
                })

        prev_close = c

        time_str = ts.strftime('%Y-%m-%d %H:%M')
        wash_real_ratio = f"{kline['wash_count']}/{kline['real_count']}"

        logger.info(
            f"{time_str:<20} {o:<10.6f} {h:<10.6f} {l:<10.6f} {c:<10.6f} "
            f"{kline['count']:<6} {amplitude:<8.2f} {body_pct:<8.1f} {upper_pct:<8.1f} {lower_pct:<8.1f} "
            f"{wash_real_ratio}"
        )

    # 4. 统计总结
    logger.info("\n" + "="*140)
    logger.info("📊 K线质量统计:")
    logger.info(f"  总K线数: {total_klines}")
    logger.info(f"  全实体K线: {full_body_count} ({full_body_count/total_klines*100:.1f}%)")
    logger.info(f"  有影线K线: {has_shadow_count} ({has_shadow_count/total_klines*100:.1f}%)")
    logger.info(f"  价格跳空: {len(price_gaps)} 次")

    if price_gaps:
        logger.info("\n⚠️ 价格跳空详情:")
        for gap in price_gaps:
            logger.info(
                f"  {gap['time'].strftime('%H:%M')} - 跳空 {gap['gap_pct']:.2f}% "
                f"(从 {gap['prev_close']:.6f} 到 {gap['open']:.6f})"
            )

    # 5. 分笔成交分析
    logger.info(f"\n📈 分笔成交效果分析:")
    for ts, kline in sorted_klines:
        time_str = ts.strftime('%H:%M')
        logger.info(f"  {time_str}: {kline['count']} 笔成交")

        # 显示价格分布
        prices = [t['price'] for t in kline['trades']]
        if len(prices) > 1:
            logger.info(
                f"    价格分布: 最低={min(prices):.6f}, 最高={max(prices):.6f}, "
                f"变化={((max(prices) - min(prices)) / min(prices) * 100):.2f}%"
            )

    # 6. 改进效果评估
    logger.info(f"\n{'='*140}")
    logger.info("✅ 改进效果评估:")

    if has_shadow_count / total_klines > 0.5:
        logger.info(f"  ✓ K线有影线比例: {has_shadow_count/total_klines*100:.1f}% (良好，目标>50%)")
    else:
        logger.info(f"  ✗ K线有影线比例: {has_shadow_count/total_klines*100:.1f}% (不足，目标>50%)")

    if len(price_gaps) == 0:
        logger.info("  ✓ 价格连续性: 无跳空 (优秀)")
    elif len(price_gaps) < total_klines * 0.2:
        logger.info(f"  ✓ 价格连续性: {len(price_gaps)}次跳空 (良好，<20%)")
    else:
        logger.info(f"  ✗ 价格连续性: {len(price_gaps)}次跳空 (需改进，>20%)")

    avg_trades_per_minute = len(trades) / minutes
    logger.info(f"  • 平均成交频率: {avg_trades_per_minute:.1f} 笔/分钟")

    logger.info(f"\n{'='*140}\n")

    conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='K线质量分析工具')
    parser.add_argument('--symbol', default='ton3l_usdt', help='交易对符号')
    parser.add_argument('--minutes', type=int, default=15, help='分析时间窗口（分钟）')

    args = parser.parse_args()

    try:
        analyze_kline_quality(symbol=args.symbol, minutes=args.minutes)
    except Exception as e:
        logger.error(f"分析失败: {e}", exc_info=True)
        sys.exit(1)
