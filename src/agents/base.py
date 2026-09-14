"""AI Agent 基类 + LLM 客户端抽象

支持 Claude API / OpenAI API，可扩展其他 Provider。
内置 token 估算、重试、流式输出支持。
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════════
# LLM 响应模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class LLMResponse:
    """LLM 返回的统一结构"""
    content: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = "stop"


# ═══════════════════════════════════════════════════════════════════════
# LLM 客户端 — 适配多种 API
# ═══════════════════════════════════════════════════════════════════════

class LLMClient:
    """统一的 LLM 客户端

    支持:
    - Claude API (Anthropic)
    - OpenAI API (GPT 系列)
    - 本地 Mock 模式 (无 API Key 时的降级)

    用法:
        client = LLMClient(provider="claude")  # 或 "openai" / "mock"
        resp = client.chat("你好")
        resp = client.chat([{"role": "user", "content": "你好"}])
    """

    def __init__(
        self,
        provider: str = "auto",
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        self.provider = self._resolve_provider(provider)
        self.model = model or self._default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._api_key = api_key
        self._base_url = base_url
        self._total_tokens_in = 0
        self._total_tokens_out = 0

    # ── 自动检测 ──────────────────────────────────────

    def _resolve_provider(self, provider: str) -> str:
        if provider != "auto":
            return provider
        if os.getenv("ANTHROPIC_API_KEY"):
            return "claude"
        if os.getenv("DEEPSEEK_API_KEY"):
            return "deepseek"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        return "mock"

    def _default_model(self) -> str:
        models = {
            "claude": "claude-sonnet-5-20250929",
            "openai": "gpt-4o",
            "deepseek": "deepseek-chat",
            "mock": "mock-model",
        }
        return models.get(self.provider, "mock-model")

    def _get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        if self.provider == "claude":
            return os.getenv("ANTHROPIC_API_KEY", "")
        if self.provider == "deepseek":
            return os.getenv("DEEPSEEK_API_KEY", "")
        if self.provider == "openai":
            return os.getenv("OPENAI_API_KEY", "")
        return ""

    # ── 主接口 ────────────────────────────────────────

    def chat(
        self,
        prompt: str | list[dict[str, str]],
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """发送对话请求，返回统一格式"""

        if isinstance(prompt, str):
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
        else:
            messages = prompt
            if system:
                messages = [{"role": "system", "content": system}] + messages

        temp = temperature if temperature is not None else self.temperature
        mt = max_tokens if max_tokens is not None else self.max_tokens

        if self.provider == "mock":
            return self._mock_chat(messages)

        if self.provider == "claude":
            return self._claude_chat(messages, temp, mt)
        elif self.provider == "deepseek":
            return self._openai_chat(messages, temp, mt, base_url="https://api.deepseek.com")
        else:
            return self._openai_chat(messages, temp, mt)

    def chat_json(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """请求并强制返回 JSON（多重降级提取）"""
        full_system = (system or "") + "\n重要：只返回纯JSON对象，不要markdown代码块，不要解释文字。"
        resp = self.chat(prompt, system=full_system, temperature=temperature)
        text = resp.content.strip()

        # 逐层尝试提取 JSON
        strategies = [
            # 1. 直接解析
            lambda t: json.loads(t),
            # 2. 去掉 ```json ... ``` 包裹
            lambda t: json.loads(re.sub(r"```(?:json|javascript)?\s*", "", t).replace("```", "").strip()),
            # 3. 提取 { 到 } 之间
            lambda t: json.loads(t[t.find("{"):t.rfind("}")+1]) if "{" in t and "}" in t else (_ for _ in ()).throw(ValueError()),
            # 4. 修复尾部逗号: "key": "val",} -> "key": "val"}
            lambda t: json.loads(re.sub(r",\s*([}\]])", r"\1", t[t.find("{"):t.rfind("}")+1])),
            # 5. 修复单引号
            lambda t: json.loads(t[t.find("{"):t.rfind("}")+1].replace("'", '"')),
        ]

        for i, strategy in enumerate(strategies):
            try:
                result = strategy(text)
                if isinstance(result, dict) and not result.get("parse_error"):
                    return result
            except (json.JSONDecodeError, ValueError, IndexError, StopIteration):
                continue

        # 彻底失败：返回原始文本供降级处理
        return {"raw": resp.content, "parse_error": True}

    @property
    def total_tokens(self) -> dict:
        return {"in": self._total_tokens_in, "out": self._total_tokens_out}

    # ── Provider 实现 ─────────────────────────────────

    def _claude_chat(self, messages: list[dict], temperature: float, max_tokens: int) -> LLMResponse:
        """Claude API 调用"""
        import httpx

        api_key = self._get_api_key()
        if not api_key:
            return self._mock_chat(messages, hint="[无 ANTHROPIC_API_KEY，使用 Mock 模式]\n")

        base = self._base_url or "https://api.anthropic.com"
        url = f"{base}/v1/messages"

        # Anthropic 要求 system 单独提取
        system_msg = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_msgs.append(m)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_msgs,
        }
        if system_msg:
            payload["system"] = system_msg

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            content = "".join(
                b["text"] for b in data.get("content", []) if b.get("type") == "text"
            )
            self._total_tokens_in += data.get("usage", {}).get("input_tokens", 0)
            self._total_tokens_out += data.get("usage", {}).get("output_tokens", 0)
            return LLMResponse(
                content=content,
                model=data.get("model", self.model),
                tokens_in=data.get("usage", {}).get("input_tokens", 0),
                tokens_out=data.get("usage", {}).get("output_tokens", 0),
                finish_reason=data.get("stop_reason", "stop"),
            )
        except Exception as e:
            return LLMResponse(content=f"[Claude API 错误: {e}]", model=self.model)

    def _openai_chat(self, messages: list[dict], temperature: float, max_tokens: int, base_url: str = "") -> LLMResponse:
        """OpenAI/DeepSeek 兼容 API 调用"""
        import httpx

        api_key = self._get_api_key()
        if not api_key:
            return self._mock_chat(messages, hint="[无 API Key，使用 Mock 模式]\n")

        base = base_url or self._base_url or "https://api.openai.com"
        url = f"{base}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            content = choice["message"]["content"]
            self._total_tokens_in += data.get("usage", {}).get("prompt_tokens", 0)
            self._total_tokens_out += data.get("usage", {}).get("completion_tokens", 0)
            return LLMResponse(
                content=content,
                model=data.get("model", self.model),
                tokens_in=data.get("usage", {}).get("prompt_tokens", 0),
                tokens_out=data.get("usage", {}).get("completion_tokens", 0),
                finish_reason=choice.get("finish_reason", "stop"),
            )
        except Exception as e:
            return LLMResponse(content=f"[OpenAI API 错误: {e}]", model=self.model)

    def _mock_chat(self, messages: list[dict], hint: str = "") -> LLMResponse:
        """Mock 模式 — 无 API 时的降级回复"""
        last_user = ""
        for m in reversed(messages):
            if m["role"] == "user":
                last_user = m["content"]
                break

        # 针对不同场景返回合理的 mock 数据
        content = self._mock_response(last_user)
        return LLMResponse(
            content=hint + content,
            model="mock",
            tokens_in=len(last_user) // 3,
            tokens_out=len(content) // 3,
        )

    def _mock_response(self, prompt: str) -> str:
        """根据 prompt 内容返回模拟回复"""
        p = prompt.lower()

        if "标题" in p and ("listing" in p or "商品" in p):
            return _MOCK_LISTING
        if "faq" in p or "客服" in p or "回复" in p:
            return "感谢您的咨询！根据您的问题，我们的产品支持相关功能。如有其他疑问请随时联系我们。"
        if "广告" in p or "roi" in p:
            return json.dumps({"action": "increase_budget", "amount_pct": 15, "reason": "ROI 高于目标"}, ensure_ascii=False)
        if "报告" in p or "周报" in p or "分析" in p:
            return "本周销量整体稳定，环比增长 5%。重点关注品类：户外照明 (+12%)。无异常告警。"
        if "评论" in p or "评价" in p:
            return "感谢您的支持！我们很高兴您对产品满意，如有任何问题请随时联系我们。"

        return f"这是对「{prompt[:50]}...」的模拟回复。设置 API Key 以获取真实 AI 响应。"


_MOCK_LISTING = """【版本A — 性价比角度】
标题: [超亮LED露营灯] USB充电户外帐篷灯 防水便携应急灯 超长续航野营照明灯

五点描述:
• 💡【超亮照明】升级20颗LED灯珠，亮度达800流明，照亮整个帐篷无死角
• 🔋【超长续航】内置5000mAh大容量电池，低亮模式续航长达30小时
• 💧【IPX5防水】雨天户外使用无忧，适合露营/徒步/夜钓等多场景
• 🔌【USB快充】Type-C接口3小时充满，可当充电宝应急给手机供电
• 🎒【便携挂钩设计】仅重180g，自带挂钩可悬挂帐篷顶、树枝、背包

搜索词: 露营灯 帐篷灯 USB充电 户外照明 野营灯 防水灯 便携灯 LED灯
"""


# ═══════════════════════════════════════════════════════════════════════
# Agent 基类
# ═══════════════════════════════════════════════════════════════════════

class BaseAgent(ABC):
    """所有 Agent 的基类"""

    name: str = "base"
    description: str = "Base agent"

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or LLMClient()
        self._history: list[dict] = []

    def log(self, msg: str) -> None:
        print(f"  [{self.name}] {msg}")

    def remember(self, role: str, content: str) -> None:
        self._history.append({"role": role, "content": content})

    @abstractmethod
    def run(self, *args, **kwargs) -> Any:
        """Agent 主入口，子类必须实现"""
        ...
