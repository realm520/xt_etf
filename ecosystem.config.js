module.exports = {
  apps: [
    // 3倍杠杆做多策略
    {
      name: 'etf-stg3l',
      script: 'python',
      args: 'run_etf.py --strategy stg3l',
      cwd: '/Users/harry/code/xt_etf',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/Users/harry/code/xt_etf',
        STRATEGY: 'stg3l'
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      max_restarts: 10,
      min_uptime: '10s',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: 'logs/pm2/etf-stg3l-error.log',
      out_file: 'logs/pm2/etf-stg3l-out.log',
      merge_logs: true,
      time: true
    },

    // 3倍杠杆做空策略
    {
      name: 'etf-stg3s',
      script: 'python',
      args: 'run_etf.py --strategy stg3s',
      cwd: '/Users/harry/code/xt_etf',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/Users/harry/code/xt_etf',
        STRATEGY: 'stg3s'
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      max_restarts: 10,
      min_uptime: '10s',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: 'logs/pm2/etf-stg3s-error.log',
      out_file: 'logs/pm2/etf-stg3s-out.log',
      merge_logs: true,
      time: true
    },

    // 5倍杠杆做多策略
    {
      name: 'etf-stg5l',
      script: 'python',
      args: 'run_etf.py --strategy stg5l',
      cwd: '/Users/harry/code/xt_etf',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/Users/harry/code/xt_etf',
        STRATEGY: 'stg5l'
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      max_restarts: 10,
      min_uptime: '10s',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: 'logs/pm2/etf-stg5l-error.log',
      out_file: 'logs/pm2/etf-stg5l-out.log',
      merge_logs: true,
      time: true
    },

    // 5倍杠杆做空策略
    {
      name: 'etf-stg5s',
      script: 'python',
      args: 'run_etf.py --strategy stg5s',
      cwd: '/Users/harry/code/xt_etf',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/Users/harry/code/xt_etf',
        STRATEGY: 'stg5s'
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      max_restarts: 10,
      min_uptime: '10s',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: 'logs/pm2/etf-stg5s-error.log',
      out_file: 'logs/pm2/etf-stg5s-out.log',
      merge_logs: true,
      time: true
    },

    // TON 3倍杠杆做多策略 (QA环境)
    {
      name: 'etf-ton3l',
      script: 'python',
      args: 'run_etf.py --strategy ton3l --env qa',
      cwd: '/Users/harry/code/xt_etf',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/Users/harry/code/xt_etf',
        STRATEGY: 'ton3l',
        ENV: 'qa'
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      max_restarts: 10,
      min_uptime: '10s',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: 'logs/pm2/etf-ton3l-error.log',
      out_file: 'logs/pm2/etf-ton3l-out.log',
      merge_logs: true,
      time: true
    },

    // TON 3倍杠杆做空策略 (QA环境)
    {
      name: 'etf-ton3s',
      script: 'python',
      args: 'run_etf.py --strategy ton3s --env qa',
      cwd: '/Users/harry/code/xt_etf',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/Users/harry/code/xt_etf',
        STRATEGY: 'ton3s',
        ENV: 'qa'
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      max_restarts: 10,
      min_uptime: '10s',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: 'logs/pm2/etf-ton3s-error.log',
      out_file: 'logs/pm2/etf-ton3s-out.log',
      merge_logs: true,
      time: true
    },

    // 净值计算服务
    {
      name: 'etf-net-value',
      script: 'python',
      args: 'run_net_value.py',
      cwd: '/Users/harry/code/xt_etf',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/Users/harry/code/xt_etf'
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      max_restarts: 10,
      min_uptime: '10s',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: 'logs/pm2/etf-net-value-error.log',
      out_file: 'logs/pm2/etf-net-value-out.log',
      merge_logs: true,
      time: true
    }
  ],

  // 部署配置
  deploy: {
    production: {
      user: 'trader',
      host: 'production-server',
      ref: 'origin/master',
      repo: 'git@github.com:your-repo/xt_etf.git',
      path: '/home/trader/xt_etf',
      'post-deploy': 'source .venv/bin/activate && uv pip install -e . && pm2 reload ecosystem.config.js --env production'
    },
    staging: {
      user: 'trader',
      host: 'staging-server',
      ref: 'origin/develop',
      repo: 'git@github.com:your-repo/xt_etf.git',
      path: '/home/trader/xt_etf',
      'post-deploy': 'source .venv/bin/activate && uv pip install -e . && pm2 reload ecosystem.config.js --env staging'
    }
  }
};