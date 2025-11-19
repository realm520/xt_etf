#!/bin/bash
# 快速检查订单情况

echo "================================"
echo "TON3L 订单状态快速检查"
echo "================================"
echo

# 检查最近的add_orders日志
echo "📊 最近10次订单操作:"
echo "--------------------------------"
tail -200 logs/ton3l/ton3l.log | grep -E "add_orders: [0-9]+" | tail -10
echo

# 检查批量订单验证
echo "✅ 最近批量订单验证结果:"
echo "--------------------------------"
tail -200 logs/ton3l/ton3l.log | grep "批量订单验证完成" | tail -5
echo

# 检查是否有rejected订单
echo "❌ 检查被拒绝的订单:"
echo "--------------------------------"
REJECTED=$(grep "rejected.*true" logs/ton3l/ton3l.log | wc -l | tr -d ' ')
if [ "$REJECTED" -eq "0" ]; then
    echo "✅ 没有被拒绝的订单"
else
    echo "⚠️  发现 $REJECTED 个被拒绝的订单"
    grep "rejected.*true" logs/ton3l/ton3l.log | tail -5
fi
echo

# 检查洗盘频率
echo "🔄 洗盘操作频率:"
echo "--------------------------------"
WASH_COUNT=$(tail -500 logs/ton3l/ton3l.log | grep "washing" | wc -l | tr -d ' ')
echo "最近500行日志中有 $WASH_COUNT 次洗盘操作"
echo

# 统计不同数量的add_orders
echo "📈 add_orders数量分布（最近100次）:"
echo "--------------------------------"
tail -1000 logs/ton3l/ton3l.log | grep -oE "add_orders: [0-9]+" | sort | uniq -c | sort -rn
echo

# 检查goal orders
echo "🎯 目标订单配置（最近一次）:"
echo "--------------------------------"
tail -100 logs/ton3l/ton3l.log | grep "goal ask1\|goal bid1" | tail -2
tail -100 logs/ton3l/ton3l.log | grep "goal ask-1\|goal bid-1" | tail -2
echo

echo "================================"
echo "如需实时监控，请运行:"
echo "  tail -f logs/ton3l/ton3l.log | grep 'add_orders\\|goal'"
echo "================================"
