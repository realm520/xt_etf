# -*- coding: utf-8 -*-
"""
Prometheus HTTP 服务器

提供 /metrics 端点供 Prometheus 抓取指标

Author: ETF Trading Team
Date: 2025-01-22
"""

import logging
import threading
from typing import Optional
from prometheus_client import start_http_server, REGISTRY
from prometheus_client.core import CollectorRegistry

logger = logging.getLogger(__name__)


class PrometheusServer:
    """
    Prometheus HTTP 服务器

    启动一个 HTTP 服务器，提供 /metrics 端点
    """

    def __init__(
        self,
        port: int = 8000,
        addr: str = '0.0.0.0',
        registry: Optional[CollectorRegistry] = None
    ):
        """
        初始化 Prometheus 服务器

        Args:
            port: HTTP 服务端口
            addr: 监听地址（默认 0.0.0.0，所有网卡）
            registry: 自定义 Registry（默认使用全局 REGISTRY）
        """
        self.port = port
        self.addr = addr
        self.registry = registry or REGISTRY
        self._server_thread: Optional[threading.Thread] = None
        self._started = False

    def start(self) -> bool:
        """
        启动 Prometheus HTTP 服务器（非阻塞）

        Returns:
            bool: 是否启动成功
        """
        if self._started:
            logger.warning(f"Prometheus 服务器已经在运行，端口: {self.port}")
            return True

        try:
            # 使用 prometheus_client 自带的 HTTP 服务器
            # start_http_server 会在后台线程启动服务器
            start_http_server(
                port=self.port,
                addr=self.addr,
                registry=self.registry
            )

            self._started = True
            logger.info(f"✅ Prometheus HTTP 服务器已启动")
            logger.info(f"   监听地址: http://{self.addr}:{self.port}/metrics")
            logger.info(f"   Prometheus 可通过此端点抓取指标")

            return True

        except OSError as e:
            if "Address already in use" in str(e):
                logger.error(f"❌ 端口 {self.port} 已被占用，请检查是否有其他服务使用该端口")
            else:
                logger.error(f"❌ Prometheus 服务器启动失败: {e}")
            return False

        except Exception as e:
            logger.error(f"❌ Prometheus 服务器启动失败: {e}")
            return False

    def is_running(self) -> bool:
        """
        检查服务器是否在运行

        Returns:
            bool: 是否在运行
        """
        return self._started

    def get_metrics_url(self) -> str:
        """
        获取 metrics 端点 URL

        Returns:
            str: metrics 端点完整 URL
        """
        return f"http://{self.addr}:{self.port}/metrics"
