"""全局配置"""

from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
EXPORT_DIR = DATA_DIR / "exports"

# 爬虫配置
CRAWLER = {
    "taobao_max_pages": 5,       # 淘宝最大翻页数
    "pdd_max_pages": 5,          # 拼多多最大翻页数
    "request_delay_min": 5.0,    # 最小请求间隔(秒)
    "request_delay_max": 10.0,   # 最大请求间隔(秒)
    "max_retries": 3,            # 最大重试次数
    "retry_backoff": 2.0,        # 重试退避倍数
    "stealth_mode": True,        # 是否启用 stealth 模式
    "headless": False,           # 是否无头模式(淘宝检测headless会崩溃, 用False)
    "viewport_width": 1366,
    "viewport_height": 768,
}

# 缓存配置
CACHE = {
    "enabled": True,
    "ttl_minutes": 30,           # 同关键词缓存有效期
}

# 打分配置
SCORING = {
    "demand_weight": 0.25,       # 需求热度权重
    "competition_weight": 0.25,  # 竞争程度(越低越好)
    "margin_weight": 0.30,       # 利润空间权重
    "arbitrage_weight": 0.10,    # 平台差异权重
    "trend_weight": 0.10,        # 趋势权重
    "default_cost_ratio": 0.40,  # 默认成本占售价比例(用户未提供时)
    "platform_fee_ratio": 0.05,  # 平台佣金+手续费估算
    "shipping_estimate": 5.0,    # 默认运费估算(元)
}

# 用户代理池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]
