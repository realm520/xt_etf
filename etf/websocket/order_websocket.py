# -*- coding: utf-8 -*-
"""
XT交易所订单WebSocket客户端
实时监听订单状态更新，替代轮询机制

Author: ETF Trading System
Date: 2025-01-24
"""

import asyncio
import json
import logging
import threading
import time
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from collections import defaultdict

try:
    import websockets
except ImportError:
    websockets = None
    logging.warning("websockets库未安装，WebSocket功能不可用。请运行: uv pip install websockets")

logger = logging.getLogger(__name__)


class OrderWebSocketClient:
    """
    XT交易所订单WebSocket客户端

    功能：
    - 实时订阅订单更新(order stream)
    - 订单状态变化回调
    - 自动重连机制
    - 心跳保活
    - 线程安全的状态管理

    支持的订单状态：
    - NEW: 订单已创建
    - PARTIALLY_FILLED: 部分成交
    - FILLED: 完全成交
    - CANCELED: 已取消
    - REJECTED: 被拒绝
    - EXPIRED: 已过期
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        symbol: str,
        ws_url: str = "wss://stream.xt.com/private",
        ping_interval: int = 20,
        ping_timeout: int = 10,
        reconnect_delay: int = 5,
        max_reconnect_attempts: int = 10,
        on_order_update: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
        client=None
    ):
        """
        初始化订单WebSocket客户端

        Args:
            access_key: XT API访问密钥
            secret_key: XT API密钥
            symbol: 交易对符号，如"btc_usdt"
            ws_url: WebSocket服务器地址（私有流）
            ping_interval: 心跳间隔（秒）
            ping_timeout: 心跳超时（秒）
            reconnect_delay: 重连延迟（秒）
            max_reconnect_attempts: 最大重连次数
            on_order_update: 订单更新回调函数 (order_data: Dict) -> None
            on_trade: 成交回调函数 (trade_data: Dict) -> None

        Note:
            XT私有WebSocket需要认证，使用listenKey机制
        """
        if websockets is None:
            raise ImportError("websockets库未安装，无法使用WebSocket功能")

        self.access_key = access_key
        self.secret_key = secret_key
        self.symbol = symbol.lower()
        self.client = client  # REST API client for getting listenKey
        self.ws_url = ws_url
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # 回调函数
        self.on_order_update = on_order_update
        self.on_trade = on_trade

        # 连接状态
        self._ws = None
        self._running = False
        self._connected = False
        self._reconnect_count = 0
        self._listen_key = None

        # 异步事件循环（在独立线程中运行）
        self._loop = None
        self._thread = None

        # Phase 5.2: 移除订单状态缓存，使用 OrderManager 统一管理
        # self._order_cache 已废弃，订单状态由 OrderManager 维护

        # 统计信息
        self._stats = {
            'messages_received': 0,
            'order_updates': 0,
            'trades': 0,
            'reconnects': 0,
            'errors': 0,
            'last_message_time': None,
            'order_states': defaultdict(int)  # 各状态订单计数
        }

        logger.info(f"订单WebSocket客户端初始化: {symbol} @ {ws_url}")

    def start(self):
        """在后台线程启动WebSocket连接"""
        if self._running:
            logger.warning("订单WebSocket已在运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()
        logger.info("订单WebSocket后台线程已启动")

    def stop(self):
        """停止WebSocket连接"""
        self._running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close(), self._loop)

        # 等待线程退出
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        logger.info("订单WebSocket已停止")

    def _run_async_loop(self):
        """在后台线程中运行异步事件循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._connect_and_subscribe())
        except Exception as e:
            logger.error(f"订单WebSocket事件循环异常: {e}", exc_info=True)
        finally:
            self._loop.close()

    async def _get_listen_key(self) -> Optional[str]:
        """
        获取listenKey用于认证私有WebSocket连接

        Returns:
            listenKey字符串，失败返回None

        Note:
            调用XT REST API的 POST /v4/ws-token 接口
        """
        try:
            if self.client is None:
                logger.warning("listenKey获取功能需要REST API client支持")
                return None
            
            # 使用client获取listenKey
            result = self.client.get_listen_key()
            logger.debug(f"get_listen_key API返回: type={type(result)}, value={repr(result)}")
            
            listen_key = None
            
            if result and isinstance(result, str) and len(result) > 10:
                listen_key = result
            elif result and isinstance(result, dict):
                # 尝试多种可能的字段名
                for key in ['accessToken', 'listenKey', 'token', 'jwt']:
                    if key in result and result[key]:
                        listen_key = result[key]
                        break
            
            if listen_key and isinstance(listen_key, str) and len(listen_key) > 10:
                logger.info(f"成功获取listenKey: {listen_key[:20]}... (长度: {len(listen_key)})")
                return listen_key
            else:
                logger.error(f"获取listenKey返回格式异常或为空: {repr(result)}")
                return None

        except Exception as e:
            logger.error(f"获取listenKey失败: {e}", exc_info=True)
            return None

    async def _keep_alive_listen_key(self):
        """
        保持listenKey活跃（每30分钟延长一次）

        Note:
            需要定期调用 PUT /v4/ws-token 接口
        """
        while self._running and self._connected:
            try:
                await asyncio.sleep(30 * 60)  # 30分钟

                # TODO: 调用REST API延长listenKey
                # PUT /v4/ws-token?listenKey={listenKey}
                logger.debug("延长listenKey有效期")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"延长listenKey失败: {e}")

    async def _connect_and_subscribe(self):
        """连接WebSocket并订阅订单数据"""
        while self._running:
            try:
                # Step 1: 获取listenKey
                self._listen_key = await self._get_listen_key()
                if not self._listen_key:
                    logger.error("无法获取listenKey，5秒后重试...")
                    await asyncio.sleep(5)
                    continue

                # Step 2: 连接WebSocket（使用Header传递listenKey，避免URL参数超时问题）
                # QA2环境URL参数方式会超时，改用Header方式
                url = self.ws_url
                headers = {
                    "X-Listen-Key": self._listen_key,
                }
                logger.info(f"WebSocket基础URL: {self.ws_url}")
                logger.info(f"正在连接订单WebSocket (Header认证)...")

                async with websockets.connect(
                    url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    additional_headers=headers
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_count = 0

                    logger.info("✅ 订单WebSocket连接成功")

                    # Step 3: 订阅订单更新流
                    await self._subscribe_orders()

                    # Step 4: 启动listenKey保活任务
                    keep_alive_task = asyncio.create_task(self._keep_alive_listen_key())

                    # Step 5: 接收消息循环
                    try:
                        await self._message_loop()
                    finally:
                        keep_alive_task.cancel()

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"订单WebSocket连接关闭: {e}")
                self._connected = False
                await self._handle_reconnect()

            except Exception as e:
                logger.error(f"订单WebSocket异常: {e}", exc_info=True)
                self._stats['errors'] += 1
                self._connected = False
                await self._handle_reconnect()

    async def _subscribe_orders(self):
        """
        订阅订单和成交更新流（XT官方协议）

        订阅格式:
        {
            "method": "subscribe",
            "params": ["order@symbol", "trade@symbol"],
            "id": "request_id"
        }

        注意：需要同时订阅order和trade频道（单数形式）：
        - order: 订单状态变化（NEW, PARTIALLY_FILLED, FILLED, CANCELED等）
        - trade: 成交明细（每笔成交的价格、数量、手续费等）
        """
        # 订阅订单和成交频道（不需要指定symbol，会推送账户下所有订单）
        # 订阅消息必须包含 listenKey
        
        # 验证 listenKey 有效性
        if not self._listen_key or not isinstance(self._listen_key, str) or len(self._listen_key) < 10:
            logger.error(f"listenKey 无效: {repr(self._listen_key)}, 无法订阅订单流")
            raise ValueError(f"Invalid listenKey: {repr(self._listen_key)}")
        
        subscribe_msg = {
            "method": "subscribe",
            "params": ["order", "trade"],
            "listenKey": self._listen_key,
            "id": str(int(time.time() * 1000))
        }

        logger.info(f"发送订阅消息, listenKey长度: {len(self._listen_key)}, 前20字符: {self._listen_key[:20]}...")
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info(f"已订阅订单和成交更新流: order, trade (账户级别，过滤symbol: {self.symbol})")

    async def _message_loop(self):
        """消息接收循环"""
        async for message in self._ws:
            if not self._running:
                break

            try:
                self._process_message(message)
                self._stats['messages_received'] += 1
                self._stats['last_message_time'] = datetime.now()

            except Exception as e:
                logger.error(f"处理订单消息失败: {e}", exc_info=True)
                self._stats['errors'] += 1

    def _process_message(self, message: str):
        """
        处理WebSocket消息（XT官方协议）

        订单更新消息格式（注意：字段使用短名称）:
        {
            "topic": "order",
            "event": "order",
            "data": {
                "s": "btc_usdt",           // Symbol
                "i": "6216559590087220004", // Order ID
                "ci": "test123",            // Client order ID
                "st": "PARTIALLY_FILLED",   // State (NEW/PARTIALLY_FILLED/FILLED/CANCELED/REJECTED/EXPIRED)
                "sd": "BUY",                // Side (BUY/SELL)
                "tp": "LIMIT",              // Type (LIMIT/MARKET)
                "oq": "4",                  // Original quantity
                "eq": "2",                  // Executed quantity
                "lq": "2",                  // Remaining quantity
                "p": "4000",                // Price
                "ap": "30000",              // Average price
                "f": "0.002",               // Fee
                "t": 1656043204763,         // Happened time (ms)
                "ct": 1656043204663         // Create time (ms)
            }
        }

        成交消息格式:
        {
            "topic": "trade",
            "event": "trade",
            "data": {
                "s": "btc_usdt",             // Symbol
                "i": 6316559590087222000,    // Trade ID
                "oi": 6616559590087222666,   // Order ID
                "p": "43000",                // Price
                "q": "0.21",                 // Quantity
                "v": "9030",                 // Quote quantity
                "b": true,                   // Whether buyer is maker
                "tm": 1,                     // Taker/maker: 1=taker, 2=maker
                "t": 1655992403617           // Trade time (ms)
            }
        }
        """
        try:
            data = json.loads(message)

            # 处理订阅响应
            if 'code' in data:
                code = data.get('code')
                msg = data.get('msg', '')
                request_id = data.get('id', '')

                if code == 0:
                    logger.info(f"✅ 订阅成功: {msg} (id={request_id})")
                else:
                    logger.warning(f"⚠️ 订阅响应: code={code}, msg={msg} (id={request_id})")
                return

            # 处理订单更新（注意：topic是单数 "order"）
            if data.get('topic') == 'order' and 'data' in data:
                self._handle_order_update(data['data'])
                return

            # 处理成交推送（注意：topic是单数 "trade"）
            if data.get('topic') == 'trade' and 'data' in data:
                self._handle_trade(data['data'])
                return

            # 未知消息类型
            logger.warning(f"未识别的消息类型: {data.get('topic')}")

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")

    def _handle_order_update(self, order_data: Dict[str, Any]):
        """
        处理订单更新（使用XT API短字段名）

        字段映射:
            s: symbol, i: orderId, ci: clientOrderId, st: state,
            sd: side, tp: type, p: price, oq: origQty, eq: executedQty,
            lq: leavingQty, ap: avgPrice, f: fee, t: time, ct: createTime

        Args:
            order_data: 订单数据字典（短字段名格式）
        """
        try:
            # 使用短字段名
            order_id = order_data.get('i')
            state = order_data.get('st')
            symbol = order_data.get('s')

            # 过滤非当前交易对的订单（账户级别推送）
            if symbol and self.symbol and symbol.lower() != self.symbol.lower():
                logger.debug(f"忽略其他交易对订单: {symbol} (当前: {self.symbol})")
                return

            logger.info(
                f"📋 订单更新: {order_id} | {symbol} | {state} | "
                f"价格:{order_data.get('p')} | "
                f"已成交:{order_data.get('eq')}/{order_data.get('oq')}"
            )

            # Phase 5.2: 移除订单缓存更新（由 OrderManager 统一管理）
            # 只更新统计信息
            if state:
                self._stats['order_states'][state] += 1
            self._stats['order_updates'] += 1

            # 调用回调函数（传递原始短字段名数据）
            if self.on_order_update:
                try:
                    self.on_order_update(order_data)
                except Exception as e:
                    logger.error(f"订单更新回调失败: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"处理订单更新失败: {e}", exc_info=True)

    def _handle_trade(self, trade_data: Dict[str, Any]):
        """
        处理成交推送（使用XT API短字段名）

        字段映射:
            s: symbol, i: tradeId, oi: orderId, p: price, q: quantity,
            v: quoteQty, b: buyerIsMaker, tm: takerMaker (1=taker, 2=maker), t: time

        Args:
            trade_data: 成交数据字典（短字段名格式）
        """
        try:
            # 使用短字段名
            trade_id = trade_data.get('i')
            order_id = trade_data.get('oi')
            symbol = trade_data.get('s')
            quantity = trade_data.get('q')
            price = trade_data.get('p')

            # 过滤非当前交易对的成交（账户级别推送）
            if symbol and self.symbol and symbol.lower() != self.symbol.lower():
                logger.debug(f"忽略其他交易对成交: {symbol} (当前: {self.symbol})")
                return

            logger.info(
                f"💰 成交推送: {trade_id} | 订单:{order_id} | {symbol} | "
                f"价格:{price} | 数量:{quantity}"
            )

            self._stats['trades'] += 1

            # 调用回调函数（传递原始短字段名数据）
            if self.on_trade:
                try:
                    self.on_trade(trade_data)
                except Exception as e:
                    logger.error(f"成交回调失败: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"处理成交推送失败: {e}", exc_info=True)

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
        delay = min(delay, 60)  # 最多60秒

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
                logger.error(f"关闭订单WebSocket失败: {e}")

    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        [已废弃] 获取订单当前状态

        Phase 5.2: 此方法已废弃，请使用 OrderManager.open_orders.get(order_id)

        Args:
            order_id: 订单ID

        Returns:
            None（缓存已移除）
        """
        logger.warning("get_order_status() 已废弃，请使用 OrderManager.open_orders.get(order_id)")
        return None

    def get_all_cached_orders(self) -> Dict[str, Dict[str, Any]]:
        """
        [已废弃] 获取所有缓存的订单

        Phase 5.2: 此方法已废弃，请使用 OrderManager.get_open_orders_list()

        Returns:
            空字典（缓存已移除）
        """
        logger.warning("get_all_cached_orders() 已废弃，请使用 OrderManager.get_open_orders_list()")
        return {}

    def clear_order_cache(self):
        """[已废弃] 清空订单缓存

        Phase 5.2: 此方法已废弃，订单状态由 OrderManager 管理
        """
        logger.warning("clear_order_cache() 已废弃，订单状态由 OrderManager 管理")

    def is_connected(self) -> bool:
        """检查WebSocket是否已连接"""
        return self._connected

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self._stats.copy()
        stats['connected'] = self._connected
        stats['reconnect_count'] = self._reconnect_count
        # Phase 5.2: 移除 cached_orders（由 OrderManager 管理）
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

    # 订单更新回调
    def on_order_update(order_data):
        print(f"\n📋 订单更新回调:")
        print(f"  订单ID: {order_data.get('orderId')}")
        print(f"  状态: {order_data.get('state')}")
        print(f"  已成交: {order_data.get('executedQty')}/{order_data.get('origQty')}")

    # 成交回调
    def on_trade(trade_data):
        print(f"\n💰 成交回调:")
        print(f"  成交ID: {trade_data.get('tradeId')}")
        print(f"  价格: {trade_data.get('price')}")
        print(f"  数量: {trade_data.get('quantity')}")

    # 使用上下文管理器
    with OrderWebSocketClient(
        access_key="your_access_key",
        secret_key="your_secret_key",
        symbol="btc_usdt",
        on_order_update=on_order_update,
        on_trade=on_trade
    ) as ws_client:
        print("订单WebSocket已启动，等待消息...")

        # 等待连接建立
        time.sleep(5)

        # 循环显示统计
        for i in range(10):
            stats = ws_client.get_stats()
            print(f"\n统计信息 #{i+1}:")
            print(f"  已连接: {stats['connected']}")
            print(f"  接收消息: {stats['messages_received']}")
            print(f"  订单更新: {stats['order_updates']}")
            print(f"  成交推送: {stats['trades']}")
            print(f"  缓存订单: {stats['cached_orders']}")
            print(f"  订单状态分布: {dict(stats['order_states'])}")

            time.sleep(5)

    print("\n订单WebSocket已关闭")
