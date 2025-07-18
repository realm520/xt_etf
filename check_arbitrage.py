import os
for file in os.listdir('/root/.pm2/logs'):
    if file.startswith('run-etf-error__2025-03'):
        with open('/root/.pm2/logs/' + file, 'r') as input:
            for line in input:
                if 'xt_delta_position' in line and "xt_delta_position == 0" not in line and "'xt_delta_position': 0.0" not in line and "crossUnPnl" not in line:
                    print(line)
