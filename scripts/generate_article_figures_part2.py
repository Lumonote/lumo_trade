"""为公众号文章追加生成 6 张图,替换大块 ASCII 流程图。"""
import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'STHeiti', 'SimHei',
                                    'Hiragino Sans GB', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['savefig.dpi'] = 200

PALETTE = {
    'primary': '#2E86AB', 'accent': '#E63946', 'success': '#06A77D',
    'warn': '#F4A261', 'neutral': '#6C757D', 'gold': '#FFB627',
    'purple': '#9B5DE5', 'cyan': '#00BBF9', 'rose': '#F072A1',
}

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'images')


def fig9_models():
    """30 个量化模型分组"""
    fig, ax = plt.subplots(figsize=(11, 9))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 9)
    ax.axis('off')

    groups = [
        (1, 7.7, 5.0, '趋势类(4)', '海龟交易、CTA趋势、ATR动量、Elder射线', '共振 → 大趋势启动', PALETTE['accent']),
        (6.5, 7.7, 5.0, '均线类(4)', '均量双动、多排突破、均线共振、分形MA', '共振 → 多周期同向', PALETTE['primary']),
        (1, 5.6, 5.0, '量价类(4)', '量能突破、VWAP偏离、量价趋势、切金资金', '共振 → 主力资金行为', PALETTE['gold']),
        (6.5, 5.6, 5.0, '震荡类(4)', 'RSI背离、随机动量、布林挤压、抛物SAR', '共振 → 反转信号', PALETTE['success']),
        (1, 3.5, 5.0, '统计类(3)', '机器学习RF、多因子Alpha、统计量化', '共振 → 计量经济', PALETTE['purple']),
        (6.5, 3.5, 5.0, '结构类(3)', '一目均衡云、六维共振、轴心MACD', '共振 → 多周期共振', PALETTE['cyan']),
        (1, 1.4, 5.0, '微观类(2)', '高频微观结构、配对交易套利', '共振 → 订单簿行为', PALETTE['rose']),
        (6.5, 1.4, 5.0, '其他(6)', '支撑阻力、趋势回踩、超级反转、资金趋势...', '辅助补充', PALETTE['neutral']),
    ]
    for x, y, w, title, members, role, color in groups:
        ax.add_patch(FancyBboxPatch((x, y), w, 1.7, boxstyle='round,pad=0.05',
                                     fc=color, alpha=0.18, ec=color, lw=2))
        ax.text(x + 0.2, y + 1.4, title, fontsize=12, fontweight='bold', color=color, va='center')
        ax.text(x + 0.2, y + 0.9, members, fontsize=10, color='#222')
        ax.text(x + 0.2, y + 0.4, '▸ ' + role, fontsize=10, color=color, fontweight='bold', style='italic')

    ax.set_title('30 个量化模型分组:七大风格,降低组内相关性', fontsize=15, fontweight='bold', pad=20)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig9_models.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig9_models.png')


def _rule_card(rules, title, color, filename, subtitle=''):
    """通用规则卡片绘图"""
    n = len(rules)
    fig, ax = plt.subplots(figsize=(9, 0.55 * n + 1.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 0.55 * n + 1.4)
    ax.axis('off')

    # 标题
    ax.add_patch(FancyBboxPatch((0.2, 0.55 * n + 0.6), 9.6, 0.7,
                                 boxstyle='round,pad=0.05',
                                 fc=color, ec=color, lw=1.5))
    ax.text(5, 0.55 * n + 0.95, title, ha='center', va='center',
            fontsize=14, fontweight='bold', color='white')
    if subtitle:
        ax.text(5, 0.55 * n + 0.3, subtitle, ha='center', va='center',
                fontsize=10, color='#666', style='italic')

    # 规则行
    for i, (cond, val, note) in enumerate(rules):
        y = 0.55 * (n - 1 - i) + 0.15
        ax.add_patch(FancyBboxPatch((0.2, y), 9.6, 0.45,
                                     boxstyle='round,pad=0.02',
                                     fc='white', ec='#ccc', lw=1))
        ax.text(0.5, y + 0.22, cond, fontsize=11, va='center', fontweight='bold')
        # 分值
        val_color = color if val.startswith('+') or val.startswith('-') else '#444'
        ax.text(5.5, y + 0.22, val, fontsize=11, va='center',
                fontweight='bold', color=val_color)
        ax.text(6.7, y + 0.22, note, fontsize=10, va='center', color='#666')

    plt.tight_layout()
    plt.savefig(os.path.join(OUT, filename), bbox_inches='tight', facecolor='white')
    plt.close()


def fig10_penalties():
    rules = [
        ('RSI ≥ 80', '-15 分', '极端超买'),
        ('RSI 50-60', '-4 分', '回落区(涨停次日)'),
        ('当日涨幅 ≥ 19.5%', '-20 分', '暴涨'),
        ('连板涨停(3日 ≥ 15%)', '-5 分', '透支'),
        ('3 日涨幅 > 20%', '-8 分', '透支'),
        ('5 日涨幅 > 25%', '-15 分', '暴涨'),
        ('板块得分 60-75', '-10 分', '死区,资金没方向'),
        ('板块得分 ≥ 95', '-12 分', '过热'),
        ('卖出信号 ≥ 3 个', '-5 分', '空头多'),
        ('量化分 ≥ 95(回测)', '-18 分', '过度共识反指标'),
        ('评分 > 95', '强制压回 95', '防止冲顶'),
    ]
    _rule_card(rules, '核心扣分规则(避坑)', PALETTE['accent'], 'fig10_penalties.png',
               '基于 1500+ 样本统计验证 · 显著反向因子')
    print('  ✓ fig10_penalties.png')


def fig11_bonuses():
    rules = [
        ('RSI 40-50(黄金回调区)', '+4 分', '胜率 52.5%'),
        ('RSI 60-80(强势区)', '+3 分', '正常上涨'),
        ('追高风险 ≥ 75(强动量)', '+4 分', '胜率 54.3%'),
        ('追高风险 ≥ 50(中动量)', '+2 分', '胜率 50%'),
        ('趋势确认(多头排列+放量)', '+12 分', '强信号'),
        ('连续放量上涨 3 日', '+15 分', '强趋势'),
        ('涨停首板 + 低追高', '+10 分', '妖股启动'),
        ('涨停首板 + 高追高', '+8 分', '胜率 51%'),
        ('MACD 金叉 + RSI 黄金区', '+6 分', '共振'),
        ('量化净买入 ≥ 10 个', '+12 分', '集成共振'),
        ('零卖出信号(sell=0)', '+4 分', '胜率 53.8%'),
        ('涨停 + 零卖出', '+8 分', '胜率 66.7%(最强组合)'),
    ]
    _rule_card(rules, '核心加分规则(锦上添花)', PALETTE['success'], 'fig11_bonuses.png',
               '基于实测胜率 · 显著正向因子')
    print('  ✓ fig11_bonuses.png')


def fig12_backtest():
    """回测 4 步流程图"""
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7.5)
    ax.axis('off')

    steps = [
        (6.5, 'Step 1', '取过去几个月所有历史推荐报告', PALETTE['primary'], '~1500 条样本'),
        (5.0, 'Step 2', 'Tushare 拉每只票的:\n  • 报告次日开盘价(买入价)\n  • 第 5 个交易日收盘价(卖出价)', PALETTE['gold'], '真实行情数据'),
        (3.2, 'Step 3', '计算每笔交易收益:\n  收益 = (卖出价 - 买入价) / 买入价', PALETTE['warn'], '单笔回报'),
        (1.2, 'Step 4', '按评级分组,统计:\n  胜率 / 平均收益 / 最大盈亏 / 年化估算', PALETTE['success'], '决策依据'),
    ]
    for y, label, content, color, note in steps:
        # 序号圆圈
        from matplotlib.patches import Circle
        ax.add_patch(Circle((1.3, y + 0.5), 0.45, fc=color, ec='black', lw=1.5))
        ax.text(1.3, y + 0.5, label.split(' ')[1], fontsize=14, fontweight='bold',
                color='white', ha='center', va='center')
        # 内容框
        ax.add_patch(FancyBboxPatch((2.2, y), 8, 1.0, boxstyle='round,pad=0.05',
                                     fc=color, alpha=0.18, ec=color, lw=2))
        ax.text(2.5, y + 0.5, content, fontsize=11, va='center', color='#222')
        # 右侧注释
        ax.text(10.5, y + 0.5, note, fontsize=10, color=color, fontweight='bold',
                style='italic', ha='left', va='center')

    # 箭头连接
    for y in [5.0, 3.2, 1.2]:
        ax.annotate('', xy=(1.3, y + 1.1), xytext=(1.3, y + 1.45),
                    arrowprops=dict(arrowstyle='->', lw=2, color='#444'))

    ax.set_title('回测系统:从历史报告到性能验证(4 步)', fontsize=15, fontweight='bold', pad=15)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig12_backtest.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig12_backtest.png')


def fig13_kfold_leak():
    """K 折信息泄漏问题"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # 左:错误的随机切分
    ax1.set_xlim(0, 10)
    ax1.set_ylim(0, 6)
    ax1.axis('off')
    ax1.text(5, 5.5, '❌ 随机切分(K-Fold):信息泄漏', ha='center',
             fontsize=13, fontweight='bold', color=PALETTE['accent'])
    # 模拟同一天的多只股票被分散到 train/val
    days = ['Day 1', 'Day 2', 'Day 3', 'Day 4']
    for i, d in enumerate(days):
        y = 4 - i * 1.0
        ax1.text(0.5, y + 0.3, d, fontsize=10, fontweight='bold', va='center')
        # 每天有 5 只票,随机分布
        for j in range(5):
            x = 1.8 + j * 1.5
            color = PALETTE['primary'] if (i + j) % 3 != 0 else PALETTE['accent']
            label = 'T' if (i + j) % 3 != 0 else 'V'
            ax1.add_patch(FancyBboxPatch((x, y), 1.2, 0.6, boxstyle='round,pad=0.03',
                                          fc=color, alpha=0.7, ec='black'))
            ax1.text(x + 0.6, y + 0.3, label, ha='center', va='center',
                     fontsize=11, fontweight='bold', color='white')
    ax1.text(5, 0.4, '同一天的样本分散到 训练(T) 和 验证(V)\n大盘涨跌信息从训练集泄漏到验证集',
             ha='center', fontsize=10, color=PALETTE['accent'], style='italic',
             fontweight='bold')

    # 右:正确的走步前推
    ax2.set_xlim(0, 10)
    ax2.set_ylim(0, 6)
    ax2.axis('off')
    ax2.text(5, 5.5, '✅ 走步前推(Walk-Forward):零泄漏', ha='center',
             fontsize=13, fontweight='bold', color=PALETTE['success'])
    for i, d in enumerate(days):
        y = 4 - i * 1.0
        ax2.text(0.5, y + 0.3, d, fontsize=10, fontweight='bold', va='center')
        # 前 3 天全是 T,最后一天全是 V
        is_val = (i == 3)
        for j in range(5):
            x = 1.8 + j * 1.5
            color = PALETTE['accent'] if is_val else PALETTE['primary']
            label = 'V' if is_val else 'T'
            ax2.add_patch(FancyBboxPatch((x, y), 1.2, 0.6, boxstyle='round,pad=0.03',
                                          fc=color, alpha=0.7, ec='black'))
            ax2.text(x + 0.6, y + 0.3, label, ha='center', va='center',
                     fontsize=11, fontweight='bold', color='white')
    ax2.text(5, 0.4, '严格按时间顺序:前面训练(T),后面验证(V)\n验证集是训练的"未来",模拟真实上线',
             ha='center', fontsize=10, color=PALETTE['success'], style='italic',
             fontweight='bold')

    fig.suptitle('为什么标准 K 折在股票上失效?同日横截面相关性导致信息泄漏',
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig13_kfold_leak.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig13_kfold_leak.png')


def fig14_optimizer():
    """4 轮参数优化流程"""
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8.5)
    ax.axis('off')

    rounds = [
        (7.0, 'Round 1', '单参数扫描', '每个参数独立扫,找出最敏感的\n复杂度 O(P × V),约 200 次评估', PALETTE['primary']),
        (5.0, 'Round 2', '精细化迭代', '在 Round 1 最优解附近做 ±1, ±2 步长\n迭代直到目标函数不再提升', PALETTE['gold']),
        (3.0, 'Round 3', '组合搜索', '只对相关参数对做组合枚举\n例如 RSI 系列 4 参数:5×5×5×5=625', PALETTE['warn']),
        (1.0, 'Round 4', '阈值搜索', '固定参数,扫 78 / 85 这种决策门槛\n找最优截断点', PALETTE['success']),
    ]
    for y, label, title, content, color in rounds:
        # 圆形序号
        from matplotlib.patches import Circle
        ax.add_patch(Circle((1.3, y + 0.6), 0.55, fc=color, ec='black', lw=1.5))
        ax.text(1.3, y + 0.6, label.split(' ')[1], fontsize=14, fontweight='bold',
                color='white', ha='center', va='center')
        # 标题 + 内容
        ax.add_patch(FancyBboxPatch((2.4, y), 8.5, 1.2, boxstyle='round,pad=0.05',
                                     fc=color, alpha=0.18, ec=color, lw=2))
        ax.text(2.7, y + 0.85, title, fontsize=13, fontweight='bold', color=color)
        ax.text(2.7, y + 0.35, content, fontsize=10.5, color='#222')

    # 箭头连接
    for y in [5.0, 3.0, 1.0]:
        ax.annotate('', xy=(1.3, y + 1.3), xytext=(1.3, y + 1.65),
                    arrowprops=dict(arrowstyle='->', lw=2, color='#444'))

    ax.set_title('参数优化:四轮 grid search 逐步逼近最优',
                 fontsize=15, fontweight='bold', pad=15)
    # 底部说明
    ax.text(6, 0.1, '💡 多轮分而治之比"一次大组合搜索"更可靠,且每轮产出明确、可调试',
            ha='center', fontsize=11, color='#444', style='italic')
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, 'fig14_optimizer.png'), bbox_inches='tight', facecolor='white')
    plt.close()
    print('  ✓ fig14_optimizer.png')


if __name__ == '__main__':
    print('追加生成 6 张图...')
    fig9_models()
    fig10_penalties()
    fig11_bonuses()
    fig12_backtest()
    fig13_kfold_leak()
    fig14_optimizer()
    print('\n✓ 全部生成完成')
