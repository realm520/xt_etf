"""
实时监控系统
提供策略运行状态、交易统计和性能指标的实时监控
"""

import logging
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import redis.asyncio as aioredis
from collections import defaultdict
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class RealTimeMonitor:
    """实时监控器"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """
        初始化监控器
        Args:
            redis_url: Redis连接URL
        """
        self.redis_url = redis_url
        self.redis = None

        # 监控数据
        self.metrics = defaultdict(lambda: defaultdict(float))
        self.alerts = []
        self.performance_history = []

        # 监控参数
        self.thresholds = {
            "max_loss_per_day": 0.02,  # 日最大亏损2%
            "min_real_volume_ratio": 0.1,  # 最小真实交易量比例10%
            "max_spread": 0.05,  # 最大价差5%
            "min_orders_per_hour": 10,  # 每小时最少订单数
            "max_inventory_ratio": 0.7,  # 最大库存比例70%
        }

        # 更新间隔
        self.update_interval = 5  # 5秒更新一次

    async def init(self):
        """初始化Redis连接"""
        self.redis = await aioredis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True
        )
        logging.info("监控器Redis连接初始化完成")

    async def start_monitoring(self):
        """启动监控循环"""
        if not self.redis:
            await self.init()

        logging.info("实时监控启动")

        while True:
            try:
                # 收集指标
                await self.collect_metrics()

                # 检查告警
                await self.check_alerts()

                # 记录性能
                await self.record_performance()

                # 发布监控数据
                await self.publish_monitoring_data()

                # 等待下一轮
                await asyncio.sleep(self.update_interval)

            except Exception as e:
                logging.error(f"监控循环错误: {e}")
                await asyncio.sleep(self.update_interval)

    async def collect_metrics(self):
        """收集各项指标"""
        try:
            # 获取所有策略的统计数据
            strategies = ["stg3l", "stg3s", "stg5l", "stg5s"]

            for strategy in strategies:
                # 订单统计
                order_stats = await self._get_order_stats(strategy)
                self.metrics[strategy]["total_orders"] = order_stats.get(
                    "total_orders", 0
                )
                self.metrics[strategy]["real_orders"] = order_stats.get(
                    "real_orders", 0
                )
                self.metrics[strategy]["real_order_ratio"] = order_stats.get(
                    "real_order_ratio", 0
                )

                # 交易量统计
                volume_stats = await self._get_volume_stats(strategy)
                self.metrics[strategy]["total_volume"] = volume_stats.get(
                    "total_volume", 0
                )
                self.metrics[strategy]["real_volume"] = volume_stats.get(
                    "real_volume", 0
                )
                self.metrics[strategy]["real_volume_ratio"] = volume_stats.get(
                    "real_volume_ratio", 0
                )

                # PnL统计
                pnl_stats = await self._get_pnl_stats(strategy)
                self.metrics[strategy]["daily_pnl"] = pnl_stats.get("daily_pnl", 0)
                self.metrics[strategy]["daily_pnl_pct"] = pnl_stats.get(
                    "daily_pnl_pct", 0
                )

                # 库存统计
                inventory_stats = await self._get_inventory_stats(strategy)
                self.metrics[strategy]["inventory_ratio"] = inventory_stats.get(
                    "ratio", 0.5
                )
                self.metrics[strategy]["inventory_value"] = inventory_stats.get(
                    "value", 0
                )

                # 价差统计
                spread_stats = await self._get_spread_stats(strategy)
                self.metrics[strategy]["current_spread"] = spread_stats.get(
                    "current", 0.01
                )
                self.metrics[strategy]["avg_spread"] = spread_stats.get("average", 0.01)

        except Exception as e:
            logging.error(f"收集指标失败: {e}")

    async def _get_order_stats(self, strategy: str) -> Dict[str, Any]:
        """获取订单统计"""
        try:
            symbol = f"{strategy}_usdt"
            stats_key = f"stats:{symbol}:orders"

            data = await self.redis.hgetall(stats_key)

            total = int(data.get("total", 0))
            real = int(data.get("real", 0))

            return {
                "total_orders": total,
                "real_orders": real,
                "wash_orders": int(data.get("wash", 0)),
                "real_order_ratio": real / max(1, total),
            }

        except Exception as e:
            logging.error(f"获取订单统计失败: {e}")
            return {}

    async def _get_volume_stats(self, strategy: str) -> Dict[str, Any]:
        """获取交易量统计"""
        try:
            symbol = f"{strategy}_usdt"
            stats_key = f"stats:{symbol}:trades"

            data = await self.redis.hgetall(stats_key)

            total_volume = float(data.get("total_volume", 0))
            real_volume = float(data.get("real_volume", 0))

            return {
                "total_volume": total_volume,
                "real_volume": real_volume,
                "wash_volume": float(data.get("wash_volume", 0)),
                "real_volume_ratio": real_volume / max(1, total_volume),
            }

        except Exception as e:
            logging.error(f"获取交易量统计失败: {e}")
            return {}

    async def _get_pnl_stats(self, strategy: str) -> Dict[str, Any]:
        """获取盈亏统计"""
        try:
            # 从Redis获取今日PnL
            pnl_key = f"pnl:{strategy}:{datetime.now().strftime('%Y%m%d')}"
            daily_pnl = float(await self.redis.get(pnl_key) or 0)

            # 获取初始资金
            capital_key = f"capital:{strategy}"
            initial_capital = float(await self.redis.get(capital_key) or 100000)

            return {
                "daily_pnl": daily_pnl,
                "daily_pnl_pct": daily_pnl / initial_capital
                if initial_capital > 0
                else 0,
                "initial_capital": initial_capital,
            }

        except Exception as e:
            logging.error(f"获取盈亏统计失败: {e}")
            return {}

    async def _get_inventory_stats(self, strategy: str) -> Dict[str, Any]:
        """获取库存统计"""
        try:
            # 从Redis获取当前库存
            inventory_key = f"inventory:{strategy}"
            data = await self.redis.hgetall(inventory_key)

            current_amount = float(data.get("amount", 0))
            target_amount = float(data.get("target", 0))

            ratio = current_amount / target_amount if target_amount > 0 else 0.5

            # 获取净值计算库存价值
            symbol = f"{strategy}_usdt"
            net_value = float(await self.redis.get(f"netvalue_{strategy}") or 1.0)

            return {
                "amount": current_amount,
                "target": target_amount,
                "ratio": ratio,
                "value": current_amount * net_value,
            }

        except Exception as e:
            logging.error(f"获取库存统计失败: {e}")
            return {"ratio": 0.5, "value": 0}

    async def _get_spread_stats(self, strategy: str) -> Dict[str, Any]:
        """获取价差统计"""
        try:
            spread_key = f"spread:{strategy}"
            data = await self.redis.hgetall(spread_key)

            return {
                "current": float(data.get("current", 0.01)),
                "average": float(data.get("average", 0.01)),
                "min": float(data.get("min", 0.005)),
                "max": float(data.get("max", 0.05)),
            }

        except Exception as e:
            logging.error(f"获取价差统计失败: {e}")
            return {"current": 0.01, "average": 0.01}

    async def check_alerts(self):
        """检查告警条件"""
        try:
            current_time = datetime.now()

            for strategy, metrics in self.metrics.items():
                # 检查日亏损
                if (
                    metrics.get("daily_pnl_pct", 0)
                    < -self.thresholds["max_loss_per_day"]
                ):
                    await self._add_alert(
                        strategy,
                        "HIGH",
                        f"日亏损超过{self.thresholds['max_loss_per_day'] * 100}%: "
                        f"{metrics['daily_pnl_pct'] * 100:.2f}%",
                    )

                # 检查真实交易量
                if (
                    metrics.get("real_volume_ratio", 0)
                    < self.thresholds["min_real_volume_ratio"]
                ):
                    await self._add_alert(
                        strategy,
                        "MEDIUM",
                        f"真实交易量比例过低: {metrics['real_volume_ratio'] * 100:.2f}%",
                    )

                # 检查价差
                if metrics.get("current_spread", 0) > self.thresholds["max_spread"]:
                    await self._add_alert(
                        strategy,
                        "LOW",
                        f"价差过大: {metrics['current_spread'] * 100:.2f}%",
                    )

                # 检查库存
                inventory_ratio = metrics.get("inventory_ratio", 0.5)
                if inventory_ratio > self.thresholds[
                    "max_inventory_ratio"
                ] or inventory_ratio < (1 - self.thresholds["max_inventory_ratio"]):
                    await self._add_alert(
                        strategy,
                        "MEDIUM",
                        f"库存偏离过大: {inventory_ratio * 100:.2f}%",
                    )

        except Exception as e:
            logging.error(f"检查告警失败: {e}")

    async def _add_alert(self, strategy: str, level: str, message: str):
        """添加告警"""
        alert = {
            "timestamp": datetime.now(),
            "strategy": strategy,
            "level": level,
            "message": message,
        }

        self.alerts.append(alert)

        # 保留最近100条告警
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]

        # 发布到Redis供其他系统使用
        alert_key = f"alerts:{strategy}"
        await self.redis.lpush(
            alert_key,
            json.dumps({
                "timestamp": alert["timestamp"].isoformat(),
                "level": level,
                "message": message,
            }),
        )
        await self.redis.ltrim(alert_key, 0, 99)

        logging.warning(f"[{level}] {strategy}: {message}")

    async def record_performance(self):
        """记录性能数据"""
        try:
            # 计算汇总指标
            total_pnl = sum(m.get("daily_pnl", 0) for m in self.metrics.values())
            total_volume = sum(m.get("total_volume", 0) for m in self.metrics.values())
            avg_real_ratio = np.mean([
                m.get("real_volume_ratio", 0) for m in self.metrics.values()
            ])

            performance = {
                "timestamp": datetime.now(),
                "total_pnl": total_pnl,
                "total_volume": total_volume,
                "avg_real_volume_ratio": avg_real_ratio,
                "active_strategies": len([
                    s for s, m in self.metrics.items() if m.get("total_orders", 0) > 0
                ]),
                "metrics": dict(self.metrics),
            }

            self.performance_history.append(performance)

            # 保留最近24小时的数据
            cutoff_time = datetime.now() - timedelta(hours=24)
            self.performance_history = [
                p for p in self.performance_history if p["timestamp"] > cutoff_time
            ]

        except Exception as e:
            logging.error(f"记录性能数据失败: {e}")

    async def publish_monitoring_data(self):
        """发布监控数据到Redis"""
        try:
            # 发布当前指标
            monitor_key = "monitor:current"
            await self.redis.hset(
                monitor_key,
                mapping={
                    "timestamp": datetime.now().isoformat(),
                    "metrics": json.dumps(dict(self.metrics)),
                    "alerts_count": len(self.alerts),
                    "last_update": datetime.now().isoformat(),
                },
            )

            # 发布性能历史（最近1小时）
            recent_history = [
                p
                for p in self.performance_history
                if p["timestamp"] > datetime.now() - timedelta(hours=1)
            ]

            history_key = "monitor:history"
            await self.redis.set(
                history_key,
                json.dumps([
                    {**p, "timestamp": p["timestamp"].isoformat()}
                    for p in recent_history
                ]),
            )

        except Exception as e:
            logging.error(f"发布监控数据失败: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """获取监控摘要"""
        return {
            "strategies": list(self.metrics.keys()),
            "total_pnl": sum(m.get("daily_pnl", 0) for m in self.metrics.values()),
            "avg_real_volume_ratio": np.mean([
                m.get("real_volume_ratio", 0) for m in self.metrics.values()
            ]),
            "active_alerts": len([
                a for a in self.alerts if a["level"] in ["HIGH", "MEDIUM"]
            ]),
            "last_update": datetime.now().isoformat(),
        }

    def update_thresholds(self, new_thresholds: Dict[str, float]):
        """更新告警阈值"""
        self.thresholds.update(new_thresholds)
        logging.info(f"告警阈值更新: {self.thresholds}")


async def main():
    """主函数 - 用于测试"""
    monitor = RealTimeMonitor()
    await monitor.start_monitoring()


if __name__ == "__main__":
    asyncio.run(main())
