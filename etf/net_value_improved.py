# -*- coding:utf-8 -*-

"""
改进版净值计算器
- 支持断线重连后的净值恢复
- 记录详细的时间戳信息
- 管理费精确计算
- 异常保护机制

Author: AllenBrother
Date:   2024/12/19
"""

import json
import time
import redis
import asyncio
from typing import Dict, Optional, List, Tuple, TYPE_CHECKING
from loguru import logger
from datetime import datetime, timedelta

from etf.xt import Spot
from etf.utils.ds import Queue
from etf.alert import send_alert, AlertLevel

# 类型提示（避免循环导入）
if TYPE_CHECKING:
    from etf.observability.metrics import MetricsCollector


class ImprovedNetValue:
    """改进版净值计算器"""

    def __init__(
        self,
        symbol: str,
        m_lever: int,
        init_net_value: float = 1.0,
        daily_fee: float = 0.001,
        time_gap_second: int = 10,
        rebalance: float = 0.05,
        long: bool = True,
        max_single_change: float = 0.10,  # 最大单次变化率限制
        max_restart_gap: int = 300,  # 最大重启间隔（秒）
        metrics_collector: Optional['MetricsCollector'] = None,  # OpenTelemetry 指标收集器
    ):
        self.symbol = symbol
        self.m_lever = m_lever
        self.long = long
        self.rebalance = rebalance
        self.time_gap_second = time_gap_second
        self.daily_fee = daily_fee
        self.time_gap_fee = daily_fee / (24 * 60 * 60) * time_gap_second
        self.max_single_change = max_single_change
        self.max_restart_gap = max_restart_gap
        self.metrics_collector = metrics_collector  # OpenTelemetry 指标收集器

        # Redis连接
        self.r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

        # Redis键名
        direction = "l" if self.long else "s"
        self.redis_key = (
            f"netvalue_{self.symbol.split('_')[0]}{self.m_lever}{direction}"
        )
        self.redis_detail_key = f"{self.redis_key}_detail"
        self.redis_history_key = f"{self.redis_key}_history"

        # 价格队列
        self.underlying_mid_price_queue = Queue(2)

        # 初始化净值数据
        self.net_value_data = self._init_net_value(init_net_value)

        # 交易所客户端
        self.spot_client = Spot(
            host="https://sapi.xt.com", access_key="", secret_key=""
        )

        logger.info(
            f"净值计算器初始化完成: {self.symbol}, 杠杆: {self.m_lever}x, 方向: {'做多' if self.long else '做空'}"
        )

    def _init_net_value(self, default_value: float) -> Dict:
        """初始化净值数据"""
        try:
            # 尝试从Redis读取详细数据
            detail_data = self.r.get(self.redis_detail_key)
            if detail_data:
                data = json.loads(detail_data)
                logger.info(f"从Redis恢复净值数据: {data}")

                # 检查是否需要恢复
                last_update = data.get("last_update_ts", 0)
                gap_seconds = time.time() - last_update

                if gap_seconds > 30:
                    logger.warning(f"检测到程序重启，断线时间: {gap_seconds:.1f}秒")
                    # 恢复净值
                    self._recover_net_value(data, gap_seconds)

                return data
            else:
                # 尝试读取简单净值
                simple_value = self.r.get(self.redis_key)
                if simple_value:
                    net_value = float(simple_value)
                else:
                    net_value = default_value

                # 创建新的数据结构
                data = {
                    "net_value": net_value,
                    "last_price": None,
                    "last_update_ts": time.time(),
                    "create_ts": time.time(),
                    "update_count": 0,
                    "total_fee_deducted": 0.0,
                    "abnormal_events": [],
                }

                # 保存到Redis
                self._save_to_redis(data)
                return data

        except Exception as e:
            logger.error(f"初始化净值数据失败: {e}")
            return {
                "net_value": default_value,
                "last_price": None,
                "last_update_ts": time.time(),
                "create_ts": time.time(),
                "update_count": 0,
                "total_fee_deducted": 0.0,
                "abnormal_events": [],
            }

    def _save_to_redis(self, data: Dict):
        """保存数据到Redis"""
        try:
            # 保存简单净值（兼容旧版本）
            self.r.set(self.redis_key, str(data["net_value"]))

            # 保存详细数据
            self.r.set(self.redis_detail_key, json.dumps(data))

            # 保存到历史记录
            history_data = {
                "net_value": data["net_value"],
                "price": data.get("last_price"),
                "timestamp": data["last_update_ts"],
            }
            self.r.lpush(self.redis_history_key, json.dumps(history_data))
            self.r.ltrim(self.redis_history_key, 0, 1000)  # 保留最近1000条

        except Exception as e:
            logger.error(f"保存数据到Redis失败: {e}")

    def _recover_net_value(self, data: Dict, gap_seconds: float):
        """恢复断线期间的净值"""
        if gap_seconds > self.max_restart_gap:
            logger.error(
                f"断线时间过长({gap_seconds:.1f}秒)，超过最大限制({self.max_restart_gap}秒)"
            )
            data["abnormal_events"].append({
                "type": "long_restart",
                "gap_seconds": gap_seconds,
                "timestamp": time.time(),
            })
            return

        try:
            # 获取历史K线数据来补算净值
            # 这里简化处理，实际应该调用交易所API获取K线
            logger.info(f"尝试恢复{gap_seconds:.1f}秒的净值变化")

            # 补扣管理费
            missed_intervals = int(gap_seconds / self.time_gap_second)
            if missed_intervals > 0:
                total_fee_rate = (
                    self.daily_fee
                    / (24 * 60 * 60)
                    * (missed_intervals * self.time_gap_second)
                )
                data["net_value"] *= 1 - total_fee_rate
                data["total_fee_deducted"] += total_fee_rate
                logger.info(
                    f"补扣管理费: {total_fee_rate:.6f}, 影响净值: {total_fee_rate * data['net_value']:.6f}"
                )

            # 记录恢复事件
            data["abnormal_events"].append({
                "type": "recovery",
                "gap_seconds": gap_seconds,
                "missed_intervals": missed_intervals,
                "timestamp": time.time(),
            })
            
            # 发送恢复告警
            asyncio.create_task(send_alert(
                "net_value_recovery",
                {
                    "event_type": "net_value_recovery",
                    "gap_seconds": gap_seconds,
                    "missed_intervals": missed_intervals,
                    "symbol": self.symbol,
                    "leverage": self.m_lever,
                    "direction": "做多" if self.long else "做空",
                    "old_net_value": data["net_value"],
                    "management_fee_deducted": total_fee_rate * data["net_value"]
                },
                strategy_name=f"{self.symbol}{self.m_lever}{'l' if self.long else 's'}"
            ))

        except Exception as e:
            logger.error(f"恢复净值失败: {e}")

    def update_mid_price(self) -> Optional[float]:
        """更新中间价"""
        try:
            depth = self.spot_client.get_depth(symbol=self.symbol, limit=5)
            if depth and "bids" in depth and "asks" in depth:
                bid_0_price = float(depth["bids"][0][0])
                ask_0_price = float(depth["asks"][0][0])
                mid_price = (bid_0_price + ask_0_price) / 2
                logger.debug(f"{self.symbol} 中间价: {mid_price}")
                return mid_price
            else:
                logger.error(f"获取{self.symbol}市场深度失败")
                return None
        except Exception as e:
            logger.error(f"更新中间价失败: {e}")
            return None

    def cal_net_value(self) -> Optional[float]:
        """计算净值"""
        if len(self.underlying_mid_price_queue) != 2:
            logger.debug("价格队列未满，跳过计算")
            return None

        p0 = self.underlying_mid_price_queue.get(0)
        p1 = self.underlying_mid_price_queue.get(1)

        # 检查价格有效性
        if p0 <= 0 or p1 <= 0:
            logger.error(f"无效的价格数据: p0={p0}, p1={p1}")
            return None

        # 计算价格变化率
        v = (p1 - p0) / p0

        # 异常保护：限制单次最大变化
        if abs(v) > self.max_single_change:
            logger.warning(f"价格变化过大: {v:.4f}, 限制为: {self.max_single_change}")
            self.net_value_data["abnormal_events"].append({
                "type": "price_spike",
                "change_rate": v,
                "p0": p0,
                "p1": p1,
                "timestamp": time.time(),
            })
            
            # 发送异常价格告警
            asyncio.create_task(send_alert(
                "abnormal_price",
                {
                    "price_change_rate": abs(v),
                    "symbol": self.symbol,
                    "old_price": p0,
                    "new_price": p1,
                    "leverage": self.m_lever,
                    "direction": "做多" if self.long else "做空"
                },
                strategy_name=f"{self.symbol}{self.m_lever}{'l' if self.long else 's'}"
            ))
            
            v = self.max_single_change if v > 0 else -self.max_single_change
            # 调整p1为限制后的价格，用于后续再平衡计算
            p1 = p0 * (1 + v)

        # 计算净值变化
        side = 1 if v > 0 else -1
        net_value = self.net_value_data["net_value"]

        # 处理再平衡
        while abs(v) > self.rebalance:
            adjustment = side * self.rebalance
            p0 = p0 * (1 + adjustment)

            # 按照原版逻辑计算再平衡时的净值变化
            if self.long:
                # 做多：价格上涨净值增加，价格下跌净值减少
                net_value = net_value * (1 + self.m_lever * adjustment)
            else:
                # 做空：价格上涨净值减少，价格下跌净值增加
                net_value = net_value * (1 - self.m_lever * adjustment)

            v = (p1 - p0) / p0
            logger.info(
                f"触发再平衡: 调整幅度={adjustment:.4f}, 新净值={net_value:.6f}"
            )

        # 正常净值变化
        if self.long:
            net_value = net_value * (1 + self.m_lever * v)
        else:
            net_value = net_value * (1 - self.m_lever * v)

        logger.debug(f"净值计算: 价格变化={v:.4f}, 新净值={net_value:.6f}")
        return net_value

    def cal_fee(self, net_value: float) -> float:
        """计算扣除管理费后的净值"""
        net_value_after_fee = net_value * (1 - self.time_gap_fee)
        fee_amount = net_value - net_value_after_fee
        self.net_value_data["total_fee_deducted"] += self.time_gap_fee
        logger.debug(f"扣除管理费: {fee_amount:.6f}, 费率: {self.time_gap_fee:.6f}")
        return net_value_after_fee

    def run(self):
        """主运行循环"""
        logger.info(f"净值计算器开始运行: {self.symbol}")

        while True:
            try:
                # 获取最新价格
                mid_price = self.update_mid_price()
                if not mid_price:
                    time.sleep(1)
                    continue

                # 更新价格队列
                self.underlying_mid_price_queue.put(mid_price)

                # 初始化时需要等待第二个价格
                if self.net_value_data["last_price"] is None:
                    self.net_value_data["last_price"] = mid_price
                    logger.info(f"初始价格: {mid_price}")
                    time.sleep(self.time_gap_second)
                    continue

                # 计算净值
                net_value = self.cal_net_value()
                if net_value is None:
                    time.sleep(self.time_gap_second)
                    continue

                # 扣除管理费
                net_value_after_fee = self.cal_fee(net_value)
                
                # 计算净值变化率
                old_net_value = self.net_value_data["net_value"]
                net_value_change_rate = (net_value_after_fee - old_net_value) / old_net_value if old_net_value > 0 else 0

                # 更新数据
                self.net_value_data.update({
                    "net_value": net_value_after_fee,
                    "last_price": mid_price,
                    "last_update_ts": time.time(),
                    "update_count": self.net_value_data["update_count"] + 1,
                })

                # 保存到Redis
                self._save_to_redis(self.net_value_data)

                # 📊 记录净值指标（OpenTelemetry）
                if self.metrics_collector:
                    try:
                        strategy_name = f"{self.symbol.split('_')[0]}{self.m_lever}{'l' if self.long else 's'}"
                        self.metrics_collector.record_net_value(
                            value=net_value_after_fee,
                            strategy=strategy_name,
                            leverage=self.m_lever,
                            direction="long" if self.long else "short",
                            change_rate=net_value_change_rate
                        )
                    except Exception as e:
                        logger.error(f"记录净值指标失败: {e}")

                logger.info(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"净值更新: {net_value_after_fee:.6f}, "
                    f"价格: {mid_price:.4f}, "
                    f"变化率: {net_value_change_rate:.4%}, "
                    f"更新次数: {self.net_value_data['update_count']}"
                )
                
                # 检查净值异常
                if abs(net_value_change_rate) > 0.05:  # 5% 变化
                    asyncio.create_task(send_alert(
                        "net_value_spike" if net_value_change_rate > 0 else "net_value_crash",
                        {
                            "net_value_change_rate": net_value_change_rate,
                            "symbol": self.symbol,
                            "old_net_value": old_net_value,
                            "new_net_value": net_value_after_fee,
                            "leverage": self.m_lever,
                            "direction": "做多" if self.long else "做空"
                        },
                        strategy_name=f"{self.symbol}{self.m_lever}{'l' if self.long else 's'}"
                    ))

                # 等待下一个周期
                time.sleep(self.time_gap_second)

            except KeyboardInterrupt:
                logger.info("收到退出信号，保存数据并退出")
                self._save_to_redis(self.net_value_data)
                break
            except Exception as e:
                logger.error(f"运行异常: {e}", exc_info=True)
                time.sleep(1)


if __name__ == "__main__":
    # 测试配置
    config = {
        "symbol": "stg_usdt",
        "m_lever": 3,
        "long": True,
        "time_gap_second": 10,
        "rebalance": 0.05,
        "daily_fee": 0.001,
        "max_single_change": 0.10,  # 最大单次10%变化
        "max_restart_gap": 300,  # 最大5分钟重启间隔
    }

    calculator = ImprovedNetValue(
        symbol=config["symbol"],
        m_lever=config["m_lever"],
        long=config["long"],
        time_gap_second=config["time_gap_second"],
        rebalance=config["rebalance"],
        daily_fee=config["daily_fee"],
        max_single_change=config["max_single_change"],
        max_restart_gap=config["max_restart_gap"],
    )

    calculator.run()
