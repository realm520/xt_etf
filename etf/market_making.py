"""
ETF做市商模块 - 统一使用 Maintainer + ExecutorV2 架构

架构:
    MarketMaker
        └── OrderbookMaintainer (计算订单簿调整操作)
        └── OrderExecutorV2 (执行订单操作)
"""

import time
import logging
import redis
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

# Maintainer 相关导入
from etf.orderbook.maintainer import (
    OrderbookMaintainer,
    MaintainerConfig,
    MaintainerAdapter,
    MaintenanceResult,
    LayerSpec,
)
from etf.orderbook.executor_v2 import OrderExecutorV2, ExecutionResult
from etf.utils.constants import (
    DEFAULT_REDIS_HOST, DEFAULT_REDIS_PORT, DEFAULT_REDIS_DB,
)

logger = logging.getLogger(__name__)


class MarketMaker:
    """
    ETF做市商核心类
    
    使用 Maintainer + ExecutorV2 架构进行订单簿维护:
    1. Maintainer: 计算当前订单簿与目标订单簿的差异，生成操作列表
    2. ExecutorV2: 执行操作列表（先添加后取消，保证流动性）
    
    Attributes:
        order_manager: 订单管理器实例
        symbol_config_manager: Symbol配置管理器
        maintainer: 订单簿维护器
        executor: 订单执行器
    """
    
    def __init__(self, order_manager: Any, symbol_config_manager: Any = None) -> None:
        """
        初始化做市商

        Args:
            order_manager: 订单管理器实例
            symbol_config_manager: Symbol配置管理器，用于动态获取交易对精度
        """
        self.order_manager = order_manager
        self.symbol_config_manager = symbol_config_manager
        
        # Redis 连接
        self.r: redis.Redis = redis.Redis(
            host=DEFAULT_REDIS_HOST,
            port=DEFAULT_REDIS_PORT,
            db=DEFAULT_REDIS_DB
        )
        
        # 最优价格追踪
        self.best_sell: float = 0.0
        self.best_buy: float = 0.0
        self.last_best_sell: float = 0.0
        self.last_best_buy: float = 0.0
        
        # 净值和更新时间追踪
        self.last_netvalue: Optional[float] = None
        self.last_update_time: float = 0.0
        
        # Maintainer 和 Executor
        self.maintainer: Optional[OrderbookMaintainer] = None
        self.executor: Optional[OrderExecutorV2] = None
        
        # 配置缓存
        self._symbol: Optional[str] = None
        self._strategy_name: Optional[str] = None

    def init_maintainer(
        self,
        config: Dict[str, Any],
        symbol: str,
        strategy_name: str,
    ) -> None:
        """
        初始化 Maintainer 和 ExecutorV2
        
        Args:
            config: 策略配置字典，包含:
                - spread: 买卖价差 (如 0.008)
                - max_distance: 最大距离 (如 0.10)
                - total_budget: 总预算 (如 10000)
                - min_price_change: 最小价格变化触发阈值 (如 0.002)
                - max_operations_per_cycle: 每周期最大操作数 (如 30)
                - near_layer / far_layer: 分层配置
            symbol: 交易对 (如 "TON3LUSDT")
            strategy_name: 策略名称 (如 "stg3l")
        """
        self._symbol = symbol
        self._strategy_name = strategy_name
        
        # 获取动态精度配置
        price_precision = config.get("price_precision", 6)
        quantity_precision = config.get("quantity_precision", 2)
        
        if self.symbol_config_manager:
            price_precision = self.symbol_config_manager.get_price_precision(symbol) or price_precision
            quantity_precision = self.symbol_config_manager.get_quantity_precision(symbol) or quantity_precision
        
        # 构建 MaintainerConfig
        spread = Decimal(str(config.get("spread", config.get("bid_ask_spread", 0.008))))
        max_distance = Decimal(str(config.get("max_distance", 0.10)))
        total_budget = Decimal(str(config.get("total_budget", 10000)))
        
        # 解析分层配置
        near_layer_cfg = config.get("near_layer", {})
        far_layer_cfg = config.get("far_layer", {})
        
        near_layer = LayerSpec(
            name="near",
            distance_range=(
                Decimal(str(near_layer_cfg.get("distance_min", 0))),
                Decimal(str(near_layer_cfg.get("distance_max", float(spread) + 0.02))),
            ),
            budget_ratio=Decimal(str(near_layer_cfg.get("budget_ratio", 0.4))),
            order_count=near_layer_cfg.get("order_count", 10),
        )
        far_layer = LayerSpec(
            name="far",
            distance_range=(
                Decimal(str(far_layer_cfg.get("distance_min", float(spread) + 0.02))),
                Decimal(str(far_layer_cfg.get("distance_max", float(max_distance)))),
            ),
            budget_ratio=Decimal(str(far_layer_cfg.get("budget_ratio", 0.6))),
            order_count=far_layer_cfg.get("order_count", 14),
        )
        
        maintainer_config = MaintainerConfig(
            spread=spread,
            max_distance=max_distance,
            total_budget=total_budget,
            near_layer=near_layer,
            far_layer=far_layer,
            price_precision=price_precision,
            quantity_precision=quantity_precision,
            min_price_change=Decimal(str(config.get("min_price_change", 0.002))),
            max_operations_per_cycle=config.get("max_operations_per_cycle", 30),
        )
        
        # 创建 Maintainer
        self.maintainer = OrderbookMaintainer(maintainer_config)
        
        # 创建 ExecutorV2
        executor_config = {
            "max_orders": config.get("max_orders", 200),
            "order_overflow_threshold": config.get("order_overflow_threshold", 0.9),
            "price_precision": price_precision,
            "quantity_precision": quantity_precision,
        }
        self.executor = OrderExecutorV2(
            order_manager=self.order_manager,
            symbol=symbol,
            strategy_name=strategy_name,
            config=executor_config,
        )
        
        logger.info(
            f"[{strategy_name}] Maintainer 初始化完成: "
            f"spread={spread}, max_distance={max_distance}, "
            f"total_budget={total_budget}"
        )

    def place_orders(
        self,
        config: Dict[str, Any],
        symbol: str = "btc5l_usdt",
        **kwargs,  # 兼容旧参数
    ) -> None:
        """
        执行做市订单放置策略
        
        流程:
        1. 获取净值
        2. 获取当前订单
        3. 调用 Maintainer 计算调整操作
        4. 使用 ExecutorV2 执行操作
        
        Args:
            config: 策略配置字典
            symbol: 交易对符号
            **kwargs: 兼容旧参数 (clientOrderId, env, ordermanager, currencies, prec)
        """
        strategy_name = config.get("strategy_name", self._strategy_name or "unknown")
        
        # === 1. 确保 Maintainer 已初始化 ===
        if self.maintainer is None or self.executor is None:
            logger.info(f"[{strategy_name}] 首次运行，初始化 Maintainer...")
            self.init_maintainer(config, symbol, strategy_name)
        
        # === 2. 获取净值 ===
        netvalue = self._get_netvalue(config)
        if not netvalue:
            logger.info(f"[{time.strftime('%H:%M:%S')}] Waiting for net value..")
            return
        
        # 更新 OrderManager 的净值
        self.order_manager.netvalue = netvalue
        logger.info(f"{symbol}, netvalue={netvalue}")
        
        # === 3. 获取当前订单 ===
        current_orders = self._get_current_orders(symbol)
        if current_orders is None:
            return
        
        # === 4. 执行 Maintainer 路径 ===
        self._execute_maintainer(
            current_orders=current_orders,
            netvalue=netvalue,
            symbol=symbol,
            config=config,
        )

    def _get_netvalue(self, config: Dict[str, Any]) -> Optional[float]:
        """获取净值"""
        try:
            redis_value = self.r.get(config["netvalue"])
            if redis_value is not None:
                return float(redis_value.decode())
            
            logger.warning(f"Redis key {config['netvalue']} not found")
            return None
            
        except Exception as e:
            logger.error(f"Error getting netvalue: {e}")
            return None

    def _get_current_orders(self, symbol: str) -> Optional[List[Dict[str, Any]]]:
        """获取当前订单，带重试"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self.order_manager.client.get_open_orders(symbol=symbol)
            except Exception as e:
                logger.error(f"获取当前订单失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None

    def _execute_maintainer(
        self,
        current_orders: List[Dict[str, Any]],
        netvalue: float,
        symbol: str,
        config: Dict[str, Any],
    ) -> None:
        """
        执行 Maintainer 路径
        
        流程:
        1. 转换当前订单为 CurrentOrderbook
        2. 调用 Maintainer.maintain() 获取操作列表
        3. 使用 ExecutorV2 执行操作
        4. 记录统计信息
        """
        strategy_name = config.get("strategy_name", self._strategy_name or "unknown")
        
        # 1. 转换当前订单为 CurrentOrderbook（仅 mm_ 前缀订单）
        current_orderbook = MaintainerAdapter.from_exchange_orders(
            orders=current_orders,
            filter_prefix="mm_",
        )
        
        mm_order_count = len(current_orderbook.bids) + len(current_orderbook.asks)
        logger.info(
            f"[{strategy_name}] 当前 {mm_order_count} 个做市订单 "
            f"(买: {len(current_orderbook.bids)}, 卖: {len(current_orderbook.asks)})"
        )
        
        # 2. 调用 Maintainer 计算调整操作
        nav_decimal = Decimal(str(netvalue))
        result: MaintenanceResult = self.maintainer.maintain(current_orderbook, nav_decimal)
        
        # 3. 检查是否需要更新
        if not result.needs_update:
            logger.info(
                f"[{strategy_name}] 无需更新 "
                f"(NAV变化: {float(result.stats.nav_change_ratio):.4%})"
            )
            return
        
        # 4. 记录操作统计
        add_count = sum(1 for op in result.operations if op.action == "add")
        cancel_count = sum(1 for op in result.operations if op.action == "cancel")

        # 判断是否为初始化阶段（与 core.py 逻辑一致）
        target_order_count = len(result.target_snapshot.bids) + len(result.target_snapshot.asks)
        is_initial = mm_order_count < target_order_count * 0.2

        if is_initial:
            logger.info(
                f"[{strategy_name}] 🚀 初始化订单簿: "
                f"一次性添加 {add_count} 个订单 (目标: {target_order_count})"
            )
        else:
            logger.info(
                f"[{strategy_name}] 生成 {len(result.operations)} 个操作: "
                f"+{add_count} add, -{cancel_count} cancel, "
                f"复用率: {float(result.stats.reuse_ratio):.1%}"
            )
        
        # 5. 使用 ExecutorV2 执行操作
        exec_result: ExecutionResult = self.executor.execute(
            operations=result.operations,
            current_order_count=mm_order_count,
        )
        
        # 6. 记录执行结果
        if exec_result.success:
            logger.info(
                f"[{strategy_name}] 执行成功: "
                f"+{exec_result.stats.adds_succeeded} adds, "
                f"-{exec_result.stats.cancels_succeeded} cancels, "
                f"成功率: {exec_result.stats.success_rate:.1%}, "
                f"耗时: {exec_result.stats.execution_time_ms:.0f}ms"
            )
        else:
            logger.warning(
                f"[{strategy_name}] 执行部分失败: "
                f"+{exec_result.stats.adds_succeeded}/{exec_result.stats.add_operations} adds, "
                f"-{exec_result.stats.cancels_succeeded}/{exec_result.stats.cancel_operations} cancels, "
                f"错误: {exec_result.error_message}"
            )
            
            # 记录失败详情
            for op, err in exec_result.failed_adds[:5]:
                logger.warning(f"  添加失败: {op.side} @ {op.price} - {err}")
            for order_id, err in exec_result.failed_cancels[:5]:
                logger.warning(f"  取消失败: {order_id} - {err}")
        
        # 7. 更新最优价格记录（从目标订单簿快照获取）
        if result.target_snapshot:
            if result.target_snapshot.bids:
                self.best_buy = float(result.target_snapshot.bids[0].price)
            if result.target_snapshot.asks:
                self.best_sell = float(result.target_snapshot.asks[0].price)
            self.last_best_buy = self.best_buy
            self.last_best_sell = self.best_sell
        
        # 更新净值和时间
        self.last_netvalue = netvalue
        self.last_update_time = time.time()

    def get_stats(self) -> Dict[str, Any]:
        """获取做市商统计信息"""
        stats = {
            "symbol": self._symbol,
            "strategy_name": self._strategy_name,
            "best_buy": self.best_buy,
            "best_sell": self.best_sell,
            "last_netvalue": self.last_netvalue,
            "last_update_time": self.last_update_time,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        if self.executor:
            stats["executor_stats"] = self.executor.get_stats() if hasattr(self.executor, 'get_stats') else {}
        
        return stats
