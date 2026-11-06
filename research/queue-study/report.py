"""Build figures and the Markdown article from saved data, without new simulations."""
import csv
import gzip
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from study import LABELS, POLICIES, ROOT, paired_interval, write_csv

OUT = ROOT / "figures"
DATA = ROOT / "results" / "finalists"
ORIGINAL = ROOT / "results" / "original"
COLORS = {"random": "#a1aebf", "clamp0": "#60a5fa", "clamp_minus1": "#2dd4bf"}
NAMES = {"random": "Случайная", "priority": "Без нижней границы", "priority_clamped": "Приоритет ≥ −1", "priority_clamped_zero": "Приоритет ≥ 0", "fifo": "Меньше сдано (исходный fifo)", "most_passed": "Больше сдано"}
SCENARIOS = {
    "baseline": "Базовый сценарий", "capacity_10": "Вместимость 10", "capacity_15": "Вместимость 15", "capacity_25": "Вместимость 25", "capacity_30": "Вместимость 30",
    "uniform": "p ~ Uniform(0, 1)", "beta": "p ~ Beta(5, 5)",
    "probability_0.3": "Средняя вероятность 0,3", "probability_0.7": "Средняя вероятность 0,7",
    "attendance_0.6": "Посещаемость 60%", "attendance_0.8": "Посещаемость 80%",
    "students_20": "20 студентов", "students_40": "40 студентов", "students_60": "60 студентов",
    "weeks_22": "22 недели", "weeks_40": "40 недель", "deadline_spacing_2": "Дедлайны через 2 недели", "deadline_spacing_4": "Дедлайны через 4 недели",
    "penalty_0": "Без штрафов", "penalty_2": "Штраф 2 балла за неделю",
    "lab_difficulty": "Разная сложность работ", "release_due_minus2": "Готовность за 2 недели до ДД",
    "cancel_week10": "Отмена приёма на 10-й неделе", "extra_capacity_week10": "Удвоение мест на 10-й неделе",
}


def read_csv(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", dpi=170, facecolor=fig.get_facecolor(), bbox_inches="tight")
    fig.savefig(OUT / f"{name}.svg", facecolor=fig.get_facecolor(), bbox_inches="tight")
    svg = OUT / f"{name}.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    plt.close(fig)


def main():
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({"figure.facecolor": "#101b2c", "axes.facecolor": "#101b2c", "axes.edgecolor": "#52647d", "text.color": "#edf3fa", "axes.labelcolor": "#d5dfed", "xtick.color": "#d5dfed", "ytick.color": "#d5dfed", "font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False, "grid.alpha": .15, "grid.color": "#9fb1c6", "legend.facecolor": "#18263b", "legend.edgecolor": "#52647d", "svg.hashsalt": "queue-study-v1"})
    original = read_csv(ORIGINAL / "comparison.csv")
    summary = read_csv(DATA / "summary.csv")
    comparisons = read_csv(DATA / "paired_comparisons.csv")
    protocol = json.loads((DATA / "protocol.json").read_text())
    seeds = protocol["baseline_seeds"]
    arrays = {p: np.concatenate([np.load(DATA / "baseline" / str(s) / f"{p}_scores.npz")["scores"] for s in seeds]) for p in POLICIES}
    per = {p: [row for seed in seeds for row in read_csv(DATA / "baseline" / str(seed) / f"{p}_runs.csv.gz")] for p in POLICIES}
    base = {p: dict(mean=float(arrays[p].mean()), median=float(np.median(arrays[p])), std=float(arrays[p].std()), share45=float((arrays[p] >= 33).mean()), share345=float((arrays[p] >= 25).mean()), zero=float((arrays[p] == 0).mean())) for p in POLICIES}

    ordered = sorted(original, key=lambda r: float(r["share45"]))
    fig, ax = plt.subplots(figsize=(11, 5.5))
    bars = ax.barh([NAMES[r["model"]] for r in ordered], [100 * float(r["share45"]) for r in ordered], color=["#2dd4bf" if r["model"] == "priority_clamped" else "#60a5fa" for r in ordered], height=.65)
    for bar, row in zip(bars, ordered):
        ax.text(bar.get_width() + .7, bar.get_y() + bar.get_height() / 2, f'{float(row["share45"]) * 100:.2f}%', va="center")
    ax.set(xlabel="Студенты с 4–5, %", title="Все исходные модели + вариант с нижней границей 0", xlim=(0, 85))
    ax.grid(axis="x")
    save(fig, "all-models")

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5), sharey=True)
    grade_colors = ["#f87171", "#fbbf24", "#60a5fa", "#2dd4bf"]
    for ax, policy in zip(axes, POLICIES):
        flat = arrays[policy].ravel()
        shares = [100 * ((flat >= lo) & (flat <= hi)).mean() for lo, hi in ((0, 24), (25, 32), (33, 44), (45, 50))]
        ax.bar(["2", "3", "4", "5"], shares, color=grade_colors)
        for i, value in enumerate(shares):
            ax.text(i, value + .6, f"{value:.2f}%", ha="center", fontsize=10)
        ax.set(title=LABELS[policy], xlabel="Оценка", ylim=(0, 55))
        ax.grid(axis="y")
    axes[0].set_ylabel("Доля студентов, %")
    fig.suptitle("Финалисты · 30 000 семестров на вариант · общий случайный фон", y=1.04)
    save(fig, "finalists-grades")

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True, sharey=True)
    for ax, policy in zip(axes, POLICIES):
        hist = np.bincount(arrays[policy].ravel(), minlength=51)
        ax.bar(np.arange(51), hist / hist.sum() * 100, color=COLORS[policy], width=.85)
        for left, right, color in ((-.5, 24.5, "#f87171"), (24.5, 32.5, "#fbbf24"), (32.5, 44.5, "#60a5fa"), (44.5, 50.5, "#2dd4bf")):
            ax.axvspan(left, right, color=color, alpha=.055)
        ax.set(title=LABELS[policy], ylabel="Студенты, %")
        ax.grid(axis="y")
    axes[-1].set(xlabel="Баллы за семестр", xlim=(-1, 51))
    fig.tight_layout()
    save(fig, "finalists-scores")

    sensitivity = [r for r in comparisons if r["comparator"] == "clamp0" and r["metric"] == "share45" and int(r["seed"]) == seeds[0]]
    sensitivity.reverse()
    fig, ax = plt.subplots(figsize=(12, 11))
    for i, row in enumerate(sensitivity):
        mean, lo, hi = [100 * float(row[key]) for key in ("delta", "ci95_low", "ci95_high")]
        ax.errorbar(mean, i, xerr=[[max(0, mean - lo)], [max(0, hi - mean)]], fmt="o", color="#2dd4bf" if mean >= 0 else "#fbbf24", capsize=3)
    ax.set_yticks(range(len(sensitivity)), [SCENARIOS[r["scenario"]] for r in sensitivity])
    ax.axvline(0, color="#d5dfed", alpha=.6)
    ax.set(xlabel="Разность доли 4–5: (−1) − (0), процентные пункты; 95% ДИ", title="Где выбор нижней границы меняет результат")
    ax.grid(axis="x")
    save(fig, "sensitivity")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    caps = [10, 15, 20, 25, 30]
    for policy in POLICIES:
        rows = [next(r for r in summary if r["policy"] == policy and int(r["seed"]) == seeds[0] and r["scenario"] == ("baseline" if cap == 20 else f"capacity_{cap}")) for cap in caps]
        for ax, metric in zip(axes, ("share45", "zero_share")):
            ax.plot(caps, [float(r[metric]) * 100 for r in rows], marker="o", label=LABELS[policy], color=COLORS[policy], linewidth=2)
            ax.grid()
            ax.set_xticks(caps)
            ax.set_xlabel("Мест приёма за неделю")
    axes[0].set(title="Основной критерий", ylabel="Студенты с 4–5, %")
    axes[1].set(title="Побочный риск", ylabel="Студенты с нулём баллов, %")
    axes[1].legend()
    save(fig, "capacity")

    fig, ax = plt.subplots(figsize=(9, 5))
    for policy in POLICIES:
        ax.scatter(base[policy]["zero"] * 100, base[policy]["share45"] * 100, s=180, color=COLORS[policy])
        ax.annotate(LABELS[policy], (base[policy]["zero"] * 100, base[policy]["share45"] * 100), xytext=(8, 9 if policy != "clamp_minus1" else -20), textcoords="offset points")
    ax.set(xlabel="Студенты с нулём баллов, % (меньше лучше)", ylabel="Студенты с 4–5, % (больше лучше)", title="Компромисс в базовом сценарии", xlim=(1.5, 8), ylim=(56, 77))
    ax.grid()
    save(fig, "tradeoff")

    original_rows = "\n".join(f'| {NAMES[r["model"]]} | {100 * float(r["share45"]):.2f}% | {100 * float(r["share345"]):.2f}% | {100 * float(r["zero_share"]):.2f}% | {float(r["mean"]):.2f} |' for r in sorted(original, key=lambda r: -float(r["share45"])))
    base_rows = "\n".join(f'| {LABELS[p]} | {100 * base[p]["share45"]:.2f}% | {100 * base[p]["share345"]:.2f}% | {100 * base[p]["zero"]:.2f}% | {base[p]["mean"]:.3f} | {base[p]["median"]:.1f} | {base[p]["std"]:.3f} |' for p in POLICIES)
    delta_rows = []
    for comparator in ("random", "clamp0"):
        for metric, name in (("share45", "Доля 4–5, п. п."), ("zero_share", "Нули, п. п."), ("mean", "Средние баллы")):
            a = np.array([float(r[metric]) for r in per["clamp_minus1"]])
            b = np.array([float(r[metric]) for r in per[comparator]])
            mult = 1 if metric == "mean" else 100
            mean, lo, hi = [x * mult for x in paired_interval(a, b)]
            delta_rows.append(f"| −1 против {LABELS[comparator]} | {name} | {mean:+.3f} | [{lo:+.3f}; {hi:+.3f}] |")
    sensitivity_rows = []
    for scenario in protocol["scenarios"]:
        name = scenario["name"]
        rows = {p: next(r for r in summary if r["policy"] == p and r["scenario"] == name and int(r["seed"]) == seeds[0]) for p in POLICIES}
        delta = (float(rows["clamp_minus1"]["share45"]) - float(rows["clamp0"]["share45"])) * 100
        sensitivity_rows.append(f'| {SCENARIOS[name]} | {float(rows["random"]["share45"]) * 100:.2f}% | {float(rows["clamp0"]["share45"]) * 100:.2f}% | {float(rows["clamp_minus1"]["share45"]) * 100:.2f}% | {delta:+.3f} |')
    detailed = []
    for policy in POLICIES:
        avg = {key: np.mean([float(r[key]) for r in per[policy]]) for key in ("mean", "median", "std", "completed_labs", "max_consecutive_skips")}
        rejected = sum(float(r["queue_rejects"]) for r in per[policy])
        wanted = sum(float(r["wanted"]) for r in per[policy])
        detailed.append(f'| {LABELS[policy]} | {avg["mean"]:.3f} | {avg["median"]:.3f} | {avg["std"]:.3f} | {avg["completed_labs"]:.3f} | {avg["max_consecutive_skips"]:.3f} | {100 * rejected / wanted:.2f}% |')
    gallery = "\n".join(f'| {NAMES[r["model"]]} | [Баллы](results/original/{r["model"]}/histogram.png) · [Оценки](results/original/{r["model"]}/automat_bars.png) · [Нули отдельно](results/original/{r["model"]}/automat_bars_with_zero.png) | [Данные](results/original/{r["model"]}) |' for r in original)
    (ROOT / "README.md").write_text(f'''<div align="center">

# Очередь, дедлайны и цена приоритета

**Исследование алгоритмов записи на защиту лабораторных**

`30 студентов` · `10 работ` · `30 недель` · `20 мест` · `seed 42`

[Результаты](#три-финалиста) · [Чувствительность](#когда-меняются-условия) · [Запуск](#воспроизведение) · [ADR](../../docs/adr/README.md)

</div>

> **Решение команды:** нижняя граница приоритета −1. **Результат эксперимента:** по доле оценок 4–5 в базовых условиях лучше граница 0. Выбор −1 сохраняет преимущество просроченных работ, но не является максимумом выбранного KPI. Разницу ниже показываем численно.

## Задача и критерий

На занятии преподаватель успевает принять ограниченное число защит. Порядок влияет на то, кто попадёт на приём до дедлайна и сколько баллов потеряет при задержке. Сравниваем правила распределения одинакового ресурса; пропуск из-за очереди не считается успешной защитой и не открывает следующую работу.

Основной показатель: **доля студентов с итоговыми оценками 4 или 5**, то есть с 33–50 баллами. Отдельно считаем долю 3–5, нули, средние баллы, завершённые работы и пропуски из-за очереди. Переключать главный показатель после получения результата нельзя: победа по 3–5 не доказывает победу по 4–5.

Это вычислительный эксперимент на синтетических студентах. Наблюдений реальных защит и причинной проверки на учебных группах нет. Баллы здесь принадлежат модели; функция очереди в приложении не выставляет оценки и не меняет ячейки Google Sheets.

## Что получили от команды

В [source/](source/) сохранены байтовые копии Python-файлов AllModels. Входные данные, переписка, реальные студенты и секреты в исследование не включены. [Контрольные суммы](original_source_hashes.json) позволяют проверить происхождение кода. Исходники написаны командой; расчётный стенд, проверка и оформление исследования добавлены отдельно.

| Исходная модель | Реальное правило |
|---|---|
| `random` | Новый случайный порядок активных студентов каждую неделю |
| `priority` | Меньше `deadline − week` → раньше |
| `priority_clamped` | `max(−1, deadline − week)`; равные приоритеты случайны |
| `most_passed` | Больше завершённых работ → раньше |
| `fifo` | Меньше завершённых работ → раньше; это **не FIFO по времени записи** |
| Дополнительный вариант `priority_clamped_zero` | Тот же исходный класс с нижней границей 0 |

При общих возрастающих дедлайнах `priority` и исходный `fifo` задают одинаковый порядок: обе сортируют по номеру текущей работы. Их результаты совпали побитно на всех 10 000 прогонах. Это две реализации одного правила в данных условиях, а не два независимых подтверждения.

В комментариях AllModels есть устаревшие формулировки: распределение названо Uniform, хотя код использует Normal; описание границы −1 говорит о трёх неделях; −10 ошибочно названо эквивалентом отсутствия границы. В течение 30 недель возможна просрочка первой работы на 28 недель. Копии не исправлялись: расчёты опираются на исполняемый код, а расхождения перечислены здесь.

## Условия базового семестра

| Параметр | Значение |
|---|---|
| Размер группы / число работ | 30 / 10 |
| Период | 30 недель, один приём в неделю |
| Вместимость | **20** студентов за приём; 15 проверяем отдельно как жёсткий сценарий |
| Вероятность успешной защиты | Для каждого студента один раз: `clip(Normal(0.5, 0.15), 0.05, 0.95)` |
| Дедлайн работы k | `3k − 1`: недели 2, 5, 8, …, 29 |
| Баллы за защищённую работу | `max(0, 5 − max(0, неделя_защиты − дедлайн))` |
| Последовательность | Сначала ЛР1; следующая доступна после защиты предыдущей |
| Попытки | Не больше одной за неделю, включая неудачную; выбывшие из-за вместимости ждут следующую неделю |
| Готовность | В базовом сценарии текущая работа доступна с первой недели; тестирование и подготовка отдельно не моделируются |
| Оценки | 2: 0–24; 3: 25–32; 4: 33–44; 5: 45–50 |

Все 10 работ дают максимум 50 баллов. В день дедлайна штрафа нет. Нулевая стоимость старой работы не отменяет необходимость её защитить, чтобы перейти дальше. Бонус `EXAM_BONUS=5` из AllModels сохранён лишь как дополнительная гипотетическая колонка в исходной сводке; он не участвует в основных оценках, графиках и выборе алгоритма.

## Как устроен эксперимент

**Этап A: воспроизведение AllModels.** Шесть вариантов × 10 000 семестров = 60 000 семестров. Исходная последовательность seed: 42…10041. Сохранены исходные графики, баллы, статистика каждого семестра и сводка. Класс с границей 0 запускается отдельной обёрткой без правки AllModels. Одинаковые seed в исходном коде не обеспечивают одинаковые случайные события для одного студента после расхождения очередей: меняется число и порядок обращений к генератору.

**Этап B: парное сравнение финалистов.** 24 сценария по 10 000 семестров на вариант. Базовый сценарий дополнительно повторён с seed 1042 и 2042: всего 780 000 семестров для трёх финалистов. Начальные вероятности, посещаемость, случайные ключи равных приоритетов и исходы возможных попыток фиксированы для каждого студента и недели и совпадают между тремя вариантами. Алгоритм меняет только допуск к попытке. Векторизация проверена независимой реализацией с обычными циклами.

Сравниваем разность показателей **внутри одного семестра**, затем усредняем. 95% доверительный интервал: `mean(delta) ± 1.96 × std(delta, ddof=1) / sqrt(n_runs)`. Единица независимого наблюдения здесь семестр, поскольку студенты одной группы конкурируют друг с другом. Это интервал ошибки Монте-Карло в заданной модели; он не учитывает ошибку её описания реальности. Для серии сценариев интервалы описательные, без поправки на множественные сравнения. Основное сравнение заранее задано задачей: −1 против 0 и случайной очереди по доле 4–5.

Протокол с точными параметрами и версиями среды: [protocol.json](results/finalists/protocol.json). Никакие сценарии из итоговой таблицы не исключены по результату.

## Все модели: исходное исполнение

![Все модели](figures/all-models.png)

| Правило | 4–5 | 3–5 | Ноль баллов | Средний балл |
|---|---:|---:|---:|---:|
{original_rows}

Большое число пятёрок само по себе может скрывать потери остальных студентов: `most_passed` оставляет большой хвост нулевых результатов. У неограниченного приоритета противоположный риск: очень старые работы продолжают выигрывать у более близких к достижению высокой оценки. Нижняя граница объединяет сильно просроченные работы в один класс и ограничивает этот эффект. Это объяснение механизма; для конкретных процентов основанием служат сохранённые результаты.

## Три финалиста

Для этой таблицы объединены **три seed × 10 000 семестров**, по 900 000 синтетических студентов на алгоритм. Их результаты не смешиваются с этапом A.

![Оценки финалистов](figures/finalists-grades.png)

| Алгоритм | 4–5 | 3–5 | Ноль баллов | Среднее | Медиана всех баллов | СКО всех баллов |
|---|---:|---:|---:|---:|---:|---:|
{base_rows}

**Граница 0 выигрывает по основному критерию.** У −1 меньше нулей, но большее число студентов с 4–5 это не обеспечивает. Предпочтение просроченным работам и максимизация высоких оценок не тождественны.

![Распределение баллов](figures/finalists-scores.png)

### Насколько велика разница

Знак «+» означает, что у −1 показатель выше. Для нулей отрицательная разность желательна; для 4–5 и баллов положительная.

| Сравнение | Показатель | Разность | 95% ДИ |
|---|---|---:|---:|
{chr(10).join(delta_rows)}

Разница между долей 4–5 у 0 и −1 сохраняется на всех трёх базовых seed. Это не единичное удачное перемешивание. Полные парные результаты каждого сценария лежат в [paired_comparisons.csv](results/finalists/paired_comparisons.csv).

![Компромисс](figures/tradeoff.png)

### Два способа считать статистику

В предыдущей таблице медиана и СКО рассчитаны по объединённым баллам. Ниже сначала считаем показатель внутри каждой группы, затем усредняем между семестрами. СКО в обоих случаях популяционное (`ddof=0`). Средние баллы совпадают при одинаковом размере групп; средние медиан и СКО совпадать не обязаны.

| Алгоритм | Среднее средних | Среднее медиан | Среднее СКО | Завершено работ на студента | Макс. подряд пропусков в группе, среднее | Отказы / все желаемые попытки |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(detailed)}

Пропуск здесь означает, что студент пришёл и имел доступную работу, но не получил место. Счётчик подряд обнуляется при обслуживании, отсутствии или недоступности работы; это не календарное время ожидания. Долю отказов нельзя читать как самостоятельную оценку справедливости: алгоритмы меняют число активных студентов и тем самым знаменатель. По одной этой метрике лучшего алгоритма не выбираем.

## Когда меняются условия

Все строки ниже используют seed 42 и 10 000 семестров на вариант. Меняется один фактор относительно базы. В модели сложности коэффициент успешности растёт от 0,8 для первой работы до 1,2 для десятой с ограничением итоговой вероятности диапазоном [0, 1]. В сценарии готовности ЛР k доступна не раньше `max(1, deadline[k] − 2)`. Вместимость 40 на дополнительном приёме всё ещё даёт каждому студенту максимум одну попытку за неделю.

| Условие | Случайная: 4–5 | Граница 0: 4–5 | Граница −1: 4–5 | Разность −1 и 0, п. п. |
|---|---:|---:|---:|---:|
{chr(10).join(sensitivity_rows)}

![Вместимость](figures/capacity.png)

**При 15 местах случайная очередь лучше обеих приоритетных по доле 4–5, а проигрыш −1 варианту 0 существенно больше, чем в мягкой базе.** При дефиците приёма поддержка старых работ расходует попытки, которые могли бы дать высокие результаты другим студентам. Это объяснение направления эффекта, а не измерение индивидуальных причин. Цену решения нельзя скрывать усреднением с более благоприятными условиями. При вместимости на всю группу все три правила дают побитно одинаковые результаты: порядок перестаёт ограничивать доступ. Это также проверка корректности стенда.

![Чувствительность](figures/sensitivity.png)

Параметры успеваемости, доступности работ и штрафов меняют относительную пользу политики. Сценарий без штрафов полезен для проверки чувствительности, но не соответствует принятому правилу снятия баллов и не служит основанием объявить −1 победителем в базовой задаче. Полного перебора сочетаний факторов нет; взаимодействия посещаемости, размера группы и сложности требуют отдельного эксперимента.

## Почему команда всё же выбрала −1

Выбранное правило: **`priority = max(−1, deadline_week − current_week)`**, меньший ключ обслуживается раньше. Все просроченные работы равны между собой; текущий дедлайн имеет приоритет 0; будущие дедлайны дают 1, 2, … без верхней границы. Человек с просрочкой 10 недель не обходит человека с просрочкой одной недели только за счёт возраста долга.

Аргумент в пользу −1: просроченная работа получает отдельный класс перед работой с текущим дедлайном, но рост просрочки не даёт бесконечно возрастающего преимущества. Это понятная студенту политика помощи с задолженностью. По сравнению со случайным порядком базовые результаты значительно лучше, а нулевых результатов меньше. Отличие от границы 0 сводится к одному явному правилу: у 0 текущие и просроченные работы равны; у −1 просроченные идут раньше.

**Цена решения:** по заявленной цели максимизации доли 4–5 при базовых 20 местах данные поддерживают границу 0. При 15 местах лучше случайная очередь. Выбор −1 является ранее заданной командой политикой; исследование обнаружило её потерю по KPI, а согласие команды именно с этой уступкой ещё не подтверждено. Если доля 4–5 остаётся единственным основанием выбора в базовом сценарии, рекомендация исследования: **взять 0**. Объявить −1 лучшим по этому критерию на этих результатах нельзя. [ADR-0001](../../docs/adr/0001-priority-policy.md) фиксирует выбор −1 и это ограничение; согласование отличающегося от FIFO порядка с заказчиком остаётся частью приёмки.

## Где заканчивается модель

В реальном сервисе допуск из таблицы и подтверждённая запись студента являются разными действиями. Модель предполагает, что все доступные студенты хотят сдавать; в чувствительности меняется лишь вероятность присутствия. Она не доказывает удобство автоматической записи и не отменяет окно записи по расписанию.

Вычислительный стенд не моделирует длительность защиты, опоздания внутри пары, стратегический выбор момента записи, общение с преподавателем, недельное изменение подготовки, корреляции между студентами, несколько преподавателей, реальный парсер расписания и перенос записей внутри дня. Готовность, посещаемость, сложность и отмена одной недели проверены только как отдельные приближения.

В модели штраф зависит от недели защиты. В существующем сервисе штраф за проверку фиксируется при прохождении тестов и может затем отличаться от вычисленной моделью «просрочки». Нельзя переносить формулу штрафов в боевую очередь или вычислять её приоритет из `v-3` без отдельного решения. Приоритет в проектируемой очереди вычисляется по сроку работы и дате занятия; оценки из таблицы только читаются.

Равные приоритеты в AllModels и эксперименте разыгрываются случайно. Для интерфейса в ADR предлагается стабильный порядок по времени записи. Повторная защита в приложении должна уходить в общий конец этого занятия, тогда как недельный стенд допускает только одну попытку в неделю. Поэтому численные преимущества нельзя обещать для готового продукта без отдельной проверки его полного алгоритма. Дедлайны курса и срок хакатона также относятся к разным задачам.

## Данные и графики для каждого варианта

| Модель | Исходные графики AllModels | Результаты |
|---|---|---|
{gallery}

| Файл | Содержимое |
|---|---|
| `results/original/<model>/all_scores.npy` | 300 000 баллов; порядок: прогон, затем студент |
| `results/original/<model>/score_distribution.csv` | Все значения 0…50, количества и доли |
| `results/original/<model>/per_run_stats.csv` | Среднее, медиана, СКО каждой группы |
| `results/original/comparison.csv` | Сопоставление всех исходных правил |
| `results/finalists/summary.csv` | Все сценарии, seed и показатели финалистов |
| `results/finalists/<scenario>/<seed>/*_scores.npz` | Сырые баллы, двумерный массив `[прогон, студент]`, ключ `scores` |
| `results/finalists/<scenario>/<seed>/*_runs.csv.gz` | Статистика каждого семестра, включая вторичные показатели |
| `results/finalists/<scenario>/<seed>/*_histogram.csv` | 51 строка распределения, включая нулевые частоты |
| `results/finalists/<scenario>/<seed>/summary.json` | Параметры, объединённая и усреднённая статистика, оценки |
| `figures/*.png`, `figures/*.svg` | Графики для GitHub и масштабируемые версии для презентации |

<details>
<summary>Прочитать сырые баллы и статистику без запуска симуляции</summary>

```python
import numpy as np
import csv, gzip

scores = np.load("research/queue-study/results/finalists/baseline/42/clamp_minus1_scores.npz")["scores"]
print(scores.shape, scores.mean(), (scores >= 33).mean())
with gzip.open("research/queue-study/results/finalists/baseline/42/clamp_minus1_runs.csv.gz", "rt") as f:
    first_run = next(csv.DictReader(f))
print(first_run)
```

</details>

## Воспроизведение

Из корня репозитория, Python 3.12. Исследовательские зависимости устанавливаются отдельно от приложения.

```bash
python3.12 -m venv .venv-research
source .venv-research/bin/activate
pip install -r research/queue-study/requirements.txt
python research/queue-study/test_study.py
python docs/queue/test_schema.py
python research/queue-study/reproduce.py --runs 10000 --seed 42
python research/queue-study/study.py --runs 10000 --seeds 42 1042 2042
python research/queue-study/report.py
python research/queue-study/validate_results.py
```

Для перестроения статьи и изображений по сохранённым данным достаточно `report.py`; расчёты не запускаются. Параметры полного опыта находятся в `Scenario` и `scenarios()` внутри [study.py](study.py). AllModels регулируется своим [common.py](source/common.py); это два разных этапа, изменение одного файла не меняет другой.

Проверки целостности, окружение и контрольные суммы собраны в [validation.json](validation.json) и [artifact_hashes.json](artifact_hashes.json). Это воспроизводимость вычислений, а не доказательство реалистичности распределений.

## Следующий проверяемый шаг

Реализовать выбранное правило как настраиваемую политику внутри окна записи, сохранить историю в SQLite, прогнать сценарии занятия из ADR и проверить порядок на обезличенных или искусственных данных. После наблюдения реальных длительностей и посещаемости можно откалибровать симулятор и повторить сравнение. Изменение нижней границы приоритета не должно требовать изменения схемы БД.
''', encoding="utf-8")
    (ROOT / "environment.json").write_text(json.dumps({"matplotlib": matplotlib.__version__, "numpy": np.__version__}, indent=2) + "\n")
    print("Generated article and six figures (PNG + SVG)")


if __name__ == "__main__":
    main()
