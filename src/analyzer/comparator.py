"""跨平台对比 — 同款识别、价差分析、竞品分布"""

import re
from difflib import SequenceMatcher

from ..models import Platform, ProductItem


class Comparator:
    """跨平台对比分析"""

    # 标题相似度阈值（认为可能是同款）
    SIMILARITY_THRESHOLD = 0.55

    @classmethod
    def find_cross_platform_matches(
        cls,
        taobao_items: list[ProductItem],
        pdd_items: list[ProductItem],
    ) -> list[dict]:
        """
        在淘宝和拼多多之间查找同款商品
        返回: [{taobao_item, pdd_item, similarity, price_diff, price_diff_pct}, ...]
        """
        matches: list[dict] = []

        # 按价格区间预过滤以减少比对量
        for tb in taobao_items:
            candidates = [
                pd for pd in pdd_items
                if cls._price_overlap(tb.price, pd.price, tolerance=0.5)
            ]
            if not candidates:
                continue

            best_match = None
            best_score = 0.0

            for pd in candidates:
                score = cls._title_similarity(tb.title, pd.title)
                if score > best_score:
                    best_score = score
                    best_match = pd

            if best_match and best_score >= cls.SIMILARITY_THRESHOLD:
                price_diff = tb.price - best_match.price
                avg_price = (tb.price + best_match.price) / 2
                price_diff_pct = round(price_diff / avg_price * 100, 1) if avg_price > 0 else 0

                matches.append({
                    "taobao_item": tb,
                    "pdd_item": best_match,
                    "similarity": round(best_score, 2),
                    "price_diff": round(price_diff, 2),
                    "price_diff_pct": price_diff_pct,
                    "arbitrage_direction": "拼多多更便宜" if price_diff > 0 else "淘宝更便宜",
                })

        # 按相似度降序排列
        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return matches

    @staticmethod
    def _price_overlap(price1: float, price2: float, tolerance: float = 0.5) -> bool:
        """判断两个价格是否可能代表同一商品（允许一定浮动）"""
        if price1 <= 0 or price2 <= 0:
            return False
        ratio = max(price1, price2) / min(price1, price2)
        return ratio <= (1 + tolerance)

    @staticmethod
    def _title_similarity(title1: str, title2: str) -> float:
        """计算两个标题的相似度"""
        # 提取关键特征词（品牌+品类+核心属性）
        t1 = Comparator._extract_features(title1)
        t2 = Comparator._extract_features(title2)
        return SequenceMatcher(None, t1, t2).ratio()

    @staticmethod
    def _extract_features(title: str) -> str:
        """提取标题中的特征词（去除非关键修饰词）"""
        # 去掉价格、包邮、促销词等
        noise = r"(\d+\.?\d*[元块]|\d+\.?\d*[—\-~到至]\d+\.?\d*)|包邮|顺丰|现货|热卖|爆款|推荐|正品|原装|批发|一件代发"
        cleaned = re.sub(noise, "", title, flags=re.IGNORECASE)
        # 去多余空格
        cleaned = re.sub(r"\s+", "", cleaned)
        return cleaned.strip()

    @classmethod
    def competition_analysis(cls, items: list[ProductItem]) -> dict:
        """
        竞争度分析
        返回: {level, shop_count, top3_share, herfindahl, ...}
        """
        if not items:
            return {"level": "未知", "shop_count": 0}

        # 各店铺销量
        shop_sales: dict[str, int] = {}
        for item in items:
            key = item.shop_name or "未知店铺"
            shop_sales[key] = shop_sales.get(key, 0) + item.sales_count

        total_sales = sum(shop_sales.values())
        shop_count = len(shop_sales)

        if total_sales == 0:
            return {"level": "数据不足", "shop_count": shop_count}

        # Top 3 集中度
        sorted_shops = sorted(shop_sales.values(), reverse=True)
        top3_sales = sum(sorted_shops[:3])
        top3_share = round(top3_sales / total_sales * 100, 1)

        # 赫芬达尔指数 (HHI)：< 1000 分散, 1000-1800 中度, > 1800 集中
        hhi = sum((s / total_sales * 100) ** 2 for s in shop_sales.values())
        hhi = round(hhi, 1)

        # 竞争等级
        if shop_count <= 5:
            level = "低竞争"
        elif shop_count <= 20 and top3_share < 50:
            level = "中等竞争"
        elif top3_share >= 70:
            level = "头部垄断"
        else:
            level = "高度竞争"

        return {
            "level": level,
            "shop_count": shop_count,
            "top3_share_pct": top3_share,
            "hhi": hhi,
            "total_products": len(items),
            "total_sales_est": total_sales,
        }
