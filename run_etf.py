from etf.risk import RiskController
from etf.washing import WashController
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.xt import Spot
from etf.stability_monitor import StabilityMonitor
from etf.websocket import XTWebSocketClient
from hedging import Hedge
from etf.observability import init_otel, MetricsCollector  # OpenTelemetry 集成
import json
import time
import logging
import threading
import atexit
import pandas as pd
import argparse
import yaml
import os
import asyncio

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

        if config["cancel_all_open_orders"]:
            logging.info("cancel_all_open_orders")
            # STG5S 特有的行为：先取消一次
            if (
                config.get("strategy_name") == "stg5s"
                or config.get("prefix") == "stg5s"
            ):
                order_manager.cancel_all_open_orders(config["symbol"])
            if len(depth["asks"]) != 0 or len(depth["bids"]) != 0:
                try:
                    order_manager.cancel_all_open_orders(config["symbol"])
                    time.sleep(10)
                except Exception as e:
                    pass
                columns = [
                    "price",
                    "quantity",
                    "orderId",
                    "time",
                    "UTC_PLUS_8",
                    "symbol",
                    "side",
                    "state",
                ]
                df = pd.DataFrame(columns=columns)
                df.to_csv(
                    market_maker.order_manager.open_orders_csv_file,
                    mode="w",
                    index=False,
                    header=True,
                )

                # STG5S 特有的日志
                if (
                    config.get("strategy_name") == "stg5s"
                    or config.get("prefix") == "stg5s"
                ):
                    logging.info("finish cancel_all_open_orders")
                # market_maker.make_orders(config["symbol"])
        else:
            logging.info("skip cancel_all_open_orders")

        if config["pre_make_orders"]:
            logging.info("pre_make_orders")
            if len(depth["asks"]) == 0 or len(depth["bids"]) == 0:
                market_maker.make_orders()
        else:
            logging.info("skip pre_make_orders")

        # try:

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

                # ✅ 持仓信息更新（用于止损计算）
                if risk_controller.stop_loss_manager and config.get("currencies"):
                    try:
                        # 获取当前持仓信息
                        delta_pos, position, mid_price, delta_amt = order_manager.get_position3(
                            config["symbol"], config["currencies"]
                        )

                        # 判断是否有持仓
                        if abs(delta_amt) > 0.01:  # 持仓量阈值
                            # 确定持仓方向（做多/做空）
                            # ETF命名规则: stg3l = 3倍做多, stg3s = 3倍做空
                            symbol_lower = config["symbol"].lower()
                            side = "short" if symbol_lower.endswith("s_usdt") else "long"

                            # 获取入场价格（使用初始金额计算平均入场价）
                            if order_manager.init_amount and order_manager.init_amount != 0:
                                entry_price = (position - order_manager.init_amount * mid_price) / delta_amt if delta_amt != 0 else mid_price
                            else:
                                entry_price = mid_price

                            # 更新止损管理器的持仓信息
                            risk_controller.update_position_for_stop_loss(
                                symbol=config["symbol"],
                                side=side,
                                amount=abs(delta_amt),
                                entry_price=abs(entry_price),
                                current_price=mid_price
                            )
                            logging.debug(f"止损管理器已更新: side={side}, amount={abs(delta_amt):.4f}, entry={abs(entry_price):.4f}, current={mid_price:.4f}")
                    except Exception as e:
                        logging.warning(f"更新止损信息失败: {e}")

                # ✅ 止损检查：异步检查是否触发止损
                if risk_controller.stop_loss_manager and risk_controller.is_stop_loss_active():
                    try:
                        # 创建新的事件循环来运行异步止损检查
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        stop_loss_result = loop.run_until_complete(
                            risk_controller.check_stop_loss(config["symbol"])
                        )
                        loop.close()

                        if stop_loss_result and stop_loss_result.triggered:
                            logging.error("=" * 70)
                            logging.error(f"🚨 止损触发: {stop_loss_result.reason}")
                            logging.error(f"亏损率: {stop_loss_result.loss_rate:.2%}")
                            logging.error(f"需要平仓数量: {stop_loss_result.position_to_close:.4f}")
                            logging.error(f"止损动作: {stop_loss_result.action.value}")
                            logging.error("=" * 70)

                            # 📊 记录止损触发指标
                            if metrics_collector:
                                metrics_collector.record_stop_loss(
                                    strategy_name,
                                    stop_loss_result.reason,
                                    stop_loss_result.loss_rate
                                )

                            # 执行止损操作：撤销所有订单
                            logging.warning("执行止损: 撤销所有挂单")
                            order_manager.cancel_all_open_orders(config["symbol"])

                            # 暂停交易一段时间（冷却期）
                            cooldown_time = risk_controller.stop_loss_manager.cooldown_minutes * 60
                            logging.warning(f"进入冷却期 {cooldown_time/60:.0f} 分钟，暂停交易")
                            time.sleep(10)  # 短暂暂停，让撤单生效
                            continue  # 跳过本轮交易

                    except Exception as e:
                        logging.error(f"止损检查失败: {e}")

                # ✅ 风险等级检查：根据风险等级决定是否继续交易
                if not order_manager.risk_actions(risk_controller.risk_level):
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


def load_strategy_config(strategy_name, config_file="config/strategies.yaml"):
    """加载策略配置文件"""
    if not os.path.exists(config_file):
        logging.warning(f"Config file {config_file} not found, using defaults")
        return {}

    try:
        with open(config_file, "r", encoding="utf8") as f:
            config_data = yaml.safe_load(f)

        if strategy_name in config_data.get("strategies", {}):
            return config_data["strategies"][strategy_name]
        else:
            logging.warning(f"Strategy {strategy_name} not found in config file")
            return {}
    except Exception as e:
        logging.error(f"Error loading config file: {e}")
        return {}


def get_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # 新增策略相关参数
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["stg3l", "stg3s", "stg5l", "stg5s"],
        help="Use predefined strategy from config file.",
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
        "--env", type=str, default="prod", choices=["qa", "prod"], help="Environment."
    )
    parser.add_argument(
        "--client-order-id", type=str, default="1655", help="Client order ID."
    )
    parser.add_argument(
        "--apikey", type=str, default="APIKey.json", help="Path to API key file."
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
    parser.add_argument(
        "--pre-make-orders",
        type=str2bool,
        default=False,
        help="Make pre-orders before market making.",
    )
    parser.add_argument(
        "--hedging-interval", type=int, default=20, help="Hedging interval in seconds."
    )
    parser.add_argument(
        "--washing-interval", type=int, default=1, help="Washing interval in seconds."
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


if __name__ == "__main__":
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
        "apikey": args.apikey
        if args.apikey != parser.get_default("apikey")
        else strategy_config.get("apikey", args.apikey),
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
        "washing_interval": args.washing_interval
        if args.washing_interval != parser.get_default("washing_interval")
        else strategy_config.get("washing_interval", args.washing_interval),
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
        "cancel_all_open_orders": args.cancel_all_open_orders
        if args.cancel_all_open_orders != parser.get_default("cancel_all_open_orders")
        else strategy_config.get("cancel_all_open_orders", args.cancel_all_open_orders),
        "pre_make_orders": args.pre_make_orders
        if args.pre_make_orders != parser.get_default("pre_make_orders")
        else strategy_config.get("pre_make_orders", args.pre_make_orders),
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
        "Exit_with_cancel_all_open_orders": args.exit_with_cancel_all_open_orders
        if args.exit_with_cancel_all_open_orders
        != parser.get_default("exit_with_cancel_all_open_orders")
        else strategy_config.get(
            "Exit_with_cancel_all_open_orders", args.exit_with_cancel_all_open_orders
        ),
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

    # 添加策略名称用于特殊处理
    if args.strategy:
        config["strategy_name"] = args.strategy

    if config["env"] == "qa":
        # QA 环境从 .env 文件读取 API 密钥
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        spot = Spot(
            host="https://sapi.xt-qa2.com",  # XT QA2 测试环境
            access_key=os.getenv("access_key"),
            secret_key=os.getenv("secret_key"),
        )

    elif config["env"] == "prod":
        # 使用安全的 API 密钥加载器 - 生产环境强制使用加密密钥
        from etf.utils.crypto import load_api_keys
        from pathlib import Path

        # 检查是否存在加密文件
        enc_file = Path(config["apikey"]).with_suffix('.enc')
        plain_file = Path(config["apikey"])

        if not enc_file.exists() and plain_file.exists():
            logging.error("=" * 70)
            logging.error("🚨 安全警告: 生产环境检测到明文 API 密钥!")
            logging.error(f"明文文件: {plain_file}")
            logging.error("=" * 70)
            logging.error("请立即执行以下步骤加密您的 API 密钥:")
            logging.error("1. 设置加密密码: export ETF_KEY_PASSWORD='your-secure-password'")
            logging.error("2. 运行加密脚本: python scripts/encrypt_apikeys.py")
            logging.error("3. 或使用命令: python -c \"from etf.utils.crypto import encrypt_api_keys; encrypt_api_keys('APIKey.json')\"")
            logging.error("=" * 70)
            logging.error("为了安全，程序将在 10 秒后退出...")
            logging.error("如需使用明文密钥（仅用于开发测试），请设置环境变量: ALLOW_PLAIN_KEYS=true")

            # 检查是否允许明文密钥（仅用于开发/测试）
            if os.environ.get("ALLOW_PLAIN_KEYS", "").lower() != "true":
                import time
                time.sleep(10)
                raise RuntimeError("生产环境禁止使用明文 API 密钥，程序已终止")
            else:
                logging.warning("检测到 ALLOW_PLAIN_KEYS=true，允许使用明文密钥（仅用于开发/测试）")

        try:
            apikey = load_api_keys(config["apikey"])
            spot = Spot(
                host="https://sapi.xt.com",
                access_key=apikey["xt_" + prefix]["access_key"],
                secret_key=apikey["xt_" + prefix]["secret_key"],
            )
        except FileNotFoundError:
            logging.error(f"错误: 找不到 API 密钥文件 {config['apikey']} 或对应的 .enc 文件")
            logging.error("请确保密钥文件存在并已正确加密")
            raise

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

    # ===== 初始化 OpenTelemetry 可观测性 =====
    try:
        otlp_endpoint = os.getenv("OTLP_ENDPOINT", "http://localhost:4317")
        enable_otel = os.getenv("ENABLE_OTEL", "true").lower() == "true"

        if enable_otel:
            meter = init_otel(
                service_name=f"etf-{strategy_name}",
                otlp_endpoint=otlp_endpoint,
                enable_metrics=True,
                enable_traces=False,  # Traces 可选
                export_interval_ms=10000,  # 10秒导出一次
                environment=config.get("env", "production")
            )
            metrics_collector = MetricsCollector(meter)
            logging.info(f"✅ OpenTelemetry 初始化成功: endpoint={otlp_endpoint}")
        else:
            metrics_collector = None
            logging.info("⏸️ OpenTelemetry 已禁用 (ENABLE_OTEL=false)")
    except Exception as e:
        logging.error(f"❌ OpenTelemetry 初始化失败: {e}")
        logging.warning("系统将继续运行，但不会导出 Metrics")
        metrics_collector = None

    # ===== 初始化 WebSocket 客户端（用于实时depth数据） =====
    ws_client = None
    enable_websocket = os.getenv("ENABLE_WEBSOCKET", "true").lower() == "true"

    if enable_websocket:
        try:
            # XT public WebSocket 不需要认证，直接连接
            ws_client = XTWebSocketClient(
                symbol=config["symbol"]
            )
            ws_client.start()
            logging.info(f"✅ WebSocket客户端已启动: {config['symbol']}")

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
    else:
        logging.info("⏸️ WebSocket已禁用 (ENABLE_WEBSOCKET=false)")

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
    # 传递策略名称给 OrderManager
    order_manager = OrderManager(spot, strategy_name=strategy_name)
    
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
            # 停止WebSocket连接
            if 'ws_client' in locals() and ws_client:
                try:
                    ws_client.stop()
                    logging.info("✅ WebSocket连接已关闭")
                except Exception as e:
                    logging.error(f"关闭WebSocket失败: {e}")

            # 停止稳定性监控
            if 'stability_monitor' in locals():
                stability_monitor.stop_monitoring()
                logging.info("稳定性监控已停止")

            # 记录停止日志（替代告警）
            log_shutdown(strategy_name, config)

            # 撤销所有挂单
            if config.get("Exit_with_cancel_all_open_orders", True):
                try:
                    order_manager.cancel_all_open_orders(config["symbol"])
                    logging.info("已撤销所有挂单")
                except Exception as e:
                    logging.error(f"撤销挂单失败: {e}")

        except Exception as e:
            logging.error(f"清理过程出错: {e}")
            
    atexit.register(cleanup)

    # 初始化余额（在单独的策略文件中有，但在原始 run_etf.py 中被注释）
    # 只有在使用策略模式时才启用，以保持向后兼容
    if args.strategy and "currencies" in config:
        info = order_manager.client.balances(config["currencies"])
        logging.info(info)
        last_amount = [
            float(currency["totalAmount"])
            for currency in info["assets"]
            if currency["currency"] == config["symbol"].split("_")[1].lower()
        ][0]
        order_manager.init_amount = last_amount
        order_manager.last_amount = last_amount
        print(
            f"init market making {config['symbol']} amount {order_manager.last_amount}"
        )
    if order_manager.risk_actions(risk_controller.risk_level):
        market_maker = MarketMaker(order_manager)
        wash_controller = WashController(order_manager, market_maker)

        # 复用之前获取的 depth，避免短时间内重复 API 调用触发限流
        if depth is None:
            try:
                depth = risk_controller.get_depth_data(config["symbol"])
            except Exception as e:
                logging.warning(f"获取 depth 失败: {e}，使用空 depth")
                depth = {"bids": [], "asks": []}
        logging.info(depth)

        # market_maker.make_orders(symbol=config["symbol"])
        hedging = Hedge()

    # thread2 = threading.Thread(target=EtfStrategy.run, args=(config, risk_controller, wash_controller, market_maker))
    if config["Enable_hedging"]:
        thread3 = threading.Thread(
            target=hedging.run, args=(order_manager, config), daemon=True
        )
    if config["Enable_wash_trading"]:
        thread4 = threading.Thread(
            target=wash_controller.run, args=(risk_controller, config), daemon=True
        )

    # thread2.start()
    if config["Enable_hedging"]:
        thread3.start()
    if config["Enable_wash_trading"]:
        thread4.start()

    # thread2.join()
    # if config["Enable_hedging"]:
    #     thread3.join()
    # if config["Enable_wash_trading"]:
    #     thread4.join()
    if config["Enable_market_making"]:
        # 传递 depth 参数，避免在 run 方法中重复调用 API
        EtfStrategy.run(config, risk_controller, wash_controller, market_maker, stability_monitor, depth)
