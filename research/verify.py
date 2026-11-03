"""Independently reconstruct summaries from saved student-level CSV files."""
from collections import Counter
import csv
import gzip
import json
import math
from pathlib import Path
from statistics import mean, median, pstdev
import sys


def verify(folder):
    folder=Path(folder)
    summary=json.loads((folder/'summary.json').read_text())
    with (folder/'per_run.csv').open() as file:
        runs={(r['policy'],int(r['run'])):r for r in csv.DictReader(file)}
    assert len(runs)==len(summary['policies'])*summary['runs']
    for policy, expected in summary['policies'].items():
        hist=Counter();grades=Counter();stats=[];group=[];current=0;identities=set();p_digest=[]
        with gzip.open(folder/policy/'students.csv.gz','rt') as file:
            for row in csv.DictReader(file):
                run=int(row['run']);student=int(row['student']);score=int(row['score'])
                assert run==current and student not in identities
                assert int(row['seed'])==summary['seed']+run
                assert 0<=score<=50 and 0<=int(row['completed_labs'])<=10
                assert 0<=float(row['p'])<=1
                expected_grade=2 if score<=24 else 3 if score<=32 else 4 if score<=44 else 5
                assert int(row['grade'])==expected_grade
                hist[score]+=1;grades[expected_grade]+=1;group.append(score);identities.add(student)
                p_digest.append(row['p'])
                if len(group)==summary['config']['students']:
                    actual=(mean(group),median(group),pstdev(group));stats.append(actual)
                    report=runs[policy,run]
                    for key,value in zip(['mean','median','std'],actual):
                        assert math.isclose(float(report[key]),value,abs_tol=1e-10)
                    for grade in range(2,6):
                        assert sum((2 if s<=24 else 3 if s<=32 else 4 if s<=44 else 5)==grade for s in group)==int(report[f'grade_{grade}'])
                    assert int(report['four_five'])==sum(s>=33 for s in group)
                    assert int(report['failed_opportunities'])==int(report['failed_attempts'])+int(report['capacity_misses'])
                    assert int(report['attempts'])<=summary['config']['capacity']*summary['config']['weeks']
                    group=[];identities=set();current+=1
        assert not group and current==summary['runs']
        if policy==next(iter(summary['policies'])):
            reference_probabilities=p_digest
        else:
            assert p_digest==reference_probabilities
        with (folder/policy/'histogram.csv').open() as file:
            exported={int(r['score']):int(r['count']) for r in csv.DictReader(file)}
        assert list(exported)==list(range(51))
        assert all(exported[s]==hist[s] for s in range(51))
        for grade in range(2,6):assert grades[grade]==expected['totals'][f'grade_{grade}']
        n=sum(hist.values());avg=sum(s*c for s,c in hist.items())/n
        centers=[];cumulative=0
        for score in range(51):
            for pos in [(n-1)//2,n//2]:
                if cumulative<=pos<cumulative+hist[score]:centers.append(score)
            cumulative+=hist[score]
        pooled=[avg,mean(centers),(sum(c*(s-avg)**2 for s,c in hist.items())/n)**0.5]
        for i,key in enumerate(['mean','median','std']):
            assert math.isclose(expected['pooled'][key],pooled[i],abs_tol=1e-10)
            assert math.isclose(expected['mean_of_runs'][key],mean(row[i] for row in stats),abs_tol=1e-10)
        assert math.isclose(expected['four_five_per_group'],(grades[4]+grades[5])/summary['runs'])
        print(policy,'OK:',n,'student outcomes')
    print('Raw data, histograms, both statistical summaries and paired probabilities: OK')


if __name__=='__main__':
    verify(sys.argv[1])
