import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.sqlite_helpers import integrity_check, readonly_connection, table_columns, table_exists, write_transaction


class SQLiteHelpersTests(unittest.TestCase):
    def test_readonly_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.sqlite3"
            con = sqlite3.connect(path)
            con.execute("create table demo(id integer primary key, name text)")
            con.execute("insert into demo(name) values('one')")
            con.commit()
            con.close()

            self.assertEqual(integrity_check(path), "ok")
            with readonly_connection(path) as ro:
                self.assertTrue(table_exists(ro, "demo"))
                self.assertEqual(table_columns(ro, "demo"), ("id", "name"))
                with self.assertRaises(sqlite3.OperationalError):
                    ro.execute("insert into demo(name) values('blocked')")

    def test_write_transaction_commits_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.sqlite3"
            con = sqlite3.connect(path, isolation_level=None)
            con.execute("create table demo(value text)")
            with write_transaction(con):
                con.execute("insert into demo values('ok')")
            self.assertEqual(con.execute("select count(*) from demo").fetchone()[0], 1)

            with self.assertRaises(RuntimeError):
                with write_transaction(con):
                    con.execute("insert into demo values('bad')")
                    raise RuntimeError("boom")
            self.assertEqual(con.execute("select count(*) from demo").fetchone()[0], 1)
            con.close()


if __name__ == "__main__":
    unittest.main()
