import os

files = sorted(os.listdir("/home/oshindow/orders/python-binance1"), reverse=False)
for file in files:
    if file.startswith('etf-stats-error'):
        xt_positions = []
        bn_positions = []
        lines = []
        with open(file, 'r', encoding='utf8') as input:
            # 2025-04-14 00:00:02,079 - INFO - etf_stats.py:225 - xt_usdt_remain 9955.25 xt_coin_remain -51.02 xt_coin_remain_convertusdt -56.82 xt_mid_price 1.1137756544632627 xt_average_price 0.877107 bn_coin_remain -858.0 bn_entry_price 0.1976636421164 bn_cost_usdt -169.6 bn_unRealizedProfit 10.52220312 bn_usdt_remain 2537.71
            for line in input:
                try:
                    xt_position = line.strip().split(' ')[10]
                    bn_position = line.strip().split(' ')[18]
                    xt_coin_covert = line.strip().split(' ')[12]
                    bn_cost = line.strip().split(' ')[22]
                    if xt_positions == [] or bn_position != bn_positions[-1]:
                        xt_positions.append(xt_position)
                        bn_positions.append(bn_position)
                        lines.append((xt_position, xt_coin_covert, bn_position, bn_cost, line))
                except Exception as e:
                    continue
    else:
        continue
    print(file)
    for line in lines:
        print(line)
 

