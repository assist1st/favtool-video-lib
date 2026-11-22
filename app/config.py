import sys
from pathlib import Path

# 打包成 exe 后：程序文件在临时解包目录，可写数据放在 exe 同级目录
FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ROOT = Path(sys.executable).resolve().parent if FROZEN else BUNDLE_DIR

APP_DIR = BUNDLE_DIR / "app"
WEB_DIR = APP_DIR / "web"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "fav.db"
COVERS_DIR = DATA_DIR / "covers"
EXPORTS_DIR = DATA_DIR / "exports"
DOWNLOADS_DIR = ROOT / "downloads"
LOGS_DIR = ROOT / "logs"
BROWSER_PROFILE = DATA_DIR / "browser_profile"

for _d in (DATA_DIR, COVERS_DIR, EXPORTS_DIR, DOWNLOADS_DIR, LOGS_DIR, BROWSER_PROFILE):
    _d.mkdir(parents=True, exist_ok=True)

APP_VERSION = "0.2-core"
HOST = "127.0.0.1"
PORT = 8765
BASE_URL = f"http://{HOST}:{PORT}"

# 「全部」并不等于无限：单次扫描的安全上限，防止收藏异常增长或分页失控时把内存吃爆
MAX_SCAN = 3000
