"""把采集流程抽成可复用函数，供 CLI、界面按钮、打包后的 exe 共用。"""
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from app import db  # noqa: E402
try:
    from app.collector.douyin import DouyinAdapter  # noqa: E402
except ImportError:  # 平台适配器未随本仓库分发，见 README 的「边界」一节
    DouyinAdapter = None
from app.config import BROWSER_PROFILE, DATA_DIR, LOGS_DIR, MAX_SCAN  # noqa: E402

STATUS_FILE = DATA_DIR / "collect-status.json"


class Status:
    def __init__(self):
        self.data = {
            "state": "idle",
            "count": 0,
            "msg": "",
            "pid": os.getpid(),
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        }

    def set(self, state=None, count=None, msg=None):
        if state is not None:
            self.data["state"] = state
        if count is not None:
            self.data["count"] = count
        if msg is not None:
            self.data["msg"] = msg
        self.data["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            STATUS_FILE.write_text(
                json.dumps(self.data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass


def read_status():
    if not STATUS_FILE.exists():
        return {"state": "idle", "count": 0, "msg": ""}
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "idle", "count": 0, "msg": ""}
    # 任务被强杀会留下「进行中」的残影，超时即视为中断
    if data.get("state") in ("starting", "waiting_login", "collecting"):
        try:
            age = (datetime.datetime.now()
                   - datetime.datetime.fromisoformat(data.get("ts", ""))).total_seconds()
            if age > 1200:
                return {"state": "idle", "count": 0, "msg": "上次任务已中断"}
        except Exception:
            pass
    return data


def reset_status(msg="空闲"):
    """服务启动时调用：能启动就说明没有正在跑的采集任务。"""
    Status().set(state="idle", count=0, msg=msg)


def pid_alive(pid):
    """判断采集子进程是否还活着。用户手动关掉浏览器后，靠它解锁按钮。"""
    if not pid:
        return False
    try:
        pid = int(pid)
    except Exception:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:
        return True  # 查不了就当作还活着，宁可不误开新任务


def run_collect(target=0, headless=False, channel="msedge", login_timeout=900,
                incremental=True):
    st = Status()
    st.set(state="starting", count=0, msg="正在启动浏览器")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    report = {"ts": ts, "ok": False, "items": 0, "target": target,
              "incremental": incremental}

    def _launch(headless_flag):
        return p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE),
            headless=headless_flag,
            channel=(channel or None),
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled"]
            + ([] if headless_flag else ["--start-maximized"]),
        )

    with sync_playwright() as p:
        try:
            ctx = _launch(True)
        except Exception as e:
            st.set(state="error", msg=f"浏览器启动失败：{e}")
            return 1

        if DouyinAdapter is None:
            st.set(state="error", msg="平台适配器未就位：本仓库不含 app/collector/douyin.py，见 README「边界」")
            return 1

        ad = DouyinAdapter()

        def bind(c):
            ad.context = c
            ad.page = c.pages[0] if c.pages else c.new_page()

        bind(ctx)
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        try:
            logged = ad._has_session()
        except Exception:
            logged = False
        report["initial_has_session"] = logged

        # 已登录就全程无窗口跑：少一个窗口合成层，采集期间清单页不容易发涩
        if not logged and not headless:
            try:
                ctx.close()
            except Exception:
                pass
            st.set(state="waiting_login", msg="需要登录，正在打开浏览器窗口，请扫码")
            try:
                ctx = _launch(False)
            except Exception as e:
                st.set(state="error", msg=f"浏览器启动失败：{e}")
                return 1
            bind(ctx)
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )

        known = db.active_ids() if incremental else set()
        ad.known_ids = known
        ad.safety_cap = MAX_SCAN
        report["known_in_db"] = len(known)
        report["safety_cap"] = MAX_SCAN
        ad.progress_cb = lambda n: st.set(
            state="collecting", count=n,
            msg=f"已扫 {n} 条，新增 {ad.new_count} 条",
        )
        try:
            st.set(state="waiting_login", msg="正在确认登录态（已登录则全程无窗口）")
            if not ad.wait_login(ctx, login_timeout):
                st.set(state="error", msg="登录超时，请重试")
                return 2

            mode = "增量" if incremental else "完整重扫"
            limit = f"上限 {target} 条" if target else f"最多 {MAX_SCAN} 条（安全上限）"
            # 注：曾试过拦截缩略图请求来减负，实测会让收藏列表返回 0 条
            # （列表渲染依赖封面），已放弃，不要重试这条路。
            st.set(state="collecting", count=0, msg=f"正在打开收藏页（{mode}，{limit}）")
            ad.goto_favorites()
            items = ad.collect(target, incremental=incremental)
            total = len(items)
            st.set(state="collecting", count=total, msg=f"扫描完成，正在写库（{total} 条）")

            # 封面改为「页面滚到时才下载」，这里只入库不预缓存，几百条也不会卡住
            n_new = 0
            if items:
                n_new, n_upd = db.upsert_items(
                    items, folder="默认收藏", reseq=not incremental
                )
                report["db"] = {"new": n_new, "updated": n_upd}
            report["items"] = total
            report["new_items"] = ad.new_count
            report["early_stop"] = ad.early_stop
            report["capped"] = ad.capped
            report["ok"] = total > 0
            report["diagnostics"] = ad.diagnostics()

            # 消失检测：完整重扫 + 真到底才判定。命中的标成 missing，移出主列表、
            # 进「失效」视图；删不删由用户在界面上决定，工具不自动删。
            missing_n = 0
            if (not incremental) and ad.has_more == 0 and not ad.capped:
                try:
                    before = db.active_ids()
                    missing = sorted(before - {it.aweme_id for it in items})
                    missing_n = db.mark_missing(missing)
                    report["missing_count"] = missing_n
                except Exception as e:
                    report["missing_count"] = f"failed: {e}"

            if ad.capped:
                tail = f"（已达安全上限 {MAX_SCAN} 条，剩余未扫）"
            elif ad.early_stop:
                tail = "（增量已追平，未扫到底）"
            elif missing_n:
                tail = f"；另有 {missing_n} 条本次未出现，已放进「失效」视图，待你决定删除或保留"
            else:
                tail = ""
            st.set(
                state="done" if total else "empty",
                count=total,
                msg=f"完成：扫描 {total} 条，新增 {n_new} 条{tail}",
            )
        except Exception as e:
            report["error"] = f"{type(e).__name__}: {e}"
            try:
                report["diagnostics"] = ad.diagnostics()
            except Exception:
                pass
            st.set(state="error", msg=f"{type(e).__name__}: {e}")
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    try:
        (DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "exports" / "probe-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (LOGS_DIR / f"collect-{ts}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    return 0 if report.get("ok") else 1

