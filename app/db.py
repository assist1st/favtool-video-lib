"""SQLite 存取层。视频本体与收藏关系分表，同一视频只存一份。"""
import datetime
import sqlite3

from .config import DB_PATH
from .classify import classify

SCHEMA = """
CREATE TABLE IF NOT EXISTS aweme (
    aweme_id     TEXT PRIMARY KEY,
    desc         TEXT,
    author_name  TEXT,
    author_id    TEXT,
    duration     INTEGER,          -- 毫秒
    cover_url    TEXT,
    cover_local  TEXT,
    play_url     TEXT,
    create_time  INTEGER,
    category     TEXT,             -- 规则分类结果（类目名）
    first_seen   TEXT
);
CREATE TABLE IF NOT EXISTS fav_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    aweme_id    TEXT NOT NULL,
    folder_name TEXT NOT NULL DEFAULT '默认收藏',
    fav_time    INTEGER,
    first_seen  TEXT,
    last_seen   TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
    ,
    archived    INTEGER NOT NULL DEFAULT 0,  -- 本地归档：只影响工具内视图，不动平台收藏
    fav_seq     INTEGER                      -- 收藏顺序：1 = 收藏列表顶部（最近收藏）
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fav ON fav_item(aweme_id, folder_name);
CREATE TABLE IF NOT EXISTS op_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT, action TEXT, aweme_id TEXT, result TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY, v TEXT
);
"""


def _migrate(conn):
    """老库升级：缺列就补，不丢数据。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(fav_item)").fetchall()}
    if "archived" not in cols:
        conn.execute(
            "ALTER TABLE fav_item ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    acols = {r["name"] for r in conn.execute("PRAGMA table_info(aweme)").fetchall()}
    if "category" not in acols:
        conn.execute("ALTER TABLE aweme ADD COLUMN category TEXT")
        conn.commit()
    if "fav_seq" not in cols:
        conn.execute("ALTER TABLE fav_item ADD COLUMN fav_seq INTEGER")
        # 存量按入库顺序回填：采集自列表顶部往下，所以 id 升序 = 收藏由新到旧；
        # fav_seq 越大代表越新（1 = 最早收藏）
        rows = conn.execute("SELECT id FROM fav_item ORDER BY id ASC").fetchall()
        n = len(rows)
        conn.executemany("UPDATE fav_item SET fav_seq=? WHERE id=?",
                         [(n - i, r["id"]) for i, r in enumerate(rows)])
        conn.commit()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def set_archived(ids, archived=True):
    """本地归档/取消归档。不触碰平台收藏，随时可撤销。"""
    if not ids:
        return 0
    conn = connect()
    try:
        marks = ",".join("?" for _ in ids)
        # 返回真正被改动的行数：ids 里混进库里没有的 id 时，
        # 界面提示的「已归档 N 条」不能比实际多。
        n = conn.execute(
            f"UPDATE fav_item SET archived=? WHERE aweme_id IN ({marks})",
            [1 if archived else 0] + list(ids),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    for aid in ids:
        log("archive" if archived else "unarchive", aid, "ok")
    return n


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def upsert_items(items, folder="默认收藏", reseq=False):
    """items 为 list[VideoItem]。返回 (新增数, 更新数)。

    reseq=True（完整重扫时）按本次列表顺序重排 fav_seq：
    列表顶部是最近收藏，所以越靠前 seq 越大，1 = 最早收藏。
    增量更新只给新条目接在当前最大值之后，不动老条目的顺序。
    """
    conn = connect()
    try:
        now = _now()
        new_count = updated = 0
        base = conn.execute("SELECT COALESCE(MAX(fav_seq), 0) FROM fav_item").fetchone()[0]
        total = len(items)
        seq = base
        for i, it in enumerate(items):
            existed = conn.execute(
                "SELECT 1 FROM aweme WHERE aweme_id=?", (it.aweme_id,)
            ).fetchone()
            conn.execute(
                """INSERT INTO aweme(aweme_id, desc, author_name, author_id, duration,
                                    cover_url, cover_local, play_url, create_time,
                                    category, first_seen)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(aweme_id) DO UPDATE SET
                     desc=excluded.desc,
                     author_name=excluded.author_name,
                     author_id=excluded.author_id,
                     duration=excluded.duration,
                     cover_url=excluded.cover_url,
                     cover_local=COALESCE(excluded.cover_local, aweme.cover_local),
                     play_url=excluded.play_url,
                     create_time=excluded.create_time,
                     category=excluded.category""",
                (it.aweme_id, it.desc, it.author_name, it.author_id, it.duration_ms,
                 it.cover_url, it.cover_local, it.play_url, it.create_time,
                 classify(it.desc, it.author_name)[0], now),
            )
            fav = conn.execute(
                "SELECT fav_seq FROM fav_item WHERE aweme_id=? AND folder_name=?",
                (it.aweme_id, folder),
            ).fetchone()
            if reseq and fav is not None:
                conn.execute(
                    "UPDATE fav_item SET last_seen=?, fav_seq=? WHERE aweme_id=? AND folder_name=?",
                    (now, total - i, it.aweme_id, folder),
                )
            elif fav is None:
                seq += 1
                newseq = total - i if reseq else seq
                conn.execute(
                    "INSERT INTO fav_item(aweme_id, folder_name, first_seen, last_seen, status, fav_seq)"
                    " VALUES(?,?,?,?, 'active', ?)",
                    (it.aweme_id, folder, now, now, newseq),
                )
            else:
                conn.execute(
                    "UPDATE fav_item SET last_seen=? WHERE aweme_id=? AND folder_name=?",
                    (now, it.aweme_id, folder),
                )
            if existed:
                updated += 1
            else:
                new_count += 1
        conn.commit()
    finally:
        # 无论正常结束还是中途抛异常，连接都要关：漏关的话这个连接会一直
        # 占着 WAL 写锁，界面上的读和写都被卡住，任务也会卡在半路。
        conn.close()
    return new_count, updated


def list_items(q="", author="", sort="first_seen", order="desc", archive="hide"):
    # 两张表都可能有同名列，排序必须限定表别名
    sort_cols = {
        "first_seen": "f.first_seen",
        "fav_seq": "f.fav_seq",
        "duration": "a.duration",
        "author_name": "a.author_name",
        "create_time": "a.create_time",
        "id": "f.id",
    }
    col = sort_cols.get(sort, "f.first_seen")
    order = "DESC" if str(order).lower() != "asc" else "ASC"
    sql = (
        "SELECT a.aweme_id, a.desc, a.author_name, a.duration, a.cover_local, "
        "a.play_url, a.create_time, a.category, f.folder_name, f.first_seen, "
        "f.archived, f.fav_seq, f.status "
        "FROM aweme a JOIN fav_item f ON f.aweme_id=a.aweme_id "
        "WHERE 1=1 "
    )
    if archive == "every":
        pass                      # 全部状态：界面自己在前端分流，避免来回发请求
    elif archive == "missing":
        sql += "AND f.status='missing' "
    elif archive == "only":
        sql += "AND f.status='active' AND f.archived=1 "
    elif archive in ("hide", "", None):
        sql += "AND f.status='active' AND f.archived=0 "
    else:
        sql += "AND f.status='active' "
    params = []
    if q:
        # 用户输入里的 % _ \ 会被当成 LIKE 通配符，先转义再用 ESCAPE 声明，
        # 否则搜「100%」会变成「任意内容」，搜「_」会匹配到几乎所有条目。
        like = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += "AND (a.desc LIKE ? ESCAPE '\\' OR a.author_name LIKE ? ESCAPE '\\') "
        params += [f"%{like}%", f"%{like}%"]
    if author:
        sql += "AND a.author_name = ? "
        params.append(author)
    sql += f"ORDER BY {col} {order}"
    conn = connect()
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def mark_missing(ids):
    """完整重扫时没再出现的条目：标成 missing，移出主列表，进「失效」视图。

    只改本地状态，不动平台；用户确认后才由 purge 真删。
    """
    if not ids:
        return 0
    conn = connect()
    try:
        marks = ",".join("?" for _ in ids)
        n = conn.execute(
            f"UPDATE fav_item SET status='missing', archived=0, fav_seq=NULL "
            f"WHERE aweme_id IN ({marks}) AND status='active'",
            list(ids),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def purge(ids):
    """彻底删除：只允许删 missing 状态的条目，视频本体无人引用时一并清掉。"""
    if not ids:
        return 0
    conn = connect()
    try:
        marks = ",".join("?" for _ in ids)
        n = conn.execute(
            f"DELETE FROM fav_item WHERE aweme_id IN ({marks}) AND status='missing'",
            list(ids),
        ).rowcount
        conn.execute(
            "DELETE FROM aweme WHERE aweme_id NOT IN (SELECT aweme_id FROM fav_item)"
        )
        conn.commit()
    finally:
        conn.close()
    return n


def stats():
    conn = connect()
    total = conn.execute("SELECT COUNT(*) c FROM fav_item WHERE status='active'").fetchone()["c"]
    authors = conn.execute(
        "SELECT COUNT(DISTINCT a.author_name) c FROM aweme a JOIN fav_item f ON f.aweme_id=a.aweme_id WHERE f.status='active'"
    ).fetchone()["c"]
    dur = conn.execute(
        "SELECT COALESCE(SUM(a.duration),0) s FROM aweme a JOIN fav_item f ON f.aweme_id=a.aweme_id WHERE f.status='active'"
    ).fetchone()["s"]
    with_cover = conn.execute(
        "SELECT COUNT(*) c FROM aweme a JOIN fav_item f ON f.aweme_id=a.aweme_id "
        "WHERE f.status='active' AND a.cover_local IS NOT NULL AND a.cover_local<>''"
    ).fetchone()["c"]
    top = conn.execute(
        "SELECT a.author_name name, COUNT(*) c FROM aweme a JOIN fav_item f ON f.aweme_id=a.aweme_id "
        "WHERE f.status='active' GROUP BY a.author_name ORDER BY c DESC LIMIT 8"
    ).fetchall()
    archived = conn.execute(
        "SELECT COUNT(*) c FROM fav_item WHERE status='active' AND archived=1"
    ).fetchone()["c"]
    cats = conn.execute(
        "SELECT COALESCE(a.category,'未分类') name, COUNT(*) c FROM aweme a "
        "JOIN fav_item f ON f.aweme_id=a.aweme_id WHERE f.status='active' "
        "GROUP BY name ORDER BY c DESC"
    ).fetchall()
    missing = conn.execute(
        "SELECT COUNT(*) c FROM fav_item WHERE status='missing'"
    ).fetchone()["c"]
    conn.close()
    return {
        "total": total,
        "authors": authors,
        "duration_ms": dur,
        "with_cover": with_cover,
        "archived": archived,
        "missing": missing,
        "categories": [dict(r) for r in cats],
        "top_authors": [dict(r) for r in top],
    }


def get_items(ids):
    if not ids:
        return []
    conn = connect()
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT aweme_id, desc, author_name, duration, play_url FROM aweme WHERE aweme_id IN ({marks})",
        list(ids),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def active_ids():
    """库里当前有效（未被取消）的收藏 id，用于增量更新判断。"""
    conn = connect()
    rows = conn.execute(
        "SELECT aweme_id FROM fav_item WHERE status='active'"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def cap_cover_local(aweme_id, filename):
    """记下封面已经落到本地，下次直接用文件、不再联网。"""
    conn = connect()
    try:
        conn.execute(
            "UPDATE aweme SET cover_local=? WHERE aweme_id=? AND coalesce(cover_local,'')=''",
            (filename, aweme_id),
        )
        conn.commit()
    finally:
        conn.close()


def log(action, aweme_id, result, detail=""):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO op_log(ts, action, aweme_id, result, detail) VALUES(?,?,?,?,?)",
            (_now(), action, aweme_id, result, detail),
        )
        conn.commit()
    finally:
        conn.close()
