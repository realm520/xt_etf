# -*- coding: utf-8 -*-
"""
OpenTelemetry 可观测性初始化

支持两种模式：
1. Prometheus Pull 模式（推荐）：提供 HTTP /metrics 端点供 Prometheus 抓取
2. OTLP Push 模式：主动推送到 OTLP Collector（兼容模式）

Author: ETF Trading Team
Date: 2025-01-22 (Updated)
"""

import os
import logging
from typing import Optional, Literal, Tuple

from prometheus_client import CollectorRegistry, REGISTRY

logger = logging.getLogger(__name__)

# 导出类型
ExportMode = Literal["prometheus", "otlp", "both"]


def init_prometheus_metrics(
    service_name: str,
    service_version: str = "1.0.0",
    environment: str = "production",
    registry: Optional[CollectorRegistry] = None
) -> CollectorRegistry:
    """
    初始化 Prometheus 指标（Pull 模式）

    Args:
        service_name: 服务名称
        service_version: 服务版本
        environment: 部署环境
        registry: 自定义 Registry（默认使用全局 REGISTRY）

    Returns:
        CollectorRegistry: Prometheus Registry 实例
    """
    if registry is None:
        registry = REGISTRY

    logger.info(f"✅ Prometheus Metrics 初始化成功")
    logger.info(f"   服务: {service_name}")
    logger.info(f"   版本: {service_version}")
    logger.info(f"   环境: {environment}")
    logger.info(f"   模式: Pull（Prometheus 主动抓取）")

    return registry


def init_otel(
    service_name: str,
    otlp_endpoint: Optional[str] = None,
    export_mode: ExportMode = "prometheus",
    prometheus_port: int = 8000,
    enable_traces: bool = False,
    export_interval_ms: int = 10000,
    service_version: str = "1.0.0",
    environment: str = "production"
) -> Tuple[Optional[CollectorRegistry], str]:
    """
    初始化 OpenTelemetry 可观测性（兼容函数）

    Args:
        service_name: 服务名称（例如：etf-stg3l）
        otlp_endpoint: OTLP Collector 端点（仅在 export_mode 包含 'otlp' 时使用）
        export_mode: 导出模式 ('prometheus' | 'otlp' | 'both')
        prometheus_port: Prometheus HTTP 服务端口（仅在 export_mode 包含 'prometheus' 时使用）
        enable_traces: 是否启用 Traces 导出（仅 OTLP 模式）
        export_interval_ms: Metrics 导出间隔（毫秒，仅 OTLP 模式）
        service_version: 服务版本
        environment: 部署环境（production/qa/dev）

    Returns:
        Tuple[CollectorRegistry | None, str]: (Registry实例, 导出模式)
    """

    logger.info(f"初始化 Metrics 系统: service={service_name}, mode={export_mode}")

    if export_mode == "prometheus" or export_mode == "both":
        # Prometheus 模式
        registry = init_prometheus_metrics(
            service_name=service_name,
            service_version=service_version,
            environment=environment
        )
        return registry, export_mode

    elif export_mode == "otlp":
        # OTLP Push 模式（原有逻辑，保留向后兼容）
        logger.warning("⚠️  OTLP Push 模式已弃用，建议迁移到 Prometheus Pull 模式")
        logger.warning("   设置 METRICS_EXPORT_MODE=prometheus 启用 Pull 模式")

        # 导入 OTLP 相关依赖（延迟导入，避免不必要的依赖）
        try:
            from opentelemetry import metrics, trace
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION, DEPLOYMENT_ENVIRONMENT
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        except ImportError as e:
            logger.error(f"❌ OTLP 依赖未安装: {e}")
            logger.error("   请运行: pip install opentelemetry-exporter-otlp-proto-grpc")
            return None, export_mode

        # 从环境变量获取端点
        if otlp_endpoint is None:
            otlp_endpoint = os.getenv("OTLP_ENDPOINT", "http://localhost:4317")

        # 定义服务资源属性
        resource = Resource.create({
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            DEPLOYMENT_ENVIRONMENT: environment,
            "service.instance.id": os.getenv("HOSTNAME", "localhost"),
        })

        # Metrics 初始化
        try:
            metric_exporter = OTLPMetricExporter(
                endpoint=otlp_endpoint,
                insecure=True,
            )

            metric_reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=export_interval_ms
            )

            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader]
            )

            metrics.set_meter_provider(meter_provider)
            logger.info(f"✅ OTLP Metrics 初始化成功，导出间隔: {export_interval_ms}ms")
        except Exception as e:
            logger.error(f"❌ OTLP Metrics 初始化失败: {e}")

        # Traces 初始化（可选）
        if enable_traces:
            try:
                trace_exporter = OTLPSpanExporter(
                    endpoint=otlp_endpoint,
                    insecure=True,
                )

                trace_provider = TracerProvider(resource=resource)
                trace_provider.add_span_processor(
                    BatchSpanProcessor(trace_exporter)
                )

                trace.set_tracer_provider(trace_provider)
                logger.info(f"✅ OTLP Traces 初始化成功")
            except Exception as e:
                logger.error(f"❌ OTLP Traces 初始化失败: {e}")

        return None, export_mode

    else:
        logger.error(f"❌ 不支持的导出模式: {export_mode}")
        return None, export_mode


def get_meter(service_name: str):
    """
    获取 Meter 实例（兼容函数）

    注意：Prometheus 模式下此函数无意义，保留仅为向后兼容
    """
    logger.warning("⚠️  get_meter() 在 Prometheus 模式下已弃用")
    logger.warning("   请直接使用 prometheus_client 创建指标")
    return None


def get_tracer(service_name: str):
    """
    获取 Tracer 实例（兼容函数）

    注意：Prometheus 模式下此函数无意义，保留仅为向后兼容
    """
    logger.warning("⚠️  get_tracer() 在 Prometheus 模式下已弃用")
    return None
