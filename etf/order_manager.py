import time
import random
import logging
import os
import json
import redis
from datetime import datetime, timezone, timedelta
from copy import deepcopy
import asyncio
import threading
from typing import Optional, Dict, Any, List, Tuple
from functools import wraps
from etf.alert import send_alert, AlertLevel
from etf.utils.common import get_mid_price
from etf.utils.order_errors import (
    is_permanent_error,
    get_error_description,
    get_blacklist_ttl,
)

# 导入WebSocket订单监听器
try:
    from etf.websocket.order_websocket import OrderWebSocketClient
    ORDER_WEBSOCKET_AVAILABLE = True
except ImportError:
    ORDER_WEBSOCKET_AVAILABLE = False
    logging.warning("订单WebSocket监听器未安装")

# 导入订单记录器
try:
    from etf.storage import get_order_recorder
    ORDER_RECORDER_AVAILABLE = True
except ImportError:
    ORDER_RECORDER_AVAILABLE = False
    logging.warning("订单记录器未安装，订单/成交数据将不会持久化")

# 导入资金检查器
from etf.balance_checker import BalanceChecker, BalanceStatus

# 导入订单状态管理器
from etf.order_state_manager import OrderStateManager


def retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """重试装饰器，用于API调用失败时重试"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = delay * (backoff ** attempt)
                        logging.warning(f"{func.__name__} failed (attempt {attempt + 1}), retrying in {wait_time:.1f}s: {e}")
                        time.sleep(wait_time)
                    else:
                        logging.error(f"{func.__name__} failed after {max_retries + 1} attempts: {e}")
                        break
            raise last_exception
        return wrapper
    return decorator


def handle_api_error(func):
    """API错误处理装饰器"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            
            # 记录API错误（告警已移除，使用日志记录）
            logging.error(f"API错误 {func.__name__}: {error_type} - {error_msg}")
            logging.error(f"策略: {getattr(self, 'strategy_name', 'unknown')}, 操作: order_management")

            # 根据错误类型决定是否重试
            if "rate limit" in error_msg.lower() or "too many requests" in error_msg.lower():
                logging.warning("遇到限频错误，等待后重试")
                time.sleep(5)
                return None
            elif "network" in error_msg.lower() or "connection" in error_msg.lower():
                logging.warning("网络错误，将在下次循环重试")
                return None
            else:
                raise
    return wrapper


class Order:
    def __init__(
        self,
        symbol=None,
        OrderId=None,
        side=None,
        type="LIMIT",
        timeInForce="GTC",
        bizType="SPOT",
        price=None,
        quantity=None,
        quoteQty=None,
    ):
        self.symbol = symbol
        self.OrderId = OrderId
        self.clientOrderId = None
        self.side = side
        self.type = type
        self.timeInForce = timeInForce
        self.bizType = bizType
        self.price = price
        self.quantity = quantity
        self.quoteQty = quoteQty


class OrderManager:
    def __init__(self, spot, strategy_name: str = "unknown", symbol_config=None, enable_websocket: bool = False, tier: int = 200):
        self.counter = 0
        self.client = spot
        self.strategy_name = strategy_name  # 添加策略名称
        self.symbol_config = symbol_config  # Symbol配置管理器
        self.tier = tier  # 订单档位数量（默认200档，避免ORDER_006挂单过多错误）
        self.last_position = 0
        self.position = 0
        self.amount = 0
        self.last_amount = 0
        self.last_amount_5l = None
        self.last_amount_5s = None
        self.last_amount_3l = None
        self.last_amount_3s = None
        self.delta_usdt = None
        self.netvalue = None
        self.init_amount = None


        # orders
        self.open_orders = {}
        self.trade_orders = {}
        self.partially_filled_orders = {}
        self.sent_orders = {}

        self.canceled_orders = []
        self.filled_orders = []

        # trade
        self.trading_history = []
        self.filled_orders = []

        # heding
        self.exposure = {"price": 0, "amount": 0, "value": 0}
        
        # ✅ 新增：成交追踪（用于洗盘交易智能调整）
        self.recent_fills = []  # [(timestamp, volume, price), ...]
        self.fill_window = 60   # 统计窗口：60秒

        # 初始化订单记录器
        if ORDER_RECORDER_AVAILABLE:
            self.order_recorder = get_order_recorder()
            # 创建后台事件循环线程用于异步操作
            self._recorder_loop = None
            self._recorder_thread = None
            self._recorder_running = False
            self._init_recorder_loop()
        else:
            self.order_recorder = None

        # 添加错误统计和健康检查
        self.api_error_count = 0
        self.last_successful_operation = time.time()
        self.consecutive_failures = 0
        self.circuit_breaker_open = False
        self.circuit_breaker_reset_time = None

        # 初始化 Redis 连接用于黑名单管理
        try:
            self.redis_client = redis.Redis(
                host='localhost',
                port=6379,
                db=0,
                decode_responses=True
            )
            self.redis_client.ping()  # 测试连接
            logging.info("Redis 连接成功，黑名单功能已启用")
        except Exception as e:
            logging.warning(f"Redis 连接失败，黑名单功能将被禁用: {e}")
            self.redis_client = None
        
        # 初始化资金检查器（默认关闭，通过配置启用）
        self.balance_checker = None
        self.balance_check_enabled = False
        self.last_balance_check_time = 0
        self.balance_check_interval = 60  # 默认每60秒检查一次
        
        # 初始化WebSocket订单监听器（默认关闭，通过参数启用）
        self.order_ws_client = None
        self.use_order_websocket = False
        
        # 如果启用WebSocket且可用，则初始化订单监听器
        if enable_websocket and ORDER_WEBSOCKET_AVAILABLE:
            self._init_order_websocket()

        # ✅ 初始化订单状态管理器（统一订单状态变更入口）
        self.state_manager = OrderStateManager(
            open_orders=self.open_orders,
            filled_orders=self.filled_orders,
            canceled_orders=self.canceled_orders,
            order_recorder=self.order_recorder,
            async_scheduler=self._schedule_async,
            logger=logging.getLogger(f"{__name__}.StateManager")
        )
        logging.info("OrderStateManager已初始化，成交记录已启用")

    def _init_recorder_loop(self):
        """初始化后台事件循环用于异步操作"""
        def _run_loop():
            """在独立线程中运行事件循环"""
            self._recorder_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._recorder_loop)
            
            # 在后台循环中初始化Redis连接
            try:
                self._recorder_loop.run_until_complete(
                    self.order_recorder.initialize_in_loop()
                )
            except Exception as e:
                logging.error(f"后台线程Redis初始化失败: {e}")
            
            self._recorder_running = True
            logging.info("订单记录器后台事件循环已启动")

            try:
                self._recorder_loop.run_forever()
            finally:
                self._recorder_loop.close()
                logging.info("订单记录器后台事件循环已关闭")

        # 启动后台线程
        self._recorder_thread = threading.Thread(
            target=_run_loop,
            daemon=True,
            name="OrderRecorderLoop"
        )
        self._recorder_thread.start()

        # 等待循环就绪
        max_wait = 5  # 最多等待5秒
        waited = 0
        while not self._recorder_running and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1

        if not self._recorder_running:
            logging.warning("订单记录器后台循环启动超时")

    def _init_order_websocket(self):
        """初始化订单WebSocket监听器
        
        功能：
        - 创建OrderWebSocketClient实例
        - 注册订单更新和成交推送的回调函数
        - 启动后台WebSocket连接
        - 设置use_order_websocket标志
        
        异常处理：
        - 捕获初始化异常并记录错误
        - 初始化失败时降级到REST API轮询
        """
        try:
            # 获取symbol（从第一个订单或配置中获取）
            # 注意：这里假设所有订单都使用相同的symbol
            symbol = None
            if hasattr(self, 'symbol_config') and self.symbol_config:
                # 从symbol_config获取symbol
                symbols = list(self.symbol_config.symbol_configs.keys())
                if symbols:
                    symbol = symbols[0]
            
            if not symbol:
                logging.warning("无法获取symbol，WebSocket订单监听器初始化失败")
                return
            
            # 创建WebSocket订单监听器
            self.order_ws_client = OrderWebSocketClient(
                access_key=self.client.api_key,
                secret_key=self.client.api_secret,
                symbol=symbol,
                on_order_update=self._on_order_update,
                on_trade=self._on_trade
            )
            
            # 启动WebSocket连接（在后台线程中运行）
            self.order_ws_client.start()
            self.use_order_websocket = True
            
            logging.info(f"订单WebSocket监听器已启动: {symbol}")
            
        except Exception as e:
            logging.error(f"初始化订单WebSocket监听器失败: {e}", exc_info=True)
            self.order_ws_client = None
            self.use_order_websocket = False
    
    def _on_order_update(self, order_data: Dict):
        """订单更新回调函数 - 重构版

        当WebSocket接收到订单状态变化时触发。

        Args:
            order_data: 订单数据字典，包含以下字段：
                - orderId: 订单ID
                - state: 订单状态 (NEW, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, EXPIRED)
                - symbol: 交易对
                - side: 方向 (BUY/SELL)
                - price: 价格
                - origQty: 原始数量
                - executedQty: 已执行数量
                - leavingQty: 剩余数量
                - avgPrice: 平均成交价
                - fee: 手续费
                - time: 创建时间
                - updatedTime: 更新时间

        ✅ 重构说明：
        所有订单状态变更现在统一通过OrderStateManager处理，确保：
        1. 状态转换合法性验证
        2. 内存缓存原子性更新
        3. 数据库异步持久化
        4. 审计追踪完整性
        """
        try:
            order_id = order_data.get('orderId')
            state = order_data.get('state')

            if not order_id or not state:
                logging.warning(f"订单更新数据不完整: {order_data}")
                return

            logging.debug(f"订单状态更新: {order_id} -> {state}")

            # ✅ 统一的订单数据格式
            unified_order_data = {
                "symbol": order_data.get('symbol'),
                "side": order_data.get('side'),
                "price": order_data.get('price'),
                "quantity": order_data.get('origQty'),
                "orderId": order_id,
                "executed_qty": order_data.get('executedQty', '0'),
                "state": state,
                "avgPrice": order_data.get('avgPrice', '0'),
                "fee": order_data.get('fee', '0'),
                "time": order_data.get('time'),
                "updatedTime": order_data.get('updatedTime')
            }

            # ✅ 调用统一状态管理器
            success = self.state_manager.update_order_state(
                order_id=order_id,
                new_state=state,
                order_data=unified_order_data,
                trigger_source='websocket'
            )

            if success:
                # 更新partially_filled_orders追踪（业务逻辑需要）
                if state == 'PARTIALLY_FILLED':
                    self.partially_filled_orders[order_id] = self.open_orders.get(order_id)
                    logging.info(f"订单部分成交: {order_id} | 已执行 {order_data.get('executedQty')}/{order_data.get('origQty')}")

                # 从partially_filled_orders中移除已终态的订单
                elif state in ['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED']:
                    if order_id in self.partially_filled_orders:
                        self.partially_filled_orders.pop(order_id)
                    logging.info(f"订单状态变更: {order_id} -> {state}")
            else:
                logging.warning(f"订单状态更新失败（可能是非法转换）: {order_id} -> {state}")

        except Exception as e:
            logging.error(f"处理订单更新失败: {e}", exc_info=True)
    
    def _on_trade(self, trade_data: Dict):
        """成交推送回调函数 - 重构版

        当WebSocket接收到订单成交事件时触发。

        Args:
            trade_data: 成交数据字典，包含以下字段：
                - tradeId: 成交ID
                - orderId: 订单ID
                - symbol: 交易对
                - side: 方向 (BUY/SELL)
                - price: 成交价格
                - quantity: 成交数量
                - fee: 手续费
                - feeCurrency: 手续费币种
                - isMaker: 是否为maker
                - time: 成交时间

        ✅ 重构说明：
        成交事件处理现在通过OrderStateManager.handle_trade_event()统一管理，确保：
        1. 订单累计成交量正确更新
        2. 订单状态自动转换（PARTIALLY_FILLED → FILLED）
        3. 成交数据完整记录到数据库
        """
        try:
            order_id = trade_data.get('orderId')
            quantity = float(trade_data.get('quantity', 0))
            price = float(trade_data.get('price', 0))

            if not order_id:
                logging.warning(f"成交推送缺少orderId: {trade_data}")
                return

            logging.info(f"成交推送: {order_id} | {quantity}@{price}")

            # 1. 记录成交到recent_fills（用于洗盘交易智能调整）
            self.record_fill(quantity, price)

            # ✅ 2. 调用统一状态管理器处理成交事件
            #   这会自动：
            #   - 更新订单的executed_qty
            #   - 判断订单状态（PARTIALLY_FILLED vs FILLED）
            #   - 触发数据库持久化
            success = self.state_manager.handle_trade_event(
                trade_data=trade_data,
                trigger_source='websocket'
            )

            if not success:
                logging.warning(f"成交事件处理失败: {order_id}")

            # 3. 记录成交到数据库（如果order_recorder可用）
            if self.order_recorder:
                record_data = {
                    "symbol": trade_data.get('symbol'),
                    "trade_id": trade_data.get('tradeId'),
                    "order_id": order_id,
                    "price": price,
                    "quantity": quantity,
                    "quote_quantity": price * quantity,
                    "is_buyer": trade_data.get('side') == 'BUY',
                    "traded_at": datetime.now(timezone.utc),
                    "strategy_name": self.strategy_name,
                    "is_maker": trade_data.get('isMaker', False),
                    "fee": float(trade_data.get('fee', 0)),
                    "fee_currency": trade_data.get('feeCurrency', 'USDT')
                }

                # 异步记录成交
                self.record_trade(record_data)

            # 4. 更新交易历史（用于本地追踪）
            self.trading_history.append({
                "trade_id": trade_data.get('tradeId'),
                "order_id": order_id,
                "symbol": trade_data.get('symbol'),
                "side": trade_data.get('side'),
                "price": price,
                "quantity": quantity,
                "time": trade_data.get('time'),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            # 限制trading_history大小（保留最近1000条）
            if len(self.trading_history) > 1000:
                self.trading_history = self.trading_history[-1000:]

        except Exception as e:
            logging.error(f"处理成交推送失败: {e}", exc_info=True)

    def enable_balance_check(
        self,
        warning_threshold: float = 0.3,
        critical_threshold: float = 0.2,
        insufficient_threshold: float = 0.1,
        check_interval: int = 60,
    ):
        """
        启用资金检查功能
        
        Args:
            warning_threshold: 警告阈值（剩余资金比例）
            critical_threshold: 危急阈值（剩余资金比例）
            insufficient_threshold: 不足阈值（剩余资金比例）
            check_interval: 检查间隔（秒）
        """
        self.balance_checker = BalanceChecker(
            strategy_name=self.strategy_name,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            insufficient_threshold=insufficient_threshold,
        )
        self.balance_check_enabled = True
        self.balance_check_interval = check_interval
        logging.info(
            f"[{self.strategy_name}] 资金检查已启用 "
            f"(警告:{warning_threshold*100}%, 危急:{critical_threshold*100}%, "
            f"不足:{insufficient_threshold*100}%, 间隔:{check_interval}秒)"
        )
    
    def check_balance_before_order(
        self,
        symbol: str,
        force_check: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        """
        下单前检查资金是否充足
        
        Args:
            symbol: 交易对
            force_check: 是否强制检查（忽略时间间隔）
            
        Returns:
            (can_place_order, message): (是否可以下单, 详细信息)
        """
        import time
        
        # 未启用资金检查
        if not self.balance_check_enabled or self.balance_checker is None:
            return True, None
        
        # 检查时间间隔
        current_time = time.time()
        if not force_check and (current_time - self.last_balance_check_time) < self.balance_check_interval:
            return True, None
        
        try:
            # 获取余额信息
            balance_info = self.balance_checker.get_balance_info(self.client, "usdt")
            available_balance = balance_info.get("available", 0.0)
            total_balance = balance_info.get("balance", 0.0)
            
            # 计算挂单占用金额
            pending_order_value = self.balance_checker.calculate_pending_order_value(
                self.open_orders,
                symbol,
            )
            
            # 检查资金状态
            status, message = self.balance_checker.check_balance(
                available_balance=available_balance,
                total_balance=total_balance,
                pending_order_value=pending_order_value,
            )
            
            # 更新检查时间
            self.last_balance_check_time = current_time
            
            # 判断是否应该停止策略
            should_stop = self.balance_checker.should_stop_strategy(status)
            
            if should_stop:
                logging.critical(
                    f"[{self.strategy_name}] 资金不足，建议停止策略！{message}"
                )
                return False, message
            elif status in [BalanceStatus.CRITICAL, BalanceStatus.WARNING]:
                logging.warning(
                    f"[{self.strategy_name}] 资金状态异常: {message}"
                )
                return True, message
            else:
                # 状态正常，只在首次或状态变化时记录
                return True, None
                
        except Exception as e:
            logging.error(f"[{self.strategy_name}] 资金检查失败: {e}")
            # 检查失败时不阻止下单，但记录错误
            return True, f"资金检查失败: {e}"

    def _schedule_async(self, coro):
        """
        线程安全地调度异步操作

        Args:
            coro: 协程对象
        """
        if not self._recorder_loop or not self._recorder_running:
            logging.warning("订单记录器后台循环未就绪，跳过记录")
            return

        try:
            # 使用 call_soon_threadsafe 在另一个线程的事件循环中安全调度任务
            asyncio.run_coroutine_threadsafe(coro, self._recorder_loop)
        except Exception as e:
            logging.error(f"调度异步任务失败: {e}")

    def shutdown_recorder(self):
        """优雅关闭订单记录器"""
        if not self._recorder_loop or not self._recorder_running:
            return

        logging.info("正在关闭订单记录器...")
        self._recorder_running = False

        if self._recorder_loop:
            self._recorder_loop.call_soon_threadsafe(self._recorder_loop.stop)

        if self._recorder_thread and self._recorder_thread.is_alive():
            self._recorder_thread.join(timeout=3)

        logging.info("订单记录器已关闭")

    def _check_circuit_breaker(self):
        """检查熔断器状态"""
        if self.circuit_breaker_open:
            if self.circuit_breaker_reset_time and time.time() > self.circuit_breaker_reset_time:
                logging.info("熔断器重置，尝试恢复操作")
                self.circuit_breaker_open = False
                self.consecutive_failures = 0
                return True
            else:
                logging.warning("熔断器开启，跳过API操作")
                return False
        return True
    
    def _record_api_success(self):
        """记录API成功操作"""
        self.last_successful_operation = time.time()
        self.consecutive_failures = 0
        if self.circuit_breaker_open:
            logging.info("API操作成功，熔断器状态重置")
            self.circuit_breaker_open = False
    
    def _record_api_failure(self):
        """记录API失败操作"""
        self.api_error_count += 1
        self.consecutive_failures += 1

        # 如果连续失败次数过多，开启熔断器
        if self.consecutive_failures >= 5:
            self.circuit_breaker_open = True
            self.circuit_breaker_reset_time = time.time() + 60  # 60秒后重置
            logging.error(f"连续失败{self.consecutive_failures}次，开启熔断器60秒")

    def _add_to_blacklist(self, symbol: str, error_code: str, ttl: Optional[int] = None):
        """
        将交易对添加到黑名单

        Args:
            symbol: 交易对符号
            error_code: 错误码
            ttl: 黑名单过期时间（秒），None 则使用默认值
        """
        if not self.redis_client:
            return

        try:
            # 使用默认 TTL
            if ttl is None:
                ttl = get_blacklist_ttl(error_code)

            # 构建黑名单键
            blacklist_key = f"order_blacklist:{symbol}"

            # 准备黑名单数据
            blacklist_data = {
                "reason": error_code,
                "description": get_error_description(error_code),
                "timestamp": time.time(),
                "strategy": self.strategy_name
            }

            # 存储到 Redis
            self.redis_client.setex(
                blacklist_key,
                ttl,
                json.dumps(blacklist_data)
            )

            logging.info(
                f"交易对 {symbol} 已加入黑名单: {error_code} - {blacklist_data['description']}, "
                f"过期时间: {ttl}秒"
            )

        except Exception as e:
            logging.error(f"添加黑名单失败: {e}")

    def is_symbol_blacklisted(self, symbol: str) -> bool:
        """
        检查交易对是否在黑名单中

        Args:
            symbol: 交易对符号

        Returns:
            True 如果在黑名单中
        """
        if not self.redis_client:
            return False

        try:
            blacklist_key = f"order_blacklist:{symbol}"
            return self.redis_client.exists(blacklist_key) > 0
        except Exception as e:
            logging.error(f"检查黑名单失败: {e}")
            return False

    def get_blacklist_info(self, symbol: str) -> Dict[str, Any]:
        """
        获取交易对黑名单详细信息

        Args:
            symbol: 交易对符号

        Returns:
            黑名单信息字典，包含 reason, description, timestamp, remaining_seconds
        """
        if not self.redis_client:
            return {}

        try:
            blacklist_key = f"order_blacklist:{symbol}"
            data = self.redis_client.get(blacklist_key)

            if not data:
                return {}

            blacklist_info = json.loads(data)

            # 添加剩余时间
            ttl = self.redis_client.ttl(blacklist_key)
            blacklist_info["remaining_seconds"] = max(0, ttl)

            return blacklist_info

        except Exception as e:
            logging.error(f"获取黑名单信息失败: {e}")
            return {}

    def clear_blacklist(self, symbol: str):
        """
        手动清除交易对黑名单

        Args:
            symbol: 交易对符号
        """
        if not self.redis_client:
            return

        try:
            blacklist_key = f"order_blacklist:{symbol}"
            if self.redis_client.delete(blacklist_key):
                logging.info(f"已清除 {symbol} 的黑名单")
            else:
                logging.warning(f"{symbol} 不在黑名单中")
        except Exception as e:
            logging.error(f"清除黑名单失败: {e}")

    def get_depth_data(self, symbol):
        """
        获取深度数据（已废弃，保留用于兼容性）
        
        注意：该方法已不再使用，所有价格计算已改为使用市场价格。
        保留仅为向后兼容，避免破坏现有代码。
        
        Returns:
            None: 始终返回None
        """
        logging.debug(f"get_depth_data 已废弃，不再获取订单簿数据: {symbol}")
        return None

    # 使用共同的 get_mid_price 函数来替代重复代码

    def create_temp_id(self):
        # 创建一个临时 ID
        # temp_id = str(uuid.uuid4())
        # timestamp = str(int(time.time() * 1000))  # 精确到毫秒的时间戳（13位）
        # counter_part = f"{self.counter:02d}"
        random_part = str(random.randint(10**17, 10**18 - 1))  # 4位随机数
        # self.counter = (self.counter + 1) % 100
        temp_id = random_part

        # try:
        # assert temp_id not in self.orders

        # self.orders[temp_id] = Order(order_data)
        return temp_id  # 返回临时 ID

    def get_min_order_value(self, symbol: str) -> float:
        """
        获取Symbol的最小订单金额（USDT）
        
        优先级:
        1. Symbol配置管理器中的minOrderAmt（最准确）
        2. 默认值1.2 USDT
        
        Args:
            symbol: 交易对符号，如'TON3LUSDT'
            
        Returns:
            float: 最小订单金额（USDT）
        """
        try:
            # 从Symbol配置管理器获取
            if self.symbol_config:
                config = self.symbol_config.get_config(symbol)
                if config:
                    min_order_amt = config.get("minOrderAmt")
                    if min_order_amt:
                        # 返回最小金额 + 20%余量（与OrderManager内部逻辑保持一致）
                        return float(min_order_amt) * 1.2
            
            # 降级：返回默认值
            logging.debug(f"使用默认最小订单金额: 1.2 USDT (Symbol: {symbol})")
            return 1.2
            
        except Exception as e:
            logging.warning(f"获取{symbol}最小订单金额失败: {e}，使用默认值1.2")
            return 1.2

    def remove_order(self, orderid):
        if orderid in self.open_orders:
            del self.open_orders[orderid]
            logging.info(f"deleted {orderid} from self.orders")
        # for symbol in self.open_orders.keys():
        #     for side in ["SELL", "BUY"]:
        #         self.open_orders[symbol][side] = [
        #             order for order in self.open_orders[symbol][side] if order["orderId"] != orderid
        #         ]

    # add orders
    @handle_api_error
    def add_order(
        self,
        symbol,
        side="BUY",
        type="LIMIT",
        price=None,
        quantity=None,
        order_purpose="market_making",
    ):
        if not self._check_circuit_breaker():
            return None

        # ✅ 格式化和验证订单参数（如果Symbol配置管理器可用）
        if self.symbol_config and price is not None and quantity is not None:
            original_price = price
            original_quantity = quantity

            # 格式化价格和数量
            price = self.symbol_config.format_price(symbol, price)
            quantity = self.symbol_config.format_quantity(symbol, quantity)

            # 记录格式化结果
            if abs(price - original_price) > 1e-10 or abs(quantity - original_quantity) > 1e-10:
                logging.debug(
                    f"订单参数格式化: "
                    f"价格 {original_price} → {price}, "
                    f"数量 {original_quantity} → {quantity}"
                )

            # 验证订单参数
            is_valid, error_msg = self.symbol_config.validate_order(symbol, price, quantity)
            if not is_valid:
                logging.error(f"订单验证失败: {error_msg}")
                logging.error(f"交易对: {symbol}, 侧: {side}, 价格: {price}, 数量: {quantity}")
                return None

        # 生成带前缀的clientOrderId，用于订单类型识别
        base_id = self.create_temp_id()
        if order_purpose == "market_making":
            client_order_id = f"mm_{base_id}"
        elif order_purpose == "anti_pin":
            client_order_id = f"antipin_{base_id}"
        elif order_purpose == "wash_trading":
            client_order_id = f"wash_{base_id}"
        elif order_purpose == "hedging":
            client_order_id = f"hedge_{base_id}"
        else:
            client_order_id = base_id

        order = Order(
            symbol=symbol, side=side, type=type, price=price, quantity=quantity
        )
        order.clientOrderId = client_order_id

        # 🆕 第一阶段：记录 PENDING 状态到数据库
        pending_order_id = None
        if self.order_recorder:
            try:
                depth = self.depth if hasattr(self, "depth") else None
                
                pending_order_data = {
                    "symbol": order.symbol,
                    "order_id": f"PENDING_{order.clientOrderId}",  # 临时ID
                    "client_order_id": order.clientOrderId,
                    "side": order.side,
                    "order_type": order.type,
                    "price": float(order.price),
                    "quantity": float(order.quantity),
                    "status": "PENDING",  # 🔥 PENDING 状态
                    "strategy_name": self.strategy_name,
                    "order_purpose": order_purpose,
                    "net_value": float(self.netvalue) if self.netvalue else None,
                    "best_bid": float(depth["bids"][0][0])
                    if depth and depth.get("bids")
                    else None,
                    "best_ask": float(depth["asks"][0][0])
                    if depth and depth.get("asks")
                    else None,
                    "timestamp": datetime.now(timezone.utc),
                }
                
                # 同步记录PENDING状态（使用线程安全调度）
                self._schedule_async(self.order_recorder.record_order(pending_order_data))
                pending_order_id = pending_order_data["order_id"]
                logging.debug(f"📝 订单 {order.clientOrderId} 已记录 PENDING 状态")
                
            except Exception as e:
                logging.error(f"记录PENDING状态失败: {e}")

        # 🆕 第二阶段：向交易所发送订单
        try:
            response = self.client.order(
                symbol=order.symbol,
                side=order.side,
                type=order.type,
                biz_type=order.bizType,
                time_in_force=order.timeInForce,
                client_order_id=order.clientOrderId,
                price=order.price,
                quantity=order.quantity,
                quote_qty=order.quoteQty,
            )
            self._record_api_success()
            
        except Exception as e:
            self._record_api_failure()
            
            # 🆕 订单失败 → 更新为 REJECTED 状态
            if self.order_recorder and pending_order_id:
                try:
                    rejected_data = {
                        "symbol": order.symbol,
                        "order_id": pending_order_id,
                        "client_order_id": order.clientOrderId,
                        "side": order.side,
                        "order_type": order.type,
                        "price": float(order.price),
                        "quantity": float(order.quantity),
                        "status": "REJECTED",  # 🔥 REJECTED 状态
                        "strategy_name": self.strategy_name,
                        "order_purpose": order_purpose,
                        "timestamp": datetime.now(timezone.utc),
                        "extra_info": {"error": str(e)}
                    }
                    self._schedule_async(self.order_recorder.record_order(rejected_data))
                    logging.warning(f"❌ 订单 {order.clientOrderId} 被拒绝: {e}")
                except Exception as update_err:
                    logging.error(f"更新REJECTED状态失败: {update_err}")
            
            logging.error(f"下单失败: {e}")
            raise

        # 🆕 第三阶段：交易所确认成功 → 更新为 NEW 状态
        if response and self.order_recorder:
            try:
                depth = self.depth if hasattr(self, "depth") else None
                exchange_order_id = response.get("orderId", "")

                confirmed_order_data = {
                    "symbol": order.symbol,
                    "order_id": exchange_order_id,  # 🔥 使用交易所返回的真实ID
                    "client_order_id": order.clientOrderId,
                    "side": order.side,
                    "order_type": order.type,
                    "price": float(order.price),
                    "quantity": float(order.quantity),
                    "status": "NEW",  # 🔥 NEW 状态
                    "strategy_name": self.strategy_name,
                    "order_purpose": order_purpose,
                    "net_value": float(self.netvalue) if self.netvalue else None,
                    "best_bid": float(depth["bids"][0][0])
                    if depth and depth.get("bids")
                    else None,
                    "best_ask": float(depth["asks"][0][0])
                    if depth and depth.get("asks")
                    else None,
                    "timestamp": datetime.now(timezone.utc),
                }

                # 使用线程安全的方式调度异步记录
                self._schedule_async(self.order_recorder.record_order(confirmed_order_data))
                logging.debug(f"✅ 订单 {exchange_order_id} 已确认 NEW 状态")

            except Exception as e:
                logging.error(f"记录订单失败: {e}")

        return response

    @handle_api_error
    def place_single_order(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        order_purpose: str = "wash_trading",
        delay_ms: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        逐笔下单方法 - 专为洗盘交易设计

        与 add_order 的区别：
        1. 更简洁的参数签名，适合循环调用
        2. 支持下单间隔延迟（模拟真实交易节奏）
        3. 针对洗盘交易优化的日志输出
        4. 返回统一格式的结果，便于批量处理统计

        Args:
            symbol: 交易对符号 (如 'TON3LUSDT')
            side: 交易方向 ('BUY' 或 'SELL')
            price: 下单价格
            quantity: 下单数量
            order_purpose: 订单用途标识，默认 'wash_trading'
            delay_ms: 下单后延迟毫秒数（0-1000），用于模拟真实交易节奏

        Returns:
            Dict: 包含以下字段的结果字典
                - success: bool，是否成功
                - order_id: str，订单ID（成功时）
                - error: str，错误信息（失败时）
                - price: float，实际下单价格
                - quantity: float，实际下单数量
                - side: str，交易方向
            None: 熔断器开启时返回

        Example:
            >>> result = order_manager.place_single_order(
            ...     symbol="TON3LUSDT",
            ...     side="BUY",
            ...     price=0.7280,
            ...     quantity=10.5,
            ...     delay_ms=50
            ... )
            >>> if result and result['success']:
            ...     print(f"订单成功: {result['order_id']}")
        """
        # 检查熔断器
        if not self._check_circuit_breaker():
            return None

        # 检查黑名单
        if self.is_symbol_blacklisted(symbol):
            blacklist_info = self.get_blacklist_info(symbol)
            logging.warning(
                f"跳过下单: {symbol} 在黑名单中, "
                f"原因: {blacklist_info.get('reason')} - {blacklist_info.get('description')}"
            )
            return {
                "success": False,
                "error": f"symbol_blacklisted:{blacklist_info.get('reason')}",
                "price": price,
                "quantity": quantity,
                "side": side,
            }

        # 格式化和验证订单参数
        original_price = price
        original_quantity = quantity

        if self.symbol_config:
            price = self.symbol_config.format_price(symbol, price)
            quantity = self.symbol_config.format_quantity(symbol, quantity)

            # 验证订单
            is_valid, error_msg = self.symbol_config.validate_order(symbol, price, quantity)
            if not is_valid:
                # 尝试自动调整数量（针对金额不足的情况）
                if "订单金额低于最小值" in error_msg:
                    min_order_value = self.symbol_config.get_min_order_value(symbol)
                    if min_order_value and price > 0:
                        adjusted_quantity = (min_order_value / price) * 1.2
                        quantity = self.symbol_config.format_quantity(symbol, adjusted_quantity)

                        is_valid_new, error_msg_new = self.symbol_config.validate_order(symbol, price, quantity)
                        if is_valid_new:
                            logging.debug(
                                f"逐笔订单数量自动调整: {original_quantity} → {quantity}"
                            )
                        else:
                            logging.warning(f"逐笔订单验证失败: {error_msg_new}")
                            return {
                                "success": False,
                                "error": error_msg_new,
                                "price": price,
                                "quantity": quantity,
                                "side": side,
                            }
                else:
                    logging.warning(f"逐笔订单验证失败: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg,
                        "price": price,
                        "quantity": quantity,
                        "side": side,
                    }

        # 生成带前缀的clientOrderId，用于订单类型识别
        base_id = self.create_temp_id()
        if order_purpose == "wash_trading":
            client_order_id = f"wash_{base_id}"
        elif order_purpose == "market_making":
            client_order_id = f"mm_{base_id}"
        elif order_purpose == "anti_pin":
            client_order_id = f"antipin_{base_id}"
        elif order_purpose == "hedging":
            client_order_id = f"hedge_{base_id}"
        else:
            client_order_id = base_id

        # 创建订单对象
        order = Order(
            symbol=symbol,
            side=side,
            type="LIMIT",
            price=price,
            quantity=quantity
        )
        order.clientOrderId = client_order_id

        # 发送订单到交易所
        try:
            response = self.client.order(
                symbol=order.symbol,
                side=order.side,
                type=order.type,
                biz_type=order.bizType,
                time_in_force=order.timeInForce,
                client_order_id=order.clientOrderId,
                price=order.price,
                quantity=order.quantity,
                quote_qty=order.quoteQty,
            )
            self._record_api_success()

            order_id = response.get("orderId", "") if response else ""

            # 记录订单到数据库
            if response and self.order_recorder:
                try:
                    record_data = {
                        "symbol": symbol,
                        "order_id": order_id,
                        "client_order_id": order.clientOrderId,
                        "side": side,
                        "order_type": "LIMIT",
                        "price": float(price),
                        "quantity": float(quantity),
                        "status": "NEW",
                        "strategy_name": self.strategy_name,
                        "order_purpose": order_purpose,
                        "net_value": float(self.netvalue) if self.netvalue else None,
                        "timestamp": datetime.now(timezone.utc),
                    }
                    self._schedule_async(self.order_recorder.record_order(record_data))
                except Exception as e:
                    logging.debug(f"记录逐笔订单失败: {e}")

            # 下单后延迟（模拟真实交易节奏）
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

            logging.debug(
                f"✅ 逐笔下单成功: {side} {quantity}@{price} | ID={order_id}"
            )

            return {
                "success": True,
                "order_id": order_id,
                "price": price,
                "quantity": quantity,
                "side": side,
                "response": response,
            }

        except Exception as e:
            self._record_api_failure()
            error_str = str(e)

            # 检查是否为永久性错误
            error_code = self._extract_error_code(error_str)
            if error_code and is_permanent_error(error_code):
                self._add_to_blacklist(symbol, error_code)

            logging.warning(f"❌ 逐笔下单失败: {side} {quantity}@{price} | 错误: {e}")

            return {
                "success": False,
                "error": error_str,
                "price": price,
                "quantity": quantity,
                "side": side,
            }

    def _extract_error_code(self, error_str: str) -> Optional[str]:
        """
        从错误信息中提取错误码

        Args:
            error_str: 错误信息字符串

        Returns:
            错误码字符串，如 'ORDER_008'，或 None
        """
        import re
        # 匹配类似 ORDER_008, BALANCE_001 等格式的错误码
        match = re.search(r'([A-Z]+_\d{3})', error_str)
        if match:
            return match.group(1)
        return None

    def place_orders_sequential(
        self,
        orders: List[Dict[str, Any]],
        delay_between_ms: int = 50,
        stop_on_failure: bool = False,
    ) -> Dict[str, Any]:
        """
        逐笔顺序下单方法 - 批量执行单笔订单

        依次执行多个单笔订单，每笔订单之间可配置延迟，
        适合需要精确控制执行节奏的洗盘交易场景。

        Args:
            orders: 订单列表，每个订单包含:
                - symbol: 交易对
                - side: 方向
                - price: 价格
                - quantity: 数量
                - order_purpose: 订单用途（可选，默认 'wash_trading'）
            delay_between_ms: 订单之间的延迟毫秒数，默认50ms
            stop_on_failure: 遇到失败是否停止，默认False继续执行

        Returns:
            Dict: 执行结果摘要
                - total: 总订单数
                - success_count: 成功数
                - failed_count: 失败数
                - results: 每个订单的详细结果列表

        Example:
            >>> orders = [
            ...     {"symbol": "TON3LUSDT", "side": "BUY", "price": 0.728, "quantity": 10},
            ...     {"symbol": "TON3LUSDT", "side": "SELL", "price": 0.728, "quantity": 10},
            ... ]
            >>> summary = order_manager.place_orders_sequential(orders, delay_between_ms=100)
            >>> print(f"成功: {summary['success_count']}/{summary['total']}")
        """
        results = []
        success_count = 0
        failed_count = 0

        logging.info(f"📤 开始逐笔下单: 共{len(orders)}笔, 间隔{delay_between_ms}ms")

        for i, order in enumerate(orders):
            symbol = order.get("symbol")
            side = order.get("side")
            price = order.get("price")
            quantity = order.get("quantity")
            order_purpose = order.get("order_purpose", "wash_trading")

            # 参数验证
            if not all([symbol, side, price, quantity]):
                logging.warning(f"订单[{i}]参数不完整，跳过")
                results.append({
                    "index": i,
                    "success": False,
                    "error": "incomplete_params",
                })
                failed_count += 1
                continue

            # 执行单笔下单
            result = self.place_single_order(
                symbol=symbol,
                side=side,
                price=price,
                quantity=quantity,
                order_purpose=order_purpose,
                delay_ms=delay_between_ms if i < len(orders) - 1 else 0,  # 最后一笔不延迟
            )

            if result is None:
                # 熔断器开启
                logging.warning(f"订单[{i}]熔断器开启，停止后续下单")
                results.append({
                    "index": i,
                    "success": False,
                    "error": "circuit_breaker_open",
                })
                failed_count += 1
                break

            result["index"] = i
            results.append(result)

            if result.get("success"):
                success_count += 1
            else:
                failed_count += 1
                if stop_on_failure:
                    logging.warning(f"订单[{i}]失败，停止后续下单")
                    break

        summary = {
            "total": len(orders),
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results,
        }

        logging.info(
            f"📊 逐笔下单完成: 成功={success_count}, 失败={failed_count}, 总计={len(orders)}"
        )

        return summary

    @handle_api_error
    def add_orders_batch(self, order_data, batch_id=None, order_purpose=None):
        if not self._check_circuit_breaker():
            return None
        
        # 下单前检查资金是否充足
        if len(order_data) > 0:
            symbol = order_data[0].get("symbol")
            can_place_order, balance_message = self.check_balance_before_order(symbol)
            
            if not can_place_order:
                logging.critical(
                    f"[{self.strategy_name}] 资金不足，取消下单！{balance_message}"
                )
                return None

        # ✅ 格式化和验证批量订单参数（如果Symbol配置管理器可用）
        if self.symbol_config:
            validated_orders = []
            for i, order in enumerate(order_data):
                symbol = order.get("symbol")
                price = order.get("price")
                quantity = order.get("quantity")

                if symbol and price is not None and quantity is not None:
                    original_price = price
                    original_quantity = quantity

                    # 格式化价格和数量
                    formatted_price = self.symbol_config.format_price(symbol, price)
                    formatted_quantity = self.symbol_config.format_quantity(symbol, quantity)

                    # 记录格式化结果
                    if abs(formatted_price - original_price) > 1e-10 or abs(formatted_quantity - original_quantity) > 1e-10:
                        logging.debug(
                            f"批量订单[{i}]格式化: "
                            f"价格 {original_price} → {formatted_price}, "
                            f"数量 {original_quantity} → {formatted_quantity}"
                        )

                    # 验证订单参数
                    is_valid, error_msg = self.symbol_config.validate_order(symbol, formatted_price, formatted_quantity)
                    if not is_valid:
                        # 检查是否是订单金额不足的问题
                        if "订单金额低于最小值" in error_msg:
                            # 获取最小订单金额
                            min_order_value = self.symbol_config.get_min_order_value(symbol)

                            if min_order_value:
                                # 计算满足最小金额所需的数量，增加20%余量确保格式化后仍满足要求
                                adjusted_quantity = (min_order_value / formatted_price) * 1.2

                                # 格式化调整后的数量
                                new_quantity = self.symbol_config.format_quantity(symbol, adjusted_quantity)

                                # 重新验证调整后的订单
                                is_valid_new, error_msg_new = self.symbol_config.validate_order(
                                    symbol, formatted_price, new_quantity
                                )

                                if is_valid_new:
                                    # 调整成功，更新订单数量
                                    order["price"] = formatted_price
                                    order["quantity"] = new_quantity
                                    logging.info(
                                        f"批量订单[{i}]数量自动调整: {original_quantity} → {new_quantity} "
                                        f"(订单金额: {formatted_price * original_quantity:.2f} → {formatted_price * new_quantity:.2f} USDT)"
                                    )
                                    validated_orders.append(order)
                                    continue
                                else:
                                    # 调整后仍不满足要求，跳过
                                    logging.warning(f"批量订单[{i}]调整后仍验证失败: {error_msg_new}")
                                    continue
                            else:
                                # 无法获取最小订单金额，跳过
                                logging.warning(f"批量订单[{i}]验证失败且无法调整: {error_msg}")
                                continue
                        else:
                            # 其他验证错误，直接跳过
                            logging.warning(f"批量订单[{i}]验证失败: {error_msg}")
                            logging.warning(f"跳过订单: {symbol}, 侧: {order.get('side')}, 价格: {formatted_price}, 数量: {formatted_quantity}")
                            continue

                    # 更新订单数据（仅在验证通过时）
                    order["price"] = formatted_price
                    order["quantity"] = formatted_quantity
                    validated_orders.append(order)

            # 如果所有订单都无效，返回None
            if not validated_orders:
                logging.error("批量订单中没有有效订单，取消下单")
                return None

            # 使用验证后的订单
            order_data = validated_orders
            logging.info(f"批量订单验证完成: {len(order_data)}/{len(order_data)} 有效")

        time.sleep(0.1)

        try:
            response = self.client.batch_order(order_data, batch_id=batch_id)
            self._record_api_success()
        except Exception as e:
            self._record_api_failure()
            raise

        # 处理批量订单响应
        if response and response.get("items"):
            # 检查被拒绝的订单
            for i, item in enumerate(response["items"]):
                if item.get("rejected"):
                    error_code = item.get("reason")
                    original_order = order_data[i]
                    symbol = original_order["symbol"]

                    # 检查是否为永久性错误
                    if is_permanent_error(error_code):
                        # 添加到黑名单
                        self._add_to_blacklist(symbol, error_code)

                        # 记录永久性错误
                        logging.error(
                            f"永久性错误: {error_code} - {get_error_description(error_code)}, "
                            f"交易对: {symbol}, "
                            f"侧: {original_order['side']}, "
                            f"价格: {original_order['price']}, "
                            f"数量: {original_order['quantity']}"
                        )
                    else:
                        # 临时性错误或未知错误，只记录警告
                        logging.warning(
                            f"订单被拒绝: {error_code} - {get_error_description(error_code)}, "
                            f"交易对: {symbol}, "
                            f"可能可以重试"
                        )

            # 记录成功的订单
            if self.order_recorder:
                try:
                    depth = self.depth if hasattr(self, "depth") else None

                    for i, item in enumerate(response["items"]):
                        if not item.get("rejected"):
                            original_order = order_data[i]

                            record_data = {
                                "symbol": original_order["symbol"],
                                "order_id": item.get("orderId", ""),
                                "client_order_id": original_order.get("clientOrderId", ""),
                                "side": original_order["side"],
                                "order_type": original_order.get("type", "LIMIT"),
                                "price": float(original_order["price"]),
                                "quantity": float(original_order["quantity"]),
                                "status": "NEW",
                                "strategy_name": self.strategy_name,
                                "order_purpose": original_order.get("order_purpose", order_purpose or "market_making"),
                                "net_value": float(self.netvalue)
                                if self.netvalue
                                else None,
                                "best_bid": float(depth["bids"][0][0])
                                if depth and depth.get("bids")
                                else None,
                                "best_ask": float(depth["asks"][0][0])
                                if depth and depth.get("asks")
                                else None,
                                "timestamp": datetime.now(timezone.utc),
                                "batch_id": response.get("batchId"),
                            }

                            # 使用线程安全的方式调度异步记录
                            self._schedule_async(
                                self.order_recorder.record_order(record_data)
                            )

                except Exception as e:
                    logging.error(f"记录批量订单失败: {e}")

        # {'batchId': '449413067009423616', 'items': [{'index': 0, 'clientOrderId': '16559590087220001', 'orderId': '449413067009423617', 'rejected': False, 'reason': None}]}

        # if response["batchId"] and not is_wash_trading:

        # for res_idx in range(len(response["items"])):
        #    self.sent_orders[response["items"][res_idx]["orderId"]] = {}
        #         # if not res["rejected"]:
        #         res = response["items"][res_idx]
        #         #logging.info(res)
        #         current_time = time.time()
        #         self.open_orders[res["orderId"]] = {
        #             "symbol":order_data[res_idx]["symbol"],
        #             "side": order_data[res_idx]["side"],
        #             "price": order_data[res_idx]["price"],
        #             "quantity": order_data[res_idx]["quantity"],
        #             "orderId": res["orderId"],
        #             "time": current_time,
        #             "UTC_PLUS_8": datetime.fromtimestamp(current_time, tz=timezone.utc).astimezone(timezone(timedelta(hours=8)))
        #         }

        # else:
        logging.info(response)
        return response

    # def sort_orders(self):
    #     for symbol in self.open_orders.keys():
    #         for side in self.open_orders[symbol].keys():
    #             self.open_orders[symbol][side].sort(key=lambda x: x["price"], reverse=(side == "SELL"))
    #     for symbol in self.failed_orders.keys():
    #         for side in self.failed_orders[symbol].keys():
    #             self.failed_orders[symbol][side].sort(key=lambda x: x["price"], reverse=(side == "SELL"))
    @handle_api_error 
    def reset_open_orders(self, symbol):
        if not self._check_circuit_breaker():
            return
            
        try:
            current_orders = self.client.get_open_orders(symbol=symbol)
            self._record_api_success()
        except Exception as e:
            self._record_api_failure()
            raise
        # logging.info(f"get len(current_orders) open orders!")
        self.open_orders = {}

        current_time = time.time()
        for res in current_orders:
            # logging.info(res)
            if res["state"] == "NEW":
                self.open_orders[res["orderId"]] = {
                    "symbol": res["symbol"],
                    "side": res["side"],
                    "price": res["price"],
                    "quantity": res["origQty"],
                    "orderId": res["orderId"],
                    "time": current_time,
                    "UTC_PLUS_8": datetime.fromtimestamp(
                        current_time, tz=timezone.utc
                    ).astimezone(timezone(timedelta(hours=8))),
                }
            elif res["state"] == "PARTIALLY_FILLED":
                self.open_orders[res["orderId"]] = {
                    "symbol": res["symbol"],
                    "side": res["side"],
                    "price": res["price"],
                    "quantity": res["origQty"],
                    "orderId": res["orderId"],
                    "time": current_time,
                    "UTC_PLUS_8": datetime.fromtimestamp(
                        current_time, tz=timezone.utc
                    ).astimezone(timezone(timedelta(hours=8))),
                }
        # logging.info(f"get {len(current_orders)} open orders! now {len(self.open_orders)} open orders")

    def cancel_order(self, order):
        response = self.client.cancel_order(order["orderId"])
        """
        current_time = time.time()
        if response is None:
            self.canceled_orders.append({
                    "symbol":order["symbol"],
                    "side": order["side"],
                    "price": order["price"],
                    "quantity": order["origQty"],
                    "orderId": order["orderId"],
                    "time": current_time,
                    "UTC_PLUS_8": datetime.fromtimestamp(current_time, tz=timezone.utc).astimezone(timezone(timedelta(hours=8))),
                    "state": "CANCELED",
                })
        """
        return response

    def cancel_orders_batch(self, orders):
        """批量取消订单"""
        time.sleep(0.1)

        response = self.client.cancel_orders([order["orderId"] for order in orders])
        # logging.info(response)
        # logging.info(f" canceled orders: {orders}")
        """
        current_time = time.time()
        if response is None:
            for order in orders:

                self.canceled_orders.append({
                    "symbol":order["symbol"],
                    "side": order["side"],
                    "price": order["price"],
                    "quantity": order["origQty"],
                    "orderId": order["orderId"],
                    "time": current_time,
                    "UTC_PLUS_8": datetime.fromtimestamp(current_time, tz=timezone.utc).astimezone(timezone(timedelta(hours=8))),
                    "state": "CANCELED",
                })
        """
        return response

    def cancel_orders_bytier(self, symbol=None, tier_limit=None):
        # self.open_orders =
        # 检查是否有该交易对的订单
        if symbol not in self.open_orders or not self.open_orders[symbol]:
            logging.info(f"没有找到 {symbol} 的挂单，跳过按档位取消")
            return None

        # 检查是否有足够的订单档位
        if "SELL" not in self.open_orders[symbol] or "BUY" not in self.open_orders[symbol]:
            logging.warning(f"{symbol} 的订单结构不完整，跳过按档位取消")
            return None

        # 计算实际可取消的档位数量（不超过现有订单数）
        max_tiers = min(
            len(self.open_orders[symbol].get("SELL", [])),
            len(self.open_orders[symbol].get("BUY", [])),
            tier_limit
        )

        if max_tiers == 0:
            logging.info(f"{symbol} 没有足够的订单进行分档取消")
            return None

        order_ids = []
        for i in range(max_tiers):
            try:
                order_ids.append(self.open_orders[symbol]["SELL"][i]["orderId"])
                order_ids.append(self.open_orders[symbol]["BUY"][i]["orderId"])
            except (IndexError, KeyError) as e:
                logging.warning(f"访问订单索引 {i} 时出错: {e}")
                break

        if not order_ids:
            logging.info(f"{symbol} 没有可取消的订单")
            return None

        response = self.cancel_orders_batch(order_ids=order_ids)
        return response

    @handle_api_error
    def cancel_all_open_orders(
        self,
        symbol=None,
        biz_type="SPOT",
        side=None,
        cancellation_reason: str = "manual",
        metadata: Optional[Dict] = None
    ):
        """撤销所有订单并记录原因
        
        Args:
            symbol: 交易对
            biz_type: 业务类型
            side: 方向（可选）
            cancellation_reason: 撤销原因
                - "stop_loss_fixed": 固定止损触发
                - "stop_loss_trailing": 移动止损触发
                - "stop_loss_time": 时间止损触发
                - "risk_level_1": 风险等级1（极高风险）
                - "risk_level_2": 风险等级2（中等风险）
                - "manual": 手动撤销
                - "strategy_adjustment": 策略调整
            metadata: 额外元数据（止损参数、风险评分等）
        """
        if not self._check_circuit_breaker():
            return None
            
        # 🆕 第一阶段：记录 PENDING_CANCEL 状态
        order_ids = list(self.open_orders.keys())
        
        if self.order_recorder and len(order_ids) > 0:
            try:
                self._schedule_async(
                    self.order_recorder.record_order_cancellation(
                        order_ids=order_ids,
                        symbol=symbol,
                        cancellation_reason=cancellation_reason,
                        metadata=metadata
                    )
                )
                logging.info(
                    f"📝 记录撤单请求: {len(order_ids)} 个订单 → PENDING_CANCEL, "
                    f"原因: {cancellation_reason}"
                )
            except Exception as e:
                logging.error(f"记录PENDING_CANCEL状态失败: {e}")
            
        # 🆕 第二阶段：向交易所发送撤单请求
        try:
            response = self.client.cancel_open_orders(
                symbol=symbol, biz_type=biz_type, side=side
            )
            self._record_api_success()
            
            # 🆕 第三阶段：撤单成功 → 确认 CANCELED 状态
            if response and self.order_recorder and len(order_ids) > 0:
                try:
                    self._schedule_async(
                        self.order_recorder.confirm_order_cancellation(
                            order_ids=order_ids,
                            success=True
                        )
                    )
                    logging.info(f"✅ 撤单成功: {len(order_ids)} 个订单 → CANCELED")
                except Exception as e:
                    logging.error(f"确认CANCELED状态失败: {e}")
            
            if response:
                self.open_orders = {}
            return response
            
        except Exception as e:
            self._record_api_failure()
            
            # 🆕 撤单失败 → 确认 CANCEL_REJECTED 状态
            if self.order_recorder and len(order_ids) > 0:
                try:
                    self._schedule_async(
                        self.order_recorder.confirm_order_cancellation(
                            order_ids=order_ids,
                            success=False
                        )
                    )
                    logging.warning(f"❌ 撤单失败: {len(order_ids)} 个订单 → CANCEL_REJECTED")
                except Exception as update_err:
                    logging.error(f"确认CANCEL_REJECTED状态失败: {update_err}")
            
            raise

    async def get_real_volume_ratio(self, symbol: str) -> float:
        """获取真实交易量占比"""
        if self.order_recorder:
            return await self.order_recorder.get_real_volume_ratio(symbol)
        return 0.0

    async def get_order_stats(self, symbol: str) -> Dict[str, Any]:
        """获取订单统计信息"""
        if self.order_recorder:
            return await self.order_recorder.get_order_stats(symbol)
        return {}

    def record_trade(self, trade_data: Dict[str, Any], trade_purpose: str = "market_making"):
        """记录成交数据到数据库"""
        if self.order_recorder:
            trade_data["strategy_name"] = self.strategy_name
            trade_data["trade_purpose"] = trade_purpose
            # 使用线程安全的方式调度异步记录
            self._schedule_async(self.order_recorder.record_trade(trade_data))

    def get_recent_fills_count(self, window_seconds: int = 60) -> int:
        """
        获取最近N秒内的成交笔数（用于洗盘交易智能调整）
        
        Args:
            window_seconds: 统计窗口（秒），默认60秒
            
        Returns:
            int: 成交笔数
        """
        import time
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # 清理过期记录
        self.recent_fills = [
            (ts, vol, price) for ts, vol, price in self.recent_fills 
            if ts > cutoff_time
        ]
        
        return len(self.recent_fills)
    
    def get_recent_fills_volume(self, window_seconds: int = 60) -> float:
        """
        获取最近N秒内的总成交量
        
        Args:
            window_seconds: 统计窗口（秒），默认60秒
            
        Returns:
            float: 总成交量
        """
        import time
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        total_volume = sum(
            vol for ts, vol, price in self.recent_fills 
            if ts > cutoff_time
        )
        
        return total_volume
    
    def record_fill(self, volume: float, price: float):
        """
        记录一笔成交（供洗盘交易使用）
        
        Args:
            volume: 成交量
            price: 成交价格
        """
        import time
        self.recent_fills.append((time.time(), volume, price))
        
        # 限制列表长度，防止内存无限增长
        # 保留最近100条记录（通常60秒内不会超过这个数量）
        if len(self.recent_fills) > 100:
            self.recent_fills = self.recent_fills[-100:]
    def get_balance(self, symbol):
        balance = self.client.balances([symbol])

        return balance

    def get_position3(self, symbol, currencies):
        """
        获取持仓信息（已改为使用市场价格，不再依赖订单簿）
        
        Returns:
            tuple: (delta_position, position, price, delta_amount)
        """
        # 使用市场价格替代中间价
        try:
            # ✅ 修复：使用正确的 XT API 方法
            ticker_data = self.client.get_tickers_24h(symbol=symbol)
            if ticker_data and len(ticker_data) > 0:
                # ticker_data 返回列表，取第一个元素的 'c' 字段（close price）
                mid_price = float(ticker_data[0]["c"])
            else:
                raise ValueError("未获取到有效的ticker数据")
        except Exception as e:
            logging.warning(f"获取市场价格失败: {e}，使用上次价格")
            mid_price = getattr(self, '_last_mid_price', 0)
        
        # 缓存价格
        self._last_mid_price = mid_price
        
        info = self.client.balances(currencies)
        for currency in info["assets"]:
            if currency["currency"] == symbol.split("_")[0].lower():
                delta_amount = (
                    float(currency["totalAmount"]) - self.last_amount
                )  # if < 0, user buy, > 0, user sell
                position_amount = float(currency["totalAmount"]) - self.init_amount
                delta_position = delta_amount * mid_price
                self.last_amount = float(currency["totalAmount"])
                self.position = position_amount * mid_price

        return delta_position, self.position, mid_price, delta_amount

    def get_position2(self, symbol):
        """
        get positions from history orders and write history orders
        """
        max_batch_size = 100
        chunked_get_orders = []

        sent_orders_ids = list(self.sent_orders.keys())
        filtered_sent_orders_ids = [x for x in sent_orders_ids if x is not None]
        for t in range(0, len(self.sent_orders), max_batch_size):
            chunked_get_orders.append([
                order_id
                for order_id in filtered_sent_orders_ids[t : t + max_batch_size]
            ])

        if len(self.sent_orders) == 0:
            return 0

        # usdt reduce
        # _ + btc5l
        # t1 * delta btc5l =

        #
        delta_position = 0
        cmu_deltaQty = 0

        for chunk in chunked_get_orders:
            if len(chunk) == 0:
                continue
            try:
                response = self.client.get_batch_orders(chunk)
            except Exception as e:
                logging.info(e)
                continue
            """
            {'symbol': 'btc5l_usdt', 'orderId': '450207381092125065', 'clientOrderId': '894875718937174804',
            'baseCurrency': 'btc5l', 'quoteCurrency': 'usdt', 'side': 'SELL', 'type': 'LIMIT',
            'timeInForce': 'GTC', 'price': '20.5877', 'origQty': '181.0000', 'origQuoteQty': '3726.3737',
            'executedQty': '0.0000', 'leavingQty': '181.0000', 'tradeBase': '0.0000', 'tradeQuote': '0.0000',
            'avgPrice': None, 'fee': None, 'feeCurrency': None, 'nftId': None, 'symbolType': 'normal',
            'deductServices': [], 'origRestFee': None, 'origFeeCurrency': None, 'platFormCurrencyFee': None,
            'platFormCurrency': None, 'couponAmount': None, 'couponCurrency': None, 'couponDeductFee': None,
            'closed': False, 'state': 'NEW', 'time': 1737039804101, 'updatedTime': None, 'ip': '54.151.166.240'}
            """
            if response:
                for res in response:
                    if res["state"] == "CANCELED":
                        current_time = time.time()

                        # ✅ 使用OrderStateManager统一处理订单取消
                        # 替换原有的直接操作：self.canceled_orders.append(...)
                        canceled_order_data = {
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "price": res["price"],
                            "quantity": res["origQty"],
                            "orderId": res["orderId"],
                            "time": current_time,
                            "UTC_PLUS_8": datetime.fromtimestamp(
                                current_time, tz=timezone.utc
                            ).astimezone(timezone(timedelta(hours=8))),
                            "state": res["state"],
                        }

                        self.state_manager.update_order_state(
                            order_id=res["orderId"],
                            new_state='CANCELED',
                            order_data=canceled_order_data,
                            trigger_source='rest_api'
                        )

                        del self.sent_orders[res["orderId"]]

                    elif res["state"] == "PARTIALLY_FILLED":
                        updatedTime = int(res["updatedTime"]) / 1000
                        logging.info(
                            datetime.fromtimestamp(
                                updatedTime, tz=timezone.utc
                            ).astimezone(timezone(timedelta(hours=8)))
                        )
                        logging.info(f"PARTIALLY_FILLED: {res}")

                        if res["orderId"] in self.partially_filled_orders:
                            last_leavingQty = self.partially_filled_orders[
                                res["orderId"]
                            ]["leavingQty"]
                            deltaQty = abs(
                                float(res["leavingQty"]) - float(last_leavingQty)
                            )
                            logging.info("in partially_filled_orders")
                        else:
                            logging.info("not in partially_filled_orders")
                            deltaQty = float(res["executedQty"])
                        logging.info(
                            f"deltaQty {deltaQty}, * price {res['price']}, delta position {deltaQty * float(res['price'])}"
                        )
                        deltaQty = -1 * deltaQty if res["side"] == "SELL" else deltaQty
                        delta_position += deltaQty * float(res["price"])
                        cmu_deltaQty += deltaQty

                        self.partially_filled_orders[res["orderId"]] = {
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "orderId": res["orderId"],
                            "origQty": res["origQty"],
                            "executedQty": res["executedQty"],
                            "leavingQty": res["leavingQty"],
                        }
                        self.trading_history.append({
                            "orderId": res["orderId"],
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "price": res["price"],
                            "deltaQty": deltaQty,
                        })

                    elif res["state"] == "FILLED":
                        updatedTime = int(res["updatedTime"]) / 1000
                        logging.info(
                            datetime.fromtimestamp(
                                updatedTime, tz=timezone.utc
                            ).astimezone(timezone(timedelta(hours=8)))
                        )
                        logging.info(f"FILLED {res}")
                        if res["orderId"] in self.partially_filled_orders:
                            last_leavingQty = self.partially_filled_orders[
                                res["orderId"]
                            ]["leavingQty"]
                            deltaQty = abs(
                                float(res["leavingQty"]) - float(last_leavingQty)
                            )
                            logging.info("in partially_filled_orders")
                            del self.partially_filled_orders[res["orderId"]]
                        else:
                            logging.info("not in partially_filled_orders")
                            deltaQty = float(res["executedQty"])
                        logging.info(
                            f"deltaQty {deltaQty}, * price {res['price']}, delta position {deltaQty * float(res['price'])}"
                        )
                        deltaQty = -1 * deltaQty if res["side"] == "SELL" else deltaQty
                        delta_position += deltaQty * float(res["price"])
                        cmu_deltaQty += deltaQty

                        # ✅ 记录成交（用于洗盘交易智能调整）
                        self.record_fill(abs(deltaQty), float(res["price"]))

                        current_time = time.time()
                        filled_order_data = {
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "price": res["price"],
                            "quantity": res["origQty"],
                            "orderId": res["orderId"],
                            "time": current_time,
                            "UTC_PLUS_8": datetime.fromtimestamp(
                                current_time, tz=timezone.utc
                            ).astimezone(timezone(timedelta(hours=8))),
                            "state": res["state"],
                        }

                        # ✅ 使用OrderStateManager统一处理订单成交
                        # 替换原有的直接操作：self.filled_orders.append(...)
                        self.state_manager.update_order_state(
                            order_id=res["orderId"],
                            new_state='FILLED',
                            order_data=filled_order_data,
                            trigger_source='rest_api'
                        )

                        # 记录成交到数据库
                        trade_data = {
                            "symbol": res["symbol"],
                            "trade_id": f"{res['orderId']}_fill",  # 使用orderId生成唯一trade_id
                            "order_id": res["orderId"],
                            "price": res["price"],
                            "quantity": abs(deltaQty),  # 取绝对值
                            "quote_quantity": float(res["price"]) * abs(deltaQty),
                            "is_buyer": res["side"] == "BUY",
                            "traded_at": datetime.fromtimestamp(current_time, tz=timezone.utc),
                            "strategy_name": self.strategy_name if hasattr(self, 'strategy_name') else None,
                        }
                        # 从订单信息中提取交易用途
                        trade_purpose = res.get("order_purpose", "market_making")
                        self.record_trade(trade_data, trade_purpose=trade_purpose)

                        self.trading_history.append({
                            "orderId": res["orderId"],
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "price": res["price"],
                            "deltaQty": deltaQty,
                        })

                        del self.sent_orders[res["orderId"]]

        depth = self.get_depth_data(symbol)
        mid_price = get_mid_price(depth)

        self.amount = self.last_amount + cmu_deltaQty
        self.last_amount = self.amount

        self.position = self.amount * mid_price
        delta_position += (
            self.exposure["amount"] * mid_price
        )  # exposure only affect the delta_position
        logging.info(
            f"cmu_deltaQty {cmu_deltaQty}, remain amount {self.amount} (exposure: {self.exposure['amount']}), price {mid_price}, delta position {delta_position}, remain position {self.position}"
        )

        return delta_position, self.position, mid_price, self.amount

    def get_position(self, symbol):
        """获取当前持仓信息
        
        优先使用WebSocket缓存的订单数据，降级到REST API轮询。
        
        数据源优先级：
        1. WebSocket实时订单缓存（如果已启用且连接正常）
        2. REST API轮询（reset_open_orders + get_batch_orders）
        
        Args:
            symbol: 交易对符号
            
        Returns:
            tuple: (delta_position, position, mid_price, amount)
        """

        
        # ✅ 优先使用WebSocket缓存，避免REST API调用
        if self.use_order_websocket and self.order_ws_client:
            # 检查WebSocket连接状态
            ws_stats = self.order_ws_client.get_stats()
            if ws_stats.get('connected', False):
                logging.debug("使用WebSocket订单缓存（跳过reset_open_orders）")
                # WebSocket已经实时更新了self.open_orders，无需再次查询
            else:
                logging.warning("WebSocket未连接，降级到REST API轮询")
                self.reset_open_orders(symbol)
        else:
            # WebSocket未启用，使用传统REST API轮询
            self.reset_open_orders(symbol)

        order_ids = [str(order_id) for order_id in self.open_orders]
        logging.debug(f"当前内存中有 {len(order_ids)} 个订单")

        # remove canceled orders
        order_ids = [
            order_id for order_id in order_ids if order_id not in self.canceled_orders
        ]
        # logging.info()
        if len(order_ids) == 0:
            return 0

        max_batch_size = 100
        chunked_get_orders = []
        delta_position = 0
        cmu_deltaQty = 0

        for t in range(0, len(order_ids), max_batch_size):
            chunked_get_orders.append([
                order_id for order_id in order_ids[t : t + max_batch_size]
            ])

        for chunk in chunked_get_orders:
            response = self.client.get_batch_orders(chunk)
            """
            {'symbol': 'btc5l_usdt', 'orderId': '450207381092125065', 'clientOrderId': '894875718937174804', 'baseCurrency': 'btc5l', 'quoteCurrency': 'usdt', 'side': 'SELL', 'type': 'LIMIT', 'timeInForce': 'GTC', 'price': '20.5877', 'origQty': '181.0000', 'origQuoteQty': '3726.3737', 'executedQty': '0.0000', 'leavingQty': '181.0000', 'tradeBase': '0.0000', 'tradeQuote': '0.0000', 'avgPrice': None, 'fee': None, 'feeCurrency': None, 'nftId': None, 'symbolType': 'normal', 'deductServices': [], 'origRestFee': None, 'origFeeCurrency': None, 'platFormCurrencyFee': None, 'platFormCurrency': None, 'couponAmount': None, 'couponCurrency': None, 'couponDeductFee': None, 'closed': False, 'state': 'NEW', 'time': 1737039804101, 'updatedTime': None, 'ip': '54.151.166.240'}
            """
            if response:
                for res in response:
                    if res["state"] == "PARTIALLY_FILLED":
                        logging.info(f"PARTIALLY_FILLED: {res}")

                        if res["orderId"] in self.partially_filled_orders:
                            last_leavingQty = self.partially_filled_orders[
                                res["orderId"]
                            ]["leavingQty"]
                            deltaQty = abs(
                                float(res["leavingQty"]) - float(last_leavingQty)
                            )
                            logging.info("in partially_filled_orders")
                        else:
                            logging.info("not in partially_filled_orders")
                            deltaQty = float(res["executedQty"])
                        logging.info(
                            f"deltaQty {deltaQty}, * price {res['price']}, delta position {deltaQty * float(res['price'])}"
                        )
                        deltaQty = -1 * deltaQty if res["side"] == "SELL" else deltaQty
                        delta_position += deltaQty * float(res["price"])
                        cmu_deltaQty += deltaQty

                        self.partially_filled_orders[res["orderId"]] = {
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "orderId": res["orderId"],
                            "origQty": res["origQty"],
                            "executedQty": res["executedQty"],
                            "leavingQty": res["leavingQty"],
                        }
                        self.trading_history.append({
                            "orderId": res["orderId"],
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "price": res["price"],
                            "deltaQty": deltaQty,
                        })

                    elif res["state"] == "FILLED":
                        if res["orderId"] in self.filled_orders:
                            continue

                        logging.info(f"FILLED {res}")
                        if res["orderId"] in self.partially_filled_orders:
                            last_leavingQty = self.partially_filled_orders[
                                res["orderId"]
                            ]["leavingQty"]
                            deltaQty = abs(
                                float(res["leavingQty"]) - float(last_leavingQty)
                            )
                            logging.info("in partially_filled_orders")
                            del self.partially_filled_orders[res["orderId"]]
                        else:
                            logging.info("not in partially_filled_orders")
                            deltaQty = float(res["executedQty"])
                        logging.info(
                            f"deltaQty {deltaQty}, * price {res['price']}, delta position {deltaQty * float(res['price'])}"
                        )
                        deltaQty = -1 * deltaQty if res["side"] == "SELL" else deltaQty
                        delta_position += deltaQty * float(res["price"])
                        cmu_deltaQty += deltaQty

                        # ✅ 记录成交（用于洗盘交易智能调整）
                        self.record_fill(abs(deltaQty), float(res["price"]))

                        self.trading_history.append({
                            "orderId": res["orderId"],
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "price": res["price"],
                            "deltaQty": deltaQty,
                        })

                        # 记录成交到数据库
                        current_time = time.time()
                        trade_data = {
                            "symbol": res["symbol"],
                            "trade_id": f"{res['orderId']}_fill",  # 使用orderId生成唯一trade_id
                            "order_id": res["orderId"],
                            "price": res["price"],
                            "quantity": abs(deltaQty),  # 取绝对值
                            "quote_quantity": float(res["price"]) * abs(deltaQty),
                            "is_buyer": res["side"] == "BUY",
                            "traded_at": datetime.fromtimestamp(current_time, tz=timezone.utc),
                            "strategy_name": self.strategy_name if hasattr(self, 'strategy_name') else None,
                        }
                        # 从订单信息中提取交易用途
                        trade_purpose = res.get("order_purpose", "market_making")
                        self.record_trade(trade_data, trade_purpose=trade_purpose)

                        # ✅ 使用OrderStateManager统一处理订单状态变更
                        # 替换原有的直接操作：
                        #   self.filled_orders.append(res["orderId"])
                        #   self.remove_order(res["orderId"])
                        self.state_manager.update_order_state(
                            order_id=res["orderId"],
                            new_state='FILLED',
                            order_data=res,
                            trigger_source='rest_api'
                        )

                        # if res["orderId"] in pre_order_ids:
                        #     self.filled_orders.append(res["orderId"])

        depth = self.get_depth_data(res["symbol"])
        mid_price = get_mid_price(depth)

        self.amount = self.last_amount + cmu_deltaQty
        self.last_amount = self.amount

        self.position = self.amount * mid_price
        delta_position += (
            self.exposure["amount"] * mid_price
        )  # exposure only affect the delta_position
        logging.info(
            f"cmu_deltaQty {cmu_deltaQty}, remain amount {self.amount} (exposure: {self.exposure['amount']}), price {mid_price}, delta position {delta_position}, remain position {self.position}"
        )

        return delta_position, self.position, mid_price, self.amount

    def risk_actions(self, risk_level, symbol=None):
        """
        风险等级响应策略：
        Level 1: 极高风险 - 立即停止交易，取消所有订单
        Level 2: 中等风险 - 允许继续交易，但如果有订单则分档减少（渐进式风控）
        Level 3: 正常 - 正常交易

        修改记录 (2025-01-24):
        - Level 2 现在允许继续交易（返回 True）
        - Level 2 仅在有订单时执行分档撤单（启动时跳过）
        - 修复了启动阶段 Level 2 无法启动的问题
        """
        logging.info(f"🔍 risk_actions 被调用: risk_level={risk_level}, symbol={symbol}")
        
        if risk_level == 1:
            # 极高风险：立即停止所有交易
            logging.warning(f"⚠️ risk_level=1 极高风险，停止交易")
            self.cancel_all_open_orders(symbol=symbol)
            return False

        elif risk_level == 2:
            # 中等风险：允许继续交易，但如果有订单则分档减少风险敞口
            if symbol in self.open_orders and self.open_orders[symbol]:
                logging.info(f"风险等级 {risk_level}: 执行分档撤单以减少风险敞口")
                self.cancel_orders_bytier(symbol=symbol, tier_limit=int(self.tier / 5))
                time.sleep(3)
                self.cancel_orders_bytier(symbol=symbol, tier_limit=int(self.tier / 3))
                time.sleep(2)
                self.cancel_orders_bytier(symbol=symbol, tier_limit=int(self.tier / 2))
                time.sleep(1)
                self.cancel_orders_bytier(symbol=symbol, tier_limit=int(self.tier * 2 / 3))
            else:
                logging.info(f"风险等级 {risk_level}: 无订单，跳过分档撤单，允许继续交易")
            logging.info(f"✅ risk_level=2 返回 True，允许交易")
            return True  # ✅ 允许继续交易

        elif risk_level == 3:
            # 正常风险：正常交易
            logging.info(f"✅ risk_level=3 正常风险，返回 True")
            return True
        else:
            # 未知风险等级，默认允许交易但记录警告
            logging.warning(f"⚠️ 未知风险等级 {risk_level}，默认允许交易")
            return True

    def cleanup(self):
        """清理资源
        
        在程序退出或OrderManager销毁时调用，用于：
        1. 停止WebSocket订单监听器
        2. 关闭后台事件循环线程
        3. 释放其他资源
        
        应该在程序退出时显式调用此方法，确保资源正确释放。
        
        示例：
            order_manager = OrderManager(...)
            try:
                # 正常运行
                pass
            finally:
                order_manager.cleanup()
        """
        logging.info("开始清理OrderManager资源...")
        
        # 停止WebSocket订单监听器
        if self.order_ws_client:
            try:
                self.order_ws_client.stop()
                logging.info("订单WebSocket已停止")
            except Exception as e:
                logging.error(f"停止订单WebSocket失败: {e}")
        
        # 关闭订单记录器的后台事件循环
        if hasattr(self, '_recorder_running') and self._recorder_running:
            try:
                self.shutdown_recorder()
                logging.info("订单记录器后台线程已停止")
            except Exception as e:
                logging.error(f"停止订单记录器失败: {e}")
        
        logging.info("OrderManager资源清理完成")
