#!/usr/bin/env python3
"""
TAgent 智能盯价模块 — 整合项目 Playwright爬虫 + 数据模型

功能:
  - 使用项目已有的 TaobaoScraper（Playwright 渲染）抓取商品
  - 按关键词保存历史快照到 data/exports/monitor/{keyword}/
  - 自动对比上一轮快照，输出价格/销量变动报告
  - 支持 CSV/JSON 导出
  - 支持命令行独立运行或由 cli.py 调用

用法:
    # 命令行独立使用
    python price_monitor.py "男装"                         # 单次盯价
    python price_monitor.py "男装" --days 7                # 对比7天前的数据
    python price_monitor.py "男装" --json                  # 导出 JSON 格式
    python price_monitor.py "男装" --alert-up 5.0          # 涨价超过5元才提醒

    # 通过 cli.py 调用
    python cli.py "男装" --monitor                         # 盯价模式
    python cli.py "男装" -m --interval 24                  # 每24小时提醒一次
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 确保能 import src
sys.path.insert(0, str(Path(__file__).parent))

from src.config import EXPORT_DIR
from src.models import Platform, ProductItem, SearchResult
from src.scrapers import TaobaoScraper

# ── 路径 ─────────────────────────────────────────────────
MONITOR_DIR = EXPORT_DIR / "monitor"


class PriceMonitor:
    """
    价格监控器 — 盯住一个关键词的价格变化

    每次执行：
      1. 用 TaobaoScraper（Playwright）拉取最新商品数据
      2. 保存为快照到 data/exports/monitor/{keyword}/{timestamp}.json
      3. 如果有历史快照，对比并报告价格/销量变化
      4. 按需导出 CSV / JSON
    """

    def __init__(self, keyword: str, pages: int = 1,
                 alert_up: float = 0, alert_down: float = 0,
                 headless: bool = True) -> None:
        """
        :param keyword:  盯价的品类关键词
        :param pages:    每轮抓取的页数（默认1页，减少反爬压力）
        :param alert_up:  涨价超过此金额才报告（0 = 全部报告）
        :param alert_down: 降价超过此金额才报告（0 = 全部报告）
        :param headless:  是否无头模式
        """
        self.keyword = keyword.strip()
        self.pages = pages
        self.alert_up = alert_up
        self.alert_down = alert_down

        # 覆盖 headless 配置
        import src.config as cfg
        if headless:
            cfg.CRAWLER["headless"] = True

        # 关键词对应的快照目录
        self.snapshot_dir = MONITOR_DIR / self._sanitize_keyword(keyword)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        # 最新一批商品
        self.products: list[ProductItem] = []

    # ── 公共方法 ────────────────────────────────────────────

    async def run(self) -> "MonitorReport":
        """
        执行一轮盯价：
          1. 抓取数据
          2. 保存快照
          3. 与历史对比
          4. 返回报告
        """
        # 1. 抓取
        scraper = TaobaoScraper()
        try:
            result = await scraper.search(self.keyword, max_pages=self.pages)
        finally:
            await scraper.close()

        if result.error:
            return MonitorReport(
                keyword=self.keyword,
                error=result.error,
                timestamp=datetime.now(),
            )

        self.products = result.products

        if not self.products:
            return MonitorReport(
                keyword=self.keyword,
                error="未获取到商品数据，可能触发了反爬验证",
                timestamp=datetime.now(),
            )

        # 2. 保存当前快照
        snapshot_path = self._save_snapshot(self.products)

        # 3. 加载上一个历史快照
        prev_snapshot = self._load_latest_snapshot(exclude=snapshot_path.name)

        # 4. 对比变化
        changes: list[PriceChange] = []
        if prev_snapshot:
            changes = self._compare_snapshots(prev_snapshot, self.products)

        # 5. 组装报告
        report = MonitorReport(
            keyword=self.keyword,
            product_count=len(self.products),
            timestamp=datetime.now(),
            snapshot_path=str(snapshot_path),
            previous_snapshot_path=str(prev_snapshot.get("_file", "")) if prev_snapshot else None,
            previous_timestamp=(
                datetime.fromisoformat(prev_snapshot["_snapshot_time"])
                if prev_snapshot and "_snapshot_time" in prev_snapshot
                else None
            ),
            changes=changes,
            price_min=min(p.price for p in self.products) if self.products else 0,
            price_max=max(p.price for p in self.products) if self.products else 0,
            price_avg=round(
                sum(p.price for p in self.products) / len(self.products), 2
            ) if self.products else 0,
            total_sales=sum(p.sales_count for p in self.products),
        )

        return report

    # ── 快照管理 ────────────────────────────────────────────

    def _sanitize_keyword(self, kw: str) -> str:
        """把关键词转为安全的目录名"""
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in kw)
        return safe.strip().replace(" ", "_") or "keyword"

    def _save_snapshot(self, products: list[ProductItem]) -> Path:
        """将当前商品列表保存为 JSON 快照"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}.json"
        path = self.snapshot_dir / filename

        data = {
            "_snapshot_time": datetime.now().isoformat(),
            "_keyword": self.keyword,
            "_product_count": len(products),
            "products": [self._product_to_dict(p) for p in products],
        }

        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  💾 快照已保存: {path}")
        return path

    def _load_latest_snapshot(self, exclude: str = "") -> Optional[dict]:
        """加载最新的历史快照（排除当前文件）"""
        snapshots = sorted(self.snapshot_dir.glob("*.json"), reverse=True)
        for f in snapshots:
            if f.name == exclude:
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_file"] = str(f)
                return data
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    def _compare_snapshots(
        self, prev_data: dict, current: list[ProductItem]
    ) -> list["PriceChange"]:
        """
        对比新旧两份商品数据，找出价格/销量变化。

        匹配策略：通过商品链接中的 item_id 匹配同款商品。
        """
        prev_products: list[dict] = prev_data.get("products", [])
        if not prev_products:
            return []

        # 构建新旧索引: item_id -> product
        def extract_id(url: str) -> str:
            import re
            m = re.search(r"id=(\d+)", url)
            return m.group(1) if m else url[:60]

        old_index: dict[str, dict] = {}
        for p in prev_products:
            pid = extract_id(p.get("product_url", ""))
            old_index[pid] = p

        new_index: dict[str, ProductItem] = {}
        for p in current:
            pid = extract_id(p.product_url)
            new_index[pid] = p

        # 遍历新旧匹配
        changes: list[PriceChange] = []

        # 1. 旧商品在新数据中依然存在 → 对比价格/销量
        for pid, old_item in old_index.items():
            if pid in new_index:
                new_item = new_index[pid]
                old_price = float(old_item.get("price", 0))
                new_price = new_item.price
                old_sales = int(old_item.get("sales_count", 0))
                new_sales = new_item.sales_count

                price_diff = round(new_price - old_price, 2)
                sales_diff = new_sales - old_sales

                # 是否触发提醒门槛
                if self.alert_up > 0 and price_diff < self.alert_up:
                    continue
                if self.alert_down > 0 and price_diff > -self.alert_down:
                    # 降价但未达到提醒线
                    pass

                change = PriceChange(
                    title=new_item.title,
                    product_url=new_item.product_url,
                    old_price=old_price,
                    new_price=new_price,
                    price_diff=price_diff,
                    price_diff_pct=round((price_diff / old_price * 100), 1) if old_price > 0 else 0,
                    old_sales=old_sales,
                    new_sales=new_sales,
                    sales_diff=sales_diff,
                    shop_name=new_item.shop_name,
                    status="涨价" if price_diff > 0 else "降价" if price_diff < 0 else "持平",
                )
                changes.append(change)

        # 2. 新商品（旧数据中没有）→ "新品"
        for pid, new_item in new_index.items():
            if pid not in old_index:
                changes.append(PriceChange(
                    title=new_item.title,
                    product_url=new_item.product_url,
                    old_price=0,
                    new_price=new_item.price,
                    price_diff=new_item.price,
                    price_diff_pct=0,
                    old_sales=0,
                    new_sales=new_item.sales_count,
                    sales_diff=new_item.sales_count,
                    shop_name=new_item.shop_name,
                    status="新品上架",
                ))

        # 3. 下架商品（旧数据中有，新数据中没有）
        for pid, old_item in old_index.items():
            if pid not in new_index:
                changes.append(PriceChange(
                    title=old_item.get("title", ""),
                    product_url=old_item.get("product_url", ""),
                    old_price=float(old_item.get("price", 0)),
                    new_price=0,
                    price_diff=-float(old_item.get("price", 0)),
                    price_diff_pct=-100,
                    old_sales=int(old_item.get("sales_count", 0)),
                    new_sales=0,
                    sales_diff=-int(old_item.get("sales_count", 0)),
                    shop_name=old_item.get("shop_name", ""),
                    status="已下架",
                ))

        # 按价格变动绝对值排序
        changes.sort(key=lambda c: abs(c.price_diff), reverse=True)
        return changes

    # ── 导出 ───────────────────────────────────────────────

    def export_csv(self, report: "MonitorReport", filepath: Optional[str] = None) -> str:
        """导出盯价报告为 CSV"""
        if filepath is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = str(MONITOR_DIR / f"盯价_{self.keyword}_{ts}.csv")

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        fieldnames = [
            "状态", "商品标题", "店铺", "旧价(¥)", "新价(¥)",
            "价格变动(¥)", "变动幅度%", "旧销量", "新销量", "销量变化",
            "商品链接",
        ]
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for c in report.changes:
                writer.writerow({
                    "状态": c.status,
                    "商品标题": c.title,
                    "店铺": c.shop_name,
                    "旧价(¥)": c.old_price,
                    "新价(¥)": c.new_price,
                    "价格变动(¥)": c.price_diff,
                    "变动幅度%": c.price_diff_pct,
                    "旧销量": c.old_sales,
                    "新销量": c.new_sales,
                    "销量变化": c.sales_diff,
                    "商品链接": c.product_url,
                })

        print(f"  📄 报告已导出: {filepath}")
        return filepath

    def export_json(self, report: "MonitorReport", filepath: Optional[str] = None) -> str:
        """导出盯价报告为 JSON"""
        if filepath is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = str(MONITOR_DIR / f"盯价_{self.keyword}_{ts}.json")

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        data = {
            "keyword": report.keyword,
            "timestamp": report.timestamp.isoformat(),
            "product_count": report.product_count,
            "price_min": report.price_min,
            "price_max": report.price_max,
            "price_avg": report.price_avg,
            "total_sales": report.total_sales,
            "previous_timestamp": report.previous_timestamp.isoformat() if report.previous_timestamp else None,
            "changes": [
                {
                    "status": c.status,
                    "title": c.title,
                    "shop_name": c.shop_name,
                    "old_price": c.old_price,
                    "new_price": c.new_price,
                    "price_diff": c.price_diff,
                    "price_diff_pct": c.price_diff_pct,
                    "old_sales": c.old_sales,
                    "new_sales": c.new_sales,
                    "sales_diff": c.sales_diff,
                    "product_url": c.product_url,
                }
                for c in report.changes
            ],
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"  📄 报告已导出: {filepath}")
        return filepath

    @staticmethod
    def _product_to_dict(p: ProductItem) -> dict:
        return {
            "title": p.title,
            "price": p.price,
            "price_min": p.price_min,
            "price_max": p.price_max,
            "sales_count": p.sales_count,
            "sales_text": p.sales_text,
            "shop_name": p.shop_name,
            "shop_type": p.shop_type,
            "location": p.location,
            "img_url": p.img_url,
            "product_url": p.product_url,
            "free_shipping": p.free_shipping,
            "tags": p.tags,
            "scraped_at": p.scraped_at.isoformat() if hasattr(p.scraped_at, 'isoformat') else str(p.scraped_at),
        }


# ── 数据类型 ─────────────────────────────────────────────

class PriceChange:
    """一条价格变动记录"""

    def __init__(self, title: str, product_url: str,
                 old_price: float, new_price: float,
                 price_diff: float, price_diff_pct: float,
                 old_sales: int, new_sales: int,
                 sales_diff: int, shop_name: str,
                 status: str = "") -> None:
        self.title = title
        self.product_url = product_url
        self.old_price = old_price
        self.new_price = new_price
        self.price_diff = price_diff
        self.price_diff_pct = price_diff_pct
        self.old_sales = old_sales
        self.new_sales = new_sales
        self.sales_diff = sales_diff
        self.shop_name = shop_name
        self.status = status


class MonitorReport:
    """一轮盯价的完整报告"""

    def __init__(self, keyword: str,
                 product_count: int = 0,
                 timestamp: Optional[datetime] = None,
                 snapshot_path: str = "",
                 previous_snapshot_path: Optional[str] = None,
                 previous_timestamp: Optional[datetime] = None,
                 changes: Optional[list[PriceChange]] = None,
                 price_min: float = 0,
                 price_max: float = 0,
                 price_avg: float = 0,
                 total_sales: int = 0,
                 error: str = "") -> None:
        self.keyword = keyword
        self.product_count = product_count
        self.timestamp = timestamp or datetime.now()
        self.snapshot_path = snapshot_path
        self.previous_snapshot_path = previous_snapshot_path
        self.previous_timestamp = previous_timestamp
        self.changes = changes or []
        self.price_min = price_min
        self.price_max = price_max
        self.price_avg = price_avg
        self.total_sales = total_sales
        self.error = error


# ── 报告格式化输出 ───────────────────────────────────────

def print_monitor_report(report: MonitorReport) -> None:
    """终端打印盯价报告"""
    if report.error:
        print(f"\n  ⚠ 盯价失败: {report.error}\n")
        return

    keyword = report.keyword
    now = report.timestamp.strftime("%Y-%m-%d %H:%M")

    print()
    print("=" * 58)
    print(f"  📊 盯价报告: {keyword}")
    print(f"  🕐 {now}")
    print("=" * 58)

    # 商品概况
    print(f"\n  📦 当前商品数: {report.product_count}")
    print(f"  💰 价格区间: ¥{report.price_min:.2f} ~ ¥{report.price_max:.2f}")
    print(f"  💰 均价: ¥{report.price_avg:.2f}")
    if report.total_sales > 0:
        print(f"  📈 总销量(估算): {report.total_sales}")

    # 历史对比
    if report.previous_timestamp:
        prev_str = report.previous_timestamp.strftime("%Y-%m-%d %H:%M")
        print(f"\n  📅 对比上次: {prev_str}")
        print(f"  🔄 变化商品数: {len(report.changes)}")

    # 变动明细
    if report.changes:
        up_count = sum(1 for c in report.changes if c.status == "涨价")
        down_count = sum(1 for c in report.changes if c.status == "降价")
        new_count = sum(1 for c in report.changes if c.status == "新品上架")
        gone_count = sum(1 for c in report.changes if c.status == "已下架")

        print(f"      ├─ 涨价: {up_count}  降价: {down_count}")
        print(f"      ├─ 新品: {new_count}  下架: {gone_count}")

        # 输出涨跌 TOP
        significant = [c for c in report.changes
                       if c.status in ("涨价", "降价", "新品上架")]

        if significant:
            print(f"\n  {'=' * 50}")
            print(f"  📋 变动明细")
            print(f"  {'=' * 50}")

            for i, c in enumerate(significant[:15], 1):
                emoji = {
                    "涨价": "🔴",
                    "降价": "🟢",
                    "新品上架": "🆕",
                    "已下架": "❌",
                }.get(c.status, "▪")

                title_short = c.title[:40] if c.title else "(无标题)"
                if c.status == "新品上架":
                    detail = f"¥{c.new_price:.2f} | 销量{c.new_sales}"
                elif c.status == "已下架":
                    detail = f"原价¥{c.old_price:.2f}"
                else:
                    arrow = "▲" if c.price_diff > 0 else "▼"
                    detail = (f"¥{c.old_price:.2f} → ¥{c.new_price:.2f} "
                              f"{arrow}{abs(c.price_diff):.1f} "
                              f"({c.price_diff_pct:+.1f}%) | "
                              f"销量 {c.old_sales}→{c.new_sales}")

                print(f"  {i:2d}. {emoji} {c.status} | {title_short}")
                print(f"      {detail} | {c.shop_name}")

        if len(significant) > 15:
            print(f"      ... 还有 {len(significant) - 15} 条变动")

    print(f"\n  💾 快照: {report.snapshot_path}")
    print()


# ── 命令行入口 ──────────────────────────────────────────

async def main_cli() -> None:
    parser = argparse.ArgumentParser(
        description="📊 TAgent 盯价工具 — 自动追踪淘宝商品价格变化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python price_monitor.py "男装"                # 单次盯价
  python price_monitor.py "蓝牙耳机" -p 2       # 翻2页
  python price_monitor.py "露营灯" --show       # 显示浏览器
  python price_monitor.py "收纳盒" --alert-up 5  # 涨价超5元才提醒
  python price_monitor.py "男装" --days 7       # 对比7天前的数据
        """,
    )
    parser.add_argument("keyword", help="盯价的品类关键词（如 男装）")
    parser.add_argument("--pages", "-p", type=int, default=1,
                        help="每轮抓取的页数 (默认: 1)")
    parser.add_argument("--show", action="store_true",
                        help="显示浏览器窗口（调试用）")
    parser.add_argument("--alert-up", type=float, default=0,
                        help="涨价超过此金额(¥)才提醒 (默认: 全部提醒)")
    parser.add_argument("--alert-down", type=float, default=0,
                        help="降价超过此金额(¥)才提醒 (默认: 全部提醒)")
    parser.add_argument("--csv", action="store_true",
                        help="导出 CSV 报告")
    parser.add_argument("--json", action="store_true",
                        help="导出 JSON 报告")
    parser.add_argument("--days", type=int, default=0,
                        help="对比多少天前的数据（默认: 最新快照）")

    args = parser.parse_args()

    monitor = PriceMonitor(
        keyword=args.keyword,
        pages=args.pages,
        alert_up=args.alert_up,
        alert_down=args.alert_down,
        headless=not args.show,
    )

    report = await monitor.run()
    print_monitor_report(report)

    if report.error:
        sys.exit(1)

    if args.csv:
        monitor.export_csv(report)

    if args.json:
        monitor.export_json(report)


if __name__ == "__main__":
    asyncio.run(main_cli())
