-- =====================================================
-- 数据库迁移脚本：添加订单用途字段
-- 作者: Claude AI
-- 日期: 2025-01-24
-- 说明: 移除 is_wash_trading，统一使用 order_purpose
-- =====================================================

-- ===== STEP 1: 添加新字段 =====

-- 1.1 为 orders 表添加 order_purpose 字段
ALTER TABLE orders
ADD COLUMN order_purpose VARCHAR(20) DEFAULT 'market_making' NOT NULL;

-- 1.2 为 trades 表添加 trade_purpose 字段
ALTER TABLE trades
ADD COLUMN trade_purpose VARCHAR(20) DEFAULT 'market_making' NOT NULL;

COMMENT ON COLUMN orders.order_purpose IS '订单用途分类: market_making(做市) / anti_pin(反针对) / wash_trading(洗盘) / hedging(对冲)';
COMMENT ON COLUMN trades.trade_purpose IS '交易用途分类: market_making(做市) / anti_pin(反针对) / wash_trading(洗盘) / hedging(对冲)';


-- ===== STEP 2: 迁移历史数据 =====

-- 2.1 迁移 orders 表历史数据
UPDATE orders
SET order_purpose = CASE
    WHEN is_wash_trading = true THEN 'wash_trading'
    ELSE 'market_making'
END
WHERE order_purpose = 'market_making';  -- 仅更新默认值的记录

-- 2.2 迁移 trades 表历史数据
UPDATE trades
SET trade_purpose = CASE
    WHEN is_wash_trading = true THEN 'wash_trading'
    ELSE 'market_making'
END
WHERE trade_purpose = 'market_making';  -- 仅更新默认值的记录

-- 2.3 验证迁移结果
DO $$
DECLARE
    orders_wash_count INT;
    orders_purpose_count INT;
    trades_wash_count INT;
    trades_purpose_count INT;
BEGIN
    SELECT COUNT(*) INTO orders_wash_count FROM orders WHERE is_wash_trading = true;
    SELECT COUNT(*) INTO orders_purpose_count FROM orders WHERE order_purpose = 'wash_trading';

    SELECT COUNT(*) INTO trades_wash_count FROM trades WHERE is_wash_trading = true;
    SELECT COUNT(*) INTO trades_purpose_count FROM trades WHERE trade_purpose = 'wash_trading';

    RAISE NOTICE '=== 数据迁移验证 ===';
    RAISE NOTICE 'orders 表: is_wash_trading=true 数量 = %, order_purpose=wash_trading 数量 = %',
                 orders_wash_count, orders_purpose_count;
    RAISE NOTICE 'trades 表: is_wash_trading=true 数量 = %, trade_purpose=wash_trading 数量 = %',
                 trades_wash_count, trades_purpose_count;

    IF orders_wash_count != orders_purpose_count OR trades_wash_count != trades_purpose_count THEN
        RAISE EXCEPTION '数据迁移失败！洗盘订单数量不匹配';
    ELSE
        RAISE NOTICE '✅ 数据迁移成功！所有洗盘记录已正确迁移';
    END IF;
END $$;


-- ===== STEP 3: 创建新索引 =====

-- 3.1 为 orders 表创建新索引
CREATE INDEX idx_order_purpose ON orders(order_purpose);
CREATE INDEX idx_strategy_purpose ON orders(strategy_name, order_purpose);
CREATE INDEX idx_purpose_created ON orders(order_purpose, created_at);

-- 3.2 为 trades 表创建新索引
CREATE INDEX idx_trade_purpose ON trades(trade_purpose);
CREATE INDEX idx_trade_strategy_purpose ON trades(strategy_name, trade_purpose);


-- ===== STEP 4: 删除旧字段和索引 =====

-- 4.1 删除 orders 表旧索引
DROP INDEX IF EXISTS idx_strategy_wash;

-- 4.2 删除 orders 表旧字段
ALTER TABLE orders DROP COLUMN IF EXISTS is_wash_trading;

-- 4.3 删除 trades 表旧字段
ALTER TABLE trades DROP COLUMN IF EXISTS is_wash_trading;

RAISE NOTICE '✅ 旧字段和索引已删除';


-- ===== STEP 5: 创建统计视图（可选） =====

-- 5.1 订单用途分布视图
CREATE OR REPLACE VIEW v_order_purpose_stats AS
SELECT
    strategy_name,
    order_purpose,
    COUNT(*) as order_count,
    SUM(price * quantity) as total_volume,
    AVG(price * quantity) as avg_order_size,
    COUNT(*) FILTER (WHERE status = 'FILLED') as filled_count,
    COUNT(*) FILTER (WHERE status = 'FILLED')::DECIMAL / NULLIF(COUNT(*), 0) as fill_rate
FROM orders
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY strategy_name, order_purpose
ORDER BY strategy_name, total_volume DESC;

-- 5.2 交易用途分布视图
CREATE OR REPLACE VIEW v_trade_purpose_stats AS
SELECT
    strategy_name,
    trade_purpose,
    COUNT(*) as trade_count,
    SUM(price * quantity) as total_volume,
    AVG(price * quantity) as avg_trade_size,
    SUM(fee) as total_fees
FROM trades
WHERE traded_at >= NOW() - INTERVAL '7 days'
GROUP BY strategy_name, trade_purpose
ORDER BY strategy_name, total_volume DESC;

COMMENT ON VIEW v_order_purpose_stats IS '订单用途统计视图（最近7天）';
COMMENT ON VIEW v_trade_purpose_stats IS '交易用途统计视图（最近7天）';


-- ===== STEP 6: 分析表以优化查询性能 =====

ANALYZE orders;
ANALYZE trades;


-- =====================================================
-- 迁移完成！
--
-- 验证步骤：
-- 1. 检查数据迁移: SELECT order_purpose, COUNT(*) FROM orders GROUP BY order_purpose;
-- 2. 检查索引创建: \di *purpose*
-- 3. 检查视图: SELECT * FROM v_order_purpose_stats LIMIT 10;
--
-- 回滚步骤（如果需要）：
-- ALTER TABLE orders ADD COLUMN is_wash_trading BOOLEAN DEFAULT false;
-- UPDATE orders SET is_wash_trading = (order_purpose = 'wash_trading');
-- ALTER TABLE trades ADD COLUMN is_wash_trading BOOLEAN DEFAULT false;
-- UPDATE trades SET is_wash_trading = (trade_purpose = 'wash_trading');
-- =====================================================
