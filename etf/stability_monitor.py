# -*- coding: utf-8 -*-
"""
系统稳定性监控模块
监控系统关键指标，及时发现和响应稳定性问题

Author: Claude Code
Date: 2025-01-21
"""

import asyncio
import logging
import time
import json
import redis
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from etf.alert import AlertLevel


class HealthStatus(Enum):
    HEALTHY = "healthy"
    WARNING = "warning" 
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class HealthMetric:
    name: str
    value: float
    threshold_warning: float
    threshold_critical: float
    unit: str = ""
    description: str = ""
    
    @property
    def status(self) -> HealthStatus:
        if self.value >= self.threshold_critical:
            return HealthStatus.CRITICAL
        elif self.value >= self.threshold_warning:
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY


class StabilityMonitor:
    """系统稳定性监控器"""
    
    def __init__(self, strategy_name: str = "unknown", check_interval: int = 30):
        self.strategy_name = strategy_name
        self.check_interval = check_interval
        self.r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        
        # 监控数据存储
        self.metrics_history: Dict[str, List[float]] = {}
        self.alerts_sent: Dict[str, float] = {}  # 记录已发送的告警，避免重复
        self.last_check_time = time.time()
        
        # 健康阈值配置
        self.thresholds = {
            "api_error_rate": {"warning": 0.05, "critical": 0.15},  # API错误率
            "websocket_reconnects": {"warning": 5, "critical": 10},  # WebSocket重连次数
            "order_failure_rate": {"warning": 0.03, "critical": 0.10},  # 订单失败率
            "memory_usage": {"warning": 0.80, "critical": 0.95},  # 内存使用率
            "response_time": {"warning": 5.0, "critical": 10.0},  # API响应时间(秒)
            "queue_size": {"warning": 500, "critical": 800},  # 消息队列大小
            "connection_downtime": {"warning": 60, "critical": 300},  # 连接断线时间(秒)
        }
        
        self.is_monitoring = False
        self._monitor_task = None
        
        logging.info(f"稳定性监控器初始化完成: {strategy_name}")

    def start_monitoring(self):
        """启动监控"""
        if not self.is_monitoring:
            self.is_monitoring = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logging.info("系统稳定性监控已启动")

    def stop_monitoring(self):
        """停止监控"""
        self.is_monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
        logging.info("系统稳定性监控已停止")

    async def _monitor_loop(self):
        """监控主循环"""
        try:
            while self.is_monitoring:
                await self._perform_health_check()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            logging.info("监控循环被取消")
        except Exception as e:
            logging.error(f"监控循环异常: {e}")
            # 记录监控系统异常（告警已移除，使用日志记录）
            logging.error(f"监控系统错误: monitoring_failure - {e}")
            logging.error(f"策略: {self.strategy_name}, 组件: stability_monitor")

    async def _perform_health_check(self):
        """执行健康检查"""
        try:
            current_time = time.time()
            metrics = await self._collect_metrics()
            
            # 分析每个指标
            critical_issues = []
            warning_issues = []
            
            for metric in metrics:
                # 记录历史数据
                if metric.name not in self.metrics_history:
                    self.metrics_history[metric.name] = []
                self.metrics_history[metric.name].append(metric.value)
                
                # 保留最近100个数据点
                if len(self.metrics_history[metric.name]) > 100:
                    self.metrics_history[metric.name] = self.metrics_history[metric.name][-100:]
                
                # 检查健康状态
                if metric.status == HealthStatus.CRITICAL:
                    critical_issues.append(metric)
                elif metric.status == HealthStatus.WARNING:
                    warning_issues.append(metric)
            
            # 发送告警
            if critical_issues:
                await self._send_health_alert(critical_issues, AlertLevel.CRITICAL)
            elif warning_issues:
                await self._send_health_alert(warning_issues, AlertLevel.WARNING)
            
            # 更新Redis中的健康状态
            health_data = {
                "last_check": current_time,
                "critical_issues": len(critical_issues),
                "warning_issues": len(warning_issues),
                "total_metrics": len(metrics),
                "strategy": self.strategy_name
            }
            
            self.r.set(
                f"health_status_{self.strategy_name}",
                json.dumps(health_data)
            )
            
            self.last_check_time = current_time
            
        except Exception as e:
            logging.error(f"健康检查执行失败: {e}")

    async def _collect_metrics(self) -> List[HealthMetric]:
        """收集系统指标"""
        metrics = []
        
        try:
            # 1. API错误率 (从Redis获取)
            error_count_key = f"api_errors_{self.strategy_name}_count"
            total_count_key = f"api_calls_{self.strategy_name}_count"
            
            error_count = float(self.r.get(error_count_key) or 0)
            total_count = float(self.r.get(total_count_key) or 1)
            error_rate = error_count / max(total_count, 1)
            
            metrics.append(HealthMetric(
                name="api_error_rate",
                value=error_rate,
                threshold_warning=self.thresholds["api_error_rate"]["warning"],
                threshold_critical=self.thresholds["api_error_rate"]["critical"],
                unit="%",
                description="API调用错误率"
            ))
            
            # 2. WebSocket重连次数
            reconnect_key = f"websocket_reconnects_{self.strategy_name}"
            reconnects = float(self.r.get(reconnect_key) or 0)
            
            metrics.append(HealthMetric(
                name="websocket_reconnects",
                value=reconnects,
                threshold_warning=self.thresholds["websocket_reconnects"]["warning"],
                threshold_critical=self.thresholds["websocket_reconnects"]["critical"],
                unit="次",
                description="WebSocket重连次数"
            ))
            
            # 3. 订单失败率
            order_failed_key = f"orders_failed_{self.strategy_name}"
            order_total_key = f"orders_total_{self.strategy_name}"
            
            failed_orders = float(self.r.get(order_failed_key) or 0)
            total_orders = float(self.r.get(order_total_key) or 1)
            failure_rate = failed_orders / max(total_orders, 1)
            
            metrics.append(HealthMetric(
                name="order_failure_rate", 
                value=failure_rate,
                threshold_warning=self.thresholds["order_failure_rate"]["warning"],
                threshold_critical=self.thresholds["order_failure_rate"]["critical"],
                unit="%",
                description="订单失败率"
            ))
            
            # 4. 最后活跃时间检查
            last_active_key = f"last_active_{self.strategy_name}"
            last_active = float(self.r.get(last_active_key) or time.time())
            downtime = time.time() - last_active
            
            metrics.append(HealthMetric(
                name="connection_downtime",
                value=downtime,
                threshold_warning=self.thresholds["connection_downtime"]["warning"],
                threshold_critical=self.thresholds["connection_downtime"]["critical"],
                unit="秒",
                description="系统无响应时间"
            ))
            
            # 5. 净值更新状态检查
            netvalue_key = f"netvalue_btc{self.strategy_name[3:]}_{self.strategy_name[-1]}_detail"
            netvalue_data = self.r.get(netvalue_key)
            if netvalue_data:
                try:
                    data = json.loads(netvalue_data)
                    last_update = data.get("last_update_ts", 0)
                    netvalue_lag = time.time() - last_update
                    
                    metrics.append(HealthMetric(
                        name="netvalue_update_lag",
                        value=netvalue_lag,
                        threshold_warning=120,  # 2分钟
                        threshold_critical=300,  # 5分钟
                        unit="秒",
                        description="净值更新延迟"
                    ))
                except:
                    pass
            
        except Exception as e:
            logging.error(f"指标收集失败: {e}")
        
        return metrics

    async def _send_health_alert(self, issues: List[HealthMetric], level: AlertLevel):
        """记录健康状态问题（告警已移除）"""
        try:
            # 构建告警消息
            alert_key = f"health_alert_{level.value}_{len(issues)}"

            # 防止重复记录 (5分钟内不重复记录相同问题)
            if alert_key in self.alerts_sent:
                if time.time() - self.alerts_sent[alert_key] < 300:
                    return

            issue_details = []
            for issue in issues:
                issue_details.append({
                    "metric": issue.name,
                    "value": issue.value,
                    "threshold": issue.threshold_critical if level == AlertLevel.CRITICAL else issue.threshold_warning,
                    "unit": issue.unit,
                    "description": issue.description
                })

            # 记录健康问题（告警已移除，使用日志记录）
            logging.warning(f"系统健康检查: {level.value}级，发现{len(issues)}个问题")
            logging.warning(f"策略: {self.strategy_name}, 时间: {datetime.now().isoformat()}")
            for detail in issue_details:
                logging.warning(f"  - {detail['description']}: {detail['value']}{detail['unit']} (阈值: {detail['threshold']}{detail['unit']})")

            self.alerts_sent[alert_key] = time.time()

        except Exception as e:
            logging.error(f"记录健康状态失败: {e}")

    def record_api_call(self, success: bool = True):
        """记录API调用结果"""
        try:
            total_key = f"api_calls_{self.strategy_name}_count"
            error_key = f"api_errors_{self.strategy_name}_count"
            
            # 使用Redis的原子操作增加计数
            self.r.incr(total_key)
            if not success:
                self.r.incr(error_key)
                
            # 设置过期时间为1小时，避免数据无限增长
            self.r.expire(total_key, 3600)
            self.r.expire(error_key, 3600)
            
        except Exception as e:
            logging.error(f"记录API调用失败: {e}")

    def record_websocket_reconnect(self):
        """记录WebSocket重连"""
        try:
            key = f"websocket_reconnects_{self.strategy_name}"
            self.r.incr(key)
            self.r.expire(key, 3600)  # 1小时过期
        except Exception as e:
            logging.error(f"记录WebSocket重连失败: {e}")

    def record_order_result(self, success: bool = True):
        """记录订单执行结果"""
        try:
            total_key = f"orders_total_{self.strategy_name}"
            failed_key = f"orders_failed_{self.strategy_name}"
            
            self.r.incr(total_key)
            if not success:
                self.r.incr(failed_key)
                
            self.r.expire(total_key, 3600)
            self.r.expire(failed_key, 3600)
            
        except Exception as e:
            logging.error(f"记录订单结果失败: {e}")

    def update_last_active(self):
        """更新最后活跃时间"""
        try:
            key = f"last_active_{self.strategy_name}"
            self.r.set(key, time.time())
        except Exception as e:
            logging.error(f"更新活跃时间失败: {e}")

    def get_health_summary(self) -> Dict[str, Any]:
        """获取健康状态摘要"""
        try:
            health_key = f"health_status_{self.strategy_name}"
            health_data = self.r.get(health_key)
            
            if health_data:
                return json.loads(health_data)
            else:
                return {
                    "status": "unknown",
                    "message": "No health data available"
                }
        except Exception as e:
            logging.error(f"获取健康摘要失败: {e}")
            return {"status": "error", "message": str(e)}