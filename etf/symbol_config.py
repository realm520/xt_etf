# -*- coding: utf-8 -*-
"""
Symbol配置管理器
动态从交易所获取交易对配置信息，用于订单参数验证和格式化

Author: ETF Trading System
Date: 2025-01-18
"""

import logging
import time
import threading
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class SymbolConfigManager:
    """
    Symbol配置管理器

    功能：
    - 从交易所API获取交易对配置
    - 缓存配置信息，定期刷新
    - 提供订单参数验证和格式化
    - 处理浮点数精度问题
    """

    def __init__(self, spot_client, refresh_interval: int = 3600):
        """
        初始化配置管理器

        Args:
            spot_client: XT交易所客户端实例
            refresh_interval: 配置刷新间隔（秒），默认3600秒（1小时）
        """
        self.spot_client = spot_client
        self.refresh_interval = refresh_interval

        # 配置缓存：{symbol: config_dict}
        self._config_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp: Dict[str, float] = {}

        # 后台刷新线程
        self._refresh_thread = None
        self._stop_refresh = threading.Event()

        logger.info("SymbolConfigManager 初始化完成")

    def load_symbol_config(self, symbol: str, force_reload: bool = False) -> bool:
        """
        从交易所加载交易对配置

        Args:
            symbol: 交易对名称，如 "btc_usdt", "ton3l_usdt"
            force_reload: 是否强制重新加载（忽略缓存）

        Returns:
            bool: 是否加载成功
        """
        # 检查缓存
        if not force_reload and symbol in self._config_cache:
            cache_age = time.time() - self._cache_timestamp.get(symbol, 0)
            if cache_age < self.refresh_interval:
                logger.debug(f"使用缓存的配置: {symbol}, 缓存年龄: {cache_age:.0f}秒")
                return True

        try:
            logger.info(f"正在从交易所加载 {symbol} 配置...")

            # 调用API获取配置
            config_list = self.spot_client.get_symbol_config(symbol=symbol)

            if not config_list or len(config_list) == 0:
                logger.error(f"未找到 {symbol} 的配置信息")
                return False

            # 取第一个结果（应该只有一个）
            config = config_list[0]

            # 验证关键字段
            required_fields = ["symbol", "pricePrecision", "quantityPrecision", "filters"]
            for field in required_fields:
                if field not in config:
                    logger.error(f"{symbol} 配置缺少必需字段: {field}")
                    return False

            # 提取过滤器信息
            filters = self._parse_filters(config.get("filters", []))

            # 构建缓存数据
            cache_data = {
                "symbol": config["symbol"],
                "state": config.get("state", "UNKNOWN"),
                "tradingEnabled": config.get("tradingEnabled", False),
                "pricePrecision": config["pricePrecision"],
                "quantityPrecision": config["quantityPrecision"],
                "baseCurrency": config.get("baseCurrency", ""),
                "quoteCurrency": config.get("quoteCurrency", ""),
                "takerFeeRate": config.get("takerFeeRate", 0),
                "makerFeeRate": config.get("makerFeeRate", 0),
                "filters": filters,
                "raw_config": config  # 保存原始配置以备查
            }

            # 更新缓存
            self._config_cache[symbol] = cache_data
            self._cache_timestamp[symbol] = time.time()

            logger.info(
                f"✅ {symbol} 配置加载成功: "
                f"价格精度={cache_data['pricePrecision']}, "
                f"数量精度={cache_data['quantityPrecision']}, "
                f"状态={cache_data['state']}"
            )

            return True

        except Exception as e:
            logger.error(f"加载 {symbol} 配置失败: {e}", exc_info=True)
            return False

    def _parse_filters(self, filters: list) -> Dict[str, Dict[str, Any]]:
        """
        解析过滤器配置

        Args:
            filters: API返回的filters列表

        Returns:
            Dict: 按filter类型组织的字典
        """
        parsed = {}

        for f in filters:
            filter_type = f.get("filter")
            if not filter_type:
                continue

            parsed[filter_type] = {
                k: v for k, v in f.items()
                if k != "filter"
            }

        return parsed

    def get_price_precision(self, symbol: str) -> Optional[int]:
        """获取价格精度（小数位数）"""
        if symbol not in self._config_cache:
            if not self.load_symbol_config(symbol):
                return None

        return self._config_cache[symbol].get("pricePrecision")

    def get_quantity_precision(self, symbol: str) -> Optional[int]:
        """获取数量精度（小数位数）"""
        if symbol not in self._config_cache:
            if not self.load_symbol_config(symbol):
                return None

        return self._config_cache[symbol].get("quantityPrecision")

    def format_price(self, symbol: str, price: float) -> float:
        """
        格式化价格，使用Decimal避免浮点数误差

        Args:
            symbol: 交易对
            price: 原始价格

        Returns:
            float: 格式化后的价格
        """
        precision = self.get_price_precision(symbol)
        if precision is None:
            logger.warning(f"无法获取 {symbol} 的价格精度，返回原始价格")
            return price

        return self._format_number(price, precision)

    def format_quantity(self, symbol: str, quantity: float) -> float:
        """
        格式化数量，使用Decimal避免浮点数误差

        Args:
            symbol: 交易对
            quantity: 原始数量

        Returns:
            float: 格式化后的数量
        """
        precision = self.get_quantity_precision(symbol)
        if precision is None:
            logger.warning(f"无法获取 {symbol} 的数量精度，返回原始数量")
            return quantity

        return self._format_number(quantity, precision)

    def _format_number(self, value: float, precision: int) -> float:
        """
        使用Decimal精确格式化数字

        Args:
            value: 原始值
            precision: 小数位数

        Returns:
            float: 格式化后的值
        """
        try:
            # 构建量化字符串，如 precision=2 -> "0.01"
            if precision == 0:
                quantize_str = "1"
            else:
                quantize_str = "0." + "0" * (precision - 1) + "1"

            # 使用Decimal精确计算
            result = Decimal(str(value)).quantize(
                Decimal(quantize_str),
                rounding=ROUND_DOWN  # 向下取整，避免超过最大值
            )

            return float(result)

        except Exception as e:
            logger.error(f"格式化数字失败: value={value}, precision={precision}, error={e}")
            return value

    def validate_order(
        self,
        symbol: str,
        price: float,
        quantity: float
    ) -> Tuple[bool, str]:
        """
        验证订单参数是否符合交易所要求

        Args:
            symbol: 交易对
            price: 订单价格
            quantity: 订单数量

        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        # 加载配置
        if symbol not in self._config_cache:
            if not self.load_symbol_config(symbol):
                return False, f"无法加载 {symbol} 配置"

        config = self._config_cache[symbol]

        # 检查交易状态
        if not config.get("tradingEnabled", False):
            return False, f"{symbol} 交易未启用"

        if config.get("state") != "ONLINE":
            return False, f"{symbol} 状态异常: {config.get('state')}"

        # 检查价格精度
        price_precision = config["pricePrecision"]
        formatted_price = self._format_number(price, price_precision)
        if abs(formatted_price - price) > 1e-10:
            return False, f"价格精度错误: {price} 应为 {formatted_price} (精度={price_precision})"

        # 检查数量精度
        quantity_precision = config["quantityPrecision"]
        formatted_quantity = self._format_number(quantity, quantity_precision)
        if abs(formatted_quantity - quantity) > 1e-10:
            return False, f"数量精度错误: {quantity} 应为 {formatted_quantity} (精度={quantity_precision})"

        # 检查PRICE过滤器
        price_filter = config["filters"].get("PRICE", {})
        if price_filter:
            min_price = price_filter.get("min")
            max_price = price_filter.get("max")

            if min_price is not None and price < float(min_price):
                return False, f"价格低于最小值: {price} < {min_price}"

            if max_price is not None and price > float(max_price):
                return False, f"价格高于最大值: {price} > {max_price}"

        # 检查QUANTITY过滤器
        quantity_filter = config["filters"].get("QUANTITY", {})
        if quantity_filter:
            min_qty = quantity_filter.get("min")
            max_qty = quantity_filter.get("max")

            if min_qty is not None and quantity < float(min_qty):
                return False, f"数量低于最小值: {quantity} < {min_qty}"

            if max_qty is not None and quantity > float(max_qty):
                return False, f"数量高于最大值: {quantity} > {max_qty}"

        # 检查QUOTE_QTY过滤器（订单金额）
        quote_qty_filter = config["filters"].get("QUOTE_QTY", {})
        if quote_qty_filter:
            min_quote_qty = quote_qty_filter.get("min")
            order_value = price * quantity

            if min_quote_qty is not None and order_value < float(min_quote_qty):
                return False, f"订单金额低于最小值: {order_value} < {min_quote_qty}"

        return True, ""

    def start_auto_refresh(self):
        """启动自动刷新线程"""
        if self._refresh_thread and self._refresh_thread.is_alive():
            logger.warning("自动刷新线程已在运行")
            return

        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(
            target=self._auto_refresh_loop,
            daemon=True,
            name="SymbolConfigRefresh"
        )
        self._refresh_thread.start()
        logger.info(f"自动刷新线程已启动，间隔: {self.refresh_interval}秒")

    def stop_auto_refresh(self):
        """停止自动刷新线程"""
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._stop_refresh.set()
            self._refresh_thread.join(timeout=5)
            logger.info("自动刷新线程已停止")

    def _auto_refresh_loop(self):
        """自动刷新循环（后台线程）"""
        while not self._stop_refresh.is_set():
            try:
                # 等待刷新间隔
                if self._stop_refresh.wait(timeout=self.refresh_interval):
                    break  # 收到停止信号

                # 刷新所有已缓存的symbol
                for symbol in list(self._config_cache.keys()):
                    try:
                        logger.debug(f"自动刷新配置: {symbol}")
                        self.load_symbol_config(symbol, force_reload=True)
                    except Exception as e:
                        logger.error(f"刷新 {symbol} 配置失败: {e}")

            except Exception as e:
                logger.error(f"自动刷新循环异常: {e}", exc_info=True)

    def get_config(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取完整的symbol配置

        Args:
            symbol: 交易对

        Returns:
            Dict: 配置字典，如果不存在则返回None
        """
        if symbol not in self._config_cache:
            if not self.load_symbol_config(symbol):
                return None

        return self._config_cache.get(symbol)

    def __enter__(self):
        """上下文管理器支持"""
        self.start_auto_refresh()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器支持"""
        self.stop_auto_refresh()
