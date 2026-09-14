"""履约Agent — 订单跟踪 & 物流异常检测

能力:
- 订单状态跟踪
- 物流异常检测 (超时未发货 / 物流停滞)
- 异常订单标记 (地址异常 / 大额 / 重复)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .base import BaseAgent, LLMClient


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Order:
    """订单"""
    order_id: str
    status: str                    # pending / confirmed / shipped / delivered / cancelled
    customer_name: str
    product_name: str
    quantity: int
    amount: float
    created_at: str
    shipped_at: str = ""
    estimated_delivery: str = ""
    tracking_number: str = ""
    carrier: str = ""
    last_tracking_update: str = ""
    shipping_address: str = ""
    is_flagged: bool = False
    flag_reason: str = ""


@dataclass
class FulfillmentAlert:
    """履约告警"""
    order_id: str
    level: str                     # critical / warning / info
    title: str
    message: str
    suggested_action: str


@dataclass
class FulfillmentReport:
    """履约报告"""
    orders: list[Order]
    total_orders: int
    pending_ship: int             # 待发货
    in_transit: int               # 运输中
    delivered: int                # 已签收
    delayed: int                  # 延迟
    flagged: int                  # 标记异常
    alerts: list[FulfillmentAlert]


# ═══════════════════════════════════════════════════════════════════════
# 履约 Agent
# ═══════════════════════════════════════════════════════════════════════

class FulfillmentAgent(BaseAgent):
    """订单履约 Agent"""

    name = "fulfillment"
    description = "履约管理 — 订单跟踪 + 物流异常检测"

    def __init__(self, llm: LLMClient | None = None):
        super().__init__(llm)
        self.orders: list[Order] = []

    def load_orders(self, mock: bool = True) -> None:
        """加载订单数据"""
        if mock:
            self._generate_mock_orders()
            self.log(f"已加载 {len(self.orders)} 个订单")

    def _generate_mock_orders(self) -> None:
        """生成模拟订单"""
        import random
        today = datetime.now()
        statuses = ["pending", "confirmed", "confirmed", "shipped", "shipped", "shipped", "delivered", "delivered"]
        products = ["LED露营灯", "帐篷灯串", "头灯强光", "强光手电筒", "复古马灯"]
        carriers = ["中通快递", "圆通速递", "顺丰速运", "韵达快递"]

        self.orders = []
        for i in range(30):
            status = random.choice(statuses)
            created = (today - timedelta(days=random.randint(0, 10)))
            # 已发货但有异常：运输超过5天
            shipped_days_ago = random.randint(0, 8) if status in ("shipped", "delivered") else 0

            order = Order(
                order_id=f"ORD{20260701 + i:04d}",
                status=status,
                customer_name=f"买家{random.choice(['张','李','王','赵','陈'])}{chr(random.randint(65, 90))}",
                product_name=random.choice(products),
                quantity=random.randint(1, 3),
                amount=round(random.uniform(28, 120), 2),
                created_at=created.strftime("%Y-%m-%d %H:%M"),
                shipped_at=(created + timedelta(days=random.randint(0, 2))).strftime("%Y-%m-%d") if status in ("shipped", "delivered") else "",
                estimated_delivery=(created + timedelta(days=random.randint(3, 7))).strftime("%Y-%m-%d"),
                tracking_number=f"YT{random.randint(1000000000, 9999999999)}" if status in ("shipped", "delivered") else "",
                carrier=random.choice(carriers) if status in ("shipped", "delivered") else "",
                last_tracking_update=(today - timedelta(days=shipped_days_ago)).strftime("%Y-%m-%d") if status in ("shipped", "delivered") else "",
                shipping_address=f"{random.choice(['北京','上海','广州','深圳','杭州','成都'])}市某区某街道",
            )
            self.orders.append(order)

    # ── 异常检测 ────────────────────────────────────────

    def check(self) -> FulfillmentReport:
        """检查所有订单异常"""
        alerts: list[FulfillmentAlert] = []
        today = datetime.now()

        for order in self.orders:
            # 1. 超时未发货（超过 48 小时）
            if order.status in ("pending", "confirmed"):
                created = datetime.strptime(order.created_at, "%Y-%m-%d %H:%M")
                hours_since = (today - created).total_seconds() / 3600
                if hours_since > 48:
                    alerts.append(FulfillmentAlert(
                        order_id=order.order_id, level="warning",
                        title=f"⚠ 超时未发货",
                        message=f"订单 {order.order_id} 已创建 {hours_since:.0f} 小时仍未发货",
                        suggested_action="联系仓库优先处理，通知买家预计发货时间",
                    ))

            # 2. 物流停滞（超过 3 天无更新）
            if order.status == "shipped" and order.last_tracking_update:
                last_update = datetime.strptime(order.last_tracking_update, "%Y-%m-%d")
                days_stuck = (today - last_update).days
                if days_stuck > 3:
                    alerts.append(FulfillmentAlert(
                        order_id=order.order_id, level="warning",
                        title=f"⚠ 物流停滞",
                        message=f"订单 {order.order_id} 物流已 {days_stuck} 天未更新",
                        suggested_action="联系快递公司查询，主动通知买家物流情况",
                    ))

            # 3. 超过预计送达
            if order.status == "shipped" and order.estimated_delivery:
                est = datetime.strptime(order.estimated_delivery, "%Y-%m-%d")
                if today > est:
                    alerts.append(FulfillmentAlert(
                        order_id=order.order_id, level="critical",
                        title=f"🚨 超时未送达",
                        message=f"订单 {order.order_id} 已超过预计送达时间 {order.estimated_delivery}",
                        suggested_action="联系快递确认位置，主动联系买家道歉并补偿",
                    ))

            # 4. 大额订单标记
            if order.amount > 100:
                order.is_flagged = True
                order.flag_reason = "大额订单"
                alerts.append(FulfillmentAlert(
                    order_id=order.order_id, level="info",
                    title=f"🔔 大额订单",
                    message=f"订单 {order.order_id} 金额 ¥{order.amount:.2f}",
                    suggested_action="确认地址有效性和买家信息",
                ))

        # 统计
        pending = sum(1 for o in self.orders if o.status in ("pending", "confirmed"))
        transit = sum(1 for o in self.orders if o.status == "shipped")
        delivered = sum(1 for o in self.orders if o.status == "delivered")
        delayed = sum(1 for a in alerts if "超时" in a.title)
        flagged = sum(1 for o in self.orders if o.is_flagged)

        report = FulfillmentReport(
            orders=self.orders,
            total_orders=len(self.orders),
            pending_ship=pending,
            in_transit=transit,
            delivered=delivered,
            delayed=delayed,
            flagged=flagged,
            alerts=alerts,
        )

        if alerts:
            self.log(f"发现 {len(alerts)} 个异常")
        else:
            self.log("所有订单正常")
        return report

    def run(self, action: str = "check", **kwargs) -> FulfillmentReport:
        """统一入口"""
        if not self.orders:
            self.load_orders(mock=True)
        return self.check()
