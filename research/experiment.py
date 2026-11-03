"""Paired semester experiments. Standard library only; never contacts external services."""
import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import random
from statistics import mean, median, pstdev, stdev

POLICIES = ('deadline', 'chance_5', 'score', 'random', 'fifo', 'chance_4')


@dataclass(frozen=True)
class Config:
    students: int = 30
    labs: int = 10
    weeks: int = 30
    capacity: int = 20
    points: int = 5

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in asdict(self).values()):
            raise ValueError('Параметры должны быть положительными целыми числами')


def grade(score):
    return 2 if score < 25 else 3 if score < 33 else 4 if score < 45 else 5


def statistics(scores):
    return dict(mean=mean(scores), median=median(scores), std=pstdev(scores))


def scenario(config, seed):
    rng = random.Random(seed)
    p = [rng.random() for _ in range(config.students)]
    order = list(range(config.students))
    rng.shuffle(order)
    rolls = [[rng.random() for _ in p] for _ in range(config.weeks)]
    tie_rng = random.Random(f'ties:{seed}')
    ties = [[tie_rng.random() for _ in p] for _ in range(config.weeks)]
    return p, order, rolls, ties


def select(policy, active, scores, completed, week, sequence, ties, config):
    if policy not in POLICIES:
        raise ValueError('Неизвестная стратегия')
    def key(s):
        reach = scores[s] + config.points * (config.labs - completed[s])
        if policy == 'deadline':
            return ((completed[s] + 1) * 3 - 1 - week, ties[s])
        if policy == 'chance_5':
            return (0 if reach >= 45 else 1, -scores[s], ties[s])
        if policy == 'chance_4':
            target = scores[s] < 33 <= reach
            return (0 if target else 1 if scores[s] >= 33 else 2, -scores[s], ties[s])
        if policy == 'score':
            return (-scores[s], ties[s])
        if policy == 'fifo':
            return (sequence[s],)
        return (ties[s],)
    return sorted(active, key=key)[:config.capacity]


def simulate(config, data, policy):
    p, order, rolls, ties = data
    scores, completed = [0] * config.students, [0] * config.students
    sequence = {s: rank for rank, s in enumerate(order)}
    serial = config.students
    attempts = failures = misses = 0
    for w in range(config.weeks):
        active = [s for s in range(config.students) if completed[s] < config.labs]
        chosen = select(policy, active, scores, completed, w + 1, sequence, ties[w], config)
        misses += len(active) - len(chosen)
        for s in chosen:
            attempts += 1
            if rolls[w][s] < p[s]:
                deadline = (completed[s] + 1) * 3 - 1
                scores[s] += max(0, config.points - max(0, w + 1 - deadline))
                completed[s] += 1
            else:
                failures += 1
            sequence[s] = serial
            serial += 1
    return scores, completed, dict(attempts=attempts, failed_attempts=failures,
                                  capacity_misses=misses, failed_opportunities=failures + misses)


def pooled(hist):
    n = sum(hist.values())
    avg = sum(x * count for x, count in hist.items()) / n
    centers, seen = [], 0
    for x, count in sorted(hist.items()):
        centers.extend(x for index in [(n - 1) // 2, n // 2] if seen <= index < seen + count)
        seen += count
    return dict(mean=avg, median=sum(centers) / 2,
                std=(sum(count * (x - avg)**2 for x, count in hist.items()) / n)**0.5)


def run(config, runs, seed, output):
    if type(runs) is not int or runs < 1:
        raise ValueError('Число прогонов должно быть положительным целым')
    if config.labs != 10 or config.points != 5:
        raise ValueError('Пороги оценок определены для 10 работ по 5 баллов')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    hist = {p: Counter() for p in POLICIES}
    stats = {p: Counter() for p in POLICIES}
    totals = {p: Counter() for p in POLICIES}
    paired = {p: [] for p in POLICIES if p != 'fifo'}
    handles, writers = {}, {}
    try:
        for policy in POLICIES:
            folder = output / policy
            folder.mkdir()
            raw = gzip.GzipFile(filename=str(folder/'students.csv.gz'), mode='wb', mtime=0)
            handle = io.TextIOWrapper(raw, encoding='utf-8', newline='')
            handles[policy] = handle
            writers[policy] = csv.writer(handle)
            writers[policy].writerow(['run','seed','student','p','score','grade','completed_labs'])
        with (output/'per_run.csv').open('w', newline='', encoding='utf-8') as file:
            fields = ['run','seed','policy','mean','median','std','grade_2','grade_3','grade_4','grade_5',
                      'four_five','attempts','failed_attempts','capacity_misses','failed_opportunities']
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for index in range(runs):
                current_seed = seed + index
                data = scenario(config, current_seed)
                objective = {}
                for policy in POLICIES:
                    scores, completed, counters = simulate(config, data, policy)
                    summary = statistics(scores)
                    counts = Counter(grade(s) for s in scores)
                    objective[policy] = counts[4] + counts[5]
                    hist[policy].update(scores)
                    stats[policy].update(summary)
                    totals[policy].update({**counters, **{f'grade_{g}': counts[g] for g in range(2,6)}})
                    writer.writerow(dict(run=index, seed=current_seed, policy=policy, **summary,
                        **{f'grade_{g}':counts[g] for g in range(2,6)}, four_five=objective[policy], **counters))
                    for student, score in enumerate(scores):
                        writers[policy].writerow([index,current_seed,student,data[0][student],
                                                 score,grade(score),completed[student]])
                for policy in paired:
                    paired[policy].append(objective[policy] - objective['fifo'])
                if (index + 1) % 1000 == 0:
                    print(f'{index + 1}/{runs}', flush=True)
    finally:
        for handle in handles.values():
            handle.close()
    for policy in POLICIES:
        with (output/policy/'histogram.csv').open('w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['score','count'])
            writer.writerows((s,hist[policy][s]) for s in range(51))
    differences = {}
    for policy, values in paired.items():
        avg = mean(values)
        error = 1.96 * stdev(values) / runs**0.5 if runs > 1 else None
        differences[policy] = dict(mean_difference=avg,
            mc_95_interval=[avg-error,avg+error] if error is not None else None)
    summary = dict(config=asdict(config), runs=runs, seed=seed, python=platform.python_version(),
        std_convention='population (ddof=0)',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        paired_difference_vs_fifo=differences, policies={})
    for policy in POLICIES:
        good = totals[policy]['grade_4'] + totals[policy]['grade_5']
        summary['policies'][policy] = dict(
            pooled=pooled(hist[policy]), mean_of_runs={k:v/runs for k,v in stats[policy].items()},
            totals=dict(totals[policy]), four_five_per_group=good/runs,
            four_five_percent=100*good/(runs*config.students))
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=10000)
    parser.add_argument('--seed', type=int, default=20261103)
    parser.add_argument('--capacity', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(Config(capacity=args.capacity), args.runs, args.seed, args.output)
    for policy, value in result['policies'].items():
        print(policy, value['four_five_per_group'])
