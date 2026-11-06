"""Design checks against temporary SQLite files; no application data is opened."""
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

DDL = Path(__file__).with_name("schema.sql").read_text()


def connect(path):
    con = sqlite3.connect(path, timeout=2, isolation_level=None)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    return con


def entry(con, key, student=1, session="s1", group="g1", teacher="t1", status="waiting", priority=-1, repeat=0):
    con.execute("""INSERT INTO queue_entries
        (request_key,session_id,course_id,group_id,teacher_key,student_id,lab_key,lab_order,
        full_name_snapshot,eligibility_snapshot,eligibility_checked_at,deadline_at,
        priority,is_repeat,joined_at,called_at,status)
        VALUES (?,?,'c1',?,?,?,'lab1',1,'Synthetic Student','v',10,20,?,?,10,?,?)""",
        (key, session, group, teacher, student, priority, repeat, 11 if status == "called" else None, status))


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "queue.sqlite3")
        self.con = connect(self.path)
        self.con.executescript(DDL)
        self.con.execute("INSERT INTO courses(course_id,title,schedule_source) VALUES ('c1','Test','manual')")
        for group in ("g1", "g2"):
            self.con.execute("INSERT INTO study_groups VALUES ('c1',?,?)", (group, group))
        for student in (1, 2):
            self.con.execute("INSERT INTO students VALUES (?,?,?,0)", (student, f"Synthetic {student}", f"user{student}"))
            self.con.execute("INSERT INTO course_students VALUES ('c1',?,'g1',?)", (student, str(student)))
        for sid, group, teacher in (("s1", "g1", "t1"), ("s2", "g2", "t1"), ("s3", "g2", "t2")):
            self.con.execute("""INSERT INTO sessions
                (session_id,course_id,group_id,teacher_key,source_key,source_kind,local_date,
                timezone,opens_at,starts_at,ends_at,expires_at,created_at)
                VALUES (?,'c1',?,?,?,'manual','2026-11-06','Europe/Moscow',0,10,20,30,0)""", (sid, group, teacher, sid))

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def test_restart_preserves_queue_and_history(self):
        entry(self.con, "r1")
        self.con.execute("INSERT INTO queue_events(session_id,entry_id,actor_kind,actor_key,kind,occurred_at) VALUES ('s1',1,'student','1','enrolled',10)")
        self.con.close()
        self.con = connect(self.path)
        self.assertEqual(self.con.execute("SELECT count(*) FROM queue_entries").fetchone()[0], 1)
        self.assertEqual(self.con.execute("SELECT count(*) FROM queue_events").fetchone()[0], 1)

    def test_one_active_entry_across_overlapping_sessions(self):
        entry(self.con, "r1")
        with self.assertRaises(sqlite3.IntegrityError):
            entry(self.con, "r2", session="s2", group="g2")

    def test_session_group_cannot_be_mixed(self):
        with self.assertRaises(sqlite3.IntegrityError):
            entry(self.con, "r1", group="g2")

    def test_same_teacher_cannot_call_two_students(self):
        entry(self.con, "r1", status="called")
        with self.assertRaises(sqlite3.IntegrityError):
            entry(self.con, "r2", student=2, session="s2", group="g2", status="called")
        entry(self.con, "r3", student=2, session="s3", group="g2", teacher="t2", status="called")

    def test_repeat_at_tail_even_with_urgent_priority(self):
        entry(self.con, "r1", student=1, priority=10)
        entry(self.con, "r2", student=2, repeat=1, priority=-1)
        rows = self.con.execute("""SELECT student_id FROM queue_entries WHERE status='waiting'
            ORDER BY is_repeat, CASE WHEN is_repeat=0 THEN priority ELSE 0 END, entry_id""").fetchall()
        self.assertEqual(rows, [(1,), (2,)])

    def test_terminal_entry_allows_rejoin_but_cannot_erase_events(self):
        entry(self.con, "r1")
        self.con.execute("UPDATE queue_entries SET status='failed',closed_at=15 WHERE entry_id=1")
        entry(self.con, "r2", repeat=1)
        self.con.execute("INSERT INTO queue_events(session_id,entry_id,actor_kind,actor_key,kind,occurred_at) VALUES ('s1',1,'teacher','t1','failed',15)")
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("DELETE FROM queue_events")

    def test_entry_and_event_transaction_roll_back_together(self):
        self.con.execute("BEGIN IMMEDIATE")
        entry(self.con, "r1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("INSERT INTO queue_events(session_id,entry_id,actor_kind,actor_key,kind,occurred_at) VALUES ('s2',1,'teacher','t1','called',11)")
        self.con.execute("ROLLBACK")
        self.assertEqual(self.con.execute("SELECT count(*) FROM queue_entries").fetchone()[0], 0)

    def test_simultaneous_enrollment_only_one_wins(self):
        barrier = threading.Barrier(2)
        results = []

        def insert(key):
            con = connect(self.path)
            barrier.wait()
            try:
                con.execute("BEGIN IMMEDIATE")
                entry(con, key)
                con.execute("COMMIT")
                results.append("ok")
            except sqlite3.IntegrityError:
                con.execute("ROLLBACK")
                results.append("duplicate")
            finally:
                con.close()

        threads = [threading.Thread(target=insert, args=(str(i),)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(results, ["ok", "duplicate"])

    def test_backup_includes_committed_wal_data(self):
        entry(self.con, "r1")
        with sqlite3.connect(Path(self.temp.name) / "backup.sqlite3") as backup:
            self.con.backup(backup)
            self.assertEqual(backup.execute("SELECT count(*) FROM queue_entries").fetchone()[0], 1)
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_cancellation_keeps_existing_entries(self):
        entry(self.con, "r1")
        self.con.execute("UPDATE sessions SET enrollment_status='cancelled' WHERE session_id='s1'")
        self.assertEqual(self.con.execute("SELECT status FROM queue_entries").fetchone()[0], "waiting")


if __name__ == "__main__":
    unittest.main()
