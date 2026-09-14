"""淘宝搜索爬虫 — 用 Playwright 渲染 + 正则提取商品数据"""

import re, json
from datetime import datetime
from urllib.parse import urlencode

from playwright.async_api import Page

from ..config import CRAWLER
from ..models import Platform, ProductItem, SearchResult
from .base import BaseScraper


class TaobaoScraper(BaseScraper):
    """淘宝搜索页数据采集"""

    platform = Platform.TAOBAO
    BASE_URL = "https://s.taobao.com/search"

    async def search(self, keyword: str, max_pages: int | None = None) -> SearchResult:
        max_pages = max_pages or CRAWLER["taobao_max_pages"]
        keyword = keyword.strip()
        result = SearchResult(keyword=keyword, platform=Platform.TAOBAO)

        # 检查缓存
        cached = self._get_cached(keyword)
        if cached:
            print(f"  📦 使用缓存数据 ({len(cached)} 条)")
            result.products = [self._parse_item(item, keyword) for item in cached]
            result.scraped_pages = 1
            return result

        try:
            context = await self._new_context()
            page = await context.new_page()
            all_products: list[ProductItem] = []

            for page_num in range(1, max_pages + 1):
                print(f"  🔍 淘宝: 正在搜索第 {page_num} 页...")
                await self._rate_limit()

                url = self._build_url(keyword, page_num)
                success = await self._safe_goto(page, url)
                if not success:
                    continue

                # 等待页面渲染
                await page.wait_for_timeout(3000)
                await self._human_scroll(page)

                # 解析商品 — 统一用正则从 HTML 提取
                products = await self._extract_products(page, keyword)
                if not products:
                    print(f"  ⚠ 第 {page_num} 页无结果")
                    if page_num == 1:
                        result.error = "未能获取数据，可能需要登录或遇到反爬验证"
                    break

                all_products.extend(products)
                print(f"  ✓ 淘宝第 {page_num} 页: 获取到 {len(products)} 个商品")
                result.scraped_pages = page_num

                # 尝试获取总数
                if result.total_results == 0:
                    result.total_results = await self._get_total_count(page)

            result.products = all_products

            # 写入缓存
            if all_products:
                cache_data = [self._product_to_dict(p) for p in all_products]
                self._save_cache(self._cache_key(keyword), cache_data)
                await self.save_session()

            await page.close()
            await self._close_context()

        except Exception as e:
            result.error = str(e)
            print(f"  ✗ 淘宝搜索出错: {e}")
            await self._close_context()

        return result

    def _build_url(self, keyword: str, page: int) -> str:
        params = {
            "q": keyword,
            "s": str((page - 1) * 44),
            "ie": "utf8",
            "sort": "sale-desc",
        }
        return f"{self.BASE_URL}?{urlencode(params)}"

    # ── 新提取策略：从 HTML 正则匹配商品卡片 ──

    async def _extract_products(self, page: Page, keyword: str) -> list[ProductItem]:
        """从页面 HTML 中提取所有商品"""
        html = await page.content()
        items: list[ProductItem] = []

        # 策略1: 找 <a> 标签商品链接，通过父级结构提取
        product_blocks = await page.locator(
            "a[href*='item.htm'], a[href*='detail.tmall.com'], "
            "a[class*='Card'], a[class*='card'], "
            "a[class*='item'], a[class*='Item'], "
            "div[class*='Item'], div[class*='item']"
        ).all()

        seen_urls = set()
        for block in product_blocks:
            try:
                href = await block.get_attribute("href") or ""
                if not href:
                    continue
                if href.startswith("//"):
                    href = "https:" + href

                # 去重
                item_id = re.search(r'id=(\d+)', href)
                key = item_id.group(1) if item_id else href[:60]
                if key in seen_urls:
                    continue
                seen_urls.add(key)

                product = await self._parse_block(block, keyword, href)
                if product and product.title and product.price > 0:
                    items.append(product)
            except Exception:
                continue

        # 策略2: 如果上面没找到，直接从 HTML 正则提取
        if not items:
            items = self._extract_from_html(html, keyword)

        return items

    async def _parse_block(self, block, keyword: str, href: str) -> ProductItem | None:
        """从 Playwright 元素提取商品信息"""
        try:
            text = await block.inner_text()
            text = text.strip()
            if not text or len(text) < 10:
                return None

            inner_html = await block.inner_html()
            has_img = "<img" in inner_html
            if not has_img:
                return None

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            is_tmall = "tmall" in href.lower()
            shop_type = "天猫" if is_tmall else "淘宝"

            # 解析标题
            title = ""
            for line in lines:
                if re.match(r"^[¥￥\d]", line):
                    continue
                if line in ["正在秒杀", "广告", "热销", "品牌新客补贴"]:
                    continue
                if len(line) > 5 and "旗舰" not in line and "专营" not in line and "专卖" not in line:
                    title = line
                    break
            if not title:
                title = lines[0] if lines else ""

            # 价格
            price = self._parse_price(text)

            # 销量
            sales_text = ""
            sales = 0
            for line in lines:
                if "人付款" in line or "已售" in line or "付款" in line:
                    sales_text = line.strip()
                    sales = self._parse_sales(sales_text)
                    break

            # 店铺名
            shop_name = ""
            for line in lines:
                if "旗舰店" in line or "专卖店" in line or "专营店" in line:
                    shop_name = line.strip()[:30]
                    break
            if not shop_name:
                shop_name = "天猫店铺" if is_tmall else "淘宝店铺"

            # 标签
            tags = []
            if is_tmall:
                tags.append("天猫")
            if "秒杀" in text:
                tags.append("秒杀")
            if "补贴" in text:
                tags.append("补贴")

            # 发货地
            location = ""
            for line in lines:
                m = re.match(r"^(广东|浙江|上海|北京|江苏|福建|山东|深圳|广州|杭州|河北|河南|四川|湖北|湖南)\s", line)
                if m:
                    location = line.strip()[:10]
                    break

            return ProductItem(
                platform=Platform.TAOBAO, keyword=keyword,
                title=title[:120], price=price,
                price_min=None, price_max=None,
                sales_count=sales, sales_text=sales_text,
                shop_name=shop_name, shop_type=shop_type,
                location=location,
                img_url="", product_url=href,
                free_shipping="包邮" in text,
                tags=tags, scraped_at=datetime.now(),
            )
        except Exception:
            return None

    def _extract_from_html(self, html: str, keyword: str) -> list[ProductItem]:
        """直接从 HTML 正则提取商品（备选方案）"""
        items: list[ProductItem] = []

        # 找商品URL + 标题模式
        # 淘宝商品链接模式: //item.taobao.com/item.htm?id=xxx 或 //detail.tmall.com/item.htm?id=xxx
        product_patterns = re.finditer(
            r'(?:https?:)?//(?:item\.taobao|detail\.tmall)\.com/item\.htm\?id=(\d+)[^"\'<>]*',
            html
        )
        seen = set()
        for m in product_patterns:
            url = m.group(0)
            if url.startswith("//"):
                url = "https:" + url
            pid = m.group(1)
            if pid in seen:
                continue
            seen.add(pid)
            # 粗略提取标题和价格（后续通过 Playwright 元素更准）
            items.append(ProductItem(
                platform=Platform.TAOBAO, keyword=keyword,
                title=f"商品#{pid}", price=0,
                sales_count=0, sales_text="",
                shop_name="", shop_type="淘宝",
                location="", img_url="",
                product_url=url,
                free_shipping=False, tags=[], scraped_at=datetime.now(),
            ))
        return items

    async def _get_total_count(self, page: Page) -> int:
        try:
            sel = ".total, [class*='total--'], .search-count"
            el = page.locator(sel).first
            if await el.count() > 0:
                text = await el.inner_text()
                nums = re.findall(r"[\d,]+", text)
                if nums:
                    return int(nums[0].replace(",", ""))
        except Exception:
            pass
        return 0

    # ── 数据清洗 ──

    def _parse_price(self, text: str) -> float:
        text = text.strip()
        normalized = re.sub(r"([¥￥]\s*\d+)\s*\.\s*(\d+)", r"\1.\2", text)
        yen_prices = re.findall(r"[¥￥]\s*(\d+\.?\d*)", normalized)
        if yen_prices:
            nums = [float(p) for p in yen_prices]
            reasonable = [n for n in nums if 3 <= n <= 50000]
            if reasonable:
                return round(sorted(reasonable)[len(reasonable)//2], 2)
            return nums[0]
        prices = re.findall(r"(\d+\.?\d*)", text)
        if not prices:
            return 0.0
        nums = [float(p) for p in prices]
        price_candidates = [n for n in nums if 3 <= n <= 50000]
        if price_candidates:
            return round(sorted(price_candidates)[len(price_candidates)//2], 2)
        return nums[0] if nums else 0.0

    def _parse_sales(self, text: str) -> int:
        text = text.strip()
        if not text:
            return 0
        cleaned = re.sub(r"[人付款已售\+]", "", text)
        if "万" in cleaned:
            num_str = cleaned.replace("万", "")
            try:
                return int(float(num_str) * 10000)
            except ValueError:
                pass
        nums = re.findall(r"(\d+)", cleaned)
        return int(nums[0]) if nums else 0

    def _parse_item(self, data: dict, keyword: str) -> ProductItem:
        return ProductItem(
            platform=Platform.TAOBAO, keyword=keyword,
            title=data.get("title", ""), price=data.get("price", 0),
            price_min=data.get("price_min"), price_max=data.get("price_max"),
            sales_count=data.get("sales_count", 0),
            sales_text=data.get("sales_text", ""),
            shop_name=data.get("shop_name", ""),
            shop_type=data.get("shop_type", ""),
            location=data.get("location", ""),
            img_url=data.get("img_url", ""),
            product_url=data.get("product_url", ""),
            free_shipping=data.get("free_shipping", False),
            tags=data.get("tags", []),
            scraped_at=datetime.now(),
        )

    def _product_to_dict(self, p: ProductItem) -> dict:
        return {
            "title": p.title, "price": p.price,
            "price_min": p.price_min, "price_max": p.price_max,
            "sales_count": p.sales_count, "sales_text": p.sales_text,
            "shop_name": p.shop_name, "shop_type": p.shop_type,
            "location": p.location, "img_url": p.img_url,
            "product_url": p.product_url,
            "free_shipping": p.free_shipping, "tags": p.tags,
        }
