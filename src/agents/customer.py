"""客服Agent — 智能客服 + RAG 知识库 + 意图路由 + 情感识别

四层处理:
1. FAQ RAG 匹配 → 覆盖 80% 常见问题
2. 意图识别 → 退货/议价/物流/技术/投诉
3. 情感识别 → 正常/焦虑/愤怒 → 自动升级
4. 回复生成 → LLM + 知识库上下文
"""

import json
import re
from dataclasses import dataclass, field

from ..knowledge import Retriever, KnowledgeStore
from .base import BaseAgent, LLMClient


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CustomerQuery:
    """客服查询"""
    message: str
    customer_name: str = ""
    order_id: str = ""
    language: str = "zh"


@dataclass
class CustomerResponse:
    """客服回复"""
    query: str
    answer: str = ""
    intent: str = "general"
    sentiment: str = "neutral"
    needs_human: bool = False
    escalation_reason: str = ""
    faq_match_score: float = 0.0
    faq_matched_question: str = ""
    suggested_actions: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# 意图 & 情感词典
# ═══════════════════════════════════════════════════════════════════════

INTENT_PATTERNS = {
    "退货退款": ["退货", "退款", "退钱", "不想要", "七天无理由", "return", "refund", "取消订单"],
    "物流查询": ["发货", "物流", "快递", "到哪", "还没收到", "什么时候到", "tracking", "运输"],
    "产品质量": ["坏了", "破损", "瑕疵", "质量", "不好用", "不能用", "有问题", "故障", "defect"],
    "议价砍价": ["便宜", "优惠", "打折", "贵了", "最低价", "砍价", "discount", "coupon"],
    "尺码规格": ["尺寸", "大小", "颜色", "规格", "型号", "多长", "多重", "size", "color"],
    "使用教程": ["怎么用", "说明书", "安装", "设置", "配对", "连接", "how to", "manual"],
    "售后保修": ["保修", "维修", "质保", "坏了怎么办", "换货", "warranty", "repair"],
    "投诉不满": ["投诉", "差评", "举报", "欺骗", "假的", "complaint", "fake", "scam"],
}

SENTIMENT_WORDS = {
    "negative": ["差", "烂", "坑", "骗子", "垃圾", "无语", "失望", "恶心", "投诉", "退款",
                 "退货", "差评", "坑爹", "假", "骗", "投诉", "315", "曝光"],
    "angry": ["气死", "怒了", "操", "草", "妈的", "tm", "tmd", "垃圾公司", "坑人",
              "投诉到底", "差评", "曝光", "退款不退", "什么玩意"],
    "anxious": ["着急", "急", "快", "赶紧", "马上", "还没", "什么时候", "等不了",
                "明天就要", "urgent", "asap", "快点"],
    "positive": ["好", "棒", "赞", "喜欢", "满意", "不错", "推荐", "好评", "nice", "good"],
}


# ═══════════════════════════════════════════════════════════════════════
# 客服 Agent
# ═══════════════════════════════════════════════════════════════════════

class CustomerAgent(BaseAgent):
    """智能客服 Agent"""

    name = "customer"
    description = "智能客服 — FAQ 匹配 + 意图路由 + 情感识别 + LLM 回复"

    def __init__(
        self,
        llm: LLMClient | None = None,
        retriever: Retriever | None = None,
        escalation_sentiments: list[str] | None = None,
    ):
        super().__init__(llm)
        self.retriever = retriever or Retriever()
        self.escalation_sentiments = escalation_sentiments or ["angry", "negative"]

        # 如果没有加载 FAQ，加载默认的示例 FAQ
        if len(self.retriever) == 0:
            self._load_default_faqs()

    def _load_default_faqs(self) -> None:
        """加载默认 FAQ（通用电商客服）"""
        default_faqs = [
            {"question": "什么时候发货？", "answer": "下单后48小时内发货，节假日顺延。发货后会短信通知您物流单号。", "tags": ["物流", "发货"]},
            {"question": "怎么退货？", "answer": "支持7天无理由退货。请在订单页面点击「申请退货」，填写原因后提交，审核通过后会短信通知您退货地址。", "tags": ["退货", "售后"]},
            {"question": "退款什么时候到账？", "answer": "仓库签收退货后1-3个工作日处理退款，退款将原路返回您的支付账户。", "tags": ["退款", "售后"]},
            {"question": "可以开发票吗？", "answer": "可以开具电子发票。下单时在备注栏填写发票抬头和税号，或收货后联系客服补开。", "tags": ["发票"]},
            {"question": "发什么快递？", "answer": "默认发中通/圆通，可联系客服补差价发顺丰。偏远地区可能需加收运费。", "tags": ["物流", "快递"]},
            {"question": "收到是坏的怎么办？", "answer": "非常抱歉！请在签收24小时内拍照联系客服，我们会为您安排换货或退款，无需退回损坏商品。", "tags": ["售后", "质量"]},
            {"question": "怎么联系人工客服？", "answer": "我是智能客服小助手。如果需要人工客服，请在工作日9:00-18:00回复「转人工」，或拨打400客服热线。", "tags": ["人工"]},
            {"question": "有优惠券吗？", "answer": "新用户首单可享9折优惠。关注店铺可领取满减券，大促期间还有限时优惠活动哦。", "tags": ["优惠", "促销"]},
            {"question": "支持货到付款吗？", "answer": "部分地区支持货到付款。下单时选择「货到付款」即可，如无法选择则说明您所在地区暂不支持。", "tags": ["支付"]},
            {"question": "怎么修改收货地址？", "answer": "未发货订单可在订单详情页直接修改地址。已发货订单请联系客服拦截或联系快递公司改派。", "tags": ["订单", "地址"]},
        ]
        self.retriever.store.add_bulk_faqs(default_faqs)
        self.log(f"已加载 {len(default_faqs)} 条默认 FAQ")

    def run(self, query: str | CustomerQuery, **kwargs) -> CustomerResponse:
        """处理客服查询

        Args:
            query: 买家消息文本 或 CustomerQuery 对象

        Returns:
            CustomerResponse 含回复和元数据
        """
        if isinstance(query, CustomerQuery):
            cq = query
        else:
            cq = CustomerQuery(message=query)

        message = cq.message.strip()
        if not message:
            return CustomerResponse(query=message, answer="请描述您的问题，我会尽力帮您解答。", intent="unknown")

        resp = CustomerResponse(query=message)

        # Layer 1: 意图识别
        resp.intent = self._detect_intent(message)
        self.log(f"意图: {resp.intent}")

        # Layer 2: 情感识别
        resp.sentiment = self._detect_sentiment(message)
        self.log(f"情感: {resp.sentiment}")

        # Layer 3: FAQ 匹配
        faq_result = self.retriever.ask(message)
        if faq_result:
            resp.faq_match_score = faq_result["score"]
            resp.faq_matched_question = faq_result["question"]
            self.log(f"FAQ 匹配: {faq_result['question'][:40]}... ({faq_result['score']:.2f})")

            # 高置信度直接用 FAQ
            if faq_result["score"] >= 0.6:
                resp.answer = faq_result["answer"]
                resp.needs_human = False
                return resp

            # 中等置信度: FAQ + 上下文给 LLM 增强
            if faq_result["score"] >= 0.25:
                resp.answer = self._llm_augment(message, faq_result)
                resp.needs_human = False
                return resp

        # Layer 4: LLM 自由回复
        resp.answer = self._llm_reply(message, resp.intent, resp.sentiment)

        # Layer 5: 是否需要升级人工
        if resp.sentiment in self.escalation_sentiments:
            resp.needs_human = True
            resp.escalation_reason = f"检测到{resp.sentiment}情绪，建议人工跟进"
            resp.suggested_actions = ["转人工客服", "优先处理", "电话回访"]
        elif resp.intent == "投诉不满":
            resp.needs_human = True
            resp.escalation_reason = "投诉类问题，建议人工处理"
            resp.suggested_actions = ["升级主管", "电话回访"]

        return resp

    # ── 意图识别 ──────────────────────────────────────────

    def _detect_intent(self, message: str) -> str:
        """关键词 + 规则 意图识别"""
        msg_lower = message.lower()
        scores: dict[str, int] = {}

        for intent, keywords in INTENT_PATTERNS.items():
            scores[intent] = sum(1 for kw in keywords if kw in msg_lower)

        if not scores or max(scores.values()) == 0:
            return "一般咨询"

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        return best if scores[best] > 0 else "一般咨询"

    # ── 情感识别 ──────────────────────────────────────────

    def _detect_sentiment(self, message: str) -> str:
        """关键词情感分析"""
        msg_lower = message.lower()
        scores = {}

        for sentiment, words in SENTIMENT_WORDS.items():
            scores[sentiment] = sum(1 for w in words if w in msg_lower)

        if not scores or max(scores.values()) == 0:
            return "neutral"

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        return best if scores[best] > 0 else "neutral"

    # ── LLM 回复 ──────────────────────────────────────────

    def _llm_augment(self, message: str, faq: dict) -> str:
        """FAQ + LLM 增强回复"""
        prompt = f"""买家问题: {message}

匹配到的 FAQ:
Q: {faq['question']}
A: {faq['answer']}

请基于 FAQ 内容，用客服的语气生成一段友好、专业的回复。可以适当补充细节。控制在 100 字以内。"""
        resp = self.llm.chat(prompt)
        return resp.content.strip() or faq["answer"]

    def _llm_reply(self, message: str, intent: str, sentiment: str) -> str:
        """LLM 自由回复"""
        esc = "请特别注意买家情绪，语气要安抚和诚恳。" if sentiment in ["angry", "negative"] else ""
        prompt = f"""你是一个电商客服助手。买家问题: {message}

识别意图: {intent} | 情绪: {sentiment}
{esc}

请生成一段友好、专业的客服回复。控制在 80 字以内。"""
        resp = self.llm.chat(prompt)
        return resp.content.strip() or "感谢您的咨询，我们会尽快为您处理。如需帮助请随时联系我们。"

    def export_faqs(self, path: str) -> None:
        """导出 FAQ 知识库"""
        self.retriever.store.save(path)
        self.log(f"FAQ 已导出到 {path}")

    def import_faqs(self, path: str) -> None:
        """导入 FAQ 知识库"""
        self.retriever.load_faqs(path)
        self.log(f"FAQ 已导入，共 {len(self.retriever)} 条")
