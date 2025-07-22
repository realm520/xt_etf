import time
import random
import logging
import pandas as pd
import os
from datetime import datetime, timezone, timedelta
from copy import deepcopy
import asyncio
from typing import Optional, Dict, Any, List
from functools import wraps
from etf.alert import send_alert, AlertLevel
from etf.utils.common import get_mid_price

# 导入订单记录器
try:
    from etf.storage import get_order_recorder

    ORDER_RECORDER_AVAILABLE = True
except ImportError:
    ORDER_RECORDER_AVAILABLE = False
    logging.warning("订单记录器未安装，将只使用CSV记录")


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
            
            # 记录API错误
            logging.error(f"API错误 {func.__name__}: {error_type} - {error_msg}")
            
            # 发送告警（如果strategy_name存在）
            if hasattr(self, 'strategy_name'):
                asyncio.create_task(send_alert(
                    "api_error",
                    {
                        "error_type": error_type,
                        "error_message": error_msg,
                        "function": func.__name__,
                        "operation": "order_management"
                    },
                    strategy_name=self.strategy_name
                ))
            
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
    def __init__(self, spot, strategy_name: str = "unknown"):
        self.counter = 0
        self.client = spot
        self.strategy_name = strategy_name  # 添加策略名称
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
        self.open_orders_csv_file = "xt_open_orders.csv"
        self.trading_history_csv_file = "xt_trading_history.csv"
        self.history_orders_csv_file = "xt_history_orders.csv"

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

        # 初始化订单记录器
        if ORDER_RECORDER_AVAILABLE:
            self.order_recorder = get_order_recorder()
            self._recorder_loop = None
        else:
            self.order_recorder = None
        
        # 添加错误统计和健康检查
        self.api_error_count = 0
        self.last_successful_operation = time.time()
        self.consecutive_failures = 0
        self.circuit_breaker_open = False
        self.circuit_breaker_reset_time = None
    
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

    @handle_api_error
    def get_depth_data(self, symbol):
        if not self._check_circuit_breaker():
            return None
            
        try:
            depth = self.client.get_depth(symbol)
            logging.debug(f"depth {depth}")
            self.depth = depth
            self._record_api_success()
            return depth
        except Exception as e:
            self._record_api_failure()
            raise

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
        is_wash_trading=False,
    ):
        if not self._check_circuit_breaker():
            return None
            
        order = Order(
            symbol=symbol, side=side, type=type, price=price, quantity=quantity
        )
        
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
            # API错误处理装饰器会处理告警发送
            logging.error(f"下单失败: {e}")
            raise

        # 记录订单到数据库
        if response and self.order_recorder:
            try:
                # 获取当前市场深度
                depth = self.depth if hasattr(self, "depth") else None

                order_data = {
                    "symbol": order.symbol,
                    "order_id": response.get("orderId", ""),
                    "client_order_id": order.clientOrderId,
                    "side": order.side,
                    "order_type": order.type,
                    "price": float(order.price),
                    "quantity": float(order.quantity),
                    "status": "NEW",
                    "strategy_name": self.strategy_name,
                    "is_wash_trading": is_wash_trading,
                    "net_value": float(self.netvalue) if self.netvalue else None,
                    "best_bid": float(depth["bids"][0][0])
                    if depth and depth.get("bids")
                    else None,
                    "best_ask": float(depth["asks"][0][0])
                    if depth and depth.get("asks")
                    else None,
                    "timestamp": datetime.now(timezone.utc),
                }

                # 异步记录订单
                asyncio.create_task(self.order_recorder.record_order(order_data))

            except Exception as e:
                logging.error(f"记录订单失败: {e}")

        return response

    @handle_api_error
    def add_orders_batch(self, order_data, batch_id=None, is_wash_trading=False):
        if not self._check_circuit_breaker():
            return None
            
        time.sleep(0.1)

        try:
            response = self.client.batch_order(order_data, batch_id=batch_id)
            self._record_api_success()
        except Exception as e:
            self._record_api_failure()
            raise

        # 记录批量订单
        if response and response.get("items") and self.order_recorder:
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
                            "is_wash_trading": is_wash_trading,
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

                        # 异步记录订单
                        asyncio.create_task(
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
        """
        cancel open orders only from csv files, should remove these orders from csv files
        """
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
        order_ids = []
        for i in range(tier_limit):
            order_ids.append(self.open_orders[symbol]["SELL"][i]["orderId"])
            order_ids.append(self.open_orders[symbol]["BUY"][i]["orderId"])

        response = self.cancel_orders_batch(order_ids=order_ids)
        return response

    @handle_api_error
    def cancel_all_open_orders(self, symbol=None, biz_type="SPOT", side=None):
        if not self._check_circuit_breaker():
            return None
            
        try:
            response = self.client.cancel_open_orders(
                symbol=symbol, biz_type=biz_type, side=side
            )
            self._record_api_success()
            if response:
                self.open_orders = {}
            return response
        except Exception as e:
            self._record_api_failure()
            raise

    def write_orders2(self):
        """
        write open orders
        """
        new_data = [order for order in self.open_orders.values()]
        df = pd.DataFrame(new_data)
        logging.info(f"writing {len(df)} open orders in to csv file")
        # logging.info(f"new open orders length: {len(new_data) - len(local_data)}")
        # logging.info(f"local open orders length: {len(local_data)}")

        df.to_csv(self.open_orders_csv_file, mode="w", index=False, header=True)

        # reset all datas
        self.open_orders = {}
        self.filled_orders = []

    def write_history_orders(self):
        """
        write history orders to local csv file,
        1. filled orders
        2. canceled orders
        """

        # 1. filled orders
        # max_batch_size = 100
        # chunked_get_orders = []
        # filled_orders = []

        # sent_orders_ids = self.sent_orders.keys()
        # for t in range(0, len(self.sent_orders), max_batch_size):
        #     chunked_get_orders.append([order_id for order_id in sent_orders_ids[t: t + max_batch_size]])

        # for chunk in chunked_get_orders:
        #     response = self.client.get_batch_orders(chunk)

        # if response:
        #     for res in response:
        #         if res["state"] == 'FILLED':
        #             '''
        #             {'symbol': 'btc5l_usdt', 'orderId': '450207381092125065', 'clientOrderId': '894875718937174804',
        #             'baseCurrency': 'btc5l', 'quoteCurrency': 'usdt', 'side': 'SELL', 'type': 'LIMIT',
        #             'timeInForce': 'GTC', 'price': '20.5877', 'origQty': '181.0000', 'origQuoteQty': '3726.3737',
        #             'executedQty': '0.0000', 'leavingQty': '181.0000', 'tradeBase': '0.0000', 'tradeQuote': '0.0000',
        #             'avgPrice': None, 'fee': None, 'feeCurrency': None, 'nftId': None, 'symbolType': 'normal',
        #             'deductServices': [], 'origRestFee': None, 'origFeeCurrency': None, 'platFormCurrencyFee': None,
        #             'platFormCurrency': None, 'couponAmount': None, 'couponCurrency': None, 'couponDeductFee': None,
        #             'closed': False, 'state': 'NEW', 'time': 1737039804101, 'updatedTime': None, 'ip': '54.151.166.240'}
        #             '''
        #             current_time = time.time()
        #             filled_orders.append({
        #                 "symbol":res["symbol"],
        #                 "side": res["side"],
        #                 "price": res["price"],
        #                 "quantity": res["origQty"],
        #                 "orderId": res["orderId"],
        #                 "time": current_time,
        #                 "UTC_PLUS_8": datetime.fromtimestamp(current_time, tz=timezone.utc).astimezone(timezone(timedelta(hours=8))),
        #                 "state": res["state"],
        #             })

        # canclled orders
        new_data = self.filled_orders + self.canceled_orders
        df = pd.DataFrame(new_data)
        logging.info(f"writing {len(df)} history orders in to csv file")
        logging.info(f"filled_orders length: {len(self.filled_orders)}")
        logging.info(f"canceled_orders length: {len(self.canceled_orders)}")

        df.to_csv(self.history_orders_csv_file, mode="a", index=False, header=False)

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

    def record_trade(self, trade_data: Dict[str, Any], is_wash_trading: bool = False):
        """记录成交数据"""
        if self.order_recorder:
            trade_data["strategy_name"] = self.strategy_name
            trade_data["is_wash_trading"] = is_wash_trading
            asyncio.create_task(self.order_recorder.record_trade(trade_data))

        self.canceled_orders = []
        self.filled_orders = []
        # self.sent_orders = {}

    def write_orders(self):
        """
        write history orders to local csv file,
        1. check filled orders and remove them from csv file before writing

        2. check canceled orders and remove them from csv file before writing && remove them from the open_orders
        3. canceled orders are the orders from market should in csv file
        """

        # load csv first
        data = self.read_orders()

        # logging.info(f"check filled orders and remove them from csv file before writing: {data}")
        self.remove_data = self.filled_orders + self.canceled_orders

        logging.info(f"############ remove filled orders {self.filled_orders}")
        # logging.info(f"############ remove orders from cancel orders {self.canceled_orders}")

        local_data = [
            item for item in data if str(item["orderId"]) not in self.remove_data
        ]
        data_ids = [str(item["orderId"]) for item in data]
        logging.info(f"comparing {len(data_ids)} data in csv")
        keep_data = [
            orderid for orderid in self.canceled_orders if orderid not in data_ids
        ]  # strange
        self.canceled_orders = deepcopy(keep_data)
        # logging.info(f"{self.canceled_orders}")

        # if len(self.canceled_orders) > 0:

        #    response = self.client.get_batch_orders([str(order_id) for order_id in self.canceled_orders])
        #    i = 0
        #    for res in response:

        #        logging.info(f"CANCELED orders id {self.canceled_orders[i]} {type(self.canceled_orders[i])} NOT in csv file: price {res['price']} leavingQty{res['leavingQty']} state {res['state']}")
        #        i += 1

        # logging.info(data_ids)
        logging.info(
            f"########### found {len(data)} orders in local, keep {len(local_data)} orders"
        )
        logging.info(f"keep canceled_orders {len(self.canceled_orders)}")
        existing_ids = {str(item["orderId"]) for item in local_data}
        new_data = local_data + [
            order
            for order in self.open_orders.values()
            if str(order["orderId"]) not in existing_ids
        ]
        # logging.info(new_data)
        df = pd.DataFrame(new_data)
        logging.info(f"writing {len(df)} open orders in to csv file")
        logging.info(f"new open orders length: {len(new_data) - len(local_data)}")
        logging.info(f"local open orders length: {len(local_data)}")

        df.to_csv(self.open_orders_csv_file, mode="w", index=False, header=True)

        # reset all datas
        self.open_orders = {}
        self.filled_orders = []

    ###
    # order manager system
    # csv 只记录成交记录，deepcopy，线程锁
    #

    def write_trading_history(self):
        if len(self.trading_history) == 0:
            return

        df = pd.DataFrame(self.trading_history)
        # logging.info(f"writing {len(self.trading_history)} trading history in to csv file")
        df.to_csv(self.trading_history_csv_file, mode="a", index=False, header=False)

    def read_orders(self):
        df = pd.read_csv(self.open_orders_csv_file)
        data = df.to_dict(orient="records")
        # logging.info(f"read {len(data)} orders from csv file")
        return data

    def get_balance(self, symbol):
        balance = self.client.balances([symbol])

        return balance

    def get_position3(self, symbol, currencies):
        depth = self.get_depth_data(symbol)
        mid_price = get_mid_price(depth)
        info = self.client.balances(currencies)
        for currency in info["assets"]:
            if currency["currency"] == symbol.split("_")[0].lower():
                # if float(currency["totalAmount"]) == self.last_amount:
                #    continue
                # if self.last_amount_5l is None:
                #    self.last_amount_5l =
                delta_amount = (
                    float(currency["totalAmount"]) - self.last_amount
                )  # if < 0, user buy, > 0, user sell
                position_amount = float(currency["totalAmount"]) - self.init_amount
                delta_position = delta_amount * mid_price
                self.last_amount = float(currency["totalAmount"])
                self.position = position_amount * mid_price
                # self.delta_amount = delta_amount

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
                        self.canceled_orders.append({
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
                        })
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

                        current_time = time.time()
                        self.filled_orders.append({
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
                        })

                        self.trading_history.append({
                            "orderId": res["orderId"],
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "price": res["price"],
                            "deltaQty": deltaQty,
                        })

                        del self.sent_orders[res["orderId"]]

        self.write_history_orders()

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
        # self.rese
        # self.write_history_orders()
        self.reset_open_orders(symbol)

        order_ids = [str(order_id) for order_id in self.open_orders]
        logging.info(self.open_orders)
        # open orders from (local csv file + self.open_orders)

        pre_order_ids = []
        try:
            if os.stat(self.open_orders_csv_file).st_size > 0:
                data = self.read_orders()
                for rec in data:
                    if rec["orderId"] not in order_ids:
                        pre_order_ids.append(str(rec["orderId"]))
        except Exception as e:
            logging.error(e)
            pass

        logging.info(
            f"find {len(order_ids)} in memory and {len(pre_order_ids)} in local"
        )
        # order_ids += pre_order_ids

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

                        self.trading_history.append({
                            "orderId": res["orderId"],
                            "symbol": res["symbol"],
                            "side": res["side"],
                            "price": res["price"],
                            "deltaQty": deltaQty,
                        })

                        # remove order
                        self.filled_orders.append(res["orderId"])
                        self.remove_order(res["orderId"])

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

    def risk_actions(self, risk_level):
        """
        Level 1: stop market making and wash trading, cancel all orders
        Level 2: stop market making and wash trading, gradually cancel near-end orders within 6 senconds, remain 1/3 far-end orders, reduce order amount to 1/10
        Level 3: continue market making
        """

        if risk_level == 1:
            self.cancel_all_open_orders()
            return False

        elif risk_level == 2:
            self.cancel_orders_bytier(tier_limit=int(self.tier / 5))
            time.sleep(3)
            self.cancel_orders_bytier(tier_limit=int(self.tier / 3))
            time.sleep(2)
            self.cancel_orders_bytier(tier_limit=int(self.tier / 2))
            time.sleep(1)
            self.cancel_orders_bytier(tier_limit=int(self.tier * 2 / 3))
            return False

        elif risk_level == 3:
            return True
