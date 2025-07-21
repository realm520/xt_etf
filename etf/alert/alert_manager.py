# -*- coding: utf-8 -*-
"""
告警管理器
统一管理告警规则、冷却时间、告警发送等

Author: ETF Trading System
Date: 2024-01-09
"""

import os
import yaml
import asyncio
import logging
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

from .lark_notifier import LarkNotifier, AlertLevel

logger = logging.getLogger(__name__)


class AlertRule:
    """告警规则"""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.description = config.get("description", name)
        self.conditions = config.get("conditions", [])
        self.level = AlertLevel[config.get("level", "INFO").upper()]
        self.cooldown = config.get("cooldown", 300)  # 默认5分钟冷却
        self.aggregate = config.get("aggregate", False)
        self.aggregate_key = config.get("aggregate_key", name)
        self.last_triggered = None
        
    def check_conditions(self, data: Dict[str, Any]) -> bool:
        """检查是否满足触发条件"""
        for condition in self.conditions:
            field = condition.get("field")
            operator = condition.get("operator")
            
            # 获取字段值
            value = data.get(field)
            if value is None:
                continue
                
            # 检查条件
            if operator == ">":
                threshold = condition.get("threshold")
                if not (value > threshold):
                    return False
            elif operator == "<":
                threshold = condition.get("threshold")
                if not (value < threshold):
                    return False
            elif operator == ">=":
                threshold = condition.get("threshold")
                if not (value >= threshold):
                    return False
            elif operator == "<=":
                threshold = condition.get("threshold")
                if not (value <= threshold):
                    return False
            elif operator == "==":
                expected = condition.get("value")
                if value != expected:
                    return False
            elif operator == "!=":
                expected = condition.get("value")
                if value == expected:
                    return False
            elif operator == "in":
                values = condition.get("values", [])
                if value not in values:
                    return False
                    
        return True
        
    def is_in_cooldown(self) -> bool:
        """检查是否在冷却期"""
        if self.cooldown == 0 or self.last_triggered is None:
            return False
            
        elapsed = (datetime.now() - self.last_triggered).total_seconds()
        return elapsed < self.cooldown
        
    def trigger(self):
        """触发告警"""
        self.last_triggered = datetime.now()


class AlertManager:
    """告警管理器"""
    
    def __init__(self, config_path: str = "config/alert.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        self.rules = self._load_rules()
        self.notifier = None
        self._init_notifier()
        
        # 告警历史记录
        self.alert_history: List[Dict[str, Any]] = []
        self.alert_counts: Dict[str, int] = defaultdict(int)
        
        # 启动定时任务
        self._summary_task = None
        
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        config_file = Path(self.config_path)
        if not config_file.exists():
            logger.warning(f"告警配置文件不存在: {config_file}")
            return {}
            
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 替换环境变量
        for match in set(s for s in content.split() if s.startswith("${") and s.endswith("}")):
            var_name = match[2:-1]
            var_value = os.environ.get(var_name, "")
            content = content.replace(match, var_value)
            
        return yaml.safe_load(content)
        
    def _load_rules(self) -> Dict[str, AlertRule]:
        """加载告警规则"""
        rules = {}
        for name, rule_config in self.config.get("alert_rules", {}).items():
            rules[name] = AlertRule(name, rule_config)
        return rules
        
    def _init_notifier(self):
        """初始化通知器"""
        lark_config = self.config.get("lark", {})
        webhooks = lark_config.get("webhooks", {})
        
        default_webhook = webhooks.get("default")
        critical_webhook = webhooks.get("critical")
        
        if not default_webhook:
            logger.warning("未配置 Lark webhook，告警功能将不可用")
            return
            
        self.notifier = LarkNotifier(
            webhook_url=default_webhook,
            critical_webhook_url=critical_webhook
        )
        
        # 更新限流配置
        rate_limit = lark_config.get("rate_limit", {})
        if rate_limit:
            self.notifier.rate_limiter.max_per_minute = rate_limit.get("max_per_minute", 10)
            self.notifier.rate_limiter.max_per_hour = rate_limit.get("max_per_hour", 100)
            
    async def check_and_send_alert(
        self,
        alert_type: str,
        data: Dict[str, Any],
        title: Optional[str] = None,
        content: Optional[str] = None,
        strategy_name: Optional[str] = None
    ) -> bool:
        """
        检查并发送告警
        
        Args:
            alert_type: 告警类型（对应配置中的规则名）
            data: 用于检查条件的数据
            title: 自定义标题（可选）
            content: 自定义内容（可选）
            strategy_name: 策略名称
            
        Returns:
            是否发送了告警
        """
        # 获取规则
        rule = self.rules.get(alert_type)
        if not rule:
            logger.warning(f"未知的告警类型: {alert_type}")
            return False
            
        # 检查条件
        if not rule.check_conditions(data):
            return False
            
        # 检查冷却期
        if rule.is_in_cooldown():
            logger.debug(f"告警 {alert_type} 在冷却期内")
            return False
            
        # 构建告警内容
        if not title:
            title = rule.description
            
        if not content:
            content_parts = []
            for key, value in data.items():
                if key != "event_type":
                    content_parts.append(f"{key}: {value}")
            content = "\n".join(content_parts)
            
        # 发送告警
        if self.notifier:
            aggregate_key = None
            if rule.aggregate:
                # 替换聚合键中的变量
                aggregate_key = rule.aggregate_key
                for key, value in data.items():
                    aggregate_key = aggregate_key.replace(f"{{{key}}}", str(value))
                    
            success = await self.notifier.send_alert(
                title=title,
                content=content,
                level=rule.level,
                strategy_name=strategy_name,
                details=data,
                aggregate_key=aggregate_key
            )
            
            if success:
                rule.trigger()
                self._record_alert(alert_type, rule.level, data)
                
            return success
        else:
            logger.warning("通知器未初始化，无法发送告警")
            return False
            
    def _record_alert(self, alert_type: str, level: AlertLevel, data: Dict[str, Any]):
        """记录告警历史"""
        record = {
            "type": alert_type,
            "level": level.value,
            "data": data,
            "timestamp": datetime.now()
        }
        
        self.alert_history.append(record)
        self.alert_counts[alert_type] += 1
        
        # 保留最近24小时的记录
        cutoff = datetime.now() - timedelta(hours=24)
        self.alert_history = [r for r in self.alert_history if r["timestamp"] > cutoff]
        
    async def send_direct_alert(
        self,
        title: str,
        content: str,
        level: AlertLevel = AlertLevel.INFO,
        strategy_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        直接发送告警（不经过规则检查）
        
        Args:
            title: 告警标题
            content: 告警内容
            level: 告警级别
            strategy_name: 策略名称
            details: 详细信息
            
        Returns:
            是否发送成功
        """
        if not self.notifier:
            logger.warning("通知器未初始化，无法发送告警")
            return False
            
        return await self.notifier.send_alert(
            title=title,
            content=content,
            level=level,
            strategy_name=strategy_name,
            details=details
        )
        
    async def send_summary(self):
        """发送告警汇总"""
        if not self.alert_history:
            return
            
        # 统计各类型告警数量
        type_counts = defaultdict(int)
        level_counts = defaultdict(int)
        
        for record in self.alert_history:
            type_counts[record["type"]] += 1
            level_counts[record["level"]] += 1
            
        # 构建汇总内容
        content_parts = [
            f"时间范围: {self.alert_history[0]['timestamp'].strftime('%Y-%m-%d %H:%M')} - {datetime.now().strftime('%H:%M')}",
            f"告警总数: {len(self.alert_history)}",
            "",
            "按级别统计:"
        ]
        
        for level in ["critical", "error", "warning", "info"]:
            if level in level_counts:
                content_parts.append(f"  {level.upper()}: {level_counts[level]}")
                
        content_parts.extend(["", "按类型统计:"])
        
        # 按数量排序
        sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        for alert_type, count in sorted_types[:10]:  # 只显示前10个
            rule = self.rules.get(alert_type)
            desc = rule.description if rule else alert_type
            content_parts.append(f"  {desc}: {count}")
            
        if len(sorted_types) > 10:
            content_parts.append(f"  ... 还有 {len(sorted_types) - 10} 种类型")
            
        # 发送汇总
        await self.send_direct_alert(
            title="告警汇总报告",
            content="\n".join(content_parts),
            level=AlertLevel.INFO
        )
        
    async def start_summary_task(self):
        """启动定时汇总任务"""
        summary_config = self.config.get("alert_summary", {})
        if not summary_config.get("enabled", True):
            return
            
        # TODO: 实现基于 cron 表达式的定时任务
        # 这里简化为每12小时发送一次
        while True:
            await asyncio.sleep(12 * 3600)  # 12小时
            await self.send_summary()
            
    async def close(self):
        """关闭管理器"""
        if self.notifier:
            await self.notifier.close()
            
        if self._summary_task:
            self._summary_task.cancel()


# 全局告警管理器实例
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """获取全局告警管理器实例"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


# 便捷函数
async def send_alert(
    alert_type: str,
    data: Dict[str, Any],
    **kwargs
) -> bool:
    """发送告警的便捷函数"""
    manager = get_alert_manager()
    return await manager.check_and_send_alert(alert_type, data, **kwargs)


async def send_direct_alert(
    title: str,
    content: str,
    level: AlertLevel = AlertLevel.INFO,
    **kwargs
) -> bool:
    """直接发送告警的便捷函数"""
    manager = get_alert_manager()
    return await manager.send_direct_alert(title, content, level, **kwargs)