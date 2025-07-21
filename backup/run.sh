pm2 start run_etf.py --interpreter python3 \
    --name run_stg5s -- \
    --prefix stg5s \
    --precision 6 \
    --prec-amount 2 \
    --bid-ask-spread 0.05 \
    --anti-pin-usdt 300 \
    --anti-pin-rate 0.2
