#!/usr/bin/env python3
"""
启动实时监控系统
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.monitoring import RealTimeMonitor


async def main():
    """启动监控"""
    print("启动ETF实时监控系统...")

    # 创建监控器
    monitor = RealTimeMonitor()

    # 自定义告警阈值（可选）
    monitor.update_thresholds({
        "max_loss_per_day": 0.02,  # 日最大亏损2%
        "min_real_volume_ratio": 0.15,  # 最小真实交易量15%
        "max_spread": 0.03,  # 最大价差3%
    })

    # 启动监控
    try:
        await monitor.start_monitoring()
    except KeyboardInterrupt:
        print("\n监控系统已停止")


if __name__ == "__main__":
    asyncio.run(main())
