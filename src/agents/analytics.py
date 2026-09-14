"""数据Agent — 报表分析 & 异常预警 & 趋势预测

能力:
- 多渠道数据汇总
- 异常检测 (销量骤降/广告消耗异常/差评激增)
- 趋势预测 (简单移动平均)
- 自动化周报 (Markdown)
- 关键指标计算

用法:
    agent = AnalyticsAgent()
    agent.load_data(mock=True)              # 加载模拟数据
    alerts = agent.check_alerts()          # 检查异常
    report = agent.weekly_report()          # 生成周报
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .base import BaseAgent, LLMClient


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DailyMetric:
    """每日指标"""
    date: str
    revenue: float = 0.0
    orders: int = 0
    ad_spend: float = 0.0
    ad_revenue: float = 0.0
    profit: float = 0.0
    profit_margin: float = 0.0
    page_views: int = 0
    conversion_rate: float = 0.0
    negative_reviews: int = 0
    total_reviews: int = 0
    inventory_warnings: int = 0


@dataclass
class Alert:
    """告警"""
    level: str             # critical / warning / info
    category: str          # sales / ad / review / inventory
    title: str
    message: str
    metric: str
    current_value: float
    expected_value: float
    deviation_pct: float


@dataclass
class WeeklyReport:
    """周报"""
    start_date: str
    end_date: str
    metrics: list[DailyMetric] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    summary: str = ""
    total_revenue: float = 0.0
    total_profit: float = 0.0
    total_orders: int = 0
    avg_margin: float = 0.0
    week_over_week: float = 0.0     # 环比
    top_products: list[dict] = field(default_factory=list)
    recommendations: str = ""


# ═══════════════════════════════════════════════════════════════════════
# 数据 Agent
# ═══════════════════════════════════════════════════════════════════════

class AnalyticsAgent(BaseAgent):
    """数据分析 & 预警 Agent"""

    name = "analytics"
    description = "数据报表 — 异常检测 + 趋势预测 + 自动化周报"

    def __init__(self, llm: LLMClient | None = None):
        super().__init__(llm)
        self.data: list[DailyMetric] = []
        self.alerts: list[Alert] = []

    # ── 数据加载 ────────────────────────────────────────

    def load_data(self, mock: bool = True, days: int = 30) -> None:
        """加载数据。接入真实数据源时替换此方法。"""
        if mock:
            self._generate_mock_data(days)
            self.log(f"已加载 {len(self.data)} 天模拟数据")

    def _generate_mock_data(self, days: int) -> None:
        """生成模拟每日数据"""
        import random
        self.data = []
        revenue_base = random.uniform(2000, 5000)
        for d in range(days, 0, -1):
            date = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
            # 加入趋势和随机波动
            trend = 1 + (days - d) * 0.003  # 轻微上升趋势
            noise = random.uniform(0.8, 1.2)
            day_of_week = (datetime.now() - timedelta(days=d)).weekday()

            revenue = round(revenue_base * trend * noise * (0.8 if day_of_week < 2 else 1.0), 2)
            orders = max(1, round(revenue / random.uniform(35, 55)))
            ad_spend = round(revenue * random.uniform(0.15, 0.35), 2)
            ad_revenue = round(revenue * random.uniform(0.3, 0.5), 2)
            cost = round(revenue * random.uniform(0.4, 0.6), 2)
            profit = round(revenue - cost - ad_spend, 2)
            margin = round(profit / revenue * 100, 1) if revenue > 0 else 0

            self.data.append(DailyMetric(
                date=date,
                revenue=revenue,
                orders=orders,
                ad_spend=ad_spend,
                ad_revenue=ad_revenue,
                profit=profit,
                profit_margin=margin,
                page_views=random.randint(500, 2000),
                conversion_rate=round(random.uniform(2, 8), 1),
                negative_reviews=random.randint(0, 2),
                total_reviews=random.randint(2, 12),
                inventory_warnings=random.randint(0, 1),
            ))

    # ── 异常检测 ────────────────────────────────────────

    def check_alerts(self) -> list[Alert]:
        """检查所有异常"""
        self.alerts = []
        if len(self.data) < 7:
            return []

        # 1. 销量骤降检测
        self._check_sales_drop()

        # 2. 广告消耗异常
        self._check_ad_spend_anomaly()

        # 3. 差评激增
        self._check_review_spike()

        # 4. 利润率异常
        self._check_margin_drop()

        if self.alerts:
            self.log(f"⚠ 发现 {len(self.alerts)} 个异常")
        else:
            self.log("✅ 无异常")
        return self.alerts

    def _check_sales_drop(self) -> None:
        """检测销量是否骤降"""
        recent = self.data[-7:]   # 最近 7 天
        prior = self.data[-14:-7]  # 前 7 天

        if len(prior) < 3:
            return

        recent_avg = statistics.mean(d.orders for d in recent)
        prior_avg = statistics.mean(d.orders for d in prior)

        if prior_avg > 0:
            change = (recent_avg - prior_avg) / prior_avg * 100
            if change < -30:
                self.alerts.append(Alert(
                    level="critical", category="sales",
                    title="📉 销量骤降",
                    message=f"近7天日均订单 {recent_avg:.0f}，环比下跌 {abs(change):.0f}%",
                    metric="orders", current_value=recent_avg,
                    expected_value=prior_avg, deviation_pct=round(change, 1),
                ))
            elif change < -15:
                self.alerts.append(Alert(
                    level="warning", category="sales",
                    title="⚠ 销量下滑趋势",
                    message=f"近7天日均订单 {recent_avg:.0f}，环比下跌 {abs(change):.0f}%",
                    metric="orders", current_value=recent_avg,
                    expected_value=prior_avg, deviation_pct=round(change, 1),
                ))

    def _check_ad_spend_anomaly(self) -> None:
        """检测广告消耗是否异常"""
        today = self.data[-1]
        recent = self.data[-7:]
        avg_spend = statistics.mean(d.ad_spend for d in recent)

        if avg_spend > 0:
            deviation = (today.ad_spend - avg_spend) / avg_spend * 100
            if deviation > 50:
                self.alerts.append(Alert(
                    level="warning", category="ad",
                    title="⚠ 广告消耗异常升高",
                    message=f"今日广告消耗 ¥{today.ad_spend:.2f}，超出7天均值 {deviation:.0f}%，请检查是否有恶意点击或设置错误",
                    metric="ad_spend", current_value=today.ad_spend,
                    expected_value=avg_spend, deviation_pct=round(deviation, 1),
                ))

            # ACOS 异常
            if today.ad_revenue > 0:
                today_acos = today.ad_spend / today.ad_revenue
                avg_acos = statistics.mean(d.ad_spend / d.ad_revenue for d in recent if d.ad_revenue > 0)
                if avg_acos > 0 and today_acos > avg_acos * 1.4:
                    self.alerts.append(Alert(
                        level="warning", category="ad",
                        title="⚠ ACOS 异常升高",
                        message=f"今日 ACOS {today_acos:.1%}，远高于近期均值 {avg_acos:.1%}",
                        metric="acos", current_value=today_acos,
                        expected_value=avg_acos, deviation_pct=round((today_acos - avg_acos) / avg_acos * 100, 1),
                    ))

    def _check_review_spike(self) -> None:
        """检测差评激增"""
        recent = self.data[-3:]
        nega = sum(d.negative_reviews for d in recent)
        if nega >= 3:
            self.alerts.append(Alert(
                level="critical", category="review",
                title="🚨 差评激增",
                message=f"近3天收到 {nega} 条差评，建议立即检查产品质量和客服响应",
                metric="negative_reviews", current_value=nega,
                expected_value=1, deviation_pct=round((nega - 1) / 1 * 100, 1),
            ))

    def _check_margin_drop(self) -> None:
        """检测利润率异常"""
        recent = self.data[-7:]
        recent_avg = statistics.mean(d.profit_margin for d in recent)
        if len(self.data) >= 14:
            prior_avg = statistics.mean(d.profit_margin for d in self.data[-14:-7])
            if prior_avg > 0 and recent_avg < prior_avg * 0.8:
                self.alerts.append(Alert(
                    level="warning", category="profit",
                    title="⚠ 利润率下降",
                    message=f"近7天平均利润率 {recent_avg:.1f}%，低于前7天 {prior_avg:.1f}%",
                    metric="profit_margin", current_value=recent_avg,
                    expected_value=prior_avg, deviation_pct=round((recent_avg - prior_avg) / prior_avg * 100, 1),
                ))

    # ── 趋势预测 ────────────────────────────────────────

    def forecast(self, metric: str = "revenue", days: int = 7) -> dict:
        """简易移动平均预测

        Returns:
            {"next_7_days": [...], "trend": "up/down/flat", "confidence": "low/medium/high"}
        """
        if len(self.data) < 7:
            return {"error": "数据不足"}

        values = [getattr(d, metric) for d in self.data]
        recent_window = values[-7:]
        ma = statistics.mean(recent_window)

        # 简单线性趋势
        n = len(values)
        if n >= 14:
            mid = n // 2
            first_half_avg = statistics.mean(values[:mid])
            second_half_avg = statistics.mean(values[mid:])
            if second_half_avg > first_half_avg * 1.05:
                trend = "up"
            elif second_half_avg < first_half_avg * 0.95:
                trend = "down"
            else:
                trend = "flat"
        else:
            trend = "flat"

        # 预测未来
        forecast_values = [round(ma, 2) for _ in range(days)]
        if trend == "up":
            forecast_values = [round(ma * (1 + 0.02 * i), 2) for i in range(days)]
        elif trend == "down":
            forecast_values = [round(ma * (1 - 0.02 * i), 2) for i in range(days)]

        return {
            "metric": metric,
            "next_days": forecast_values,
            "trend": trend,
            "trend_label": {"up": "📈 上升", "down": "📉 下降", "flat": "➡ 平稳"}.get(trend, ""),
            "confidence": "medium",
        }

    # ── 周报 ────────────────────────────────────────────

    def weekly_report(self) -> WeeklyReport:
        """生成周报"""
        if len(self.data) < 7:
            return WeeklyReport(start_date="", end_date="", summary="数据不足，无法生成周报")

        week_data = self.data[-7:]
        prior_week = self.data[-14:-7] if len(self.data) >= 14 else []

        total_revenue = sum(d.revenue for d in week_data)
        total_profit = sum(d.profit for d in week_data)
        total_orders = sum(d.orders for d in week_data)
        avg_margin = statistics.mean(d.profit_margin for d in week_data)

        # 环比
        if prior_week:
            prior_revenue = sum(d.revenue for d in prior_week)
            wow = round((total_revenue - prior_revenue) / prior_revenue * 100, 1) if prior_revenue > 0 else 0
        else:
            wow = 0

        # 异常
        alerts = self.check_alerts()

        # 趋势预测
        forecast = self.forecast("revenue", 7)

        # LLM 生成总结
        summary = self._llm_summary(week_data, total_revenue, total_profit, alerts, forecast)

        report = WeeklyReport(
            start_date=week_data[0].date,
            end_date=week_data[-1].date,
            metrics=week_data,
            alerts=alerts,
            summary=summary,
            total_revenue=round(total_revenue, 2),
            total_profit=round(total_profit, 2),
            total_orders=total_orders,
            avg_margin=round(avg_margin, 1),
            week_over_week=wow,
        )

        self.log(f"周报生成完成: {report.start_date} ~ {report.end_date}")
        return report

    def _llm_summary(self, week_data, total_revenue, total_profit, alerts, forecast) -> str:
        """用 LLM 生成周报总结"""
        data_summary = f"""
本周营收: ¥{total_revenue:.2f} | 利润: ¥{total_profit:.2f}
日均订单: {statistics.mean(d.orders for d in week_data):.0f}
趋势: {forecast.get('trend_label', '')}
异常: {len(alerts)} 个
"""
        prompt = f"请根据以下电商数据，用3-4句话总结本周表现，指出亮点和需要关注的问题:\n{data_summary}"
        resp = self.llm.chat(prompt)
        return resp.content.strip() or f"本周营收 ¥{total_revenue:.2f}，共 {sum(d.orders for d in week_data)} 单，利润率 {statistics.mean(d.profit_margin for d in week_data):.1f}%。"

    def export_weekly_report_md(self) -> str:
        """导出周报为 Markdown"""
        report = self.weekly_report()

        md = [
            f"# 📊 电商运营周报",
            f"**{report.start_date} ~ {report.end_date}**\n",
            f"## 📈 关键指标\n",
            f"| 指标 | 本周 | 环比 |",
            f"|---|---|---|",
            f"| 总营收 | ¥{report.total_revenue:,.2f} | {report.week_over_week:+.1f}% |",
            f"| 总利润 | ¥{report.total_profit:,.2f} | — |",
            f"| 总订单 | {report.total_orders} 单 | — |",
            f"| 平均利润率 | {report.avg_margin:.1f}% | — |",
            f"",
            f"## 🤖 AI 总结\n",
            f"{report.summary}\n",
        ]

        if report.alerts:
            md.append(f"## 🚨 异常告警\n")
            for a in report.alerts:
                icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.level, "")
                md.append(f"- {icon} **{a.title}**: {a.message}")

        # 每日明细
        md.append(f"\n## 📅 每日明细\n")
        md.append(f"| 日期 | 营收 | 订单 | 广告费 | 利润 | 利润率 |")
        md.append(f"|---|---|---|---|---|---|")
        for d in report.metrics:
            md.append(f"| {d.date} | ¥{d.revenue:.0f} | {d.orders} | ¥{d.ad_spend:.0f} | ¥{d.profit:.0f} | {d.profit_margin:.1f}% |")

        return "\n".join(md)

    def run(self, action: str = "report", **kwargs) -> Any:
        """统一入口"""
        if not self.data:
            self.load_data(mock=True)

        if action == "report" or action == "weekly":
            return self.weekly_report()
        elif action == "alerts" or action == "check":
            return self.check_alerts()
        elif action == "forecast":
            return self.forecast(kwargs.get("metric", "revenue"), kwargs.get("days", 7))
        elif action == "export":
            return self.export_weekly_report_md()
        else:
            return self.weekly_report()
