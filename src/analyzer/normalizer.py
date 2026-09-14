"""数据清洗 & 标准化 — 统一两平台数据格式，清洗异常值"""

import re
import statistics
from typing import Sequence

from ..models import Platform, ProductItem, SearchResult


class Normalizer:
    """数据清洗器"""

    @classmethod
    def normalize(cls, results: list[SearchResult]) -> list[ProductItem]:
        """合并多个 SearchResult 并清洗"""
        all_items: list[ProductItem] = []
        for r in results:
            if r.error:
                continue
            for p in r.products:
                cleaned = cls._clean_item(p)
                if cleaned:
                    all_items.append(cleaned)
        return all_items

    @classmethod
    def _clean_item(cls, item: ProductItem) -> ProductItem | None:
        """清洗单个商品数据"""
        # 标题清洗
        title = cls._clean_title(item.title)
        if not title or len(title) < 2:
            return None

        # 过滤异常价格（< 0.1 或 > 100000 可能是解析错误）
        if item.price < 0.1 or item.price > 100000:
            return None

        # 价格修正：处理区间价格
        if item.price_min is None and item.price_max is None and title:
            interval_price = cls._extract_interval_price(title)
            if interval_price:
                item.price_min, item.price_max = interval_price
                item.price = round((interval_price[0] + interval_price[1]) / 2, 2)

        item.title = title
        return item

    @staticmethod
    def _clean_title(raw: str) -> str:
        """清洗标题：去 HTML 实体、多余空白、emoji 过滤"""
        # 去 HTML 实体
        raw = raw.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
        # 去多余空白
        raw = re.sub(r"\s+", " ", raw)
        # 去除首尾空格和特殊字符
        raw = raw.strip(" -\t\n\r")
        # 去除纯 emoji 或乱码行（保留包含中文/英文的）
        if not re.search(r"[一-鿿\w]", raw):
            return ""
        return raw

    @staticmethod
    def _extract_interval_price(title: str) -> tuple[float, float] | None:
        """从标题中提取区间价格如 "9.9-19.9" """
        m = re.search(r"(\d+\.?\d*)\s*[—\-~到至]\s*(\d+\.?\d*)", title)
        if m:
            return (float(m.group(1)), float(m.group(2)))
        return None

    @staticmethod
    def remove_outliers(items: list[ProductItem], field: str = "price") -> list[ProductItem]:
        """去除价格/销量异常值 (IQR 方法)"""
        if len(items) < 4:
            return items

        values = [getattr(i, field) for i in items if getattr(i, field) > 0]
        if len(values) < 4:
            return items

        q1 = statistics.median(sorted(values)[: len(values) // 2])
        q3 = statistics.median(sorted(values)[len(values) // 2 :])
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        return [i for i in items if lower <= getattr(i, field) <= upper]

    @classmethod
    def aggregate_stats(cls, items: list[ProductItem]) -> dict:
        """汇总统计"""
        if not items:
            return {}

        prices = [i.price for i in items if i.price > 0]
        sales = [i.sales_count for i in items]

        return {
            "count": len(items),
            "avg_price": round(statistics.mean(prices), 2) if prices else 0,
            "median_price": round(statistics.median(prices), 2) if prices else 0,
            "min_price": round(min(prices), 2) if prices else 0,
            "max_price": round(max(prices), 2) if prices else 0,
            "price_std": round(statistics.pstdev(prices), 2) if len(prices) > 1 else 0,
            "total_sales": sum(sales),
            "avg_sales": round(statistics.mean(sales), 0) if sales else 0,
            "median_sales": round(statistics.median(sales), 0) if sales else 0,
            "shop_count": len(set(i.shop_name for i in items if i.shop_name)),
        }
