"""采集层抽象。抖音先跑通，B站/小红书后续按同一接口接入。"""
from dataclasses import dataclass


@dataclass
class VideoItem:
    aweme_id: str
    desc: str = ""
    author_name: str = ""
    author_id: str = ""
    duration_ms: int = 0
    cover_url: str = ""
    cover_local: str = ""
    play_url: str = ""
    create_time: int = 0


class BaseAdapter:
    """adapter 契约：核心逻辑（runner / db）不感知平台差异。

    要实现四个方法；另外还要按下面的约定维护几个属性——
    runner 会读它们，契约里不写清楚，自己接适配器时一定对不上。
    """

    key = ""
    platform_name = ""

    # ---- 采集前由 runner 写入 ----
    known_ids: set = set()   # 已在库里的 id：增量判定「已追平」靠它
    safety_cap: int = 0      # 本次最多扫多少条（安全上限）
    progress_cb = None       # 每扫完一批调一次，入参是已扫条数

    # ---- 采集中由实现方维护 ----
    new_count: int = 0       # 本次新增条数
    early_stop: bool = False # 是否因「已追平」提前结束
    capped: bool = False     # 是否撞到 safety_cap
    has_more: int = 0        # 还剩几页（0 = 已扫到底）

    def wait_login(self, context, timeout_sec: int) -> bool:
        raise NotImplementedError

    def goto_favorites(self) -> None:
        raise NotImplementedError

    def collect(self, target: int, incremental: bool = True) -> list[VideoItem]:
        raise NotImplementedError

    def diagnostics(self) -> dict:
        raise NotImplementedError
