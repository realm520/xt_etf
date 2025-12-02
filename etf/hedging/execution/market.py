"""
市价单执行器

使用市价单保证成交，包含重试机制和滑点控制。
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Optional

from .base import OrderExecutor, ExecutionResult, OrderStatus

logger = logging.getLogger(__name__)


class MarketOrderExecutor(OrderExecutor):
    """
    市价单执行器

    使用市价单确保订单成交，提供：
    - 自动重试机制（指数退避）
    - 滑点监控和告警
    - 部分成交处理
    - 详细的执行日志

    Args:
        client: Binance客户端实例
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔（秒），默认1.0秒
        slippage_tolerance: 滑点容忍度，默认0.01（1%）
        timeout: 订单超时时间（秒），默认30秒

    Examples:
        executor = MarketOrderExecutor(client)
        result = await executor.execute("TONUSDT", "BUY", Decimal("100"))
    """

    # 永久错误码，不进行重试
    PERMANENT_ERRORS = {
        "-2010",  # Insufficient balance
        "-1013",  # Invalid quantity
        "-1111",  # Precision error
        "-1121",  # Invalid symbol
    }

    # 可重试错误码
    RETRYABLE_ERRORS = {
        "-1001",  # Disconnected
        "-1003",  # Rate limit
        "-1015",  # Too many orders
        "-1016",  # Service unavailable
    }

    def __init__(
        self,
        client,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        slippage_tolerance: float = 0.01,
        timeout: float = 30.0,
    ):
        if max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got {max_retries}")
        if retry_delay <= 0:
            raise ValueError(f"retry_delay must be positive, got {retry_delay}")
        if slippage_tolerance < 0 or slippage_tolerance > 1:
            raise ValueError(f"slippage_tolerance must be between 0 and 1, got {slippage_tolerance}")

        self.client = client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.slippage_tolerance = slippage_tolerance
        self.timeout = timeout

        logger.info(
            f"MarketOrderExecutor 初始化: max_retries={max_retries}, "
            f"retry_delay={retry_delay}s, slippage_tolerance={slippage_tolerance:.1%}"
        )

    async def execute(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Optional[Decimal] = None
    ) -> ExecutionResult:
        """
        执行市价单

        Args:
            symbol: 交易对 (例如: "TONUSDT")
            side: 交易方向 ('BUY' 或 'SELL')
            quantity: 交易数量
            price: 参考价格（用于滑点计算，非下单价格）

        Returns:
            ExecutionResult: 执行结果
        """
        if side not in ("BUY", "SELL"):
            return ExecutionResult(
                success=False,
                status=OrderStatus.REJECTED,
                error_message=f"Invalid side: {side}",
                error_code="INVALID_SIDE"
            )

        if quantity <= 0:
            return ExecutionResult(
                success=False,
                status=OrderStatus.REJECTED,
                error_message=f"Invalid quantity: {quantity}",
                error_code="INVALID_QUANTITY"
            )

        start_time = time.time()
        last_error = None
        last_error_code = None

        for attempt in range(self.max_retries + 1):
            try:
                logger.info(
                    f"执行市价单: {side} {quantity} {symbol} "
                    f"(尝试 {attempt + 1}/{self.max_retries + 1})"
                )

                # 调用Binance API创建市价单
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type="MARKET",
                    quantity=float(quantity),
                )

                # 解析执行结果
                result = self._parse_order_response(order, price, attempt + 1, start_time)

                if result.success:
                    logger.info(
                        f"市价单成交: {side} {result.filled_qty} {symbol} @ {result.filled_price}, "
                        f"耗时={result.execution_time:.3f}s"
                    )

                    # 滑点检查
                    if price and result.filled_price > 0:
                        self._check_slippage(side, price, result.filled_price)

                return result

            except Exception as e:
                error_str = str(e)
                error_code = self._extract_error_code(error_str)
                last_error = error_str
                last_error_code = error_code

                logger.warning(
                    f"市价单执行失败 (尝试 {attempt + 1}): {error_str}"
                )

                # 检查是否为永久错误
                if error_code in self.PERMANENT_ERRORS:
                    logger.error(f"永久错误，停止重试: {error_code}")
                    break

                # 检查是否需要重试
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** attempt)  # 指数退避
                    logger.info(f"等待 {delay:.1f}s 后重试...")
                    await asyncio.sleep(delay)

        # 所有重试都失败
        execution_time = time.time() - start_time
        return ExecutionResult(
            success=False,
            status=OrderStatus.FAILED,
            error_message=last_error,
            error_code=last_error_code,
            attempts=self.max_retries + 1,
            execution_time=execution_time,
        )

    async def cancel(self, symbol: str, order_id: str) -> bool:
        """
        取消订单

        市价单通常立即成交，很少需要取消。
        """
        try:
            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"订单已取消: {order_id}")
            return True
        except Exception as e:
            logger.warning(f"取消订单失败: {e}")
            return False

    async def get_order_status(self, symbol: str, order_id: str) -> ExecutionResult:
        """查询订单状态"""
        try:
            order = self.client.futures_get_order(symbol=symbol, orderId=order_id)
            return self._parse_order_response(order, None, 1, 0)
        except Exception as e:
            return ExecutionResult(
                success=False,
                status=OrderStatus.FAILED,
                error_message=str(e),
            )

    def _parse_order_response(
        self,
        order: dict,
        reference_price: Optional[Decimal],
        attempts: int,
        start_time: float
    ) -> ExecutionResult:
        """解析订单响应"""
        execution_time = time.time() - start_time if start_time > 0 else 0

        # 解析状态
        status_str = order.get("status", "UNKNOWN")
        status_map = {
            "NEW": OrderStatus.PENDING,
            "FILLED": OrderStatus.FILLED,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "CANCELED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.EXPIRED,
        }
        status = status_map.get(status_str, OrderStatus.PENDING)

        # 解析成交信息
        filled_qty = Decimal(str(order.get("executedQty", 0)))

        # 计算成交均价
        cum_quote = order.get("cumQuote") or order.get("cummulativeQuoteQty", 0)
        if filled_qty > 0 and cum_quote:
            filled_price = Decimal(str(cum_quote)) / filled_qty
        else:
            filled_price = Decimal(str(order.get("avgPrice", 0)))

        # 计算剩余数量
        orig_qty = Decimal(str(order.get("origQty", 0)))
        remaining_qty = orig_qty - filled_qty if orig_qty > filled_qty else Decimal("0")

        success = status == OrderStatus.FILLED

        return ExecutionResult(
            success=success,
            order_id=str(order.get("orderId", "")),
            status=status,
            filled_qty=filled_qty,
            filled_price=filled_price,
            remaining_qty=remaining_qty,
            attempts=attempts,
            execution_time=execution_time,
        )

    def _check_slippage(
        self,
        side: str,
        reference_price: Decimal,
        filled_price: Decimal
    ) -> None:
        """检查滑点"""
        if reference_price <= 0:
            return

        if side == "BUY":
            slippage = (filled_price - reference_price) / reference_price
        else:
            slippage = (reference_price - filled_price) / reference_price

        if slippage > self.slippage_tolerance:
            logger.warning(
                f"滑点超过阈值: {slippage:.2%} > {self.slippage_tolerance:.2%} "
                f"(参考价={reference_price}, 成交价={filled_price})"
            )
        elif slippage > 0:
            logger.debug(f"滑点: {slippage:.4%}")

    def _extract_error_code(self, error_str: str) -> Optional[str]:
        """从错误信息中提取错误码"""
        import re
        match = re.search(r'(-\d+)', error_str)
        return match.group(1) if match else None

    def get_name(self) -> str:
        return "MarketOrderExecutor"

    def get_config(self) -> dict:
        return {
            "name": self.get_name(),
            "type": "market",
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "slippage_tolerance": self.slippage_tolerance,
            "timeout": self.timeout,
        }
