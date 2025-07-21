#!/usr/bin/env python3
"""
监控 Redis 中的 last_amount 数据
实时显示各策略的持仓数量和变化情况
"""

import os
import sys
import time
import redis
from datetime import datetime
from tabulate import tabulate

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.storage.redis_last_amount import RedisLastAmountStorage


def monitor_last_amount(refresh_interval=5):
    """
    监控 last_amount 数据

    Args:
        refresh_interval: 刷新间隔（秒）
    """
    storage = RedisLastAmountStorage()

    # 检查 Redis 连接
    if not storage.health_check():
        print("Error: Cannot connect to Redis!")
        return

    print("Monitoring last_amount data in Redis...")
    print(f"Refresh interval: {refresh_interval} seconds")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            # 清屏（跨平台）
            os.system("cls" if os.name == "nt" else "clear")

            print(
                f"Last Amount Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            print("=" * 80)

            # 获取所有 symbols
            symbols = storage.get_all_symbols()

            if not symbols:
                print("No data found in Redis")
            else:
                # 准备表格数据
                table_data = []

                for symbol in sorted(symbols):
                    amount = storage.get_last_amount(symbol)
                    detail = storage.get_last_amount_detail(symbol)

                    if detail:
                        timestamp = detail.get("timestamp", "N/A")
                        delta_amount = detail.get("delta_amount", "N/A")
                        delta_position = detail.get("delta_position", "N/A")
                        mid_price = detail.get("mid_price", "N/A")
                        source = detail.get("source", "normal")

                        # 格式化时间戳
                        if timestamp != "N/A":
                            try:
                                dt = datetime.fromisoformat(timestamp)
                                timestamp = dt.strftime("%H:%M:%S")
                            except:
                                pass

                        # 格式化数值
                        if isinstance(delta_amount, (int, float)):
                            delta_str = f"{delta_amount:+.2f}"
                            if delta_amount < 0:
                                delta_str = (
                                    f"\033[92m{delta_str}\033[0m"  # 绿色：用户买入
                                )
                            elif delta_amount > 0:
                                delta_str = (
                                    f"\033[91m{delta_str}\033[0m"  # 红色：用户卖出
                                )
                        else:
                            delta_str = str(delta_amount)

                        table_data.append([
                            symbol,
                            f"{amount:,.2f}" if amount else "N/A",
                            delta_str,
                            f"{delta_position:,.2f}"
                            if isinstance(delta_position, (int, float))
                            else delta_position,
                            f"{mid_price:.4f}"
                            if isinstance(mid_price, (int, float))
                            else mid_price,
                            timestamp,
                            source,
                        ])
                    else:
                        table_data.append([
                            symbol,
                            f"{amount:,.2f}" if amount else "N/A",
                            "N/A",
                            "N/A",
                            "N/A",
                            "N/A",
                            "N/A",
                        ])

                # 打印表格
                headers = [
                    "Symbol",
                    "Last Amount",
                    "Delta Amount",
                    "Delta Position",
                    "Mid Price",
                    "Update Time",
                    "Source",
                ]
                print(tabulate(table_data, headers=headers, tablefmt="grid"))

                # 统计信息
                print(f"\nTotal symbols: {len(symbols)}")

            # 说明
            print("\nLegend:")
            print("  \033[92m- Green\033[0m: User bought (delta < 0)")
            print("  \033[91m- Red\033[0m: User sold (delta > 0)")
            print("  Source: 'initial' means first run initialization")

            time.sleep(refresh_interval)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


def show_detailed_info():
    """显示详细的 last_amount 信息"""
    storage = RedisLastAmountStorage()

    if not storage.health_check():
        print("Error: Cannot connect to Redis!")
        return

    print("Detailed Last Amount Information")
    print("=" * 80)

    symbols = storage.get_all_symbols()

    for symbol in sorted(symbols):
        print(f"\n{symbol}:")
        print("-" * 40)

        amount = storage.get_last_amount(symbol)
        detail = storage.get_last_amount_detail(symbol)

        print(f"  Current Amount: {amount}")

        if detail:
            for key, value in detail.items():
                if key != "amount":  # 避免重复
                    print(f"  {key}: {value}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Monitor last_amount data in Redis")
    parser.add_argument(
        "-d",
        "--detailed",
        action="store_true",
        help="Show detailed information and exit",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=5,
        help="Refresh interval in seconds (default: 5)",
    )

    args = parser.parse_args()

    if args.detailed:
        show_detailed_info()
    else:
        monitor_last_amount(args.interval)
