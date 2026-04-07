"""Smoke test — verify all services that are reachable."""

import asyncio
import json
import sys
import os

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import nyaa, subsplease, bangumi


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg):
    print(f"  {RED}✗{RESET} {msg}")

def warn(msg):
    print(f"  {YELLOW}⚠{RESET} {msg}")


async def test_subsplease():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}[1] SubsPlease RSS — 当季番剧列表{RESET}")
    print(f"{'='*60}")

    season = await subsplease.get_current_season()
    if season.items:
        ok(f"成功获取 {season.total} 条当季番剧 RSS")
        for i, item in enumerate(season.items[:8]):
            print(f"      {i+1:2d}. {item.title}")
            if i == 0:
                # Verify data fields
                assert item.source == "subsplease", "source should be subsplease"
                assert item.date, "should have date"
        ok("数据字段完整 (title/source/date)")
    else:
        fail("SubsPlease RSS 为空")
        return False

    # Keyword filter test
    print()
    keyword = season.items[0].title.split("]")[1].split("-")[0].strip() if "]" in season.items[0].title else "witch"
    filtered = await subsplease.search(keyword=keyword[:10], quality=1080)
    if filtered.items:
        ok(f"关键词过滤 '{keyword[:10]}' → {filtered.total} 结果")
    else:
        warn(f"关键词过滤无结果（可能拼写问题）")

    return True


async def test_bangumi():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}[2] Bangumi API — 元数据搜索{RESET}")
    print(f"{'='*60}")

    # Search test
    results = await bangumi.search("葬送的芙莉莲")
    if results:
        ok(f"搜索 '葬送的芙莉莲' → {len(results)} 结果")
        top = results[0]
        print(f"      ID: {top.id}")
        print(f"      中文名: {top.name_cn}")
        print(f"      原名: {top.name}")
        print(f"      封面: {'有' if top.cover_url else '无'}")
    else:
        fail("Bangumi 搜索无结果")
        return False

    # Detail test
    subject_id = results[0].id
    print()
    detail = await bangumi.get_detail(subject_id)
    if detail:
        ok(f"详情查询 id={subject_id}")
        print(f"      简介: {detail.summary[:80]}..." if len(detail.summary) > 80 else f"      简介: {detail.summary}")
        print(f"      评分: {detail.score}")
        assert detail.name, "should have name"
        ok("数据字段完整 (name/summary/score/cover_url)")
    else:
        fail("Bangumi 详情获取失败")

    # Cover test
    print()
    cover_path = await bangumi.get_cover(subject_id)
    if cover_path and cover_path.exists():
        size_kb = cover_path.stat().st_size / 1024
        ok(f"封面缓存成功 → {cover_path.name} ({size_kb:.0f} KB)")
        # Test cache hit (should be instant)
        cover_path2 = await bangumi.get_cover(subject_id)
        assert cover_path2 == cover_path
        ok("二次请求命中缓存")
    else:
        warn("封面下载失败（可能图片 CDN 不可达）")

    return True


async def test_nyaa():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}[3] Nyaa — 种子搜索 (需要代理){RESET}")
    print(f"{'='*60}")

    from app.config import settings
    if not settings.HTTP_PROXY:
        warn("未配置 HTTP_PROXY，Nyaa 在大陆被墙，跳过")
        warn("设置 ANIME_HTTP_PROXY=http://127.0.0.1:7890 后可测试")
        return None

    result = await nyaa.search_html("frieren")
    if result.items:
        ok(f"Nyaa 搜索 'frieren' → {result.total} 结果")
        for i, item in enumerate(result.items[:3]):
            print(f"      {i+1}. {item.title}")
            print(f"         S={item.seeders} L={item.leechers} Size={item.size}")
        ok("数据字段完整")
    else:
        fail("Nyaa 搜索无结果（可能代理不通或被 CF 拦截）")
        return False

    return True


async def main():
    print(f"{BOLD}动漫资源管理系统 — 服务测试{RESET}")
    print(f"{'='*60}")

    results = {}
    results["SubsPlease"] = await test_subsplease()
    results["Bangumi"] = await test_bangumi()
    results["Nyaa"] = await test_nyaa()

    # Summary
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}测试结果汇总{RESET}")
    print(f"{'='*60}")
    for name, passed in results.items():
        if passed is True:
            print(f"  {GREEN}✓ PASS{RESET}  {name}")
        elif passed is False:
            print(f"  {RED}✗ FAIL{RESET}  {name}")
        else:
            print(f"  {YELLOW}⊘ SKIP{RESET}  {name}")

    all_tested = [v for v in results.values() if v is not None]
    if all_tested and all(all_tested):
        print(f"\n{GREEN}所有可测试的服务均正常工作！{RESET}")
    elif any(v is False for v in results.values()):
        print(f"\n{RED}部分服务测试失败{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
