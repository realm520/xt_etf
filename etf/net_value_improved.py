# -*- coding:utf-8 -*-

"""
改进版净值计算器
- 支持断线重连后的净值恢复
- 记录详细的时间戳信息
- 管理费精确计算
- 异常保护机制
- PostgreSQL持久化存储（可选）

Author: AllenBrother
Date:   2024/12/19
Updated: 2025-01-20 (添加数据库持久化)
"""

import json
import time
import redis
import asyncio
from typing import Dict, Optional, List, Tuple, TYPE_CHECKING
from loguru import logger
from datetime import datetime, timedelta

from etf.xt import Spot
from etf.utils.ds import Queue
# Alert system removed - using logging only

# 类型提示（避免循环导入）
if TYPE_CHECKING:
    from etf.observability.metrics import MetricsCollector
    from etf.storage.net_value_recorder import NetValueRecorder


class ImprovedNetValue:
    """改进版净值计算器"""

    def __init__(
        self,
        symbol: str,
        m_lever: int,
        init_net_value: float = 1.0,
        daily_fee: float = 0.001,
        time_gap_second: int = 10,
        rebalance: float = 0.05,
        long: bool = True,
        max_single_change: float = 0.10,  # 最大单次变化率限制
        max_restart_gap: int = 300,  # 最大重启间隔（秒）
        metrics_collector: Optional['MetricsCollector'] = None,  # OpenTelemetry 指标收集器
        enable_db_persistence: bool = False,  # 启用数据库持久化（默认禁用）
        strategy_name: Optional[str] = None,  # 策略名称（用于数据库记录）
        # 新增：净值推送相关参数
        enable_push_to_exchange: bool = False,  # 启用推送到交易所（默认禁用）
        push_interval: int = 60,  # 推送间隔（秒），默认60秒推送一次
        push_host: Optional[str] = None,  # 交易所API主机（None则使用默认）
        push_access_key: Optional[str] = None,  # 推送用的access_key
        push_secret_key: Optional[str] = None,  # 推送用的secret_key
        push_symbol: Optional[str] = None,  # 推送到交易所的symbol名称（如 "TON3L_USDT"）
    ):
        self.symbol = symbol
        self.m_lever = m_lever
        self.long = long
        self.rebalance = rebalance
        self.time_gap_second = time_gap_second
        self.daily_fee = daily_fee
        self.time_gap_fee = daily_fee / (24 * 60 * 60) * time_gap_second
        self.max_single_change = max_single_change
        self.max_restart_gap = max_restart_gap
        self.metrics_collector = metrics_collector  # OpenTelemetry 指标收集器
        self.enable_db_persistence = enable_db_persistence

        # 净值推送相关配置
        self.enable_push_to_exchange = enable_push_to_exchange
        self.push_interval = push_interval
        self.push_host = push_host or "https://sapi.xt.com"  # 默认生产环境
        self.push_symbol = push_symbol  # 交易所symbol（如 "TON3L_USDT"）
        self.last_push_time = 0  # 上次推送时间戳
        self.push_client = None  # 推送用的Spot客户端

        # 策略名称（从symbol推导）
        if strategy_name:
            self.strategy_name = strategy_name
        else:
            direction = "l" if self.long else "s"
            self.strategy_name = f"{self.symbol.split('_')[0]}{self.m_lever}{direction}"

        # Redis连接
        self.r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

        # Redis键名
        direction = "l" if self.long else "s"
        self.redis_key = (
            f"netvalue_{self.symbol.split('_')[0]}{self.m_lever}{direction}"
        )
        self.redis_detail_key = f"{self.redis_key}_detail"
        self.redis_history_key = f"{self.redis_key}_history"

        # 价格队列
        self.underlying_mid_price_queue = Queue(2)

        # 数据库记录器（必须在 _init_net_value 之前初始化，因为恢复逻辑需要用到）
        self.db_recorder: Optional['NetValueRecorder'] = None
        if enable_db_persistence:
            try:
                from etf.storage.net_value_recorder import NetValueRecorder
                self.db_recorder = NetValueRecorder(
                    strategy_name=self.strategy_name,
                    batch_size=40,
                    flush_interval=10.0,
                    enable_persistence=True
                )
                logger.info(f"数据库持久化已启用: {self.strategy_name}")
            except Exception as e:
                logger.error(f"数据库记录器初始化失败: {e}，将仅使用Redis")
                self.db_recorder = None

        # 初始化净值数据（必须在 db_recorder 之后，因为可能需要记录恢复事件）
        self.net_value_data = self._init_net_value(init_net_value)

        # 交易所客户端（获取价格）
        self.spot_client = Spot(
            host="https://sapi.xt.com", access_key="", secret_key=""
        )

        # 初始化推送客户端（如果启用推送）
        if self.enable_push_to_exchange:
            if not push_access_key or not push_secret_key:
                logger.warning("推送功能已启用但未提供API密钥，推送将被禁用")
                self.enable_push_to_exchange = False
            else:
                self.push_client = Spot(
                    host=self.push_host,
                    access_key=push_access_key,
                    secret_key=push_secret_key
                )
                logger.info(
                    f"净值推送功能已启用: {self.push_symbol or self.strategy_name.upper() + '_USDT'}, "
                    f"推送间隔: {self.push_interval}秒, "
                    f"目标主机: {self.push_host}"
                )

        logger.info(
            f"净值计算器初始化完成: {self.symbol}, 杠杆: {self.m_lever}x, 方向: {'做多' if self.long else '做空'}, "
            f"数据库持久化: {'启用' if self.db_recorder else '禁用'}, "
            f"交易所推送: {'启用' if self.enable_push_to_exchange else '禁用'}"
        )

    def _get_or_create_event_loop(self) -> asyncio.AbstractEventLoop:
        """获取或创建持久的事件循环（用于异步数据库操作）"""
        if not hasattr(self, '_event_loop') or self._event_loop is None or self._event_loop.is_closed():
            import threading
            
            # 创建新的事件循环和线程
            self._event_loop = asyncio.new_event_loop()
            
            def run_loop():
                """在独立线程中运行事件循环"""
                asyncio.set_event_loop(self._event_loop)
                self._event_loop.run_forever()
            
            self._loop_thread = threading.Thread(
                target=run_loop,
                daemon=True,
                name="async_db_loop"
            )
            self._loop_thread.start()
            logger.debug(f"{self.strategy_name}: 创建持久事件循环用于异步数据库操作")
        
        return self._event_loop

    def _cleanup_async_resources(self):
        """清理异步资源（事件循环、数据库连接等）"""
        try:
            # 刷新数据库缓冲
            if self.db_recorder:
                logger.info(f"{self.strategy_name}: 正在刷新数据库缓冲...")
                loop = self._get_or_create_event_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self.db_recorder.flush_all(),
                    loop
                )
                # 等待刷新完成（最多10秒）
                future.result(timeout=10)
                
                # 关闭数据库连接
                future = asyncio.run_coroutine_threadsafe(
                    self.db_recorder.close(),
                    loop
                )
                future.result(timeout=5)
                logger.info(f"{self.strategy_name}: 数据库资源已清理")
            
            # 停止事件循环
            if hasattr(self, '_event_loop') and self._event_loop and not self._event_loop.is_closed():
                self._event_loop.call_soon_threadsafe(self._event_loop.stop)
                if hasattr(self, '_loop_thread') and self._loop_thread.is_alive():
                    self._loop_thread.join(timeout=5)
                logger.debug(f"{self.strategy_name}: 事件循环已停止")
            
            # 关闭线程池
            if hasattr(self, '_db_thread_pool'):
                self._db_thread_pool.shutdown(wait=True, cancel_futures=False)
            if hasattr(self, '_event_thread_pool'):
                self._event_thread_pool.shutdown(wait=True, cancel_futures=False)
            
            logger.info(f"{self.strategy_name}: 所有异步资源已清理")
            
        except Exception as e:
            logger.error(f"{self.strategy_name}: 清理异步资源时出错: {e}", exc_info=True)

    def _init_net_value(self, default_value: float) -> Dict:
        """初始化净值数据"""
        try:
            # 尝试从Redis读取详细数据
            detail_data = self.r.get(self.redis_detail_key)
            if detail_data:
                data = json.loads(detail_data)
                logger.info(f"从Redis恢复净值数据: {data}")

                # 检查是否需要恢复
                last_update = data.get("last_update_ts", 0)
                gap_seconds = time.time() - last_update

                if gap_seconds > 30:
                    logger.warning(f"检测到程序重启，断线时间: {gap_seconds:.1f}秒")
                    # 恢复净值
                    self._recover_net_value(data, gap_seconds)

                return data
            else:
                # 尝试读取简单净值
                simple_value = self.r.get(self.redis_key)
                if simple_value:
                    net_value = float(simple_value)
                else:
                    net_value = default_value

                # 创建新的数据结构
                data = {
                    "net_value": net_value,
                    "last_price": None,
                    "last_update_ts": time.time(),
                    "create_ts": time.time(),
                    "update_count": 0,
                    "total_fee_deducted": 0.0,
                    "abnormal_events": [],
                }

                # 保存到Redis
                self._save_to_redis(data)
                return data

        except Exception as e:
            logger.error(f"初始化净值数据失败: {e}")
            return {
                "net_value": default_value,
                "last_price": None,
                "last_update_ts": time.time(),
                "create_ts": time.time(),
                "update_count": 0,
                "total_fee_deducted": 0.0,
                "abnormal_events": [],
            }

    def _save_to_redis(self, data: Dict):
        """保存数据到Redis + PostgreSQL（异步）"""
        try:
            # 1. 保存到Redis（实时查询）
            self.r.set(self.redis_key, str(data["net_value"]))
            self.r.set(self.redis_detail_key, json.dumps(data))

            # 保存到历史记录
            history_data = {
                "net_value": data["net_value"],
                "price": data.get("last_price"),
                "timestamp": data["last_update_ts"],
            }
            self.r.lpush(self.redis_history_key, json.dumps(history_data))
            self.r.ltrim(self.redis_history_key, 0, 1000)  # 保留最近1000条

            # 2. 异步写入PostgreSQL（持久化）
            # 使用后台线程处理异步数据库写入，避免阻塞主循环
            if self.db_recorder:
                self._record_net_value_to_db_sync(data)

        except Exception as e:
            logger.error(f"保存数据到Redis失败: {e}")

    def _recover_net_value(self, data: Dict, gap_seconds: float):
        """恢复断线期间的净值"""
        if gap_seconds > self.max_restart_gap:
            logger.error(
                f"断线时间过长({gap_seconds:.1f}秒)，超过最大限制({self.max_restart_gap}秒)"
            )
            event_data = {
                "type": "long_restart",
                "gap_seconds": gap_seconds,
                "timestamp": time.time(),
                "severity": "critical",
            }
            data["abnormal_events"].append(event_data)

            # 记录到数据库
            if self.db_recorder:
                self._record_event_sync("long_restart", event_data)

            return

        try:
            # 获取历史K线数据来补算净值
            # 这里简化处理，实际应该调用交易所API获取K线
            logger.info(f"尝试恢复{gap_seconds:.1f}秒的净值变化")

            # 补扣管理费
            missed_intervals = int(gap_seconds / self.time_gap_second)
            if missed_intervals > 0:
                total_fee_rate = (
                    self.daily_fee
                    / (24 * 60 * 60)
                    * (missed_intervals * self.time_gap_second)
                )
                data["net_value"] *= 1 - total_fee_rate
                data["total_fee_deducted"] += total_fee_rate
                logger.info(
                    f"补扣管理费: {total_fee_rate:.6f}, 影响净值: {total_fee_rate * data['net_value']:.6f}"
                )

            # 记录恢复事件
            event_data = {
                "type": "recovery",
                "gap_seconds": gap_seconds,
                "missed_intervals": missed_intervals,
                "timestamp": time.time(),
                "severity": "high" if gap_seconds > 180 else "medium",
            }
            data["abnormal_events"].append(event_data)

            # 记录恢复日志（告警已移除，使用日志记录）
            logger.warning(f"净值恢复事件:")
            logger.warning(f"  断线时间: {gap_seconds:.1f}秒")
            logger.warning(f"  遗漏周期: {missed_intervals}个")
            logger.warning(f"  交易对: {self.symbol}")
            logger.warning(f"  杠杆: {self.m_lever}x {'做多' if self.long else '做空'}")
            logger.warning(f"  净值: {data['net_value']:.6f}")
            logger.warning(f"  补扣管理费: {total_fee_rate * data['net_value']:.6f}")

            # 记录到数据库（使用线程安全的方式）
            if self.db_recorder:
                self._record_event_sync("recovery", event_data)

        except Exception as e:
            logger.error(f"恢复净值失败: {e}")

    def _format_db_data(self, data: Dict) -> Dict:
        """格式化数据为数据库格式"""
        return {
            "symbol": self.symbol,
            "leverage": self.m_lever,
            "long": self.long,
            "net_value": data["net_value"],
            "underlying_price": data.get("last_price"),
            "change_rate": None,  # 由调用方计算
            "price_change_rate": None,
            "fee_deducted": self.time_gap_fee * data["net_value"] if "net_value" in data else None,
            "cumulative_fee": data.get("total_fee_deducted", 0),
            "rebalance_triggered": False,  # 由调用方设置
            "rebalance_count": 0,
            "recorded_at": data.get("last_update_ts", time.time()),
        }

    def _record_net_value_to_db_sync(self, data: Dict):
        """将净值数据记录到数据库（同步方式，使用线程池）"""
        if not self.db_recorder:
            return

        try:
            # 使用线程池执行，避免阻塞主线程
            from concurrent.futures import ThreadPoolExecutor
            import threading

            # 创建单例线程池（如果不存在）
            if not hasattr(self, '_db_thread_pool'):
                self._db_thread_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db_writer")

            # 提交任务到线程池
            self._db_thread_pool.submit(self._run_async_db_write, self._format_db_data(data))
        except Exception as e:
            logger.debug(f"提交数据库写入任务失败: {e}")

    def _run_async_db_write(self, formatted_data: Dict):
        """在后台线程中运行异步数据库写入"""
        try:
            # 使用事件循环线程安全方式提交任务
            loop = self._get_or_create_event_loop()
            future = asyncio.run_coroutine_threadsafe(
                self.db_recorder.record_net_value(formatted_data),
                loop
            )
            # 不等待结果，让它在后台完成
        except Exception as e:
            logger.debug(f"后台数据库写入失败（正常，将由批量处理）: {e}")

    def _record_event_sync(self, event_type: str, event_data: Dict):
        """记录异常事件到数据库（同步方式，使用线程池）"""
        if not self.db_recorder:
            return

        try:
            # 使用线程池执行（事件写入优先级更高，使用独立线程池）
            from concurrent.futures import ThreadPoolExecutor

            if not hasattr(self, '_event_thread_pool'):
                self._event_thread_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="event_writer")

            self._event_thread_pool.submit(self._run_async_event_write, event_type, event_data)
        except Exception as e:
            logger.debug(f"提交事件写入任务失败: {e}")

    def _run_async_event_write(self, event_type: str, event_data: Dict):
        """在后台线程中运行异步事件写入"""
        try:
            # 使用事件循环线程安全方式提交任务
            loop = self._get_or_create_event_loop()
            future = asyncio.run_coroutine_threadsafe(
                self._record_event_async_impl(event_type, event_data),
                loop
            )
            # 不等待结果，让它在后台完成
        except Exception as e:
            logger.debug(f"后台事件写入失败: {e}")

    async def _record_event_async_impl(self, event_type: str, event_data: Dict):
        """记录异常事件到数据库的异步实现"""
        if not self.db_recorder:
            return

        try:
            await self.db_recorder.record_event({
                "symbol": self.symbol,
                "event_type": event_type,
                "severity": event_data.get("severity", "medium"),
                "old_price": event_data.get("p0"),
                "new_price": event_data.get("p1"),
                "change_rate": event_data.get("change_rate"),
                "gap_seconds": event_data.get("gap_seconds"),
                "missed_intervals": event_data.get("missed_intervals"),
                "event_time": event_data.get("timestamp", time.time()),
                "extra_data": event_data,
            })
        except Exception as e:
            logger.error(f"记录异常事件失败: {e}")

    def update_mid_price(self) -> Optional[float]:
        """更新中间价"""
        try:
            depth = self.spot_client.get_depth(symbol=self.symbol, limit=5)
            if depth and "bids" in depth and "asks" in depth:
                bid_0_price = float(depth["bids"][0][0])
                ask_0_price = float(depth["asks"][0][0])
                mid_price = (bid_0_price + ask_0_price) / 2
                logger.debug(f"{self.symbol} 中间价: {mid_price}")
                return mid_price
            else:
                logger.error(f"获取{self.symbol}市场深度失败")
                return None
        except Exception as e:
            logger.error(f"更新中间价失败: {e}")
            return None

    def cal_net_value(self) -> Optional[float]:
        """计算净值"""
        if len(self.underlying_mid_price_queue) != 2:
            logger.debug("价格队列未满，跳过计算")
            return None

        p0 = self.underlying_mid_price_queue.get(0)
        p1 = self.underlying_mid_price_queue.get(1)

        # 检查价格有效性
        if p0 <= 0 or p1 <= 0:
            logger.error(f"无效的价格数据: p0={p0}, p1={p1}")
            return None

        # 计算价格变化率
        v = (p1 - p0) / p0

        # 异常保护：限制单次最大变化
        if abs(v) > self.max_single_change:
            logger.warning(f"价格变化过大: {v:.4f}, 限制为: {self.max_single_change}")

            event_data = {
                "type": "price_spike",
                "change_rate": v,
                "p0": p0,
                "p1": p1,
                "timestamp": time.time(),
                "severity": "high" if abs(v) > 0.15 else "medium",
            }
            self.net_value_data["abnormal_events"].append(event_data)

            # 记录异常价格日志（告警已移除，使用日志记录）
            logger.error(f"异常价格变化:")
            logger.error(f"  变化率: {abs(v):.4f}")
            logger.error(f"  交易对: {self.symbol}")
            logger.error(f"  旧价格: {p0:.4f}")
            logger.error(f"  新价格: {p1:.4f}")
            logger.error(f"  杠杆: {self.m_lever}x {'做多' if self.long else '做空'}")

            # 记录到数据库
            if self.db_recorder:
                self._record_event_sync("price_spike", event_data)

            v = self.max_single_change if v > 0 else -self.max_single_change
            # 调整p1为限制后的价格，用于后续再平衡计算
            p1 = p0 * (1 + v)

        # 计算净值变化
        side = 1 if v > 0 else -1
        net_value = self.net_value_data["net_value"]

        # 处理再平衡
        while abs(v) > self.rebalance:
            adjustment = side * self.rebalance
            p0 = p0 * (1 + adjustment)

            # 按照原版逻辑计算再平衡时的净值变化
            if self.long:
                # 做多：价格上涨净值增加，价格下跌净值减少
                net_value = net_value * (1 + self.m_lever * adjustment)
            else:
                # 做空：价格上涨净值减少，价格下跌净值增加
                net_value = net_value * (1 - self.m_lever * adjustment)

            v = (p1 - p0) / p0
            logger.info(
                f"触发再平衡: 调整幅度={adjustment:.4f}, 新净值={net_value:.6f}"
            )

        # 正常净值变化
        if self.long:
            net_value = net_value * (1 + self.m_lever * v)
        else:
            net_value = net_value * (1 - self.m_lever * v)

        logger.debug(f"净值计算: 价格变化={v:.4f}, 新净值={net_value:.6f}")
        return net_value

    def cal_fee(self, net_value: float) -> float:
        """计算扣除管理费后的净值"""
        net_value_after_fee = net_value * (1 - self.time_gap_fee)
        fee_amount = net_value - net_value_after_fee
        self.net_value_data["total_fee_deducted"] += self.time_gap_fee
        logger.debug(f"扣除管理费: {fee_amount:.6f}, 费率: {self.time_gap_fee:.6f}")
        return net_value_after_fee

    def _push_net_value_to_exchange(self, net_value: float, retry_count: int = 3) -> bool:
        """
        推送净值到交易所
        
        Args:
            net_value: 要推送的净值
            retry_count: 失败重试次数
            
        Returns:
            bool: 推送是否成功
        """
        if not self.enable_push_to_exchange or not self.push_client:
            return False
        
        # 检查推送间隔
        current_time = time.time()
        if current_time - self.last_push_time < self.push_interval:
            logger.debug(f"距离上次推送不足{self.push_interval}秒，跳过本次推送")
            return False
        
        # 确定推送的symbol名称（如 "TON3L_USDT"）
        push_symbol = self.push_symbol
        if not push_symbol:
            # 自动构建symbol：从 "ton_usdt" + 杠杆 + 方向 => "TON3L_USDT"
            base_symbol = self.symbol.split('_')[0].upper()  # "ton" => "TON"
            direction = "L" if self.long else "S"
            push_symbol = f"{base_symbol}{self.m_lever}{direction}_USDT"
        
        # 尝试推送（带重试）
        for attempt in range(retry_count):
            try:
                logger.info(f"正在推送净值到交易所 (尝试 {attempt + 1}/{retry_count}): {push_symbol} = {net_value:.6f}")
                
                result = self.push_client.update_etf_net_worth(
                    symbol=push_symbol,
                    net_worth=net_value
                )
                
                # 推送成功
                self.last_push_time = current_time
                logger.info(f"✅ 净值推送成功: {push_symbol} = {net_value:.6f}, 响应: {result}")
                
                # 记录成功事件到数据库
                if self.db_recorder:
                    event_data = {
                        "type": "net_value_push_success",
                        "symbol": push_symbol,
                        "net_value": net_value,
                        "timestamp": current_time,
                        "severity": "low",
                        "attempt": attempt + 1
                    }
                    self._record_event_sync("net_value_push", event_data)
                
                return True
                
            except Exception as e:
                logger.error(f"❌ 推送净值失败 (尝试 {attempt + 1}/{retry_count}): {e}")
                
                # 记录失败事件
                if attempt == retry_count - 1:  # 最后一次尝试
                    event_data = {
                        "type": "net_value_push_failed",
                        "symbol": push_symbol,
                        "net_value": net_value,
                        "timestamp": current_time,
                        "error": str(e),
                        "severity": "high",
                        "attempts": retry_count
                    }
                    
                    # 记录到数据库
                    if self.db_recorder:
                        self._record_event_sync("net_value_push_failed", event_data)
                    
                    # 记录到abnormal_events
                    self.net_value_data["abnormal_events"].append(event_data)
                    
                    # 日志告警
                    logger.error(f"🚨 净值推送失败（已重试{retry_count}次）:")
                    logger.error(f"  交易对: {push_symbol}")
                    logger.error(f"  净值: {net_value:.6f}")
                    logger.error(f"  错误: {e}")
                    logger.error(f"  主机: {self.push_host}")
                
                # 等待后重试
                if attempt < retry_count - 1:
                    time.sleep(2 ** attempt)  # 指数退避：1s, 2s, 4s
        
        return False

    def run(self):
        """主运行循环"""
        logger.info(f"净值计算器开始运行: {self.symbol}")

        while True:
            try:
                # 获取最新价格
                mid_price = self.update_mid_price()
                if not mid_price:
                    time.sleep(1)
                    continue

                # 更新价格队列
                self.underlying_mid_price_queue.put(mid_price)

                # 初始化时需要等待第二个价格
                if self.net_value_data["last_price"] is None:
                    self.net_value_data["last_price"] = mid_price
                    logger.info(f"初始价格: {mid_price}")
                    time.sleep(self.time_gap_second)
                    continue

                # 计算净值
                net_value = self.cal_net_value()
                if net_value is None:
                    time.sleep(self.time_gap_second)
                    continue

                # 扣除管理费
                net_value_after_fee = self.cal_fee(net_value)
                
                # 计算净值变化率
                old_net_value = self.net_value_data["net_value"]
                net_value_change_rate = (net_value_after_fee - old_net_value) / old_net_value if old_net_value > 0 else 0

                # 更新数据
                self.net_value_data.update({
                    "net_value": net_value_after_fee,
                    "last_price": mid_price,
                    "last_update_ts": time.time(),
                    "update_count": self.net_value_data["update_count"] + 1,
                })

                # 保存到Redis
                self._save_to_redis(self.net_value_data)

                # 📤 推送净值到交易所（如果启用）
                if self.enable_push_to_exchange:
                    self._push_net_value_to_exchange(net_value_after_fee)

                # 📊 记录净值指标（OpenTelemetry）
                if self.metrics_collector:
                    try:
                        strategy_name = f"{self.symbol.split('_')[0]}{self.m_lever}{'l' if self.long else 's'}"
                        self.metrics_collector.record_net_value(
                            value=net_value_after_fee,
                            strategy=strategy_name,
                            leverage=self.m_lever,
                            direction="long" if self.long else "short",
                            change_rate=net_value_change_rate
                        )
                    except Exception as e:
                        logger.error(f"记录净值指标失败: {e}")

                logger.info(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"净值更新: {net_value_after_fee:.6f}, "
                    f"价格: {mid_price:.4f}, "
                    f"变化率: {net_value_change_rate:.4%}, "
                    f"更新次数: {self.net_value_data['update_count']}"
                )

                # 检查净值异常
                if abs(net_value_change_rate) > 0.05:  # 5% 变化
                    # 记录净值异常日志（告警已移除，使用日志记录）
                    event_type = "净值暴涨" if net_value_change_rate > 0 else "净值暴跌"
                    logger.warning(f"{event_type}:")
                    logger.warning(f"  变化率: {net_value_change_rate:.4%}")
                    logger.warning(f"  交易对: {self.symbol}")
                    logger.warning(f"  旧净值: {old_net_value:.6f}")
                    logger.warning(f"  新净值: {net_value_after_fee:.6f}")
                    logger.warning(f"  杠杆: {self.m_lever}x {'做多' if self.long else '做空'}")

                # 等待下一个周期
                time.sleep(self.time_gap_second)

            except KeyboardInterrupt:
                logger.info("收到退出信号，保存数据并退出")
                self._save_to_redis(self.net_value_data)
                # 清理异步资源
                self._cleanup_async_resources()
                break
            except Exception as e:
                logger.error(f"运行异常: {e}", exc_info=True)
                time.sleep(1)


if __name__ == "__main__":
    # 测试配置
    config = {
        "symbol": "stg_usdt",
        "m_lever": 3,
        "long": True,
        "time_gap_second": 10,
        "rebalance": 0.05,
        "daily_fee": 0.001,
        "max_single_change": 0.10,  # 最大单次10%变化
        "max_restart_gap": 300,  # 最大5分钟重启间隔
    }

    calculator = ImprovedNetValue(
        symbol=config["symbol"],
        m_lever=config["m_lever"],
        long=config["long"],
        time_gap_second=config["time_gap_second"],
        rebalance=config["rebalance"],
        daily_fee=config["daily_fee"],
        max_single_change=config["max_single_change"],
        max_restart_gap=config["max_restart_gap"],
    )

    calculator.run()
