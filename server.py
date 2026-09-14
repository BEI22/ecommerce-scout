#!/usr/bin/env python3
"""TAgent Web Dashboard — AI电商全链路系统后端"""

import os, sys, json, threading, uuid, asyncio
from datetime import datetime
from pathlib import Path

# Safe UTF-8 encoding on Windows
if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    try: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, jsonify, request

app = Flask(__name__, static_folder="templates", static_url_path="")

# ── LLM 客户端（共享实例） ────────────────────────────
from src.agents.base import LLMClient
llm = LLMClient(provider="auto")


# ═══════════════════════════════════════════════════════════════
# 首页
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return app.send_static_file("dashboard.html")


# ═══════════════════════════════════════════════════════════════
# 1. 选品 Agent
# ═══════════════════════════════════════════════════════════════

@app.route("/api/scout", methods=["POST"])
def api_scout():
    data = request.json or {}
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "请输入关键词"}), 400

    import hashlib
    from src.config import CACHE_DIR

    # 1. 先检查是否有缓存数据
    products_cached = []
    for platform in ["taobao", "pinduoduo"]:
        cache_key = hashlib.md5(f"{platform}:{keyword}".encode()).hexdigest()
        cache_file = CACHE_DIR / f"{cache_key}.json"
        if cache_file.exists():
            try:
                cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
                for item in cache_data.get("products", []):
                    item["platform"] = platform
                    products_cached.append(item)
            except (json.JSONDecodeError, KeyError):
                pass

    # 2. 如果有缓存，用真实数据打分返回
    if products_cached:
        from src.models import Platform
        from src.analyzer import Normalizer, Comparator, Scorer

        real_products = []
        for item in products_cached:
            p = Platform.TAOBAO if item.get("platform") == "taobao" else Platform.PDD
            from src.models import ProductItem
            real_products.append(ProductItem(
                platform=p, keyword=keyword,
                title=item.get("title", ""), price=item.get("price", 0),
                sales_count=item.get("sales_count", 0), sales_text=item.get("sales_text", ""),
                shop_name=item.get("shop_name", ""), shop_type=item.get("shop_type", ""),
                location=item.get("location", ""), product_url=item.get("product_url", ""),
                tags=item.get("tags", []), free_shipping=item.get("free_shipping", False),
            ))

        all_items = Normalizer.normalize([])
        all_items = Normalizer.remove_outliers(real_products, "price")
        scorer = Scorer()
        scored = scorer.score_all(all_items)

        tb_items = [i for i in real_products if i.platform == Platform.TAOBAO]
        pd_items = [i for i in real_products if i.platform == Platform.PDD]
        tb_avg = round(sum(i.price for i in tb_items) / len(tb_items), 2) if tb_items else 0
        pd_avg = round(sum(i.price for i in pd_items) / len(pd_items), 2) if pd_items else 0
        gap = round((tb_avg - pd_avg) / pd_avg * 100, 1) if pd_avg > 0 else 0
        comp = Comparator.competition_analysis(all_items)

        result_products = []
        for i, p in enumerate(scored[:30]):
            result_products.append({
                "rank": i + 1, "score": round(p.score, 1),
                "title": p.title, "price": p.price, "sales": p.sales_count,
                "sales_text": p.sales_text, "platform": p.platform.value,
                "shop": p.shop_name, "margin_pct": p.estimated_margin_pct,
                "insight": p.insight,
                "product_url": p.product_url,
                "demand_score": round(p.demand_score, 1),
                "competition_score": round(p.competition_score, 1),
                "margin_score": round(p.margin_score, 1),
                "arbitrage_score": round(p.arbitrage_score, 1),
                "trend_score": round(p.trend_score, 1),
            })

        return jsonify({
            "keyword": keyword, "products": result_products,
            "taobao_count": len(tb_items), "pdd_count": len(pd_items),
            "taobao_avg_price": tb_avg, "pdd_avg_price": pd_avg,
            "price_gap_pct": gap, "competition": comp.get("level", ""),
            "total": len(scored), "source": "真实缓存数据",
        })

    # 3. 无缓存 → 返回空数据，前端显示可抓取
    return jsonify({
        "keyword": keyword,
        "products": [],
        "taobao_count": 0, "pdd_count": 0,
        "taobao_avg_price": 0, "pdd_avg_price": 0,
        "price_gap_pct": 0, "competition": "-", "total": 0,
        "source": "",
        "data_available": False,
        "hint": f'暂无「{keyword}」的缓存数据，点击下方按钮实时抓取',
    })


# ═══════════════════════════════════════════════════════════════
# 今日爆款
# ═══════════════════════════════════════════════════════════════

@app.route("/api/daily-hot", methods=["GET"])
def api_daily_hot():
    hot_file = Path(__file__).parent / "data" / "daily_hot.json"
    if hot_file.exists():
        try:
            return jsonify(json.loads(hot_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, IOError):
            pass
    return jsonify({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "top50": [],
        "category_summary": {},
        "hot_trends": [],
        "empty": True,
        "hint": "请先运行: python daily_hot.py 获取今日爆款数据",
    })


# ═══════════════════════════════════════════════════════════════
# 异步抓取任务管理
# ═══════════════════════════════════════════════════════════════

_crawl_tasks: dict = {}

async def _do_crawl(keyword: str) -> dict:
    """后台执行淘宝爬虫"""
    from src.scrapers import TaobaoScraper
    from src.config import CACHE_DIR
    import hashlib

    try:
        scraper = TaobaoScraper()
        result = await scraper.search(keyword, max_pages=1)
        await scraper.close()

        count = len(result.products)
        cache_key = hashlib.md5(f"taobao:{keyword}".encode()).hexdigest()
        cache_file = CACHE_DIR / f"{cache_key}.json"

        return {
            "success": True, "product_count": count, "keyword": keyword,
            "cache_file": str(cache_file.name) if cache_file.exists() else "",
            "message": f'抓到 {count} 个商品',
        }
    except Exception as e:
        return {"success": False, "error": str(e), "keyword": keyword}


def _run_crawl_thread(keyword: str, task_id: str) -> None:
    """在线程中运行异步爬虫"""
    _crawl_tasks[task_id]["status"] = "running"
    try:
        result = asyncio.run(_do_crawl(keyword))
        _crawl_tasks[task_id]["status"] = "done"
        _crawl_tasks[task_id]["result"] = result
    except Exception as e:
        _crawl_tasks[task_id]["status"] = "error"
        _crawl_tasks[task_id]["error"] = str(e)


@app.route("/api/scout/crawl", methods=["POST"])
def api_scout_crawl():
    """触发后台抓取"""
    data = request.json or {}
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "请输入关键词"}), 400

    task_id = uuid.uuid4().hex[:12]
    _crawl_tasks[task_id] = {
        "keyword": keyword, "status": "queued", "result": None, "error": None,
    }

    t = threading.Thread(target=_run_crawl_thread, args=(keyword, task_id), daemon=True)
    t.start()

    return jsonify({"task_id": task_id, "keyword": keyword, "status": "queued"})


@app.route("/api/scout/crawl-status/<task_id>", methods=["GET"])
def api_scout_crawl_status(task_id: str):
    task = _crawl_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    resp = {"task_id": task_id, "status": task["status"], "keyword": task["keyword"]}
    if task["status"] == "done":
        resp["result"] = task["result"]
        del _crawl_tasks[task_id]
    elif task["status"] == "error":
        resp["error"] = task["error"]
        del _crawl_tasks[task_id]
    return jsonify(resp)


# ═══════════════════════════════════════════════════════════════
# 1688 供应商比价
# ═══════════════════════════════════════════════════════════════

@app.route("/api/supplier/search", methods=["POST"])
def api_supplier_search():
    """搜索 1688 供应商并计算利润对比"""
    data = request.json or {}
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "请输入关键词"}), 400

    # 用后台线程跑 1688 爬虫
    import uuid
    task_id = uuid.uuid4().hex[:12]
    _supplier_tasks = getattr(api_supplier_search, "_tasks", {})
    _supplier_tasks[task_id] = {"status": "queued", "keyword": keyword, "result": None, "error": None}
    api_supplier_search._tasks = _supplier_tasks

    def _run():
        _supplier_tasks[task_id]["status"] = "running"
        try:
            from src.scrapers.supplier_1688 import search_1688
            result = search_1688(keyword)
            _supplier_tasks[task_id]["status"] = "done"
            products = []
            for p in result:
                products.append({
                    "title": p.title, "price": p.price,
                    "sales_text": p.sales_text,
                    "product_url": p.product_url,
                })
            valid_prices = [p.price for p in result if p.price > 0]
            avg_price = round(sum(valid_prices) / len(valid_prices), 2) if valid_prices else 0
            _supplier_tasks[task_id]["result"] = {
                "products": products,
                "count": len(products),
                "avg_price_1688": avg_price,
            }
        except Exception as e:
            _supplier_tasks[task_id]["status"] = "error"
            _supplier_tasks[task_id]["error"] = str(e)

    import threading
    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify({"task_id": task_id, "status": "queued"})


@app.route("/api/supplier/status/<task_id>", methods=["GET"])
def api_supplier_status(task_id: str):
    _tasks = getattr(api_supplier_search, "_tasks", {})
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    resp = {"status": task["status"], "keyword": task["keyword"]}
    if task["status"] == "done":
        resp["result"] = task["result"]
        del _tasks[task_id]
    elif task["status"] == "error":
        resp["error"] = task["error"]
        del _tasks[task_id]
    return jsonify(resp)


# ═══════════════════════════════════════════════════════════════
# 决策引擎 — AI 选品决策报告
# ═══════════════════════════════════════════════════════════════

@app.route("/api/decision", methods=["POST"])
def api_decision():
    """AI 决策引擎：分析选品数据，输出投资建议"""
    data = request.json or {}
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "请输入关键词"}), 400

    wholesale = float(data.get("wholesale", 35))
    shipping = float(data.get("shipping", 5))
    fee_rate = float(data.get("fee_rate", 0.05))
    packaging = float(data.get("packaging", 2))

    # 1. 获取缓存数据
    import hashlib
    from src.config import CACHE_DIR
    from src.models import Platform
    from src.analyzer import Normalizer, Comparator, Scorer

    products_all = []
    for platform in ["taobao", "pinduoduo"]:
        cache_key = hashlib.md5(f"{platform}:{keyword}".encode()).hexdigest()
        cache_file = CACHE_DIR / f"{cache_key}.json"
        if cache_file.exists():
            try:
                cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
                for item in cache_data.get("products", []):
                    item["platform"] = platform
                    products_all.append(item)
            except (json.JSONDecodeError, KeyError):
                pass

    if not products_all:
        return jsonify({"error": f'暂无「{keyword}」的数据，请先抓取', "data_missing": True}), 400

    # 2. 计算真实利润
    from src.models import ProductItem
    real_items = []
    for item in products_all:
        p = Platform.TAOBAO if item.get("platform") == "taobao" else Platform.PDD
        real_items.append(ProductItem(
            platform=p, keyword=keyword,
            title=item.get("title", ""), price=item.get("price", 0),
            sales_count=item.get("sales_count", 0),
            sales_text=item.get("sales_text", ""),
            shop_name=item.get("shop_name", ""),
            shop_type=item.get("shop_type", ""),
            location=item.get("location", ""),
            product_url=item.get("product_url", ""),
            tags=item.get("tags", []),
            free_shipping=item.get("free_shipping", False),
        ))

    # 打分
    all_items = Normalizer.remove_outliers(real_items, "price")
    scorer = Scorer()
    scored = scorer.score_all(all_items)

    # 利润计算
    cost_per_unit = wholesale + shipping + packaging
    profit_items = []
    for item in scored:
        total_cost = cost_per_unit + item.price * fee_rate
        profit = item.price - total_cost
        margin = (profit / item.price * 100) if item.price > 0 else 0

        # 利润潜力分 = 利润率 * 销量(归一化)
        profit_potential = margin * (item.sales_count / 1000) if item.sales_count > 0 else 0

        profit_items.append({
            "rank": len(profit_items) + 1,
            "title": item.title[:80],
            "price": round(item.price, 2),
            "sales": item.sales_count,
            "platform": item.platform.value,
            "cost": round(total_cost, 2),
            "profit": round(profit, 2),
            "margin": round(margin, 1),
            "score": round(item.score, 1),
            "profit_potential": round(profit_potential, 1),
            "product_url": item.product_url,
        })

    # 排序：综合利润率 + 销量得分
    profit_items.sort(key=lambda x: x["profit_potential"], reverse=True)
    for i, item in enumerate(profit_items, 1):
        item["rank"] = i

    # 3. 统计数据
    avg_price = round(sum(i["price"] for i in profit_items) / len(profit_items), 2)
    avg_margin = round(sum(i["margin"] for i in profit_items) / len(profit_items), 1)
    median_price = sorted([i["price"] for i in profit_items])[len(profit_items)//2]

    top3 = profit_items[:3]
    total_est_sales = sum(i["sales"] for i in top3)

    # 4. 生成决策报告
    # 先用 AI (DeepSeek)，失败则用规则降级
    good_items = [i for i in profit_items if i["margin"] > 20]
    hot_items = [i for i in profit_items if i["sales"] > 1000]
    best_items = [i for i in profit_items if i["margin"] > 20 and i["sales"] > 500]

    if best_items:
        best = best_items[0]
        est_daily = round(best["sales"] / 30, 0)
        monthly_profit = round(est_daily * 30 * best["profit"])
        verdict = "✅ 推荐进入"
    elif good_items:
        best = good_items[0]
        est_daily = max(round(best["sales"] / 30, 0), 3)
        monthly_profit = round(est_daily * 30 * best["profit"])
        verdict = "⚠️ 谨慎观察"
    elif profit_items:
        best = profit_items[0]
        est_daily = 5
        monthly_profit = round(est_daily * 30 * best["profit"]) if best["profit"] > 0 else -999
        verdict = "❌ 不建议"
    else:
        best = None; est_daily = 0; monthly_profit = 0; verdict = "❌ 数据不足"

    # AI 报告 (用 DeepSeek)
    top3_str = ""
    for i, p in enumerate(profit_items[:3], 1):
        top3_str += f"{i}. 标题：{p['title'][:50]} | 售价¥{p['price']} | 月销{p['sales']}件 | 利润¥{p['profit']}/件 | 毛利率{p['margin']}%\n"

    prompt = f"""你是资深电商选品经理。根据以下数据给出选品决策建议，一行废话都不要。

品类：{keyword}
商品数：{len(profit_items)} | 均价：¥{avg_price} | 中位数：¥{median_price}
假设进价¥{wholesale} + 运费¥{shipping} + 佣金{fee_rate*100:.0f}% + 包装¥{packaging}
平均毛利率：{avg_margin}%

Top3 商品：\n{top3_str}

请按以下格式输出（纯文字，不要markdown）：
📋 选品决策报告：{keyword}
🥇 首选推荐：商品名 | 售价¥XX | 单件利润¥XX | 毛利率XX%
📊 预期表现：首批100件预计X天售罄，月利润约¥XX
📈 市场判断：竞争XX | 价格区间¥XX-¥XX
⚠️ 风险提示：XX
✅ 结论：✅推荐 / ⚠️谨慎 / ❌不建议

字数控制在150字以内，结论要有明确态度。"""

    try:
        from src.agents.base import LLMClient
        llm = LLMClient(provider="auto")
        resp = llm.chat(prompt, temperature=0.3, max_tokens=1000)
        ai_report = resp.content
        if resp.tokens_in > 0:
            ai_report = resp.content.replace("```", "").strip()
    except Exception:
        # 降级：规则报告
        lines = [
            f"📋 选品决策报告：{keyword}", "",
            f"🥇 首选推荐：【{best['title'][:40]}】",
            f"   售价 ¥{best['price']} | 单件利润 ¥{best['profit']} | 毛利率 {best['margin']}%",
            f"📊 预期表现：参考月销 {best['sales']}件，预计日销 {int(est_daily)}单",
            f"   首批 100 件预计 {max(1, round(100/est_daily))} 天售罄",
            f"   月利润预估约 ¥{monthly_profit}",
            f"💰 成本明细：进价¥{wholesale} + 运费¥{shipping} + 佣金¥{round(best['price']*fee_rate,1)} + 包装¥{packaging} = ¥{best['cost']}/件",
            f"📈 市场判断：{len(profit_items)}个商品 | 均价¥{avg_price} | 中位数¥{median_price}",
            f"⚠️ 风险提示：利润空间一般，需控制成本" if best['margin'] < 30 else f"⚠️ 无明显风险",
            "", f"✅ 结论：{verdict}",
        ]
        ai_report = "\n".join(lines)

    return jsonify({
        "keyword": keyword,
        "total_products": len(profit_items),
        "avg_price": avg_price,
        "median_price": median_price,
        "avg_margin": avg_margin,
        "cost_per_unit": round(cost_per_unit, 2),
        "top3": profit_items[:10],
        "all_items": profit_items[:30],
        "ai_report": ai_report,
    })


# ═══════════════════════════════════════════════════════════════
# 2. 内容 Agent
# ═══════════════════════════════════════════════════════════════

@app.route("/api/content", methods=["POST"])
def api_content():
    data = request.json or {}
    product = data.get("product", "").strip()
    if not product:
        return jsonify({"error": "请输入商品名称"}), 400

    from src.agents.content import ContentAgent
    agent = ContentAgent(llm)
    result = agent.run(
        product=product,
        price=float(data.get("price", 0)),
        features=data.get("features", ""),
        angles=[a.strip() for a in data.get("angles", "性价比,品质,场景").split(",") if a.strip()],
        languages=[l.strip() for l in data.get("languages", "en").split(",") if l.strip()],
    )

    listings = []
    for l in result.listings:
        listings.append({
            "angle": l.angle, "language": l.language,
            "title": l.title, "bullets": l.bullets,
            "description": l.description, "search_terms": l.search_terms,
        })

    translations = {}
    for lang, lst in result.translations.items():
        translations[lang] = [{
            "title": x.title, "bullets": x.bullets, "search_terms": x.search_terms,
        } for x in lst]

    return jsonify({"product": product, "listings": listings, "translations": translations})


# ═══════════════════════════════════════════════════════════════
# 3. 客服 Agent
# ═══════════════════════════════════════════════════════════════

_customer_agent = None

def _get_customer_agent():
    global _customer_agent
    if _customer_agent is None:
        from src.agents.customer import CustomerAgent
        _customer_agent = CustomerAgent(llm)
    return _customer_agent

@app.route("/api/customer", methods=["POST"])
def api_customer():
    data = request.json or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "请输入消息"}), 400

    agent = _get_customer_agent()
    resp = agent.run(message)

    return jsonify({
        "query": resp.query,
        "answer": resp.answer,
        "intent": resp.intent,
        "sentiment": resp.sentiment,
        "needs_human": resp.needs_human,
        "escalation_reason": resp.escalation_reason,
        "faq_score": resp.faq_match_score,
        "faq_matched": resp.faq_matched_question,
        "suggested_actions": resp.suggested_actions,
    })

@app.route("/api/customer/faqs", methods=["GET"])
def api_customer_faqs():
    agent = _get_customer_agent()
    faqs = []
    for doc in agent.retriever.store.documents:
        faqs.append({"question": doc.question, "answer": doc.content})
    return jsonify({"faqs": faqs, "total": len(faqs)})


# ═══════════════════════════════════════════════════════════════
# 4. 广告 Agent
# ═══════════════════════════════════════════════════════════════

_ad_agent = None

def _get_ad_agent():
    global _ad_agent
    if _ad_agent is None:
        from src.agents.advertising import AdvertisingAgent
        _ad_agent = AdvertisingAgent()
        _ad_agent.setup_campaigns(mock_data=True)
    return _ad_agent

@app.route("/api/advertising/status", methods=["GET"])
def api_ad_status():
    agent = _get_ad_agent()
    report = agent.get_status()
    campaigns = []
    for c in report.campaigns:
        campaigns.append({
            "id": c.id, "name": c.name, "product": c.product_name,
            "budget": c.daily_budget, "spend": c.spend_today,
            "orders": c.orders, "revenue": c.revenue,
            "acos": round(c.acos * 100, 1), "roas": c.roas,
            "status": c.status, "bid": c.bid,
        })
    return jsonify({
        "date": report.date,
        "total_spend": report.total_spend,
        "total_revenue": report.total_revenue,
        "total_orders": report.total_orders,
        "overall_acos": round(report.overall_acos * 100, 1),
        "overall_roas": report.overall_roas,
        "campaigns": campaigns,
    })

@app.route("/api/advertising/optimize", methods=["POST"])
def api_ad_optimize():
    agent = _get_ad_agent()
    actions = agent.optimize()
    return jsonify({
        "actions": [{"campaign": a.campaign_name, "action": a.action, "detail": a.detail, "reason": a.reason} for a in actions],
        "count": len(actions),
    })


# ═══════════════════════════════════════════════════════════════
# 5. 数据 Agent
# ═══════════════════════════════════════════════════════════════

_data_agent = None

def _get_data_agent():
    global _data_agent
    if _data_agent is None:
        from src.agents.analytics import AnalyticsAgent
        _data_agent = AnalyticsAgent()
        _data_agent.load_data(mock=True, days=30)
    return _data_agent

@app.route("/api/analytics/report", methods=["GET"])
def api_analytics_report():
    agent = _get_data_agent()
    report = agent.weekly_report()
    metrics = []
    for m in report.metrics:
        metrics.append({
            "date": m.date, "revenue": m.revenue, "orders": m.orders,
            "ad_spend": m.ad_spend, "profit": m.profit, "margin": m.profit_margin,
        })
    alerts = [{"level": a.level, "title": a.title, "message": a.message, "deviation": a.deviation_pct} for a in report.alerts]
    forecast = agent.forecast("revenue", 7)

    return jsonify({
        "start_date": report.start_date, "end_date": report.end_date,
        "total_revenue": report.total_revenue, "total_profit": report.total_profit,
        "total_orders": report.total_orders, "avg_margin": report.avg_margin,
        "wow": report.week_over_week,
        "summary": report.summary,
        "metrics": metrics,
        "alerts": alerts,
        "forecast": forecast.get("next_days", []),
        "trend": forecast.get("trend_label", ""),
    })

@app.route("/api/analytics/alerts", methods=["GET"])
def api_analytics_alerts():
    agent = _get_data_agent()
    alerts = agent.check_alerts()
    return jsonify({
        "alerts": [{"level": a.level, "category": a.category, "title": a.title, "message": a.message} for a in alerts],
        "total": len(alerts),
    })


# ═══════════════════════════════════════════════════════════════
# 6. 库存 Agent
# ═══════════════════════════════════════════════════════════════

_inventory_agent = None

@app.route("/api/inventory", methods=["GET"])
def api_inventory():
    global _inventory_agent
    if _inventory_agent is None:
        from src.agents.inventory import InventoryAgent
        _inventory_agent = InventoryAgent()
        _inventory_agent.load_inventory(mock=True)

    report = _inventory_agent.analyze()
    skus = []
    for s in report.skus:
        safety = _inventory_agent.calc_safety_stock(s)
        skus.append({
            "id": s.sku_id, "name": s.product_name,
            "stock": s.current_stock, "daily_sales": s.daily_avg_sales,
            "safety_stock": safety, "lead_time": s.lead_time_days,
            "turnover_days": s.stock_turnover_days,
            "status": s.status, "price": s.price, "cost": s.unit_cost,
        })
    alerts = [{"level": a.level, "title": a.title, "message": a.message, "action": a.suggested_action} for a in report.alerts]
    return jsonify({
        "skus": skus,
        "alerts": alerts,
        "total_value": report.total_stock_value,
        "dead_value": report.dead_stock_value,
        "low_count": report.low_stock_count,
        "dead_count": report.dead_stock_count,
        "summary": report.summary,
    })


# ═══════════════════════════════════════════════════════════════
# 7. 评价 Agent
# ═══════════════════════════════════════════════════════════════

_review_agent = None

@app.route("/api/reviews", methods=["GET"])
def api_reviews():
    global _review_agent
    if _review_agent is None:
        from src.agents.review import ReviewAgent
        _review_agent = ReviewAgent()
        _review_agent.load_reviews(mock=True)

    report = _review_agent.analyze()
    reviews = []
    for r in report.reviews:
        reviews.append({
            "id": r.review_id, "product": r.product_name,
            "customer": r.customer_name, "rating": r.rating,
            "title": r.title, "content": r.content,
            "sentiment": r.sentiment, "date": r.created_at,
        })
    alerts = [{"level": a.level, "title": a.title, "message": a.message, "reply": a.suggested_reply} for a in report.alerts]
    return jsonify({
        "reviews": reviews,
        "alerts": alerts,
        "avg_rating": report.avg_rating,
        "positive": report.positive_count,
        "neutral": report.neutral_count,
        "negative": report.negative_count,
        "trend": report.negative_trend,
        "recommendations": report.recommendations,
    })

@app.route("/api/reviews/reply", methods=["POST"])
def api_reviews_reply():
    global _review_agent
    if _review_agent is None:
        from src.agents.review import ReviewAgent
        _review_agent = ReviewAgent()
        _review_agent.load_reviews(mock=True)

    replies = _review_agent.reply_to_all_negative()
    return jsonify({"replies": replies, "count": len(replies)})


# ═══════════════════════════════════════════════════════════════
# 8. 全链路 Demo
# ═══════════════════════════════════════════════════════════════

@app.route("/api/demo", methods=["POST"])
def api_demo():
    data = request.json or {}
    keyword = data.get("keyword", "露营灯")
    results = {}

    # 选品 — 用缓存数据或空
    results["scout"] = {"products": [], "total": 0, "note": "请先在选品分析页面搜索获取数据"}

    # 内容
    from src.agents.content import ContentAgent
    content_agent = ContentAgent(llm)
    cr = content_agent.run(product=f"{keyword} 高配版", price=35, features="超亮,防水,USB充电", angles=["性价比"], languages=["en"])
    results["content"] = {"title": cr.listings[0].title if cr.listings else "", "bullets": cr.listings[0].bullets[:3] if cr.listings else []}

    # 客服
    from src.agents.customer import CustomerAgent
    cs_agent = CustomerAgent()
    cs_resp = cs_agent.run("什么时候发货？")
    results["customer"] = {"answer": cs_resp.answer, "intent": cs_resp.intent, "sentiment": cs_resp.sentiment}

    # 广告
    agent = _get_ad_agent()
    ad_report = agent.get_status()
    results["advertising"] = {"total_spend": ad_report.total_spend, "total_revenue": ad_report.total_revenue, "acos": round(ad_report.overall_acos * 100, 1)}

    # 数据
    data_agent = _get_data_agent()
    results["analytics"] = {"total_revenue": data_agent.weekly_report().total_revenue, "alerts": len(data_agent.check_alerts())}

    # 库存
    inv_agent = _inventory_agent
    if inv_agent is None:
        from src.agents.inventory import InventoryAgent
        inv_agent = InventoryAgent(); inv_agent.load_inventory(mock=True)
    inv_report = inv_agent.analyze()
    results["inventory"] = {"total_value": inv_report.total_stock_value, "alerts": len(inv_report.alerts)}

    # 评价
    from src.agents.review import ReviewAgent
    rev_agent = ReviewAgent(); rev_agent.load_reviews(mock=True)
    rev_report = rev_agent.analyze()
    results["reviews"] = {"avg_rating": rev_report.avg_rating, "negative": rev_report.negative_count}

    return jsonify({"keyword": keyword, "results": results})



# ═══════════════════════════════════════════════════════════════
# 9. 盯价监控 — Price Monitor
# ═══════════════════════════════════════════════════════════════

@app.route("/monitor")
def monitor_page():
    return app.send_static_file("dashboard.html")


@app.route("/api/monitor", methods=["POST"])
def api_monitor():
    """执行盯价：接收关键词，调用 price_monitor.py 抓取最新数据并对比历史"""
    data = request.json or {}
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "请输入关键词"}), 400

    pages = int(data.get("pages", 1))

    try:
        from price_monitor import PriceMonitor

        results = {}
        errors = [None]

        def _run():
            import asyncio
            try:
                monitor = PriceMonitor(keyword=keyword, pages=pages, headless=True)
                report = asyncio.run(monitor.run())
                results["report"] = report
                results["products"] = monitor.products
            except Exception as e:
                errors[0] = str(e)

        import threading
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=120)

        if errors[0]:
            return jsonify({"error": errors[0]}), 500

        report = results.get("report")
        if not report:
            return jsonify({"error": "盯价超时或无结果"}), 500

        if report.error:
            return jsonify({"error": report.error}), 500

        products = []
        product_list = results.get("products", [])
        for p in product_list:
            products.append({
                "title": p.title,
                "price": p.price,
                "sales_count": p.sales_count,
                "sales_text": p.sales_text,
                "shop_name": p.shop_name,
                "shop_type": p.shop_type,
                "product_url": p.product_url,
                "img_url": p.img_url,
                "free_shipping": p.free_shipping,
                "tags": p.tags,
            })

        changes = []
        for c in report.changes:
            changes.append({
                "title": c.title,
                "product_url": c.product_url,
                "old_price": c.old_price,
                "new_price": c.new_price,
                "price_diff": c.price_diff,
                "price_diff_pct": c.price_diff_pct,
                "old_sales": c.old_sales,
                "new_sales": c.new_sales,
                "sales_diff": c.sales_diff,
                "shop_name": c.shop_name,
                "status": c.status,
            })

        return jsonify({
            "keyword": keyword,
            "product_count": report.product_count,
            "products": products,
            "changes": changes,
            "price_min": report.price_min,
            "price_max": report.price_max,
            "price_avg": report.price_avg,
            "total_sales": report.total_sales,
            "previous_timestamp": report.previous_timestamp.isoformat() if report.previous_timestamp else None,
            "snapshot_path": report.snapshot_path,
            "timestamp": report.timestamp.isoformat(),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/monitor/history", methods=["GET"])
def api_monitor_history():
    """返回历史盯价记录：所有已盯过的关键词和最新快照"""
    from price_monitor import MONITOR_DIR

    if not MONITOR_DIR.exists():
        return jsonify({"keywords": [], "recent_snapshots": []})

    keywords = []
    recent_snapshots = []

    for kw_dir in sorted(MONITOR_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not kw_dir.is_dir():
            continue
        keywords.append(kw_dir.name)

        snapshots = sorted(kw_dir.glob("*.json"), reverse=True)
        if snapshots:
            try:
                snap_data = json.loads(snapshots[0].read_text(encoding="utf-8"))
                recent_snapshots.append({
                    "keyword": snap_data.get("_keyword", kw_dir.name),
                    "product_count": snap_data.get("_product_count", 0),
                    "time": snap_data.get("_snapshot_time", ""),
                })
            except (json.JSONDecodeError, IOError):
                pass

    return jsonify({
        "keywords": keywords,
        "recent_snapshots": recent_snapshots[:50],
        "snapshot_dir": str(MONITOR_DIR),
    })


# ═══════════════════════════════════════════════════════════════
# 启动时自动获取今日热搜词
# ═══════════════════════════════════════════════════════════════

def auto_refresh_daily_hot():
    """启动时自动获取热搜词，自动抓取热门品类，然后每4小时循环"""
    import threading
    def _run():
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from daily_hot import generate_report
            print("  🔥 自动获取今日热搜词...")
            report = generate_report()
            kw_count = report['total_hot_keywords']
            cat_count = len(report.get('by_category',{}))
            print(f"  ✅ 获取 {kw_count} 个热搜词，覆盖 {cat_count} 个品类")

            # 自动抓取热搜 Top3 品类
            top_cats = list(report.get('by_category', {}).keys())[:3]
            for cat in top_cats:
                hot_kw = report['by_category'][cat].get('hottest', '')
                if hot_kw:
                    print(f"  🕷️ 自动抓取热搜品类: {hot_kw}...")
                    _auto_crawl_keyword(hot_kw)
        except Exception as e:
            print(f"  ⚠ 自动采集任务失败: {e}")

        # 4小时后再次刷新
        _schedule_next_refresh()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _schedule_next_refresh():
    """4小时后自动刷新"""
    import threading
    def _wait_and_run():
        import time
        time.sleep(4 * 3600)
        print("  🔄 定时刷新热搜词...")
        try:
            from daily_hot import generate_report
            report = generate_report()
            print(f"  ✅ 刷新完成: {report['total_hot_keywords']} 个热词")
            # 自动抓取最新热搜
            for cat in list(report.get('by_category', {}).keys())[:3]:
                kw = report['by_category'][cat].get('hottest', '')
                if kw:
                    _auto_crawl_keyword(kw)
        except Exception as e:
            print(f"  ⚠ 定时刷新失败: {e}")
        _schedule_next_refresh()
    t = threading.Thread(target=_wait_and_run, daemon=True)
    t.start()


def _auto_crawl_keyword(keyword: str):
    """后台静默抓取关键词（有缓存且未过期则跳过）"""
    try:
        import hashlib, time
        from src.config import CACHE_DIR
        cache_key = hashlib.md5(f"taobao:{keyword}".encode()).hexdigest()
        cache_file = CACHE_DIR / f"{cache_key}.json"

        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - data.get("cached_at", 0) < 3600:
                print(f"    📦 {keyword} 缓存未过期，跳过")
                return

        import asyncio
        from src.scrapers import TaobaoScraper

        async def _do():
            s = TaobaoScraper()
            try:
                await s.search(keyword, max_pages=1)
            finally:
                await s.close()
        asyncio.run(_do())
        print(f"    ✅ {keyword} 自动抓取完成")
    except Exception as e:
        print(f"    ⚠ {keyword} 自动抓取失败: {e}")


@app.route("/api/schedule/status", methods=["GET"])
def api_schedule_status():
    """查看定时任务状态"""
    return jsonify({
        "auto_refresh": True,
        "interval_hours": 4,
        "auto_crawl_top_keywords": True,
    })


# ═══════════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
  ╔═════════════════════════════════════════════╗
  ║  TAgent Dashboard 已启动                     ║
  ║  打开浏览器访问: http://localhost:5000        ║
  ╚═════════════════════════════════════════════╝
    """)
    # 启动时自动获取今日热搜词
    auto_refresh_daily_hot()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
