"""演示数据：让 `launcher.py --demo` 不需要平台适配器、也不需要任何真实数据就能跑完整界面。

40 条示例，覆盖四个类目与六个月，含 3 条「已归档」，用来演示归档视图与类目×月份筛选。
全部为虚构内容，与任何真实账号、作者、视频无关。
"""
import datetime
import struct
import zlib

from . import db
from .classify import classify
from .config import COVERS_DIR, DEMO

NOW = datetime.datetime(2026, 11, 22, 12, 0, 0)

# (简介, 作者, 时长秒, 距今几天)
SAMPLE = [
    ("Excel 数据透视表：把 3000 行明细 3 分钟做成月报", "表格研究所", 213, 2),
    ("求职简历里的项目怎么写：从职责到结果的改写练习", "职场练手", 380, 3),
    ("AI 工作流拆解：把重复动作排成一条自动链路", "工作流笔记", 465, 5),
    ("用思维导图整理一门新技能的 30 天路径", "方法论频道", 287, 8),
    ("减脂期怎么吃：一周备餐清单与配比", "生活实验员", 340, 10),
    ("化妆新手的第一套工具，别买多", "素人化妆间", 260, 12),
    ("一部悬疑片的三条叙事线，第二次看才懂", "影评小站", 720, 15),
    ("美剧里最会写群像的一幕，逐帧拆", "剧集拆解局", 845, 18),
    ("纪录片镜头语言：为什么它不给你答案", "影像笔记", 610, 21),
    ("短剧为什么三分钟就能留住人", "内容观察员", 520, 24),
    ("大结局之后，故事真正的落点在哪", "影评小站", 690, 28),
    ("成年人的内耗，往往从一句「我没事」开始", "树洞频道", 195, 30),
    ("情绪上头的三分钟，先别做决定", "心理小课", 240, 33),
    ("恋爱里最容易忽略的沟通错位", "关系观察", 305, 36),
    ("独居第三年，我学会了和自己吃饭", "生活切片", 180, 40),
    ("焦虑不是敌人，是没被翻译的需求", "心理小课", 268, 44),
    ("城市探店：开在老小区的咖啡店", "街头食记", 330, 47),
    ("在家做饭菜谱：20 分钟晚饭，食材只要五样", "厨房最小化", 295, 50),
    ("旅行只带一个背包：七天装备清单", "轻装上路", 410, 54),
    ("酒店怎么选：三个容易被忽略的细节", "出门笔记", 355, 58),
    ("数码开箱：这只充电头的取舍", "器物评测", 262, 62),
    ("护肤流程砍到三步，皮肤反而稳定了", "成分观察", 225, 66),
    ("穿搭基础款：五件衣服的十种组合", "衣橱整理", 300, 70),
    ("一家餐厅的菜单结构，藏着它的定位", "餐饮观察", 275, 74),
    ("python 处理表格：把手工复制粘贴换掉", "代码小工具", 480, 78),
    ("面试前一周的准备清单，按小时排", "求职陪跑", 398, 82),
    ("考研复习的节奏感，比时长更重要", "自习室频道", 342, 86),
    ("健身新手四周计划：先练动作再加重量", "训练日记", 425, 90),
    ("体态问题自查：三个动作看出差别", "训练日记", 310, 95),
    ("唱歌发声练习：每天十分钟的基础功", "声乐小课", 288, 100),
    ("发音纠正：几个最容易混的音", "语言练习室", 235, 105),
    ("AI 绘画提示词怎么写才稳定", "ai工具站", 372, 110),
    ("AI 剪辑：把三小时素材压成三分钟", "ai工具站", 445, 115),
    ("用记忆法背专业书，先做结构再做细节", "学习实验室", 320, 120),
    ("工作流复盘：哪一步其实可以删掉", "工作流笔记", 355, 126),
    ("编程入门别从语法开始，从一个小目标开始", "代码小工具", 300, 132),
    ("面试官问「你还有什么问题」，怎么答", "求职陪跑", 245, 140),
    ("打卡式旅行之外，另一种走法", "轻装上路", 385, 148),
    ("早餐菜谱：不开火，一周不重样", "厨房最小化", 205, 155),
    ("看完一部电影，怎么把它记住", "影像笔记", 265, 162),
]

ARCHIVED = {3, 17, 31}   # 这三条在 demo 里预置为「已归档」，用来演示归档视图

# 按类目配色，生成渐变色封面（纯 stdlib 写 PNG，不引入 Pillow，也不往仓库塞图片）
PALETTE = {
    "影视解说": ((20, 34, 62), (54, 92, 148)),
    "情绪共鸣": ((58, 36, 74), (122, 84, 132)),
    "生活消费": ((28, 66, 50), (62, 124, 84)),
    "技能学习": ((116, 58, 18), (206, 126, 44)),
    "未分类":   ((64, 64, 64), (108, 108, 108)),
}
COVER_W, COVER_H = 480, 640


def _pixel(t, top, bottom, jitter):
    return tuple(
        max(0, min(255, int(top[k] * (1 - t) + bottom[k] * t) + jitter))
        for k in range(3)
    )


def _write_png(path, top, bottom, jitter):
    rows = []
    for y in range(COVER_H):
        t = y / (COVER_H - 1)
        rgb = _pixel(t, top, bottom, jitter)
        rows.append(b"\x00" + bytes(rgb) * COVER_W)
    raw = b"".join(rows)

    def chunk(typ, data):
        crc = zlib.crc32(typ + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", crc)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", COVER_W, COVER_H, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _make_covers(categories):
    """给每条示例生成一张渐变色封面，文件名 demo-000.png …"""
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for i, cat in enumerate(categories):
        top, bottom = PALETTE.get(cat, PALETTE["未分类"])
        jitter = (i % 7) * 6 - 18      # 轻微色差，避免 40 张封面一模一样
        _write_png(COVERS_DIR / f"demo-{i:03d}.png", top, bottom, jitter)


def seed_if_empty():
    """只在 demo 库里灌一次；重复启动不会叠加。返回灌入条数。"""
    if not DEMO:
        return 0
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM fav_item").fetchone()[0]
        if n:
            return 0
        total = len(SAMPLE)
        now_iso = NOW.isoformat(timespec="seconds")
        cats = [classify(desc, author)[0] for desc, author, _, _ in SAMPLE]
        _make_covers(cats)
        for i, (desc, author, secs, days_ago) in enumerate(SAMPLE):
            aid = f"demo{1000 + i}"
            cover = f"demo-{i:03d}.png"
            created = (NOW - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
            cat = cats[i]
            conn.execute(
                """INSERT INTO aweme(aweme_id, desc, author_name, author_id, duration,
                                     cover_url, cover_local, play_url, create_time,
                                     category, first_seen)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, desc, author, f"author{abs(hash(author)) % 1000:03d}", secs * 1000,
                 "", cover, f"demo://{aid}", int((NOW - datetime.timedelta(days=days_ago)).timestamp()),
                 cat, now_iso),
            )
            conn.execute(
                """INSERT INTO fav_item(aweme_id, folder_name, fav_time, first_seen,
                                        last_seen, status, archived, fav_seq)
                   VALUES(?,?,?,?,?, 'active', ?, ?)""",
                (aid, "示例收藏", int((NOW - datetime.timedelta(days=days_ago)).timestamp()),
                 now_iso, now_iso, 1 if i in ARCHIVED else 0, total - i),
            )
        conn.commit()
        return total
    finally:
        conn.close()
