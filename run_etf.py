from etf.risk import RiskController
from etf.washing import WashController
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.xt import Spot
from etf.stability_monitor import StabilityMonitor
from etf.websocket import XTWebSocketClient
from etf.symbol_config import SymbolConfigManager  # Symbol配置管理器
from hedging import Hedge  # 旧版对冲（向后兼容）
from etf.hedging import create_hedge_orchestrator  # 新版模块化对冲系统
from etf.observability import init_otel, MetricsCollector, PrometheusServer  # Prometheus 集成
from etf.utils.logger import setup_logging  # 新增：统一日志配置工具
import json
import time
import logging
import threading
import atexit
import argparse
import yaml
import os
import asyncio
import sys
import redis

# 暂时使用基础配置，等策略名称确定后会重新配置
logging.shutdown()
logging.basicConfig(
    level=logging.DEBUG,  # 改为 DEBUG 级别以显示 debug 日志
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class EtfStrategy:
    def __init__(self, client, order_manager):
        self.client = client
        self.order_manager = order_manager

    @staticmethod
    def run(config, risk_controller, wash_controller, market_maker, stability_monitor=None, depth=None):
        # 优先使用传入的 depth，避免重复 API 调用触发限流
        if depth is None or (not depth.get("bids") and not depth.get("asks")):
            try:
                depth = risk_controller.get_depth_data(config["symbol"])
                if stability_monitor:
                    stability_monitor.record_api_call(success=True)
                logging.info("获取新的 depth 数据成功")
            except Exception as e:
                logging.error(f"获取 depth 失败: {e}")
                logging.info("使用历史 depth 数据")
                depth = risk_controller.depth if risk_controller.depth else {"bids": [], "asks": []}
                if stability_monitor:
                    stability_monitor.record_api_call(success=False)
        else:
            logging.info("使用传入的 depth 数据，避免重复 API 调用")

        logging.info("cancel_all_open_orders")        
        try:
            market_maker.order_manager.cancel_all_open_orders(config["symbol"])
            time.sleep(10)
        except Exception as e:
            pass
        logging.info("finish cancel_all_open_orders")

        # ═══════════════════════════════════════════════════════════
        # 🚀 初始化阶段：确保做市订单和反针对订单挂好后才启动洗盘逻辑
        # ═══════════════════════════════════════════════════════════
        logging.info("=" * 70)
        logging.info("🚀 开始初始化阶段")
        logging.info("=" * 70)
        
        # 设置初始化标志为 False（通过 Redis 共享给其他线程）
        strategy_name = config.get("strategy_name", "unknown")
        r = redis.StrictRedis(host="localhost", port=6379, db=0, decode_responses=True)
        r.set(f"initialized:{strategy_name}", "false")
        logging.info(f"✅ 初始化标志已设置为 false (strategy={strategy_name})")
        
        try:
            # Step 1: 挂初始做市订单
            logging.info("📝 Step 1: 挂初始做市订单...")
            logging.info(f"   策略: {strategy_name}, 交易对: {config['symbol']}")
            
            market_maker.place_orders(
                config,
                symbol=config["symbol"],
                env=config["env"],
                currencies=config["currencies"],
                prec=config["precision"],
            )
            
            logging.info("⏳ 等待5秒让订单挂单...")
            time.sleep(5)
            logging.info("✅ 初始做市订单下单完成")
            
            # Step 2: 验证订单挂单状态
            logging.info("📝 Step 2: 验证订单挂单状态...")
            
            # 获取最新订单状态
            market_maker.order_manager.reset_open_orders(config["symbol"])
            open_orders = market_maker.order_manager.open_orders  # 直接访问属性
            
            if open_orders and len(open_orders) > 0:
                logging.info(f"✅ 当前活跃订单数: {len(open_orders)}")
                # 显示前5个订单ID示例
                sample_order_ids = list(open_orders.keys())[:5]
                logging.info(f"   - 示例订单ID: {sample_order_ids}")
                
                # 统计买卖订单数量
                buy_count = sum(1 for order in open_orders.values() if order.get('side') == 'BUY')
                sell_count = sum(1 for order in open_orders.values() if order.get('side') == 'SELL')
                logging.info(f"   - 买单: {buy_count}, 卖单: {sell_count}")
            else:
                logging.warning("⚠️ 未检测到活跃订单")
                logging.warning("   可能原因: 1) 订单被秒成交 2) API延迟 3) 网络问题")
                logging.warning("   系统将继续初始化，但建议检查订单状态")
            
            # Step 3: 设置初始化完成标志
            logging.info("📝 Step 3: 设置初始化完成标志...")
            r.set(f"initialized:{strategy_name}", "true")
            logging.info("✅ 初始化完成！洗盘逻辑现在可以启动")
            
        except Exception as e:
            logging.error(f"❌ 初始化阶段失败: {e}")
            logging.warning("继续运行主循环，但洗盘逻辑将等待初始化完成")
            r.set(f"initialized:{strategy_name}", "false")
        
        logging.info("=" * 70)
        logging.info("🎯 进入主循环")
        logging.info("=" * 70)

        while True:
            try:
                time.sleep(config.get("sleep_interval", 1))

                # 更新活跃状态
                if stability_monitor:
                    stability_monitor.update_last_active()

                # ✅ 风险监控：每次循环更新风险等级
                if config["Enable_risk_controller"]:
                    try:
                        # 将depth传递给risk_monitor，避免重复API调用
                        risk_controller.risk_monitor(symbol=config["symbol"], depth_data=depth)
                        logging.info(f"风险等级: {risk_controller.risk_level}")

                        # 📊 记录风险等级指标
                        if metrics_collector:
                            metrics_collector.record_risk_level(
                                risk_controller.risk_level,
                                strategy_name
                            )
                    except (IndexError, Exception) as e:
                        logging.warning(f"风险监控失败: {e}")
                        # 保持当前风险等级，继续运行

                # 止损功能已禁用 - 如需启用请参考 git history

                # ✅ 风险等级检查：根据风险等级决定是否继续交易
                if not market_maker.order_manager.risk_actions(risk_controller.risk_level, symbol=config["symbol"]):
                    logging.warning(f"风险等级 {risk_controller.risk_level} 过高，暂停市场做市")
                    continue

                market_maker.place_orders(
                    config,
                    symbol=config["symbol"],
                    env=config["env"],
                    currencies=config["currencies"],
                    prec=config["precision"],
                )

                market_maker.order_manager.reset_open_orders(config["symbol"])

            except Exception as e:
                logging.error(f"主循环异常: {e}")
                if stability_monitor:
                    stability_monitor.record_api_call(success=False)
                # 短暂休息后继续
                time.sleep(5)


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


# 使用共享的配置加载模块
from etf.config.loader import (
    load_strategy_config,
    get_available_strategies,
)


def get_parser():
    # 动态获取可用策略
    available_strategies = get_available_strategies()
    
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # 新增策略相关参数 - 动态从配置文件读取
    parser.add_argument(
        "--strategy",
        type=str,
        choices=available_strategies,
        help=f"Use predefined strategy from config file. Available: {', '.join(available_strategies)}",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/strategies.yaml",
        help="Path to strategy config file.",
    )

    parser.add_argument(
        "--prefix",
        type=str,
        default="stg5s",
        help="Prefix for the symbol (e.g., 'stg5s').",
    )
    parser.add_argument(
        "--env", type=str, default="prod", choices=["qa", "uat", "prod"], help="Environment."
    )
    parser.add_argument(
        "--client-order-id", type=str, default="1655", help="Client order ID."
    )
    parser.add_argument(
        "--apikey", type=str, default="", help="Deprecated, use .env file instead."
    )
    parser.add_argument(
        "--enable-risk-controller",
        type=str2bool,
        default=False,
        help="Enable risk controller.",
    )
    parser.add_argument(
        "--enable-wash-trading",
        type=str2bool,
        default=True,
        help="Enable wash trading.",
    )
    parser.add_argument(
        "--enable-hedging", type=str2bool, default=False, help="Enable hedging."
    )
    parser.add_argument(
        "--enable-market-making",
        type=str2bool,
        default=True,
        help="Enable market making.",
    )
    parser.add_argument(
        "--cancel-all-open-orders",
        type=str2bool,
        default=False,
        help="Cancel all open orders on start.",
    )
    parser.add_argument(
        "--exit-with-cancel-all-open-orders",
        type=str2bool,
        default=True,
        help="Cancel all open orders before exit.",
    )
    # ❌ --pre-make-orders 参数已废弃 (2025-11-21)
    # parser.add_argument(
    #     "--pre-make-orders",
    #     type=str2bool,
    #     default=False,
    #     help="Make pre-orders before market making.",
    # )
    parser.add_argument(
        "--hedging-interval", type=int, default=20, help="Hedging interval in seconds."
    )
    parser.add_argument(
        "--washing-lambda", type=int, default=10, help="Washing base interval in seconds (default: 10)."
    )
    parser.add_argument(
        "--kline-continuity-interval",
        type=int,
        default=60,
        help="Kline continuity check interval in seconds.",
    )
    parser.add_argument("--precision", type=int, default=6, help="Precision for price.")
    parser.add_argument(
        "--prec-amount", type=int, default=2, help="Precision for amount."
    )
    parser.add_argument(
        "--precision-amount", type=int, default=0, help="Override precision for amount."
    )
    parser.add_argument(
        "--precision-price", type=int, default=4, help="Override precision for price."
    )
    parser.add_argument(
        "--leverage", type=int, default=5, help="Leverage for the position."
    )
    parser.add_argument(
        "--wash", type=str, default="mid_price", help="Wash trading reference price."
    )
    parser.add_argument(
        "--anti-pin-usdt",
        type=float,
        default=300,
        help="USDT threshold for anti-pin mechanism.",
    )
    parser.add_argument(
        "--anti-pin-rate", type=float, default=0.2, help="Rate for anti-pin mechanism."
    )
    parser.add_argument(
        "--bid-ask-spread",
        type=float,
        default=0.05,
        help="Bid-ask spread for market making.",
    )
    parser.add_argument(
        "--sleep-interval",
        type=int,
        default=None,
        help="Main loop sleep interval in seconds.",
    )

    return parser


def log_startup(strategy_name: str, config: dict):
    """记录程序启动日志（替代告警）"""
    logging.info("=" * 70)
    logging.info(f"✅ 策略启动: {strategy_name}")
    logging.info(f"   环境: {config.get('env', 'unknown')}")
    logging.info(f"   交易对: {config.get('symbol', 'unknown')}")
    logging.info(f"   杠杆: {config.get('leverage', 'unknown')}x")
    logging.info(f"   对冲功能: {'启用' if config.get('Enable_hedging', False) else '禁用'}")
    logging.info(f"   刷量功能: {'启用' if config.get('Enable_wash_trading', False) else '禁用'}")
    logging.info(f"   风控功能: {'启用' if config.get('Enable_risk_controller', False) else '禁用'}")
    logging.info("=" * 70)


def log_shutdown(strategy_name: str, config: dict, reason: str = "正常退出"):
    """记录程序停止日志（替代告警）"""
    logging.info("=" * 70)
    logging.info(f"🛑 策略停止: {strategy_name}")
    logging.info(f"   原因: {reason}")
    logging.info(f"   交易对: {config.get('symbol', 'unknown')}")
    logging.info("=" * 70)


def main():
    """ETF 策略主入口函数，支持 uvx 直接调用"""
    parser = get_parser()
    args = parser.parse_args()

    # 如果指定了策略，先加载策略配置
    if args.strategy:
        strategy_config = load_strategy_config(args.strategy, args.config)
        # 使用策略配置中的 prefix
        prefix = strategy_config.get("prefix", args.prefix)
        logging.info(f"Loading strategy {args.strategy} with prefix {prefix}")
    else:
        strategy_config = {}
        prefix = args.prefix

    # 构建配置，策略配置作为默认值，命令行参数优先
    config = {
        "env": args.env
        if args.env != parser.get_default("env")
        else strategy_config.get("env", args.env),
        "clientOrderId": args.client_order_id
        if args.client_order_id != parser.get_default("client_order_id")
        else strategy_config.get("clientOrderId", args.client_order_id),
        "symbol": prefix + "_usdt",
        "netvalue": "netvalue_" + prefix,
        "bnsymbol": prefix.upper()[:-2] + "USDT"
        if prefix
        else strategy_config.get("bnsymbol", "STGUSDT"),
        "precision": args.precision
        if args.precision != parser.get_default("precision")
        else strategy_config.get("precision", args.precision),
        "prec_amount": args.prec_amount
        if args.prec_amount != parser.get_default("prec_amount")
        else strategy_config.get("prec_amount", args.prec_amount),
        "Hedging_interval": args.hedging_interval
        if args.hedging_interval != parser.get_default("hedging_interval")
        else strategy_config.get("Hedging_interval", args.hedging_interval),
        "washing_lambda": args.washing_lambda
        if args.washing_lambda != parser.get_default("washing_lambda")
        else strategy_config.get("washing_lambda", args.washing_lambda),
        "kline_continuity_interval": args.kline_continuity_interval
        if args.kline_continuity_interval
        != parser.get_default("kline_continuity_interval")
        else strategy_config.get(
            "kline_continuity_interval", args.kline_continuity_interval
        ),
        "Enable_risk_controller": args.enable_risk_controller
        if args.enable_risk_controller != parser.get_default("enable_risk_controller")
        else strategy_config.get("Enable_risk_controller", args.enable_risk_controller),
        "Enable_wash_trading": args.enable_wash_trading
        if args.enable_wash_trading != parser.get_default("enable_wash_trading")
        else strategy_config.get("Enable_wash_trading", args.enable_wash_trading),
        "leverage": args.leverage
        if args.leverage != parser.get_default("leverage")
        else strategy_config.get("leverage", args.leverage),
        "precision_amount": args.precision_amount
        if args.precision_amount != parser.get_default("precision_amount")
        else strategy_config.get("precision_amount", args.precision_amount),
        "precision_price": args.precision_price
        if args.precision_price != parser.get_default("precision_price")
        else strategy_config.get("precision_price", args.precision_price),
        "Enable_hedging": args.enable_hedging
        if args.enable_hedging != parser.get_default("enable_hedging")
        else strategy_config.get("Enable_hedging", args.enable_hedging),
        "wash": args.wash
        if args.wash != parser.get_default("wash")
        else strategy_config.get("wash", args.wash),
        "anti_pin_usdt": args.anti_pin_usdt
        if args.anti_pin_usdt != parser.get_default("anti_pin_usdt")
        else strategy_config.get("anti_pin_usdt", args.anti_pin_usdt),
        "anti_pin_rate": args.anti_pin_rate
        if args.anti_pin_rate != parser.get_default("anti_pin_rate")
        else strategy_config.get("anti_pin_rate", args.anti_pin_rate),
        "Enable_market_making": args.enable_market_making
        if args.enable_market_making != parser.get_default("enable_market_making")
        else strategy_config.get("Enable_market_making", args.enable_market_making),
        "bid_ask_spread": args.bid_ask_spread
        if args.bid_ask_spread != parser.get_default("bid_ask_spread")
        else strategy_config.get("bid_ask_spread", args.bid_ask_spread),
        "sleep_interval": args.sleep_interval
        if args.sleep_interval is not None
        else strategy_config.get("sleep_interval", 1),
    }

    # 添加 currencies 从策略配置
    if "currencies" in strategy_config:
        config["currencies"] = strategy_config["currencies"]

    # ✅ 添加订单簿算法配置（重要！）
    if "orderbook_algorithm" in strategy_config:
        config["orderbook_algorithm"] = strategy_config["orderbook_algorithm"]
    if "orderbook_config" in strategy_config:
        config["orderbook_config"] = strategy_config["orderbook_config"]

    # ✅ 添加 Maintainer 订单簿维护配置（重要！）
    if "orderbook_maintainer" in strategy_config:
        config["orderbook_maintainer"] = strategy_config["orderbook_maintainer"]

    # 添加策略名称用于特殊处理
    if args.strategy:
        config["strategy_name"] = args.strategy

    if config["env"] in ("qa", "uat"):
        # QA/UAT 环境从 .env 文件读取 API 密钥
        import os
        from pathlib import Path
        from dotenv import load_dotenv

        # 显式查找 .env 文件
        cwd = Path.cwd()
        env_file = cwd / ".env"

        if env_file.exists():
            load_dotenv(env_file)
            logging.info(f"✅ 已加载 .env 文件: {env_file}")
        else:
            # 尝试从当前目录向上查找
            load_dotenv()  # 使用默认查找
            logging.warning(f"⚠️ 当前目录 {cwd} 未找到 .env 文件，使用默认查找")

        access_key = os.getenv("access_key")
        secret_key = os.getenv("secret_key")

        env_name = config["env"].upper()
        if not access_key or not secret_key:
            logging.error("=" * 70)
            logging.error(f"🚨 错误: 未能从 .env 文件读取 API 密钥!")
            logging.error(f"   当前工作目录: {cwd}")
            logging.error(f"   .env 文件路径: {env_file}")
            logging.error(f"   .env 文件存在: {env_file.exists()}")
            logging.error("=" * 70)
            logging.error("请确保 .env 文件包含以下内容:")
            logging.error("   access_key=your_access_key")
            logging.error("   secret_key=your_secret_key")
            logging.error("=" * 70)
            raise RuntimeError(f"{env_name} 环境需要 .env 文件中的 API 密钥")

        # 根据环境选择 API 主机
        if config["env"] == "qa":
            api_host = "https://sapi.xt-qa2.com"  # XT QA2 测试环境
        else:  # uat
            api_host = "https://sapi.xt-uat.com"  # XT UAT 测试环境

        spot = Spot(
            host=api_host,
            access_key=access_key,
            secret_key=secret_key,
        )
        logging.info(f"✅ {env_name} 环境 API 密钥已加载 (access_key: {access_key[:4]}..., host: {api_host})")

    else:  # prod 环境
        # 生产环境也从 .env 文件或环境变量读取 API 密钥
        import os
        from pathlib import Path
        from dotenv import load_dotenv

        # 显式查找 .env 文件
        cwd = Path.cwd()
        env_file = cwd / ".env"

        if env_file.exists():
            load_dotenv(env_file)
            logging.info(f"✅ 已加载 .env 文件: {env_file}")
        else:
            load_dotenv()

        access_key = os.getenv("access_key")
        secret_key = os.getenv("secret_key")

        if not access_key or not secret_key:
            logging.error("=" * 70)
            logging.error("🚨 错误: 未能从环境变量读取 API 密钥!")
            logging.error(f"   当前工作目录: {cwd}")
            logging.error("=" * 70)
            logging.error("请配置 API 密钥:")
            logging.error("  1. 在 .env 文件中设置: access_key=xxx 和 secret_key=xxx")
            logging.error("  2. 或设置环境变量: export access_key=xxx && export secret_key=xxx")
            logging.error("=" * 70)
            raise RuntimeError("API 密钥未配置，程序已终止")

        spot = Spot(
            host="https://sapi.xt.com",
            access_key=access_key,
            secret_key=secret_key,
        )
        logging.info(f"✅ 生产环境 API 密钥已加载 (access_key: {access_key[:4]}...)")

    # risk related
    risk_params = {
        "volatility_levels": 1,
        "price_deviation_threshold": [0.02, 0.05, 0.1],
        "base_ask_volume": 50,
        "base_bid_volume": 50,
        "orderbook_threshold": [0.8, 0.5, 0.2],
    }
    
    # 添加止损配置（如果在策略配置中存在）
    if "stop_loss" in strategy_config:
        risk_params["stop_loss"] = strategy_config["stop_loss"]

    # 定义策略名称（在使用前定义）
    strategy_name = config.get("strategy_name", config.get("prefix", "unknown"))

    # ===== 初始化完整日志配置 =====
    # 现在策略名称已确定，配置专业的日志系统（文件 + 控制台）
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level_value = getattr(logging, log_level, logging.INFO)

    setup_logging(
        strategy_name=strategy_name,
        log_level=log_level_value,
        log_dir="logs",
        enable_console=True,
        enable_file=True,
        enable_error_file=True,
        max_bytes=10 * 1024 * 1024,  # 10MB
        backup_count=7,
        retention_days=30,
    )

    # ===== 初始化 Prometheus 可观测性（Pull 模式）=====
    prometheus_server = None
    metrics_collector = None

    try:
        # 读取配置
        enable_metrics = os.getenv("ENABLE_METRICS", "true").lower() == "true"
        metrics_mode = os.getenv("METRICS_EXPORT_MODE", "prometheus")  # prometheus | otlp
        prometheus_port = int(os.getenv("PROMETHEUS_PORT", "8000"))

        if enable_metrics:
            if metrics_mode == "prometheus":
                # Prometheus Pull 模式（推荐）
                registry, _ = init_otel(
                    service_name=f"etf-{strategy_name}",
                    export_mode="prometheus",
                    prometheus_port=prometheus_port,
                    environment=config.get("env", "production")
                )

                # 创建 MetricsCollector
                metrics_collector = MetricsCollector(registry)

                # 启动 Prometheus HTTP 服务器
                prometheus_server = PrometheusServer(
                    port=prometheus_port,
                    addr='0.0.0.0',
                    registry=registry
                )

                if prometheus_server.start():
                    logging.info(f"✅ Prometheus 初始化成功")
                    logging.info(f"   Metrics 端点: {prometheus_server.get_metrics_url()}")
                    logging.info(f"   提示: 在 Prometheus 配置中添加:")
                    logging.info(f"     - targets: ['localhost:{prometheus_port}']")
                else:
                    logging.error("❌ Prometheus HTTP 服务器启动失败")
                    prometheus_server = None

            elif metrics_mode == "otlp":
                # OTLP Push 模式（兼容旧版）
                logging.warning("⚠️  使用 OTLP Push 模式（不推荐）")
                otlp_endpoint = os.getenv("OTLP_ENDPOINT", "http://localhost:4317")

                _, _ = init_otel(
                    service_name=f"etf-{strategy_name}",
                    otlp_endpoint=otlp_endpoint,
                    export_mode="otlp",
                    enable_traces=False,
                    export_interval_ms=10000,
                    environment=config.get("env", "production")
                )

                # 注意：OTLP 模式下需要使用旧的 MetricsCollector 初始化方式
                from opentelemetry import metrics as otel_metrics
                meter = otel_metrics.get_meter(f"etf-{strategy_name}")
                metrics_collector = MetricsCollector(meter)

                logging.info(f"✅ OTLP 初始化成功: endpoint={otlp_endpoint}")
                logging.warning("   建议迁移到 Prometheus 模式：METRICS_EXPORT_MODE=prometheus")
            else:
                logging.error(f"❌ 不支持的 Metrics 导出模式: {metrics_mode}")
        else:
            logging.info("⏸️ Metrics 已禁用 (ENABLE_METRICS=false)")

    except Exception as e:
        logging.error(f"❌ Metrics 初始化失败: {e}")
        logging.warning("系统将继续运行，但不会导出 Metrics")
        logging.exception(e)
        metrics_collector = None
        prometheus_server = None

    # ===== 初始化 WebSocket 客户端（用于实时depth数据） =====
    ws_client = None
    try:
        # 根据环境选择 WebSocket URL
        if config["env"] == "qa":
            ws_url = "wss://stream.xt-qa2.com/public"  # QA2 测试环境
        elif config["env"] == "uat":
            ws_url = "wss://stream.xt-uat.com/public"  # UAT 测试环境
        else:
            ws_url = "wss://stream.xt.com/public"      # 生产环境

        # XT public WebSocket 不需要认证，直接连接
        ws_client = XTWebSocketClient(
            symbol=config["symbol"],
            ws_url=ws_url  # ✅ 传递环境相关的 URL
        )
        ws_client.start()
        logging.info(f"✅ WebSocket客户端已启动: {config['symbol']} @ {ws_url}")

        # 等待WebSocket连接建立（最多5秒）
        for i in range(10):
            if ws_client.is_connected():
                logging.info("✅ WebSocket连接成功")
                break
            time.sleep(0.5)
        else:
            logging.warning("WebSocket连接未在5秒内建立，将fallback到REST API")
    except Exception as e:
        logging.warning(f"WebSocket初始化失败: {e}，将使用REST API")
        ws_client = None

    # ===== 初始化 Symbol 配置管理器（用于动态获取精度配置） =====
    # 🔴 关键：精度配置必须从交易所API获取，失败则退出程序
    symbol_config_manager = None
    try:
        symbol_config_manager = SymbolConfigManager(
            spot_client=spot,
            refresh_interval=3600  # 每小时刷新一次配置
        )

        # 加载当前交易对的配置
        if symbol_config_manager.load_symbol_config(config["symbol"]):
            logging.info(f"✅ Symbol配置管理器初始化成功: {config['symbol']}")

            # 启动自动刷新线程
            symbol_config_manager.start_auto_refresh()
            logging.info("✅ Symbol配置自动刷新已启动")
        else:
            logging.critical(f"❌ 无法加载 {config['symbol']} 的精度配置！程序无法继续")
            logging.critical("请检查: 1. 交易所API是否可访问  2. 交易对名称是否正确")
            sys.exit(1)
    except Exception as e:
        logging.critical(f"❌ Symbol配置管理器初始化失败: {e}")
        logging.critical("精度配置是交易的关键参数，程序无法继续运行")
        sys.exit(1)

    logging.info("run RiskController")
    risk_controller = RiskController(spot, risk_params, strategy_name=strategy_name, ws_client=ws_client)
    depth = None  # 初始化 depth 变量，用于复用避免 API 限流
    if config["Enable_risk_controller"]:
        try:
            risk_controller.risk_monitor(symbol=config["symbol"])
            depth = risk_controller.depth  # 保存获取到的 depth 数据
            logging.info(f"初始风险等级: {risk_controller.risk_level}")
        except (IndexError, Exception) as e:
            logging.warning(f"启动时风险监控失败（可能是空订单簿）: {e}")
            logging.info("使用默认风险等级，主循环中将继续监控")

    # market maker related
    # 传递策略名称和Symbol配置管理器给 OrderManager
    # 从配置中读取订单档位数量（layer），默认200（避免ORDER_006挂单过多错误）
    tier = config.get("orderbook_config", {}).get("layer", 200)
    # ✅ OrderManager 默认启用订单/成交 WebSocket 推送
    # 这样才能触发 _on_trade() 回调，记录成交到 trades 表
    order_manager = OrderManager(
        spot,
        strategy_name=strategy_name,
        symbol_config=symbol_config_manager,
        tier=tier
    )
    
    # 启用资金检查（如果配置中启用）
    balance_check_config = config.get("balance_check", {})
    if balance_check_config.get("enabled", False):
        order_manager.enable_balance_check(
            warning_threshold=balance_check_config.get("warning_threshold", 0.3),
            critical_threshold=balance_check_config.get("critical_threshold", 0.2),
            insufficient_threshold=balance_check_config.get("insufficient_threshold", 0.1),
            check_interval=balance_check_config.get("check_interval", 60),
        )
        logging.info(f"✅ [{strategy_name}] 资金检查已启用")
    else:
        logging.info(f"ℹ️ [{strategy_name}] 资金检查未启用")
    
    # 初始化稳定性监控
    stability_monitor = StabilityMonitor(strategy_name=strategy_name, check_interval=60)
    # TODO: stability_monitor.start_monitoring() 需要异步事件循环
    # 暂时只使用同步方法（update_last_active, record_api_call等）
    # 完整的异步监控将在 Phase 2 实现
    logging.info("稳定性监控器已初始化（仅同步模式）")

    # 记录启动日志（替代告警）
    log_startup(strategy_name, config)
    
    # 注册退出处理函数
    def cleanup():
        """清理函数，在程序退出时执行"""
        try:
            logging.info("=" * 70)
            logging.info("🛑 开始执行程序退出流程")
            logging.info("=" * 70)
            
            # ✅ 步骤1: 停止洗盘交易（优先级最高）
            if config.get("Enable_wash_trading", False):
                try:
                    # 尝试访问 wash_controller（如果已创建）
                    if 'wash_controller' in dir():
                        logging.info("🛑 步骤1: 停止洗盘交易控制器...")
                        success = wash_controller.stop(wait_timeout=60)
                        if success:
                            logging.info("✅ 洗盘交易已安全停止")
                        else:
                            logging.warning("⚠️ 洗盘交易停止超时，但已设置停止标志")
                    else:
                        logging.info("ℹ️ 洗盘交易控制器未创建，跳过停止步骤")
                except Exception as e:
                    logging.error(f"停止洗盘交易失败: {e}")
            
            # 清理初始化标志
            try:
                r = redis.StrictRedis(host="localhost", port=6379, db=0, decode_responses=True)
                r.delete(f"initialized:{strategy_name}")
                logging.info(f"✅ 已清理初始化标志: initialized:{strategy_name}")
            except Exception as e:
                logging.error(f"清理初始化标志失败: {e}")
            
            # 停止Symbol配置管理器
            if symbol_config_manager:
                try:
                    symbol_config_manager.stop_auto_refresh()
                    logging.info("✅ Symbol配置管理器已停止")
                except Exception as e:
                    logging.error(f"停止Symbol配置管理器失败: {e}")

            # 停止WebSocket连接
            if ws_client:
                try:
                    ws_client.stop()
                    logging.info("✅ WebSocket连接已关闭")
                except Exception as e:
                    logging.error(f"关闭WebSocket失败: {e}")

            # 停止稳定性监控
            if 'stability_monitor' in locals():
                stability_monitor.stop_monitoring()
                logging.info("✅ 稳定性监控已停止")

            # 记录停止日志（替代告警）
            log_shutdown(strategy_name, config)

            # ✅ 步骤2: 根据环境变量决定是否撤单
            logging.info("🛑 步骤2: 撤销所有挂单 (CANCEL_ORDERS_ON_EXIT=true)")
            try:
                order_manager.cancel_all_open_orders(config["symbol"])
                logging.info("✅ 已撤销所有挂单")
            except Exception as e:
                logging.error(f"撤销挂单失败: {e}")

            logging.info("=" * 70)
            logging.info("✅ 程序退出流程完成")
            logging.info("=" * 70)

        except Exception as e:
            logging.error(f"清理过程出错: {e}")
            
    atexit.register(cleanup)

    # 初始化余额（在单独的策略文件中有，但在原始 run_etf.py 中被注释）
    # 只有在使用策略模式时才启用，以保持向后兼容
    if args.strategy and "currencies" in config:
        info = order_manager.client.balances(config["currencies"])
        logging.info(info)
        
        # 安全地获取余额，处理空资产列表的情况
        target_currency = config["symbol"].split("_")[1].lower()
        matching_amounts = [
            float(currency["totalAmount"])
            for currency in info.get("assets", [])
            if currency.get("currency") == target_currency
        ]
        
        if matching_amounts:
            last_amount = matching_amounts[0]
        else:
            logging.warning(
                f"未找到货币 {target_currency} 的余额，assets: {info.get('assets', [])}，使用默认值 0"
            )
            last_amount = 0.0
        
        order_manager.init_amount = last_amount
        order_manager.last_amount = last_amount
        print(
            f"init market making {config['symbol']} amount {order_manager.last_amount}"
        )
    if order_manager.risk_actions(risk_controller.risk_level, symbol=config["symbol"]):
        market_maker = MarketMaker(order_manager, symbol_config_manager=symbol_config_manager)
        
        # ✅ 初始化 Maintainer（如果启用）
        maintainer_config = config.get("orderbook_maintainer", {})
        logging.debug(f"📋 Maintainer 配置: enabled={maintainer_config.get('enabled', False)}, "
                     f"spread={maintainer_config.get('spread')}, "
                     f"total_budget={maintainer_config.get('total_budget')}, "
                     f"near_layer={maintainer_config.get('near_layer', {}).get('order_count')}")
        if maintainer_config.get("enabled", False):
            market_maker.init_maintainer(
                config=maintainer_config,
                symbol=config["symbol"],
                strategy_name=config.get("strategy_name", "unknown"),
            )
            logging.info(f"✅ Maintainer 初始化完成: {config['symbol']}")
        
        wash_controller = WashController(order_manager, market_maker, symbol_config_manager=symbol_config_manager)
        
        # ✅ 初始化洗盘订单追踪器（检测和处理孤儿订单）
        wash_order_check_interval = config.get("wash_order_check_interval", 5.0)
        wash_order_max_wait = config.get("wash_order_max_wait", 30.0)
        wash_controller.init_order_tracker(
            client=order_manager.client,
            check_interval=wash_order_check_interval,
            max_wait_time=wash_order_max_wait
        )

        # 复用之前获取的 depth，避免短时间内重复 API 调用触发限流
        if depth is None:
            try:
                depth = risk_controller.get_depth_data(config["symbol"])
            except Exception as e:
                logging.warning(f"获取 depth 失败: {e}，使用空 depth")
                depth = {"bids": [], "asks": []}
        logging.info(depth)

        # ═══════════════════════════════════════════════════════════
        # 对冲系统初始化
        # ═══════════════════════════════════════════════════════════
        hedge_orchestrator = None
        if config.get("Enable_hedging", False):
            hedging_config = config.get("hedging", {})
            if hedging_config.get("enabled", False):
                # 使用新版模块化对冲系统
                try:
                    from etf.binance_client import BinanceClient
                    from etf.config import load_binance_api_keys

                    bn_keys = load_binance_api_keys()
                    bn_client = BinanceClient(bn_keys["access_key"], bn_keys["secret_key"])

                    hedge_orchestrator = create_hedge_orchestrator(
                        client=bn_client,
                        config=hedging_config,
                        symbol=config.get("bnsymbol", "TONUSDT"),
                        leverage=config.get("leverage", 3),
                    )
                    logging.info(f"✅ 新版对冲系统初始化完成: {hedge_orchestrator.get_status()}")
                except Exception as e:
                    logging.error(f"❌ 新版对冲系统初始化失败: {e}")
                    hedge_orchestrator = None
            else:
                # 使用旧版对冲（向后兼容）
                logging.info("使用旧版对冲系统（向后兼容模式）")
                hedging = Hedge()

        # thread2 = threading.Thread(target=EtfStrategy.run, args=(config, risk_controller, wash_controller, market_maker))
        if config["Enable_hedging"] and hedge_orchestrator is None:
            # 旧版对冲线程
            hedging = Hedge()
            thread3 = threading.Thread(
                target=hedging.run, args=(order_manager, config), daemon=True
            )
        if config["Enable_wash_trading"]:
            thread4 = threading.Thread(
                target=wash_controller.run, args=(risk_controller, config), daemon=True
            )

        # thread2.start()
        if config["Enable_hedging"] and hedge_orchestrator is None:
            thread3.start()
        if config["Enable_wash_trading"]:
            thread4.start()

        # 新版对冲系统异步运行
        if hedge_orchestrator is not None:
            async def run_hedge_loop():
                """对冲主循环"""
                interval = config.get("hedging", {}).get("interval", 20)
                logging.info(f"🔄 新版对冲系统启动，检查间隔: {interval}s")

                while True:
                    try:
                        # 从 order_manager 获取持仓变化
                        xt_delta = order_manager.get_position_delta() if hasattr(order_manager, 'get_position_delta') else 0

                        if xt_delta != 0:
                            from decimal import Decimal
                            result = await hedge_orchestrator.check_and_hedge(
                                xt_position_delta=Decimal(str(xt_delta)),
                            )
                            if result:
                                logging.info(f"对冲执行结果: {result.to_dict()}")

                        await asyncio.sleep(interval)
                    except Exception as e:
                        logging.error(f"对冲循环异常: {e}")
                        await asyncio.sleep(interval)

            # 在单独线程中运行异步对冲循环
            def start_hedge_loop():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(run_hedge_loop())

            hedge_thread = threading.Thread(target=start_hedge_loop, daemon=True)
            hedge_thread.start()
            logging.info("✅ 新版对冲线程已启动")

        # thread2.join()
        # if config["Enable_hedging"]:
        #     thread3.join()
        # if config["Enable_wash_trading"]:
        #     thread4.join()
        if config["Enable_market_making"]:
            # 传递 depth 参数，避免在 run 方法中重复调用 API
            EtfStrategy.run(config, risk_controller, wash_controller, market_maker, stability_monitor, depth)
    else:
        logging.error(f"风险等级 {risk_controller.risk_level} 过高，无法启动策略")
        sys.exit(1)


if __name__ == "__main__":
    main()
