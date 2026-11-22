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
    """adapter 契约：只实现这五个方法，核心逻辑不感知平台差异。"""

    key = ""
    platform_name = ""

    def wait_login(self, context, timeout_sec: int) -> bool:
        raise NotImplementedError

    def goto_favorites(self) -> None:
        raise NotImplementedError

    def collect(self, target: int) -> list[VideoItem]:
        raise NotImplementedError

    def diagnostics(self) -> dict:
        raise NotImplementedError

    def unfavorite(self, item: VideoItem) -> bool:
        raise NotImplementedError
