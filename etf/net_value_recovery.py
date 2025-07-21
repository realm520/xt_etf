# -*- coding:utf-8 -*-

"""
净值恢复工具
用于程序重启后恢复断线期间的净值变化

Author: AllenBrother
Date:   2024/12/19
"""

import time
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
from loguru import logger

from etf.exchange.xt import Spot


class NetValueRecovery:
    """净值恢复工具类"""

    def __init__(
        self, symbol: str, m_lever: int, rebalance: float = 0.05, long: bool = True
    ):
        self.symbol = symbol
        self.m_lever = m_lever
        self.rebalance = rebalance
        self.long = long
        self.spot_client = Spot(
            host="https://sapi.xt.com", access_key="", secret_key=""
        )

    def get_klines(
        self, start_time: int, end_time: int, interval: str = "1m"
    ) -> List[Dict]:
        """
        获取K线数据

        Args:
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            interval: K线周期（1m, 5m, 15m等）

        Returns:
            K线数据列表
        """
        try:
            # XT交易所的K线接口
            # 注意：这里需要根据实际的XT API文档调整参数
            params = {
                "symbol": self.symbol,
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time,
                "limit": 1000,  # 最多获取1000条
            }

            # 模拟K线数据格式
            # 实际应该调用 self.spot_client.get_klines(**params)
            logger.info(
                f"获取K线数据: {self.symbol}, 时间范围: {start_time} - {end_time}"
            )

            # 返回模拟数据用于测试
            # 格式: [时间戳, 开盘价, 最高价, 最低价, 收盘价, 成交量]
            return []

        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return []

    def calculate_price_changes(
        self, klines: List[Dict]
    ) -> List[Tuple[float, float, float]]:
        """
        计算每个K线的价格变化

        Args:
            klines: K线数据

        Returns:
            [(时间戳, 价格, 变化率), ...]
        """
        if not klines:
            return []

        changes = []
        prev_close = None

        for kline in klines:
            timestamp = kline[0] / 1000  # 转换为秒
            close_price = float(kline[4])

            if prev_close is not None:
                change_rate = (close_price - prev_close) / prev_close
                changes.append((timestamp, close_price, change_rate))
            else:
                changes.append((timestamp, close_price, 0.0))

            prev_close = close_price

        return changes

    def recover_net_value(
        self,
        initial_net_value: float,
        last_price: float,
        last_update_ts: float,
        current_ts: float,
        daily_fee: float = 0.001,
    ) -> Tuple[float, float, List[Dict]]:
        """
        恢复断线期间的净值

        Args:
            initial_net_value: 断线前的净值
            last_price: 断线前的最后价格
            last_update_ts: 上次更新时间戳（秒）
            current_ts: 当前时间戳（秒）
            daily_fee: 日管理费率

        Returns:
            (恢复后的净值, 当前价格, 恢复过程记录)
        """
        gap_seconds = current_ts - last_update_ts
        recovery_log = []

        logger.info(f"开始恢复净值，断线时长: {gap_seconds:.1f}秒")

        # 获取当前价格
        try:
            depth = self.spot_client.get_depth(symbol=self.symbol, limit=1)
            if depth and "bids" in depth and "asks" in depth:
                current_price = (
                    float(depth["bids"][0][0]) + float(depth["asks"][0][0])
                ) / 2
            else:
                logger.error("无法获取当前价格，使用历史价格")
                current_price = last_price
        except Exception as e:
            logger.error(f"获取当前价格失败: {e}")
            current_price = last_price

        # 如果断线时间很短，直接计算
        if gap_seconds < 60:
            # 简单线性插值
            price_change = (current_price - last_price) / last_price
            net_value = self._calculate_net_value_change(
                initial_net_value, price_change
            )

            # 扣除管理费
            fee_rate = daily_fee * gap_seconds / (24 * 60 * 60)
            net_value *= 1 - fee_rate

            recovery_log.append({
                "method": "linear_interpolation",
                "gap_seconds": gap_seconds,
                "price_change": price_change,
                "fee_deducted": fee_rate,
            })

            return net_value, current_price, recovery_log

        # 断线时间较长，使用K线数据恢复
        start_time = int(last_update_ts * 1000)
        end_time = int(current_ts * 1000)

        # 根据断线时长选择K线周期
        if gap_seconds < 3600:  # 1小时内
            interval = "1m"
        elif gap_seconds < 7200:  # 2小时内
            interval = "5m"
        else:
            interval = "15m"

        klines = self.get_klines(start_time, end_time, interval)

        if not klines:
            # 无法获取K线，使用简单计算
            logger.warning("无法获取K线数据，使用简单计算")
            return self._simple_recovery(
                initial_net_value, last_price, current_price, gap_seconds, daily_fee
            )

        # 基于K线数据恢复
        net_value = initial_net_value
        price_changes = self.calculate_price_changes(klines)

        for timestamp, price, change_rate in price_changes:
            if change_rate != 0:
                net_value = self._calculate_net_value_change(net_value, change_rate)

                recovery_log.append({
                    "timestamp": timestamp,
                    "price": price,
                    "change_rate": change_rate,
                    "net_value": net_value,
                })

        # 扣除总管理费
        total_fee_rate = daily_fee * gap_seconds / (24 * 60 * 60)
        net_value *= 1 - total_fee_rate

        recovery_log.append({
            "method": "kline_based",
            "gap_seconds": gap_seconds,
            "kline_count": len(klines),
            "total_fee_deducted": total_fee_rate,
        })

        return net_value, current_price, recovery_log

    def _calculate_net_value_change(
        self, net_value: float, price_change: float
    ) -> float:
        """计算净值变化（考虑再平衡）"""
        # 处理再平衡
        remaining_change = price_change
        current_net_value = net_value

        while abs(remaining_change) > self.rebalance:
            # 再平衡
            adjustment = self.rebalance if remaining_change > 0 else -self.rebalance

            if self.long:
                current_net_value *= 1 + self.m_lever * adjustment
            else:
                current_net_value *= 1 - self.m_lever * adjustment

            remaining_change -= adjustment

        # 处理剩余变化
        if self.long:
            current_net_value *= 1 + self.m_lever * remaining_change
        else:
            current_net_value *= 1 - self.m_lever * remaining_change

        return current_net_value

    def _simple_recovery(
        self,
        initial_net_value: float,
        last_price: float,
        current_price: float,
        gap_seconds: float,
        daily_fee: float,
    ) -> Tuple[float, float, List[Dict]]:
        """简单恢复方法（无K线数据时使用）"""
        # 计算总价格变化
        total_change = (current_price - last_price) / last_price

        # 估算分段数（假设每分钟一次更新）
        segments = max(1, int(gap_seconds / 60))
        change_per_segment = total_change / segments

        net_value = initial_net_value
        recovery_log = []

        # 分段计算，避免单次变化过大
        for i in range(segments):
            net_value = self._calculate_net_value_change(net_value, change_per_segment)

            if i % 10 == 0:  # 每10段记录一次
                recovery_log.append({
                    "segment": i,
                    "net_value": net_value,
                    "accumulated_change": change_per_segment * (i + 1),
                })

        # 扣除管理费
        fee_rate = daily_fee * gap_seconds / (24 * 60 * 60)
        net_value *= 1 - fee_rate

        recovery_log.append({
            "method": "simple_segmented",
            "gap_seconds": gap_seconds,
            "segments": segments,
            "total_change": total_change,
            "fee_deducted": fee_rate,
        })

        return net_value, current_price, recovery_log


def test_recovery():
    """测试净值恢复功能"""
    recovery = NetValueRecovery(symbol="stg_usdt", m_lever=3, rebalance=0.05, long=True)

    # 模拟断线5分钟的情况
    initial_net_value = 1.0
    last_price = 100.0
    last_update = time.time() - 300  # 5分钟前
    current_time = time.time()

    net_value, current_price, log = recovery.recover_net_value(
        initial_net_value=initial_net_value,
        last_price=last_price,
        last_update_ts=last_update,
        current_ts=current_time,
        daily_fee=0.001,
    )

    logger.info(f"恢复结果: 净值={net_value:.6f}, 当前价格={current_price:.4f}")
    logger.info(f"恢复日志: {log}")


if __name__ == "__main__":
    test_recovery()
