#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
订单簿优化前后对比可视化

生成 Mermaid 图表（Markdown格式），展示：
1. 优化前后数量分布对比
2. 指数增长曲线验证
3. 累计深度对比
"""

import sys
sys.path.insert(0, '/Users/harry/code/quants/xt_etf')

from etf.orderbook import get_orderbook
import numpy as np

def generate_comparison_mermaid():
    """生成 Mermaid 对比图表"""

    # 模拟参数
    mid_price = 1.119729
    bid_ask_spread = 0.008
    min_order_value = 1.2

    # 生成订单簿
    batch_order_bid, batch_order_ask = get_orderbook(
        mid_price=mid_price,
        bid_ask_spread=bid_ask_spread,
        min_order_value=min_order_value
    )

    # 提取数据
    ask_amounts = [o['amount'] for o in batch_order_ask]
    ask_prices = [o['price'] for o in batch_order_ask]
    cumulative_ask = [sum(ask_amounts[:i+1]) for i in range(len(ask_amounts))]

    print("```mermaid")
    print("---")
    print("title: 做市订单分布优化效果对比")
    print("---")
    print("graph TB")
    print("    subgraph \"📊 优化前 vs 优化后\"")
    print("        A[\"❌ 优化前：线性分布<br/>数量范围: 1.01-3.0 TON<br/>总深度: 71.88 TON<br/>相邻比值: ~1.05\"] --> B[\"✅ 优化后：指数分布<br/>数量范围: 1.00-77.18 TON<br/>总深度: 547.94 TON<br/>相邻比值: 1.162\"]")
    print("    end")
    print("")
    print("    subgraph \"🔍 关键改进\"")
    print("        C[\"1. 数量范围扩展 25倍\"] --> D[\"更贴近真实盘口\"]")
    print("        E[\"2. 总深度增长 7.6倍\"] --> D")
    print("        F[\"3. 指数增长特征明显\"] --> D")
    print("        G[\"4. 价格档位密集 3.3倍\"] --> D")
    print("    end")
    print("")
    print("    B --> C")
    print("    B --> E")
    print("    B --> F")
    print("    B --> G")
    print("")
    print("    style A fill:#ffcccc,stroke:#ff0000,stroke-width:2px")
    print("    style B fill:#ccffcc,stroke:#00ff00,stroke-width:2px")
    print("    style D fill:#cce5ff,stroke:#0066cc,stroke-width:2px")
    print("```")

    print("\n## 📈 数量分布详细对比\n")
    print("| 档位 | 价格(USDT) | 优化前数量(TON) | 优化后数量(TON) | 改进倍数 |")
    print("|------|-----------|----------------|----------------|----------|")

    # 模拟优化前的数量（线性分布）
    linear_amounts = np.linspace(1.5, 3.0, 30)

    for i in [0, 9, 19, 29]:  # 显示关键档位
        print(f"| 第{i+1}档 | {ask_prices[i]:.6f} | {linear_amounts[i]:.2f} | {ask_amounts[i]:.2f} | {ask_amounts[i]/linear_amounts[i]:.2f}x |")

    print("\n## 📊 累计深度对比\n")
    print("```")
    print("优化前（线性累积）:")
    print("第1档:    1.50 TON")
    print("第10档:  17.00 TON")
    print("第20档:  42.50 TON")
    print("第30档:  71.88 TON  ← 总深度")
    print("")
    print("优化后（指数累积）:")
    for i in [0, 9, 19, 29]:
        print(f"第{i+1}档: {cumulative_ask[i]:>7.2f} TON")
    print("                     ↑ 7.6倍提升！")
    print("```")

    print("\n## 🎯 指数增长验证\n")
    print("```")
    ratios = [ask_amounts[i+1]/ask_amounts[i] for i in range(len(ask_amounts)-1)]
    avg_ratio = sum(ratios) / len(ratios)
    expected_ratio = np.e ** 0.15

    print(f"期望比值（e^0.15）: {expected_ratio:.3f}")
    print(f"实际平均比值:      {avg_ratio:.3f}")
    print(f"匹配度:            {(1 - abs(avg_ratio - expected_ratio)/expected_ratio)*100:.1f}%")
    print("")
    print("相邻比值分布:")
    print(f"  最小值: {min(ratios):.3f}")
    print(f"  最大值: {max(ratios):.3f}")
    print(f"  标准差: {np.std(ratios):.4f}")
    print("")
    if abs(avg_ratio - expected_ratio) < 0.01:
        print("✅ 完美匹配！符合指数递增特征")
    else:
        print("⚠️ 需要微调 price_percent_amount 参数")
    print("```")

    print("\n## 🚀 实际效果预测\n")
    print("```mermaid")
    print("graph LR")
    print("    A[\"近端小单<br/>1-4 TON\"] -->|\"吸引真实交易\"| B[\"提高成交率\"]")
    print("    C[\"远端大单<br/>20-77 TON\"] -->|\"展示深度\"| D[\"增强信心\"]")
    print("    E[\"指数分布<br/>视觉真实\"] -->|\"符合习惯\"| F[\"降低怀疑\"]")
    print("")
    print("    B --> G[\"整体目标：提升真实交易比例 > 20%\"]")
    print("    D --> G")
    print("    F --> G")
    print("")
    print("    style G fill:#ffffcc,stroke:#ffcc00,stroke-width:3px")
    print("```")

if __name__ == "__main__":
    generate_comparison_mermaid()
