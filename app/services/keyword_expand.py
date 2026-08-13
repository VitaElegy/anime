"""Keyword expansion helpers for cross-language anime search.

Centralizes the Chinese/Japanese → English/Romaji expansion that used to live
in the search router so the channel aggregator can reuse it without importing
from the HTTP layer (docs/CHANNEL_ARCHITECTURE.md §1.2).
"""

from __future__ import annotations

import re

from app.services import bangumi
from app.services import database as db

#: Offline Chinese -> English/Romaji title map. This is the FIRST fallback so
#: Chinese-first search still reaches English/Romaji-indexed channels (Anilibria,
#: Gogoanime) even when Bangumi / network lookups are unreachable (verified
#: 2026-08-13: Bangumi down -> Chinese query alone produced 0 channel hits).
CHINESE_TITLE_MAP: dict[str, tuple[str, ...]] = {
    "孤独摇滚": ("BOCCHI THE ROCK!", "Bocchi the Rock!", "Bocchi"),
    "葬送的芙莉莲": ("Frieren", "Sousou no Frieren", "Frieren: Beyond Journey's End"),
    "间谍过家家": ("Spy x Family", "Spy Family"),
    "进击的巨人": ("Attack on Titan", "Shingeki no Kyojin", "AoT"),
    "鬼灭之刃": ("Demon Slayer", "Kimetsu no Yaiba"),
    "咒术回战": ("Jujutsu Kaisen", "Jujutsu"),
    "海贼王": ("One Piece",),
    "火影忍者": ("Naruto",),
    "名侦探柯南": ("Detective Conan", "Meitantei Conan"),
    "龙珠": ("Dragon Ball",),
    "死亡笔记": ("Death Note",),
    "钢之炼金术师": ("Fullmetal Alchemist", "Fullmetal Alchemist: Brotherhood"),
    "命运石之门": ("Steins;Gate", "Steins Gate"),
    "新世纪福音战士": ("Neon Genesis Evangelion", "Evangelion"),
    "我推的孩子": ("Oshi no Ko",),
    "电锯人": ("Chainsaw Man",),
    "蓝色监狱": ("Blue Lock",),
    "灌篮高手": ("Slam Dunk",),
    "千与千寻": ("Spirited Away", "Sen to Chihiro no Kamikakushi"),
    "你的名字": ("Your Name", "Kimi no Na wa"),
    "铃芽之旅": ("Suzume",),
    "天气之子": ("Weathering with You", "Tenki no Ko"),
    "辉夜大小姐想让我告白": ("Kaguya-sama: Love Is War", "Kaguya-sama"),
    "一拳超人": ("One Punch Man",),
    "排球少年": ("Haikyuu", "Haikyu!!"),
    "东京复仇者": ("Tokyo Revengers",),
    "关于我转生变成史莱姆这档事": ("That Time I Got Reincarnated as a Slime", "Tensei Shitara Slime Datta Ken", "TenSura"),
    "为美好的世界献上祝福": ("Konosuba", "KonoSuba"),
    "从零开始的异世界生活": ("Re:Zero", "Re:Zero - Starting Life in Another World"),
    "刀剑神域": ("Sword Art Online", "SAO"),
    "紫罗兰永恒花园": ("Violet Evergarden",),
    "约定的梦幻岛": ("The Promised Neverland", "Yakusoku no Neverland"),
    "灵能百分百": ("Mob Psycho 100",),
    "齐木楠雄的灾难": ("The Disastrous Life of Saiki K.", "Saiki Kusuo no Sai-nan"),
    "青春猪头少年不会梦到兔女郎学姐": ("Rascal Does Not Dream of Bunny Girl Senpai", "Seishun Buta Yarou"),
    "五等分的新娘": ("The Quintessential Quintuplets", "Gotoubun no Hanayome"),
    "赛马娘": ("Uma Musume Pretty Derby", "Uma Musume"),
    "少女终末旅行": ("Girls' Last Tour", "Shoujo Shuumatsu Ryokou"),
    "来自深渊": ("Made in Abyss",),
    "摇曳露营": ("Laid-Back Camp", "Yuru Camp"),
    "轻音少女": ("K-ON!", "K-On"),
    "冰菓": ("Hyouka",),
    "未闻花名": ("Anohana", "Ano Hi Mita Hana no Namae o Bokutachi wa Mada Shiranai"),
    "四月是你的谎言": ("Your Lie in April", "Shigatsu wa Kimi no Uso"),
    "暗杀教室": ("Assassination Classroom", "Ansatsu Kyoushitsu"),
    "东京喰种": ("Tokyo Ghoul",),
    "寄生兽": ("Parasyte", "Kiseijuu"),
    "夏目友人帐": ("Natsume's Book of Friends", "Natsume Yuujinchou"),
    "文豪野犬": ("Bungo Stray Dogs", "Bungou Stray Dogs"),
    "家庭教师": ("Reborn!", "Katekyo Hitman Reborn"),
    "黑子的篮球": ("Kuroko's Basketball", "Kuroko no Basuke"),
    "网球王子": ("The Prince of Tennis",),
    "火影忍者疾风传": ("Naruto Shippuden",),
    "死神": ("Bleach",),
    "银魂": ("Gintama",),
    "全职猎人": ("Hunter x Hunter", "HxH"),
    "JOJO的奇妙冒险": ("JoJo's Bizarre Adventure", "JoJo"),
    "天元突破红莲螺岩": ("Gurren Lagann", "Tengen Toppa Gurren Lagann"),
    "魔法少女小圆": ("Puella Magi Madoka Magica", "Madoka Magica"),
    "物语系列": ("Monogatari Series", "Bakemonogatari"),
    "无头骑士异闻录": ("Durarara!!",),
    "心理测量者": ("Psycho-Pass",),
    "黑塔利亚": ("Hetalia",),
    "境界的彼方": ("Beyond the Boundary", "Kyoukai no Kanata"),
    "冰上的尤里": ("Yuri!!! on Ice",),
    "工作细胞": ("Cells at Work!", "Hataraku Saibou"),
    "食戟之灵": ("Food Wars!", "Shokugeki no Soma"),
    "异世界食堂": ("Restaurant to Another World", "Isekai Shokudou"),
    "月光下的异世界之旅": ("Tsukimichi -Moonlit Fantasy-",),
    "转生成为了只有乙女游戏破灭Flag的邪恶大小姐": ("My Next Life as a Villainess", "Hamefura"),
    "魔法禁书目录": ("A Certain Magical Index", "Toaru Majutsu no Index"),
    "某科学的超电磁炮": ("A Certain Scientific Railgun", "Toaru Kagaku no Railgun"),
    "青春猪头少年": ("Rascal Does Not Dream of Bunny Girl Senpai", "Seishun Buta Yarou"),
    "时光代理人": ("Link Click", "Shiguang Dailiren"),
    "天官赐福": ("Heaven Official's Blessing", "Tian Guan Ci Fu"),
    "魔道祖师": ("Mo Dao Zu Shi", "Grandmaster of Demonic Cultivation"),
    "斗罗大陆": ("Soul Land", "Douluo Dalu"),
    "斗破苍穹": ("Battle Through the Heavens", "Doupo Cangqiong"),
    "完美世界": ("Perfect World",),
    "凡人修仙传": ("A Record of a Mortal's Journey to Immortality", "Fanren Xiu Xian Chuan"),
    "灵笼": ("Ling Cage", "Linglong"),
    "三体": ("Three-Body Problem", "San Ti"),
}


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def has_japanese(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text))


async def expand_keywords(keyword: str) -> list[str]:
    """Expand a Chinese/Japanese keyword into search-friendly alternatives.

    Always includes the original keyword; may also return romaji/English names
    from the local title map and Bangumi, which the channel aggregator tries in
    turn so sources that only index English titles still get hits.
    """
    alternatives: set[str] = set()
    alternatives.add(keyword)

    # Strategy 0: Offline Chinese title map (instant, no network).
    # Guards the "Chinese-first search" promise when remote lookups are down.
    if len(keyword) >= 2:
        for cn, names in CHINESE_TITLE_MAP.items():
            if cn in keyword or keyword in cn:
                alternatives.update(names)

    # Strategy 1: Local DB reverse lookup (instant, best quality)
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT cleaned_title, name, name_cn FROM title_cover_map WHERE name_cn LIKE ? OR name LIKE ? LIMIT 10",
                (f"%{keyword}%", f"%{keyword}%"),
            ).fetchall()
            for row in rows:
                if row["cleaned_title"]:
                    alternatives.add(row["cleaned_title"])
                if row["name"]:
                    alternatives.add(row["name"])
    except Exception:
        pass

    # Strategy 2: Bangumi search
    try:
        results = await bangumi.search(keyword, limit=3)
        for r in results:
            if r.name:
                alternatives.add(r.name)
                eng_words = re.findall(r"[A-Za-z]{3,}", r.name)
                for w in eng_words:
                    alternatives.add(w)
            if r.name_cn and r.name_cn != keyword:
                alternatives.add(r.name_cn)
    except Exception:
        pass

    return list(alternatives)


def normalize_title_key(title: str) -> str:
    """Normalize a title for deduping (strip bracketed tags, non-alnum, lowercase)."""
    t = re.sub(r"[\[\(（][^\]\)）]*[\]\)）]", "", title)
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t).lower()
    return t[:80]
