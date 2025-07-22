# ETF交易系统 API参考文档

本文档提供ETF交易系统所有公共API的详细说明，包括类、方法、参数和返回值的完整信息。

## 目录

- [核心交易模块](#核心交易模块)
  - [MarketMaker 做市商](#marketmaker-做市商)
  - [WashController 洗盘控制器](#washcontroller-洗盘控制器)
  - [RiskController 风险控制器](#riskcontroller-风险控制器)
  - [OrderManager 订单管理器](#ordermanager-订单管理器)
- [工具模块](#工具模块)
  - [通用工具函数](#通用工具函数)
  - [性能优化工具](#性能优化工具)
  - [异常处理工具](#异常处理工具)
- [配置常量](#配置常量)

---

## 核心交易模块

### MarketMaker 做市商

ETF做市商核心类，负责自动化的市场做市和流动性提供。

**位置**: `etf/market_making.py`

#### 类定义

```python
class MarketMaker:
    """
    ETF做市商核心类，负责自动化的市场做市和流动性提供
    
    该类实现了高级做市策略，包括：
    - 动态订单簿生成和管理
    - 基于净值的智能定价
    - 优化的批量订单处理
    - 反针对订单保护
    - 实时性能监控
    """
```

#### 构造函数

```python
def __init__(self, order_manager: Any) -> None:
    """
    初始化做市商
    
    Args:
        order_manager: 订单管理器实例，用于执行订单操作
    """
```

#### 核心方法

##### make_orders()

```python
def make_orders(
    self,
    symbol: Optional[str] = None,
    clientOrderId: str = DEFAULT_CLIENT_ORDER_ID,
    netvalue: float = 1.0,
    env: str = "qa",
    ordermanager: Optional[Any] = None,
) -> None:
    """
    创建模拟做市订单（主要用于测试环境）
    
    在QA环境中生成假订单用于测试做市逻辑，不实际提交到交易所
    
    Args:
        symbol: 交易对符号，如'btc5l_usdt'
        clientOrderId: 客户端订单ID
        netvalue: 净值价格，用作订单簿中间价
        env: 环境标识，目前只支持'qa'测试环境
        ordermanager: 订单管理器（已弃用参数）
        
    Note:
        该方法只在qa环境下生效，用于测试做市策略
    """
```

##### place_orders()

```python
def place_orders(
    self,
    config: Dict[str, Any],
    symbol: str = "btc5l_usdt",
    clientOrderId: str = DEFAULT_CLIENT_ORDER_ID,
    env: str = "qa",
    ordermanager: Optional[Any] = None,
    currencies: Optional[List[str]] = None,
    prec: int = 4,
) -> None:
    """
    执行智能做市订单放置策略
    
    这是核心做市方法，执行以下操作：
    1. 从Redis或文件获取实时净值
    2. 生成基于净值的订单簿
    3. 使用优化算法匹配当前订单
    4. 批量执行订单添加和取消
    5. 添加反针对保护订单
    
    Args:
        config: 策略配置字典，包含净值键、价差、精度等参数
        symbol: 交易对符号
        clientOrderId: 客户端订单ID（已弃用）
        env: 环境标识
        ordermanager: 订单管理器（已弃用参数）
        currencies: 货币列表（已弃用参数）
        prec: 价格精度位数
        
    Note:
        该方法使用O(n log n)优化算法进行订单匹配，
        显著提升大量订单场景下的性能
    """
```

##### get_performance_stats()

```python
def get_performance_stats(self) -> Dict[str, Any]:
    """
    获取做市商性能统计信息
    
    收集并返回订单匹配和批量处理的详细性能指标，
    用于监控系统性能和优化策略参数
    
    Returns:
        Dict[str, Any]: 包含以下键的性能统计字典：
            - order_matching: 订单匹配算法性能指标
            - batch_processing: 批量订单处理性能指标  
            - timestamp: 统计时间戳
            
    Example:
        >>> stats = market_maker.get_performance_stats()
        >>> print(f"Average matching time: {stats['order_matching']['avg_time']:.4f}s")
    """
```

---

### WashController 洗盘控制器

ETF洗盘交易控制器，负责市场流动性维护和价格连续性管理。

**位置**: `etf/washing.py`

#### 类定义

```python
class WashController:
    """
    ETF洗盘交易控制器，负责市场流动性维护和价格连续性管理
    
    该类实现智能洗盘交易策略，包括：
    - 基于波动率的风险控制
    - 自适应交易量调节
    - 双向交易配对执行
    - K线连续性维护
    - 性能监控和统计
    """
```

#### 构造函数

```python
def __init__(self, order_manager: Any, market_maker: Any) -> None:
    """
    初始化洗盘交易控制器
    
    Args:
        order_manager: 订单管理器实例，用于执行交易
        market_maker: 做市商实例，用于获取价格信息
    """
```

#### 核心方法

##### wash()

```python
@performance_monitor.time_function("wash_trading")
def wash(
    self, 
    symbol: str, 
    last_mid_price: float, 
    mid_price: float, 
    prec: int = 4, 
    prec_amount: int = 2, 
    interval: int = 60
) -> float:
    """
    执行智能洗盘交易策略
    
    基于价格变动和波动率分析，执行双向配对交易以维护市场流动性
    和价格连续性。该方法包含多重风险控制机制。
    
    Args:
        symbol: 交易对符号
        last_mid_price: 上一个中间价
        mid_price: 当前中间价  
        prec: 价格精度位数
        prec_amount: 数量精度位数
        interval: K线连续性检查间隔（秒）
        
    Returns:
        float: 调整后的中间价格
        
    Risk Controls:
        - 波动率限制：volatility > 1% 时跳过交易
        - 最小交易额：确保单笔交易 >= 5 USDT
        - 动态数量：根据价格涨跌调节交易量
        
    Note:
        该方法会同时创建买单和卖单，形成完整的wash trading配对
    """
```

##### get_washing_price()

```python
def get_washing_price(self, config: Dict[str, Any]) -> float:
    """
    获取洗盘交易的基准价格
    
    从做市商获取当前最优价格，如果做市商未运行则从Redis或文件获取净值
    
    Args:
        config: 策略配置字典，包含净值键等参数
        
    Returns:
        float: 洗盘交易基准价格
        
    Fallback Strategy:
        1. 优先使用做市商的最优卖价
        2. 从Redis获取净值
        3. 从文件读取净值
        4. 使用默认值1.0
    """
```

##### run()

```python
def run(self, risk_controller: Any, config: Dict[str, Any]) -> None:
    """
    执行完整的洗盘交易流程
    
    这是洗盘控制器的主要运行方法，包含完整的交易循环：
    1. 初始化基准价格
    2. 检查风险控制状态
    3. 获取当前市场价格
    4. 执行洗盘交易策略
    
    Args:
        risk_controller: 风险控制器实例，用于风险评估
        config: 策略配置字典，包含各种交易参数
        
    Flow:
        - 随机延迟启动（1-5秒）
        - 获取初始化价格
        - 基于风险等级决定是否执行交易
        - 调用wash方法执行具体交易
        
    Note:
        该方法会根据风险控制器的状态动态调整交易行为
    """
```

##### get_performance_stats()

```python
def get_performance_stats(self) -> Dict[str, Any]:
    """
    获取洗盘交易性能统计信息
    
    收集并返回洗盘交易的详细性能指标和运营数据，
    用于监控交易效率和成本控制
    
    Returns:
        Dict[str, Any]: 包含以下键的性能统计字典：
            - wash_trading: 洗盘交易性能指标
            - timestamp: 统计时间戳
            - total_spent: 累计交易成本
            - max_trade_amount: 最大单次交易量配置
            
    Example:
        >>> stats = wash_controller.get_performance_stats()
        >>> print(f"Total wash trades: {stats['wash_trading']['count']}")
    """
```

---

## 工具模块

### 通用工具函数

**位置**: `etf/utils/common.py`

#### get_mid_price()

```python
def get_mid_price(depth: Dict[str, Any]) -> float:
    """
    从订单簿计算中间价格
    
    Args:
        depth: 订单簿深度数据，包含bids和asks
        
    Returns:
        float: 中间价格
        
    Raises:
        IndexError: 当订单簿为空时
        ValueError: 当价格格式无效时
    """
```

#### calculate_price_change_percentage()

```python
def calculate_price_change_percentage(old_price: float, new_price: float) -> float:
    """
    计算价格变化百分比
    
    Args:
        old_price: 旧价格
        new_price: 新价格
        
    Returns:
        float: 价格变化百分比 (小数形式，如0.05表示5%)
    """
```

### 性能优化工具

**位置**: `etf/utils/optimization.py`

#### AsyncOrderProcessor

```python
class AsyncOrderProcessor:
    """异步订单处理器，优化批量订单操作"""
    
    def __init__(self, max_concurrent: int = 5, batch_size: int = 100):
        """
        初始化异步处理器
        
        Args:
            max_concurrent: 最大并发数
            batch_size: 批处理大小
        """
```

#### optimize_order_matching()

```python
def optimize_order_matching(
    current_orders: List[Dict[str, Any]],
    goal_orders: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    优化的订单匹配算法，将O(n²)复杂度降低到O(n log n)
    
    Args:
        current_orders: 当前订单列表
        goal_orders: 目标订单列表
        
    Returns:
        Tuple: (需要添加的订单, 需要取消的订单)
    """
```

#### PerformanceMonitor

```python
class PerformanceMonitor:
    """性能监控器"""
    
    def time_function(self, func_name: str):
        """函数执行时间装饰器"""
        
    def get_statistics(self, func_name: str) -> Dict[str, float]:
        """获取函数执行统计信息"""
```

---

## 配置常量

**位置**: `etf/utils/constants.py`

### Redis配置
```python
DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379
DEFAULT_REDIS_DB = 0
```

### 订单配置
```python
DEFAULT_BATCH_SIZE = 100
DEFAULT_BATCH_ID = 51232
DEFAULT_CLIENT_ORDER_ID = "16559590087220001"
```

### 交易配置
```python
DEFAULT_MAX_TRADE_AMOUNT = 50
DEFAULT_MIN_TRADE_VALUE = 5  # USDT
DEFAULT_VOLATILITY_THRESHOLD = 0.01
```

### 订单类型常量
```python
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_MARKET = "MARKET"
SIDE_BUY = "BUY"  
SIDE_SELL = "SELL"
TIME_IN_FORCE_GTC = "GTC"
BIZ_TYPE_SPOT = "SPOT"
```

---

## 使用示例

### 基本做市商使用

```python
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager

# 初始化订单管理器和做市商
order_manager = OrderManager(client, strategy_name="example")
market_maker = MarketMaker(order_manager)

# 配置策略参数
config = {
    "netvalue": "netvalue_btc5l",
    "bid_ask_spread": 0.01,
    "precision": 4,
    "prec_amount": 2,
    "anti_pin_rate": 0.05,
    "anti_pin_usdt": 100
}

# 执行做市
market_maker.place_orders(config, symbol="btc5l_usdt")

# 获取性能统计
stats = market_maker.get_performance_stats()
print(f"订单匹配平均耗时: {stats['order_matching']['avg_time']:.4f}s")
```

### 洗盘交易使用

```python
from etf.washing import WashController
from etf.risk import RiskController

# 初始化控制器
wash_controller = WashController(order_manager, market_maker)
risk_controller = RiskController(client, risk_params, "strategy_name")

# 配置参数
config = {
    "netvalue": "netvalue_btc5l",
    "precision": 4,
    "prec_amount": 2,
    "kline_continuity_interval": 60
}

# 执行洗盘交易
wash_controller.run(risk_controller, config)

# 监控性能
stats = wash_controller.get_performance_stats()
print(f"洗盘交易总次数: {stats['wash_trading']['count']}")
```

---

## 注意事项

1. **类型安全**: 所有公共API都提供了完整的类型注解，建议使用支持类型检查的IDE
2. **异常处理**: 关键方法都有相应的异常处理，请注意捕获和处理异常
3. **性能监控**: 建议定期调用性能统计方法监控系统运行状态
4. **配置管理**: 使用constants.py中定义的常量而不是硬编码值
5. **日志记录**: 系统自动记录关键操作日志，注意日志级别设置

---

*最后更新: 2025-01-22*
*版本: 1.0.0*