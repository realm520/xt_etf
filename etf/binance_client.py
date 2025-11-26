"""
CCXT Binance 客户端适配器

使用 ccxt 统一 API 替代原 python-binance 库，提供标准化的期货交易接口。

主要功能:
- 期货持仓查询
- 期货订单管理
- 账户余额查询
- 杠杆设置

使用示例:
    from etf.binance_client import BinanceClient
    
    client = BinanceClient(api_key, api_secret)
    positions = client.get_positions()
    balance = client.get_balance()
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import ccxt

logger = logging.getLogger(__name__)


class BinanceClient:
    """
    Binance 期货客户端 (基于 ccxt 统一 API)
    
    提供与原 python-binance 兼容的接口，同时使用 ccxt 标准化方法。
    """
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        default_type: str = "future",
    ):
        """
        初始化 Binance 客户端
        
        Args:
            api_key: API Key
            api_secret: API Secret
            testnet: 是否使用测试网
            default_type: 默认交易类型 ('spot', 'future', 'swap')
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.default_type = default_type
        
        # 初始化 ccxt exchange
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'options': {
                'defaultType': default_type,
                'adjustForTimeDifference': True,
            },
            'enableRateLimit': True,
        })
        
        # 设置测试网
        if testnet:
            self.exchange.set_sandbox_mode(True)
        
        # 加载市场信息
        self._markets_loaded = False
        self._symbol_map: Dict[str, str] = {}  # binance symbol -> ccxt symbol
        
        logger.info(f"BinanceClient 初始化完成 (testnet={testnet}, type={default_type})")
    
    def _ensure_markets_loaded(self):
        """确保市场信息已加载"""
        if not self._markets_loaded:
            self.exchange.load_markets()
            self._build_symbol_map()
            self._markets_loaded = True
    
    def _build_symbol_map(self):
        """构建 symbol 映射表"""
        for ccxt_symbol, market in self.exchange.markets.items():
            binance_symbol = market.get('id', '')
            if binance_symbol:
                self._symbol_map[binance_symbol] = ccxt_symbol
    
    def _convert_symbol(self, binance_symbol: str) -> str:
        """
        将 Binance symbol 转换为 ccxt 格式
        
        Args:
            binance_symbol: Binance 格式的交易对 (如 'BTCUSDT')
            
        Returns:
            ccxt 格式的交易对 (如 'BTC/USDT:USDT')
        """
        self._ensure_markets_loaded()
        
        # 先尝试从映射表查找
        if binance_symbol in self._symbol_map:
            return self._symbol_map[binance_symbol]
        
        # 如果是 USDT 结尾的期货
        if binance_symbol.endswith('USDT'):
            base = binance_symbol[:-4]
            ccxt_symbol = f"{base}/USDT:USDT"
            if ccxt_symbol in self.exchange.markets:
                return ccxt_symbol
        
        # 如果是 BUSD 结尾的期货
        if binance_symbol.endswith('BUSD'):
            base = binance_symbol[:-4]
            ccxt_symbol = f"{base}/BUSD:BUSD"
            if ccxt_symbol in self.exchange.markets:
                return ccxt_symbol
        
        # 返回原始值（可能是现货格式）
        logger.warning(f"无法转换 symbol: {binance_symbol}")
        return binance_symbol
    
    def _convert_symbol_reverse(self, ccxt_symbol: str) -> str:
        """
        将 ccxt symbol 转换回 Binance 格式
        
        Args:
            ccxt_symbol: ccxt 格式的交易对 (如 'BTC/USDT:USDT')
            
        Returns:
            Binance 格式的交易对 (如 'BTCUSDT')
        """
        self._ensure_markets_loaded()
        
        if ccxt_symbol in self.exchange.markets:
            return self.exchange.markets[ccxt_symbol].get('id', ccxt_symbol)
        
        # 简单转换
        return ccxt_symbol.replace('/', '').replace(':USDT', '').replace(':BUSD', '')
    
    # ==================== 持仓相关 ====================
    
    def futures_position_information(
        self, 
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取期货持仓信息
        
        Args:
            symbol: 交易对 (可选，不传则返回所有持仓)
            
        Returns:
            持仓信息列表，格式与原 python-binance 兼容:
            [{
                'symbol': 'BTCUSDT',
                'positionAmt': '0.001',
                'entryPrice': '50000.0',
                'unRealizedProfit': '10.5',
                'liquidationPrice': '40000.0',
                'leverage': '10',
                'marginType': 'cross',
                ...
            }]
        """
        self._ensure_markets_loaded()
        
        try:
            # 使用 ccxt 统一 API
            if symbol:
                ccxt_symbol = self._convert_symbol(symbol)
                positions = self.exchange.fetch_positions([ccxt_symbol])
            else:
                positions = self.exchange.fetch_positions()
            
            # 转换为原 python-binance 格式
            result = []
            for pos in positions:
                result.append({
                    'symbol': self._convert_symbol_reverse(pos.get('symbol', '')),
                    'positionAmt': str(pos.get('contracts', 0)),
                    'entryPrice': str(pos.get('entryPrice', 0)),
                    'unRealizedProfit': str(pos.get('unrealizedPnl', 0)),
                    'liquidationPrice': str(pos.get('liquidationPrice', 0) or 0),
                    'leverage': str(pos.get('leverage', 1)),
                    'marginType': pos.get('marginMode', 'cross'),
                    'isolatedMargin': str(pos.get('initialMargin', 0)),
                    'positionSide': pos.get('side', 'BOTH').upper(),
                    'markPrice': str(pos.get('markPrice', 0)),
                    'notional': str(pos.get('notional', 0)),
                    # ccxt 原始数据
                    '_ccxt_raw': pos,
                })
            
            return result
            
        except Exception as e:
            logger.error(f"获取持仓信息失败: {e}")
            raise
    
    # ==================== 账户相关 ====================
    
    def futures_account_balance(self) -> List[Dict[str, Any]]:
        """
        获取期货账户余额
        
        Returns:
            余额列表，格式与原 python-binance 兼容:
            [{
                'asset': 'USDT',
                'balance': '10000.0',
                'availableBalance': '9000.0',
                'crossUnPnl': '100.0',
                ...
            }]
        """
        self._ensure_markets_loaded()
        
        try:
            balance = self.exchange.fetch_balance()
            
            result = []
            for currency, amounts in balance.items():
                if isinstance(amounts, dict) and 'total' in amounts:
                    result.append({
                        'asset': currency,
                        'balance': str(amounts.get('total', 0)),
                        'availableBalance': str(amounts.get('free', 0)),
                        'crossUnPnl': '0',  # ccxt 统一 API 不直接提供此字段
                        'crossWalletBalance': str(amounts.get('total', 0)),
                        'marginAvailable': True,
                    })
            
            return result
            
        except Exception as e:
            logger.error(f"获取账户余额失败: {e}")
            raise
    
    def futures_account(self) -> Dict[str, Any]:
        """
        获取期货账户完整信息
        
        Returns:
            账户信息，格式与原 python-binance 兼容
        """
        self._ensure_markets_loaded()
        
        try:
            balance = self.exchange.fetch_balance()
            positions = self.exchange.fetch_positions()
            
            # 计算总余额和未实现盈亏
            total_wallet_balance = Decimal('0')
            total_unrealized_pnl = Decimal('0')
            
            usdt_balance = balance.get('USDT', {})
            if isinstance(usdt_balance, dict):
                total_wallet_balance = Decimal(str(usdt_balance.get('total', 0)))
            
            for pos in positions:
                total_unrealized_pnl += Decimal(str(pos.get('unrealizedPnl', 0)))
            
            # 转换持仓格式
            position_list = []
            for pos in positions:
                position_list.append({
                    'symbol': self._convert_symbol_reverse(pos.get('symbol', '')),
                    'positionAmt': str(pos.get('contracts', 0)),
                    'entryPrice': str(pos.get('entryPrice', 0)),
                    'unrealizedProfit': str(pos.get('unrealizedPnl', 0)),
                })
            
            return {
                'totalWalletBalance': str(total_wallet_balance),
                'totalUnrealizedProfit': str(total_unrealized_pnl),
                'totalMarginBalance': str(total_wallet_balance + total_unrealized_pnl),
                'availableBalance': str(balance.get('USDT', {}).get('free', 0)),
                'positions': position_list,
                '_ccxt_balance': balance,
            }
            
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
            raise
    
    # ==================== 订单相关 ====================
    
    def futures_create_order(
        self,
        symbol: str,
        side: str,
        type: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        timeInForce: str = "GTC",
        **kwargs
    ) -> Dict[str, Any]:
        """
        创建期货订单
        
        Args:
            symbol: 交易对 (Binance 格式，如 'BTCUSDT')
            side: 方向 ('BUY' 或 'SELL')
            type: 订单类型 ('LIMIT', 'MARKET', 'STOP', 'STOP_MARKET' 等)
            quantity: 数量
            price: 价格 (限价单必填)
            timeInForce: 有效期 ('GTC', 'IOC', 'FOK')
            **kwargs: 其他参数 (如 stopPrice, reduceOnly 等)
            
        Returns:
            订单信息
        """
        self._ensure_markets_loaded()
        
        ccxt_symbol = self._convert_symbol(symbol)
        ccxt_side = side.lower()
        ccxt_type = type.lower()
        
        # 构建参数
        params = {'timeInForce': timeInForce}
        params.update(kwargs)
        
        try:
            order = self.exchange.create_order(
                symbol=ccxt_symbol,
                type=ccxt_type,
                side=ccxt_side,
                amount=quantity,
                price=price,
                params=params,
            )
            
            # 转换为原 python-binance 格式
            return {
                'orderId': order.get('id'),
                'symbol': symbol,
                'status': order.get('status', '').upper(),
                'clientOrderId': order.get('clientOrderId'),
                'price': str(order.get('price', 0)),
                'avgPrice': str(order.get('average', 0)),
                'origQty': str(order.get('amount', 0)),
                'executedQty': str(order.get('filled', 0)),
                'type': type,
                'side': side,
                'timeInForce': timeInForce,
                'transactTime': order.get('timestamp'),
                '_ccxt_raw': order,
            }
            
        except Exception as e:
            logger.error(f"创建订单失败: {e}")
            raise
    
    def futures_cancel_order(
        self, 
        symbol: str, 
        orderId: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        取消期货订单
        
        Args:
            symbol: 交易对
            orderId: 订单 ID
            
        Returns:
            取消结果
        """
        self._ensure_markets_loaded()
        
        ccxt_symbol = self._convert_symbol(symbol)
        
        try:
            result = self.exchange.cancel_order(orderId, ccxt_symbol, kwargs)
            
            return {
                'orderId': result.get('id'),
                'symbol': symbol,
                'status': 'CANCELED',
                '_ccxt_raw': result,
            }
            
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            raise
    
    def futures_get_open_orders(
        self, 
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取未成交订单
        
        Args:
            symbol: 交易对 (可选)
            
        Returns:
            订单列表
        """
        self._ensure_markets_loaded()
        
        try:
            ccxt_symbol = self._convert_symbol(symbol) if symbol else None
            orders = self.exchange.fetch_open_orders(ccxt_symbol)
            
            result = []
            for order in orders:
                result.append({
                    'orderId': order.get('id'),
                    'symbol': self._convert_symbol_reverse(order.get('symbol', '')),
                    'status': order.get('status', '').upper(),
                    'clientOrderId': order.get('clientOrderId'),
                    'price': str(order.get('price', 0)),
                    'origQty': str(order.get('amount', 0)),
                    'executedQty': str(order.get('filled', 0)),
                    'type': order.get('type', '').upper(),
                    'side': order.get('side', '').upper(),
                    'time': order.get('timestamp'),
                    '_ccxt_raw': order,
                })
            
            return result
            
        except Exception as e:
            logger.error(f"获取未成交订单失败: {e}")
            raise
    
    def futures_get_all_orders(
        self, 
        symbol: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        获取所有订单 (包括已完成)
        
        Args:
            symbol: 交易对 (可选)
            limit: 返回数量限制
            
        Returns:
            订单列表
        """
        self._ensure_markets_loaded()
        
        try:
            ccxt_symbol = self._convert_symbol(symbol) if symbol else None
            orders = self.exchange.fetch_orders(ccxt_symbol, limit=limit)
            
            result = []
            for order in orders:
                result.append({
                    'orderId': order.get('id'),
                    'symbol': self._convert_symbol_reverse(order.get('symbol', '')),
                    'status': order.get('status', '').upper(),
                    'price': str(order.get('price', 0)),
                    'origQty': str(order.get('amount', 0)),
                    'executedQty': str(order.get('filled', 0)),
                    'type': order.get('type', '').upper(),
                    'side': order.get('side', '').upper(),
                    'time': order.get('timestamp'),
                    '_ccxt_raw': order,
                })
            
            return result
            
        except Exception as e:
            logger.error(f"获取所有订单失败: {e}")
            raise
    
    # ==================== 杠杆和保证金 ====================
    
    def futures_change_leverage(
        self, 
        symbol: str, 
        leverage: int
    ) -> Dict[str, Any]:
        """
        设置杠杆倍数
        
        Args:
            symbol: 交易对
            leverage: 杠杆倍数
            
        Returns:
            设置结果
        """
        self._ensure_markets_loaded()
        
        ccxt_symbol = self._convert_symbol(symbol)
        
        try:
            result = self.exchange.set_leverage(leverage, ccxt_symbol)
            
            return {
                'symbol': symbol,
                'leverage': leverage,
                'maxNotionalValue': str(result.get('maxNotionalValue', 0)) if result else '0',
                '_ccxt_raw': result,
            }
            
        except Exception as e:
            logger.error(f"设置杠杆失败: {e}")
            raise
    
    def futures_change_margin_type(
        self, 
        symbol: str, 
        marginType: str
    ) -> Dict[str, Any]:
        """
        设置保证金模式
        
        Args:
            symbol: 交易对
            marginType: 保证金类型 ('CROSSED' 或 'ISOLATED')
            
        Returns:
            设置结果
        """
        self._ensure_markets_loaded()
        
        ccxt_symbol = self._convert_symbol(symbol)
        margin_mode = 'cross' if marginType.upper() == 'CROSSED' else 'isolated'
        
        try:
            result = self.exchange.set_margin_mode(margin_mode, ccxt_symbol)
            return {
                'symbol': symbol,
                'marginType': marginType,
                '_ccxt_raw': result,
            }
            
        except Exception as e:
            logger.error(f"设置保证金模式失败: {e}")
            raise
    
    def futures_change_position_mode(
        self, 
        dualSidePosition: bool
    ) -> Dict[str, Any]:
        """
        设置持仓模式 (单向/双向)
        
        Args:
            dualSidePosition: True=双向持仓模式, False=单向持仓模式
            
        Returns:
            设置结果
        """
        self._ensure_markets_loaded()
        
        try:
            # 使用隐式 API，因为 ccxt 统一 API 不直接支持此操作
            result = self.exchange.fapiprivate_post_positionside_dual({
                'dualSidePosition': dualSidePosition,
            })
            return {
                'dualSidePosition': dualSidePosition,
                '_ccxt_raw': result,
            }
            
        except Exception as e:
            logger.error(f"设置持仓模式失败: {e}")
            raise
    
    # ==================== 市场数据 ====================
    
    def get_symbol_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        获取交易对当前价格 (现货)
        
        Args:
            symbol: 交易对
            
        Returns:
            价格信息 {'symbol': 'BTCUSDT', 'price': '50000.0'}
        """
        self._ensure_markets_loaded()
        
        try:
            # 临时切换到现货模式
            original_type = self.exchange.options.get('defaultType')
            self.exchange.options['defaultType'] = 'spot'
            
            # 获取现货 symbol
            spot_symbol = symbol
            if symbol.endswith('USDT'):
                base = symbol[:-4]
                spot_symbol = f"{base}/USDT"
            
            ticker = self.exchange.fetch_ticker(spot_symbol)
            
            # 恢复原模式
            self.exchange.options['defaultType'] = original_type
            
            return {
                'symbol': symbol,
                'price': str(ticker.get('last', 0)),
            }
            
        except Exception as e:
            logger.error(f"获取价格失败: {e}")
            raise
    
    def futures_symbol_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        获取交易对当前价格 (期货)
        
        Args:
            symbol: 交易对
            
        Returns:
            价格信息 {'symbol': 'BTCUSDT', 'price': '50000.0'}
        """
        self._ensure_markets_loaded()
        
        ccxt_symbol = self._convert_symbol(symbol)
        
        try:
            ticker = self.exchange.fetch_ticker(ccxt_symbol)
            
            return {
                'symbol': symbol,
                'price': str(ticker.get('last', 0)),
                'time': ticker.get('timestamp'),
            }
            
        except Exception as e:
            logger.error(f"获取期货价格失败: {e}")
            raise
    
    # ==================== 交易所信息 ====================
    
    def get_exchange_info(self) -> Dict[str, Any]:
        """
        获取交易所信息
        
        Returns:
            交易所规则和交易对信息
        """
        self._ensure_markets_loaded()
        
        try:
            # ccxt 的 markets 包含了交易所信息
            symbols = []
            for ccxt_symbol, market in self.exchange.markets.items():
                symbols.append({
                    'symbol': market.get('id'),
                    'baseAsset': market.get('base'),
                    'quoteAsset': market.get('quote'),
                    'pricePrecision': market.get('precision', {}).get('price'),
                    'quantityPrecision': market.get('precision', {}).get('amount'),
                    'status': 'TRADING' if market.get('active') else 'BREAK',
                })
            
            return {
                'timezone': 'UTC',
                'serverTime': self.exchange.milliseconds(),
                'symbols': symbols,
            }
            
        except Exception as e:
            logger.error(f"获取交易所信息失败: {e}")
            raise
    
    def get_account(self) -> Dict[str, Any]:
        """
        获取现货账户信息
        
        Returns:
            账户信息
        """
        self._ensure_markets_loaded()
        
        try:
            # 临时切换到现货模式
            original_type = self.exchange.options.get('defaultType')
            self.exchange.options['defaultType'] = 'spot'
            
            balance = self.exchange.fetch_balance()
            
            # 恢复原模式
            self.exchange.options['defaultType'] = original_type
            
            # 转换格式
            balances = []
            for currency, amounts in balance.items():
                if isinstance(amounts, dict) and amounts.get('total', 0) > 0:
                    balances.append({
                        'asset': currency,
                        'free': str(amounts.get('free', 0)),
                        'locked': str(amounts.get('used', 0)),
                    })
            
            return {
                'balances': balances,
                '_ccxt_raw': balance,
            }
            
        except Exception as e:
            logger.error(f"获取现货账户失败: {e}")
            raise
    
    # ==================== 工具方法 ====================
    
    def close(self):
        """关闭连接"""
        pass  # ccxt 同步客户端不需要显式关闭


# 为了兼容性，提供 Client 别名
Client = BinanceClient


class AsyncBinanceClient:
    """
    Binance 期货异步客户端 (基于 ccxt 统一 API)
    
    提供与 BinanceClient 相同的接口，但支持异步操作。
    """
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        default_type: str = "future",
    ):
        """初始化异步客户端"""
        import ccxt.async_support as ccxt_async
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.default_type = default_type
        
        self.exchange = ccxt_async.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'options': {
                'defaultType': default_type,
                'adjustForTimeDifference': True,
            },
            'enableRateLimit': True,
        })
        
        if testnet:
            self.exchange.set_sandbox_mode(True)
        
        self._markets_loaded = False
        self._symbol_map: Dict[str, str] = {}
        
        logger.info(f"AsyncBinanceClient 初始化完成 (testnet={testnet})")
    
    async def _ensure_markets_loaded(self):
        """确保市场信息已加载"""
        if not self._markets_loaded:
            await self.exchange.load_markets()
            self._build_symbol_map()
            self._markets_loaded = True
    
    def _build_symbol_map(self):
        """构建 symbol 映射表"""
        for ccxt_symbol, market in self.exchange.markets.items():
            binance_symbol = market.get('id', '')
            if binance_symbol:
                self._symbol_map[binance_symbol] = ccxt_symbol
    
    def _convert_symbol(self, binance_symbol: str) -> str:
        """将 Binance symbol 转换为 ccxt 格式"""
        if binance_symbol in self._symbol_map:
            return self._symbol_map[binance_symbol]
        
        if binance_symbol.endswith('USDT'):
            base = binance_symbol[:-4]
            return f"{base}/USDT:USDT"
        
        return binance_symbol
    
    def _convert_symbol_reverse(self, ccxt_symbol: str) -> str:
        """将 ccxt symbol 转换回 Binance 格式"""
        if ccxt_symbol in self.exchange.markets:
            return self.exchange.markets[ccxt_symbol].get('id', ccxt_symbol)
        return ccxt_symbol.replace('/', '').replace(':USDT', '')
    
    async def futures_position_information(
        self, 
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取期货持仓信息 (异步)"""
        await self._ensure_markets_loaded()
        
        if symbol:
            ccxt_symbol = self._convert_symbol(symbol)
            positions = await self.exchange.fetch_positions([ccxt_symbol])
        else:
            positions = await self.exchange.fetch_positions()
        
        result = []
        for pos in positions:
            result.append({
                'symbol': self._convert_symbol_reverse(pos.get('symbol', '')),
                'positionAmt': str(pos.get('contracts', 0)),
                'entryPrice': str(pos.get('entryPrice', 0)),
                'unRealizedProfit': str(pos.get('unrealizedPnl', 0)),
                'liquidationPrice': str(pos.get('liquidationPrice', 0) or 0),
                'leverage': str(pos.get('leverage', 1)),
                'marginType': pos.get('marginMode', 'cross'),
                '_ccxt_raw': pos,
            })
        
        return result
    
    async def futures_account_balance(self) -> List[Dict[str, Any]]:
        """获取期货账户余额 (异步)"""
        await self._ensure_markets_loaded()
        
        balance = await self.exchange.fetch_balance()
        
        result = []
        for currency, amounts in balance.items():
            if isinstance(amounts, dict) and 'total' in amounts:
                result.append({
                    'asset': currency,
                    'balance': str(amounts.get('total', 0)),
                    'availableBalance': str(amounts.get('free', 0)),
                })
        
        return result
    
    async def futures_create_order(
        self,
        symbol: str,
        side: str,
        type: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        timeInForce: str = "GTC",
        **kwargs
    ) -> Dict[str, Any]:
        """创建期货订单 (异步)"""
        await self._ensure_markets_loaded()
        
        ccxt_symbol = self._convert_symbol(symbol)
        params = {'timeInForce': timeInForce}
        params.update(kwargs)
        
        order = await self.exchange.create_order(
            symbol=ccxt_symbol,
            type=type.lower(),
            side=side.lower(),
            amount=quantity,
            price=price,
            params=params,
        )
        
        return {
            'orderId': order.get('id'),
            'symbol': symbol,
            'status': order.get('status', '').upper(),
            'price': str(order.get('price', 0)),
            'origQty': str(order.get('amount', 0)),
            'executedQty': str(order.get('filled', 0)),
            '_ccxt_raw': order,
        }
    
    async def futures_change_leverage(
        self, 
        symbol: str, 
        leverage: int
    ) -> Dict[str, Any]:
        """设置杠杆倍数 (异步)"""
        await self._ensure_markets_loaded()
        
        ccxt_symbol = self._convert_symbol(symbol)
        result = await self.exchange.set_leverage(leverage, ccxt_symbol)
        
        return {
            'symbol': symbol,
            'leverage': leverage,
            '_ccxt_raw': result,
        }
    
    async def get_symbol_ticker(self, symbol: str) -> Dict[str, Any]:
        """获取价格 (异步)"""
        await self._ensure_markets_loaded()
        
        ccxt_symbol = self._convert_symbol(symbol)
        ticker = await self.exchange.fetch_ticker(ccxt_symbol)
        
        return {
            'symbol': symbol,
            'price': str(ticker.get('last', 0)),
        }
    
    async def close(self):
        """关闭连接"""
        await self.exchange.close()


# 提供 AsyncClient 别名
AsyncClient = AsyncBinanceClient
