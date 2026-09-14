"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Platform(str, Enum):
    TAOBAO = "taobao"
    PDD = "pinduoduo"
    SUPPLIER_1688 = "1688"


@dataclass
class ProductItem:
    """单个商品数据"""

    platform: Platform
    keyword: str                        # 搜索关键词
    title: str                          # 商品标题
    price: float                        # 价格(区间价取中位数)
    price_min: Optional[float] = None   # 最低价
    price_max: Optional[float] = None   # 最高价
    sales_count: int = 0                # 估算月销量
    sales_text: str = ""                # 原始销量文本(如"1万+人付款")
    shop_name: str = ""                 # 店铺名
    shop_type: str = ""                 # 店铺类型: 天猫/淘宝/旗舰店/个人店
    location: str = ""                  # 发货地
    img_url: str = ""                   # 主图URL
    product_url: str = ""               # 商品链接
    rating: Optional[float] = None      # 评分(如有)
    tags: list[str] = field(default_factory=list)     # 标签: 百亿补贴/品牌/新品
    free_shipping: bool = False         # 是否包邮
    scraped_at: datetime = field(default_factory=datetime.now)

    @property
    def estimated_monthly_revenue(self) -> float:
        """估算月销售额"""
        return self.price * self.sales_count


@dataclass
class ScoredProduct(ProductItem):
    """带打分结果的商品"""

    score: float = 0.0                  # 综合得分 0-100
    demand_score: float = 0.0           # 需求热度分
    competition_score: float = 0.0      # 竞争度分(越高=竞争越小)
    margin_score: float = 0.0           # 利润空间分
    arbitrage_score: float = 0.0        # 平台套利分
    trend_score: float = 0.0            # 趋势分
    estimated_margin_pct: float = 0.0   # 估算毛利率(%)
    cross_platform_match: bool = False  # 是否在另一平台有同款
    match_price_diff: float = 0.0       # 跨平台价差
    insight: str = ""                   # AI 选品洞察


@dataclass
class SearchResult:
    """一次搜索的完整结果"""

    keyword: str
    platform: Platform
    products: list[ProductItem] = field(default_factory=list)
    total_results: int = 0              # 平台显示的总结果数
    scraped_pages: int = 0
    error: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.now)


@dataclass
class AnalysisReport:
    """分析报告"""

    keyword: str
    products: list[ScoredProduct] = field(default_factory=list)
    taobao_count: int = 0
    pdd_count: int = 0
    avg_price_taobao: float = 0.0
    avg_price_pdd: float = 0.0
    price_gap_pct: float = 0.0          # 两平台均价差(%)
    competition_level: str = "未知"     # 竞争等级: 低/中/高/激烈
    top_pick: Optional[ScoredProduct] = None
    market_summary: str = ""            # 市场总结
    generated_at: datetime = field(default_factory=datetime.now)
