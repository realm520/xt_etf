# -*- coding: utf-8 -*-
"""
XT Exchange WebSocket客户端模块
用于实时订阅市场数据，替代高频REST API轮询
"""

from .xt_websocket import XTWebSocketClient

__all__ = ['XTWebSocketClient']
