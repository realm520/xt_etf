# -*- coding: utf-8 -*-
"""
可观测性模块

提供基于 OpenTelemetry 的 Metrics 收集和导出功能
"""

from .otel import init_otel, get_meter, get_tracer
from .metrics import MetricsCollector

__all__ = [
    "init_otel",
    "get_meter",
    "get_tracer",
    "MetricsCollector",
]
