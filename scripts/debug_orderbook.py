#!/usr/bin/env python3
"""
订单簿调试工具 - 诊断订单簿数据获取问题

功能:
1. 测试WebSocket实时深度数据
2. 测试REST API深度查询
3. 对比两种数据源的差异
4. 检测数据完整性问题

使用:
    python scripts/debug_orderbook.py --symbol ton3s_usdt --env qa
    python scripts/debug_orderbook.py --symbol btc_usdt --env prod
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from etf.websocket.xt_websocket import XTWebSocketClient
from etf.xt import Spot

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OrderbookDebugger:
    """订单簿调试器"""
    
    def __init__(self, symbol: str, env: str = "prod"):
        self.symbol = symbol
        self.env = env
        
        # 环境配置
        if env == "qa":
            self.ws_url = "wss://stream.xt-qa2.com/public"
            self.rest_base_url = "https://sapi.xt-qa2.com"
        elif env == "uat":
            self.ws_url = "wss://stream.xt-uat.com/public"
            self.rest_base_url = "https://sapi.xt-uat.com"
        else:
            self.ws_url = "wss://stream.xt.com/public"
            self.rest_base_url = "https://sapi.xt.com"
        
        logger.info(f"🔧 初始化调试器: symbol={symbol}, env={env}")
        logger.info(f"   WebSocket: {self.ws_url}")
        logger.info(f"   REST API: {self.rest_base_url}")
        
        # 初始化客户端
        self.rest_client = Spot(host=self.rest_base_url)
        self.ws_client = None
    
    def test_rest_api(self) -> Dict[str, Any]:
        """测试REST API深度查询"""
        logger.info("\n" + "="*60)
        logger.info("📊 测试REST API深度数据")
        logger.info("="*60)
        
        try:
            depth = self.rest_client.get_depth(self.symbol, limit=100)
            
            bids = depth.get('bids', [])
            asks = depth.get('asks', [])
            
            logger.info(f"✅ REST API查询成功:")
            logger.info(f"   - Bids档位: {len(bids)}")
            logger.info(f"   - Asks档位: {len(asks)}")
            logger.info(f"   - 时间戳: {depth.get('timestamp')}")
            
            if bids:
                logger.info(f"   - 最佳买价: {bids[0][0]} @ {bids[0][1]}")
            else:
                logger.warning(f"   ⚠️ 买单为空!")
            
            if asks:
                logger.info(f"   - 最佳卖价: {asks[0][0]} @ {asks[0][1]}")
            else:
                logger.warning(f"   ⚠️ 卖单为空!")
            
            # 数据完整性检查
            if not bids or not asks:
                logger.warning(f"\n⚠️ 订单簿不完整: bids={len(bids)}, asks={len(asks)}")
                logger.warning(f"⚠️ 可能原因:")
                logger.warning(f"   1. {self.env.upper()}环境流动性不足")
                logger.warning(f"   2. 交易对 {self.symbol} 暂停交易")
                logger.warning(f"   3. API数据异常")
            
            return depth
            
        except Exception as e:
            logger.error(f"❌ REST API查询失败: {e}", exc_info=True)
            return {}
    
    async def test_websocket(self, duration: int = 10) -> None:
        """测试WebSocket实时深度数据
        
        Args:
            duration: 监听时长（秒）
        """
        logger.info("\n" + "="*60)
        logger.info(f"🌐 测试WebSocket深度推送 (监听{duration}秒)")
        logger.info("="*60)
        
        try:
            # 创建WebSocket客户端
            self.ws_client = XTWebSocketClient(
                symbol=self.symbol,
                ws_url=self.ws_url,
                depth_levels=100
            )
            
            # 启动WebSocket
            self.ws_client.start()
            logger.info("✅ WebSocket已启动，等待连接...")
            
            # 等待连接建立
            await asyncio.sleep(3)
            
            if not self.ws_client.is_connected():
                logger.error("❌ WebSocket连接失败")
                return
            
            logger.info("✅ WebSocket已连接，开始监听数据...")
            
            # 监听数据更新
            update_count = 0
            start_time = time.time()
            
            while time.time() - start_time < duration:
                depth = self.ws_client.get_cached_depth(max_age=5)
                
                if depth:
                    update_count += 1
                    bids = depth.get('bids', [])
                    asks = depth.get('asks', [])
                    
                    logger.info(f"\n📈 深度更新 #{update_count}:")
                    logger.info(f"   - Bids档位: {len(bids)}")
                    logger.info(f"   - Asks档位: {len(asks)}")
                    logger.info(f"   - 时间戳: {depth.get('timestamp')}")
                    
                    if bids:
                        logger.info(f"   - 最佳买价: {bids[0][0]} @ {bids[0][1]}")
                    else:
                        logger.warning(f"   ⚠️ 买单为空!")
                    
                    if asks:
                        logger.info(f"   - 最佳卖价: {asks[0][0]} @ {asks[0][1]}")
                    else:
                        logger.warning(f"   ⚠️ 卖单为空!")
                    
                    # 数据完整性检查
                    if not bids or not asks:
                        logger.warning(f"\n⚠️ WebSocket推送的订单簿不完整!")
                        logger.warning(f"   原始数据: {json.dumps(depth, indent=2)}")
                else:
                    logger.warning("⏳ 暂无缓存数据...")
                
                await asyncio.sleep(2)
            
            # 显示统计信息
            stats = self.ws_client.get_stats()
            logger.info("\n" + "="*60)
            logger.info("📊 WebSocket统计信息:")
            logger.info("="*60)
            logger.info(f"   - 接收消息: {stats['messages_received']}")
            logger.info(f"   - 深度更新: {stats['depth_updates']}")
            logger.info(f"   - 重连次数: {stats['reconnects']}")
            logger.info(f"   - 错误次数: {stats['errors']}")
            logger.info(f"   - 缓存年龄: {stats.get('cache_age', 'N/A')}秒")
            
        except Exception as e:
            logger.error(f"❌ WebSocket测试失败: {e}", exc_info=True)
        
        finally:
            if self.ws_client:
                self.ws_client.stop()
                logger.info("WebSocket已关闭")
    
    async def compare_data_sources(self) -> None:
        """对比REST API和WebSocket数据"""
        logger.info("\n" + "="*60)
        logger.info("🔍 对比REST API vs WebSocket数据")
        logger.info("="*60)
        
        # 1. REST API数据
        rest_depth = self.test_rest_api()
        
        # 2. WebSocket数据
        await self.test_websocket(duration=5)
        
        # 3. 对比分析
        if rest_depth and self.ws_client:
            ws_depth = self.ws_client.get_cached_depth()
            
            if ws_depth:
                rest_bids = len(rest_depth.get('bids', []))
                rest_asks = len(rest_depth.get('asks', []))
                ws_bids = len(ws_depth.get('bids', []))
                ws_asks = len(ws_depth.get('asks', []))
                
                logger.info("\n" + "="*60)
                logger.info("📊 数据源对比:")
                logger.info("="*60)
                logger.info(f"REST API: bids={rest_bids}, asks={rest_asks}")
                logger.info(f"WebSocket: bids={ws_bids}, asks={ws_asks}")
                
                if rest_bids == 0 or rest_asks == 0 or ws_bids == 0 or ws_asks == 0:
                    logger.warning("\n⚠️ 检测到订单簿不完整问题!")
                    logger.warning("⚠️ 建议:")
                    logger.warning("   1. 检查交易对是否正常交易")
                    logger.warning("   2. 切换到生产环境测试")
                    logger.warning("   3. 联系交易所技术支持")


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="订单簿调试工具")
    parser.add_argument("--symbol", default="ton3s_usdt", help="交易对符号")
    parser.add_argument("--env", default="qa", choices=["qa", "uat", "prod"], help="环境")
    parser.add_argument("--mode", default="all", choices=["rest", "ws", "all"], help="测试模式")
    parser.add_argument("--duration", type=int, default=10, help="WebSocket监听时长（秒）")
    
    args = parser.parse_args()
    
    debugger = OrderbookDebugger(symbol=args.symbol, env=args.env)
    
    if args.mode == "rest":
        debugger.test_rest_api()
    elif args.mode == "ws":
        await debugger.test_websocket(duration=args.duration)
    else:
        await debugger.compare_data_sources()


if __name__ == "__main__":
    asyncio.run(main())
