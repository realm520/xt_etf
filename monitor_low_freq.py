#!/usr/bin/env python3
"""
中低频策略监控脚本
监控洗盘交易频率、真实交易占比、净值偏离度等关键指标
"""

import time
import json
import redis
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, List, Tuple
import requests

from etf.config import load_config


class LowFrequencyMonitor:
    """中低频策略监控器"""

    def __init__(self, config_file="config/strategies.yaml"):
        """初始化监控器"""
        # 使用统一配置加载器
        config = load_config(config_file)
        self.strategies_config = config.get("strategies", {})

        # Redis连接
        self.redis_client = redis.Redis(
            host="localhost", port=6379, decode_responses=True
        )

        # 监控数据存储
        self.washing_trades = defaultdict(lambda: deque(maxlen=1000))  # 洗盘交易记录
        self.real_trades = defaultdict(lambda: deque(maxlen=1000))  # 真实交易记录
        self.net_values = defaultdict(lambda: deque(maxlen=100))  # 净值记录
        self.alerts = []  # 告警记录

        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger("LowFreqMonitor")

        # 告警阈值
        self.thresholds = {
            "washing_freq_min": 40,  # 每小时最少洗盘次数
            "washing_freq_max": 150,  # 每小时最多洗盘次数
            "real_trade_ratio_min": 0.05,  # 真实交易最低占比
            "real_trade_ratio_max": 0.3,  # 真实交易最高占比
            "net_value_deviation": 0.05,  # 净值偏离度阈值
        }

    def collect_trade_data(self, strategy: str):
        """收集交易数据"""
        # 从Redis获取最新交易数据
        trades_key = f"trades:{strategy}"
        latest_trades = self.redis_client.lrange(trades_key, 0, 100)

        current_time = time.time()

        for trade_json in latest_trades:
            try:
                trade = json.loads(trade_json)
                trade_time = trade.get("timestamp", current_time)

                # 区分洗盘交易和真实交易
                if trade.get("is_washing", False):
                    self.washing_trades[strategy].append({
                        "time": trade_time,
                        "amount": trade.get("amount", 0),
                        "price": trade.get("price", 0),
                    })
                else:
                    self.real_trades[strategy].append({
                        "time": trade_time,
                        "amount": trade.get("amount", 0),
                        "price": trade.get("price", 0),
                        "side": trade.get("side", "unknown"),
                    })
            except Exception as e:
                self.logger.error(f"解析交易数据失败: {e}")

    def collect_net_value_data(self, strategy: str):
        """收集净值数据"""
        # 从Redis获取最新净值
        net_value_key = f"net_value:{strategy}"
        net_value_data = self.redis_client.get(net_value_key)

        if net_value_data:
            try:
                data = json.loads(net_value_data)
                self.net_values[strategy].append({
                    "time": time.time(),
                    "value": data.get("net_value", 1.0),
                    "btc_price": data.get("btc_price", 0),
                })
            except Exception as e:
                self.logger.error(f"解析净值数据失败: {e}")

    def calculate_washing_frequency(self, strategy: str) -> float:
        """计算洗盘交易频率（每小时）"""
        current_time = time.time()
        one_hour_ago = current_time - 3600

        # 统计过去一小时的洗盘交易
        recent_washes = [
            t for t in self.washing_trades[strategy] if t["time"] > one_hour_ago
        ]

        return len(recent_washes)

    def calculate_real_trade_ratio(self, strategy: str) -> float:
        """计算真实交易占比"""
        current_time = time.time()
        one_hour_ago = current_time - 3600

        # 统计过去一小时的交易
        recent_washes = [
            t for t in self.washing_trades[strategy] if t["time"] > one_hour_ago
        ]
        recent_real = [
            t for t in self.real_trades[strategy] if t["time"] > one_hour_ago
        ]

        total_trades = len(recent_washes) + len(recent_real)
        if total_trades == 0:
            return 0

        return len(recent_real) / total_trades

    def calculate_net_value_deviation(self, strategy: str) -> Tuple[float, float]:
        """计算净值偏离度"""
        if len(self.net_values[strategy]) < 2:
            return 0, 0

        # 获取最新净值和初始净值
        latest_value = self.net_values[strategy][-1]["value"]
        initial_value = self.net_values[strategy][0]["value"]

        # 计算收益率
        return_rate = (latest_value - initial_value) / initial_value

        # 计算净值波动率
        values = [v["value"] for v in self.net_values[strategy]]
        if len(values) > 1:
            avg_value = sum(values) / len(values)
            variance = sum((v - avg_value) ** 2 for v in values) / len(values)
            volatility = variance**0.5
        else:
            volatility = 0

        return return_rate, volatility

    def check_alerts(self, strategy: str):
        """检查并生成告警"""
        # 检查洗盘频率
        washing_freq = self.calculate_washing_frequency(strategy)
        if washing_freq < self.thresholds["washing_freq_min"]:
            self.generate_alert(
                strategy, "LOW_WASHING_FREQ", f"洗盘频率过低: {washing_freq:.0f}次/小时"
            )
        elif washing_freq > self.thresholds["washing_freq_max"]:
            self.generate_alert(
                strategy,
                "HIGH_WASHING_FREQ",
                f"洗盘频率过高: {washing_freq:.0f}次/小时",
            )

        # 检查真实交易占比
        real_ratio = self.calculate_real_trade_ratio(strategy)
        if real_ratio < self.thresholds["real_trade_ratio_min"]:
            self.generate_alert(
                strategy, "LOW_REAL_TRADE_RATIO", f"真实交易占比过低: {real_ratio:.1%}"
            )
        elif real_ratio > self.thresholds["real_trade_ratio_max"]:
            self.generate_alert(
                strategy, "HIGH_REAL_TRADE_RATIO", f"真实交易占比过高: {real_ratio:.1%}"
            )

        # 检查净值偏离
        return_rate, volatility = self.calculate_net_value_deviation(strategy)
        if abs(return_rate) > self.thresholds["net_value_deviation"]:
            self.generate_alert(
                strategy, "NET_VALUE_DEVIATION", f"净值偏离过大: {return_rate:.1%}"
            )

    def generate_alert(self, strategy: str, alert_type: str, message: str):
        """生成告警"""
        alert = {
            "time": datetime.now().isoformat(),
            "strategy": strategy,
            "type": alert_type,
            "message": message,
        }

        self.alerts.append(alert)
        self.logger.warning(f"[{strategy}] {alert_type}: {message}")

        # TODO: 发送告警通知（邮件、企业微信等）
        # self.send_notification(alert)

    def print_status(self):
        """打印当前状态"""
        print("\n" + "=" * 60)
        print(f"中低频策略监控报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        for strategy in self.strategies_config.keys():
            print(f"\n策略: {strategy}")
            print("-" * 40)

            # 洗盘频率
            washing_freq = self.calculate_washing_frequency(strategy)
            expected_freq = 3600 / self.strategies_config[strategy]["washing_interval"]
            print(
                f"洗盘频率: {washing_freq:.0f}次/小时 (预期: {expected_freq:.0f}次/小时)"
            )

            # 真实交易占比
            real_ratio = self.calculate_real_trade_ratio(strategy)
            print(f"真实交易占比: {real_ratio:.1%}")

            # 净值情况
            if self.net_values[strategy]:
                latest_nv = self.net_values[strategy][-1]["value"]
                return_rate, volatility = self.calculate_net_value_deviation(strategy)
                print(f"最新净值: {latest_nv:.4f}")
                print(f"收益率: {return_rate:.2%}")
                print(f"波动率: {volatility:.2%}")

        # 显示告警
        if self.alerts:
            print("\n" + "=" * 60)
            print("告警信息:")
            print("=" * 60)
            for alert in self.alerts[-10:]:  # 显示最近10条告警
                print(f"[{alert['time']}] {alert['strategy']} - {alert['message']}")

    def run(self, interval=60):
        """运行监控"""
        self.logger.info("中低频策略监控启动...")

        while True:
            try:
                # 收集数据并检查告警
                for strategy in self.strategies_config.keys():
                    self.collect_trade_data(strategy)
                    self.collect_net_value_data(strategy)
                    self.check_alerts(strategy)

                # 打印状态
                self.print_status()

                # 清理旧告警
                if len(self.alerts) > 100:
                    self.alerts = self.alerts[-50:]

                # 等待下一次检查
                time.sleep(interval)

            except KeyboardInterrupt:
                self.logger.info("监控停止")
                break
            except Exception as e:
                self.logger.error(f"监控出错: {e}")
                time.sleep(10)


if __name__ == "__main__":
    monitor = LowFrequencyMonitor()
    monitor.run(interval=60)  # 每60秒检查一次
