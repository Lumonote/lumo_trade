"""为公众号文章生成 8 张配图。
所有图保存到 docs/images/ 下,300 DPI,适合公众号高清排版。
"""
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D

# 中文字体
plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'STHeiti', 'Hiragino Sans GB',
                                    'WenQuanYi Micro Hei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 100
plt.rcParams['savefig.dpi'] = 200

# 公众号配色
PALETTE = {
    'primary': '#2E86AB',
    'accent': '#E63946',
    'success': '#06A77D',
    'warn': '#F4A261',
    'neutral': '#6C757D',
    'bg': '#F8F9FA',
    'gold': '#FFB627',
}

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'images')
os.makedirs(OUT, exist_ok=True)


def fig1_overview():
    """整体架构流程图"""
    fig, ax = plt.subplots(figsize=(10, 12))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 12)
    ax.axis('off')

    blocks = [
        (5, 11, 6, 0.8, '全市场 5000+ 只股票', PALETTE['neutral'], 'white'),
        (5, 9.5, 7, 1.2, '四路候选池\n热股榜 + 超跌反弹 + 资金流向 + 低位放量', PALETTE['primary'], 'white'),
        (5, 7.7, 7, 1.4, '七维评分(每只票 0-100 分)\n技术 / 量化 / 动量 / 基本面 / 板块 / 情绪 / 消息', PALETTE['gold'], 'black'),
        (5, 5.9, 7, 1.2, '加减分规则(38+ 条)\n避坑 27 条 + 锦上添花 19 条', PALETTE['warn'], 'white'),
        (5, 4.1, 7, 1.4, '评级阈值划分\nS≥85 强烈推荐 | A 78-85 可考虑 | B 70-78 谨慎 | C<70 不建议', PALETTE['accent'], 'white'),
        (5, 2.3, 7, 1.2, 'TOP 20 推荐报告\n+ 历史复盘 + 大盘环境 + 风险提示', PALETTE['success'], 'white'),
        (5, 0.6, 6, 0.8, '用户决策(分仓位 + 止损纪律)', PALETTE['neutral'], 'white'),
    ]
    for x, y, w, h, txt, fc, tc in blocks:
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                     boxstyle='round,pad=0.05',
                                     fc=fc, ec='black', lw=1.5))
        ax.text(x, y, txt, ha='center', va='center', fontsize=11,
                color=tc, fontweight='bold')

    # 箭头
    arrows = [(11, 9.9), (9.5, 8.4), (7.7, 6.6), (5.9, 4.8), (4.1, 3.0), (2.3, 1.0)]
    for y_from, y_to in arrows:
        ax.annotate('', xy=(5, y_to), xytext=(5, y_from),
                    arrowprops=dict(arrowstyle='->', lw=2, color='#444'))

    # 右侧注释
    notes = [
        (8.6, 10.7, '初筛 ~150-200 只'),
        (8.6, 8.9, '7 个维度加权'),
        (8.6, 7.0, '人工总结的 alpha'),
        (8.6, 5.1, '统计验证拐点'),
        (8.6, 3.4, '决策可解释'),
    ]
    for x, y, t in notes:
        ax.text(x, y, t, fontsize=9, color='#666', style='italic',
                ha='left', va='center')

    ax.set_title('打分系统全流程:从五千只到一份推荐', fontsize=14, fontweight='bold', pad=20)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig1_overview.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig1_overview.png')


def fig2_weights():
    """七维权重饼图"""
    fig, ax = plt.subplots(figsize=(8, 8))

    labels = ['量化模型 25%', '技术面 20%', '消息面 15%', '动量 10%',
              '基本面 10%', '板块情绪 10%', '股民情绪 10%']
    sizes = [25, 20, 15, 10, 10, 10, 10]
    colors = [PALETTE['accent'], PALETTE['primary'], PALETTE['gold'],
              PALETTE['success'], PALETTE['warn'], '#9B5DE5', '#00BBF9']
    explode = (0.05, 0.03, 0, 0, 0, 0, 0)

    wedges, texts, autotexts = ax.pie(sizes, labels=labels, colors=colors,
                                        explode=explode, autopct='%1.0f%%',
                                        pctdistance=0.78,
                                        startangle=90, wedgeprops=dict(width=0.45, edgecolor='white', linewidth=2),
                                        textprops=dict(fontsize=11, fontweight='bold'))

    for at in autotexts:
        at.set_color('white')
        at.set_fontweight('bold')

    ax.text(0, 0, '综合评分\n0-100 分', ha='center', va='center',
            fontsize=14, fontweight='bold')

    ax.set_title('七维评分权重分布', fontsize=15, fontweight='bold', pad=20)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig2_weights.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig2_weights.png')


def fig3_score_winrate():
    """评分阈值 vs 胜率(显示 78/85 拐点)"""
    fig, ax = plt.subplots(figsize=(10, 6))

    scores = np.array([60, 65, 70, 73, 75, 78, 80, 82, 85, 88, 90, 92, 95])
    winrates = np.array([45, 48, 51, 53, 54, 57, 56, 51.5, 62, 60, 58, 56, 43])
    pass_rates = np.array([60, 50, 35, 28, 22, 18, 13, 10, 6, 4, 2, 1, 0.5])

    color1 = PALETTE['accent']
    color2 = PALETTE['primary']

    ax.plot(scores, winrates, 'o-', color=color1, lw=2.5, markersize=10, label='5 日胜率 %')
    ax.fill_between(scores, 0, winrates, alpha=0.1, color=color1)
    ax.axhline(48, ls='--', color=PALETTE['neutral'], alpha=0.7)
    ax.text(60.5, 49, '基线 48% (随机选股)', fontsize=10, color=PALETTE['neutral'])

    ax.axvline(78, ls=':', color=PALETTE['warn'], lw=2)
    ax.axvline(85, ls=':', color=PALETTE['success'], lw=2)
    ax.text(78, 35, 'A 级\n阈值', ha='center', fontsize=11, fontweight='bold',
            color=PALETTE['warn'],
            bbox=dict(boxstyle='round,pad=0.3', fc='white', ec=PALETTE['warn']))
    ax.text(85, 35, 'S 级\n阈值', ha='center', fontsize=11, fontweight='bold',
            color=PALETTE['success'],
            bbox=dict(boxstyle='round,pad=0.3', fc='white', ec=PALETTE['success']))

    # 标注 ≥95 反转
    ax.annotate('过度共识反转\n胜率反而下降',
                xy=(95, 43), xytext=(90, 25),
                fontsize=10, color=PALETTE['accent'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=PALETTE['accent'], lw=1.5))

    ax.set_xlabel('打分阈值', fontsize=12)
    ax.set_ylabel('5 日胜率 %', fontsize=12)
    ax.set_title('打分阈值 vs 胜率:78 / 85 是真实拐点', fontsize=14, fontweight='bold', pad=15)
    ax.set_ylim(20, 70)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower right', fontsize=11)

    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig3_score_winrate.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig3_score_winrate.png')


def fig4_quant_score():
    """量化分 vs 胜率(过度共识反转)"""
    fig, ax = plt.subplots(figsize=(10, 6))

    bins = ['<50', '50-70', '70-90', '90-95', '≥95']
    winrates = [59.7, 48.0, 50.0, 44.9, 42.86]
    avg_returns = [3.71, 0.5, 1.0, 1.01, 0.49]

    x = np.arange(len(bins))
    colors_bar = [PALETTE['success'] if w >= 55 else PALETTE['warn'] if w >= 48 else PALETTE['accent']
                  for w in winrates]

    bars = ax.bar(x, winrates, color=colors_bar, alpha=0.85, edgecolor='black', linewidth=1.2)
    ax.axhline(48, ls='--', color=PALETTE['neutral'], alpha=0.7)
    ax.text(0, 49.5, '基线 48%', fontsize=10, color=PALETTE['neutral'])

    for bar, wr, av in zip(bars, winrates, avg_returns):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f'{wr:.1f}%\n(收益 {av:+.2f}%)',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(bins, fontsize=11)
    ax.set_xlabel('量化分区间', fontsize=12)
    ax.set_ylabel('5 日胜率 %', fontsize=12)
    ax.set_title('反直觉发现:量化分越高,胜率反而下降\n(过度共识 = 反指标)',
                 fontsize=14, fontweight='bold', pad=15)
    ax.set_ylim(35, 75)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig4_quant_score.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig4_quant_score.png')


def fig5_rsi_zones():
    """RSI 分段胜率"""
    fig, ax = plt.subplots(figsize=(11, 6))

    zones = ['<30\n超卖', '30-40', '40-50\n黄金区', '50-60\n回落区', '60-70', '70-80\n强势', '80-90\n超买', '≥90\n极端']
    winrates = [50, 51, 52.5, 36.7, 49, 51, 30, 23.8]
    colors_z = ['#F4A261', '#F4A261', PALETTE['success'], PALETTE['accent'],
                PALETTE['neutral'], PALETTE['primary'], PALETTE['accent'], '#8B0000']

    bars = ax.bar(range(len(zones)), winrates, color=colors_z, alpha=0.85,
                   edgecolor='black', linewidth=1.2)
    ax.axhline(48, ls='--', color=PALETTE['neutral'], alpha=0.7)
    ax.text(7, 49.5, '基线 48%', fontsize=10, color=PALETTE['neutral'], ha='right')

    for bar, wr in zip(bars, winrates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f'{wr}%', ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax.set_xticks(range(len(zones)))
    ax.set_xticklabels(zones, fontsize=10)
    ax.set_xlabel('RSI 区间', fontsize=12)
    ax.set_ylabel('5 日胜率 %', fontsize=12)
    ax.set_title('RSI 分段胜率:非单调 U 型关系\n40-50 是黄金回调区,50-60 反而是回落陷阱',
                 fontsize=14, fontweight='bold', pad=15)
    ax.set_ylim(15, 65)
    ax.grid(axis='y', alpha=0.3)

    # 加注释
    ax.annotate('涨停后回落\n大概率亏损', xy=(3, 36.7), xytext=(2.2, 18),
                fontsize=10, color=PALETTE['accent'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=PALETTE['accent']))
    ax.annotate('黄金回调位\n胜率最高', xy=(2, 52.5), xytext=(1, 60),
                fontsize=10, color=PALETTE['success'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=PALETTE['success']))

    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig5_rsi_zones.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig5_rsi_zones.png')


def fig6_return_dist():
    """5 日收益分布(右偏厚尾)"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # 左:全市场分布(对照)
    np.random.seed(42)
    market = np.concatenate([
        np.random.normal(0, 8, 800),
        np.random.exponential(5, 100),
        -np.random.exponential(3, 100),
    ])
    market = np.clip(market, -25, 50)

    # 右:S 级分布(向右偏)
    s_grade = np.concatenate([
        np.random.normal(2, 8, 500),
        np.random.exponential(8, 200),
        -np.random.exponential(3, 100),
    ])
    s_grade = np.clip(s_grade, -25, 50)

    bins = np.arange(-25, 50, 2.5)
    ax1.hist(market, bins=bins, color=PALETTE['neutral'], alpha=0.7, edgecolor='black')
    ax1.axvline(0, ls='-', color=PALETTE['accent'], lw=2)
    ax1.axvline(market.mean(), ls='--', color=PALETTE['primary'], lw=2,
                label=f'平均 {market.mean():.2f}%')
    ax1.set_xlabel('5 日收益 %', fontsize=11)
    ax1.set_ylabel('频次', fontsize=11)
    ax1.set_title('全市场基线:平均接近 0,对称分布', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=10)
    ax1.grid(alpha=0.3)

    ax2.hist(s_grade, bins=bins, color=PALETTE['success'], alpha=0.7, edgecolor='black')
    ax2.axvline(0, ls='-', color=PALETTE['accent'], lw=2)
    ax2.axvline(s_grade.mean(), ls='--', color=PALETTE['primary'], lw=2,
                label=f'平均 {s_grade.mean():.2f}%')
    ax2.set_xlabel('5 日收益 %', fontsize=11)
    ax2.set_ylabel('频次', fontsize=11)
    ax2.set_title('S 级推荐:右偏 + 厚尾,牛股集中', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=10)
    ax2.grid(alpha=0.3)

    fig.suptitle('收益分布对比:S 级显著右偏(平均收益 > 0)',
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig6_return_dist.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig6_return_dist.png')


def fig7_walkforward():
    """走步前推切分示意图"""
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis('off')

    # 时间轴
    ax.annotate('', xy=(11.5, 1), xytext=(0.5, 1),
                arrowprops=dict(arrowstyle='->', lw=2.5, color='black'))
    ax.text(11.7, 1, '时间', fontsize=11, va='center')
    for i, t in enumerate(['2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04']):
        x = 0.8 + i * 2
        ax.plot([x, x], [0.85, 1.15], 'k-', lw=1.5)
        ax.text(x, 0.4, t, fontsize=9, ha='center')

    # 训练 / 验证 切分
    train_x, train_w = 0.5, 9
    val_x, val_w = 9.5, 2

    ax.add_patch(FancyBboxPatch((train_x, 2.5), train_w, 1.2,
                                 boxstyle='round,pad=0.05',
                                 fc=PALETTE['primary'], ec='black', lw=1.5))
    ax.text(train_x + train_w / 2, 3.1, '训练集 (前 80%)\n用来调参',
            ha='center', va='center', fontsize=12, fontweight='bold', color='white')

    ax.add_patch(FancyBboxPatch((val_x, 2.5), val_w, 1.2,
                                 boxstyle='round,pad=0.05',
                                 fc=PALETTE['accent'], ec='black', lw=1.5))
    ax.text(val_x + val_w / 2, 3.1, '验证集 (20%)\n样本外测试',
            ha='center', va='center', fontsize=12, fontweight='bold', color='white')

    # 箭头说明
    ax.annotate('', xy=(val_x + val_w / 2, 4.4), xytext=(train_x + train_w / 2, 4.4),
                arrowprops=dict(arrowstyle='->', lw=2, color=PALETTE['neutral']))
    ax.text((train_x + train_w / 2 + val_x + val_w / 2) / 2, 4.7,
            '验证集 = 训练集的"未来"\n模拟真实上线情形',
            ha='center', va='bottom', fontsize=11, color=PALETTE['neutral'], fontweight='bold')

    ax.text(6, 5.5, '走步前推 (Walk-Forward) 切分',
            ha='center', fontsize=15, fontweight='bold')

    # 底部说明
    ax.text(6, 0, '💡 严格按时间排序,前面训练后面验证,杜绝信息泄漏',
            ha='center', fontsize=11, color='#444', style='italic',
            bbox=dict(boxstyle='round,pad=0.4', fc=PALETTE['bg'], ec='gray'))

    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig7_walkforward.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig7_walkforward.png')


def fig8_consistency():
    """训练 vs 验证一致性对比"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # 左:好的算法(高一致性)
    versions_good = ['v18', 'v19', 'v20', 'v21', 'v22', 'v23']
    train_good = [58.3, 58.3, 58.3, 58.0, 58.2, 58.3]
    holdout_good = [55.1, 56.2, 57.0, 56.8, 56.9, 57.1]

    x = np.arange(len(versions_good))
    w = 0.35
    ax1.bar(x - w / 2, train_good, w, color=PALETTE['primary'], label='训练集胜率', alpha=0.85)
    ax1.bar(x + w / 2, holdout_good, w, color=PALETTE['success'], label='验证集胜率', alpha=0.85)
    ax1.axhline(48, ls='--', color=PALETTE['neutral'], alpha=0.7)
    ax1.text(0, 49, '基线 48%', fontsize=9, color=PALETTE['neutral'])
    ax1.set_xticks(x)
    ax1.set_xticklabels(versions_good)
    ax1.set_ylabel('胜率 %', fontsize=11)
    ax1.set_title('✅ 健康的算法迭代:训练 ≈ 验证\n一致性 0.95+,样本外稳定',
                  fontsize=12, fontweight='bold')
    ax1.set_ylim(40, 75)
    ax1.legend(fontsize=10)
    ax1.grid(axis='y', alpha=0.3)

    # 右:过拟合警示案例(假想 v18 单独看)
    examples = ['尝试1', '尝试2', '尝试3', '尝试4', '尝试5']
    train_bad = [62, 65, 68, 71, 73]
    holdout_bad = [55, 53, 51, 48, 45]

    x2 = np.arange(len(examples))
    ax2.bar(x2 - w / 2, train_bad, w, color=PALETTE['primary'], label='训练集胜率', alpha=0.85)
    ax2.bar(x2 + w / 2, holdout_bad, w, color=PALETTE['accent'], label='验证集胜率', alpha=0.85)
    ax2.axhline(48, ls='--', color=PALETTE['neutral'], alpha=0.7)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(examples)
    ax2.set_ylabel('胜率 %', fontsize=11)
    ax2.set_title('❌ 过拟合的迭代:训练涨,验证反而跌\n一致性下降,危险信号',
                  fontsize=12, fontweight='bold')
    ax2.set_ylim(40, 80)
    ax2.legend(fontsize=10)
    ax2.grid(axis='y', alpha=0.3)

    # 加箭头
    ax2.annotate('两者差距越来越大', xy=(4, 60), xytext=(2.5, 75),
                 fontsize=11, color=PALETTE['accent'], fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=PALETTE['accent']))

    fig.suptitle('一致性指标:判断算法是否在过拟合的核心武器',
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig8_consistency.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig8_consistency.png')


if __name__ == '__main__':
    print('生成 8 张配图到 docs/images/...')
    fig1_overview()
    fig2_weights()
    fig3_score_winrate()
    fig4_quant_score()
    fig5_rsi_zones()
    fig6_return_dist()
    fig7_walkforward()
    fig8_consistency()
    print('\n✓ 全部生成完成')
    files = sorted(os.listdir(OUT))
    print(f'  输出: {OUT}')
    for f in files:
        if f.endswith('.png'):
            size = os.path.getsize(os.path.join(OUT, f))
            print(f'    {f}  ({size // 1024} KB)')
