"""评价Agent — 评论管理 & 情感分析 & 差评挽回

能力:
- 评论情感分析 (正面/中性/负面)
- 差评实时告警
- 好评回复模板
- 差评挽回话术生成
"""

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .base import BaseAgent, LLMClient


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Review:
    """评价"""
    review_id: str
    product_name: str
    customer_name: str
    rating: int                   # 1-5 星
    title: str
    content: str
    images: list[str] = field(default_factory=list)
    created_at: str = ""
    sentiment: str = ""           # positive / neutral / negative
    sentiment_score: float = 0.0  # -1 ~ 1
    replied: bool = False
    reply_content: str = ""


@dataclass
class ReviewAlert:
    """差评告警"""
    review: Review
    level: str                    # critical / warning
    title: str
    message: str
    suggested_reply: str


@dataclass
class ReviewReport:
    """评价报告"""
    reviews: list[Review]
    total: int
    avg_rating: float
    positive_count: int
    neutral_count: int
    negative_count: int
    alerts: list[ReviewAlert]
    negative_trend: str           # 差评趋势描述
    recommendations: str


# ═══════════════════════════════════════════════════════════════════════
# 情感词典
# ═══════════════════════════════════════════════════════════════════════

POSITIVE_WORDS = {
    "好", "棒", "赞", "满意", "喜欢", "不错", "推荐", "好评", "完美", "nice",
    "good", "great", "excellent", "物美价廉", "超值", "神器", "惊喜", "好用的",
    "质量不错", "性价比高", "值得", "给力", "良心", "做工好", "漂亮", "实用",
    "方便", "舒服", "耐用", "质感", "精准",
}

NEGATIVE_WORDS = {
    "差", "烂", "不好", "失望", "退货", "退款", "垃圾", "坑", "骗",
    "坏", "破", "瑕疵", "故障", "问题", "无语", "后悔", "不值",
    "味道大", "噪音", "发热", "掉色", "掉漆", "不亮", "漏水",
    "坏了", "不能用", "不好用", "难用", "鸡肋", "智商税",
    "太差", "极差", "垃圾货", "千万别买",
}


# ═══════════════════════════════════════════════════════════════════════
# 评价 Agent
# ═══════════════════════════════════════════════════════════════════════

class ReviewAgent(BaseAgent):
    """评价管理 Agent"""

    name = "review"
    description = "评价管理 — 情感分析 + 差评告警 + 回复话术"

    def __init__(self, llm: LLMClient | None = None):
        super().__init__(llm)
        self.reviews: list[Review] = []

    def load_reviews(self, mock: bool = True) -> None:
        """加载评价数据"""
        if mock:
            self._generate_mock_reviews()
            self.log(f"已加载 {len(self.reviews)} 条评价")

    def _generate_mock_reviews(self) -> None:
        """生成模拟评价"""
        import random
        today = datetime.now()

        mock_reviews = [
            (5, "质量很好，亮度超乎预期", "露营用了一次，续航很给力，晚上照明完全够用，推荐购买！"),
            (5, "性价比很高", "比实体店便宜不少，质量一样的，已经推荐给朋友了"),
            (4, "还不错", "整体满意，就是充电口有点紧，其他都挺好"),
            (3, "一般般", "亮度还行，但是做工感觉一般，有点塑料感"),
            (2, "不太满意", "用了两次就充不进电了，联系客服中"),
            (1, "太差了", "收到的灯根本不亮，退货退款！浪费我时间"),
            (5, "非常满意", "物流快，包装好，产品更好，会回购"),
            (4, "挺好用的", "大小合适，挂在帐篷里正好"),
            (1, "质量有问题", "外壳有划痕，感觉是二手的，要求换货"),
            (5, "二次购买", "第二次买了，送朋友的，两个颜色都好看"),
            (3, "凑合用", "价格便宜，也不能要求太多"),
            (2, "灯珠有一颗不亮", "收到就有一颗不亮的，虽然不影响使用但心里不舒服"),
        ]

        self.reviews = []
        for i, (rating, title, content) in enumerate(mock_reviews):
            created = today - timedelta(days=random.randint(0, 14))
            self.reviews.append(Review(
                review_id=f"RV{i+1:04d}",
                product_name=random.choice(["LED露营灯", "帐篷灯串", "头灯强光", "复古马灯"]),
                customer_name=f"***{random.choice('abcdefgh')}",
                rating=rating,
                title=title,
                content=content,
                created_at=created.strftime("%Y-%m-%d %H:%M"),
            ))

    # ── 情感分析 ────────────────────────────────────────

    def analyze_sentiment(self, review: Review) -> tuple[str, float]:
        """简易情感分析

        返回: (sentiment_label, score)  分数 -1(完全负面) ~ +1(完全正面)
        """
        text = review.title + " " + review.content
        pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
        neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)

        if review.rating <= 2:
            neg_count += 3  # 低评分加重负面权重
        elif review.rating >= 4:
            pos_count += 3

        total = pos_count + neg_count
        if total == 0:
            return ("neutral", 0.0)

        score = round((pos_count - neg_count) / max(pos_count, neg_count, 5), 2)
        score = max(-1.0, min(1.0, score))

        if score > 0.2:
            return ("positive", score)
        elif score < -0.2:
            return ("negative", score)
        else:
            return ("neutral", score)

    # ── 回复生成 ────────────────────────────────────────

    def generate_reply(self, review: Review) -> str:
        """为评价生成回复"""
        sentiment, _ = self.analyze_sentiment(review)

        if sentiment == "negative":
            prompt = f"""你是一个电商客服。请为以下差评生成一段诚恳的回复，需要:
1. 真诚道歉
2. 提出解决方案（退换货/退款/补偿）
3. 留下联系方式或引导联系客服

差评: {review.rating}星 | {review.title} | {review.content}

请写一段100字以内的回复:"""
            resp = self.llm.chat(prompt)
            return resp.content.strip()

        elif sentiment == "neutral":
            return f"感谢您的反馈！我们一直在努力改进产品质量。如有任何问题，欢迎随时联系我们的客服团队。"

        else:
            templates = [
                f"感谢您的好评！很高兴我们的{review.product_name}能让您满意。我们会继续努力提供优质产品和服务，期待您的再次光临！",
                f"看到您满意的评价我们非常开心！感谢您选择我们的{review.product_name}，祝您使用愉快！",
            ]
            import random
            return random.choice(templates)

    # ── 核心分析 ────────────────────────────────────────

    def analyze(self) -> ReviewReport:
        """分析所有评价"""
        alerts: list[ReviewAlert] = []

        for review in self.reviews:
            sentiment, score = self.analyze_sentiment(review)
            review.sentiment = sentiment
            review.sentiment_score = score

            # 差评告警
            if review.rating <= 2 and not review.replied:
                suggested_reply = self.generate_reply(review)
                alerts.append(ReviewAlert(
                    review=review,
                    level="critical" if review.rating == 1 else "warning",
                    title=f"{'🚨' if review.rating == 1 else '⚠'} {review.rating}星差评: {review.product_name}",
                    message=f"{review.customer_name}: {review.title} — {review.content[:60]}...",
                    suggested_reply=suggested_reply,
                ))

        # 统计
        pos = sum(1 for r in self.reviews if r.sentiment == "positive")
        neu = sum(1 for r in self.reviews if r.sentiment == "neutral")
        neg = sum(1 for r in self.reviews if r.sentiment == "negative")
        avg_rating = round(sum(r.rating for r in self.reviews) / len(self.reviews), 1) if self.reviews else 0

        # 差评趋势
        if neg >= 3:
            trend = "⚠ 近期差评较多，建议排查产品质量或物流问题"
        elif neg >= 1:
            trend = "有少量差评，保持关注"
        else:
            trend = "近期无明显差评"

        recs = []
        if neg > 0:
            recs.append("对差评用户主动联系并解决问题，争取改评")
        if avg_rating < 4.0:
            recs.append("整体评分偏低，建议优化产品质量或客服体验")
        if pos > neg * 2:
            recs.append("好评率良好，可引导满意用户晒图评价")

        self.log(f"评分 {avg_rating}/5 | 好评{pos} 中评{neu} 差评{neg} | {len(alerts)} 个告警")

        return ReviewReport(
            reviews=self.reviews,
            total=len(self.reviews),
            avg_rating=avg_rating,
            positive_count=pos,
            neutral_count=neu,
            negative_count=neg,
            alerts=alerts,
            negative_trend=trend,
            recommendations="; ".join(recs),
        )

    def reply_to_all_negative(self) -> list[dict]:
        """为所有未回复的差评生成回复"""
        result = []
        for r in self.reviews:
            if r.rating <= 2 and not r.replied:
                reply = self.generate_reply(r)
                r.reply_content = reply
                r.replied = True
                result.append({"review_id": r.review_id, "reply": reply})
                self.log(f"已生成回复: {r.review_id}")
        return result

    def run(self, action: str = "analyze", **kwargs) -> ReviewReport | list[dict]:
        """统一入口"""
        if not self.reviews:
            self.load_reviews(mock=True)

        if action == "analyze":
            return self.analyze()
        elif action == "reply":
            return self.reply_to_all_negative()
        else:
            return self.analyze()
