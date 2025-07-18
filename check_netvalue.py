import os
for file in os.listdir("/root/.pm2/logs"):
    if "net-value-error__" in file:
        # net-value-error__2025-04-10_14-23-54.log
        with open("/root/.pm2/logs/" + file, 'r', encoding="utf-8") as input:
            for line in input:
                if "DEBUG" not in line:
                    print(file, line)

