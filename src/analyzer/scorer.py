"""智能打分引擎 — 五维评分模型"""

import math
import statistics

from ..config import SCORING
from ..models import Platform, ProductItem, ScoredProduct
from .comparator import Comparator
from .normalizer import Normalizer


class Scorer:
    """五维打分模型：
    1. 需求热度 (25%) — 销量 + 搜索热度
    2. 竞争程度 (25%) — 卖家数 + 头部集中度（竞争越低分越高）
    3. 利润空间 (30%) — (售价 - 估算成本 - 佣金 - 运费) / 售价
    4. 平台套利 (10%) — 跨平台价差越大机会越大
    5. 趋势判断 (10%) — 销量分布/近期走势
    """

    def __init__(self, cost_ratio: float | None = None, shipping: float | None = None):
        """
        Args:
            cost_ratio: 成本占售价的比例（0-1），不传则用默认 0.40
            shipping: 单件运费估算(元)，不传则用默认 5.0
        """
        self.cost_ratio = cost_ratio if cost_ratio is not None else SCORING["default_cost_ratio"]
        self.shipping = shipping if shipping is not None else SCORING["shipping_estimate"]

    def score_all(
        self,
        items: list[ProductItem],
        taobao_items: list[ProductItem] | None = None,
        pdd_items: list[ProductItem] | None = None,
    ) -> list[ScoredProduct]:
        """对所有商品打分排序"""
        if not items:
            return []

        # 去异常值
        cleaned = Normalizer.remove_outliers(items, "price")
        cleaned = Normalizer.remove_outliers(cleaned, "sales_count")

        # 全局统计（用于相对评分）
        all_prices = [i.price for i in cleaned if i.price > 0]
        all_sales = [i.sales_count for i in cleaned]
        max_price = max(all_prices) if all_prices else 1
        max_sales = max(all_sales) if all_sales else 1
        median_price = statistics.median(all_prices) if all_prices else 1
        median_sales = statistics.median(all_sales) if all_sales else 1

        # 跨平台匹配
        tb = taobao_items or [i for i in items if i.platform == Platform.TAOBAO]
        pd = pdd_items or [i for i in items if i.platform == Platform.PDD]
        cross_matches = Comparator.find_cross_platform_matches(tb, pd) if tb and pd else []
        matched_tb_ids = {id(m["taobao_item"]) for m in cross_matches}
        matched_pd_ids = {id(m["pdd_item"]) for m in cross_matches}

        scored: list[ScoredProduct] = []
        for item in cleaned:
            s = self._score_one(
                item, max_price, max_sales, median_price, median_sales,
                cross_matches, matched_tb_ids, matched_pd_ids,
            )
            scored.append(s)

        # 按综合得分降序
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    def _score_one(
        self,
        item: ProductItem,
        max_price: float,
        max_sales: float,
        median_price: float,
        median_sales: float,
        cross_matches: list[dict],
        matched_tb_ids: set,
        matched_pd_ids: set,
    ) -> ScoredProduct:
        """对单个商品打分"""

        # 1. 需求热度 (0-100): 销量越高越好
        demand = self._normalize(item.sales_count, median_sales, max_sales) * 100

        # 2. 竞争程度 (0-100): 中位价附近竞争最激烈，偏离中位价越多竞争越小
        if median_price > 0:
            price_deviation = abs(item.price - median_price) / median_price
            # 价格偏离中位数越远，竞争越小（可能是高端或低端蓝海）
            competition = min(100, price_deviation * 80 + 30)
        else:
            competition = 50

        # 3. 利润空间 (0-100)
        cost = item.price * self.cost_ratio
        platform_fee = item.price * SCORING["platform_fee_ratio"]
        shipping = 0 if item.free_shipping else self.shipping
        gross_profit = item.price - cost - platform_fee - shipping
        margin_pct = gross_profit / item.price if item.price > 0 else 0
        # 利润率映射到 0-100: 负利润→0, 50%利润率→100
        margin = max(0, min(100, margin_pct * 200))

        # 4. 平台套利 (0-100): 同一商品在另一平台价差越大越好
        arbitrage = 0
        match_price_diff = 0.0
        cross_platform_match = False
        if item.platform == Platform.TAOBAO and id(item) in matched_tb_ids:
            match = next(m for m in cross_matches if id(m["taobao_item"]) == id(item))
            match_price_diff = match["price_diff"]
            cross_platform_match = True
            # 淘宝比拼多多贵 → 从拼多多进货到淘宝卖有利可图
            if match["price_diff"] > 0:
                arb_pct = abs(match["price_diff_pct"])
                arbitrage = min(100, arb_pct * 3)  # 30%价差=90分
        elif item.platform == Platform.PDD and id(item) in matched_pd_ids:
            match = next(m for m in cross_matches if id(m["pdd_item"]) == id(item))
            match_price_diff = -match["price_diff"]
            cross_platform_match = True
            if match["price_diff"] < 0:  # 拼多多比淘宝便宜 → 有套利空间
                arb_pct = abs(match["price_diff_pct"])
                arbitrage = min(100, arb_pct * 3)

        # 5. 趋势 (0-100): 基于销量相对位置 (简易版，有历史数据后可扩展)
        sales_ratio = item.sales_count / max_sales if max_sales > 0 else 0
        trend = sales_ratio * 70 + (20 if cross_platform_match else 0) + 10
        if item.tags and any(t in ["新品", "百亿补贴", "品牌"] for t in item.tags):
            trend = min(100, trend + 10)

        # 加权总分
        weights = SCORING
        total = (
            demand * weights["demand_weight"]
            + competition * weights["competition_weight"]
            + margin * weights["margin_weight"]
            + arbitrage * weights["arbitrage_weight"]
            + trend * weights["trend_weight"]
        )

        # 生成洞察
        insight = self._generate_insight(item, margin_pct, cross_platform_match, match_price_diff)

        return ScoredProduct(
            platform=item.platform,
            keyword=item.keyword,
            title=item.title,
            price=item.price,
            price_min=item.price_min,
            price_max=item.price_max,
            sales_count=item.sales_count,
            sales_text=item.sales_text,
            shop_name=item.shop_name,
            shop_type=item.shop_type,
            location=item.location,
            img_url=item.img_url,
            product_url=item.product_url,
            tags=item.tags,
            free_shipping=item.free_shipping,
            score=round(total, 1),
            demand_score=round(demand, 1),
            competition_score=round(competition, 1),
            margin_score=round(margin, 1),
            arbitrage_score=round(arbitrage, 1),
            trend_score=round(trend, 1),
            estimated_margin_pct=round(margin_pct * 100, 1),
            cross_platform_match=cross_platform_match,
            match_price_diff=match_price_diff,
            insight=insight,
        )

    @staticmethod
    def _normalize(value: float, median: float, maximum: float) -> float:
        """对数归一化到 0-1"""
        if maximum <= 0:
            return 0.0
        # 使用对数平滑极端值
        v = math.log1p(value) / math.log1p(maximum) if value > 0 else 0
        return max(0.0, min(1.0, v))

    @staticmethod
    def _generate_insight(
        item: ProductItem,
        margin_pct: float,
        cross_match: bool,
        price_diff: float,
    ) -> str:
        """生成分维度分析洞察"""
        parts = []

        # 利润判断
        if margin_pct > 0.5:
            parts.append("💰 高利润品类")
        elif margin_pct > 0.25:
            parts.append("👍 利润可观")
        elif margin_pct > 0.1:
            parts.append("📊 薄利多销型")
        else:
            parts.append("⚠ 利润偏低，需控制成本")

        # 跨平台
        if cross_match:
            if price_diff > 20:
                parts.append("🔄 跨平台价差大，套利空间明显")
            elif price_diff > 5:
                parts.append("↔ 两平台价差适中")
            else:
                parts.append("≈ 两平台价格趋同，竞争充分")

        # 销量
        if item.sales_count > 10000:
            parts.append("🔥 爆款级别销量")
        elif item.sales_count > 1000:
            parts.append("📈 销量稳定")
        elif item.sales_count > 100:
            parts.append("🌱 成长中，待观察")
        else:
            parts.append("🔍 新品或长尾，可测试")

        # 品牌判断
        if item.shop_type in ["天猫", "品牌店"]:
            parts.append("🏷 品牌背书，信任成本低")

        return " | ".join(parts)
