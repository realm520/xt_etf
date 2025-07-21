#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
改进版净值计算器使用示例
展示如何直接使用 ImprovedNetValue 类

使用方法:
    python example_improved_net_value.py
"""

from etf.net_value_improved import ImprovedNetValue
from loguru import logger
import time


def main():
    """示例：使用改进版净值计算器"""

    # 配置参数
    config = {
        "symbol": "stg_usdt",
        "m_lever": 3,  # 3倍杠杆
        "long": True,  # 做多
        "init_net_value": 1.0,  # 初始净值
        "daily_fee": 0.001,  # 日管理费率 0.1%
        "time_gap_second": 10,  # 更新间隔10秒
        "rebalance": 0.05,  # 再平衡阈值 5%
        "max_single_change": 0.10,  # 最大单次变化率 10%
        "max_restart_gap": 300,  # 最大重启间隔 5分钟
    }

    logger.info("启动改进版净值计算器示例")
    logger.info(f"配置参数: {config}")

    # 创建净值计算器实例
    calculator = ImprovedNetValue(**config)

    logger.info("改进版净值计算器特性:")
    logger.info("1. 自动断线恢复 - 程序重启后自动恢复净值")
    logger.info("2. 价格异常保护 - 限制单次价格变化最大10%")
    logger.info("3. 详细数据记录 - Redis保存完整历史和异常事件")
    logger.info("4. 管理费精确计算 - 断线期间的管理费会被补扣")

    # 显示Redis键
    logger.info(f"\nRedis键:")
    logger.info(f"- 简单净值: {calculator.redis_key}")
    logger.info(f"- 详细数据: {calculator.redis_detail_key}")
    logger.info(f"- 历史记录: {calculator.redis_history_key}")

    # 模拟运行（仅用于演示，实际使用时调用 calculator.run()）
    logger.info("\n模拟净值计算过程...")

    # 模拟价格更新
    prices = [100.0, 101.0, 99.5, 102.0, 98.0]

    for i, price in enumerate(prices[:2]):
        calculator.underlying_mid_price_queue.put(price)
        logger.info(f"添加价格: {price}")

    # 计算净值
    net_value = calculator.cal_net_value()
    if net_value:
        logger.info(f"计算后净值: {net_value:.6f}")

        # 扣除管理费
        net_value_after_fee = calculator.cal_fee(net_value)
        logger.info(f"扣费后净值: {net_value_after_fee:.6f}")

    logger.info("\n要启动实际的净值计算，请运行:")
    logger.info("python run_net_value.py --strategy stg3l")

    # 显示如何检查异常事件
    if calculator.net_value_data["abnormal_events"]:
        logger.warning(f"异常事件记录: {calculator.net_value_data['abnormal_events']}")

    logger.info("\n示例完成！")


if __name__ == "__main__":
    main()
