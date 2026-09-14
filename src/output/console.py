"""终端彩色报告输出"""

from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.layout import Layout

from ..models import Platform, AnalysisReport, ScoredProduct


console = Console()


def print_banner(keyword: str) -> None:
    """打印工具 Banner"""
    banner = f"""
  ╔══════════════════════════════════════════╗
  ║   🛒  Ecommerce Scout — 选品分析工具      ║
  ║   淘宝 + 拼多多 数据驱动的选品决策          ║
  ╚══════════════════════════════════════════╝
  """
    console.print(banner, style="bold cyan")
    console.print(f"  🔍 搜索关键词: [bold yellow]{keyword}[/bold yellow]")
    console.print(f"  🕐 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    console.print()


def print_market_overview(report: AnalysisReport) -> None:
    """打印市场概览"""
    console.print(Panel.fit("[bold]📊 市场概览[/bold]", style="bold white on blue"))

    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="bold cyan")
    grid.add_column()

    taobao_avg = f"¥{report.avg_price_taobao:.2f}" if report.avg_price_taobao > 0 else "N/A"
    pdd_avg = f"¥{report.avg_price_pdd:.2f}" if report.avg_price_pdd > 0 else "N/A"

    # 竞争等级颜色
    comp_color = {
        "低竞争": "green",
        "中等竞争": "yellow",
        "头部垄断": "red",
        "高度竞争": "red",
    }.get(report.competition_level, "white")

    grid.add_row("淘宝商品数", str(report.taobao_count))
    grid.add_row("拼多多商品数", str(report.pdd_count))
    grid.add_row("淘宝均价", taobao_avg)
    grid.add_row("拼多多均价", pdd_avg)
    grid.add_row("两平台价差", f"{report.price_gap_pct:+.1f}%")
    grid.add_row("竞争等级", f"[{comp_color}]{report.competition_level}[/{comp_color}]")

    console.print(grid)
    console.print()

    if report.market_summary:
        console.print(Panel(report.market_summary, title="市场总结", style="yellow"))
        console.print()


def print_top_products(products: list[ScoredProduct], top_n: int = 15) -> None:
    """打印 Top N 商品表格"""
    if not products:
        console.print("[yellow]⚠ 没有足够的数据生成排名[/yellow]")
        return

    console.print(Panel.fit(f"[bold]🏆 选品推荐 Top {min(top_n, len(products))}[/bold]", style="bold white on green"))

    table = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold white",
        expand=False,
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("得分", width=6, justify="right")
    table.add_column("商品标题", width=40, overflow="fold")
    table.add_column("价格", width=8, justify="right")
    table.add_column("月销量", width=10, justify="right")
    table.add_column("平台", width=8)
    table.add_column("毛利率", width=7, justify="right")
    table.add_column("洞察", width=30, overflow="fold")

    for i, p in enumerate(products[:top_n], 1):
        # 得分颜色
        if p.score >= 70:
            score_style = "bold green"
        elif p.score >= 50:
            score_style = "bold yellow"
        else:
            score_style = "dim white"

        platform_icon = "🍑" if p.platform == Platform.TAOBAO else "📱"
        platform_name = f"{platform_icon} {p.platform.value}"

        # 毛利率颜色
        margin_style = "green" if p.estimated_margin_pct > 30 else "yellow" if p.estimated_margin_pct > 15 else "red"

        table.add_row(
            str(i),
            f"[{score_style}]{p.score:.0f}[/{score_style}]",
            p.title[:60] + ("..." if len(p.title) > 60 else ""),
            f"¥{p.price:.2f}",
            f"{p.sales_count:,}" if p.sales_count > 0 else p.sales_text,
            platform_name,
            f"[{margin_style}]{p.estimated_margin_pct:.0f}%[/{margin_style}]",
            p.insight[:60] + ("..." if len(p.insight) > 60 else ""),
        )

    console.print(table)
    console.print()


def print_top_pick(product: ScoredProduct) -> None:
    """打印首选推荐"""
    if not product:
        return

    console.print(Panel.fit("[bold]⭐ 今日首选[/bold]", style="bold white on yellow"))

    lines = [
        f"商品: {product.title}",
        f"平台: {product.platform.value} | 店铺: {product.shop_name}",
        f"售价: ¥{product.price:.2f} | 月销: {product.sales_count:,} | 毛利率: {product.estimated_margin_pct:.0f}%",
        f"综合得分: {product.score:.0f}/100",
        f"分析: {product.insight}",
    ]
    for line in lines:
        console.print(f"  {line}")
    console.print()


def print_score_breakdown(product: ScoredProduct) -> None:
    """打印单个商品的打分明细"""
    console.print(Panel.fit("[bold]📈 打分明细[/bold]", style="bold white on magenta"))

    breakdown = Table(box=box.SIMPLE)
    breakdown.add_column("维度", style="bold")
    breakdown.add_column("得分", justify="right")
    breakdown.add_column("权重")
    breakdown.add_column("加权分", justify="right")
    breakdown.add_column("进度条")

    dims = [
        ("需求热度", product.demand_score, "25%"),
        ("竞争程度", product.competition_score, "25%"),
        ("利润空间", product.margin_score, "30%"),
        ("平台套利", product.arbitrage_score, "10%"),
        ("趋势判断", product.trend_score, "10%"),
    ]

    for name, score, weight in dims:
        bar_len = int(score / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        color = "green" if score >= 60 else "yellow" if score >= 30 else "red"
        try:
            weighted = score * float(weight.replace("%", "")) / 100
        except ValueError:
            weighted = 0
        breakdown.add_row(name, f"{score:.0f}", weight, f"{weighted:.1f}", f"[{color}]{bar}[/{color}]")

    console.print(breakdown)
    console.print()


def print_report(report: AnalysisReport, top_n: int = 15, show_breakdown: bool = True) -> None:
    """输出完整报告"""
    print_banner(report.keyword)
    print_market_overview(report)

    if report.top_pick and show_breakdown:
        print_top_pick(report.top_pick)
        print_score_breakdown(report.top_pick)

    print_top_products(report.products, top_n)
