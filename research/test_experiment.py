import csv
import gzip
from pathlib import Path
from statistics import mean, median, pstdev
import tempfile
import unittest
from research.experiment import Config, POLICIES, grade, pooled, run, scenario, select, simulate
from collections import Counter


class ExperimentTests(unittest.TestCase):
    def test_grade_boundaries(self):
        self.assertEqual([grade(s) for s in [0,24,25,32,33,44,45,50]], [2,2,3,3,4,4,5,5])

    def test_full_points_on_deadline_and_penalties(self):
        for week, expected in [(2,5),(3,4),(6,1),(7,0)]:
            config = Config(students=1, labs=1, weeks=week)
            data = ([0.5],[0],[[0.9]]*(week-1)+[[0.1]],[[0]]*week)
            scores, completed, counters = simulate(config, data, 'deadline')
            self.assertEqual(scores,[expected])
            self.assertEqual(completed,[1])
            self.assertEqual(counters['attempts'],week)

    def test_capacity_and_one_attempt_per_week(self):
        config = Config(students=2,labs=2,weeks=1,capacity=1)
        result = simulate(config,([1,1],[0,1],[[0,0]],[[0,1]]),'fifo')
        self.assertEqual(result[0],[5,0])
        self.assertEqual(result[1],[1,0])
        self.assertEqual(result[2]['capacity_misses'],1)
        self.assertEqual(result[2]['failed_opportunities'],1)

    def test_zero_success_never_unlocks_next_lab(self):
        config=Config(students=1,weeks=30)
        result=simulate(config,([0],[0],[[0]]*30,[[0]]*30),'random')
        self.assertEqual(result[0],[0])
        self.assertEqual(result[1],[0])
        self.assertEqual(result[2]['failed_attempts'],30)

    def test_deadline_and_score_and_threshold_policies(self):
        config=Config(capacity=1)
        args=([0,1],[32,40],[3,5],10,{0:0,1:1},[0,1],config)
        self.assertEqual(select('deadline',*args),[0])
        self.assertEqual(select('score',*args),[1])
        self.assertEqual(select('chance_5',*args),[1])
        self.assertEqual(select('chance_4',*args),[0])

    def test_policy_cannot_change_random_outcomes_without_capacity_constraint(self):
        config=Config(capacity=30)
        data=scenario(config,42)
        results=[simulate(config,data,p)[0] for p in POLICIES]
        self.assertTrue(all(r==results[0] for r in results))
        self.assertEqual(data,scenario(config,42))
        self.assertNotEqual(data,scenario(config,43))

    def test_aggregate_statistics_match_expanded_values(self):
        for values in [[0,0,10,10],[1,3,5],[0,50]]:
            stats=pooled(Counter(values))
            for key, expected in [('mean',mean(values)),('median',median(values)),('std',pstdev(values))]:
                self.assertAlmostEqual(stats[key],expected)

    def test_score_and_attempt_invariants(self):
        for seed in range(10):
            config=Config()
            for policy in POLICIES:
                scores,done,c=simulate(config,scenario(config,seed),policy)
                self.assertTrue(all(0<=s<=50 for s in scores))
                self.assertTrue(all(0<=n<=10 for n in done))
                self.assertEqual(c['attempts'],sum(done)+c['failed_attempts'])
                self.assertLessEqual(c['attempts'],600)

    def test_export_reproducible_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=Path(tmp)/'a',Path(tmp)/'b'
            config=Config(students=3,weeks=2,capacity=2)
            run(config,2,42,a);run(config,2,42,b)
            for path in a.rglob('*'):
                if path.is_file():self.assertEqual(path.read_bytes(),(b/path.relative_to(a)).read_bytes())
            for policy in POLICIES:
                with gzip.open(a/policy/'students.csv.gz','rt') as file:
                    self.assertEqual(len(list(csv.DictReader(file))),6)
                with (a/policy/'histogram.csv').open() as file:
                    rows=list(csv.DictReader(file))
                    self.assertEqual(len(rows),51)
                    self.assertEqual(sum(int(r['count']) for r in rows),6)
            with self.assertRaises(FileExistsError):run(config,2,42,a)

    def test_invalid_configuration(self):
        for kwargs in [{'capacity':0},{'students':True},{'weeks':1.5}]:
            with self.assertRaises(ValueError):Config(**kwargs)


if __name__=='__main__':
    unittest.main()
