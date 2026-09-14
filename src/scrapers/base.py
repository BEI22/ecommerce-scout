"""浏览器自动化基类 — 统一的反爬策略、重试、限速、缓存"""

import asyncio
import hashlib
import json
import os, sys
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path

# 修复 Windows GBK 终端编码 (Python 3.7+ safe method)
if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from ..config import CRAWLER, CACHE, CACHE_DIR, USER_AGENTS
from ..models import Platform, ProductItem, SearchResult


class BaseScraper(ABC):
    """爬虫基类，封装 Playwright 生命周期和反爬策略"""

    platform: Platform

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._last_request_time = 0.0
        self._request_count = 0
        self._cache: dict[str, list[dict]] = {}
        self._load_cache()

    # ── 缓存 ────────────────────────────────────────────

    def _cache_key(self, keyword: str) -> str:
        raw = f"{self.platform.value}:{keyword.strip().lower()}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _cache_file(self, key: str) -> Path:
        return CACHE_DIR / f"{key}.json"

    def _load_cache(self) -> None:
        """从磁盘加载缓存"""
        if not CACHE["enabled"]:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for f in CACHE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                created = data.get("cached_at", 0)
                if time.time() - created < CACHE["ttl_minutes"] * 60:
                    self._cache[f.stem] = data.get("products", [])
            except (json.JSONDecodeError, KeyError):
                f.unlink(missing_ok=True)

    def _save_cache(self, key: str, products: list[dict]) -> None:
        if not CACHE["enabled"]:
            return
        self._cache[key] = products
        self._cache_file(key).write_text(
            json.dumps({"cached_at": time.time(), "products": products}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _get_cached(self, keyword: str) -> list[dict] | None:
        key = self._cache_key(keyword)
        if key in self._cache:
            return self._cache[key]
        # 尝试从磁盘读取
        f = self._cache_file(key)
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if time.time() - data.get("cached_at", 0) < CACHE["ttl_minutes"] * 60:
                    self._cache[key] = data.get("products", [])
                    return self._cache[key]
            except (json.JSONDecodeError, KeyError):
                pass
        return None

    # ── 会话持久化 ────────────────────────────────────────

    @property
    def _session_file(self) -> Path:
        return CACHE_DIR / f"{self.platform.value}_session.json"

    async def save_session(self) -> None:
        """保存登录会话到文件"""
        if self._context:
            state = await self._context.storage_state()
            self._session_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            print(f"  ✓ 登录会话已保存: {self._session_file}")

    def _load_session(self) -> dict | None:
        """加载已保存的登录会话"""
        f = self._session_file
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError):
                pass
        return None

    # ── 浏览器生命周期 ───────────────────────────────────

    async def _launch_browser(self) -> None:
        """启动浏览器 — 优先使用系统已安装的 Chrome/Edge，无需额外下载"""
        self._playwright = await async_playwright().start()

        # 尝试顺序: 系统Chrome → 系统Edge → Playwright内置Chromium
        launch_opts = dict(
            headless=CRAWLER["headless"],
        )

        for browser_config in [
            {"executable_path": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"},
            {"executable_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe"},
            {"channel": "msedge"},
            {"channel": "chrome"},
            {},
        ]:
            try:
                opts = {**launch_opts}
                if "channel" in browser_config:
                    opts["channel"] = browser_config["channel"]
                if "executable_path" in browser_config:
                    opts["executable_path"] = browser_config["executable_path"]
                # 合并额外 args
                extra_args = browser_config.get("args", [])
                if extra_args:
                    opts["args"] = opts.get("args", []) + extra_args
                self._browser = await self._playwright.chromium.launch(**opts)
                return
            except Exception:
                continue

        raise RuntimeError("未找到可用的浏览器。请安装 Chrome 或 Edge。")

    async def _new_context(self) -> BrowserContext:
        """创建带反检测的浏览器上下文，自动加载已保存的登录会话"""
        if self._browser is None:
            await self._launch_browser()

        ua = random.choice(USER_AGENTS)
        session = self._load_session()

        context = await self._browser.new_context(
            user_agent=ua,
            viewport={
                "width": CRAWLER["viewport_width"],
                "height": CRAWLER["viewport_height"],
            },
            storage_state=session,  # 加载已保存的登录状态
        )
        # 注入 stealth 脚本，隐藏 webdriver 特征
        if CRAWLER["stealth_mode"]:
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                window.chrome = { runtime: {} };
            """)
        self._context = context
        return context

    async def _close_context(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None

    async def close(self) -> None:
        """关闭浏览器"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ── 限速 & 重试 ─────────────────────────────────────

    async def _rate_limit(self) -> None:
        """强制请求间隔，模拟人类行为"""
        delay = random.uniform(CRAWLER["request_delay_min"], CRAWLER["request_delay_max"])
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._last_request_time = time.time()
        self._request_count += 1

    async def _retry(self, coro, name: str = "操作"):
        """带退避的重试包装"""
        last_error = None
        for attempt in range(CRAWLER["max_retries"]):
            try:
                return await coro()
            except Exception as e:
                last_error = e
                if attempt < CRAWLER["max_retries"] - 1:
                    wait = CRAWLER["retry_backoff"] ** (attempt + 1)
                    print(f"  ⚠ {name} 失败 (第{attempt+1}次)，{wait:.1f}s 后重试...")
                    await asyncio.sleep(wait)
        raise last_error  # type: ignore[misc]

    # ── 通用页面操作 ────────────────────────────────────

    async def _human_scroll(self, page: Page) -> None:
        """模拟人类滚动"""
        for _ in range(random.randint(2, 4)):
            scroll_y = random.randint(300, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_y})")
            await asyncio.sleep(random.uniform(0.5, 1.5))

    async def _safe_goto(self, page: Page, url: str) -> bool:
        """安全导航，处理超时和验证码"""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2)  # 等待异步渲染
            # 检测是否出现验证码
            if await self._detect_captcha(page):
                print(f"  ⚠ 检测到验证码！请手动在浏览器中完成验证。")
                return False
            return True
        except Exception as e:
            print(f"  ✗ 页面加载失败: {e}")
            return False

    async def _detect_captcha(self, page: Page) -> bool:
        """检测页面是否出现滑块/验证码"""
        captcha_keywords = ["验证码", "captcha", "滑块", "请按住滑块", "安全验证", "verify"]
        try:
            body_text = await page.inner_text("body")
            for kw in captcha_keywords:
                if kw.lower() in body_text.lower():
                    return True
        except Exception:
            pass
        return False

    # ── 抽象方法，子类实现 ────────────────────────────────

    @abstractmethod
    async def search(self, keyword: str, max_pages: int | None = None) -> SearchResult:
        """搜索商品，返回标准化结果"""
        ...
