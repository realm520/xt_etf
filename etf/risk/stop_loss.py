# -*- coding: utf-8 -*-
"""
止损管理器

实现多种止损策略：
1. 固定止损：按百分比设置止损线
2. 移动止损：跟踪最高点动态调整止损线
3. 时间止损：持仓时间过长自动平仓
4. 分级止损：不同亏损级别采取不同措施

Author: ETF Trading System
Date: 2024-01-09
"""

import time
import logging
import asyncio
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from etf.alert import send_alert, AlertLevel

logger = logging.getLogger(__name__)


class StopLossType(Enum):
    """止损类型"""
    FIXED = "fixed"          # 固定止损
    TRAILING = "trailing"    # 移动止损
    TIME_BASED = "time"      # 时间止损
    COMBINED = "combined"    # 组合止损


class StopLossAction(Enum):
    """止损动作"""
    NONE = "none"                    # 无动作
    REDUCE_POSITION = "reduce"       # 减仓
    CLOSE_POSITION = "close"         # 平仓
    PAUSE_TRADING = "pause"          # 暂停交易


@dataclass
class PositionInfo:
    """持仓信息"""
    symbol: str
    side: str  # 'long' or 'short'
    amount: float
    entry_price: float
    entry_time: datetime
    current_price: float
    highest_price: float  # 用于移动止损
    lowest_price: float   # 用于做空的移动止损


@dataclass
class StopLossResult:
    """止损检查结果"""
    triggered: bool
    action: StopLossAction
    reason: str
    loss_rate: float
    position_to_close: float  # 需要平仓的数量


class StopLossManager:
    """止损管理器"""
    
    def __init__(
        self,
        strategy_name: str,
        fixed_threshold: float = -0.02,      # 固定止损阈值 -2%
        trailing_stop: float = 0.01,         # 移动止损 1%
        time_stop_hours: int = 24,           # 时间止损 24小时
        cooldown_minutes: int = 60,          # 止损后冷却时间
        enable_partial_close: bool = True,   # 是否启用部分平仓
    ):
        """
        初始化止损管理器
        
        Args:
            strategy_name: 策略名称
            fixed_threshold: 固定止损阈值（负数）
            trailing_stop: 移动止损百分比
            time_stop_hours: 时间止损（小时）
            cooldown_minutes: 止损后冷却时间（分钟）
            enable_partial_close: 是否启用部分平仓
        """
        self.strategy_name = strategy_name
        self.fixed_threshold = fixed_threshold
        self.trailing_stop = trailing_stop
        self.time_stop_hours = time_stop_hours
        self.cooldown_minutes = cooldown_minutes
        self.enable_partial_close = enable_partial_close
        
        # 止损记录
        self.stop_loss_history: List[Dict] = []
        self.last_stop_loss_time: Optional[datetime] = None
        self.is_in_cooldown = False
        
        # 持仓跟踪
        self.positions: Dict[str, PositionInfo] = {}
        
    def update_position(
        self,
        symbol: str,
        side: str,
        amount: float,
        entry_price: float,
        current_price: float,
        entry_time: Optional[datetime] = None
    ):
        """更新持仓信息"""
        if amount == 0:
            # 清空持仓
            if symbol in self.positions:
                del self.positions[symbol]
            return
            
        if symbol not in self.positions:
            # 新建持仓
            self.positions[symbol] = PositionInfo(
                symbol=symbol,
                side=side,
                amount=amount,
                entry_price=entry_price,
                entry_time=entry_time or datetime.now(),
                current_price=current_price,
                highest_price=current_price,
                lowest_price=current_price
            )
        else:
            # 更新现有持仓
            position = self.positions[symbol]
            position.amount = amount
            position.current_price = current_price
            
            # 更新最高/最低价（用于移动止损）
            if side == 'long':
                position.highest_price = max(position.highest_price, current_price)
            else:  # short
                position.lowest_price = min(position.lowest_price, current_price)
                
    def calculate_pnl_rate(self, position: PositionInfo) -> float:
        """计算盈亏率"""
        if position.side == 'long':
            return (position.current_price - position.entry_price) / position.entry_price
        else:  # short
            return (position.entry_price - position.current_price) / position.entry_price
            
    def check_fixed_stop_loss(self, position: PositionInfo) -> Tuple[bool, float]:
        """检查固定止损"""
        pnl_rate = self.calculate_pnl_rate(position)
        
        if pnl_rate <= self.fixed_threshold:
            return True, pnl_rate
            
        return False, pnl_rate
        
    def check_trailing_stop_loss(self, position: PositionInfo) -> Tuple[bool, float]:
        """检查移动止损"""
        if position.side == 'long':
            # 做多：从最高点回撤
            drawdown = (position.highest_price - position.current_price) / position.highest_price
            if drawdown >= self.trailing_stop:
                return True, -drawdown
        else:  # short
            # 做空：从最低点反弹
            bounce = (position.current_price - position.lowest_price) / position.lowest_price
            if bounce >= self.trailing_stop:
                return True, -bounce
                
        return False, 0.0
        
    def check_time_stop_loss(self, position: PositionInfo) -> Tuple[bool, str]:
        """检查时间止损"""
        holding_time = datetime.now() - position.entry_time
        
        if holding_time > timedelta(hours=self.time_stop_hours):
            pnl_rate = self.calculate_pnl_rate(position)
            # 只有亏损时才触发时间止损
            if pnl_rate < 0:
                return True, f"持仓超过{self.time_stop_hours}小时且处于亏损状态"
                
        return False, ""
        
    def check_cooldown(self) -> bool:
        """检查是否在冷却期"""
        if not self.last_stop_loss_time:
            return False
            
        elapsed = datetime.now() - self.last_stop_loss_time
        if elapsed < timedelta(minutes=self.cooldown_minutes):
            self.is_in_cooldown = True
            return True
        else:
            self.is_in_cooldown = False
            return False
            
    async def check_stop_loss(self, symbol: str) -> StopLossResult:
        """
        检查止损条件
        
        Returns:
            止损检查结果
        """
        # 检查冷却期
        if self.check_cooldown():
            return StopLossResult(
                triggered=False,
                action=StopLossAction.NONE,
                reason="处于冷却期",
                loss_rate=0.0,
                position_to_close=0.0
            )
            
        # 获取持仓信息
        position = self.positions.get(symbol)
        if not position or position.amount == 0:
            return StopLossResult(
                triggered=False,
                action=StopLossAction.NONE,
                reason="无持仓",
                loss_rate=0.0,
                position_to_close=0.0
            )
            
        # 检查各种止损条件
        stop_loss_triggered = False
        stop_loss_reason = ""
        loss_rate = 0.0
        
        # 1. 固定止损
        fixed_triggered, pnl_rate = self.check_fixed_stop_loss(position)
        if fixed_triggered:
            stop_loss_triggered = True
            stop_loss_reason = f"固定止损触发，亏损率: {pnl_rate:.2%}"
            loss_rate = pnl_rate
            
        # 2. 移动止损
        trailing_triggered, drawdown_rate = self.check_trailing_stop_loss(position)
        if trailing_triggered and not stop_loss_triggered:
            stop_loss_triggered = True
            stop_loss_reason = f"移动止损触发，回撤率: {abs(drawdown_rate):.2%}"
            loss_rate = self.calculate_pnl_rate(position)
            
        # 3. 时间止损
        time_triggered, time_reason = self.check_time_stop_loss(position)
        if time_triggered and not stop_loss_triggered:
            stop_loss_triggered = True
            stop_loss_reason = time_reason
            loss_rate = self.calculate_pnl_rate(position)
            
        if not stop_loss_triggered:
            return StopLossResult(
                triggered=False,
                action=StopLossAction.NONE,
                reason="",
                loss_rate=0.0,
                position_to_close=0.0
            )
            
        # 确定止损动作
        action = StopLossAction.CLOSE_POSITION
        position_to_close = position.amount
        
        # 如果启用部分平仓，根据亏损程度决定平仓比例
        if self.enable_partial_close and abs(loss_rate) < 0.05:  # 亏损小于5%
            action = StopLossAction.REDUCE_POSITION
            position_to_close = position.amount * 0.5  # 平仓50%
            
        # 记录止损事件
        self.last_stop_loss_time = datetime.now()
        stop_loss_event = {
            "timestamp": self.last_stop_loss_time,
            "symbol": symbol,
            "reason": stop_loss_reason,
            "loss_rate": loss_rate,
            "position": position.amount,
            "action": action.value,
            "position_to_close": position_to_close
        }
        self.stop_loss_history.append(stop_loss_event)
        
        # 发送止损告警
        await send_alert(
            "stop_loss_triggered",
            {
                "event_type": "stop_loss",
                "symbol": symbol,
                "reason": stop_loss_reason,
                "loss_rate": loss_rate,
                "position": position.amount,
                "action": action.value,
                "position_to_close": position_to_close,
                "entry_price": position.entry_price,
                "current_price": position.current_price,
                "holding_time_hours": (datetime.now() - position.entry_time).total_seconds() / 3600
            },
            strategy_name=self.strategy_name
        )
        
        logger.warning(f"止损触发: {stop_loss_reason}, 动作: {action.value}")
        
        return StopLossResult(
            triggered=True,
            action=action,
            reason=stop_loss_reason,
            loss_rate=loss_rate,
            position_to_close=position_to_close
        )
        
    def get_stop_loss_summary(self) -> Dict:
        """获取止损汇总信息"""
        if not self.stop_loss_history:
            return {
                "total_count": 0,
                "is_in_cooldown": self.is_in_cooldown,
                "last_stop_loss": None
            }
            
        total_loss = sum(event["loss_rate"] for event in self.stop_loss_history)
        
        return {
            "total_count": len(self.stop_loss_history),
            "total_loss_rate": total_loss,
            "average_loss_rate": total_loss / len(self.stop_loss_history),
            "is_in_cooldown": self.is_in_cooldown,
            "last_stop_loss": self.stop_loss_history[-1] if self.stop_loss_history else None,
            "cooldown_remaining_minutes": max(0, self.cooldown_minutes - 
                                            (datetime.now() - self.last_stop_loss_time).total_seconds() / 60)
                                          if self.last_stop_loss_time else 0
        }
        
    def reset_cooldown(self):
        """重置冷却期（用于手动恢复交易）"""
        self.last_stop_loss_time = None
        self.is_in_cooldown = False
        logger.info("止损冷却期已重置")


# 测试代码
if __name__ == "__main__":
    async def test():
        # 创建止损管理器
        stop_loss = StopLossManager(
            strategy_name="test",
            fixed_threshold=-0.02,     # -2% 固定止损
            trailing_stop=0.01,        # 1% 移动止损
            time_stop_hours=24,        # 24小时时间止损
            cooldown_minutes=60        # 60分钟冷却期
        )
        
        # 模拟持仓
        stop_loss.update_position(
            symbol="btc_usdt",
            side="long",
            amount=1.0,
            entry_price=50000,
            current_price=50000
        )
        
        # 模拟价格下跌
        prices = [50000, 49500, 49000, 48500, 48000]  # 逐步下跌
        
        for price in prices:
            stop_loss.update_position(
                symbol="btc_usdt",
                side="long",
                amount=1.0,
                entry_price=50000,
                current_price=price
            )
            
            result = await stop_loss.check_stop_loss("btc_usdt")
            
            if result.triggered:
                print(f"止损触发! 原因: {result.reason}")
                print(f"亏损率: {result.loss_rate:.2%}")
                print(f"需要平仓: {result.position_to_close}")
                break
            else:
                pnl_rate = (price - 50000) / 50000
                print(f"当前价格: {price}, 盈亏率: {pnl_rate:.2%}, 未触发止损")
                
        # 获取止损汇总
        summary = stop_loss.get_stop_loss_summary()
        print(f"\n止损汇总: {summary}")
        
    asyncio.run(test())