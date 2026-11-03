"""
Симуляция сдачи лабораторных со случайной очередью.

Запуск:  python simulation.py
Результаты сохраняются в папку results/ (без графиков - только данные).
"""
import json
import csv
import os
import numpy as np

# ------------------------- ПАРАМЕТРЫ -------------------------
SEED = 42
N_RUNS = 10_000
N_STUDENTS = 30
N_LABS = 10
MAX_PER_LAB = 5
N_DAYS = 30            # 1 день приема в неделю, 30 недель
CAPACITY = 20          # сколько человек могут принять за один день
DEADLINES = [3 * k - 1 for k in range(1, N_LABS + 1)]  # 2, 5, 8, ..., 29
MAX_SCORE = N_LABS * MAX_PER_LAB  # 50
OUT_DIR = "results"


def grade(score: int) -> int:
    if score <= 24:
        return 2
    if score <= 32:
        return 3
    if score <= 44:
        return 4
    return 5


def lab_score(lab_idx: int, week: int) -> int:
    """Баллы за лабу lab_idx (0-based), сданную на неделе week (1-based)."""
    late_weeks = max(0, week - DEADLINES[lab_idx])
    return max(0, MAX_PER_LAB - late_weeks)


def simulate_run(rng: np.random.Generator):
    """Один прогон = один семестр. Возвращает (баллы студентов, доля отказов из-за очереди)."""
    p = rng.uniform(0.0, 1.0, N_STUDENTS)          # шанс сдачи у каждого студента
    current_lab = np.zeros(N_STUDENTS, dtype=int)  # какую лабу сейчас сдает студент
    scores = np.zeros(N_STUDENTS, dtype=int)
    queue_rejects = 0
    attempts_wanted = 0

    for week in range(1, N_DAYS + 1):
        # хотят сдавать все, у кого остались несданные лабы
        wanting = np.flatnonzero(current_lab < N_LABS)
        if wanting.size == 0:
            break
        attempts_wanted += wanting.size

        # случайный порядок очереди, принимают первых CAPACITY
        order = rng.permutation(wanting)
        accepted = order[:CAPACITY]
        queue_rejects += max(0, wanting.size - CAPACITY)

        # попытка сдачи у принятых
        success = rng.random(accepted.size) < p[accepted]
        for s in accepted[success]:
            lab = current_lab[s]
            scores[s] += lab_score(lab, week)
            current_lab[s] += 1

    return scores, queue_rejects, attempts_wanted


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = np.random.default_rng(SEED)

    all_scores = np.zeros((N_RUNS, N_STUDENTS), dtype=int)
    run_mean = np.zeros(N_RUNS)
    run_median = np.zeros(N_RUNS)
    run_std = np.zeros(N_RUNS)
    rejects_total = 0
    wanted_total = 0

    for r in range(N_RUNS):
        sc, rej, wanted = simulate_run(rng)
        all_scores[r] = sc
        run_mean[r] = sc.mean()
        run_median[r] = np.median(sc)
        run_std[r] = sc.std(ddof=0)
        rejects_total += rej
        wanted_total += wanted

    flat = all_scores.ravel()

    # 1. Распределение баллов (0..50)
    hist = np.bincount(flat, minlength=MAX_SCORE + 1)

    # Распределение оценок (автоматы)
    grades = np.array([grade(s) for s in range(MAX_SCORE + 1)])
    grade_counts = {g: int(hist[grades == g].sum()) for g in (2, 3, 4, 5)}

    # 2. Статистика: два варианта
    stats = {
        "params": {
            "seed": SEED, "n_runs": N_RUNS, "n_students": N_STUDENTS,
            "n_labs": N_LABS, "n_days": N_DAYS, "capacity": CAPACITY,
            "deadlines": DEADLINES, "std_ddof": 0,
        },
        "averaged_over_runs": {   # считали по каждому прогону, потом усреднили
            "mean": float(run_mean.mean()),
            "median": float(run_median.mean()),
            "std": float(run_std.mean()),
        },
        "pooled_all_runs": {      # все 300 000 студентов как одна выборка
            "mean": float(flat.mean()),
            "median": float(np.median(flat)),
            "std": float(flat.std(ddof=0)),
        },
        "grades_count": grade_counts,
        "grades_share": {g: c / flat.size for g, c in grade_counts.items()},
        "queue": {
            "share_of_attempts_lost_to_queue": rejects_total / wanted_total,
        },
    }

    # ------------------------- СОХРАНЕНИЕ -------------------------
    with open(f"{OUT_DIR}/score_distribution.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["score", "count", "share"])
        for s in range(MAX_SCORE + 1):
            w.writerow([s, int(hist[s]), hist[s] / flat.size])

    with open(f"{OUT_DIR}/per_run_stats.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run", "mean", "median", "std"])
        for r in range(N_RUNS):
            w.writerow([r, run_mean[r], run_median[r], run_std[r]])

    with open(f"{OUT_DIR}/summary_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # сырые баллы всех студентов во всех прогонах (для любых будущих графиков)
    np.save(f"{OUT_DIR}/all_scores.npy", all_scores)

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
