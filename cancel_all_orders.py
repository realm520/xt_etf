"""
取消所有订单或下测试单的工具脚本

使用前请确保配置 .env 文件:
    access_key=xxx
    secret_key=xxx
"""
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
from etf.xt import Spot
from etf.order_manager import OrderManager


def load_api_keys():
    """从 .env 或环境变量加载 API 密钥"""
    # 显式从当前工作目录加载 .env 文件
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
    
    access_key = os.getenv("access_key")
    secret_key = os.getenv("secret_key")
    
    if not access_key or not secret_key:
        raise ValueError(
            "未找到 API 密钥。请配置：\n"
            "  1. 在 .env 文件中设置: access_key=xxx 和 secret_key=xxx\n"
            "  2. 或设置环境变量: export access_key=xxx && export secret_key=xxx"
        )
    
    return access_key, secret_key


if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='取消指定交易对的所有订单或下测试单')
    parser.add_argument('--symbol', type=str, default='stt5l_usdt',
                       help='交易对名称 (默认: stt5l_usdt)')
    parser.add_argument('--action', type=str, default='test_order',
                       choices=['cancel_all', 'test_order'],
                       help='操作类型: cancel_all=取消所有订单, test_order=下测试单 (默认: test_order)')
    parser.add_argument('--price', type=float, default=1.0,
                       help='测试订单价格 (默认: 1.0)')
    parser.add_argument('--quantity', type=float, default=10.0,
                       help='测试订单数量 (默认: 10.0)')
    args = parser.parse_args()
    
    # 加载 API 密钥
    access_key, secret_key = load_api_keys()
    
    spot = Spot(
        host="https://sapi.xt.com",
        access_key=access_key,
        secret_key=secret_key
    )

    order_manager = OrderManager(spot)

    # 根据action参数执行不同操作
    if args.action == 'cancel_all':
        print(f"取消 {args.symbol} 的所有订单...")
        order_manager.cancel_all_open_orders(args.symbol)
        print("完成!")
    else:  # test_order
        print(f"为 {args.symbol} 下测试单...")
        print(f"  价格: {args.price}, 数量: {args.quantity}")
        order_data = {
            "symbol": args.symbol,
            "clientOrderId": order_manager.create_temp_id(),
            "side": "SELL",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "bizType": "SPOT",
            "price": args.price,
            "quantity": args.quantity,
            "quoteQty": None
        }
        response = order_manager.add_orders_batch([order_data], batch_id=51232, order_purpose="manual")
        print(f"响应: {response}")
