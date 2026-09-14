"""内容Agent — AI 驱动的电商 Listing 生成

能力:
- 标题生成 (SEO关键词植入, 多版本)
- 五点描述 / 产品卖点
- A+ 页面文案
- 搜索词 / 后台关键词
- 多语言本地化 (英文→日/德/西/法)
- 多角度 A/B 版本 (性价比/品质/场景/功能/情感)
"""

import json
from dataclasses import dataclass, field

from .base import BaseAgent, LLMClient, LLMResponse


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ListingContent:
    """一份完整 Listing"""
    angle: str = ""                         # 卖点角度
    title: str = ""                         # 标题
    bullets: list[str] = field(default_factory=list)  # 五点描述
    description: str = ""                   # A+ 描述
    search_terms: list[str] = field(default_factory=list)  # 后台搜索词
    language: str = "zh"                    # 语言代码


@dataclass
class ContentResult:
    """内容生成结果"""
    product_name: str
    price: float
    features: list[str]
    listings: list[ListingContent] = field(default_factory=list)
    translations: dict[str, list[ListingContent]] = field(default_factory=dict)
    raw_responses: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

LISTING_SYSTEM_PROMPT = """你是一个专业的亚马逊/电商 Listing 文案专家。你的任务是生成高质量的电商 Listing。

规则:
1. 标题控制在 150-200 字符，自然植入核心关键词
2. 五点描述(bullet points)每条 200 字符以内，突出卖点
3. 搜索词用逗号分隔，不要重复标题中已有的词
4. 根据不同角度产生差异化的文案
5. 请只返回 JSON 格式，不要包含其他文字

返回格式:
{
  "title": "标题文本",
  "bullets": ["卖点1", "卖点2", "卖点3", "卖点4", "卖点5"],
  "description": "A+ 页面长描述",
  "search_terms": ["词1", "词2", "词3", ...]
}"""


TRANSLATION_PROMPT = """将以下电商 Listing 翻译为 {language}，保持卖点语气，适应当地表达习惯。

原始标题: {title}
原始卖点:
{bullets}

请只返回 JSON:
{{
  "title": "翻译后标题",
  "bullets": ["翻译后卖点1", "翻译后卖点2"],
  "search_terms": ["本地化搜索词1", "本地化搜索词2"]
}}"""


# ═══════════════════════════════════════════════════════════════════════
# 内容 Agent
# ═══════════════════════════════════════════════════════════════════════

class ContentAgent(BaseAgent):
    """AI 内容生成 Agent"""

    name = "content"
    description = "电商 Listing 文案生成 & 多语言本地化"

    # 不同卖点角度预设
    ANGLES = {
        "性价比": "突出价格优势和功能齐全，强调「花小钱办大事」",
        "品质": "突出材质、工艺、耐用性，强调「一分钱一分货」",
        "场景": "突出使用场景和体验感，强调「提升生活品质」",
        "功能": "突出技术参数和黑科技，强调「性能强悍」",
        "情感": "突出送礼属性、情感价值，强调「关怀/品味」",
    }

    # 支持的语言
    LANGUAGES = {
        "en": "英语",
        "ja": "日语",
        "de": "德语",
        "es": "西班牙语",
        "fr": "法语",
        "ko": "韩语",
    }

    def __init__(self, llm: LLMClient | None = None):
        super().__init__(llm)
        self.default_angles = ["性价比", "品质", "场景"]

    def run(
        self,
        product: str,
        price: float = 0,
        features: list[str] | str | None = None,
        angles: list[str] | None = None,
        languages: list[str] | None = None,
        num_variants: int = 3,
    ) -> ContentResult:
        """主入口

        Args:
            product: 商品名称
            price: 售价
            features: 商品特性列表 或 逗号分隔字符串
            angles: 卖点角度，默认 ['性价比','品质','场景']
            languages: 要翻译的目标语言，默认 ['en']
            num_variants: 每个角度生成的版本数

        Returns:
            ContentResult 含所有生成内容
        """
        if isinstance(features, str):
            features = [f.strip() for f in features.split(",") if f.strip()]
        features = features or []
        angles = angles or self.default_angles
        languages = languages or ["en"]

        result = ContentResult(
            product_name=product,
            price=price,
            features=features,
        )

        self.log(f"🎯 开始生成 Listing: {product}")
        self.log(f"   售价: ¥{price} | 特性: {', '.join(features[:5])}")
        self.log(f"   角度: {', '.join(angles)} | 目标语言: {', '.join(languages)}")

        # 1. 生成各角度 Listing
        for angle in angles[:num_variants]:
            self.log(f"  📝 生成角度: {angle}")
            listing = self._generate_listing(product, price, features, angle)
            if listing:
                result.listings.append(listing)

        # 2. 多语言翻译
        if result.listings and languages:
            self.log(f"  🌐 多语言翻译...")
            best = result.listings[0]  # 用第一个角度做翻译
            for lang in languages:
                if lang == "zh":
                    continue
                translated = self._translate(best, lang)
                if translated:
                    result.translations[lang] = [translated]

        self.log(f"  ✅ 完成: {len(result.listings)} 个版本, {len(result.translations)} 种语言")
        return result

    def _generate_listing(
        self,
        product: str,
        price: float,
        features: list[str],
        angle: str,
    ) -> ListingContent | None:
        """生成一个角度的 Listing"""
        angle_desc = self.ANGLES.get(angle, angle)
        features_text = "\n".join(f"- {f}" for f in features)

        prompt = f"""请为以下商品生成 Listing:

商品: {product}
售价: ¥{price}
特性:
{features_text}

卖点角度: {angle} — {angle_desc}

请从这个角度切入，生成差异化的标题、五点描述、A+描述和搜索词。"""

        try:
            data = self.llm.chat_json(prompt, system=LISTING_SYSTEM_PROMPT)
            if "parse_error" in data:
                self.log(f"    ⚠ JSON 解析失败，使用文本提取")
                return self._fallback_parse(data.get("raw", ""), angle)

            return ListingContent(
                angle=angle,
                title=data.get("title", ""),
                bullets=data.get("bullets", []),
                description=data.get("description", ""),
                search_terms=data.get("search_terms", []),
                language="zh",
            )
        except Exception as e:
            self.log(f"    ✗ 生成失败: {e}")
            return None

    def _translate(self, listing: ListingContent, target_lang: str) -> ListingContent | None:
        """翻译 Listing 到目标语言"""
        lang_name = self.LANGUAGES.get(target_lang, target_lang)

        prompt = TRANSLATION_PROMPT.format(
            language=lang_name,
            title=listing.title,
            bullets="\n".join(f"- {b}" for b in listing.bullets),
        )

        try:
            data = self.llm.chat_json(prompt)
            if "parse_error" in data:
                return None
            return ListingContent(
                angle=listing.angle,
                title=data.get("title", ""),
                bullets=data.get("bullets", []),
                search_terms=data.get("search_terms", []),
                language=target_lang,
            )
        except Exception:
            return None

    def _fallback_parse(self, raw_text: str, angle: str) -> ListingContent:
        """当 LLM 返回非 JSON 时的降级解析"""
        lines = raw_text.strip().split("\n")
        title = lines[0] if lines else raw_text[:100]

        bullets = []
        for line in lines[1:]:
            line = line.strip().lstrip("-•·*12345. ①②③④⑤")
            if line and len(line) > 5:
                bullets.append(line)
            if len(bullets) >= 5:
                break

        return ListingContent(
            angle=angle,
            title=title,
            bullets=bullets or ["请设置 API Key 以获取完整文案"],
            description=raw_text,
            search_terms=[],
            language="zh",
        )

    def export_markdown(self, result: ContentResult) -> str:
        """导出为 Markdown 格式"""
        md = [f"# {result.product_name} — Listing 文案\n"]
        md.append(f"售价: ¥{result.price}  |  特性: {', '.join(result.features[:5])}\n")

        for listing in result.listings:
            md.append(f"## 版本: {listing.angle} ({listing.language})\n")
            md.append(f"### 标题\n{listing.title}\n")
            md.append(f"### 五点描述\n")
            for i, b in enumerate(listing.bullets, 1):
                md.append(f"{i}. {b}")
            md.append(f"\n### A+ 描述\n{listing.description}\n")
            md.append(f"### 搜索词\n{', '.join(listing.search_terms)}\n")
            md.append("---\n")

        for lang, listings in result.translations.items():
            lang_name = self.LANGUAGES.get(lang, lang)
            for listing in listings:
                md.append(f"## 翻译: {lang_name}\n")
                md.append(f"### 标题\n{listing.title}\n")
                md.append(f"### 卖点\n")
                for b in listing.bullets:
                    md.append(f"- {b}")
                md.append("\n---\n")

        return "\n".join(md)
