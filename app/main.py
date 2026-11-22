"""本地服务：清单页 + 只读 API + 导出。写操作（下载/取消收藏）在 v0.3/v0.4 开放。"""
import csv
import datetime
import json
import subprocess
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import covers, db
from .config import (APP_VERSION, BASE_URL, COVERS_DIR, EXPORTS_DIR, HOST,
                     PORT, ROOT, WEB_DIR)
from .runner import pid_alive, read_status, reset_status

app = FastAPI(title="收藏视频工具箱", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
app.mount("/covers", StaticFiles(directory=str(COVERS_DIR)), name="covers")
app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")


class ExportReq(BaseModel):
    ids: list[str] = []
    fmt: str = "csv"


class CollectReq(BaseModel):
    target: int = 0
    full: bool = False      # True = 完整重扫到底，不做增量提前结束


@app.on_event("startup")
def _reset_stale_status():
    """程序启动时，把上次被中断任务的残影清掉，否则按钮会被永久锁死。"""
    try:
        if read_status().get("state") in ("starting", "waiting_login", "collecting"):
            reset_status("上次任务已中断")
    except Exception:
        pass


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION, "base_url": BASE_URL}


class ArchiveReq(BaseModel):
    ids: list[str] = []
    archived: bool = True


@app.get("/api/items")
def items(q: str = "", author: str = "", sort: str = "first_seen",
          order: str = "desc", archive: str = "hide"):
    return {"items": db.list_items(q=q, author=author, sort=sort,
                                   order=order, archive=archive)}


@app.post("/api/archive")
def archive(req: ArchiveReq):
    """本地归档：只改本地视图，平台收藏一条不动，随时可撤销。"""
    n = db.set_archived(req.ids, req.archived)
    return {"ok": True, "count": n, "archived": req.archived}


class PurgeReq(BaseModel):
    ids: list[str] = []
    mode: str = "ids"        # ids = 删指定条目；missing = 清空全部失效条目


@app.post("/api/purge")
def purge(req: PurgeReq):
    """彻底删除失效条目（只删本地库，不碰平台收藏）。"""
    if req.mode == "missing":
        conn = db.connect()
        ids = [r["aweme_id"] for r in conn.execute(
            "SELECT aweme_id FROM fav_item WHERE status='missing'")]
        conn.close()
    else:
        ids = req.ids
    n = db.purge(ids)
    return {"ok": True, "count": n}


@app.get("/api/stats")
def stats():
    return db.stats()


@app.get("/cover/{aweme_id}")
def cover(aweme_id: str):
    """封面按需下载：页面滚到哪张才取哪张，几百条也不会一次性拉爆。"""
    conn = db.connect()
    row = conn.execute(
        "SELECT cover_local, cover_url FROM aweme WHERE aweme_id=?", (aweme_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "没有这条记录")
    if row["cover_local"]:
        p = COVERS_DIR / row["cover_local"]
        if p.exists():
            return FileResponse(p, media_type="image/jpeg")
    fn = covers.cache_cover(row["cover_url"], aweme_id)
    if fn:
        p = COVERS_DIR / fn
        if p.exists():
            db.cap_cover_local(aweme_id, fn)
            return FileResponse(p, media_type="image/jpeg")
    raise HTTPException(404, "封面取不到")


@app.get("/api/authors")
def authors():
    conn = db.connect()
    rows = conn.execute(
        "SELECT a.author_name name, COUNT(*) c FROM aweme a JOIN fav_item f "
        "ON f.aweme_id=a.aweme_id WHERE f.status='active' AND a.author_name<>'' "
        "GROUP BY a.author_name ORDER BY c DESC LIMIT 60"
    ).fetchall()
    conn.close()
    return {"authors": [dict(r) for r in rows]}


@app.post("/api/collect")
def collect(req: CollectReq):
    st = read_status()
    if st.get("state") in ("starting", "waiting_login", "collecting"):
        if pid_alive(st.get("pid")):
            raise HTTPException(409, "已有抓取任务在进行中，请等它结束")
        reset_status("上次任务已中断，可重新开始")
    target = max(0, int(req.target or 0))
    extra = ["--full"] if req.full else []
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--collect", "--target", str(target)] + extra
    else:
        cmd = [sys.executable, str(ROOT / "launcher.py"),
               "--collect", "--target", str(target)] + extra
    flags = 0x08000000 if sys.platform == "win32" else 0
    subprocess.Popen(
        cmd, cwd=str(ROOT), creationflags=flags,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "state": "starting"}


@app.get("/api/collect/status")
def collect_status():
    return read_status()


@app.post("/api/export/links")
def export_links(req: ExportReq):
    rows = db.get_items(req.ids or [])
    if not rows:
        raise HTTPException(400, "没有可导出的条目")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if req.fmt == "md":
        name = f"收藏链接-{ts}.md"
        lines = ["# 收藏视频链接清单", ""]
        for i, r in enumerate(rows, 1):
            link = f"https://www.douyin.com/video/{r['aweme_id']}"
            lines.append(f"{i}. [{r['desc'] or r['aweme_id']}]({link}) — @{r['author_name']}")
        (EXPORTS_DIR / name).write_text("\n".join(lines), encoding="utf-8")
    else:
        name = f"收藏链接-{ts}.csv"
        with open(EXPORTS_DIR / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["序号", "aweme_id", "分享链接", "简介", "作者", "时长(秒)"])
            for i, r in enumerate(rows, 1):
                w.writerow([
                    i, r["aweme_id"], f"https://www.douyin.com/video/{r['aweme_id']}",
                    (r["desc"] or "").replace("\n", " "),
                    r["author_name"], round((r["duration"] or 0) / 1000, 1),
                ])
    db.log("export_links", f"{len(rows)}条", "ok", name)
    return {"file": name, "count": len(rows), "url": f"/exports/{name}"}


@app.post("/api/download")
def download(req: ExportReq):
    return JSONResponse(
        status_code=501,
        content={
            "ok": False,
            "reason": "批量下载待开放：实测 play_addr 单条平均 52.5MB，需先做降码率方案。",
        },
    )


# 取消收藏：已按需求舍弃，不再提供入口（平台侧写操作不可逆，风险高于收益）。


@app.get("/api/probe-report")
def probe_report():
    p = EXPORTS_DIR / "probe-report.json"
    if not p.exists():
        return {"ok": False, "reason": "尚未运行探针"}
    return json.loads(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
