"""
价格验证器

提供价格异常检测功能，防止因异常价格导致的错误对冲。
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from statistics import mean, stdev
from typing import Optional, Dict, Deque
from datetime import datetime

logger = logging.getLogger(__name__)


class PriceStatus(Enum):
    """价格状态枚举"""
    VALID = "VALID"           # 价格正常
    ABNORMAL = "ABNORMAL"     # 价格异常
    STALE = "STALE"           # 价格过时
    UNAVAILABLE = "UNAVAILABLE"  # 价格不可用


@dataclass
class ValidatedPrice:
    """
    验证后的价格数据

    Attributes:
        status: 价格状态
        price: 验证后的价格（异常时可能为None）
        confidence: 置信度 (0-1)
        reason: 状态原因说明
        original_price: 原始价格
        timestamp: 验证时间戳
    """
    status: PriceStatus
    price: Optional[Decimal]
    confidence: float
    reason: str
    original_price: Optional[Decimal] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """验证数据"""
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError(f"confidence must be between 0 and 1, got {self.confidence}")

    @property
    def is_valid(self) -> bool:
        """价格是否有效"""
        return self.status == PriceStatus.VALID

    @property
    def is_usable(self) -> bool:
        """价格是否可用（有效或置信度足够）"""
        return self.status == PriceStatus.VALID or (
            self.status == PriceStatus.ABNORMAL and self.confidence >= 0.5
        )

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "status": self.status.value,
            "price": float(self.price) if self.price else None,
            "confidence": self.confidence,
            "reason": self.reason,
            "original_price": float(self.original_price) if self.original_price else None,
            "timestamp": self.timestamp.isoformat(),
        }


class PriceValidator:
    """
    价格验证器

    提供多层次的价格异常检测：
    1. 价格突变检测：单次变化超过阈值
    2. 价格偏离检测：偏离历史均值过大
    3. 价格过期检测：长时间未更新

    Args:
        client: Binance客户端实例（可选，用于主动获取价格）
        max_price_change: 单次最大价格变化率，默认0.05（5%）
        max_deviation: 最大偏离均值比例，默认0.03（3%）
        history_size: 历史价格记录数量，默认20
        stale_threshold: 价格过期阈值（秒），默认60

    Examples:
        validator = PriceValidator(client)
        result = validator.validate_price("TONUSDT", Decimal("2.5"))
        if result.is_valid:
            # 使用价格
            pass
    """

    def __init__(
        self,
        client=None,
        max_price_change: float = 0.05,
        max_deviation: float = 0.03,
        history_size: int = 20,
        stale_threshold: float = 60.0,
    ):
        if max_price_change <= 0 or max_price_change > 1:
            raise ValueError(f"max_price_change must be between 0 and 1, got {max_price_change}")
        if max_deviation <= 0 or max_deviation > 1:
            raise ValueError(f"max_deviation must be between 0 and 1, got {max_deviation}")

        self.client = client
        self.max_price_change = max_price_change
        self.max_deviation = max_deviation
        self.history_size = history_size
        self.stale_threshold = stale_threshold

        # 每个交易对的价格历史和最后价格
        self.price_history: Dict[str, Deque[float]] = {}
        self.last_prices: Dict[str, tuple[Decimal, datetime]] = {}

        logger.info(
            f"PriceValidator 初始化: max_change={max_price_change:.1%}, "
            f"max_deviation={max_deviation:.1%}, history_size={history_size}"
        )

    def validate_price(
        self,
        symbol: str,
        current_price: Optional[Decimal] = None
    ) -> ValidatedPrice:
        """
        验证价格

        Args:
            symbol: 交易对
            current_price: 当前价格（可选，如不提供则从client获取）

        Returns:
            ValidatedPrice: 验证结果
        """
        # 获取价格
        if current_price is None:
            if self.client is None:
                return ValidatedPrice(
                    status=PriceStatus.UNAVAILABLE,
                    price=None,
                    confidence=0.0,
                    reason="无价格且无客户端",
                )
            try:
                ticker = self.client.futures_symbol_ticker(symbol=symbol)
                current_price = Decimal(str(ticker.get("price", 0)))
            except Exception as e:
                logger.warning(f"获取价格失败: {e}")
                return ValidatedPrice(
                    status=PriceStatus.UNAVAILABLE,
                    price=None,
                    confidence=0.0,
                    reason=f"获取价格失败: {e}",
                )

        if current_price <= 0:
            return ValidatedPrice(
                status=PriceStatus.ABNORMAL,
                price=None,
                confidence=0.0,
                reason=f"价格无效: {current_price}",
                original_price=current_price,
            )

        now = datetime.now()

        # 初始化价格历史
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.history_size)

        # 1. 检查价格突变
        if symbol in self.last_prices:
            last_price, last_time = self.last_prices[symbol]

            # 检查过期
            time_delta = (now - last_time).total_seconds()
            if time_delta > self.stale_threshold:
                logger.warning(f"{symbol} 价格过期: {time_delta:.1f}s > {self.stale_threshold}s")
                # 价格过期但仍可使用，重置历史
                self.price_history[symbol].clear()

            # 检查突变
            if last_price > 0:
                change = abs(float(current_price) - float(last_price)) / float(last_price)
                if change > self.max_price_change:
                    logger.warning(
                        f"{symbol} 价格突变: {change:.2%} > {self.max_price_change:.1%} "
                        f"({last_price} → {current_price})"
                    )
                    # 价格突变，降低置信度但不完全拒绝
                    confidence = max(0.3, 1.0 - change)
                    return ValidatedPrice(
                        status=PriceStatus.ABNORMAL,
                        price=current_price,
                        confidence=confidence,
                        reason=f"价格突变 {change:.2%}",
                        original_price=current_price,
                    )

        # 2. 检查偏离历史均值
        history = self.price_history[symbol]
        if len(history) >= 10:
            avg_price = mean(history)
            deviation = abs(float(current_price) - avg_price) / avg_price

            if deviation > self.max_deviation:
                logger.warning(
                    f"{symbol} 价格偏离: {deviation:.2%} > {self.max_deviation:.1%} "
                    f"(均值={avg_price:.4f}, 当前={current_price})"
                )
                # 偏离过大，降低置信度
                confidence = max(0.5, 1.0 - deviation)
                return ValidatedPrice(
                    status=PriceStatus.ABNORMAL,
                    price=current_price,
                    confidence=confidence,
                    reason=f"偏离均值 {deviation:.2%}",
                    original_price=current_price,
                )

        # 3. 检查波动率异常（如果有足够历史）
        if len(history) >= 10:
            try:
                volatility = stdev(history) / mean(history)
                # 如果波动率突然增大，也需警惕
                if volatility > 0.1:  # 10%波动率
                    logger.debug(f"{symbol} 高波动率: {volatility:.2%}")
            except Exception:
                pass  # 统计计算失败时忽略

        # 更新历史记录
        self.price_history[symbol].append(float(current_price))
        self.last_prices[symbol] = (current_price, now)

        return ValidatedPrice(
            status=PriceStatus.VALID,
            price=current_price,
            confidence=1.0,
            reason="价格正常",
            original_price=current_price,
        )

    def get_last_valid_price(self, symbol: str) -> Optional[Decimal]:
        """
        获取最后一个有效价格

        Args:
            symbol: 交易对

        Returns:
            最后有效价格，如果没有则返回None
        """
        if symbol in self.last_prices:
            price, _ = self.last_prices[symbol]
            return price
        return None

    def get_price_stats(self, symbol: str) -> Optional[dict]:
        """
        获取价格统计信息

        Args:
            symbol: 交易对

        Returns:
            统计信息字典，包含均值、标准差、最高价、最低价
        """
        history = self.price_history.get(symbol)
        if not history or len(history) < 2:
            return None

        prices = list(history)
        return {
            "mean": mean(prices),
            "stdev": stdev(prices) if len(prices) >= 2 else 0,
            "min": min(prices),
            "max": max(prices),
            "count": len(prices),
        }

    def reset(self, symbol: Optional[str] = None) -> None:
        """
        重置价格历史

        Args:
            symbol: 交易对，如果为None则重置所有
        """
        if symbol:
            if symbol in self.price_history:
                self.price_history[symbol].clear()
            if symbol in self.last_prices:
                del self.last_prices[symbol]
            logger.info(f"已重置 {symbol} 价格历史")
        else:
            self.price_history.clear()
            self.last_prices.clear()
            logger.info("已重置所有价格历史")
