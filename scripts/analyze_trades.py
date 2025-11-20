#!/usr/bin/env python3
"""
成交数据分析脚本

分析数据库中的成交记录，包括：
1. 成交频率分析
2. 成交时间分布
3. 成交量分布
4. K线生成可行性分析
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sqlalchemy import create_engine, func, and_, or_
from sqlalchemy.orm import sessionmaker
import seaborn as sns

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from etf.storage.models import Trade, Order
from dotenv import load_dotenv

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 设置样式
sns.set_style("whitegrid")
sns.set_palette("husl")

# 加载环境变量
load_dotenv()


class TradeAnalyzer:
    """成交数据分析器"""

    def __init__(self, db_url: str = None):
        """初始化分析器"""
        if db_url is None:
            db_url = f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}:" \
                     f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@" \
                     f"{os.getenv('POSTGRES_HOST', 'localhost')}:" \
                     f"{os.getenv('POSTGRES_PORT', '5432')}/" \
                     f"{os.getenv('POSTGRES_DB', 'xt_etf')}"

        self.engine = create_engine(db_url)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

        # 创建输出目录
        self.output_dir = project_root / "analysis_output"
        self.output_dir.mkdir(exist_ok=True)

    def get_basic_stats(self, symbol: str = None, strategy: str = None,
                       start_time: datetime = None, end_time: datetime = None):
        """获取基本统计信息"""
        query = self.session.query(Trade)

        # 添加过滤条件
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        if strategy:
            query = query.filter(Trade.strategy_name == strategy)
        if start_time:
            query = query.filter(Trade.traded_at >= start_time)
        if end_time:
            query = query.filter(Trade.traded_at <= end_time)

        trades = query.all()

        if not trades:
            print("❌ 没有找到成交记录")
            return None

        df = pd.DataFrame([{
            'trade_id': t.trade_id,
            'symbol': t.symbol,
            'price': float(t.price),
            'quantity': float(t.quantity),
            'quote_quantity': float(t.quote_quantity) if t.quote_quantity else 0,
            'is_maker': t.is_maker,
            'is_buyer': t.is_buyer,
            'is_wash': t.is_wash_trading,
            'strategy': t.strategy_name,
            'traded_at': t.traded_at
        } for t in trades])

        print("\n" + "="*80)
        print("📊 基本统计信息")
        print("="*80)
        print(f"总成交数: {len(df)}")
        print(f"真实成交: {(~df['is_wash']).sum()} ({(~df['is_wash']).sum()/len(df)*100:.2f}%)")
        print(f"洗盘成交: {df['is_wash'].sum()} ({df['is_wash'].sum()/len(df)*100:.2f}%)")
        print(f"\n时间范围: {df['traded_at'].min()} 至 {df['traded_at'].max()}")
        print(f"持续时间: {df['traded_at'].max() - df['traded_at'].min()}")
        print(f"\n价格范围: {df['price'].min():.8f} - {df['price'].max():.8f}")
        print(f"平均价格: {df['price'].mean():.8f}")
        print(f"价格标准差: {df['price'].std():.8f}")
        print(f"\n总成交量: {df['quantity'].sum():.8f}")
        print(f"总成交额: {df['quote_quantity'].sum():.8f}")
        print(f"平均单笔量: {df['quantity'].mean():.8f}")

        return df

    def analyze_frequency(self, df: pd.DataFrame):
        """分析成交频率"""
        print("\n" + "="*80)
        print("⏱️  成交频率分析")
        print("="*80)

        df = df.sort_values('traded_at')

        # 计算时间间隔
        df['time_diff'] = df['traded_at'].diff().dt.total_seconds()

        # 移除第一条记录（没有时间差）
        intervals = df['time_diff'].dropna()

        print(f"\n平均间隔: {intervals.mean():.2f} 秒")
        print(f"中位数间隔: {intervals.median():.2f} 秒")
        print(f"最小间隔: {intervals.min():.2f} 秒")
        print(f"最大间隔: {intervals.max():.2f} 秒")
        print(f"标准差: {intervals.std():.2f} 秒")

        # 统计不同时间间隔的分布
        bins = [0, 1, 5, 10, 30, 60, 300, 600, float('inf')]
        labels = ['<1s', '1-5s', '5-10s', '10-30s', '30-60s', '1-5m', '5-10m', '>10m']
        df['interval_category'] = pd.cut(intervals, bins=bins, labels=labels)

        print("\n时间间隔分布:")
        dist = df['interval_category'].value_counts().sort_index()
        for label, count in dist.items():
            pct = count / len(intervals) * 100
            print(f"  {label:8s}: {count:6d} ({pct:5.2f}%)")

        # 绘制频率分布图
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))

        # 1. 时间间隔直方图
        ax = axes[0, 0]
        intervals_filtered = intervals[intervals <= 60]  # 只显示60秒以内
        ax.hist(intervals_filtered, bins=50, edgecolor='black', alpha=0.7)
        ax.set_xlabel('时间间隔 (秒)')
        ax.set_ylabel('频次')
        ax.set_title('成交时间间隔分布 (≤60秒)')
        ax.grid(True, alpha=0.3)

        # 2. 时间间隔分类柱状图
        ax = axes[0, 1]
        dist.plot(kind='bar', ax=ax)
        ax.set_xlabel('时间间隔类别')
        ax.set_ylabel('频次')
        ax.set_title('时间间隔分类分布')
        ax.tick_params(axis='x', rotation=45)
        ax.grid(True, alpha=0.3)

        # 3. 成交频率时间序列
        ax = axes[1, 0]
        df_hour = df.set_index('traded_at').resample('1H').size()
        df_hour.plot(ax=ax, marker='o', linestyle='-', markersize=4)
        ax.set_xlabel('时间')
        ax.set_ylabel('每小时成交数')
        ax.set_title('每小时成交频率')
        ax.grid(True, alpha=0.3)

        # 4. 累计成交数
        ax = axes[1, 1]
        df['cumulative'] = range(1, len(df) + 1)
        ax.plot(df['traded_at'], df['cumulative'], linewidth=1.5)
        ax.set_xlabel('时间')
        ax.set_ylabel('累计成交数')
        ax.set_title('累计成交数量')
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        filename = self.output_dir / f"frequency_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"\n✅ 频率分析图表已保存: {filename}")

        return intervals

    def analyze_time_distribution(self, df: pd.DataFrame):
        """分析时间分布"""
        print("\n" + "="*80)
        print("📅 时间分布分析")
        print("="*80)

        df['hour'] = df['traded_at'].dt.hour
        df['minute'] = df['traded_at'].dt.minute
        df['weekday'] = df['traded_at'].dt.dayofweek
        df['date'] = df['traded_at'].dt.date

        # 按小时统计
        hourly = df.groupby('hour').size()
        print("\n每小时成交分布:")
        for hour, count in hourly.items():
            pct = count / len(df) * 100
            bar = '█' * int(pct / 2)
            print(f"  {hour:02d}:00 - {(hour+1)%24:02d}:00  {bar} {count:5d} ({pct:5.2f}%)")

        # 绘制时间分布图
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))

        # 1. 每小时成交分布
        ax = axes[0, 0]
        hourly.plot(kind='bar', ax=ax, color='steelblue', edgecolor='black')
        ax.set_xlabel('小时')
        ax.set_ylabel('成交数')
        ax.set_title('每小时成交分布')
        ax.grid(True, alpha=0.3, axis='y')

        # 2. 每分钟成交分布（热力图）
        ax = axes[0, 1]
        minute_hour = df.groupby(['hour', 'minute']).size().unstack(fill_value=0)
        sns.heatmap(minute_hour, ax=ax, cmap='YlOrRd', cbar_kws={'label': '成交数'})
        ax.set_xlabel('分钟')
        ax.set_ylabel('小时')
        ax.set_title('每小时-每分钟成交热力图')

        # 3. 每周日成交分布
        ax = axes[1, 0]
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekly = df.groupby('weekday').size()
        weekly.index = [weekday_names[i] for i in weekly.index]
        weekly.plot(kind='bar', ax=ax, color='coral', edgecolor='black')
        ax.set_xlabel('星期')
        ax.set_ylabel('成交数')
        ax.set_title('每周日成交分布')
        ax.grid(True, alpha=0.3, axis='y')

        # 4. 每日成交数
        ax = axes[1, 1]
        daily = df.groupby('date').size()
        daily.plot(kind='bar', ax=ax, color='lightgreen', edgecolor='black')
        ax.set_xlabel('日期')
        ax.set_ylabel('成交数')
        ax.set_title('每日成交数')
        ax.tick_params(axis='x', rotation=45)
        ax.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()
        filename = self.output_dir / f"time_distribution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"\n✅ 时间分布图表已保存: {filename}")

    def analyze_volume_distribution(self, df: pd.DataFrame):
        """分析成交量分布"""
        print("\n" + "="*80)
        print("📊 成交量分布分析")
        print("="*80)

        print(f"\n成交量统计:")
        print(f"  最小单笔: {df['quantity'].min():.8f}")
        print(f"  最大单笔: {df['quantity'].max():.8f}")
        print(f"  平均单笔: {df['quantity'].mean():.8f}")
        print(f"  中位数: {df['quantity'].median():.8f}")
        print(f"  标准差: {df['quantity'].std():.8f}")

        # 分位数分析
        quantiles = [0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
        print(f"\n成交量分位数:")
        for q in quantiles:
            val = df['quantity'].quantile(q)
            print(f"  {int(q*100):2d}%: {val:.8f}")

        # 绘制成交量分布图
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))

        # 1. 成交量直方图
        ax = axes[0, 0]
        ax.hist(df['quantity'], bins=50, edgecolor='black', alpha=0.7)
        ax.set_xlabel('成交量')
        ax.set_ylabel('频次')
        ax.set_title('成交量分布直方图')
        ax.grid(True, alpha=0.3)

        # 2. 成交量对数直方图
        ax = axes[0, 1]
        log_qty = np.log10(df['quantity'] + 1e-8)
        ax.hist(log_qty, bins=50, edgecolor='black', alpha=0.7, color='orange')
        ax.set_xlabel('log10(成交量)')
        ax.set_ylabel('频次')
        ax.set_title('成交量对数分布')
        ax.grid(True, alpha=0.3)

        # 3. 成交量箱线图（按wash/real分类）
        ax = axes[1, 0]
        df['type'] = df['is_wash'].map({True: '洗盘', False: '真实'})
        df.boxplot(column='quantity', by='type', ax=ax)
        ax.set_xlabel('成交类型')
        ax.set_ylabel('成交量')
        ax.set_title('成交量分布（按类型）')
        plt.suptitle('')  # 移除默认标题
        ax.grid(True, alpha=0.3)

        # 4. 成交量时间序列
        ax = axes[1, 1]
        df_sorted = df.sort_values('traded_at')
        ax.scatter(df_sorted['traded_at'], df_sorted['quantity'],
                  c=df_sorted['is_wash'].map({True: 'red', False: 'blue'}),
                  alpha=0.5, s=10)
        ax.set_xlabel('时间')
        ax.set_ylabel('成交量')
        ax.set_title('成交量时间序列')
        ax.legend(['洗盘', '真实'], loc='upper right')
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        filename = self.output_dir / f"volume_distribution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"\n✅ 成交量分布图表已保存: {filename}")

    def analyze_kline_feasibility(self, df: pd.DataFrame, intervals=['1m', '5m', '15m', '1h']):
        """分析K线生成可行性"""
        print("\n" + "="*80)
        print("📈 K线生成可行性分析")
        print("="*80)

        df = df.sort_values('traded_at').set_index('traded_at')

        fig, axes = plt.subplots(2, 2, figsize=(18, 12))

        for idx, interval in enumerate(intervals):
            ax = axes[idx // 2, idx % 2]

            # 按时间间隔聚合生成OHLCV
            ohlcv = df['price'].resample(interval).agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last'
            })
            volume = df['quantity'].resample(interval).sum()
            count = df.resample(interval).size()

            # 移除没有数据的时间段
            valid_idx = count > 0
            ohlcv = ohlcv[valid_idx]
            volume = volume[valid_idx]
            count = count[valid_idx]

            # 统计
            total_candles = len(ohlcv)
            candles_with_data = (count > 0).sum()
            coverage = candles_with_data / total_candles * 100 if total_candles > 0 else 0
            avg_trades_per_candle = count.mean()

            print(f"\n{interval} K线:")
            print(f"  总K线数: {total_candles}")
            print(f"  有数据K线: {candles_with_data} ({coverage:.2f}%)")
            print(f"  平均每根K线成交数: {avg_trades_per_candle:.2f}")
            print(f"  最多成交数: {count.max()}")
            print(f"  最少成交数: {count.min()}")

            # 绘制K线图
            if len(ohlcv) > 0:
                # 使用简化的K线绘制
                for i in range(len(ohlcv)):
                    timestamp = ohlcv.index[i]
                    open_price = ohlcv.iloc[i]['open']
                    high_price = ohlcv.iloc[i]['high']
                    low_price = ohlcv.iloc[i]['low']
                    close_price = ohlcv.iloc[i]['close']

                    color = 'red' if close_price >= open_price else 'green'

                    # 绘制影线
                    ax.plot([timestamp, timestamp], [low_price, high_price],
                           color=color, linewidth=0.8, alpha=0.8)

                    # 绘制实体
                    body_height = abs(close_price - open_price)
                    body_bottom = min(open_price, close_price)
                    rect = plt.Rectangle((mdates.date2num(timestamp), body_bottom),
                                        width=0.0003 * len(ohlcv),
                                        height=body_height,
                                        facecolor=color, edgecolor='black',
                                        linewidth=0.5, alpha=0.7)
                    ax.add_patch(rect)

                ax.set_xlabel('时间')
                ax.set_ylabel('价格')
                ax.set_title(f'{interval} K线图 (覆盖率: {coverage:.1f}%)')
                ax.grid(True, alpha=0.3)
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            else:
                ax.text(0.5, 0.5, f'无数据生成 {interval} K线',
                       horizontalalignment='center', verticalalignment='center',
                       transform=ax.transAxes, fontsize=14)

        plt.tight_layout()
        filename = self.output_dir / f"kline_feasibility_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"\n✅ K线可行性图表已保存: {filename}")

        # 生成随机成交量建议
        print("\n" + "="*80)
        print("💡 随机成交量生成建议")
        print("="*80)
        self._suggest_random_volume_generation(df)

    def _suggest_random_volume_generation(self, df: pd.DataFrame):
        """建议随机成交量生成策略"""

        # 分析真实成交
        real_trades = df[~df['is_wash']]
        wash_trades = df[df['is_wash']]

        if len(real_trades) == 0:
            print("⚠️  没有真实成交数据，无法提供建议")
            return

        print("\n基于当前数据的建议:")
        print(f"\n1. 成交量范围:")
        print(f"   真实成交: {real_trades['quantity'].min():.8f} - {real_trades['quantity'].max():.8f}")
        print(f"   平均: {real_trades['quantity'].mean():.8f}")
        print(f"   建议使用对数正态分布: μ={np.log(real_trades['quantity'].mean()):.2f}, σ={np.log(real_trades['quantity'].std() + 1):.2f}")

        print(f"\n2. 成交频率:")
        intervals = df.index.to_series().diff().dt.total_seconds().dropna()
        print(f"   平均间隔: {intervals.mean():.2f}秒")
        print(f"   中位数间隔: {intervals.median():.2f}秒")
        print(f"   建议使用泊松分布: λ={1/intervals.mean():.4f} (每秒)")

        print(f"\n3. 真实/洗盘比例:")
        total = len(df)
        real_pct = len(real_trades) / total * 100
        wash_pct = len(wash_trades) / total * 100
        print(f"   真实: {real_pct:.2f}%")
        print(f"   洗盘: {wash_pct:.2f}%")
        print(f"   建议真实成交比例: {max(20, min(40, real_pct)):.0f}%")

        print(f"\n4. 价格分布:")
        price_std = df['price'].std()
        price_mean = df['price'].mean()
        print(f"   价格波动率: {price_std/price_mean*100:.4f}%")
        print(f"   建议价格扰动: ±{price_std:.8f}")

        print("\n5. 实现伪代码:")
        print("""
        def generate_random_trade():
            # 成交时间（泊松过程）
            time_interval = np.random.exponential(scale=平均间隔秒数)

            # 成交量（对数正态分布）
            volume = np.random.lognormal(mean=μ, sigma=σ)

            # 是否为真实成交（伯努利分布）
            is_real = np.random.random() < 真实成交比例

            # 价格（基础价格 + 随机波动）
            price = base_price + np.random.normal(0, price_std)

            return {
                'time': current_time + time_interval,
                'price': price,
                'volume': volume,
                'is_real': is_real
            }
        """)

    def export_summary(self, df: pd.DataFrame):
        """导出分析摘要"""
        summary_file = self.output_dir / f"analysis_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("成交数据分析报告\n")
            f.write("="*80 + "\n\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write("基本统计:\n")
            f.write(f"  总成交数: {len(df)}\n")
            f.write(f"  真实成交: {(~df['is_wash']).sum()}\n")
            f.write(f"  洗盘成交: {df['is_wash'].sum()}\n")
            f.write(f"  时间范围: {df['traded_at'].min()} 至 {df['traded_at'].max()}\n")
            f.write(f"  总成交量: {df['quantity'].sum():.8f}\n")
            f.write(f"  总成交额: {df['quote_quantity'].sum():.8f}\n")

        print(f"\n✅ 分析摘要已保存: {summary_file}")

    def run_full_analysis(self, **kwargs):
        """运行完整分析"""
        print("\n" + "="*80)
        print("🚀 开始完整成交数据分析")
        print("="*80)

        # 获取数据
        df = self.get_basic_stats(**kwargs)
        if df is None:
            return

        # 运行各项分析
        self.analyze_frequency(df)
        self.analyze_time_distribution(df)
        self.analyze_volume_distribution(df)
        self.analyze_kline_feasibility(df)
        self.export_summary(df)

        print("\n" + "="*80)
        print("✅ 分析完成！所有图表已保存到: " + str(self.output_dir))
        print("="*80 + "\n")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='成交数据分析工具')
    parser.add_argument('--symbol', type=str, help='交易对符号')
    parser.add_argument('--strategy', type=str, help='策略名称')
    parser.add_argument('--hours', type=int, default=24, help='分析最近N小时的数据（默认24）')
    parser.add_argument('--start', type=str, help='开始时间 (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end', type=str, help='结束时间 (YYYY-MM-DD HH:MM:SS)')

    args = parser.parse_args()

    # 处理时间参数
    end_time = datetime.now()
    if args.end:
        end_time = datetime.strptime(args.end, '%Y-%m-%d %H:%M:%S')

    start_time = end_time - timedelta(hours=args.hours)
    if args.start:
        start_time = datetime.strptime(args.start, '%Y-%m-%d %H:%M:%S')

    # 运行分析
    analyzer = TradeAnalyzer()
    analyzer.run_full_analysis(
        symbol=args.symbol,
        strategy=args.strategy,
        start_time=start_time,
        end_time=end_time
    )


if __name__ == '__main__':
    main()
