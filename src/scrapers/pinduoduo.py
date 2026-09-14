"""拼多多搜索爬虫 — 使用移动端页面"""

import re
from datetime import datetime
from urllib.parse import urlencode

from playwright.async_api import Page

from ..config import CRAWLER
from ..models import Platform, ProductItem, SearchResult
from .base import BaseScraper


class PinduoduoScraper(BaseScraper):
    """拼多多移动端搜索数据采集"""

    platform = Platform.PDD
    BASE_URL = "https://mobile.yangkeduo.com/search_result.html"

    async def search(self, keyword: str, max_pages: int | None = None) -> SearchResult:
        """搜索拼多多商品"""
        max_pages = max_pages or CRAWLER["pdd_max_pages"]
        keyword = keyword.strip()
        result = SearchResult(keyword=keyword, platform=Platform.PDD)

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

            # 拼多多用手机端 viewport 更自然
            await page.set_viewport_size({"width": 414, "height": 896})
            all_products: list[ProductItem] = []

            for page_num in range(1, max_pages + 1):
                print(f"  🔍 拼多多: 正在搜索第 {page_num} 页...")
                await self._rate_limit()

                url = self._build_url(keyword, page_num)
                success = await self._safe_goto(page, url)
                if not success:
                    continue

                # 等待渲染
                await self._wait_for_results(page)
                await self._human_scroll(page)

                # 可能是 app 下载引导页，尝试关闭
                await self._dismiss_overlays(page)

                products = await self._parse_page(page, keyword)
                if not products:
                    if page_num == 1:
                        result.error = "未能获取数据，页面结构可能已变化"
                    break

                all_products.extend(products)
                print(f"  ✓ 拼多多第 {page_num} 页: 获取到 {len(products)} 个商品")
                result.scraped_pages = page_num

            result.products = all_products

            if all_products:
                self._save_cache(
                    self._cache_key(keyword),
                    [self._product_to_dict(p) for p in all_products],
                )
                await self.save_session()  # 保存登录状态

            await page.close()
            await self._close_context()

        except Exception as e:
            result.error = str(e)
            print(f"  ✗ 拼多多搜索出错: {e}")
            await self._close_context()

        return result

    def _build_url(self, keyword: str, page: int) -> str:
        """构建拼多多搜索URL"""
        params = {
            "search_key": keyword,
            "page": str(page),
        }
        return f"{self.BASE_URL}?{urlencode(params)}"

    async def _dismiss_overlays(self, page: Page) -> None:
        """关闭各种弹窗/浮层"""
        close_selectors = [
            ".close-btn", ".modal-close", ".popup-close",
            "[class*='close']", ".icon-close", ".download-tip-close",
        ]
        for sel in close_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click(timeout=2_000)
                    await page.wait_for_timeout(500)
            except Exception:
                pass

    async def _wait_for_results(self, page: Page) -> None:
        """等待搜索结果加载"""
        selectors = [
            ".search-result-list .goods-item",
            "[class*='goods-item']",
            "[class*='search-result'] [class*='item']",
            ".goods-list .item",
        ]
        for sel in selectors:
            try:
                await page.wait_for_selector(sel, timeout=10_000)
                return
            except Exception:
                continue
        await page.wait_for_timeout(5_000)

    async def _parse_page(self, page: Page, keyword: str) -> list[ProductItem]:
        """解析一页商品列表"""
        items: list[ProductItem] = []

        # 拼多多移动端常见选择器
        goods_selectors = [
            ".search-result-list .goods-item",
            "[class*='goods-item']",
            "[class*='GoodsItem']",
            "li[class*='item']",
        ]

        raw_items = []
        for gs in goods_selectors:
            raw_items = await page.locator(gs).all()
            if raw_items:
                break

        for item in raw_items:
            try:
                product = await self._parse_single_item(item, keyword)
                if product and product.title:
                    items.append(product)
            except Exception:
                continue

        return items

    async def _parse_single_item(self, item, keyword: str) -> ProductItem | None:
        """解析单个商品卡片"""
        try:
            # 标题
            title = ""
            for ts in ["[class*='goods-title']", ".title", "[class*='name']", "h3", ".goods-name"]:
                try:
                    el = item.locator(ts).first
                    if await el.count() > 0:
                        title = await el.inner_text()
                        break
                except Exception:
                    continue
            title = title.strip()
            if not title or len(title) < 2:
                return None

            # 商品链接
            href = ""
            try:
                a_el = item.locator("a").first
                if await a_el.count() > 0:
                    href = await a_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = f"https://mobile.yangkeduo.com{href}" if href.startswith("/") else href
            except Exception:
                pass

            # 价格 — 拼多多喜欢用红色数字
            price_text = ""
            for ps in ["[class*='price']", "[class*='Price']", ".current-price", ".goods-price"]:
                try:
                    el = item.locator(ps).first
                    if await el.count() > 0:
                        price_text = await el.inner_text()
                        break
                except Exception:
                    continue
            price = self._parse_price(price_text)

            # 销量/已拼件数
            sales_text = ""
            for ss in ["[class*='sales']", "[class*='Sales']", "[class*='group']", "[class*='sold']", ".sale-num"]:
                try:
                    el = item.locator(ss).first
                    if await el.count() > 0:
                        sales_text = await el.inner_text()
                        break
                except Exception:
                    continue
            sales = self._parse_sales(sales_text)

            # 店铺名
            shop_name = ""
            for sn in ["[class*='shop']", "[class*='Shop']", ".mall-name", "[class*='store']"]:
                try:
                    el = item.locator(sn).first
                    if await el.count() > 0:
                        shop_name = await el.inner_text()
                        break
                except Exception:
                    continue
            shop_name = shop_name.strip()

            # 标签
            tags = []
            try:
                tag_els = await item.locator("[class*='tag'], [class*='Tag'], [class*='badge']").all()
                for t in tag_els[:5]:
                    txt = await t.inner_text()
                    if txt.strip():
                        tags.append(txt.strip())
            except Exception:
                pass

            # 判断店铺类型
            shop_type = "个人店"
            if any(t in " ".join(tags) + shop_name for t in ["旗舰店", "品牌", "官方", "百亿补贴"]):
                shop_type = "品牌店"
            if "百亿补贴" in " ".join(tags):
                tags.append("百亿补贴")

            return ProductItem(
                platform=Platform.PDD,
                keyword=keyword,
                title=title,
                price=price,
                price_min=None,
                price_max=None,
                sales_count=sales,
                sales_text=sales_text,
                shop_name=shop_name,
                shop_type=shop_type,
                location="",
                img_url="",
                product_url=href,
                tags=tags,
                free_shipping=True,  # 拼多多大部分包邮
                scraped_at=datetime.now(),
            )

        except Exception:
            return None

    # ── 数据清洗工具 ──────────────────────────────────────

    def _parse_price(self, text: str) -> float:
        """解析价格文本 → 浮点数"""
        text = text.strip()
        text = re.sub(r"[¥￥\s已拼券后到手价]", "", text)
        prices = re.findall(r"(\d+\.?\d*)", text)
        if not prices:
            return 0.0
        nums = [float(p) for p in prices]
        if len(nums) >= 2:
            return round((nums[0] + nums[-1]) / 2, 2)
        return nums[0]

    def _parse_sales(self, text: str) -> int:
        """解析拼多多销量文本 → 整数"""
        text = text.strip()
        if not text:
            return 0
        # "已拼10万+件" / "已售1000+" / "10万+"
        cleaned = re.sub(r"[已拼件售\+]", "", text)
        if "万" in cleaned:
            try:
                num_str = cleaned.replace("万", "")
                return int(float(num_str) * 10000)
            except ValueError:
                pass
        nums = re.findall(r"(\d+)", cleaned)
        return int(nums[0]) if nums else 0

    def _parse_item(self, data: dict, keyword: str) -> ProductItem:
        """从缓存字典还原 ProductItem"""
        return ProductItem(
            platform=Platform.PDD,
            keyword=keyword,
            title=data.get("title", ""),
            price=data.get("price", 0),
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            sales_count=data.get("sales_count", 0),
            sales_text=data.get("sales_text", ""),
            shop_name=data.get("shop_name", ""),
            shop_type=data.get("shop_type", ""),
            location=data.get("location", ""),
            img_url=data.get("img_url", ""),
            product_url=data.get("product_url", ""),
            free_shipping=data.get("free_shipping", True),
            tags=data.get("tags", []),
            scraped_at=datetime.now(),
        )

    def _product_to_dict(self, p: ProductItem) -> dict:
        return {
            "title": p.title,
            "price": p.price,
            "price_min": p.price_min,
            "price_max": p.price_max,
            "sales_count": p.sales_count,
            "sales_text": p.sales_text,
            "shop_name": p.shop_name,
            "shop_type": p.shop_type,
            "location": p.location,
            "img_url": p.img_url,
            "product_url": p.product_url,
            "free_shipping": p.free_shipping,
            "tags": p.tags,
        }
