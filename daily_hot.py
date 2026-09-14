#!/usr/bin/env python3
"""每日爆款 — 淘宝搜索建议API获取实时热门词（纯HTTP，零风控）

原理：
  淘宝搜索框的自动补全建议词 = 用户正在大量搜索的关键词
  获取这些词 ≈ 知道今天什么品类在爆

用法:
    python daily_hot.py                  # 获取今日热门词
    python daily_hot.py --full           # 热门词 + 浏览器搜索Top5(慎用)
"""

import sys, json, time
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.parse import quote

if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except: pass

sys.path.insert(0, str(Path(__file__).parent))

OUTPUT_FILE = Path(__file__).parent / "data" / "daily_hot.json"

# 搜索前缀种子 — 覆盖各领域触发热搜联想
SEED_PREFIXES = [
    # 中文热词种子
    "夏", "新", "爆", "热", "潮", "美",
    # 品类触达
    "手机", "蓝牙", "充电", "防晒", "收纳", "露营",
    # 场景
    "户外", "家居", "学生", "儿童", "宠物",
    # 单品
    "裙", "鞋", "包", "灯", "表",
    # 英文/数字前缀
    "a", "b", "1", "ip",
]


def fetch_hot_keywords() -> list[dict]:
    """从淘宝搜索建议API获取实时热门搜索词"""
    all_words: dict[str, int] = {}  # word -> estimated popularity

    for prefix in SEED_PREFIXES:
        try:
            url = f"https://suggest.taobao.com/sug?code=utf-8&q={quote(prefix)}&_ksTS={int(time.time()*1000)}"
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.taobao.com/",
            })
            data = json.loads(urlopen(req, timeout=5).read().decode("utf-8"))
            suggestions = data.get("result", [])

            for item in suggestions:
                if isinstance(item, list) and len(item) >= 1:
                    word = str(item[0]).strip()
                    # popularity score (item[1] if exists)
                    pop = 0
                    if len(item) >= 2 and isinstance(item[1], (int, float)):
                        pop = int(item[1])

                    # 过滤：2-20字，不包含特殊字符
                    if 2 <= len(word) <= 20 and all(ord(c) > 31 for c in word):
                        # 同一词取最高热度
                        if word not in all_words or pop > all_words[word]:
                            all_words[word] = pop

            time.sleep(0.3)  # 请求间隔

        except Exception as e:
            print(f"  ⚠ 获取失败({prefix}): {e}")
            continue

    # 排序：优先按热度，其次按词长（3-5字的长尾词更有选品价值）
    result = []
    for word, pop in all_words.items():
        category = classify_word(word)
        result.append({
            "keyword": word,
            "popularity": pop,
            "category": category,
            "is_longtail": 3 <= len(word) <= 8,
        })

    result.sort(key=lambda x: (x["is_longtail"], x["popularity"]), reverse=True)
    return result


def classify_word(word: str) -> str:
    """根据关键词推断品类"""
    rules = [
        ("数码电子", ["手机", "蓝牙", "充电", "耳机", "数据线", "电脑", "鼠标", "键盘", "音箱", "平板", "苹果", "华为", "小米", "vivo", "oppo", "type", "耳机仓", "无线", "快充", "蓝牙音箱", "智能手表", "手环"]),
        ("女装服饰", ["裙", "衣", "裤", "装", "T恤", "衬衫", "外套", "针织", "旗袍", "中式", "牛仔", "短袖", "长袖", "吊带", "开衫", "马甲", "卫衣", "风衣", "女", "夏装", "春装", "秋装", "冬装", "套装", "连体", "阔腿", "喇叭"]),
        ("鞋靴箱包", ["鞋", "包", "靴", "拖", "凉鞋", "运动鞋", "帆布鞋", "双肩包", "高跟", "平底", "马丁", "乐福", "托特", "斜挎", "手拿", "单肩", "行李"]),
        ("美妆护肤", ["面膜", "口红", "防晒霜", "粉底", "精华", "眼影", "香水", "卸妆", "乳液", "面霜", "隔离", "bb霜", "cc霜", "眉笔", "眼线", "腮红", "唇", "美甲", "护手霜", "洗面奶", "爽肤水"]),
        ("家居生活", ["收纳", "抱枕", "台灯", "地毯", "窗帘", "四件套", "沙发", "桌", "椅", "柜", "床", "垫", "枕", "被", "凉席", "蚊帐", "置物架", "挂钩", "纸巾盒", "垃圾桶", "拖鞋", "浴帘", "水杯", "保温杯", "水壶", "饭盒", "锅", "碗", "盘"]),
        ("户外运动", ["露营", "帐篷", "防晒衣", "水杯", "登山", "跑步", "骑行", "瑜伽", "泳", "健身", "足球", "篮球", "羽毛球", "乒乓", "跳绳", "护膝", "登山杖", "冲锋衣", "速干", "渔具", "烧烤", "野餐"]),
        ("母婴亲子", ["儿童", "学生", "婴儿", "宝宝", "孕妇", "玩具", "文具", "书包", "奶瓶", "尿不湿", "推车", "安全座椅", "爬行垫", "早教", "积木", "绘本", "画笔", "彩笔"]),
        ("食品零食", ["零食", "坚果", "茶叶", "咖啡", "巧克力", "饼干", "糕点", "特产", "肉干", "糖果", "果冻", "薯片", "瓜子", "花生", "蜜饯", "方便面", "速食", "代餐", "麦片"]),
        ("个护健康", ["牙刷", "牙膏", "洗面奶", "沐浴", "洗发", "梳子", "按摩", "泡脚", "剃须", "脱毛", "理发器", "体温计", "血压计", "口罩", "湿巾", "纸巾"]),
        ("宠物用品", ["猫", "狗", "宠物", "猫粮", "狗粮", "猫砂", "逗猫", "猫抓板", "狗绳", "猫包", "宠物窝", "宠物垫", "宠物衣服", "饮水机"]),
        ("汽车用品", ["车载", "行车记录仪", "座垫", "脚垫", "车充", "头枕", "腰靠", "导航", "安全锤", "灭火器", "洗车", "车蜡", "雨刮"]),
        ("日用百货", ["伞", "雨衣", "手电", "电池", "胶带", "绳子", "锁", "剪刀", "镜子", "梳子", "发夹", "头绳", "发箍", "帽子", "围巾", "手套", "袜子", "内衣", "睡衣"]),
    ]
    for cat, tags in rules:
        if any(tag in word for tag in tags):
            return cat
    return "热销趋势"


def generate_report() -> dict:
    """生成每日爆款报告"""
    print("📡 获取淘宝实时热门搜索词...\n")
    keywords = fetch_hot_keywords()

    # Top 50 热门词
    top50 = keywords[:50]
    # 按品类分组
    by_category: dict[str, list] = {}
    for kw in top50:
        cat = kw["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(kw)

    # 每个品类挑Top3
    category_picks = {}
    for cat, words in by_category.items():
        top3 = words[:3]
        category_picks[cat] = {
            "count": len(words),
            "top_keywords": [w["keyword"] for w in top3],
            "hottest": top3[0]["keyword"] if top3 else "",
        }

    # 趋势洞察
    insights = []
    top_cats = sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)
    if top_cats:
        insights.append(f"今日热搜集中在{top_cats[0][0]}领域({len(top_cats[0][1])}个热词)")
    if len(top_cats) > 1:
        insights.append(f"{top_cats[1][0]}热度第二({len(top_cats[1][1])}个热词)")
    # 找快速增长词（长尾+高热度）
    longtail_hot = [k for k in top50 if k["is_longtail"] and k["popularity"] > 0][:5]
    if longtail_hot:
        insights.append(f"潜力长尾词: {', '.join(k['keyword'] for k in longtail_hot[:3])}")

    today = datetime.now().strftime("%Y-%m-%d")
    report = {
        "date": today,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "淘宝搜索建议API (实时热搜词)",
        "total_hot_keywords": len(keywords),
        "top_keywords": [k["keyword"] for k in top50],
        "by_category": {cat: {
            "count": v["count"],
            "top_keywords": v["top_keywords"],
            "hottest": v["hottest"],
        } for cat, v in sorted(category_picks.items(), key=lambda x: x[1]["count"], reverse=True)},
        "potential_products": [{
            "keyword": k["keyword"],
            "category": k["category"],
            "popularity": k["popularity"],
            "suggestion": f"建议搜索「{k['keyword']}」查看热销商品，当前淘宝搜索热度高",
        } for k in longtail_hot[:20]],
        "insights": insights,
        "category_summary": {cat: {
            "keyword": v["hottest"],
            "count": v["count"],
            "top_product": f"品类热搜: {', '.join(v['top_keywords'])}",
        } for cat, v in category_picks.items()},
        "hot_trends": [
            {"keyword": k["keyword"], "category": k["category"], "popularity": k["popularity"]}
            for k in top50[:8]
        ],
        "top50": [{
            "rank": i + 1,
            "score": min(95, 100 - i * 1.5),
            "title": k["keyword"],
            "price": 0,
            "sales_text": f"热搜度 {k['popularity']}" if k["popularity"] > 0 else "实时热搜",
            "shop_type": k["category"],
            "margin_pct": 0,
            "insight": f"🔥 淘宝实时热搜词 | {k['category']}" + (" | 高价值长尾词" if k["is_longtail"] else ""),
        } for i, k in enumerate(top50[:50])],
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  ✅ 今日爆款报告已生成: {OUTPUT_FILE}")
    print(f"  🔥 获取 {len(keywords)} 个实时热搜词")
    print(f"  📂 覆盖 {len(category_picks)} 个品类")
    print(f"  💡 {'; '.join(insights)}")
    print(f"{'='*60}")

    return report


async def run_with_browser():
    """可选：用浏览器搜索Top5热门词获取具体商品数据（慎用，会触发反爬）"""
    import asyncio, random
    sys.path.insert(0, str(Path(__file__).parent))
    from src.scrapers import TaobaoScraper
    from src.analyzer import Normalizer, Scorer

    report = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    top_words = report.get("top_keywords", [])[:5]

    print(f"\n🕷️  浏览器搜索 Top5 热门词（间隔20-35秒）...")
    print(f"   关键词: {', '.join(top_words)}")

    all_products = []
    for i, word in enumerate(top_words):
        if i > 0:
            wait = random.uniform(40, 70)
            print(f"   ⏳ 等待 {wait:.0f} 秒...")
            await asyncio.sleep(wait)

        print(f"   🔍 [{i+1}/5] {word}")
        tb = TaobaoScraper()
        try:
            result = await tb.search(word, 1)
            if result.products:
                items = Normalizer.normalize([result])
                scorer = Scorer()
                scored = scorer.score_all(items)
                for p in scored[:3]:
                    all_products.append({
                        "keyword": word,
                        "title": p.title,
                        "price": p.price,
                        "sales_text": p.sales_text,
                        "score": p.score,
                    })
        except Exception as e:
            print(f"     ✗ {e}")
        finally:
            await tb.close()

    if all_products:
        report["sample_products"] = all_products
        report["top50"] = [{
            "rank": i+1,
            "score": p.get("score", 0),
            "title": p.get("title", ""),
            "price": p.get("price", 0),
            "sales_text": p.get("sales_text", ""),
            "insight": f"热搜词: {p.get('keyword','')}",
        } for i, p in enumerate(all_products[:50])]

    OUTPUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  ✅ 报告已更新（含商品详情）")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="每日爆款 - 淘宝热搜词获取")
    parser.add_argument("--full", action="store_true", help="热搜词+浏览器搜索商品(慎用)")
    parser.add_argument("--schedule", action="store_true", help="每天9:00自动运行")
    args = parser.parse_args()

    if args.schedule:
        print("🕐 每日定时模式 (每天09:00)")
        print("   纯API模式，零风控\n")
        generate_report()
        # 简单循环：每天跑一次
        while True:
            now = datetime.now()
            next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= next_run:
                from datetime import timedelta
                next_run += timedelta(days=1)
            wait = (next_run - now).total_seconds()
            print(f"   ⏰ 下次运行: {next_run.strftime('%Y-%m-%d %H:%M')} ({wait/3600:.1f}小时后)")
            time.sleep(min(wait, 3600))
            if datetime.now().hour == 9:
                generate_report()

    elif args.full:
        generate_report()
        import asyncio
        asyncio.run(run_with_browser())

    else:
        generate_report()
        print("\n💡 提示:")
        print("   python daily_hot.py              # 获取热搜词(推荐，零风控)")
        print("   python daily_hot.py --full       # 热搜词+商品详情(会启动浏览器)")
        print("   python daily_hot.py --schedule   # 每天9:00自动运行")


if __name__ == "__main__":
    main()
