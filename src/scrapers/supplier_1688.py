"""1688 供应商查询 — 基于 HTTP 请求（轻量，零风控）"""

import re, json, time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote, urlencode

from ..models import ProductItem, Platform


PLATFORM = Platform.SUPPLIER_1688


def search_1688(keyword: str, max_results: int = 30) -> list[ProductItem]:
    """搜索 1688 商品，返回批发价信息

    策略:
    1. 先尝试 1688 搜索建议 API
    2. 再尝试搜索页面 HTML 解析
    3. 最后尝试开放 API
    """
    items = _try_suggest_api(keyword)
    if not items:
        items = _try_search_page(keyword)
    return items[:max_results]


def _try_suggest_api(keyword: str) -> list[ProductItem]:
    """尝试 1688 搜索建议 API"""
    items = []
    try:
        url = f"https://suggest.1688.com/sug?code=***&q={quote(keyword)}&_ksTS={int(time.time()*1000)}"
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.1688.com/",
        })
        data = json.loads(urlopen(req, timeout=5).read().decode("utf-8"))
        results = data.get("result", [])
        for item in results:
            if isinstance(item, list) and len(item) >= 1:
                word = str(item[0]).strip()
                if 2 <= len(word) <= 40:
                    items.append(ProductItem(
                        platform=PLATFORM, keyword=keyword,
                        title=word, price=0,
                        sales_count=0, sales_text="热搜建议",
                        shop_name="", shop_type="1688",
                        location="", img_url="",
                        product_url="",
                        free_shipping=False, tags=[],
                        scraped_at=datetime.now(),
                    ))
    except Exception:
        pass
    return items


def _try_search_page(keyword: str) -> list[ProductItem]:
    """尝试直接解析 1688 搜索页面 HTML"""
    items = []
    try:
        params = urlencode({"keywords": keyword, "n": "y", "beginPage": 1})
        url = f"https://s.1688.com/youyuan/{params}.htm"
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.1688.com/",
        })
        resp = urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", errors="replace")

        # 从 HTML 中提取商品信息
        # 1688 商品卡片: <div class="offer-list-item" ...>
        # 或 JSON 数据在 <script> 中

        # 模式1: 找 offer-list-item div
        blocks = re.findall(
            r'<div[^>]*class="[^"]*offer-list-item[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>\s*</div>',
            html, re.DOTALL
        )

        for block in blocks[:30]:
            product = _parse_html_block(block, keyword)
            if product:
                items.append(product)

        # 模式2: 找 JSON 数据
        if not items:
            # 尝试找 priceJson 或 offerData
            json_patterns = re.findall(
                r'<script[^>]*>(?:window\.)?__(?:INITIAL|OFFER|PRICE)_?[^=]*=\s*(\{.*?\});?\s*</script>',
                html, re.DOTALL
            )
            for js in json_patterns[:3]:
                try:
                    data = json.loads(js)
                    products = _parse_json_data(data, keyword)
                    items.extend(products)
                except (json.JSONDecodeError, TypeError):
                    continue

    except Exception as e:
        print(f"  1688 搜索页解析失败: {e}")

    return items


def _parse_html_block(block: str, keyword: str) -> ProductItem | None:
    """从 HTML block 解析 1688 商品"""
    try:
        # 标题
        title_m = re.search(r'<a[^>]*title="([^"]+)"', block)
        title = title_m.group(1) if title_m else ""

        # 链接
        href_m = re.search(r'<a[^>]*href="([^"]+)"', block)
        href = href_m.group(1) if href_m else ""
        if href and not href.startswith("http"):
            href = "https:" + href if href.startswith("//") else href

        # 价格
        price = 0.0
        price_m = re.search(r'price[^:]*[¥￥]?\s*(\d+\.?\d*)', block, re.I)
        if price_m:
            price = float(price_m.group(1))

        # 起批量/销量
        sales_text = ""
        sales_m = re.search(r'起批.*?(\d+)', block)
        if sales_m:
            sales_text = f"起批{sales_m.group(1)}件"

        return ProductItem(
            platform=PLATFORM, keyword=keyword,
            title=title[:120], price=price,
            sales_count=0, sales_text=sales_text,
            shop_name="", shop_type="1688",
            location="", img_url="",
            product_url=href,
            free_shipping=False, tags=[],
            scraped_at=datetime.now(),
        )
    except Exception:
        return None


def _parse_json_data(data: dict, keyword: str) -> list[ProductItem]:
    """从 JSON 数据解析 1688 商品"""
    items = []
    # 尝试不同的 JSON 结构
    offer_list = (
        data.get("offerList") or
        data.get("data", {}).get("offerList") or
        data.get("result", {}).get("offerList") or
        []
    )
    if isinstance(offer_list, list):
        for offer in offer_list:
            try:
                items.append(ProductItem(
                    platform=PLATFORM, keyword=keyword,
                    title=offer.get("title", offer.get("subject", ""))[:120],
                    price=float(offer.get("price", offer.get("unitPrice", 0))),
                    sales_count=int(offer.get("saleCount", offer.get("saleQuantity", 0))),
                    sales_text=offer.get("saleTip", ""),
                    shop_name=offer.get("shopName", ""),
                    shop_type="1688",
                    location=offer.get("province", ""),
                    img_url=offer.get("imgUrl", ""),
                    product_url=offer.get("detailUrl", ""),
                    free_shipping=False, tags=[],
                    scraped_at=datetime.now(),
                ))
            except (ValueError, TypeError):
                continue
    return items
