import numpy as np
import pandas as pd
import json
import os
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# ------------------------- Параметры модели -------------------------
CONFIG = {
    'n_students':      30,
    'n_labs':          10,
    'n_weeks':         30,
    'slots_per_week':  20,
    'points_per_lab':  5,
    'n_runs':          10_000,
    'base_seed':       42,
    'out_dir':         'sim_results',
}

DEADLINES = [k * 3 - 1 for k in range(1, CONFIG['n_labs'] + 1)]

# Границы оценок (включая нижнюю, исключая верхнюю, кроме последней)
GRADE_BOUNDS = [
    ('Двойка (0–24)',  0,  24, 'crimson'),
    ('Тройка (25–32)', 25, 32, 'orange'),
    ('Четвёрка (33–44)', 33, 44, 'deepskyblue'),
    ('Пятёрка (45–50)', 45, 50, 'green'),
]


def simulate_once(seed, config):
    rng = np.random.default_rng(seed)
    n_students = config['n_students']
    n_labs     = config['n_labs']
    n_weeks    = config['n_weeks']
    slots      = config['slots_per_week']
    pt_max     = config['points_per_lab']

    probs       = rng.uniform(0.0, 1.0, n_students)
    current_lab = np.zeros(n_students, dtype=np.int32)
    points      = np.zeros(n_students, dtype=np.int32)
    deadlines   = np.array(DEADLINES, dtype=np.int32)

    for week in range(1, n_weeks + 1):
        active = np.where(current_lab < n_labs)[0]
        if active.size == 0:
            break
        labs_now   = current_lab[active]
        priorities = deadlines[labs_now] - week
        tiebreak   = rng.uniform(0.0, 1.0, active.size)
        order      = np.lexsort((tiebreak, priorities))
        selected   = active[order[:slots]]

        rolls   = rng.uniform(0.0, 1.0, selected.size)
        success = rolls < probs[selected]

        for j in np.where(success)[0]:
            s = selected[j]
            lab = current_lab[s]
            weeks_late = max(0, week - deadlines[lab])
            earned     = max(0, pt_max - weeks_late)
            points[s]      += earned
            current_lab[s] += 1

    return points


# ------------------------- Построение гистограммы -------------------------
def plot_histogram(df_hist, out_path):
    """Гистограмма распределения баллов с раскраской по оценкам."""
    fig, ax = plt.subplots(figsize=(15, 6.5))

    colors = []
    for s in df_hist['score']:
        c = None
        for _, lo, hi, col in GRADE_BOUNDS:
            if lo <= s <= hi:
                c = col
                break
        colors.append(c)

    bars = ax.bar(df_hist['score'], df_hist['count'],
                  color=colors, edgecolor='black', linewidth=0.4)

    max_count = df_hist['count'].max()
    for bar, cnt in zip(bars, df_hist['count']):
        if cnt > 0 and cnt >= max_count * 0.02:
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max_count * 0.005,
                    f'{int(cnt)}',
                    ha='center', va='bottom', fontsize=7, rotation=90)

    ax.set_xlabel('Баллы (0–50)', fontsize=12)
    ax.set_ylabel('Количество студентов (сумма за все прогоны)', fontsize=12)
    ax.set_title(
        f"Распределение итоговых баллов за семестр "
        f"(всего прогонов: {CONFIG['n_runs']:,}, студентов на прогон: {CONFIG['n_students']})",
        fontsize=13
    )
    ax.set_xticks(range(0, 51, 2))
    ax.set_xlim(-1, 51)
    ax.grid(axis='y', alpha=0.3, linestyle='--')

    legend_elements = [
        Patch(facecolor=col, edgecolor='black', label=label)
        for label, _, _, col in GRADE_BOUNDS
    ]
    # Легенда ВНЕ области графика — под осью X, в одну строку
    ax.legend(handles=legend_elements,
              loc='upper center',
              bbox_to_anchor=(0.5, -0.12),
              ncol=4,
              fontsize=10,
              framealpha=0.95)

    # Даём место под легенду снизу
    fig.subplots_adjust(bottom=0.18, top=0.92)
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.show()

def plot_grade_distribution(df_hist, out_path):
    """Столбики: доля каждой оценки (2/3/4/5) в % от всех выставленных баллов."""
    labels, colors, counts = [], [], []
    for label, lo, hi, col in GRADE_BOUNDS:
        mask = (df_hist['score'] >= lo) & (df_hist['score'] <= hi)
        counts.append(int(df_hist.loc[mask, 'count'].sum()))
        labels.append(label)
        colors.append(col)

    total = sum(counts)
    percents = [c / total * 100 for c in counts]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(labels, percents, color=colors,
                  edgecolor='black', linewidth=0.6, width=0.65)

    # Подписи: процент + абсолютное число
    top = max(percents) if max(percents) > 0 else 1
    for bar, pct, cnt in zip(bars, percents, counts):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + top * 0.02,
                f'{pct:.2f}%\n({cnt:,})',
                ha='center', va='bottom', fontsize=11)

    ax.set_ylabel('Доля студентов, %', fontsize=12)
    ax.set_xlabel('Оценка (автомат)', fontsize=12)
    ax.set_title(
        f"Распределение автоматов по итогам {CONFIG['n_runs']:,} прогонов "
        f"({total:,} выставленных баллов)",
        fontsize=13
    )
    ax.set_ylim(0, top * 1.20)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=11)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.show()

    # Дополнительно — табличкой в CSV
    pd.DataFrame({
        'grade':      labels,
        'count':      counts,
        'percent':    [round(p, 4) for p in percents],
    }).to_csv(out_path.replace('.png', '.csv'), index=False)

    return list(zip(labels, counts, percents))


def main(config=None):
    if config is None:
        config = CONFIG
    os.makedirs(config['out_dir'], exist_ok=True)

    n_runs     = config['n_runs']
    n_students = config['n_students']
    base_seed  = config['base_seed']

    hist_total     = np.zeros(51, dtype=np.int64)
    per_run_stats  = []
    all_points_mat = np.zeros((n_runs, n_students), dtype=np.int8)

    for r in range(n_runs):
        seed = base_seed + r
        pts  = simulate_once(seed, config)
        all_points_mat[r] = pts
        hist_total += np.bincount(pts, minlength=51)

        per_run_stats.append({
            'run':    r,
            'seed':   seed,
            'mean':   float(pts.mean()),
            'median': float(np.median(pts)),
            'std':    float(pts.std(ddof=1)),
        })

        if (r + 1) % 1000 == 0:
            print(f"[{r + 1}/{n_runs}] прогонов готово")

    # ---------- Сохранение данных ----------
    np.save(os.path.join(config['out_dir'], 'all_points_raw.npy'), all_points_mat)

    df_hist = pd.DataFrame({'score': np.arange(51), 'count': hist_total})
    df_hist.to_csv(os.path.join(config['out_dir'], 'score_distribution.csv'), index=False)

    df_pr = pd.DataFrame(per_run_stats)
    df_pr.to_csv(os.path.join(config['out_dir'], 'per_run_stats.csv'), index=False)

    # ---------- Статистики ----------
    v1 = {
        'mean':   float(df_pr['mean'].mean()),
        'median': float(df_pr['median'].mean()),
        'std':    float(df_pr['std'].mean()),
    }
    flat = all_points_mat.flatten().astype(np.float64)
    v2 = {
        'mean':   float(flat.mean()),
        'median': float(np.median(flat)),
        'std':    float(flat.std(ddof=1)),
    }
    summary = {
        'config': {k: int(v) if isinstance(v, np.integer) else v
                   for k, v in config.items()},
        'deadlines_week_by_lab': {f'lab_{i+1}': d for i, d in enumerate(DEADLINES)},
        'variant_1_avg_of_per_run_stats': v1,
        'variant_2_from_pooled_data':     v2,
    }
    with open(os.path.join(config['out_dir'], 'summary_stats.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # ---------- Гистограмма ----------
    plot_histogram(df_hist, os.path.join(config['out_dir'], 'score_histogram.png'))

    grade_table = plot_grade_distribution(
        df_hist,
        os.path.join(config['out_dir'], 'grade_distribution.png'),
    )

    print("\n=== Автоматы (в % от всех баллов) ===")
    for label, cnt, pct in grade_table:
        print(f"  {label:>18}: {cnt:>10,}  ({pct:6.2f}%)")

    print("\n=== Итог ===")
    print("Variant 1 (avg по прогонам):", v1)
    print("Variant 2 (по объединённой выборке):", v2)
    print(f"Файлы в папке: {config['out_dir']}/")
    return summary


if __name__ == '__main__':
    main()