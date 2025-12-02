"""
对冲监控器

提供对冲操作的记录、统计和审计功能。
"""

import csv
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, List

from ..strategies.base import HedgeDecision
from ..execution.base import ExecutionResult, OrderStatus

logger = logging.getLogger(__name__)


@dataclass
class HedgeRecord:
    """
    对冲记录数据类

    包含单次对冲操作的完整信息。
    """
    timestamp: datetime
    symbol: str
    strategy: str
    decision_direction: str
    decision_amount: Decimal
    decision_urgency: float
    decision_reason: str
    execution_success: bool
    execution_order_id: Optional[str]
    execution_filled_qty: Decimal
    execution_filled_price: Decimal
    execution_filled_value: Decimal
    execution_attempts: int
    execution_time: float
    error_message: Optional[str]
    xt_position_delta: Decimal
    current_hedge_position: Decimal
    price: Decimal
    price_status: str
    price_confidence: float

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "strategy": self.strategy,
            "decision_direction": self.decision_direction,
            "decision_amount": float(self.decision_amount),
            "decision_urgency": self.decision_urgency,
            "decision_reason": self.decision_reason,
            "execution_success": self.execution_success,
            "execution_order_id": self.execution_order_id,
            "execution_filled_qty": float(self.execution_filled_qty),
            "execution_filled_price": float(self.execution_filled_price),
            "execution_filled_value": float(self.execution_filled_value),
            "execution_attempts": self.execution_attempts,
            "execution_time": self.execution_time,
            "error_message": self.error_message,
            "xt_position_delta": float(self.xt_position_delta),
            "current_hedge_position": float(self.current_hedge_position),
            "price": float(self.price),
            "price_status": self.price_status,
            "price_confidence": self.price_confidence,
        }


@dataclass
class HedgeStats:
    """
    对冲统计数据

    汇总对冲操作的统计信息。
    """
    total_decisions: int = 0
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    skipped_decisions: int = 0
    total_hedged_value: Decimal = field(default_factory=lambda: Decimal("0"))
    total_attempts: int = 0
    avg_execution_time: float = 0.0
    price_abnormal_count: int = 0
    last_hedge_time: Optional[datetime] = None

    def to_dict(self) -> dict:
        """转换为字典格式"""
        success_rate = (
            self.successful_executions / self.total_executions * 100
            if self.total_executions > 0 else 0
        )
        return {
            "total_decisions": self.total_decisions,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "skipped_decisions": self.skipped_decisions,
            "success_rate": f"{success_rate:.1f}%",
            "total_hedged_value": float(self.total_hedged_value),
            "total_attempts": self.total_attempts,
            "avg_execution_time": self.avg_execution_time,
            "price_abnormal_count": self.price_abnormal_count,
            "last_hedge_time": self.last_hedge_time.isoformat() if self.last_hedge_time else None,
        }


class HedgeMonitor:
    """
    对冲监控器

    提供：
    - CSV文件记录：详细的对冲操作审计日志
    - 实时日志：重要事件的日志记录
    - 统计汇总：对冲操作的统计数据
    - 内存记录：最近的对冲记录缓存

    Args:
        log_dir: 日志目录，默认 "logs/hedging"
        csv_enabled: 是否启用CSV记录，默认True
        max_memory_records: 内存中保留的最大记录数，默认1000

    Examples:
        monitor = HedgeMonitor(log_dir="logs/hedging")
        monitor.record_decision(decision)
        monitor.record_execution(decision, result)
        print(monitor.get_stats())
    """

    CSV_HEADERS = [
        "timestamp", "symbol", "strategy",
        "decision_direction", "decision_amount", "decision_urgency", "decision_reason",
        "execution_success", "execution_order_id",
        "execution_filled_qty", "execution_filled_price", "execution_filled_value",
        "execution_attempts", "execution_time", "error_message",
        "xt_position_delta", "current_hedge_position",
        "price", "price_status", "price_confidence",
    ]

    def __init__(
        self,
        log_dir: str = "logs/hedging",
        csv_enabled: bool = True,
        max_memory_records: int = 1000,
    ):
        self.log_dir = Path(log_dir)
        self.csv_enabled = csv_enabled
        self.max_memory_records = max_memory_records

        # 统计数据
        self.stats = HedgeStats()

        # 内存记录
        self.records: List[HedgeRecord] = []

        # 创建日志目录
        if self.csv_enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._init_csv_file()

        logger.info(
            f"HedgeMonitor 初始化: log_dir={log_dir}, "
            f"csv_enabled={csv_enabled}"
        )

    def _init_csv_file(self) -> None:
        """初始化CSV文件"""
        today = datetime.now().strftime("%Y%m%d")
        self.csv_path = self.log_dir / f"hedge_log_{today}.csv"

        # 如果文件不存在，写入表头
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.CSV_HEADERS)
            logger.info(f"创建对冲日志文件: {self.csv_path}")

    def _ensure_csv_file(self) -> None:
        """确保CSV文件是当天的"""
        today = datetime.now().strftime("%Y%m%d")
        expected_path = self.log_dir / f"hedge_log_{today}.csv"

        if self.csv_path != expected_path:
            self._init_csv_file()

    def record_decision(
        self,
        symbol: str,
        strategy_name: str,
        decision: HedgeDecision,
        xt_position_delta: Decimal,
        current_hedge_position: Decimal,
        price: Decimal,
        price_status: str = "VALID",
        price_confidence: float = 1.0,
    ) -> None:
        """
        记录对冲决策（不包含执行结果）

        用于记录不执行对冲的决策。
        """
        self.stats.total_decisions += 1

        if not decision.should_hedge:
            self.stats.skipped_decisions += 1
            logger.debug(
                f"对冲跳过: {symbol} - {decision.reason}"
            )
            return

        logger.info(
            f"对冲决策: {symbol} {decision.direction} {decision.amount:.6f} "
            f"(urgency={decision.urgency:.2f}, reason={decision.reason})"
        )

    def record_execution(
        self,
        symbol: str,
        strategy_name: str,
        decision: HedgeDecision,
        result: ExecutionResult,
        xt_position_delta: Decimal,
        current_hedge_position: Decimal,
        price: Decimal,
        price_status: str = "VALID",
        price_confidence: float = 1.0,
    ) -> None:
        """
        记录对冲执行结果

        完整记录包含决策和执行结果。
        """
        # 更新统计
        self.stats.total_decisions += 1
        self.stats.total_executions += 1
        self.stats.total_attempts += result.attempts
        self.stats.last_hedge_time = datetime.now()

        if result.success:
            self.stats.successful_executions += 1
            self.stats.total_hedged_value += result.filled_value
            logger.info(
                f"对冲成功: {symbol} {decision.direction} "
                f"{result.filled_qty:.6f} @ {result.filled_price:.4f} "
                f"(金额={result.filled_value:.2f} USDT, 耗时={result.execution_time:.3f}s)"
            )
        else:
            self.stats.failed_executions += 1
            logger.error(
                f"对冲失败: {symbol} {decision.direction} {decision.amount:.6f} "
                f"(错误={result.error_message}, 尝试={result.attempts}次)"
            )

        # 更新平均执行时间
        if self.stats.total_executions > 0:
            total_time = self.stats.avg_execution_time * (self.stats.total_executions - 1)
            self.stats.avg_execution_time = (total_time + result.execution_time) / self.stats.total_executions

        # 价格异常统计
        if price_status != "VALID":
            self.stats.price_abnormal_count += 1

        # 创建记录
        record = HedgeRecord(
            timestamp=datetime.now(),
            symbol=symbol,
            strategy=strategy_name,
            decision_direction=decision.direction,
            decision_amount=decision.amount,
            decision_urgency=decision.urgency,
            decision_reason=decision.reason,
            execution_success=result.success,
            execution_order_id=result.order_id,
            execution_filled_qty=result.filled_qty,
            execution_filled_price=result.filled_price,
            execution_filled_value=result.filled_value,
            execution_attempts=result.attempts,
            execution_time=result.execution_time,
            error_message=result.error_message,
            xt_position_delta=xt_position_delta,
            current_hedge_position=current_hedge_position,
            price=price,
            price_status=price_status,
            price_confidence=price_confidence,
        )

        # 保存到内存
        self.records.append(record)
        if len(self.records) > self.max_memory_records:
            self.records.pop(0)

        # 写入CSV
        if self.csv_enabled:
            self._write_csv_record(record)

    def record_skip(
        self,
        symbol: str,
        reason: str,
        price_status: str = "VALID",
    ) -> None:
        """
        记录跳过对冲的原因

        用于记录因价格异常等原因跳过对冲的情况。
        """
        self.stats.skipped_decisions += 1

        if price_status != "VALID":
            self.stats.price_abnormal_count += 1

        logger.info(f"对冲跳过: {symbol} - {reason} (price_status={price_status})")

    def _write_csv_record(self, record: HedgeRecord) -> None:
        """写入CSV记录"""
        self._ensure_csv_file()

        row = [
            record.timestamp.isoformat(),
            record.symbol,
            record.strategy,
            record.decision_direction,
            float(record.decision_amount),
            record.decision_urgency,
            record.decision_reason,
            record.execution_success,
            record.execution_order_id or "",
            float(record.execution_filled_qty),
            float(record.execution_filled_price),
            float(record.execution_filled_value),
            record.execution_attempts,
            record.execution_time,
            record.error_message or "",
            float(record.xt_position_delta),
            float(record.current_hedge_position),
            float(record.price),
            record.price_status,
            record.price_confidence,
        ]

        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            logger.error(f"写入CSV失败: {e}")

    def get_stats(self) -> HedgeStats:
        """获取统计数据"""
        return self.stats

    def get_recent_records(self, count: int = 10) -> List[HedgeRecord]:
        """获取最近的记录"""
        return self.records[-count:]

    def reset_stats(self) -> None:
        """重置统计数据"""
        self.stats = HedgeStats()
        self.records.clear()
        logger.info("对冲统计已重置")
