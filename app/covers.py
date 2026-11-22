"""封面本地缓存：抖音图片有 referer 校验，必须落本地再给前端读。"""
import httpx

from .config import COVERS_DIR

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def cache_cover(url: str, aweme_id: str) -> str:
    """成功返回本地文件名，失败返回空串（不阻断主流程）。"""
    if not url:
        return ""
    fname = f"{aweme_id}.jpg"
    path = COVERS_DIR / fname
    if path.exists() and path.stat().st_size > 1024:
        return fname
    try:
        r = httpx.get(
            url,
            headers={"Referer": "https://www.douyin.com/", "User-Agent": UA},
            timeout=15,
            follow_redirects=True,
        )
        if r.status_code == 200 and len(r.content) > 1024:
            path.write_bytes(r.content)
            return fname
    except Exception:
        return ""
    return ""
