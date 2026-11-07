import importlib
import sys
from pathlib import Path
import tempfile
import types
import unittest

PACKAGE = 'queue_ops_test'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).parents[1] / 'grading/defense_queue')]
sys.modules[PACKAGE] = package
ops = importlib.import_module(PACKAGE + '.operations')
Store = importlib.import_module(PACKAGE + '.storage').QueueStore


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'queue.db')
        self.store.configure_group('c', 'g', title='Предмет')
        self.ids = []
        for i in range(3):
            sid = self.store.student(f'Студент {i}', f'user{i}', now=1)
            cid = self.store.qualify('c', 'g', sid, '1', 1, deadline_at=None, now=2+i)
            self.ids.append(cid)
        self.store.create_session('s', 'c', 'g', 'teacher', starts_at=100, ends_at=200, local_date='2026-11-06', now=1)
        for cid in self.ids[:2]:
            self.store.attendance('s', cid, True, now=10)
        self.course = {'queue': {}, 'timezone': 'UTC'}

    def tearDown(self):
        self.temp.cleanup()

    def view(self, now=110):
        return ops.teacher_view(self.store, 'c', 'g', self.course, deadlines_available=True, now=now, session_id='s')

    def test_whole_roster_with_current_and_next(self):
        before = self.view()
        self.assertEqual(len(before['entries']), 3)
        self.assertEqual(before['stats']['waiting'], 2)
        self.assertEqual(before['entries'][0]['attempt']['joined_at'], 10)
        self.assertEqual(before['entries'][0]['attendance_at'], 10)
        eid = ops.call_next(self.store, 's', now=111, actor='admin')
        second = ops.call_next(self.store, 's', now=112, actor='admin')
        self.assertNotEqual(second, eid)
        view = self.view()
        self.assertEqual(view['current_entry_id'], eid)
        self.assertEqual(view['current_entry_ids'], [eid, second])
        self.assertIsNone(view['next_entry_id'])
        ops.record_result(self.store, second, 'defended', now=113, actor='admin')
        self.assertEqual(self.view()['current_entry_ids'], [eid])

    def test_upgrade_v4_keeps_called_and_allows_another_defense(self):
        self.view()
        first = ops.call_next(self.store, 's', now=111, actor='admin')
        with self.store.transaction() as con:
            con.execute('DROP TABLE queue_commands')
            con.execute("CREATE UNIQUE INDEX one_called_per_teacher ON queue_entries(teacher_key) WHERE status='called'")
            con.execute('PRAGMA user_version=4')
        self.store = Store(self.store.path)
        second = ops.call_next(self.store, 's', now=112, actor='admin', request_id='second')
        self.assertEqual(ops.call_next(self.store, 's', now=113, actor='admin', request_id='second'), second)
        self.assertEqual(self.view()['current_entry_ids'], [first, second])
        with self.store.connection() as con:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 5)

    def test_parallel_distinct_calls_never_call_same_student_twice(self):
        from concurrent.futures import ThreadPoolExecutor
        self.view()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: ops.call_next(self.store, 's', now=111, actor='admin', request_id=f'command-{i}'), range(8)))
        called = [entry_id for entry_id in results if entry_id is not None]
        self.assertEqual(len(called), 2)
        self.assertEqual(len(set(called)), 2)
        self.assertEqual(set(self.view()['current_entry_ids']), set(called))
        with self.store.connection() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM queue_events WHERE kind='called'").fetchone()[0], 2)

    def test_failed_retry_tail_and_idempotency(self):
        self.view()
        eid = ops.call_next(self.store, 's', now=111, actor='admin')
        for _ in range(2):
            ops.record_result(self.store, eid, 'failed', now=112, actor='admin')
        view = self.view()
        self.assertEqual(view['stats']['failed'], 1)
        self.assertEqual(view['stats']['waiting'], 2)
        next_id = ops.call_next(self.store, 's', now=113, actor='admin')
        self.assertNotEqual(next_id, eid)
        called = next(row for row in self.view()['attempts'] if row['entry_id'] == next_id)
        self.assertEqual(called['candidate_id'], self.ids[1])

    def test_defense_updates_history_not_sheet(self):
        self.view()
        eid = ops.call_next(self.store, 's', now=111, actor='admin')
        ops.record_result(self.store, eid, 'defended', now=112, actor='admin')
        with self.store.connection() as con:
            self.assertEqual(con.execute('SELECT status FROM queue_candidates WHERE candidate_id=?', (self.ids[0],)).fetchone()[0], 'defended')

    def test_manual_tail_and_withdrawal(self):
        self.view()
        eid = ops.add_to_tail(self.store, 's', self.ids[2], now=111, actor='admin')
        view = self.view()
        self.assertEqual(view['entries'][-1]['candidate_id'], self.ids[2])
        ops.withdraw(self.store, eid, now=112, actor='admin')
        self.assertEqual(self.view()['stats']['withdrawn'], 1)

    def test_move_keeps_attendance_and_renews_snapshot(self):
        self.view()
        ops.move_session(self.store, 's', starts_at=300, ends_at=400, local_date='2026-11-07', now=120, actor='admin')
        self.store.attendance('s', self.ids[0], False, now=121)
        view = self.view(now=310)
        self.assertFalse(next(row for row in view['entries'] if row['candidate_id'] == self.ids[0])['will_attend'])
        self.assertEqual(view['stats']['waiting'], 1)

    def test_cancel_keeps_candidates(self):
        self.view()
        ops.cancel_session(self.store, 's', now=120, actor='admin')
        with self.store.connection() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM queue_candidates WHERE status='eligible'").fetchone()[0], 3)
        self.assertEqual(self.view()['stats']['expired'], 2)

    def test_settings_persist(self):
        ops.save_settings(self.store, 'c', random=True, deadlines={'1': None}, now=10)
        effective = ops.effective_course(Store(self.store.path), 'c', self.course)
        self.assertTrue(effective['queue']['random'])
        self.assertIsNone(effective['queue']['deadlines']['1'])

    def test_manual_tail_before_start_is_not_duplicated(self):
        ops.add_to_tail(self.store,'s',self.ids[0],now=10,actor='admin')
        view=self.view()
        self.assertEqual(len([r for r in view['attempts'] if r['candidate_id']==self.ids[0]]),1)
        self.assertTrue(next(r for r in view['attempts'] if r['candidate_id']==self.ids[0])['is_repeat'])

    def test_overlapping_class_does_not_duplicate_active_student(self):
        self.view()
        self.store.create_session('overlap','c','g','teacher2',starts_at=105,ends_at=205,local_date='1970-01-01',now=1)
        self.store.attendance('overlap',self.ids[0],True,now=90)
        view=ops.teacher_view(self.store,'c','g',self.course,deadlines_available=True,now=110,session_id='overlap')
        self.assertEqual(view['stats']['waiting'],0)

    def test_settings_can_remove_yaml_deadline_override(self):
        original={'queue':{'deadlines':{'1':'2026-01-01'},'random':True}}
        ops.save_schedule(self.store,'c','g',{'source':'manual'},now=5)
        self.assertTrue(ops.effective_course(self.store,'c',original)['queue']['random'])
        ops.save_settings(self.store,'c',random=False,deadlines={},now=6)
        self.assertEqual(ops.effective_course(self.store,'c',original)['queue']['deadlines'],{})
        self.assertFalse(ops.effective_course(self.store,'c',original)['queue']['random'])

    def test_early_close_reopen_and_freeze(self):
        ops.set_enrollment(self.store,'s',closed=True,now=20,actor='admin')
        with self.assertRaises(ValueError): self.store.attendance('s',self.ids[2],True,now=21)
        ops.set_enrollment(self.store,'s',closed=False,now=22,actor='admin')
        self.store.attendance('s',self.ids[2],True,now=23)
        self.assertEqual(self.view()['stats']['waiting'],3)
        with self.assertRaises(ValueError): ops.set_enrollment(self.store,'s',closed=False,now=100,actor='admin')

    def test_withdraw_and_manual_readd_in_same_second(self):
        first=ops.add_to_tail(self.store,'s',self.ids[2],now=10,actor='admin')
        ops.withdraw(self.store,first,now=10,actor='admin')
        second=ops.add_to_tail(self.store,'s',self.ids[2],now=10,actor='admin')
        self.assertNotEqual(first,second)
        with self.store.connection() as con:
            self.assertEqual(con.execute('SELECT status FROM queue_entries WHERE entry_id=?',(second,)).fetchone()[0],'waiting')


if __name__ == '__main__':
    unittest.main()
