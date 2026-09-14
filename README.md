# Ecommerce Scout 🛒

**电商多 Agent 智能运营系统** — 从选品决策到运营执行的全链路 AI Agent 应用

输入一个品类关键词 → 自动抓取多平台数据 → 五维加权打分排名 → Agent 生成运营决策

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-green)](https://flask.palletsprojects.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.45%2B-orange)](https://playwright.dev/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey)](LICENSE)

---

## 📖 项目简介

中小电商卖家选品靠感觉：不知道该做什么类目、不知道竞品定价空间、不知道利润能不能撑住。
市面上的工具要么数据单一，要么**只给数据不给结论**。

本项目把选品从"看数据"变成"给决策"，并进一步覆盖运营全链路：

| 模块 | 能力 |
|------|------|
| 🎯 **选品决策** | 淘宝/拼多多/1688 三平台数据采集 + 五维加权评分 |
| ✍️ **内容生成** | 电商 Listing 文案生成、多语言本地化 |
| 💬 **智能客服** | FAQ 向量检索 + 意图路由 + 情感识别 + LLM 回复 |
| 📈 **广告优化** | 规则引擎 + ROI 自动调整预算 |
| 📊 **数据报表** | 异常检测 + 趋势预测 + 自动化周报 |
| 📦 **库存管理** | 需求预测 + 补货建议 + 滞销预警 |
| 🚚 **履约管理** | 订单跟踪 + 物流异常检测 |
| ⭐ **评价管理** | 情感分析 + 差评告警 + 挽回话术 |

---

## 🏗 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      表现层                                  │
│   Web 数据看板 (dashboard.html)  │  统一 CLI (11 个子命令)   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   服务层 (Flask · 25 个 API)                 │
│   异步任务模式：task_id + 状态轮询，避免长请求阻塞             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              Agent 层 (BaseAgent 抽象基类)                   │
│  ContentAgent │ CustomerAgent │ AdvertisingAgent             │
│  AnalyticsAgent │ InventoryAgent │ FulfillmentAgent          │
│  ReviewAgent                                                 │
└──────┬───────────────────┬───────────────────┬──────────────┘
       │                   │                   │
┌──────▼──────┐   ┌────────▼────────┐   ┌──────▼──────────┐
│ LLM 抽象层  │   │  RAG 知识库     │   │  分析引擎        │
│ 多 Provider │   │  自研 TF-IDF    │   │  五维加权评分    │
│ 自动检测    │   │  混合检索       │   │  跨平台对比      │
│ Mock 降级   │   │  余弦相似度     │   │  数据清洗        │
└─────────────┘   └─────────────────┘   └─────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              数据采集层 (Playwright + HTTP)                  │
│   淘宝 (渲染) │ 拼多多 (渲染) │ 1688 (轻量 HTTP)             │
│   反爬：stealth 注入 · UA 池 · 随机限速 · 指数退避 · 会话持久化 │
└─────────────────────────────────────────────────────────────┘
```

**Agent 协作模式**：所有 Agent 继承 `BaseAgent` 抽象基类，共享 `LLMClient` 客户端，
统一 `run()` 入口，可独立扩展新 Agent 而不影响其他模块。

---

## 💡 技术亮点

### 1. 自研向量检索 —— 零依赖的 RAG 方案

不引入 FAISS / sentence-transformers（数百 MB 依赖），用**纯 Python stdlib** 实现：

```python
class SimpleVectorizer:
    """TF-IDF 向量化器 — 中英混合分词 + L2 归一化"""

    def _tokenize(self, text):
        # 中文：1-gram + 2-gram 字符级切分
        # 英文：正则分词
        # → 适配中英混合场景
```

**混合检索策略**：`最终得分 = 0.6 × 向量相似度 + 0.4 × 关键词匹配率`

> **Trade-off 说明**：牺牲语义精度换取部署轻量——零安装依赖、秒级启动，
> 适配轻量部署场景。正式版可通过 `pgvector` 替换。

### 2. LLM 输出容错 —— 5 层降级 JSON 解析

LLM 返回 JSON 经常不稳定（markdown 包裹、尾逗号、单引号）。`chat_json()` 逐层尝试：

| 层级 | 策略 |
|------|------|
| 1 | 直接 `json.loads()` |
| 2 | 剥离 ` ```json ``` ` markdown 包裹 |
| 3 | 提取首个 `{` 到末个 `}` 之间的内容 |
| 4 | 修复尾部多余逗号 `,}` → `}` |
| 5 | 单引号替换为双引号 |

全部失败才返回原始文本供上层降级处理。

> **设计原则**：不要假设模型会听话，要假设它一定会出错。

### 3. 多 Provider 抽象 + Mock 降级

```python
def _resolve_provider(self, provider):
    if os.getenv("ANTHROPIC_API_KEY"):  return "claude"
    if os.getenv("DEEPSEEK_API_KEY"):   return "deepseek"
    if os.getenv("OPENAI_API_KEY"):     return "openai"
    return "mock"   # 无 Key 时降级，保证 Demo 可演示
```

零配置即可跑通完整流程（返回结构合理的模拟数据），降低体验门槛。

### 4. 反爬体系 —— 三平台差异化策略

| 机制 | 实现 |
|------|------|
| **反检测** | 注入脚本隐藏 `navigator.webdriver`、伪造 plugins/languages、补 `window.chrome` |
| **UA 轮换** | 4 个真实浏览器 UA 随机选用 |
| **请求限速** | 随机 5-10 秒间隔，模拟人类行为 |
| **重试机制** | 3 次重试 + 指数退避（2.0 倍） |
| **会话持久化** | `storage_state` 保存登录态，避免重复登录 |
| **缓存** | MD5 关键词为 key + 30 分钟 TTL 磁盘缓存 |
| **验证码检测** | 关键词识别 + 人工介入提示 |
| **模拟滚动** | 随机滚动 + 随机停顿 |
| **浏览器降级** | 系统 Edge → 系统 Chrome → 内置 Chromium 依次尝试 |

> **技术路线选择**：淘宝/拼多多走 Playwright 渲染（重，但能拿到动态数据）；
> 1688 走纯 HTTP 请求（轻量，零风控压力）。**同项目内两种路线并用**，
> 是因为场景不同——这个判断比技术本身更重要。

### 5. 五维加权评分模型

```python
SCORING = {
    "demand_weight": 0.25,       # 需求热度（销量）
    "competition_weight": 0.25,  # 竞争程度（价格偏离中位数）
    "margin_weight": 0.30,       # 利润空间（售价-成本-佣金-运费）/售价
    "arbitrage_weight": 0.10,    # 平台套利（两平台价差）
    "trend_weight": 0.10,        # 趋势判断（销量位置 + 标签加分）
}
```

**权重设计逻辑**：利润空间权重最高（30%）——选品最终看能不能赚钱，
而非单纯看热度。

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Chrome 或 Edge（Playwright 会优先复用系统浏览器）

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/BEI22/ecommerce-scout.git
cd ecommerce-scout

# 2. 创建虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装浏览器（首次运行需要）
playwright install chromium

# 5. 配置 API Key（可选，不配置走 Mock 模式）
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 使用

#### 方式一：Web 数据看板（推荐）

```bash
python launch.py
# 打开浏览器访问 http://localhost:5000
```

#### 方式二：命令行

```bash
# 基础搜索（淘宝 + 拼多多）
python cli.py "露营灯"

# 只看淘宝
python cli.py "手机壳" -p taobao

# 自定义翻页数和成本比例
python cli.py "收纳盒" -n 5 -c 0.35

# 导出 Excel
python cli.py "蓝牙耳机" -o report.xlsx

# 显示浏览器窗口（调试反爬）
python cli.py "台灯" --no-headless
```

#### 方式三：统一 CLI（11 个子命令）

```bash
python unified_cli.py demo        # 全功能演示
python unified_cli.py scout       # 选品分析
python unified_cli.py content     # Listing 文案生成
python unified_cli.py customer    # 智能客服
python unified_cli.py ad          # 广告优化
python unified_cli.py report      # 数据报表
python unified_cli.py inventory   # 库存管理
python unified_cli.py orders      # 履约管理
python unified_cli.py reviews     # 评价分析
python unified_cli.py monitor     # 价格监控
python unified_cli.py alert       # 告警汇总
```

---

## 📂 项目结构

```
ecommerce-scout/
├── launch.py                 # 启动器（Web 看板）
├── server.py                 # Flask 后端 · 25 个 API
├── cli.py                    # 选品命令行入口
├── unified_cli.py            # 统一 CLI · 11 个子命令
├── price_monitor.py          # 价格监控（快照对比 + 涨跌告警）
├── daily_hot.py              # 每日爆款（搜索建议 API）
├── setup_schedule.py         # 定时任务配置
├── login.py                  # 扫码登录 + 会话保存
├── requirements.txt
├── .env.example              # 配置模板
│
├── src/
│   ├── agents/               # 🧠 Agent 层（7 个业务 Agent）
│   │   ├── base.py           #    BaseAgent 基类 + LLMClient 抽象
│   │   ├── content.py        #    Listing 文案生成
│   │   ├── customer.py       #    智能客服
│   │   ├── advertising.py    #    广告优化
│   │   ├── analytics.py      #    数据报表
│   │   ├── inventory.py      #    库存管理
│   │   ├── fulfillment.py    #    履约管理
│   │   └── review.py         #    评价管理
│   │
│   ├── knowledge/            # 📚 自研 RAG
│   │   ├── store.py          #    TF-IDF 向量库 + 混合检索
│   │   └── retriever.py      #    检索器高层封装
│   │
│   ├── scrapers/             # 🕷 数据采集
│   │   ├── base.py           #    浏览器基类 + 反爬策略
│   │   ├── taobao.py         #    淘宝（Playwright）
│   │   ├── pinduoduo.py      #    拼多多（Playwright）
│   │   └── supplier_1688.py  #    1688（轻量 HTTP）
│   │
│   ├── analyzer/             # 📊 分析引擎
│   │   ├── normalizer.py     #    数据清洗
│   │   ├── comparator.py     #    跨平台对比
│   │   └── scorer.py         #    五维打分
│   │
│   ├── output/               # 🖨 输出
│   │   ├── console.py        #    终端彩色输出
│   │   └── excel.py          #    Excel 导出
│   │
│   ├── models.py             # 数据模型（dataclass）
│   └── config.py             # 全局配置
│
├── templates/
│   └── dashboard.html        # Web 数据看板
└── data/
    ├── cache/                # 请求缓存（gitignore）
    └── exports/              # 导出文件（gitignore）
```

---

## ⚙️ 技术栈

| 层次 | 技术 |
|------|------|
| **语言** | Python 3.10+ |
| **Agent 编排** | 自研 BaseAgent 抽象 + LLM 工具调用 |
| **LLM** | DeepSeek / OpenAI / Claude（自动检测 + Mock 降级） |
| **RAG** | 自研 TF-IDF 向量化 + 混合检索（向量 0.6 + 关键词 0.4） |
| **后端** | Flask（25 个 RESTful API，异步任务轮询模式） |
| **数据采集** | Playwright（Chrome/Edge 复用）+ 反爬体系 |
| **前端** | 原生 HTML/CSS/JavaScript |
| **数据处理** | Pydantic / dataclass / openpyxl |
| **CLI** | argparse + Rich（彩色输出） |

---

## ⚠️ 注意事项

1. **首次运行**需执行 `playwright install chromium`，或确保已安装 Chrome/Edge
2. **反爬建议**：不要频繁请求，项目已内置随机延时（5-10 秒）
3. **验证码处理**：遇到验证码可用 `--no-headless` 显示浏览器窗口手动完成
4. **数据说明**：平台销量为展示值估算，非精确数字
5. **合规声明**：仅供学习与选品参考，请遵守目标平台的服务条款

---

## 🔮 后续规划

- [ ] 向量检索替换为 pgvector，提升语义精度
- [ ] 引入定时调度（已预留 `setup_schedule.py`）
- [ ] Docker 化部署
- [ ] 增加更多平台数据源

---

## 📄 License

MIT License — 详见 [LICENSE](LICENSE)

---

> **说明**：本项目为个人学习与作品集项目，采用 AI 辅助开发方式完成
> （需求定义、架构设计、模块划分、评分模型、反爬策略由本人设计，
> AI 工具辅助代码实现）。代码全部开源，欢迎交流指正。
