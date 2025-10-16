# -*- coding: utf-8 -*-
"""
OpenTelemetry 可观测性初始化

支持 Metrics, Traces, Logs 统一导出
使用 OTLP (OpenTelemetry Protocol) 协议

Author: ETF Trading Team
Date: 2025-01-16
"""

import os
import logging
from typing import Optional

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION, DEPLOYMENT_ENVIRONMENT
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

logger = logging.getLogger(__name__)


def init_otel(
    service_name: str,
    otlp_endpoint: Optional[str] = None,
    enable_metrics: bool = True,
    enable_traces: bool = False,
    export_interval_ms: int = 10000,
    service_version: str = "1.0.0",
    environment: str = "production"
) -> metrics.Meter:
    """
    初始化 OpenTelemetry 可观测性

    Args:
        service_name: 服务名称（例如：etf-stg3l）
        otlp_endpoint: OTLP Collector 端点（默认 http://localhost:4317）
        enable_metrics: 是否启用 Metrics 导出
        enable_traces: 是否启用 Traces 导出
        export_interval_ms: Metrics 导出间隔（毫秒）
        service_version: 服务版本
        environment: 部署环境（production/qa/dev）

    Returns:
        Meter 实例，用于创建指标
    """

    # 从环境变量获取端点（优先级最高）
    if otlp_endpoint is None:
        otlp_endpoint = os.getenv("OTLP_ENDPOINT", "http://localhost:4317")

    logger.info(f"初始化 OpenTelemetry: service={service_name}, endpoint={otlp_endpoint}")

    # 定义服务资源属性
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
        DEPLOYMENT_ENVIRONMENT: environment,
        "service.instance.id": os.getenv("HOSTNAME", "localhost"),
    })

    # ===== Metrics 初始化 =====
    if enable_metrics:
        try:
            # 创建 OTLP Metrics 导出器
            metric_exporter = OTLPMetricExporter(
                endpoint=otlp_endpoint,
                insecure=True,  # 开发环境使用非加密连接
            )

            # 创建周期性导出读取器
            metric_reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=export_interval_ms
            )

            # 创建 MeterProvider
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader]
            )

            # 设置全局 MeterProvider
            metrics.set_meter_provider(meter_provider)

            logger.info(f"✅ Metrics 初始化成功，导出间隔: {export_interval_ms}ms")
        except Exception as e:
            logger.error(f"❌ Metrics 初始化失败: {e}")
            logger.warning("系统将继续运行，但不会导出 Metrics")

    # ===== Traces 初始化（可选）=====
    if enable_traces:
        try:
            # 创建 OTLP Trace 导出器
            trace_exporter = OTLPSpanExporter(
                endpoint=otlp_endpoint,
                insecure=True,
            )

            # 创建 TracerProvider
            trace_provider = TracerProvider(resource=resource)
            trace_provider.add_span_processor(
                BatchSpanProcessor(trace_exporter)
            )

            # 设置全局 TracerProvider
            trace.set_tracer_provider(trace_provider)

            logger.info(f"✅ Traces 初始化成功")
        except Exception as e:
            logger.error(f"❌ Traces 初始化失败: {e}")
            logger.warning("系统将继续运行，但不会导出 Traces")

    # 返回 Meter 实例
    return metrics.get_meter(service_name)


def get_meter(service_name: str) -> metrics.Meter:
    """
    获取 Meter 实例

    如果 OpenTelemetry 未初始化，返回 NoOp Meter（不会报错）
    """
    return metrics.get_meter(service_name)


def get_tracer(service_name: str) -> trace.Tracer:
    """
    获取 Tracer 实例

    如果 OpenTelemetry 未初始化，返回 NoOp Tracer（不会报错）
    """
    return trace.get_tracer(service_name)
