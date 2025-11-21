"""
资金充足性检查模块

功能:
1. 检查账户资金是否充足
2. 输出告警日志
3. 提供策略暂停建议
"""

import logging
from typing import Dict, Optional, Tuple
from enum import Enum
from etf.alert import send_alert, AlertLevel


class BalanceStatus(Enum):
    """资金状态枚举"""
    SUFFICIENT = "sufficient"  # 充足
    WARNING = "warning"  # 警告
    CRITICAL = "critical"  # 危急
    INSUFFICIENT = "insufficient"  # 不足


class BalanceChecker:
    """资金检查器"""
    
    def __init__(
        self,
        strategy_name: str,
        warning_threshold: float = 0.3,  # 警告阈值：资金使用率30%
        critical_threshold: float = 0.2,  # 危急阈值：资金使用率20%
        insufficient_threshold: float = 0.1,  # 不足阈值：资金使用率10%
        min_order_value: float = 1.2,  # 最小订单金额（USDT）
    ):
        """
        初始化资金检查器
        
        Args:
            strategy_name: 策略名称
            warning_threshold: 警告阈值（剩余资金比例）
            critical_threshold: 危急阈值（剩余资金比例）
            insufficient_threshold: 不足阈值（剩余资金比例）
            min_order_value: 最小订单金额
        """
        self.strategy_name = strategy_name
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.insufficient_threshold = insufficient_threshold
        self.min_order_value = min_order_value
        
        self.logger = logging.getLogger(f"balance_checker.{strategy_name}")
        
        # 状态跟踪
        self.last_status = BalanceStatus.SUFFICIENT
        self.warning_count = 0
        self.critical_count = 0
        
    def check_balance(
        self,
        available_balance: float,
        total_balance: float,
        pending_order_value: float = 0.0,
    ) -> Tuple[BalanceStatus, str]:
        """
        检查资金充足性
        
        Args:
            available_balance: 可用余额（USDT）
            total_balance: 总余额（USDT）
            pending_order_value: 挂单占用金额（USDT）
            
        Returns:
            (status, message): 状态和详细信息
        """
        # 计算实际可用资金（扣除挂单）
        actual_available = available_balance - pending_order_value
        
        # 计算资金使用率
        if total_balance > 0:
            usage_rate = (total_balance - actual_available) / total_balance
            available_rate = actual_available / total_balance
        else:
            usage_rate = 1.0
            available_rate = 0.0
            
        # 检查是否能下单
        can_place_order = actual_available >= self.min_order_value
        
        # 确定状态
        status = self._determine_status(available_rate, can_place_order)
        
        # 构建详细信息
        message = self._build_message(
            status,
            available_balance,
            total_balance,
            pending_order_value,
            actual_available,
            usage_rate,
            available_rate,
            can_place_order,
        )
        
        # 记录日志和发送告警
        self._log_and_alert(status, message, actual_available)
        
        return status, message
    
    def _determine_status(
        self,
        available_rate: float,
        can_place_order: bool,
    ) -> BalanceStatus:
        """确定资金状态"""
        if not can_place_order:
            return BalanceStatus.INSUFFICIENT
        elif available_rate <= self.insufficient_threshold:
            return BalanceStatus.INSUFFICIENT
        elif available_rate <= self.critical_threshold:
            return BalanceStatus.CRITICAL
        elif available_rate <= self.warning_threshold:
            return BalanceStatus.WARNING
        else:
            return BalanceStatus.SUFFICIENT
    
    def _build_message(
        self,
        status: BalanceStatus,
        available_balance: float,
        total_balance: float,
        pending_order_value: float,
        actual_available: float,
        usage_rate: float,
        available_rate: float,
        can_place_order: bool,
    ) -> str:
        """构建详细信息"""
        msg_parts = [
            f"[{self.strategy_name}] 资金状态检查",
            f"状态: {status.value.upper()}",
            f"总余额: {total_balance:.2f} USDT",
            f"可用余额: {available_balance:.2f} USDT",
            f"挂单占用: {pending_order_value:.2f} USDT",
            f"实际可用: {actual_available:.2f} USDT",
            f"资金使用率: {usage_rate * 100:.2f}%",
            f"剩余资金比例: {available_rate * 100:.2f}%",
            f"可下单: {'是' if can_place_order else '否'}",
        ]
        
        # 添加建议
        if status == BalanceStatus.INSUFFICIENT:
            msg_parts.append("⚠️ 建议: 立即停止策略并充值")
        elif status == BalanceStatus.CRITICAL:
            msg_parts.append("⚠️ 建议: 考虑暂停策略或充值")
        elif status == BalanceStatus.WARNING:
            msg_parts.append("💡 建议: 关注资金状况")
            
        return " | ".join(msg_parts)
    
    def _log_and_alert(
        self,
        status: BalanceStatus,
        message: str,
        actual_available: float,
    ):
        """记录日志并发送告警"""
        # 状态变化或持续异常时记录
        if status != self.last_status:
            # 状态变化
            if status == BalanceStatus.INSUFFICIENT:
                self.logger.critical(message)
                send_alert(
                    f"[{self.strategy_name}] 资金不足告警",
                    message,
                    AlertLevel.CRITICAL,
                )
            elif status == BalanceStatus.CRITICAL:
                self.logger.error(message)
                send_alert(
                    f"[{self.strategy_name}] 资金危急告警",
                    message,
                    AlertLevel.ERROR,
                )
                self.critical_count += 1
            elif status == BalanceStatus.WARNING:
                self.logger.warning(message)
                send_alert(
                    f"[{self.strategy_name}] 资金警告",
                    message,
                    AlertLevel.WARNING,
                )
                self.warning_count += 1
            else:
                # 恢复正常
                if self.last_status != BalanceStatus.SUFFICIENT:
                    self.logger.info(f"{message} (已恢复正常)")
                    send_alert(
                        f"[{self.strategy_name}] 资金状态恢复",
                        message,
                        AlertLevel.INFO,
                    )
                    
            self.last_status = status
        else:
            # 状态未变化，但仍是异常状态时定期记录
            if status in [BalanceStatus.CRITICAL, BalanceStatus.INSUFFICIENT]:
                if status == BalanceStatus.CRITICAL:
                    self.critical_count += 1
                    # 每5次记录一次
                    if self.critical_count % 5 == 0:
                        self.logger.error(f"{message} (持续危急)")
                elif status == BalanceStatus.INSUFFICIENT:
                    # 不足状态每次都记录
                    self.logger.critical(f"{message} (持续不足)")
            elif status == BalanceStatus.WARNING:
                self.warning_count += 1
                # 每10次记录一次
                if self.warning_count % 10 == 0:
                    self.logger.warning(f"{message} (持续警告)")
    
    def should_stop_strategy(self, status: BalanceStatus) -> bool:
        """
        判断是否应该停止策略
        
        Args:
            status: 当前资金状态
            
        Returns:
            True: 应该停止策略
            False: 可以继续运行
        """
        return status == BalanceStatus.INSUFFICIENT
    
    def get_balance_info(self, client, currency: str = "usdt") -> Dict[str, float]:
        """
        获取账户余额信息
        
        Args:
            client: 交易客户端
            currency: 币种（默认USDT）
            
        Returns:
            包含balance和available的字典
        """
        try:
            balances = client.balances([currency])
            for asset in balances.get("assets", []):
                if asset.get("currency", "").lower() == currency.lower():
                    return {
                        "balance": float(asset.get("totalAmount", 0)),
                        "available": float(asset.get("availableAmount", 0)),
                        "frozen": float(asset.get("frozenAmount", 0)),
                    }
            self.logger.warning(f"未找到{currency}余额信息")
            return {"balance": 0.0, "available": 0.0, "frozen": 0.0}
        except Exception as e:
            self.logger.error(f"获取余额失败: {e}")
            return {"balance": 0.0, "available": 0.0, "frozen": 0.0}
    
    def calculate_pending_order_value(
        self,
        open_orders: Dict,
        symbol: str,
    ) -> float:
        """
        计算挂单占用金额
        
        Args:
            open_orders: 当前挂单字典
            symbol: 交易对
            
        Returns:
            挂单占用的总金额（USDT）
        """
        total_value = 0.0
        for order_id, order in open_orders.items():
            if order.get("symbol") == symbol:
                order_type = order.get("side", "").lower()
                quantity = float(order.get("origQty", 0))
                price = float(order.get("price", 0))
                
                # 买单占用USDT
                if order_type == "buy":
                    total_value += quantity * price
                    
        return total_value
