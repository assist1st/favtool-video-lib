"""唯一的入口：既当本地服务，也当采集器（打包成 exe 后同样可用）。

    python launcher.py              # 启动页面（自动打开浏览器）
    python launcher.py --demo       # 用内置示例数据启动，不需要适配器、不碰真实收藏
    python launcher.py --collect    # 抓取收藏（由页面的按钮调用）
"""
import argparse
import os
import socket
import threading
import time
import webbrowser


def port_busy(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def open_when_ready(host, port, url, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                break
        except Exception:
            time.sleep(0.4)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def serve():
    import uvicorn

    from app.config import BASE_URL, HOST, PORT
    from app.main import app

    if port_busy(HOST, PORT):
        print(f"[launcher] 已有实例在运行，直接打开页面 {BASE_URL}", flush=True)
        webbrowser.open(BASE_URL)
        return 0
    threading.Thread(target=open_when_ready, args=(HOST, PORT, BASE_URL), daemon=True).start()
    print(f"[launcher] 服务启动：{BASE_URL}（关闭此窗口即停止）", flush=True)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", workers=1)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="演示模式：内置 40 条示例数据 + 独立数据库/端口，不需要平台适配器")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--target", type=int, default=0, help="0 表示不设数量上限")
    ap.add_argument("--full", action="store_true", help="完整重扫到底，不用增量提前结束")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--channel", default="msedge", help="msedge / chrome / 空=自带内核")
    ap.add_argument("--login-timeout", type=int, default=900)
    args = ap.parse_args()

    # 必须在 import app.config 之前设环境变量：数据库与端口由它决定
    if args.demo:
        os.environ["FAVTOOL_DEMO"] = "1"
        os.environ.setdefault("FAVTOOL_PORT", "8788")

    if args.collect:
        from app.runner import run_collect

        return run_collect(
            target=args.target,
            headless=args.headless,
            channel=args.channel,
            login_timeout=args.login_timeout,
            incremental=not args.full,
        )
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
