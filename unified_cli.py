#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TAgent — AI 电商自动化全链路系统

Windows 终端: 如遇编码问题请设置 PYTHONIOENCODING=utf-8 或 PYTHONUTF8=1
"""

import os, sys
if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    try: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


# ═══════════════════════════════════════════════════════════════════════
# Banner
# ═══════════════════════════════════════════════════════════════════════

BANNER = r"""
  ╔══════════════════════════════════════════════════════╗
  ║   🤖 TAgent — AI Ecommerce Automation               ║
  ║   淘宝 + 拼多多 · 全链路 AI Agent 系统                 ║
  ║                                                      ║
  ║   选品 → 内容 → 客服 → 广告 → 数据 → 库存 → 评价      ║
  ╚══════════════════════════════════════════════════════╝
"""


# ═══════════════════════════════════════════════════════════════════════
# Demo — 全链路演示
# ═══════════════════════════════════════════════════════════════════════

def cmd_demo(args: argparse.Namespace) -> None:
    """全链路演示：从选品到评价跑完整流程"""
    console.print(BANNER, style="bold cyan")
    console.print(f"  🎬 开始全链路演示: [bold yellow]{args.keyword}[/bold yellow]")
    console.print()

    keyword = args.keyword

    # ── 阶段 1: 选品 ──
    console.print(Panel.fit("[bold]📊 阶段 1/7: 选品分析[/bold]", style="bold white on blue"))
    from src.scrapers import TaobaoScraper, PinduoduoScraper
    from src.analyzer import Normalizer, Comparator, Scorer
    from src.models import Platform
    import asyncio

    async def do_scout():
        console.print("  🔍 正在搜索淘宝和拼多多...")
        from src.config import CRAWLER
        CRAWLER["taobao_max_pages"] = 1
        CRAWLER["pdd_max_pages"] = 1

        try:
            tb = TaobaoScraper()
            pd = PinduoduoScraper()
            try:
                tb_result, pd_result = await asyncio.gather(
                    tb.search(keyword, 1),
                    pd.search(keyword, 1),
                )
            finally:
                await tb.close()
                await pd.close()

            all_items = Normalizer.normalize([tb_result, pd_result])
            scorer = Scorer()
            scored = scorer.score_all(all_items)

            console.print(f"  ✓ 淘宝: {len([i for i in all_items if i.platform == Platform.TAOBAO])} 个商品")
            console.print(f"  ✓ 拼多多: {len([i for i in all_items if i.platform == Platform.PDD])} 个商品")

            if scored:
                top = scored[0]
                console.print(f"  ⭐ 首选: {top.title[:50]}... ({top.platform.value}, ¥{top.price:.2f}, 得分 {top.score:.0f})")
                return top
            return None
        except Exception as e:
            console.print(f"  ⚠ 浏览器未就绪 (playwright install chromium)，使用模拟数据演示")
            console.print(f"  ✓ 淘宝: 220 个商品 (模拟)")
            console.print(f"  ✓ 拼多多: 180 个商品 (模拟)")
            return None

    top_pick = asyncio.run(do_scout())
    console.print()

    product_name = top_pick.title if top_pick else keyword
    product_price = top_pick.price if top_pick else 35.0

    # ── 阶段 2: 内容 ──
    console.print(Panel.fit("[bold]📝 阶段 2/7: Listing 内容生成[/bold]", style="bold white on green"))
    from src.agents.content import ContentAgent
    from src.agents.base import LLMClient

    content_llm = LLMClient(provider="auto")
    content_agent = ContentAgent(content_llm)
    result = content_agent.run(
        product=product_name,
        price=product_price,
        features="超亮LED,USB充电,防水,超长续航,便携挂钩",
        angles=["性价比", "品质"],
        languages=["en"],
    )

    for listing in result.listings[:2]:
        console.print(f"  📌 [{listing.angle}] {listing.title[:60]}...")
        if listing.bullets:
            console.print(f"     • {listing.bullets[0][:50]}...")
    console.print()

    # ── 阶段 3: 客服 ──
    console.print(Panel.fit("[bold]💬 阶段 3/7: 客服 FAQ 匹配[/bold]", style="bold white on magenta"))
    from src.agents.customer import CustomerAgent

    cs_agent = CustomerAgent()
    test_queries = [
        "什么时候发货？",
        "怎么退货？",
        "质量有问题能换吗",
    ]
    for q in test_queries:
        resp = cs_agent.run(q)
        icon = "✅" if resp.faq_match_score > 0.3 else "🤖"
        console.print(f"  {icon} Q: {q}")
        console.print(f"     A: {resp.answer[:80]}...")
        if resp.faq_matched_question:
            console.print(f"     [dim]匹配 FAQ: {resp.faq_matched_question}[/dim]")
    console.print()

    # ── 阶段 4: 广告 ──
    console.print(Panel.fit("[bold]📢 阶段 4/7: 广告优化[/bold]", style="bold white on yellow"))
    from src.agents.advertising import AdvertisingAgent

    ad_agent = AdvertisingAgent()
    ad_agent.setup_campaigns(mock_data=True)
    actions = ad_agent.optimize()
    report = ad_agent.get_status()

    console.print(f"  💰 总花费: ¥{report.total_spend:.2f} | 总收入: ¥{report.total_revenue:.2f}")
    console.print(f"  📊 整体 ACOS: {report.overall_acos:.1%} | ROAS: {report.overall_roas:.1f}")

    if actions:
        for a in actions[:3]:
            console.print(f"  ⚡ {a.action}: {a.campaign_name} — {a.reason}")
    console.print()

    # ── 阶段 5: 数据 ──
    console.print(Panel.fit("[bold]📈 阶段 5/7: 数据分析 & 预警[/bold]", style="bold white on red"))
    from src.agents.analytics import AnalyticsAgent

    data_agent = AnalyticsAgent()
    data_agent.load_data(mock=True, days=30)
    alerts = data_agent.check_alerts()
    forecast = data_agent.forecast("revenue", 7)

    if alerts:
        for a in alerts[:3]:
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.level, "")
            console.print(f"  {icon} {a.title}: {a.message}")
    else:
        console.print(f"  ✅ 无异常告警")
    console.print(f"  📈 趋势: {forecast.get('trend_label', '')} | 7天预测: ¥{forecast['next_days'][0]:.0f} → ¥{forecast['next_days'][-1]:.0f}")
    console.print()

    # ── 阶段 6: 库存 ──
    console.print(Panel.fit("[bold]📦 阶段 6/7: 库存健康检查[/bold]", style="bold white on cyan"))
    from src.agents.inventory import InventoryAgent

    inv_agent = InventoryAgent()
    inv_agent.load_inventory(mock=True)
    inv_report = inv_agent.analyze()

    console.print(f"  💰 库存总值: ¥{inv_report.total_stock_value:,.2f}")
    console.print(f"  🔴 断货: {sum(1 for a in inv_report.alerts if a.level == 'critical')} 个 | "
                 f"🟡 低库存: {inv_report.low_stock_count} 个 | 💤 滞销: {inv_report.dead_stock_count} 个")
    for a in inv_report.alerts[:3]:
        console.print(f"  {'🔴' if a.level == 'critical' else '🟡'} {a.title}: {a.suggested_action[:60]}")
    console.print()

    # ── 阶段 7: 评价 ──
    console.print(Panel.fit("[bold]⭐ 阶段 7/7: 评价分析[/bold]", style="bold white on green"))
    from src.agents.review import ReviewAgent

    rev_agent = ReviewAgent()
    rev_agent.load_reviews(mock=True)
    rev_report = rev_agent.analyze()

    console.print(f"  ⭐ 平均评分: {rev_report.avg_rating}/5 | "
                 f"好评 {rev_report.positive_count} | 中评 {rev_report.neutral_count} | 差评 {rev_report.negative_count}")
    for a in rev_report.alerts[:2]:
        console.print(f"  {'🚨' if a.level == 'critical' else '⚠'} {a.title}")
        console.print(f"     建议回复: {a.suggested_reply[:80]}...")

    console.print()
    console.print(Panel.fit(
        "[bold green]✅ 全链路演示完成！[/bold green]\n\n"
        "这只是 AI 电商自动化的一个快照。每个 Agent 都可以独立深入使用。\n"
        "运行 python unified_cli.py --help 查看所有命令。",
        style="green"
    ))
    console.print()


# ═══════════════════════════════════════════════════════════════════════
# 选品
# ═══════════════════════════════════════════════════════════════════════

def cmd_scout(args: argparse.Namespace) -> None:
    """选品分析"""
    console.print("[bold cyan]🔍 选品模式[/bold cyan]")
    # 委托给现有的 cli.py
    import subprocess
    cli_path = Path(__file__).parent / "cli.py"
    cmd_args = [sys.executable, str(cli_path), args.keyword]
    if args.platform != "all":
        cmd_args.extend(["-p", args.platform])
    if args.pages:
        cmd_args.extend(["-n", str(args.pages)])
    if args.cost:
        cmd_args.extend(["-c", str(args.cost)])
    if args.output:
        cmd_args.extend(["-o", args.output])
    subprocess.run(cmd_args)


# ═══════════════════════════════════════════════════════════════════════
# 内容
# ═══════════════════════════════════════════════════════════════════════

def cmd_content(args: argparse.Namespace) -> None:
    """内容生成"""
    console.print("[bold cyan]📝 内容生成模式[/bold cyan]")
    from src.agents.content import ContentAgent
    from src.agents.base import LLMClient
    from rich.markdown import Markdown

    llm = LLMClient(provider="auto")
    agent = ContentAgent(llm)

    angles = [a.strip() for a in args.angles.split(",")] if args.angles else None
    langs = [l.strip() for l in args.lang.split(",")] if args.lang else ["en"]

    result = agent.run(
        product=args.product,
        price=args.price or 0,
        features=args.features or "",
        angles=angles,
        languages=langs,
    )

    # 显示结果
    for listing in result.listings:
        console.print(Panel.fit(f"[bold]{listing.angle}[/bold] ({listing.language})", style="yellow"))
        console.print(f"[bold]标题:[/bold] {listing.title}")
        console.print(f"[bold]五点描述:[/bold]")
        for i, b in enumerate(listing.bullets, 1):
            console.print(f"  {i}. {b}")
        if listing.description:
            console.print(f"[bold]A+描述:[/bold] {listing.description[:200]}...")
        if listing.search_terms:
            console.print(f"[bold]搜索词:[/bold] {', '.join(listing.search_terms)}")

    # 翻译
    for lang, listings in result.translations.items():
        lang_name = ContentAgent.LANGUAGES.get(lang, lang)
        for listing in listings:
            console.print(Panel.fit(f"[bold]🌐 {lang_name}[/bold]", style="cyan"))
            console.print(f"[bold]标题:[/bold] {listing.title}")
            if listing.bullets:
                console.print(f"[bold]卖点:[/bold]")
                for b in listing.bullets:
                    console.print(f"  - {b}")

    if args.export:
        md = agent.export_markdown(result)
        Path(args.export).write_text(md, encoding="utf-8")
        console.print(f"\n📁 已导出: {args.export}")


# ═══════════════════════════════════════════════════════════════════════
# 客服
# ═══════════════════════════════════════════════════════════════════════

def cmd_customer(args: argparse.Namespace) -> None:
    """客服查询"""
    from src.agents.customer import CustomerAgent
    from src.agents.base import LLMClient

    llm = LLMClient(provider="auto") if args.llm else LLMClient(provider="mock")
    agent = CustomerAgent(llm)

    if args.load_faq:
        agent.import_faqs(args.load_faq)

    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    resp = agent.run(query)

    # 结果
    console.print(f"\n[bold cyan]💬 客服分析[/bold cyan]")
    console.print(f"  意图: [yellow]{resp.intent}[/yellow]")
    console.print(f"  情感: [{'red' if resp.sentiment in ('angry','negative') else 'green'}]{resp.sentiment}[/]")

    if resp.faq_match_score > 0:
        console.print(f"  FAQ匹配: {resp.faq_matched_question} (相似度 {resp.faq_match_score:.2f})")

    console.print(f"\n[bold green]回复:[/bold green]")
    console.print(f"  {resp.answer}")

    if resp.needs_human:
        console.print(f"\n[bold red]⚠ 建议转人工: {resp.escalation_reason}[/bold red]")
        if resp.suggested_actions:
            for a in resp.suggested_actions:
                console.print(f"  → {a}")

    if args.verbose:
        console.print(f"\n[dim]详细数据: {resp}[/dim]")


# ═══════════════════════════════════════════════════════════════════════
# 广告
# ═══════════════════════════════════════════════════════════════════════

def cmd_ad(args: argparse.Namespace) -> None:
    """广告管理"""
    from src.agents.advertising import AdvertisingAgent
    from rich.markdown import Markdown

    agent = AdvertisingAgent()
    agent.setup_campaigns(mock_data=True)

    if args.add_campaign:
        parts = args.add_campaign
        name = parts[0] if len(parts) > 0 else "新品"
        price = float(parts[1]) if len(parts) > 1 else 50
        keywords = parts[2].split(",") if len(parts) > 2 else ["新品"]
        camp = agent.create_test_campaign(name, price, keywords)
        console.print(f"✅ 已创建测款广告: {camp.name}")

    if args.status:
        report = agent.get_status()
        console.print(f"\n[bold cyan]📢 广告状态 — {report.date}[/bold cyan]")
        console.print(f"  总花费: ¥{report.total_spend:.2f} | 总收入: ¥{report.total_revenue:.2f}")
        console.print(f"  总订单: {report.total_orders} | ACOS: {report.overall_acos:.1%} | ROAS: {report.overall_roas:.1f}")

        table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        table.add_column("广告组")
        table.add_column("预算", justify="right")
        table.add_column("消耗", justify="right")
        table.add_column("订单", justify="right")
        table.add_column("ACOS", justify="right")
        table.add_column("ROAS", justify="right")
        table.add_column("状态")

        for c in report.campaigns:
            icon = "🟢" if c.status == "active" else "🔴" if c.status == "paused" else "🟡"
            table.add_row(
                c.name, f"¥{c.daily_budget:.0f}", f"¥{c.spend_today:.2f}",
                str(c.orders), f"{c.acos:.1%}", f"{c.roas:.1f}",
                f"{icon} {c.status}",
            )
        console.print(table)

    if args.optimize:
        actions = agent.optimize()
        console.print(f"\n[bold yellow]⚡ 优化操作 ({len(actions)} 个)[/bold yellow]")
        for a in actions:
            console.print(f"  → {a.campaign_name}: {a.action} — {a.reason}")

    if args.report:
        md = agent.daily_report()
        console.print(Markdown(md))


# ═══════════════════════════════════════════════════════════════════════
# 数据
# ═══════════════════════════════════════════════════════════════════════

def cmd_report(args: argparse.Namespace) -> None:
    """数据报表"""
    from src.agents.analytics import AnalyticsAgent
    from rich.markdown import Markdown

    agent = AnalyticsAgent()
    agent.load_data(mock=True, days=30)

    if args.type == "weekly":
        report = agent.weekly_report()
        md = agent.export_weekly_report_md()
        console.print(Markdown(md))

    elif args.type == "forecast":
        forecast = agent.forecast(args.metric or "revenue", args.days or 7)
        console.print(f"\n[bold cyan]📈 趋势预测 — {forecast['metric']}[/bold cyan]")
        console.print(f"  趋势: {forecast.get('trend_label', '')}")
        console.print(f"  未来 {len(forecast['next_days'])} 天预测:")
        for i, v in enumerate(forecast['next_days'], 1):
            bar = "█" * int(v / max(forecast['next_days']) * 20) if max(forecast['next_days']) > 0 else ""
            console.print(f"  Day {i}: ¥{v:,.2f} {bar}")


def cmd_alert(args: argparse.Namespace) -> None:
    """异常预警"""
    from src.agents.analytics import AnalyticsAgent

    agent = AnalyticsAgent()
    agent.load_data(mock=True, days=30)
    alerts = agent.check_alerts()

    if alerts:
        console.print(f"\n[bold red]🚨 发现 {len(alerts)} 个异常[/bold red]")
        for a in alerts:
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.level, "")
            console.print(f"\n  {icon} [{a.level}] {a.title}")
            console.print(f"     {a.message}")
            console.print(f"     当前值: {a.current_value} | 预期: {a.expected_value} | 偏差: {a.deviation_pct:+.0f}%")
    else:
        console.print("[bold green]✅ 未发现异常[/bold green]")


# ═══════════════════════════════════════════════════════════════════════
# 库存
# ═══════════════════════════════════════════════════════════════════════

def cmd_inventory(args: argparse.Namespace) -> None:
    """库存检查"""
    from src.agents.inventory import InventoryAgent

    agent = InventoryAgent()
    agent.load_inventory(mock=True)
    report = agent.analyze()

    console.print(f"\n[bold cyan]📦 库存健康报告[/bold cyan]")
    console.print(f"  库存总值: ¥{report.total_stock_value:,.2f}")
    console.print(f"  滞销库存: ¥{report.dead_stock_value:,.2f}")
    console.print(f"  断货: {sum(1 for a in report.alerts if a.level == 'critical')} 个")
    console.print(f"  低库存: {report.low_stock_count} 个")
    console.print(f"  滞销: {report.dead_stock_count} 个")

    if report.alerts:
        console.print(f"\n[bold yellow]告警列表:[/bold yellow]")
    for a in report.alerts:
        icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.level, "")
        console.print(f"  {icon} {a.title}")
        console.print(f"     {a.message}")
        console.print(f"     → {a.suggested_action}")

    # SKU 表格
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("SKU")
    table.add_column("商品")
    table.add_column("库存", justify="right")
    table.add_column("日均销量", justify="right")
    table.add_column("安全库存", justify="right")
    table.add_column("周转天数", justify="right")
    table.add_column("状态")

    for s in report.skus:
        safety = agent.calc_safety_stock(s)
        status_icon = {"normal": "🟢", "low": "🟡", "critical": "🔴", "dead": "💤"}.get(s.status, "")
        table.add_row(
            s.sku_id, s.product_name,
            str(s.current_stock), f"{s.daily_avg_sales:.1f}",
            str(safety), f"{s.stock_turnover_days:.0f}",
            f"{status_icon} {s.status}",
        )
    console.print(table)


# ═══════════════════════════════════════════════════════════════════════
# 履约
# ═══════════════════════════════════════════════════════════════════════

def cmd_orders(args: argparse.Namespace) -> None:
    """订单履约检查"""
    from src.agents.fulfillment import FulfillmentAgent

    agent = FulfillmentAgent()
    agent.load_orders(mock=True)
    report = agent.check()

    console.print(f"\n[bold cyan]📋 订单履约报告[/bold cyan]")
    console.print(f"  总订单: {report.total_orders}")
    console.print(f"  待发货: {report.pending_ship} | 运输中: {report.in_transit} | 已签收: {report.delivered}")
    console.print(f"  延迟: {report.delayed} | 标记异常: {report.flagged}")

    if report.alerts:
        console.print(f"\n[bold yellow]异常告警:[/bold yellow]")
    for a in report.alerts:
        icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.level, "")
        console.print(f"  {icon} {a.title}")
        console.print(f"     订单: {a.order_id} | {a.message}")
        console.print(f"     → {a.suggested_action}")


# ═══════════════════════════════════════════════════════════════════════
# 评价
# ═══════════════════════════════════════════════════════════════════════

def cmd_reviews(args: argparse.Namespace) -> None:
    """评价分析"""
    from src.agents.review import ReviewAgent

    agent = ReviewAgent()
    agent.load_reviews(mock=True)
    report = agent.analyze()

    console.print(f"\n[bold cyan]⭐ 评价报告[/bold cyan]")
    console.print(f"  平均评分: {report.avg_rating}/5")
    console.print(f"  好评: {report.positive_count} | 中评: {report.neutral_count} | 差评: {report.negative_count}")
    console.print(f"  趋势: {report.negative_trend}")
    console.print(f"  建议: {report.recommendations}")

    if report.alerts:
        console.print(f"\n[bold red]差评告警:[/bold red]")
    for a in report.alerts:
        icon = {"critical": "🔴", "warning": "🟡"}.get(a.level, "")
        console.print(f"  {icon} {a.title}")
        console.print(f"     {a.message}")
        console.print(f"     [green]建议回复:[/green] {a.suggested_reply[:100]}...")

    if args.reply:
        console.print(f"\n[bold yellow]自动生成差评回复...[/bold yellow]")
        replies = agent.reply_to_all_negative()
        for r in replies:
            console.print(f"  ✅ {r['review_id']}: {r['reply'][:80]}...")


# ═══════════════════════════════════════════════════════════════════════
# CLI 主入口
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="🤖 TAgent — AI 电商全链路自动化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python unified_cli.py demo --keyword "露营灯"
  python unified_cli.py scout "手机壳"
  python unified_cli.py content --product "露营灯" --price 32 --features "防水,USB充电"
  python unified_cli.py customer "这个灯防水吗"
  python unified_cli.py ad --status
  python unified_cli.py report --type weekly
  python unified_cli.py inventory
  python unified_cli.py orders
  python unified_cli.py reviews
        """,
    )

    sub = parser.add_subparsers(dest="command", help="Agent 选择")

    # ── demo ──
    p_demo = sub.add_parser("demo", help="全链路演示")
    p_demo.add_argument("--keyword", "-k", default="露营灯", help="分析关键词")

    # ── scout ──
    p_scout = sub.add_parser("scout", help="选品分析")
    p_scout.add_argument("keyword", help="搜索关键词")
    p_scout.add_argument("--platform", "-p", choices=["taobao", "pdd", "all"], default="all")
    p_scout.add_argument("--pages", "-n", type=int, default=None)
    p_scout.add_argument("--cost", "-c", type=float, default=None)
    p_scout.add_argument("--output", "-o", type=str, default=None)

    # ── content ──
    p_content = sub.add_parser("content", help="Listing 内容生成")
    p_content.add_argument("--product", required=True, help="商品名称")
    p_content.add_argument("--price", type=float, help="售价")
    p_content.add_argument("--features", help="商品特性，逗号分隔")
    p_content.add_argument("--angles", default="性价比,品质,场景", help="卖点角度，逗号分隔")
    p_content.add_argument("--lang", default="en", help="目标语言，逗号分隔")
    p_content.add_argument("--export", "-e", help="导出 Markdown 路径")

    # ── customer ──
    p_cs = sub.add_parser("customer", help="智能客服")
    p_cs.add_argument("query", nargs="+", help="买家消息")
    p_cs.add_argument("--llm", action="store_true", help="启用 LLM 增强回复")
    p_cs.add_argument("--load-faq", help="加载 FAQ JSON 文件")
    p_cs.add_argument("--verbose", "-v", action="store_true")

    # ── ad ──
    p_ad = sub.add_parser("ad", help="广告管理")
    p_ad.add_argument("--status", action="store_true", default=True, help="查看状态")
    p_ad.add_argument("--optimize", "-O", action="store_true", help="执行优化")
    p_ad.add_argument("--report", "-r", action="store_true", help="查看日报")
    p_ad.add_argument("--add-campaign", nargs="*", help="新增测款: 名称 价格 '关键词1,关键词2'")

    # ── report ──
    p_rep = sub.add_parser("report", help="数据报表")
    p_rep.add_argument("--type", "-t", choices=["weekly", "forecast"], default="weekly")
    p_rep.add_argument("--metric", "-m", default="revenue")
    p_rep.add_argument("--days", "-d", type=int, default=7)

    # ── alert ──
    sub.add_parser("alert", help="异常预警检测")

    # ── inventory ──
    sub.add_parser("inventory", help="库存健康检查")

    # ── orders ──
    sub.add_parser("orders", help="订单履约检查")

    # ── reviews ──
    p_rev = sub.add_parser("reviews", help="评价管理")
    p_rev.add_argument("--reply", action="store_true", help="自动回复差评")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 路由
    cmds = {
        "demo": cmd_demo,
        "scout": cmd_scout,
        "content": cmd_content,
        "customer": cmd_customer,
        "ad": cmd_ad,
        "report": cmd_report,
        "alert": cmd_alert,
        "inventory": cmd_inventory,
        "orders": cmd_orders,
        "reviews": cmd_reviews,
    }

    handler = cmds.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
