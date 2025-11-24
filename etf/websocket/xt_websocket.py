# -*- coding: utf-8 -*-
"""
XT Exchange WebSocket客户端
实时订阅市场深度数据，减少REST API调用

Author: ETF Trading System
Date: 2025-01-16
"""

import asyncio
import json
import logging
import threading
import time
from typing import Optional, Dict, Any
from datetime import datetime

try:
    import websockets
except ImportError:
    websockets = None
    logging.warning("websockets库未安装，WebSocket功能不可用。请运行: uv pip install websockets")

logger = logging.getLogger(__name__)


class XTWebSocketClient:
    """
    XT交易所WebSocket客户端

    功能：
    - 实时订阅深度数据(depth)
    - 自动重连机制
    - 心跳保活
    - 线程安全的数据缓存
    - 降级到REST API的fallback机制
    """

    def __init__(
        self,
        symbol: str,
        ws_url: str = "wss://stream.xt.com/public",
        depth_levels: int = 20,
        ping_interval: int = 20,
        ping_timeout: int = 10,
        reconnect_delay: int = 5,
        max_reconnect_attempts: int = 10
    ):
        """
        初始化WebSocket客户端

        Args:
            symbol: 交易对符号，如"btc_usdt"
            ws_url: WebSocket服务器地址
            depth_levels: 订阅的深度档位数量，支持 5/10/20/50，默认20
            ping_interval: 心跳间隔（秒）
            ping_timeout: 心跳超时（秒）
            reconnect_delay: 重连延迟（秒）
            max_reconnect_attempts: 最大重连次数

        Note:
            XT public WebSocket 不需要认证，可直接连接订阅 depth 数据
        """
        if websockets is None:
            raise ImportError("websockets库未安装，无法使用WebSocket功能")

        self.symbol = symbol.lower()
        self.ws_url = ws_url
        self.depth_levels = depth_levels
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # 数据缓存
        self._depth_cache: Optional[Dict[str, Any]] = None
        self._cache_lock = threading.Lock()
        self._cache_timestamp = 0

        # 连接状态
        self._ws = None
        self._running = False
        self._connected = False
        self._reconnect_count = 0

        # 异步事件循环（在独立线程中运行）
        self._loop = None
        self._thread = None

        # 统计信息
        self._stats = {
            'messages_received': 0,
            'depth_updates': 0,
            'reconnects': 0,
            'errors': 0,
            'last_message_time': None
        }

        logger.info(f"WebSocket客户端初始化: {symbol} @ {ws_url}")

    def start(self):
        """在后台线程启动WebSocket连接"""
        if self._running:
            logger.warning("WebSocket已在运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()
        logger.info("WebSocket后台线程已启动")

    def stop(self):
        """停止WebSocket连接"""
        self._running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close(), self._loop)

        # 等待线程退出
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        logger.info("WebSocket已停止")

    def _run_async_loop(self):
        """在后台线程中运行异步事件循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._connect_and_subscribe())
        except Exception as e:
            logger.error(f"WebSocket事件循环异常: {e}", exc_info=True)
        finally:
            self._loop.close()

    async def _connect_and_subscribe(self):
        """连接WebSocket并订阅数据
        
        增强特性:
        - 区分正常停止和异常断开
        - 正常停止时不触发重连
        - CancelledError正确传播
        """
        while self._running:
            try:
                # Public WebSocket 不需要 listenKey
                url = self.ws_url

                logger.info(f"正在连接WebSocket: {url}")

                async with websockets.connect(
                    url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_count = 0

                    logger.info("WebSocket连接成功")

                    # 订阅深度数据
                    await self._subscribe_depth()

                    # 接收消息循环
                    await self._message_loop()
            
            except asyncio.CancelledError:
                # 任务被取消（stop()调用），正常退出，不重连
                logger.info("连接任务被取消，停止运行")
                self._connected = False
                self._running = False
                break

            except websockets.exceptions.ConnectionClosedOK:
                # WebSocket正常关闭
                logger.info("WebSocket正常关闭")
                self._connected = False
                if self._running:
                    await self._handle_reconnect()
                else:
                    break

            except websockets.exceptions.ConnectionClosed as e:
                # WebSocket异常关闭
                logger.warning(f"WebSocket连接关闭: {e}")
                self._connected = False
                if self._running:
                    await self._handle_reconnect()
                else:
                    break

            except Exception as e:
                # 其他未预期的异常
                logger.error(f"WebSocket异常: {e}", exc_info=True)
                self._stats['errors'] += 1
                self._connected = False
                if self._running:
                    await self._handle_reconnect()
                else:
                    break

    async def _subscribe_depth(self):
        """订阅深度数据（XT官方格式：depth@symbol,levels）"""
        subscribe_msg = {
            "method": "subscribe",
            "params": [f"depth@{self.symbol},{self.depth_levels}"],
            "id": str(int(time.time() * 1000))  # ID必须是字符串
        }

        await self._ws.send(json.dumps(subscribe_msg))
        logger.info(f"已订阅深度数据: depth@{self.symbol},{self.depth_levels}")

    async def _message_loop(self):
        """消息接收循环
        
        增强特性:
        - 捕获CancelledError避免误触发重连
        - 持续监听直到明确停止或连接异常
        - 正确处理WebSocket关闭状态
        """
        try:
            async for message in self._ws:
                if not self._running:
                    logger.info("收到停止信号，退出消息循环")
                    break

                try:
                    self._process_message(message)
                    self._stats['messages_received'] += 1
                    self._stats['last_message_time'] = datetime.now()

                except Exception as e:
                    logger.error(f"处理消息失败: {e}", exc_info=True)
                    self._stats['errors'] += 1
        
        except asyncio.CancelledError:
            # 任务被取消，这是正常的停止流程，不触发重连
            logger.info("消息循环被取消（正常停止）")
            raise  # 重新抛出，让上层处理
        
        except websockets.exceptions.ConnectionClosedOK:
            # WebSocket正常关闭，记录但不报错
            logger.info("WebSocket正常关闭")
        
        except websockets.exceptions.ConnectionClosedError as e:
            # WebSocket异常关闭，交给上层重连逻辑处理
            logger.warning(f"WebSocket连接异常关闭: {e}")
            raise  # 重新抛出，触发重连
        
        except Exception as e:
            # 未预期的异常，记录详细信息
            logger.error(f"消息循环异常: {e}", exc_info=True)
            self._stats['errors'] += 1
            raise  # 重新抛出，触发重连

    def _process_message(self, message: str):
        """处理WebSocket消息（XT官方协议）"""
        try:
            data = json.loads(message)

            # 处理订阅响应（官方格式：{"id": "...", "code": 0/1/2, "msg": "..."}）
            if 'code' in data:
                code = data.get('code')
                msg = data.get('msg', '')
                request_id = data.get('id', '')

                if code == 0:
                    logger.info(f"✅ 订阅成功: {msg} (id={request_id})")
                else:
                    logger.warning(f"⚠️ 订阅响应: code={code}, msg={msg} (id={request_id})")
                return

            # 处理深度数据推送（官方格式：{"topic": "depth", "event": "...", "data": {...}}）
            if data.get('topic') == 'depth' and 'data' in data:
                self._update_depth_cache(data['data'])  # 传递 data['data']
                return

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")

    def _update_depth_cache(self, depth_data: Dict[str, Any]):
        """更新深度数据缓存（线程安全）- 已禁用

        注意：根据业务需求，已不再监控订单簿深度数据。
        该方法保留用于兼容性，但不再处理数据。
        """
        # 不再处理和缓存深度数据
        pass

    async def _handle_reconnect(self):
        """处理重连逻辑"""
        if not self._running:
            return

        self._reconnect_count += 1

        if self._reconnect_count > self.max_reconnect_attempts:
            logger.error(
                f"达到最大重连次数({self.max_reconnect_attempts})，停止重连"
            )
            self._running = False
            return

        delay = self.reconnect_delay * (2 ** (self._reconnect_count - 1))  # 指数退避
        delay = min(delay, 60)  # 最大60秒

        logger.warning(
            f"第{self._reconnect_count}次重连，{delay}秒后重试..."
        )

        await asyncio.sleep(delay)
        self._stats['reconnects'] += 1

    async def _close(self):
        """关闭WebSocket连接"""
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.error(f"关闭WebSocket失败: {e}")

    def get_cached_depth(self, max_age: int = 5) -> Optional[Dict[str, Any]]:
        """
        获取缓存的深度数据（线程安全）

        Args:
            max_age: 最大数据年龄（秒），超过则返回None

        Returns:
            深度数据字典，格式与REST API一致
            如果数据过期或不可用，返回None
        """
        with self._cache_lock:
            if self._depth_cache is None:
                return None

            # 检查数据新鲜度
            age = time.time() - self._cache_timestamp
            if age > max_age:
                logger.warning(
                    f"缓存数据过期: {age:.1f}秒 > {max_age}秒"
                )
                return None

            return self._depth_cache.copy()

    def is_connected(self) -> bool:
        """检查WebSocket是否已连接"""
        return self._connected

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self._stats.copy()
        stats['connected'] = self._connected
        stats['reconnect_count'] = self._reconnect_count

        # 计算数据新鲜度
        if self._cache_timestamp > 0:
            stats['cache_age'] = time.time() - self._cache_timestamp
        else:
            stats['cache_age'] = None

        return stats

    def __enter__(self):
        """上下文管理器支持"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器支持"""
        self.stop()


# 测试代码
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # XT public WebSocket 不需要认证
    symbol = "btc_usdt"

    # 使用上下文管理器
    with XTWebSocketClient(symbol) as ws_client:
        print("WebSocket已启动，等待数据...")

        # 等待连接建立
        time.sleep(5)

        # 循环获取数据
        for i in range(10):
            depth = ws_client.get_cached_depth()
            if depth:
                print(f"\n深度数据 #{i+1}:")
                print(f"  Bids: {len(depth['bids'])} 档")
                print(f"  Asks: {len(depth['asks'])} 档")
                print(f"  最佳买价: {depth['bids'][0][0] if depth['bids'] else 'N/A'}")
                print(f"  最佳卖价: {depth['asks'][0][0] if depth['asks'] else 'N/A'}")
            else:
                print(f"\n数据 #{i+1}: 暂无缓存数据")

            # 显示统计
            stats = ws_client.get_stats()
            print(f"  统计: 已接收{stats['messages_received']}条消息，"
                  f"深度更新{stats['depth_updates']}次")

            time.sleep(2)

    print("\nWebSocket已关闭")
