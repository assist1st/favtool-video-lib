"""存取层的回归测试：用临时库，不碰 data/fav.db。"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db


class Item:
    """最小 VideoItem 替身：只带 upsert_items 用得到的字段。"""

    def __init__(self, aweme_id, desc="", author_name="", duration_ms=0):
        self.aweme_id = aweme_id
        self.desc = desc
        self.author_name = author_name
        self.author_id = ""
        self.duration_ms = duration_ms
        self.cover_url = ""
        self.cover_local = None
        self.play_url = ""
        self.create_time = 0


class BadItem(Item):
    """取 desc 就炸，用来验证出错时连接也会被关掉。"""

    def __init__(self, aweme_id):
        self.aweme_id = aweme_id

    @property
    def desc(self):
        raise RuntimeError("boom")


class _SpyConn:
    """包一层连接，记录 close 有没有被调用。"""

    def __init__(self, conn):
        self._conn = conn
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        self.closed = True
        self._conn.close()


class TestDb(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="favtool-db-"))
        self._saved = db.DB_PATH
        db.DB_PATH = self.tmp / "test.db"

    def tearDown(self):
        db.DB_PATH = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed(self, *ids):
        return db.upsert_items([Item(i, desc=f"视频{i}") for i in ids])

    def test_set_archived_returns_the_real_row_count(self):
        self._seed("a1", "a2")
        n = db.set_archived(["a1", "根本不存在"], True)
        # 库里只有 a1 命中，不能按 ids 的长度报 2
        self.assertEqual(n, 1)

    def test_set_archived_with_empty_ids(self):
        self._seed("a1")
        self.assertEqual(db.set_archived([], True), 0)

    def test_purge_only_deletes_missing_items(self):
        self._seed("a1", "a2")
        db.mark_missing(["a1"])
        n = db.purge(["a1", "a2"])
        self.assertEqual(n, 1)
        self.assertEqual(
            [r["aweme_id"] for r in db.list_items(archive="every")], ["a2"]
        )

    def test_upsert_counts_new_then_updated(self):
        self.assertEqual(self._seed("a1", "a2"), (2, 0))
        self.assertEqual(self._seed("a1", "a2"), (0, 2))

    def test_reseq_renumbers_by_scan_order(self):
        self._seed("a1", "a2", "a3")
        # 完整重扫：列表顶部是最近收藏的，序号要跟着扫描顺序重排
        db.upsert_items([Item("a3"), Item("a2"), Item("a1")], reseq=True)
        rows = {r["aweme_id"]: r["fav_seq"] for r in db.list_items(archive="every")}
        self.assertGreater(rows["a3"], rows["a2"])
        self.assertGreater(rows["a2"], rows["a1"])

    def test_connection_is_closed_when_upsert_raises(self):
        spies = []
        real_connect = db.connect

        def spy_connect():
            spy = _SpyConn(real_connect())
            spies.append(spy)
            return spy

        db.connect = spy_connect
        try:
            with self.assertRaises(RuntimeError):
                db.upsert_items([BadItem("a1")])
        finally:
            db.connect = real_connect
        self.assertTrue(spies and spies[0].closed)


if __name__ == "__main__":
    unittest.main()
