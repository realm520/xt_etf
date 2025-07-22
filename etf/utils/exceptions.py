# -*- coding:utf-8 -*-

"""
ETF系统异常处理工具

Author: Claude Code
Date: 2025-01-22
"""

import time
import logging
import functools
from typing import Any, Callable, Optional, Dict, Type
from enum import Enum


class ETFErrorSeverity(Enum):
    """错误严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ETFError(Exception):
    """ETF系统基础异常"""
    def __init__(self, message: str, error_code: str = None, severity: ETFErrorSeverity = ETFErrorSeverity.MEDIUM):
        self.message = message
        self.error_code = error_code
        self.severity = severity
        self.timestamp = time.time()
        super().__init__(self.message)


class NetworkError(ETFError):
    """网络错误"""
    def __init__(self, message: str, retry_after: float = 1.0):
        super().__init__(message, "NETWORK_ERROR", ETFErrorSeverity.MEDIUM)
        self.retry_after = retry_after


class APIError(ETFError):
    """API调用错误"""
    def __init__(self, message: str, status_code: int = None, response_text: str = None):
        super().__init__(message, "API_ERROR", ETFErrorSeverity.HIGH)
        self.status_code = status_code
        self.response_text = response_text


class ValidationError(ETFError):
    """数据验证错误"""
    def __init__(self, message: str, field_name: str = None):
        super().__init__(message, "VALIDATION_ERROR", ETFErrorSeverity.LOW)
        self.field_name = field_name


class OrderError(ETFError):
    """订单处理错误"""
    def __init__(self, message: str, order_id: str = None):
        super().__init__(message, "ORDER_ERROR", ETFErrorSeverity.HIGH)
        self.order_id = order_id


class RiskError(ETFError):
    """风险控制错误"""
    def __init__(self, message: str, risk_level: int = None):
        super().__init__(message, "RISK_ERROR", ETFErrorSeverity.CRITICAL)
        self.risk_level = risk_level


class ConfigurationError(ETFError):
    """配置错误"""
    def __init__(self, message: str, config_key: str = None):
        super().__init__(message, "CONFIG_ERROR", ETFErrorSeverity.HIGH)
        self.config_key = config_key


def retry_on_exception(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None
):
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间(秒)
        backoff_factor: 退避因子
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        wait_time = delay * (backoff_factor ** attempt)
                        
                        logging.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying in {wait_time:.1f}s: {e}"
                        )
                        
                        if on_retry:
                            on_retry(attempt, e, wait_time)
                        
                        time.sleep(wait_time)
                    else:
                        logging.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


def handle_api_errors(func: Callable) -> Callable:
    """
    API错误处理装饰器
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            
            # 检查常见的API错误模式
            if any(keyword in error_msg for keyword in ["rate limit", "too many requests"]):
                raise APIError(f"API rate limit exceeded: {e}", status_code=429)
            elif any(keyword in error_msg for keyword in ["unauthorized", "invalid api key"]):
                raise APIError(f"API authentication failed: {e}", status_code=401)
            elif any(keyword in error_msg for keyword in ["network", "connection", "timeout"]):
                raise NetworkError(f"Network error: {e}")
            elif any(keyword in error_msg for keyword in ["invalid", "bad request"]):
                raise ValidationError(f"Invalid request: {e}")
            else:
                # 重新抛出原始异常，包装为ETFError
                raise ETFError(f"Unexpected error in {func.__name__}: {e}")
    
    return wrapper


def log_exceptions(logger: Optional[logging.Logger] = None):
    """
    异常日志装饰器
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Exception in {func.__name__}: {e}",
                    exc_info=True,
                    extra={
                        "function": func.__name__,
                        "args": str(args)[:100],  # 限制长度
                        "kwargs": str(kwargs)[:100]
                    }
                )
                raise
        
        return wrapper
    return decorator


class CircuitBreaker:
    """
    熔断器实现
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Type[Exception] = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def __call__(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if self.state == "OPEN":
                if self._should_attempt_reset():
                    self.state = "HALF_OPEN"
                else:
                    raise ETFError(
                        f"Circuit breaker is OPEN for {func.__name__}",
                        "CIRCUIT_BREAKER_OPEN",
                        ETFErrorSeverity.HIGH
                    )
            
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
            except self.expected_exception as e:
                self._on_failure()
                raise
        
        return wrapper
    
    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试重置熔断器"""
        return (
            self.last_failure_time and
            time.time() - self.last_failure_time >= self.recovery_timeout
        )
    
    def _on_success(self):
        """成功时的处理"""
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self):
        """失败时的处理"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logging.warning(
                f"Circuit breaker opened after {self.failure_count} failures"
            )


def safe_execute(
    func: Callable,
    *args,
    default_return: Any = None,
    log_errors: bool = True,
    **kwargs
) -> Any:
    """
    安全执行函数，捕获所有异常
    
    Args:
        func: 要执行的函数
        *args: 函数参数
        default_return: 异常时的默认返回值
        log_errors: 是否记录错误日志
        **kwargs: 函数关键字参数
    
    Returns:
        函数返回值或默认值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_errors:
            logging.error(f"Error executing {func.__name__}: {e}")
        return default_return


class ErrorCollector:
    """
    错误收集器，用于批量处理错误
    """
    
    def __init__(self):
        self.errors: List[ETFError] = []
    
    def add_error(self, error: ETFError):
        """添加错误"""
        self.errors.append(error)
    
    def has_errors(self) -> bool:
        """是否有错误"""
        return len(self.errors) > 0
    
    def has_critical_errors(self) -> bool:
        """是否有严重错误"""
        return any(
            error.severity == ETFErrorSeverity.CRITICAL 
            for error in self.errors
        )
    
    def get_errors_by_severity(self, severity: ETFErrorSeverity) -> List[ETFError]:
        """按严重程度获取错误"""
        return [error for error in self.errors if error.severity == severity]
    
    def clear(self):
        """清空错误"""
        self.errors.clear()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "total_errors": len(self.errors),
            "critical_errors": len(self.get_errors_by_severity(ETFErrorSeverity.CRITICAL)),
            "high_errors": len(self.get_errors_by_severity(ETFErrorSeverity.HIGH)),
            "medium_errors": len(self.get_errors_by_severity(ETFErrorSeverity.MEDIUM)),
            "low_errors": len(self.get_errors_by_severity(ETFErrorSeverity.LOW)),
            "errors": [
                {
                    "message": error.message,
                    "error_code": error.error_code,
                    "severity": error.severity.value,
                    "timestamp": error.timestamp
                }
                for error in self.errors
            ]
        }


def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> None:
    """
    验证必需字段
    
    Args:
        data: 要验证的数据
        required_fields: 必需字段列表
    
    Raises:
        ValidationError: 当缺少必需字段时
    """
    missing_fields = []
    
    for field in required_fields:
        if field not in data or data[field] is None:
            missing_fields.append(field)
    
    if missing_fields:
        raise ValidationError(
            f"Missing required fields: {', '.join(missing_fields)}",
            field_name=missing_fields[0]
        )


def validate_price_quantity(price: Any, quantity: Any) -> None:
    """
    验证价格和数量
    
    Args:
        price: 价格
        quantity: 数量
    
    Raises:
        ValidationError: 当价格或数量无效时
    """
    try:
        price_float = float(price)
        quantity_float = float(quantity)
        
        if price_float <= 0:
            raise ValidationError("Price must be positive")
        
        if quantity_float <= 0:
            raise ValidationError("Quantity must be positive")
            
    except (ValueError, TypeError):
        raise ValidationError("Price and quantity must be valid numbers")