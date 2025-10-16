import requests
import json
from datetime import datetime, timedelta, date
import schedule
import time
import os
class LarkBot:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token = None
        self.token_expire_time = None
    
    def get_access_token(self):
        """获取访问令牌"""
        # 如果已有有效token则直接返回
        if self.access_token and self.token_expire_time and datetime.now() < self.token_expire_time:
            return self.access_token
            
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {
            "Content-Type": "application/json"
        }
        data = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code == 200:
            result = response.json()
            self.access_token = result.get("tenant_access_token")
            # 设置token过期时间（提前10分钟过期）
            expire = result.get("expire", 7200) - 600
            self.token_expire_time = datetime.now() + timedelta(seconds=expire)
            return self.access_token
        else:
            raise Exception(f"获取access_token失败: {response.text}")
    
    def send_group_message(self, chat_id, msg_type, content):
        """发送群组消息"""
        access_token = self.get_access_token()
        url = f"https://open.larksuite.com/open-apis/bot/v2/hook/" + chat_id
        headers = {
            "Content-Type": "application/json",
            # "Authorization": f"Bearer {access_token}"
        }
        data = {
            "receive_id": chat_id,
            "content": json.dumps(content),
            "msg_type": msg_type
        }
        # https://open.larksuite.com/open-apis/bot/v2/hook/bfcc4b0a-15ce-4775-a958-24d4ad02ad3f
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"发送消息失败: {response.text}")
    
    def send_text_message(self, chat_id, text):
        """发送文本消息"""
        content = {
            "text": text
        }
        return self.send_group_message(chat_id, "text", content)
    
    def send_post_message(self, chat_id, title, content):
        """发送富文本消息"""
        post_content = {
            "zh_cn": {
                "title": title,
                "content": content
            }
        }
        return self.send_group_message(chat_id, "post", post_content)

def send_daily_message():
    APP_ID = "cli_a888a93b54389029"
    APP_SECRET = "M44bRQxX9oJKFFP4USGaufyMKyA62hbw"
    # Etf Prod Alert
    CHAT_ID = "bfcc4b0a-15ce-4775-a958-24d4ad02ad3f"
    # https://open.larksuite.com/open-apis/bot/v2/hook/
    # bfcc4b0a-15ce-4775-a958-24d4ad02ad3f
    bot = LarkBot(APP_ID, APP_SECRET)
    today = date.today()
    if not os.path.isfile('/root/.pm2/logs/etf-stats-aggregation-error__' + str(today) + '_00-00-00.log'):
        return
    data = []
    pnl = []
    trade = []
    #stg5l_coin = []
    #stg5s_coin = []
    #stg3l_coin = []
    #stg3s_coin = []
    #with open('/root/.pm2/logs/etf-stats-aggregation-error.log', 'r') as input:
    with open('/root/.pm2/logs/etf-stats-aggregation-error__' + str(today) + '_00-00-00.log', 'r') as input:
        for line in input:
            #etf-stats-aggregation-error__2025-04-19_00-00-00.log
            if "etf_stats.py:187" in line or "INFO" not in line:
                continue
            #print(line)
            date1 = line.strip().split(' - ')[0]
            line = line.strip().split(' - ')[-1]
            # 2025-04-21 23:02:15,003 - INFO - etf_stats_aggregation.py:139 - xt_coin_reduce (stg5l_usdt: 45.83) (stg5s_usdt: 0.02) (stg3l_usdt: 8.39) (stg3s_usdt: 0.0) xt_usdt_remain_sum 69963.27 xt_coin_reduce_sum 54.24 xt_coin_reduce_convertusdt_sum 70.8 bn_unRealizedProfit 1.31896336 bn_usdt_remain 2530.15
            #print(line)
            line_1 = line.split(' ')
            #xt_coin_stg5l = float(line_1[2][:-1])
            #xt_coin_stg5s = float(line_1[4][:-1])
            #xt_coin_stg3l = float(line_1[6][:-1])
            #xt_coin_stg3s = float(line_1[8][:-1])

            line_2 = line.split(') ')[-1]
            #xt_coin_reduce = 
            #print(line_2)
            xt_usdt_remain = float(line_2.split(' ')[1])
            bn_usdt_remain = float(line_2.split(' ')[9])
            
            try:
                bn_cost_usdt = float(line_2.split(' ')[11])
            except Exception as e:
                pass
            xt_coin_reduce_sum = float(line_2.split(' ')[3])
            xt_xt_coin_reduce_convertusdt_sum = float(line_2.split(' ')[5])
            bn_unRealizedProfit = float(line_2.split(' ')[7])
            if len(data) > 0:
                xt_pnl = xt_usdt_remain + xt_xt_coin_reduce_convertusdt_sum - data[-1][1] - data[-1][2]
                bn_pnl = bn_usdt_remain - data[-1][-1]
                #print(xt_pnl, bn_pnl)
                pnl.append(xt_pnl + bn_pnl)
            if len(trade) == 0 or xt_coin_reduce_sum != trade[-1][-1]:                    
                trade.append([date, xt_coin_reduce_sum])    
            #if len(stg5l_coin) == 0 or xt_coin_stg5l != stg5l_coin[-1][-1]:
            #    stg5l_coin.append([date, xt_coin_stg5l])
            #if len(stg5s_coin) == 0 or xt_coin_stg5s != stg5s_coin[-1][-1]:
            #    stg5s_coin.append([date, xt_coin_stg5s])
            #if len(stg3l_coin) == 0 or xt_coin_stg3l != stg3l_coin[-1][-1]:
            #    stg3l_coin.append([date, xt_coin_stg3l])
            #if len(stg3s_coin) == 0 or xt_coin_stg3s != stg3s_coin[-1][-1]:
            #    stg3s_coin.append([date, xt_coin_stg3s])

            data.append([date1, xt_usdt_remain, xt_xt_coin_reduce_convertusdt_sum, bn_unRealizedProfit, bn_usdt_remain])
        print(sum(pnl), len(trade), trade, data[-1][0], data[-1][1], data[-1][2], data[-1][3])
        message = '【日期】：截止到' + str(date1) + '\n'
        message += '【币对】：STG5L, STG3L, STG5S, STG3S\n'
        message += '本日自然成交量：' + str(len(trade)) + ' 笔\n' 
        message += 'XT剩余USDT：' + str(xt_usdt_remain) + '\n'
        message += 'XT用户持仓总价值：' + str(xt_xt_coin_reduce_convertusdt_sum) + '\n'
        message += 'XT累计盈利：' + str(xt_usdt_remain - 70000 - xt_xt_coin_reduce_convertusdt_sum) + '\n'
        message += 'BN剩余USDT：' + str(bn_usdt_remain) + '\n'
        message += 'BN持仓总价值：' + str(bn_cost_usdt) + '\n'
        message += 'BN累计盈利：' + str(bn_usdt_remain - 2500) + '\n'
        message += '合计累计盈利：' + str(xt_usdt_remain - 70000 - xt_xt_coin_reduce_convertusdt_sum + bn_usdt_remain - 2500)
        
    bot.send_text_message(CHAT_ID, message)

# 使用示例
if __name__ == "__main__":
     
    # 发送纯文本消息
    # 设置每天早上8点执行
    #send_daily_message()
    schedule.every().day.at("08:00").do(send_daily_message)
    
    # 保持程序运行
    while True:
        schedule.run_pending()
        time.sleep(1)  # 避免CPU占用过高
    #send_daily_message()
    # 发送富文本消息
    # post_content = [
    #     [{
    #         "tag": "text",
    #         "text": "这是一条富文本消息\n"
    #     }, {
    #         "tag": "a",
    #         "text": "点击查看详情",
    #         "href": "https://open.feishu.cn"
    #     }],
    #     [{
    #         "tag": "at",
    #         "user_id": "all",  # @所有人
    #         "user_name": "所有人"
    #     }]
    # ]
    # bot.send_post_message(CHAT_ID, "通知标题", post_content)
