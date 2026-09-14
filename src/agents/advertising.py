"""广告Agent — 投放优化 & 规则引擎 & 预算分配

能力:
- ROI 规则引擎: ROI > 目标 → 加预算 | ROI < 底线 → 暂停
- 日预算自动分配 (多广告组按 ROI 加权)
- 降价策略 (ROI 中间区间的自动调价)
- 新广告组小预算测款
- 关键词表现分析
- 广告日报/周报

用法:
    agent = AdvertisingAgent()
    agent.setup_campaigns(mock_data=True)      # 初始化模拟数据

    status = agent.get_status()                # 查看广告状态
    actions = agent.optimize()                 # 执行优化建议
    report = agent.daily_report()              # 日报
"""

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .base import BaseAgent, LLMClient


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class AdGroup:
    """广告组/广告计划"""
    id: str
    name: str
    product_name: str
    daily_budget: float           # 日预算
    spend_today: float = 0.0      # 今日消耗
    cpc: float = 0.0              # 平均点击单价
    clicks: int = 0               # 今日点击数
    impressions: int = 0          # 今日曝光
    orders: int = 0               # 今日订单
    revenue: float = 0.0          # 今日广告收入
    acos: float = 0.0             # ACOS (广告花费/广告收入)
    roas: float = 0.0             # ROAS (广告收入/广告花费)
    status: str = "active"        # active / paused / testing
    bid: float = 0.0              # 出价
    target_acos: float = 0.30     # 目标 ACOS
    keywords: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)  # 历史每日数据
    created_at: str = ""


@dataclass
class AdAction:
    """广告优化操作"""
    campaign_id: str
    campaign_name: str
    action: str                    # increase_budget / decrease_budget / pause / reduce_bid / start_testing
    detail: str
    amount: float = 0.0
    reason: str = ""


@dataclass
class AdReport:
    """广告日报"""
    date: str
    campaigns: list[AdGroup]
    total_spend: float = 0.0
    total_revenue: float = 0.0
    total_orders: int = 0
    overall_acos: float = 0.0
    overall_roas: float = 0.0
    actions_taken: list[AdAction] = field(default_factory=list)
    insights: str = ""


# ═══════════════════════════════════════════════════════════════════════
# 规则引擎配置
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class AdRules:
    """广告规则配置"""
    target_acos: float = 0.30            # 目标 ACOS（30%）
    min_acos: float = 0.10               # ACOS 下限（低于这个暂停，可能数据不准）
    max_acos: float = 0.50               # ACOS 上限（高于这个暂停）
    budget_increase_pct: float = 0.20    # 加预算 20%
    budget_decrease_pct: float = 0.15    # 减预算 15%
    bid_decrease_pct: float = 0.10       # 降价 10%
    testing_daily_budget: float = 50.0   # 新组测款日预算
    min_daily_budget: float = 10.0       # 最低日预算（低于这个暂停）
    min_data_threshold: int = 10         # 最少点击数才做决策（数据不足不动）
    max_budget_per_campaign: float = 500.0  # 单组预算上限


# ═══════════════════════════════════════════════════════════════════════
# 广告 Agent
# ═══════════════════════════════════════════════════════════════════════

class AdvertisingAgent(BaseAgent):
    """广告投放优化 Agent"""

    name = "advertising"
    description = "广告投放优化 — 规则引擎 + ROI 自动调整"

    def __init__(
        self,
        llm: LLMClient | None = None,
        rules: AdRules | None = None,
    ):
        super().__init__(llm)
        self.rules = rules or AdRules()
        self.campaigns: list[AdGroup] = []
        self.action_log: list[AdAction] = []

    # ── 初始化 ──────────────────────────────────────────

    def setup_campaigns(self, mock_data: bool = True) -> None:
        """初始化广告组

        接入真实 API 时，替换此方法对接各广告平台 (Amazon Ads / 淘宝直通车 / 拼多多推广)
        """
        if mock_data:
            self._generate_mock_campaigns()

    def _generate_mock_campaigns(self) -> None:
        """生成模拟广告数据"""
        today = datetime.now().strftime("%Y-%m-%d")
        products = [
            ("camplight", "LED露营灯", 32.0),
            ("tentlight", "帐篷灯串", 28.0),
            ("headlamp", "头灯强光", 45.0),
            ("flashlight", "强光手电筒", 39.0),
            ("lantern", "户外复古马灯", 55.0),
        ]

        self.campaigns = []
        for pid, name, price in products:
            # 生成历史 7 天数据
            history = []
            for d in range(7, 0, -1):
                date = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
                spend = round(random.uniform(30, 100), 2)
                orders = random.randint(1, 8)
                revenue = round(orders * price, 2)
                acos = round(spend / revenue, 3) if revenue > 0 else 1.0
                history.append({
                    "date": date, "spend": spend, "orders": orders,
                    "revenue": revenue, "acos": acos,
                })

            # 今天的实时数据
            spend_today = round(random.uniform(20, 80), 2)
            clicks = random.randint(20, 100)
            impressions = random.randint(500, 3000)
            orders = random.randint(0, 5)
            revenue = round(orders * price, 2)
            acos = round(spend_today / revenue, 3) if revenue > 0 else 1.0
            roas = round(revenue / spend_today, 2) if spend_today > 0 else 0.0

            campaign = AdGroup(
                id=pid,
                name=f"{name}-自动广告",
                product_name=name,
                daily_budget=round(random.uniform(50, 150), 2),
                spend_today=spend_today,
                cpc=round(random.uniform(0.5, 2.0), 2),
                clicks=clicks,
                impressions=impressions,
                orders=orders,
                revenue=revenue,
                acos=acos,
                roas=roas,
                status="active" if random.random() > 0.2 else "paused",
                bid=round(random.uniform(1.0, 3.0), 2),
                target_acos=self.rules.target_acos,
                keywords=self._mock_keywords(pid),
                history=history,
                created_at=(datetime.now() - timedelta(days=random.randint(7, 30))).strftime("%Y-%m-%d"),
            )
            self.campaigns.append(campaign)

        self.log(f"已创建 {len(self.campaigns)} 个模拟广告组")

    @staticmethod
    def _mock_keywords(pid: str) -> list[dict]:
        words = {
            "camplight": [("露营灯", 0.25), ("户外灯", 0.35), ("帐篷灯", 0.20), ("充电灯", 0.30)],
            "tentlight": [("帐篷灯串", 0.22), ("装饰灯", 0.40), ("氛围灯", 0.28)],
            "headlamp": [("头灯强光", 0.18), ("夜跑灯", 0.32), ("矿灯", 0.35)],
            "flashlight": [("手电筒强光", 0.20), ("应急灯", 0.30), ("远射手电", 0.28)],
            "lantern": [("复古马灯", 0.15), ("露营灯", 0.35), ("装饰灯", 0.33)],
        }
        ws = words.get(pid, [("通用词", 0.30)])
        return [{"keyword": w[0], "acos": w[1], "clicks": random.randint(5, 30)} for w in ws]

    # ── 状态查询 ────────────────────────────────────────

    def get_status(self) -> AdReport:
        """获取当前广告状态"""
        return self._build_report()

    # ── 核心: 优化决策 ──────────────────────────────────

    def optimize(self) -> list[AdAction]:
        """执行一轮优化，返回执行的操作列表"""
        actions: list[AdAction] = []
        self.action_log = []

        for camp in self.campaigns:
            action = self._evaluate_campaign(camp)
            if action:
                actions.append(action)
                self.action_log.append(action)
                self._apply_action(camp, action)

        self.log(f"优化完成: 执行了 {len(actions)} 个操作")
        return actions

    def _evaluate_campaign(self, camp: AdGroup) -> AdAction | None:
        """评估单个广告组是否需要优化"""
        # 数据不足，不做决策
        if camp.clicks < self.rules.min_data_threshold:
            return None

        # ACOS > 上限 → 暂停或大降预算
        if camp.acos > self.rules.max_acos:
            if camp.daily_budget <= self.rules.min_daily_budget:
                return AdAction(
                    campaign_id=camp.id, campaign_name=camp.name,
                    action="pause", detail="暂停广告组",
                    reason=f"ACOS {camp.acos:.1%} 远超上限 {self.rules.max_acos:.0%}，且预算已到最低",
                )
            new_budget = round(camp.daily_budget * (1 - self.rules.budget_decrease_pct), 2)
            return AdAction(
                campaign_id=camp.id, campaign_name=camp.name,
                action="decrease_budget", detail=f"预算 {camp.daily_budget}→{new_budget}",
                amount=new_budget - camp.daily_budget,
                reason=f"ACOS {camp.acos:.1%} > 上限 {self.rules.max_acos:.0%}",
            )

        # ACOS < 目标 → 加预算
        if camp.acos < self.rules.target_acos:
            if camp.daily_budget >= self.rules.max_budget_per_campaign:
                return None  # 已到预算上限
            new_budget = round(camp.daily_budget * (1 + self.rules.budget_increase_pct), 2)
            new_budget = min(new_budget, self.rules.max_budget_per_campaign)
            return AdAction(
                campaign_id=camp.id, campaign_name=camp.name,
                action="increase_budget", detail=f"预算 {camp.daily_budget}→{new_budget}",
                amount=new_budget - camp.daily_budget,
                reason=f"ACOS {camp.acos:.1%} < 目标 {self.rules.target_acos:.0%}，加大投入",
            )

        # ACOS 在中间区间 → 降低出价测试
        if self.rules.target_acos < camp.acos <= self.rules.max_acos:
            new_bid = round(camp.bid * (1 - self.rules.bid_decrease_pct), 2)
            return AdAction(
                campaign_id=camp.id, campaign_name=camp.name,
                action="reduce_bid", detail=f"出价 {camp.bid}→{new_bid}",
                amount=camp.bid - new_bid,
                reason=f"ACOS {camp.acos:.1%} 偏高，降出价 10% 测试",
            )

        return None

    def _apply_action(self, camp: AdGroup, action: AdAction) -> None:
        """将优化操作应用到广告组"""
        if action.action == "pause":
            camp.status = "paused"
            camp.daily_budget = 0
        elif action.action == "increase_budget":
            camp.daily_budget += action.amount
        elif action.action == "decrease_budget":
            camp.daily_budget = max(self.rules.min_daily_budget, camp.daily_budget + action.amount)
        elif action.action == "reduce_bid":
            camp.bid = max(0.3, camp.bid - action.amount)

    # ── 新广告组测款 ────────────────────────────────────

    def create_test_campaign(self, product_name: str, product_price: float, keywords: list[str]) -> AdGroup:
        """创建新的测款广告组"""
        today = datetime.now().strftime("%Y-%m-%d")
        camp = AdGroup(
            id=f"test_{len(self.campaigns):04d}",
            name=f"{product_name}-测款广告",
            product_name=product_name,
            daily_budget=self.rules.testing_daily_budget,
            status="testing",
            bid=round(product_price * 0.05, 2),  # 初始出价为售价的 5%
            target_acos=self.rules.target_acos,
            keywords=[{"keyword": kw, "acos": 0, "clicks": 0} for kw in keywords],
            created_at=today,
        )
        self.campaigns.append(camp)
        self.log(f"新建测款广告: {camp.name} (日预算 ¥{camp.daily_budget})")
        action = AdAction(
            campaign_id=camp.id, campaign_name=camp.name,
            action="start_testing", detail=f"新建测款，日预算 ¥{camp.daily_budget}",
            reason=f"新产品 {product_name} 上架，小预算测试市场反应",
        )
        self.action_log.append(action)
        return camp

    # ── 报告 ────────────────────────────────────────────

    def _build_report(self) -> AdReport:
        """生成当前广告报告"""
        total_spend = sum(c.spend_today for c in self.campaigns)
        total_revenue = sum(c.revenue for c in self.campaigns)
        total_orders = sum(c.orders for c in self.campaigns)
        overall_acos = round(total_spend / total_revenue, 3) if total_revenue > 0 else 0
        overall_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0

        return AdReport(
            date=datetime.now().strftime("%Y-%m-%d"),
            campaigns=self.campaigns,
            total_spend=round(total_spend, 2),
            total_revenue=round(total_revenue, 2),
            total_orders=total_orders,
            overall_acos=overall_acos,
            overall_roas=overall_roas,
            actions_taken=list(self.action_log),
            insights=self._generate_insights(),
        )

    def _generate_insights(self) -> str:
        """生成广告洞察 (LLM)"""
        if not self.campaigns:
            return "暂无广告数据"

        # 规则生成的快速摘要
        active = [c for c in self.campaigns if c.status == "active"]
        winner = max(self.campaigns, key=lambda c: c.roas) if self.campaigns else None
        loser = min(self.campaigns, key=lambda c: c.roas) if self.campaigns else None

        parts = []
        parts.append(f"共 {len(self.campaigns)} 个广告组，{len(active)} 个活跃。")

        if winner:
            parts.append(f"表现最佳: {winner.name}（ROAS {winner.roas:.1f}，ACOS {winner.acos:.1%})。")
        if loser:
            parts.append(f"需关注: {loser.name}（ROAS {loser.roas:.1f}，ACOS {loser.acos:.1%})。")

        total_spend = round(sum(c.spend_today for c in self.campaigns), 2)
        total_rev = round(sum(c.revenue for c in self.campaigns), 2)
        profit = round(total_rev - total_spend, 2)
        parts.append(f"今日广告花费 ¥{total_spend}，带来收入 ¥{total_rev}，利润 ¥{profit}。")

        return " ".join(parts)

    def daily_report(self) -> str:
        """生成广告日报（Markdown）"""
        report = self._build_report()

        md = [
            f"# 📊 广告日报 — {report.date}\n",
            f"## 总览\n",
            f"| 指标 | 数值 |",
            f"|---|---|",
            f"| 总花费 | ¥{report.total_spend:.2f} |",
            f"| 总收入 | ¥{report.total_revenue:.2f} |",
            f"| 总订单 | {report.total_orders} 单 |",
            f"| 整体 ACOS | {report.overall_acos:.1%} |",
            f"| 整体 ROAS | {report.overall_roas:.1f} |",
            f"\n## 广告组详情\n",
            f"| 广告组 | 预算 | 消耗 | 订单 | 收入 | ACOS | ROAS | 状态 |",
            f"|---|---|---|---|---|---|---|---|",
        ]

        for c in report.campaigns:
            status_icon = "🟢" if c.status == "active" else "🔴" if c.status == "paused" else "🟡"
            md.append(
                f"| {c.name} | ¥{c.daily_budget:.0f} | ¥{c.spend_today:.2f} | {c.orders} | "
                f"¥{c.revenue:.2f} | {c.acos:.1%} | {c.roas:.1f} | {status_icon} {c.status} |"
            )

        if report.actions_taken:
            md.append(f"\n## 今日操作\n")
            for a in report.actions_taken:
                md.append(f"- **{a.campaign_name}**: {a.detail} — _{a.reason}_")

        md.append(f"\n## 洞察\n{report.insights}\n")
        return "\n".join(md)

    def run(self, action: str = "status", **kwargs) -> Any:
        """统一入口"""
        if action == "status":
            return self.get_status()
        elif action == "optimize":
            return self.optimize()
        elif action == "report":
            return self.daily_report()
        elif action == "add_campaign":
            return self.create_test_campaign(
                kwargs.get("product_name", "新品"),
                kwargs.get("product_price", 50),
                kwargs.get("keywords", []),
            )
        else:
            return self.get_status()
