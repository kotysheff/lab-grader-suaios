"""Validate original authors' outputs without modifying their source code."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent


def audit():
    sources=json.loads((ROOT/'originals/SHA256.json').read_text())
    for name,digest in sources.items():
        assert hashlib.sha256((ROOT/'originals'/name).read_bytes()).hexdigest()==digest
    report={}
    for author,folder,array_file,hist_file,per_file,ddof in [
        ('А. М. Кутыев','original-kutyev/sim_results','all_points_raw.npy','score_distribution.csv','per_run_stats.csv',1),
        ('Е. И. Волжанин','original-volzhanin/results','all_scores.npy','score_distribution.csv','per_run_stats.csv',0),
        ('Н. А. Щепоткин','original-shchepotkin/simulation_results',None,'pooled_score_counts.csv','per_run_stats.csv',0),
    ]:
        path=ROOT/'results'/folder
        if array_file:
            scores=np.load(path/array_file,allow_pickle=False)
        else:
            with (path/'all_scores.csv').open() as f:
                rows=list(csv.DictReader(f))
            scores=np.array([int(row['score']) for row in rows]).reshape(10000,30)
        assert scores.shape==(10000,30)
        assert np.all((scores>=0)&(scores<=50))
        actual=np.bincount(scores.ravel(),minlength=51)
        with (path/hist_file).open() as f:
            histogram=list(csv.DictReader(f))
        assert [int(row['score']) for row in histogram]==list(range(51))
        assert np.array_equal([int(row['count']) for row in histogram],actual)
        with (path/per_file).open() as f:
            stats=list(csv.DictReader(f))
        assert len(stats)==10000
        for key,expected in [('mean',scores.mean(axis=1)),('median',np.median(scores,axis=1)),('std',scores.std(axis=1,ddof=ddof))]:
            assert np.allclose([float(row[key]) for row in stats],expected)
        if 'kutyev' in folder:
            source_summary=json.loads((path/'summary_stats.json').read_text())
            averaged=source_summary['variant_1_avg_of_per_run_stats'];all_stats=source_summary['variant_2_from_pooled_data']
        elif 'volzhanin' in folder:
            source_summary=json.loads((path/'summary_stats.json').read_text())
            averaged=source_summary['averaged_over_runs'];all_stats=source_summary['pooled_all_runs']
        else:
            source_summary=json.loads((path/'summary.json').read_text())
            averaged=source_summary['per_run_stats_averaged'];all_stats=source_summary['pooled_stats']
        for key in ['mean','median','std']:
            assert np.isclose(averaged[key],np.mean([float(row[key]) for row in stats]))
        assert np.isclose(all_stats['mean'],scores.mean())
        assert np.isclose(all_stats['median'],np.median(scores))
        assert np.isclose(all_stats['std'],scores.std(ddof=ddof))
        report[author]={'runs':10000,'students':300000,'original_std_ddof':ddof,
            'mean':float(scores.mean()),'median':float(np.median(scores)),
            'population_std':float(scores.std(ddof=0)),
            'four_five_per_group':float((scores>=33).sum()/10000),'verification':'passed'}
    (ROOT/'results/original-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':audit()
