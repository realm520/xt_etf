API_KEY=lDHuIavZpEErNyC27HGnJSMOb0ArGR0lBBNJGEWU56NnxjxUwljgnBn97RFScuZN
SECRET_KEY=zlo0LVMVqNTDJRCby7QZMYuPRSY8QMLOokK6UnmqtUZ5YDP9GIqsvqCnXh7bAPSV


# sig=$(echo -n)
timestamp=`date +%s000`
echo "$timestamp"
sig=`echo -n "timestamp=$timestamp" | openssl dgst -sha256 -hmac $SECRET_KEY | sed 's/.*= //'`
#echo "https://sapi.xt-qa.com/v4/public/depth?signature=$sig"
curl -H "X-MBX-APIKEY: $API_KEY" -X GET "https://api.binance.com/api/v3/account?timestamp=$timestamp&signature=$sig"
