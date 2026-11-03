import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path("simulation_results")
OUT.mkdir(exist_ok=True)

# ---------------- Параметры ----------------
N_RUNS        = 10_000
N_STUDENTS    = 30
N_LABS        = 10
MAX_PER_DAY   = 20
N_WEEKS       = 30
SEED          = 20260427
THRESHOLD_5   = 45

# Стратегия очереди:
#   "chance_5" — сначала те, кто ещё может набрать >= 45 (шанс на 5),
#                внутри группы — по убыванию текущего балла;
#   "score"    — просто по убыванию балла (без приоритета 5);
#   "fair"     — случайно.
PRIORITY_MODE = "chance_5"

DEADLINES = np.array([lab * 3 - 1 for lab in range(1, N_LABS + 1)], dtype=int)


def grade_from_score(score: int) -> int:
    if score <= 24: return 2
    if score <= 32: return 3
    if score <= 44: return 4
    return 5


def pick_queue(rng, scores, next_lab):
    """Возвращает индексы студентов, которых проверяем на этой неделе."""
    active = np.flatnonzero(next_lab < N_LABS)
    if active.size == 0:
        return active
    if active.size <= MAX_PER_DAY:
        return active

    if PRIORITY_MODE == "fair":
        return rng.choice(active, size=MAX_PER_DAY, replace=False)

    # сколько ещё максимум можно набрать
    max_reach = scores[active] + 5 * (N_LABS - next_lab[active])

    if PRIORITY_MODE == "chance_5":
        chance_5 = (max_reach >= THRESHOLD_5).astype(int)
        tiebreak = rng.random(active.size)
        # lexsort: последний ключ — главный
        order = np.lexsort((tiebreak, -scores[active], -chance_5))
    elif PRIORITY_MODE == "score":
        tiebreak = rng.random(active.size)
        order = np.lexsort((tiebreak, -scores[active]))
    else:
        raise ValueError(PRIORITY_MODE)

    return active[order[:MAX_PER_DAY]]


# ---------------- Прогоны ----------------
per_run_rows = []
all_rows = []

for run_id in range(N_RUNS):
    rng = np.random.default_rng(SEED + run_id)

    p = rng.uniform(0.0, 1.0, size=N_STUDENTS)
    next_lab = np.zeros(N_STUDENTS, dtype=int)
    scores = np.zeros(N_STUDENTS, dtype=int)

    for week in range(1, N_WEEKS + 1):
        selected = pick_queue(rng, scores, next_lab)
        if selected.size == 0:
            break

        # одна попытка в неделю; если не попал в 20 — считается провал
        success = rng.random(selected.size) < p[selected]

        for sid, ok in zip(selected, success):
            if ok:
                lab = next_lab[sid]
                dl = DEADLINES[lab]
                late = max(0, week - dl)
                scores[sid] += max(0, 5 - late)
                next_lab[sid] += 1

    grades = np.array([grade_from_score(int(s)) for s in scores])
    per_run_rows.append({
        "run_id": run_id,
        "mean":   float(scores.mean()),
        "median": float(np.median(scores)),
        "std":    float(scores.std(ddof=0)),
        "count_2": int((grades == 2).sum()),
        "count_3": int((grades == 3).sum()),
        "count_4": int((grades == 4).sum()),
        "count_5": int((grades == 5).sum()),
    })
    for sid, s in enumerate(scores):
        all_rows.append({
            "run_id": run_id,
            "student_id": int(sid),
            "score": int(s),
            "grade": grade_from_score(int(s)),
        })

per_run_df = pd.DataFrame(per_run_rows)
all_df = pd.DataFrame(all_rows)

score_counts = (
    all_df["score"].value_counts()
    .reindex(range(0, 51), fill_value=0).sort_index()
    .rename_axis("score").reset_index(name="count")
)
grade_counts = (
    all_df["grade"].value_counts()
    .reindex([2, 3, 4, 5], fill_value=0).sort_index()
    .rename_axis("grade").reset_index(name="count")
)

summary = {
    "params": {
        "N_RUNS": N_RUNS, "N_STUDENTS": N_STUDENTS, "N_LABS": N_LABS,
        "MAX_PER_DAY": MAX_PER_DAY, "N_WEEKS": N_WEEKS, "SEED": SEED,
        "THRESHOLD_5": THRESHOLD_5, "PRIORITY_MODE": PRIORITY_MODE,
        "DEADLINES": DEADLINES.tolist(),
    },
    "per_run_stats_averaged": {
        "mean":   float(per_run_df["mean"].mean()),
        "median": float(per_run_df["median"].mean()),
        "std":    float(per_run_df["std"].mean()),
        "count_2_avg": float(per_run_df["count_2"].mean()),
        "count_3_avg": float(per_run_df["count_3"].mean()),
        "count_4_avg": float(per_run_df["count_4"].mean()),
        "count_5_avg": float(per_run_df["count_5"].mean()),
    },
    "pooled_stats": {
        "mean":   float(all_df["score"].mean()),
        "median": float(all_df["score"].median()),
        "std":    float(all_df["score"].std(ddof=0)),
    },
}

# ---------------- Сохранение ----------------
per_run_df.to_csv(OUT / "per_run_stats.csv", index=False)
all_df.to_csv(OUT / "all_scores.csv", index=False)
score_counts.to_csv(OUT / "pooled_score_counts.csv", index=False)
grade_counts.to_csv(OUT / "pooled_grade_counts.csv", index=False)
with open(OUT / "summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)


def save(fig, name):
    fig.savefig(OUT / name, dpi=150, bbox_inches="tight")
    plt.close(fig)


# 1. Распределение баллов
fig, ax = plt.subplots(figsize=(11, 6))
ax.bar(score_counts["score"], score_counts["count"],
       color="steelblue", edgecolor="black")
for thr, lab in [(24, "24 — граница 2/3"),
                 (32, "32 — граница 3/4"),
                 (44, "44 — граница 4/5")]:
    ax.axvline(thr, color="red", ls=":", alpha=0.7)
    ax.text(thr, score_counts["count"].max()*0.92, lab,
            rotation=90, color="red", fontsize=8, ha="right", va="top")
ax.set_xlabel("Баллы за семестр")
ax.set_ylabel("Кол-во студентов (по 10k прогонам)")
ax.set_title("Распределение итоговых баллов (0–50)")
ax.set_xticks(range(0, 51, 5))
ax.grid(axis="y", alpha=0.3)
save(fig, "01_hist_scores.png")

# 2. Распределение оценок
fig, ax = plt.subplots(figsize=(7, 5))
ax.bar(grade_counts["grade"], grade_counts["count"],
       color="coral", edgecolor="black")
for g, c in zip(grade_counts["grade"], grade_counts["count"]):
    pct = c / all_df.shape[0] * 100
    ax.text(g, c, f"{pct:.1f}%", ha="center", va="bottom", fontsize=10)
ax.set_xlabel("Оценка"); ax.set_ylabel("Кол-во студентов")
ax.set_title("Распределение оценок (2–5)")
ax.set_xticks([2, 3, 4, 5]); ax.grid(axis="y", alpha=0.3)
save(fig, "02_hist_grades.png")

# 3. Среднее по прогонам
fig, ax = plt.subplots(figsize=(9, 5))
ax.hist(per_run_df["mean"], bins=60, color="seagreen", edgecolor="black", alpha=0.8)
ax.axvline(per_run_df["mean"].mean(), color="red", ls="--",
           label=f"avg = {per_run_df['mean'].mean():.2f}")
ax.set_xlabel("Средний балл в прогоне"); ax.set_ylabel("Частота")
ax.set_title("Распределение среднего по 10 000 прогонам")
ax.legend(); ax.grid(alpha=0.3)
save(fig, "03_hist_per_run_mean.png")

# 4. Медиана по прогонам
fig, ax = plt.subplots(figsize=(9, 5))
ax.hist(per_run_df["median"], bins=30, color="mediumpurple", edgecolor="black", alpha=0.8)
ax.axvline(per_run_df["median"].mean(), color="red", ls="--",
           label=f"avg = {per_run_df['median'].mean():.2f}")
ax.set_xlabel("Медиана в прогоне"); ax.set_ylabel("Частота")
ax.set_title("Распределение медиан по 10 000 прогонам")
ax.legend(); ax.grid(alpha=0.3)
save(fig, "04_hist_per_run_median.png")

# 5. СКО по прогонам
fig, ax = plt.subplots(figsize=(9, 5))
ax.hist(per_run_df["std"], bins=60, color="darkorange", edgecolor="black", alpha=0.8)
ax.axvline(per_run_df["std"].mean(), color="red", ls="--",
           label=f"avg = {per_run_df['std'].mean():.2f}")
ax.set_xlabel("СКО в прогоне"); ax.set_ylabel("Частота")
ax.set_title("Распределение СКО по 10 000 прогонам")
ax.legend(); ax.grid(alpha=0.3)
save(fig, "05_hist_per_run_std.png")

# 6. Средние количества оценок в прогоне
fig, ax = plt.subplots(figsize=(8, 5))
means = [per_run_df[f"count_{g}"].mean() for g in (2, 3, 4, 5)]
stds  = [per_run_df[f"count_{g}"].std(ddof=0) for g in (2, 3, 4, 5)]
ax.bar([2, 3, 4, 5], means, yerr=stds, capsize=6,
       color=["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4"], edgecolor="black")
for g, m in zip([2, 3, 4, 5], means):
    ax.text(g, m, f"{m:.2f}", ha="center", va="bottom")
ax.set_xlabel("Оценка"); ax.set_ylabel("Среднее кол-во в прогоне")
ax.set_title("Сколько человек получают каждую оценку (mean ± std)")
ax.set_xticks([2, 3, 4, 5]); ax.grid(axis="y", alpha=0.3)
save(fig, "06_avg_grade_counts.png")

# 7. Сравнение двух способов расчёта
fig, ax = plt.subplots(figsize=(8, 5))
labels = ["Среднее", "Медиана", "СКО"]
per_run_vals = [
    summary["per_run_stats_averaged"]["mean"],
    summary["per_run_stats_averaged"]["median"],
    summary["per_run_stats_averaged"]["std"],
]
pooled_vals = [
    summary["pooled_stats"]["mean"],
    summary["pooled_stats"]["median"],
    summary["pooled_stats"]["std"],
]
x = np.arange(len(labels)); w = 0.35
ax.bar(x - w/2, per_run_vals, w, label="Среднее по прогонам", color="steelblue")
ax.bar(x + w/2, pooled_vals, w, label="По объединённым данным", color="coral")
for i, (a, b) in enumerate(zip(per_run_vals, pooled_vals)):
    ax.text(i - w/2, a, f"{a:.2f}", ha="center", va="bottom", fontsize=9)
    ax.text(i + w/2, b, f"{b:.2f}", ha="center", va="bottom", fontsize=9)
ax.set_xticks(x); ax.set_xticklabels(labels)
ax.set_ylabel("Значение")
ax.set_title("Сравнение двух способов расчёта статистик")
ax.legend(); ax.grid(axis="y", alpha=0.3)
save(fig, "07_compare_stats.png")

print(json.dumps(summary, ensure_ascii=False, indent=2))
print(f"\nВсё сохранено в {OUT.resolve()}")