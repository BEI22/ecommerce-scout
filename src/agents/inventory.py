"""库存Agent — 需求预测 & 补货建议 & 滞销预警

能力:
- 基于销量趋势的需求预测
- 安全库存计算 (lead time + 日均销量 + 安全系数)
- 补货提醒 (库存 < 安全库存)
- 滞销预警 (30天无销量或库存周转 > 90天)
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .base import BaseAgent, LLMClient


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SKU:
    """库存单位"""
    sku_id: str
    product_name: str
    current_stock: int              # 当前库存
    daily_avg_sales: float          # 日均销量 (近30天)
    lead_time_days: int = 7         # 补货周期(天)
    safety_factor: float = 1.5      # 安全库存系数
    unit_cost: float = 0.0          # 单位成本
    price: float = 0.0              # 售价
    last_restock_date: str = ""
    days_without_sales: int = 0     # 连续无销量天数
    stock_turnover_days: float = 0  # 库存周转天数
    status: str = "normal"          # normal / low / critical / dead


@dataclass
class InventoryAlert:
    """库存告警"""
    sku: SKU
    level: str                      # critical / warning / info
    title: str
    message: str
    suggested_action: str
    suggested_quantity: int = 0


@dataclass
class InventoryReport:
    """库存报告"""
    skus: list[SKU]
    alerts: list[InventoryAlert]
    total_stock_value: float
    dead_stock_value: float
    low_stock_count: int
    dead_stock_count: int
    summary: str


# ═══════════════════════════════════════════════════════════════════════
# 库存 Agent
# ═══════════════════════════════════════════════════════════════════════

class InventoryAgent(BaseAgent):
    """库存管理 Agent"""

    name = "inventory"
    description = "库存管理 — 需求预测 + 补货建议 + 滞销预警"

    def __init__(self, llm: LLMClient | None = None):
        super().__init__(llm)
        self.skus: list[SKU] = []

    def load_inventory(self, mock: bool = True) -> None:
        """加载库存数据"""
        if mock:
            self._generate_mock_skus()
            self.log(f"已加载 {len(self.skus)} 个 SKU")

    def _generate_mock_skus(self) -> None:
        """生成模拟库存数据"""
        import random
        today = datetime.now().strftime("%Y-%m-%d")
        products = [
            ("SKU001", "LED露营灯", 150, 8, 32.0, 18.0),
            ("SKU002", "帐篷灯串", 45, 5, 28.0, 15.0),
            ("SKU003", "头灯强光", 200, 12, 45.0, 25.0),
            ("SKU004", "强光手电筒", 80, 6, 39.0, 22.0),
            ("SKU005", "复古马灯", 20, 2, 55.0, 30.0),
            ("SKU006", "户外小风扇", 0, 3, 35.0, 20.0),         # 断货
            ("SKU007", "营地锤", 300, 0.2, 25.0, 12.0),         # 滞销
            ("SKU008", "防水袋", 60, 4, 18.0, 8.0),
        ]

        self.skus = []
        for sid, name, stock, daily_sales, price, cost in products:
            lead_time = random.randint(3, 10)
            safety_stock = round(daily_sales * lead_time * 1.5)
            turnover = round(stock / daily_sales, 1) if daily_sales > 0 else 999

            # 状态判断
            if stock <= 0:
                status = "critical"
            elif stock < safety_stock:
                status = "low"
            elif daily_sales < 0.5:
                status = "dead"
            else:
                status = "normal"

            self.skus.append(SKU(
                sku_id=sid,
                product_name=name,
                current_stock=stock,
                daily_avg_sales=daily_sales,
                lead_time_days=lead_time,
                safety_factor=1.5,
                unit_cost=cost,
                price=price,
                last_restock_date=(datetime.now() - timedelta(days=random.randint(5, 30))).strftime("%Y-%m-%d"),
                days_without_sales=random.randint(0, 60) if daily_sales < 1 else 0,
                stock_turnover_days=turnover,
                status=status,
            ))

    # ── 安全库存计算 ─────────────────────────────────────

    def calc_safety_stock(self, sku: SKU) -> int:
        """安全库存 = 日均销量 × 补货周期 × 安全系数"""
        return max(1, round(sku.daily_avg_sales * sku.lead_time_days * sku.safety_factor))

    def calc_suggested_order(self, sku: SKU) -> int:
        """建议补货量 = 安全库存 + 预计周期销量 - 当前库存"""
        safety = self.calc_safety_stock(sku)
        cycle_demand = round(sku.daily_avg_sales * sku.lead_time_days)
        needed = safety + cycle_demand - sku.current_stock
        return max(0, round(needed))

    # ── 核心分析 ────────────────────────────────────────

    def analyze(self) -> InventoryReport:
        """分析全量库存"""
        alerts: list[InventoryAlert] = []

        for sku in self.skus:
            safety_stock = self.calc_safety_stock(sku)
            suggested = self.calc_suggested_order(sku)

            # 断货
            if sku.current_stock <= 0:
                alerts.append(InventoryAlert(
                    sku=sku, level="critical",
                    title=f"🚨 断货: {sku.product_name}",
                    message=f"库存为 0，日均销售 {sku.daily_avg_sales:.1f} 件",
                    suggested_action=f"立即补货至少 {suggested} 件",
                    suggested_quantity=suggested,
                ))

            # 低库存
            elif sku.current_stock < safety_stock:
                alerts.append(InventoryAlert(
                    sku=sku, level="warning",
                    title=f"⚠ 库存不足: {sku.product_name}",
                    message=f"当前库存 {sku.current_stock}，安全库存 {safety_stock}，日均销售 {sku.daily_avg_sales:.1f} 件",
                    suggested_action=f"建议 3 天内补货 {suggested} 件",
                    suggested_quantity=suggested,
                ))

            # 滞销
            if sku.daily_avg_sales < 1 or sku.stock_turnover_days > 90:
                stock_value = sku.current_stock * sku.unit_cost
                alerts.append(InventoryAlert(
                    sku=sku, level="info",
                    title=f"💤 滞销预警: {sku.product_name}",
                    message=f"日均仅售 {sku.daily_avg_sales:.1f} 件，库存周转 {sku.stock_turnover_days:.0f} 天，占用资金 ¥{stock_value:.2f}",
                    suggested_action="建议降价促销或捆绑销售清理库存",
                ))

        # 汇总
        total_stock_value = sum(s.current_stock * s.unit_cost for s in self.skus)
        dead = [s for s in self.skus if s.daily_avg_sales < 1 or s.stock_turnover_days > 90]
        dead_value = sum(s.current_stock * s.unit_cost for s in dead)
        low_stock = sum(1 for s in self.skus if s.current_stock < self.calc_safety_stock(s) and s.current_stock > 0)
        out_of_stock = sum(1 for s in self.skus if s.current_stock <= 0)

        summary = (
            f"总库存价值 ¥{total_stock_value:,.2f}，滞销库存 ¥{dead_value:,.2f}。"
            f"断货 {out_of_stock} 个 SKU，低库存 {low_stock} 个 SKU，滞销 {len(dead)} 个 SKU。"
        )

        self.log(summary)
        return InventoryReport(
            skus=self.skus,
            alerts=alerts,
            total_stock_value=round(total_stock_value, 2),
            dead_stock_value=round(dead_value, 2),
            low_stock_count=low_stock,
            dead_stock_count=len(dead),
            summary=summary,
        )

    def run(self, action: str = "analyze", **kwargs) -> InventoryReport:
        """统一入口"""
        if not self.skus:
            self.load_inventory(mock=True)
        return self.analyze()
