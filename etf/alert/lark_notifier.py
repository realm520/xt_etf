# -*- coding: utf-8 -*-
"""
Lark (飞书) Webhook 告警通知模块

功能：
1. 发送不同级别的告警消息
2. 支持富文本卡片消息
3. 限流保护防止告警轰炸
4. 告警聚合和去重

Author: ETF Trading System
Date: 2024-01-09
"""

import json
import time
import httpx
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RateLimiter:
    """限流器"""
    
    def __init__(self, max_per_minute: int = 10, max_per_hour: int = 100):
        self.max_per_minute = max_per_minute
        self.max_per_hour = max_per_hour
        self.minute_counts = defaultdict(int)
        self.hour_counts = defaultdict(int)
        
    def can_send(self) -> bool:
        """检查是否可以发送"""
        now = datetime.now()
        current_minute = now.strftime("%Y%m%d%H%M")
        current_hour = now.strftime("%Y%m%d%H")
        
        # 清理过期记录
        self._cleanup_old_records()
        
        # 检查分钟限制
        if self.minute_counts[current_minute] >= self.max_per_minute:
            return False
            
        # 检查小时限制
        if self.hour_counts[current_hour] >= self.max_per_hour:
            return False
            
        # 更新计数
        self.minute_counts[current_minute] += 1
        self.hour_counts[current_hour] += 1
        
        return True
        
    def _cleanup_old_records(self):
        """清理过期记录"""
        now = datetime.now()
        
        # 清理超过2分钟的分钟记录
        cutoff_minute = (now - timedelta(minutes=2)).strftime("%Y%m%d%H%M")
        old_minutes = [k for k in self.minute_counts if k < cutoff_minute]
        for k in old_minutes:
            del self.minute_counts[k]
            
        # 清理超过2小时的小时记录
        cutoff_hour = (now - timedelta(hours=2)).strftime("%Y%m%d%H")
        old_hours = [k for k in self.hour_counts if k < cutoff_hour]
        for k in old_hours:
            del self.hour_counts[k]


class AlertAggregator:
    """告警聚合器"""
    
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self.alerts: Dict[str, List[Dict]] = defaultdict(list)
        self.last_sent: Dict[str, datetime] = {}
        
    def should_aggregate(self, alert_key: str, alert_data: Dict) -> bool:
        """判断是否需要聚合"""
        now = datetime.now()
        
        # 如果是新告警类型，不聚合
        if alert_key not in self.last_sent:
            self.alerts[alert_key] = [alert_data]
            self.last_sent[alert_key] = now
            return False
            
        # 如果距离上次发送超过窗口时间，发送聚合消息
        if (now - self.last_sent[alert_key]).total_seconds() > self.window_seconds:
            self.alerts[alert_key] = [alert_data]
            self.last_sent[alert_key] = now
            return True
        else:
            # 添加到聚合列表
            self.alerts[alert_key].append(alert_data)
            return False
            
    def get_aggregated_alerts(self, alert_key: str) -> List[Dict]:
        """获取聚合的告警"""
        return self.alerts.get(alert_key, [])


class LarkNotifier:
    """Lark 告警通知器"""
    
    def __init__(self, webhook_url: str, critical_webhook_url: Optional[str] = None):
        """
        初始化
        
        Args:
            webhook_url: 默认 webhook 地址
            critical_webhook_url: 严重告警专用 webhook 地址
        """
        self.webhook_url = webhook_url
        self.critical_webhook_url = critical_webhook_url or webhook_url
        self.rate_limiter = RateLimiter()
        self.aggregator = AlertAggregator()
        self.client = httpx.AsyncClient(timeout=10.0)
        
    async def send_alert(
        self,
        title: str,
        content: str,
        level: AlertLevel = AlertLevel.INFO,
        strategy_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        aggregate_key: Optional[str] = None
    ) -> bool:
        """
        发送告警
        
        Args:
            title: 告警标题
            content: 告警内容
            level: 告警级别
            strategy_name: 策略名称
            details: 详细信息
            aggregate_key: 聚合键（相同键的告警会被聚合）
            
        Returns:
            是否发送成功
        """
        # 检查限流
        if not self.rate_limiter.can_send():
            logger.warning(f"告警被限流: {title}")
            return False
            
        # 准备告警数据
        alert_data = {
            "title": title,
            "content": content,
            "level": level,
            "strategy_name": strategy_name,
            "details": details,
            "timestamp": datetime.now()
        }
        
        # 检查是否需要聚合
        if aggregate_key:
            should_send_aggregated = self.aggregator.should_aggregate(aggregate_key, alert_data)
            if should_send_aggregated:
                # 发送聚合消息
                aggregated_alerts = self.aggregator.get_aggregated_alerts(aggregate_key)
                return await self._send_aggregated_alert(aggregate_key, aggregated_alerts, level)
            elif len(self.aggregator.alerts[aggregate_key]) == 1:
                # 第一条消息，直接发送
                pass
            else:
                # 添加到聚合队列，不发送
                return True
                
        # 构建消息
        message = self._build_message(alert_data)
        
        # 选择 webhook
        webhook = self.critical_webhook_url if level == AlertLevel.CRITICAL else self.webhook_url
        
        # 发送消息
        try:
            response = await self.client.post(webhook, json=message)
            if response.status_code == 200:
                logger.info(f"告警发送成功: {title}")
                return True
            else:
                logger.error(f"告警发送失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"发送告警异常: {e}")
            return False
            
    async def _send_aggregated_alert(
        self,
        aggregate_key: str,
        alerts: List[Dict],
        level: AlertLevel
    ) -> bool:
        """发送聚合告警"""
        if not alerts:
            return True
            
        # 构建聚合消息
        title = f"[聚合告警] {aggregate_key} ({len(alerts)}条)"
        
        # 统计信息
        first_time = alerts[0]["timestamp"]
        last_time = alerts[-1]["timestamp"]
        duration = (last_time - first_time).total_seconds()
        
        content_parts = [
            f"告警数量: {len(alerts)}条",
            f"时间范围: {first_time.strftime('%H:%M:%S')} - {last_time.strftime('%H:%M:%S')} ({duration:.0f}秒)",
            "",
            "告警摘要:"
        ]
        
        # 添加前5条告警的摘要
        for i, alert in enumerate(alerts[:5]):
            content_parts.append(f"{i+1}. [{alert['timestamp'].strftime('%H:%M:%S')}] {alert['content']}")
            
        if len(alerts) > 5:
            content_parts.append(f"... 还有 {len(alerts) - 5} 条告警")
            
        message = self._build_card_message(
            title=title,
            content="\n".join(content_parts),
            level=level,
            color=self._get_color_by_level(level)
        )
        
        # 选择 webhook
        webhook = self.critical_webhook_url if level == AlertLevel.CRITICAL else self.webhook_url
        
        # 发送消息
        try:
            response = await self.client.post(webhook, json=message)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"发送聚合告警异常: {e}")
            return False
            
    def _build_message(self, alert_data: Dict) -> Dict:
        """构建消息"""
        level = alert_data["level"]
        color = self._get_color_by_level(level)
        
        # 构建内容
        content_parts = [alert_data["content"]]
        
        if alert_data.get("strategy_name"):
            content_parts.append(f"\n策略: {alert_data['strategy_name']}")
            
        if alert_data.get("details"):
            content_parts.append("\n详细信息:")
            for key, value in alert_data["details"].items():
                content_parts.append(f"  {key}: {value}")
                
        content_parts.append(f"\n时间: {alert_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        return self._build_card_message(
            title=f"[{level.value.upper()}] {alert_data['title']}",
            content="\n".join(content_parts),
            level=level,
            color=color
        )
        
    def _build_card_message(self, title: str, content: str, level: AlertLevel, color: str) -> Dict:
        """构建卡片消息"""
        return {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    },
                    "template": color
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content
                        }
                    }
                ]
            }
        }
        
    def _get_color_by_level(self, level: AlertLevel) -> str:
        """根据级别获取颜色"""
        color_map = {
            AlertLevel.INFO: "blue",
            AlertLevel.WARNING: "orange",
            AlertLevel.ERROR: "red",
            AlertLevel.CRITICAL: "red"
        }
        return color_map.get(level, "blue")
        
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


# 便捷函数
async def send_lark_alert(
    webhook_url: str,
    title: str,
    content: str,
    level: AlertLevel = AlertLevel.INFO,
    **kwargs
) -> bool:
    """
    发送单次告警的便捷函数
    
    Args:
        webhook_url: Webhook 地址
        title: 告警标题
        content: 告警内容
        level: 告警级别
        **kwargs: 其他参数
        
    Returns:
        是否发送成功
    """
    notifier = LarkNotifier(webhook_url)
    try:
        return await notifier.send_alert(title, content, level, **kwargs)
    finally:
        await notifier.close()


# 测试代码
if __name__ == "__main__":
    async def test():
        # 替换为实际的 webhook URL
        webhook_url = "https://open.larksuite.com/open-apis/bot/v2/hook/xxx"
        
        notifier = LarkNotifier(webhook_url)
        
        # 测试不同级别的告警
        await notifier.send_alert(
            title="测试告警",
            content="这是一条测试告警消息",
            level=AlertLevel.INFO,
            strategy_name="stg3l",
            details={
                "净值": 1.0234,
                "持仓": 10000,
                "盈亏": 234.56
            }
        )
        
        # 测试聚合告警
        for i in range(5):
            await notifier.send_alert(
                title="API 错误",
                content=f"API 调用失败 #{i+1}",
                level=AlertLevel.WARNING,
                aggregate_key="api_error"
            )
            await asyncio.sleep(1)
            
        await notifier.close()
        
    asyncio.run(test())