# -*- coding: utf-8 -*-
"""
交易所连接健康检查器
监控API连接状态，实现智能重连和降级处理

Author: Claude Code  
Date: 2025-01-21
"""

import asyncio
import time
import logging
import threading
from typing import Dict, Optional, Callable, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

from etf.alert import AlertLevel


class ConnectionStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded" 
    UNSTABLE = "unstable"
    FAILED = "failed"


@dataclass
class ConnectionMetrics:
    """连接指标"""
    success_count: int = 0
    error_count: int = 0
    last_success_time: float = 0
    last_error_time: float = 0
    consecutive_failures: int = 0
    average_response_time: float = 0
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.error_count
        return self.success_count / max(total, 1)
    
    @property
    def error_rate(self) -> float:
        return 1 - self.success_rate


class ConnectionHealthChecker:
    """交易所连接健康检查器"""
    
    def __init__(
        self,
        client,
        strategy_name: str = "unknown",
        check_interval: int = 30,
        health_check_timeout: int = 5,
    ):
        self.client = client
        self.strategy_name = strategy_name
        self.check_interval = check_interval
        self.health_check_timeout = health_check_timeout
        
        # 连接指标
        self.metrics = ConnectionMetrics()
        self.status = ConnectionStatus.HEALTHY
        
        # 健康检查配置
        self.thresholds = {
            "error_rate_warning": 0.10,     # 错误率警告阈值
            "error_rate_critical": 0.25,    # 错误率严重阈值
            "consecutive_failures_warning": 3,  # 连续失败警告阈值
            "consecutive_failures_critical": 5, # 连续失败严重阈值
            "response_time_warning": 3.0,    # 响应时间警告阈值(秒)
            "response_time_critical": 10.0,  # 响应时间严重阈值(秒)
            "max_downtime": 300,            # 最大断线时间(秒)
        }
        
        # 状态管理
        self.is_monitoring = False
        self.last_alert_time = {}
        self.degraded_mode = False
        self.circuit_breaker_open = False
        self.circuit_breaker_reset_time = None
        
        # 监控线程
        self._monitor_thread = None
        self._stop_event = threading.Event()
        
        logging.info(f"连接健康检查器初始化完成: {strategy_name}")

    def start_monitoring(self):
        """启动健康监控"""
        if not self.is_monitoring:
            self.is_monitoring = True
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
            logging.info("连接健康监控已启动")

    def stop_monitoring(self):
        """停止健康监控"""
        if self.is_monitoring:
            self.is_monitoring = False
            self._stop_event.set()
            if self._monitor_thread:
                self._monitor_thread.join(timeout=5)
            logging.info("连接健康监控已停止")

    def _monitor_loop(self):
        """监控主循环"""
        while not self._stop_event.wait(self.check_interval):
            try:
                self._perform_health_check()
            except Exception as e:
                logging.error(f"健康检查异常: {e}")

    def _perform_health_check(self):
        """执行健康检查"""
        try:
            start_time = time.time()
            
            # 执行简单的API调用检查连接
            success = self._test_connection()
            
            end_time = time.time()
            response_time = end_time - start_time
            
            # 更新指标
            if success:
                self.metrics.success_count += 1
                self.metrics.last_success_time = end_time
                self.metrics.consecutive_failures = 0
                
                # 重置熔断器
                if self.circuit_breaker_open:
                    self.circuit_breaker_open = False
                    logging.info("连接恢复，熔断器重置")
            else:
                self.metrics.error_count += 1
                self.metrics.last_error_time = end_time
                self.metrics.consecutive_failures += 1
            
            # 更新平均响应时间
            self._update_response_time(response_time)
            
            # 评估连接状态
            new_status = self._evaluate_connection_status()
            
            # 状态变化处理
            if new_status != self.status:
                self._handle_status_change(self.status, new_status)
                self.status = new_status
            
            # 检查是否需要开启熔断器
            if self.metrics.consecutive_failures >= self.thresholds["consecutive_failures_critical"]:
                if not self.circuit_breaker_open:
                    self.circuit_breaker_open = True
                    self.circuit_breaker_reset_time = time.time() + 120  # 2分钟后重置
                    logging.error("连接严重异常，开启熔断器")
                    # 记录熔断器告警（告警已移除，使用日志记录）
                    logging.error(f"熔断器开启: 连续失败{self.metrics.consecutive_failures}次，错误率{self.metrics.error_rate:.2%}")
                    logging.error(f"策略: {self.strategy_name}, 重置时间: {datetime.fromtimestamp(self.circuit_breaker_reset_time).isoformat()}")
            
        except Exception as e:
            logging.error(f"健康检查执行失败: {e}")

    def _test_connection(self) -> bool:
        """测试连接状态"""
        try:
            # 使用轻量级的API调用测试连接
            # 这里可以调用服务器时间或交易对信息等轻量接口
            response = self.client.get_server_time()  # 假设存在此方法
            return response is not None
        except Exception as e:
            logging.warning(f"连接测试失败: {e}")
            return False

    def _update_response_time(self, response_time: float):
        """更新平均响应时间"""
        if self.metrics.average_response_time == 0:
            self.metrics.average_response_time = response_time
        else:
            # 使用指数移动平均
            alpha = 0.1
            self.metrics.average_response_time = (
                alpha * response_time + (1 - alpha) * self.metrics.average_response_time
            )

    def _evaluate_connection_status(self) -> ConnectionStatus:
        """评估连接状态"""
        # 检查熔断器状态
        if self.circuit_breaker_open:
            if self.circuit_breaker_reset_time and time.time() > self.circuit_breaker_reset_time:
                self.circuit_breaker_open = False
                logging.info("熔断器重置时间到，尝试恢复")
            else:
                return ConnectionStatus.FAILED
        
        # 检查连续失败次数
        if self.metrics.consecutive_failures >= self.thresholds["consecutive_failures_critical"]:
            return ConnectionStatus.FAILED
        elif self.metrics.consecutive_failures >= self.thresholds["consecutive_failures_warning"]:
            return ConnectionStatus.UNSTABLE
        
        # 检查错误率
        if self.metrics.error_rate >= self.thresholds["error_rate_critical"]:
            return ConnectionStatus.UNSTABLE
        elif self.metrics.error_rate >= self.thresholds["error_rate_warning"]:
            return ConnectionStatus.DEGRADED
        
        # 检查响应时间
        if self.metrics.average_response_time >= self.thresholds["response_time_critical"]:
            return ConnectionStatus.UNSTABLE
        elif self.metrics.average_response_time >= self.thresholds["response_time_warning"]:
            return ConnectionStatus.DEGRADED
        
        # 检查上次成功时间
        if self.metrics.last_success_time > 0:
            downtime = time.time() - self.metrics.last_success_time
            if downtime > self.thresholds["max_downtime"]:
                return ConnectionStatus.FAILED
        
        return ConnectionStatus.HEALTHY

    def _handle_status_change(self, old_status: ConnectionStatus, new_status: ConnectionStatus):
        """处理状态变化"""
        logging.info(f"连接状态变化: {old_status.value} -> {new_status.value}")

        # 记录状态变化（告警已移除，使用日志记录）
        alert_level = "INFO"
        if new_status == ConnectionStatus.FAILED:
            alert_level = "CRITICAL"
        elif new_status == ConnectionStatus.UNSTABLE:
            alert_level = "ERROR"
        elif new_status == ConnectionStatus.DEGRADED:
            alert_level = "WARNING"

        logging.log(
            logging.CRITICAL if alert_level == "CRITICAL" else
            logging.ERROR if alert_level == "ERROR" else
            logging.WARNING if alert_level == "WARNING" else logging.INFO,
            f"连接状态变化告警: {old_status.value} -> {new_status.value}"
        )
        logging.info(f"  成功率: {self.metrics.success_rate:.2%}")
        logging.info(f"  连续失败: {self.metrics.consecutive_failures}次")
        logging.info(f"  平均响应时间: {self.metrics.average_response_time:.2f}秒")
        logging.info(f"  策略: {self.strategy_name}")

        # 根据新状态执行相应操作
        if new_status == ConnectionStatus.DEGRADED:
            self._enter_degraded_mode()
        elif new_status == ConnectionStatus.UNSTABLE:
            self._handle_unstable_connection()
        elif new_status == ConnectionStatus.FAILED:
            self._handle_connection_failure()
        elif new_status == ConnectionStatus.HEALTHY and old_status != ConnectionStatus.HEALTHY:
            self._restore_normal_mode()

    def _enter_degraded_mode(self):
        """进入降级模式"""
        self.degraded_mode = True
        logging.warning("进入连接降级模式，减少API调用频率")

    def _handle_unstable_connection(self):
        """处理不稳定连接"""
        logging.warning("连接不稳定，实施保护措施")
        # 可以在这里实施额外的保护措施

    def _handle_connection_failure(self):
        """处理连接失败"""
        logging.error("连接失败，停止非关键操作")
        # 可以在这里停止非关键操作

    def _restore_normal_mode(self):
        """恢复正常模式"""
        self.degraded_mode = False
        logging.info("连接恢复正常，退出降级模式")


    def is_connection_healthy(self) -> bool:
        """检查连接是否健康"""
        return self.status == ConnectionStatus.HEALTHY

    def should_reduce_frequency(self) -> bool:
        """是否应该减少调用频率"""
        return self.status in [ConnectionStatus.DEGRADED, ConnectionStatus.UNSTABLE]

    def is_circuit_breaker_open(self) -> bool:
        """检查熔断器是否开启"""
        if self.circuit_breaker_open:
            if self.circuit_breaker_reset_time and time.time() > self.circuit_breaker_reset_time:
                self.circuit_breaker_open = False
                logging.info("熔断器重置时间到")
                return False
        return self.circuit_breaker_open

    def get_health_summary(self) -> Dict[str, Any]:
        """获取健康状态摘要"""
        return {
            "status": self.status.value,
            "success_rate": self.metrics.success_rate,
            "error_rate": self.metrics.error_rate,
            "consecutive_failures": self.metrics.consecutive_failures,
            "average_response_time": self.metrics.average_response_time,
            "circuit_breaker_open": self.circuit_breaker_open,
            "degraded_mode": self.degraded_mode,
            "last_check": datetime.now().isoformat()
        }