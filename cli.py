#!/usr/bin/env python3
"""
Ecommerce Scout — 淘宝 + 拼多多 选品分析工具

用法:
    python cli.py "露营灯"                       # 基本搜索
    python cli.py "手机壳" --pages 3             # 指定翻页数
    python cli.py "蓝牙耳机" --platform taobao    # 只看淘宝
    python cli.py "收纳盒" --cost 0.35           # 自定义成本比例
    python cli.py "台灯" -o report.xlsx          # 导出 Excel
    python cli.py "键盘" --no-headless            # 显示浏览器(调试用)
    python cli.py "男装" -m                       # 🆕 盯价模式（追踪价格变化）
    python cli.py "蓝牙耳机" -m -p 2 --csv       # 🆕 盯价 + 翻2页 + 导出CSV

环境要求:
    - Python 3.10+
    - pip install -r requirements.txt
    - playwright install chromium
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 确保能 import src
sys.path.insert(0, str(Path(__file__).parent))

from src.scrapers import TaobaoScraper, PinduoduoScraper
from src.analyzer import Normalizer, Comparator, Scorer
from src.output.console import print_report
from src.output.excel import export_report
from src.models import Platform, AnalysisReport


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="🛒 Ecommerce Scout — 淘宝+拼多多 选品分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python cli.py "露营灯"
  python cli.py "收纳盒" --pages 5 --cost 0.35 -o report.xlsx
  python cli.py "手机壳" --platform taobao --no-headless
        """,
    )
    parser.add_argument("keyword", help="搜索关键词（品类名）")
    parser.add_argument("--platform", "-p", choices=["taobao", "pdd", "all"],
                        default="all", help="目标平台 (默认: all)")
    parser.add_argument("--pages", "-n", type=int, default=None,
                        help="每个平台最大翻页数 (默认: 5)")
    parser.add_argument("--cost", "-c", type=float, default=None,
                        help="成本占售价比例，如 0.40 表示成本占售价 40%% (默认: 0.40)")
    parser.add_argument("--shipping", "-s", type=float, default=None,
                        help="单件运费估算/元 (默认: 5.0)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="导出 Excel 文件路径")
    parser.add_argument("--no-headless", action="store_true",
                        help="显示浏览器窗口 (调试用)")
    parser.add_argument("--no-cache", action="store_true",
                        help="禁用缓存，强制重新抓取")
    parser.add_argument("--top", "-t", type=int, default=15,
                        help="报告中显示的 Top N 商品数 (默认: 15)")

    # ── 盯价模式参数 ──
    parser.add_argument("--monitor", "-m", action="store_true",
                        help="盯价模式：追踪该品类价格变化，自动保存历史快照")
    parser.add_argument("--interval", "-i", type=int, default=0,
                        help="盯价模式下，两次提醒之间的最小间隔(小时) (默认: 每次均提醒)")
    parser.add_argument("--alert-up", type=float, default=0,
                        help="盯价模式：涨价超过此金额(¥)才提醒 (默认: 全部提醒)")
    parser.add_argument("--alert-down", type=float, default=0,
                        help="盯价模式：降价超过此金额(¥)才提醒 (默认: 全部提醒)")
    parser.add_argument("--csv", action="store_true",
                        help="盯价模式：导出 CSV 报告")
    parser.add_argument("--json", action="store_true",
                        help="盯价模式：导出 JSON 报告")

    args = parser.parse_args()

    # ── 盯价模式 ──────────────────────────────────────
    if args.monitor:
        from price_monitor import PriceMonitor, print_monitor_report

        print(f"\n  📊 盯价模式: {args.keyword}")
        print(f"  🔄 翻页: {args.pages or 1} 页 | 浏览器: {'显示' if args.no_headless else '无头'}")
        print()

        monitor = PriceMonitor(
            keyword=args.keyword,
            pages=args.pages or 1,
            alert_up=args.alert_up,
            alert_down=args.alert_down,
            headless=not args.no_headless,
        )
        report = await monitor.run()
        print_monitor_report(report)

        if report.error:
            print(f"  ⚠ 盯价失败: {report.error}")
            return

        # 导出
        if args.csv:
            monitor.export_csv(report)
        if args.json:
            monitor.export_json(report)

        # 提醒间隔检查
        if args.interval > 0 and report.previous_timestamp:
            elapsed_h = (datetime.now() - report.previous_timestamp).total_seconds() / 3600
            if elapsed_h < args.interval:
                print(f"  ⏰ 距上次盯价仅 {elapsed_h:.1f}h，未达到 {args.interval}h 提醒间隔")
        return

    # ── 选品分析模式 ────────────────────────────────────

    # 更新配置
    from src import config

    if args.no_headless:
        config.CRAWLER["headless"] = False
    if args.no_cache:
        config.CACHE["enabled"] = False
    if args.pages:
        config.CRAWLER["taobao_max_pages"] = args.pages
        config.CRAWLER["pdd_max_pages"] = args.pages

    print(f"\n  🚀 开始分析: [bold]{args.keyword}[/bold]")
    print(f"  📋 平台: {args.platform} | 每平台最多 {config.CRAWLER['taobao_max_pages']} 页")
    print(f"  💰 成本比例: {args.cost or config.SCORING['default_cost_ratio']:.0%} | 运费: ¥{args.shipping or config.SCORING['shipping_estimate']}")
    print()

    # ── 阶段 1: 数据采集 ──
    print("─" * 50)
    print("  📥 阶段 1/3: 数据采集")
    print("─" * 50)

    taobao_scraper = None
    pdd_scraper = None
    taobao_result = None
    pdd_result = None

    try:
        tasks = []
        if args.platform in ("taobao", "all"):
            taobao_scraper = TaobaoScraper()
            tasks.append(("淘宝", taobao_scraper.search(args.keyword, args.pages)))
        if args.platform in ("pdd", "all"):
            pdd_scraper = PinduoduoScraper()
            tasks.append(("拼多多", pdd_scraper.search(args.keyword, args.pages)))

        results = await asyncio.gather(*[t[1] for t in tasks])

        for (name, _), result in zip(tasks, results):
            if name == "淘宝":
                taobao_result = result
            else:
                pdd_result = result
            status = f"✓ {len(result.products)} 个商品" if not result.error else f"✗ {result.error}"
            print(f"  {name}: {status}")

    finally:
        # 清理浏览器资源
        for s in [taobao_scraper, pdd_scraper]:
            if s:
                await s.close()

    # ── 阶段 2: 数据分析 ──
    print()
    print("─" * 50)
    print("  🧠 阶段 2/3: 数据分析")
    print("─" * 50)

    # 合并清洗
    all_results = [r for r in [taobao_result, pdd_result] if r is not None]
    all_items = Normalizer.normalize(all_results)
    print(f"  ✓ 清洗后有效商品: {len(all_items)} 个")

    # 分平台
    taobao_items = [i for i in all_items if i.platform == Platform.TAOBAO]
    pdd_items = [i for i in all_items if i.platform == Platform.PDD]

    # 统计
    tb_stats = Normalizer.aggregate_stats(taobao_items)
    pd_stats = Normalizer.aggregate_stats(pdd_items)
    tb_avg = tb_stats.get("avg_price", 0)
    pd_avg = pd_stats.get("avg_price", 0)
    price_gap = round((tb_avg - pd_avg) / pd_avg * 100, 1) if pd_avg > 0 else 0

    print(f"  ✓ 淘宝: {len(taobao_items)} 个 | 均价 ¥{tb_avg:.2f}")
    print(f"  ✓ 拼多多: {len(pdd_items)} 个 | 均价 ¥{pd_avg:.2f}")
    print(f"  ✓ 两平台价差: {price_gap:+.1f}%")

    # 跨平台对比
    cross_matches = Comparator.find_cross_platform_matches(taobao_items, pdd_items)
    print(f"  ✓ 跨平台同款匹配: {len(cross_matches)} 对")

    # 竞争分析
    comp = Comparator.competition_analysis(all_items)
    print(f"  ✓ 竞争分析: {comp['level']} (卖家{comp.get('shop_count', 0)}家, Top3占比{comp.get('top3_share_pct', 0)}%)")

    # 打分
    scorer = Scorer(cost_ratio=args.cost, shipping=args.shipping)
    scored = scorer.score_all(all_items, taobao_items, pdd_items)
    print(f"  ✓ 打分完成: {len(scored)} 个商品参与排名")

    # ── 阶段 3: 报告输出 ──
    print()
    print("─" * 50)
    print("  📊 阶段 3/3: 生成报告")
    print("─" * 50)

    top_pick = scored[0] if scored else None

    # 市场总结
    market_summary = _generate_market_summary(
        args.keyword, len(taobao_items), len(pdd_items),
        tb_avg, pd_avg, price_gap, comp, cross_matches, top_pick,
    )

    report = AnalysisReport(
        keyword=args.keyword,
        products=scored,
        taobao_count=len(taobao_items),
        pdd_count=len(pdd_items),
        avg_price_taobao=tb_avg,
        avg_price_pdd=pd_avg,
        price_gap_pct=price_gap,
        competition_level=comp["level"],
        top_pick=top_pick,
        market_summary=market_summary,
    )

    # 终端输出
    print_report(report, top_n=args.top)

    # Excel 导出
    if args.output or True:  # 默认导出
        out_path = export_report(report, args.output)
        print(f"  📁 Excel 已导出: {out_path}")

    print(f"\n  ✅ 分析完成! 共分析 {len(scored)} 个商品\n")


def _generate_market_summary(
    keyword: str,
    tb_count: int,
    pd_count: int,
    tb_avg: float,
    pd_avg: float,
    price_gap: float,
    comp: dict,
    cross_matches: list,
    top_pick,
) -> str:
    """生成市场总结文字"""
    parts = []

    total = tb_count + pd_count
    if total == 0:
        return f"未能获取到「{keyword}」的有效数据，请检查网络或尝试其他关键词。"

    # 市场规模
    parts.append(f"「{keyword}」在两平台共有 {total} 个有效商品，"
                 f"其中淘宝 {tb_count} 个、拼多多 {pd_count} 个。")

    # 价格
    if tb_avg > 0 and pd_avg > 0:
        parts.append(f"淘宝均价 ¥{tb_avg:.2f}，拼多多均价 ¥{pd_avg:.2f}，"
                     f"价差 {price_gap:+.1f}%。")
        if price_gap > 10:
            parts.append("淘宝端存在溢价空间，可考虑从拼多多渠道拿货。")

    # 竞争
    parts.append(f"竞争等级为「{comp['level']}」，"
                 f"Top 3 头部卖家占 {comp.get('top3_share_pct', 0)}% 销量。")

    # 跨平台
    if cross_matches:
        parts.append(f"发现 {len(cross_matches)} 对跨平台同款，"
                     f"存在套利观察机会。")

    # 推荐
    if top_pick:
        parts.append(f"首选推荐「{top_pick.title[:30]}...」"
                     f"(¥{top_pick.price:.2f}，{top_pick.platform.value}，"
                     f"综合 {top_pick.score:.0f} 分)。")

    return "".join(parts)


if __name__ == "__main__":
    asyncio.run(main())
