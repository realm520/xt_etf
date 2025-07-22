import asyncio
import gzip
import json
import logging
from socket import gaierror
from typing import Optional
from asyncio import sleep
from random import random

# load orjson if available, otherwise default to json
orjson = None
try:
    import orjson as orjson
except ImportError:
    pass

try:
    from websockets.exceptions import ConnectionClosedError  # type: ignore
except ImportError:
    from websockets import ConnectionClosedError  # type: ignore


Proxy = None
proxy_connect = None
try:
    from websockets_proxy import Proxy as w_Proxy, proxy_connect as w_proxy_connect

    Proxy = w_Proxy
    proxy_connect = w_proxy_connect
except ImportError:
    pass

import websockets as ws

from binance.exceptions import (
    BinanceWebsocketClosed,
    BinanceWebsocketUnableToConnect,
    BinanceWebsocketQueueOverflow,
)
from binance.helpers import get_loop
from binance.ws.constants import WSListenerState


class ReconnectingWebsocket:
    MAX_RECONNECTS = 20  # 增加重连次数
    MAX_RECONNECT_SECONDS = 300  # 增加最大重连间隔
    MIN_RECONNECT_WAIT = 0.1
    TIMEOUT = 30  # 增加超时时间
    NO_MESSAGE_RECONNECT_TIMEOUT = 120  # 增加无消息重连超时
    MAX_QUEUE_SIZE = 1000  # 增加队列大小
    BACKOFF_MULTIPLIER = 1.5  # 指数退避倍数
    MAX_BACKOFF_SECONDS = 300  # 最大退避时间

    def __init__(
        self,
        url: str,
        path: Optional[str] = None,
        prefix: str = "ws/",
        is_binary: bool = False,
        exit_coro=None,
        https_proxy: Optional[str] = None,
        **kwargs,
    ):
        self._loop = get_loop()
        self._log = logging.getLogger(__name__)
        self._path = path
        self._url = url
        self._exit_coro = exit_coro
        self._prefix = prefix
        self._reconnects = 0
        self._is_binary = is_binary
        self._conn = None
        self._socket = None
        self.ws: Optional[ws.WebSocketClientProtocol] = None  # type: ignore
        self.ws_state = WSListenerState.INITIALISING
        self._queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._handle_read_loop = None
        self._https_proxy = https_proxy
        self._ws_kwargs = kwargs
        self._last_message_time = None  # 上次接收消息时间
        self._connection_start_time = None  # 连接开始时间
        self._total_reconnects = 0  # 总重连次数统计

    def json_dumps(self, msg):
        if orjson:
            return orjson.dumps(msg)
        return json.dumps(msg)

    def json_loads(self, msg):
        if orjson:
            return orjson.loads(msg)
        return json.loads(msg)

    async def __aenter__(self):
        await self.connect()
        return self

    async def close(self):
        await self.__aexit__(None, None, None)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._log.debug(f"Closing Websocket {self._url}{self._prefix}{self._path}")
        if self._handle_read_loop:
            await self._kill_read_loop()
        if self._exit_coro:
            await self._exit_coro(self._path)
        if self.ws:
            await self.ws.close()
        if self._conn and hasattr(self._conn, "protocol"):
            await self._conn.__aexit__(exc_type, exc_val, exc_tb)
        self.ws = None

    async def connect(self):
        self._log.debug("Establishing new WebSocket connection")
        self.ws_state = WSListenerState.RECONNECTING
        await self._before_connect()

        ws_url = (
            f"{self._url}{getattr(self, '_prefix', '')}{getattr(self, '_path', '')}"
        )

        # handle https_proxy
        if self._https_proxy:
            if not Proxy or not proxy_connect:
                raise ImportError(
                    "websockets_proxy is not installed, please install it to use a websockets proxy (pip install websockets_proxy)"
                )
            proxy = Proxy.from_url(self._https_proxy)  # type: ignore
            self._conn = proxy_connect(
                ws_url, close_timeout=0.1, proxy=proxy, **self._ws_kwargs
            )  # type: ignore
        else:
            self._conn = ws.connect(ws_url, close_timeout=0.1, **self._ws_kwargs)  # type: ignore

        try:
            self.ws = await self._conn.__aenter__()
        except Exception as e:  # noqa
            self._log.error(f"Failed to connect to websocket: {e}")
            self.ws_state = WSListenerState.RECONNECTING
            raise e
        self.ws_state = WSListenerState.STREAMING
        self._reconnects = 0
        self._connection_start_time = asyncio.get_event_loop().time()
        self._last_message_time = asyncio.get_event_loop().time()
        await self._after_connect()
        if not self._handle_read_loop:
            self._handle_read_loop = self._loop.call_soon_threadsafe(
                asyncio.create_task, self._read_loop()
            )

    async def _kill_read_loop(self):
        self.ws_state = WSListenerState.EXITING
        while self._handle_read_loop:
            await sleep(0.1)
        self._log.debug("Finished killing read_loop")

    async def _before_connect(self):
        pass

    async def _after_connect(self):
        pass

    def _handle_message(self, evt):
        if self._is_binary:
            try:
                evt = gzip.decompress(evt)
            except (ValueError, OSError) as e:
                self._log.error(f"Failed to decompress message: {(e)}")
                raise
            except Exception as e:
                self._log.error(f"Unexpected decompression error: {(e)}")
                raise
        try:
            return self.json_loads(evt)
        except ValueError as e:
            self._log.error(f"JSON Value Error parsing message: Error: {(e)}")
            raise
        except TypeError as e:
            self._log.error(f"JSON Type Error parsing message. Error: {(e)}")
            raise
        except Exception as e:
            self._log.error(f"Unexpected error parsing message. Error: {(e)}")
            raise

    async def _read_loop(self):
        try:
            while True:
                try:
                    while self.ws_state == WSListenerState.RECONNECTING:
                        await self._run_reconnect()

                    if self.ws_state == WSListenerState.EXITING:
                        self._log.debug(
                            f"_read_loop {self._path} break for {self.ws_state}"
                        )
                        break
                    elif self.ws.state == ws.protocol.State.CLOSING:  # type: ignore
                        await asyncio.sleep(0.1)
                        continue
                    elif self.ws.state == ws.protocol.State.CLOSED:  # type: ignore
                        self._reconnect()
                        raise BinanceWebsocketClosed(
                            "Connection closed. Reconnecting..."
                        )
                    elif self.ws_state == WSListenerState.STREAMING:
                        assert self.ws
                        res = await asyncio.wait_for(
                            self.ws.recv(), timeout=self.TIMEOUT
                        )
                        self._last_message_time = asyncio.get_event_loop().time()
                        res = self._handle_message(res)
                        self._log.debug(f"Received message: {res}")
                        if res:
                            try:
                                await asyncio.wait_for(
                                    self._queue.put(res), timeout=1.0
                                )
                            except asyncio.TimeoutError:
                                self._log.warning("Queue put timeout, dropping message")
                                # 清理部分队列以释放空间
                                if self._queue.qsize() > self.MAX_QUEUE_SIZE * 0.8:
                                    for _ in range(min(100, self._queue.qsize() // 4)):
                                        try:
                                            self._queue.get_nowait()
                                        except:
                                            break
                except asyncio.TimeoutError:
                    current_time = asyncio.get_event_loop().time()
                    if self._last_message_time:
                        no_message_duration = current_time - self._last_message_time
                        self._log.debug(f"No message in {self.TIMEOUT} seconds (total: {no_message_duration:.1f}s)")
                        
                        # 如果长时间没有消息，触发重连
                        if no_message_duration > self.NO_MESSAGE_RECONNECT_TIMEOUT:
                            self._log.warning(f"No message for {no_message_duration:.1f}s, triggering reconnect")
                            self._reconnect()
                            continue
                    else:
                        self._log.debug(f"no message in {self.TIMEOUT} seconds")
                except asyncio.CancelledError as e:
                    self._log.debug(f"_read_loop cancelled error {e}")
                    break
                except (
                    asyncio.IncompleteReadError,
                    gaierror,
                    ConnectionClosedError,
                    BinanceWebsocketClosed,
                ) as e:
                    # reports errors and continue loop
                    self._log.error(f"{e.__class__.__name__} ({e})")
                    await self._queue.put({
                        "e": "error",
                        "type": f"{e.__class__.__name__}",
                        "m": f"{e}",
                    })
                except (
                    BinanceWebsocketUnableToConnect,
                    BinanceWebsocketQueueOverflow,
                    Exception,
                ) as e:
                    # reports errors and break the loop
                    self._log.error(f"Unknown exception ({e})")
                    await self._queue.put({
                        "e": "error",
                        "type": e.__class__.__name__,
                        "m": f"{e}",
                    })
                    break
        finally:
            self._handle_read_loop = None  # Signal the coro is stopped
            self._reconnects = 0

    async def _run_reconnect(self):
        await self.before_reconnect()
        
        # 改进重连逻辑：允许无限重连，但有智能退避
        reconnect_wait = self._get_reconnect_wait(self._reconnects)
        
        # 如果达到最大重连次数，重置计数器但增加基础等待时间
        if self._reconnects >= self.MAX_RECONNECTS:
            self._log.warning(f"Reached max reconnects ({self.MAX_RECONNECTS}), resetting counter with extended backoff")
            self._reconnects = self.MAX_RECONNECTS // 2  # 重置到中等水平
            reconnect_wait = max(reconnect_wait, 180)  # 至少等待3分钟
        
        self._log.info(
            f"WebSocket reconnecting (attempt #{self._total_reconnects}, current cycle: {self._reconnects}) - "
            f"waiting {reconnect_wait}s"
        )
        
        await asyncio.sleep(reconnect_wait)
        
        try:
            await self.connect()
            self._log.info(f"WebSocket reconnected successfully after {self._total_reconnects} total attempts")
        except Exception as e:
            self._log.error(f"Reconnection attempt failed: {e}")
            # 不再抛出异常，而是继续尝试
            pass

    async def recv(self):
        res = None
        while not res:
            try:
                res = await asyncio.wait_for(self._queue.get(), timeout=self.TIMEOUT)
            except asyncio.TimeoutError:
                self._log.debug(f"no message in {self.TIMEOUT} seconds")
        return res

    async def _wait_for_reconnect(self):
        while (
            self.ws_state != WSListenerState.STREAMING
            and self.ws_state != WSListenerState.EXITING
        ):
            await sleep(0.1)

    def _get_reconnect_wait(self, attempts: int) -> int:
        """改进的指数退避算法"""
        # 使用更平滑的指数退避
        base_wait = min(
            self.MAX_BACKOFF_SECONDS,
            self.MIN_RECONNECT_WAIT * (self.BACKOFF_MULTIPLIER ** attempts)
        )
        # 添加随机抖动避免雷群效应
        jitter = random() * base_wait * 0.1
        wait_time = base_wait + jitter
        return round(min(wait_time, self.MAX_RECONNECT_SECONDS))

    async def before_reconnect(self):
        if self.ws:
            self.ws = None

        if self._conn and hasattr(self._conn, "protocol"):
            await self._conn.__aexit__(None, None, None)

        self._reconnects += 1
        self._total_reconnects += 1
        
        # 记录重连统计信息
        if self._connection_start_time:
            connection_duration = asyncio.get_event_loop().time() - self._connection_start_time
            self._log.info(f"Connection lasted {connection_duration:.1f}s before reconnect #{self._total_reconnects}")
        
        # 重连次数过多时，重置计数器给系统喘息时间
        if self._reconnects >= self.MAX_RECONNECTS // 2:
            self._log.warning(f"High reconnect count ({self._reconnects}), implementing progressive backoff")
            await sleep(min(60, self._reconnects * 2))  # 额外延迟

    def _reconnect(self):
        self.ws_state = WSListenerState.RECONNECTING
