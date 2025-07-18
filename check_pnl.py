data = []
pnl = []
trade = []

with open('/root/.pm2/logs/etf-stats-error__2025-04-18_00-00-00.log', 'r') as input:
    for line in input:
        if "etf_stats.py:187" in line or "INFO" not in line:
            continue
        #print(line)
        line = line.strip().split(' - ')[-1]
        # "xt_usdt_remain 10007.48 xt_coin_remain -73.39 xt_coin_remain_convertusdt -88.21 xt_mid_price 1.2019736060942279 xt_average_price -0.101921 bn_coin_remain -1109.0 bn_entry_price 0.2643180342651 bn_cost_usdt -293.13 bn_unRealizedProfit 4.07892418 bn_usdt_remain 2454.81"
        xt_usdt_remain = float(line.split(' ')[1])
        xt_coin_remain = float(line.split(' ')[3])
        xt_coin_remain_convertusdt = float(line.split(' ')[5])
        xt_mid_price = float(line.split(' ')[7])
        xt_average_price = float(line.split(' ')[9])
        bn_coin_remain = float(line.split(' ')[11])
        bn_entry_price = float(line.split(' ')[13])
        bn_cost_usdt = float(line.split(' ')[15])
        bn_unRealizedProfit = float(line.split(' ')[17])
        bn_usdt_remain = float(line.split(' ')[19])
        if xt_coin_remain not in trade:
            trade.append(xt_coin_remain)
        if len(data) > 0:
            xt_pnl = xt_usdt_remain + xt_coin_remain_convertusdt - data[-1][0] - data[-1][2]
            bn_pnl = bn_usdt_remain - data[-1][9]
            #print(xt_pnl, bn_pnl)
            pnl.append(xt_pnl + bn_pnl)
            
        data.append([xt_usdt_remain, xt_coin_remain, xt_coin_remain_convertusdt, xt_mid_price, xt_average_price, bn_coin_remain, bn_entry_price, bn_cost_usdt, bn_unRealizedProfit, bn_usdt_remain])
print(sum(pnl), len(trade), trade)
