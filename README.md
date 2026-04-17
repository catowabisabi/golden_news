# Golden News - 實時新聞智能系統

AI 驅動嘅新聞情報系統，自動收集 25+ 新聞源、生成交易信號、以互動圖形展示新聞關係。

## 功能

- 📰 **25+ 新聞 API** - RSS + REST，涵蓋 Yahoo Finance、BBC、CNBC、Google News 等
- 🤖 **AI 交易信號** - MiniMax M2.7 分析新聞，即時生成 SHORT/LONG 信號（信心度 82-88%）
- 🌐 **WebSocket 實時推送** - 客戶端可即時接收最新新聞同信號
- 📊 **D3.js 新聞關係圖** - 關鍵詞連線、情緒著色、互動拖曳
- 📈 **Dash 儀表板** - 實時信號、新聞列表、API 狀態

## 架構

```
golden_news/
├── config/
│   ├── news_sources.json   # 25+ 新聞源配置
│   └── api_keys.json       # 你的 API keys
├── database/
│   ├── schema.sql          # SQLite 9 張表結構
│   └── golden_news.db      # 實際數據庫
├── src/
│   ├── init_db.py          # 初始化數據庫
│   ├── collector.py        # 新聞收集器
│   ├── ai_analyzer.py      # AI 信號生成器
│   ├── api_tester.py        # API 健康檢查
│   └── websocket_server.py # WebSocket 服務器
├── dashboard/
│   ├── app.py              # Plotly Dash 儀表板
│   └── index.html          # D3.js 獨立版（可 browser 直接開）
└── scripts/
    └── demo.sh             # 一鍵啟動腳本
```

## 安裝

### 1. 克隆項目

```bash
git clone https://github.com/catowabisabi/golden_news.git
cd golden_news
```

### 2. 安裝依賴

```bash
pip install requests feedparser websockets flask-socketio dash plotly anthropic openai python-dateutil -q --break-system-packages
```

或者一次過：

```bash
pip install -r requirements.txt -q --break-system-packages
```

### 3. 配置 API Keys

編輯 `config/api_keys.json`，填入你嘅 keys：

```json
{
  "openai": "",
  "minimax_chat": "sk-cp-ml_你的key",
  "minimax_tts": "sk-api-你的key",
  "newsapi": "",
  "mediastack": "",
  "finnhub": "",
  "alphavantage": "",
  "newsdata": "",
  ...
}
```

**可選 Keys（無 key 仍可用部分功能）：**
| API | 用途 | 申請 |
|-----|------|------|
| MiniMax Chat | AI 信號生成 | 已有 |
| MiniMax TTS | 粵語/普通話語音 | 已有 |
| NewsAPI.org | 新聞聚合 | https://newsapi.org |
| NewsData.io | 新聞 API | https://newsdata.io |
| Finnhub | 金融新聞 | https://finnhub.io |
| Alpha Vantage | 新聞情緒 | https://alphavantage.co |

### 4. 初始化數據庫

```bash
python3 scripts/init_db.py
```

### 5. 測試 APIs

```bash
python3 src/api_tester.py
```

輸出範例：
```
==================================
🌐 Golden News - API Tester
==================================

Testing 26 APIs...
🆓 Yahoo Finance RSS: ✅ 11 articles
🆓 Google News RSS: ✅ 8 articles
🆓 BBC RSS: ✅ 5 articles
🆓 CNBC RSS: ✅ 5 articles
🆓 ZeroHedge RSS: ✅ 5 articles
🆓 Reddit RSS: ✅ 5 articles
💰 NewsAPI.org: ❌ (需要 key)
💰 MediaStack: ❌ (需要 key)
...
==================================
6/26 APIs working without keys
==================================
```

## 使用方法

### 完整流程（一次過運行所有模組）

```bash
# 初始化數據庫
python3 scripts/init_db.py

# 收集新聞
python3 src/collector.py

# 生成 AI 交易信號
python3 src/ai_analyzer.py

# 啟動 WebSocket 服務器（端口 8765）
python3 src/websocket_server.py

# 啟動 Dash 儀表板（端口 8050）
cd dashboard && python3 app.py
```

或者用一鍵腳本：

```bash
bash scripts/demo.sh
```

### 個別模組

**1. 收集新聞**
```bash
python3 src/collector.py
# 輸出：Collected 40 new articles!
```

**2. 生成 AI 信號**
```bash
python3 src/ai_analyzer.py
# 輸出：✅ SHORT oil | 88% | XLE
#       ✅ SHORT oil | 85%
#       ✅ LONG stocks | 72%
```

**3. WebSocket 客戶端示例**
```python
import socketio

sio = socketio.Client()
sio.connect("http://localhost:8765")

@sio.on("new_article")
def on_article(data):
    print(f"📰 {data['title']}")

@sio.on("trading_signal")
def on_signal(data):
    print(f"⚡ {data['direction']} {data['asset_class']} | {data['confidence']}%")

sio.wait()
```

**4. 查詢數據庫**
```bash
python3 -c "
import sqlite3
db = sqlite3.connect('database/golden_news.db')

# 最新信號
sigs = db.execute('SELECT * FROM trading_signals ORDER BY generated_at DESC LIMIT 5').fetchall()
for s in sigs:
    print(f'{s[3]} {s[2]} | {int(s[4]*100)}%')

# API 狀態
status = db.execute('SELECT is_working, COUNT(*) FROM news_sources GROUP BY is_working').fetchall()
print(f'Working: {status[1][1] if len(status)>1 else 0}, Down: {status[0][1] if status and not status[0][0] else 0}')
"
```

## WebSocket 命令

連接到 `ws://localhost:8765` 後，發送 JSON：

```json
{"command": "ping"}
{"command": "get_latest", "minutes": 30, "limit": 20}
{"command": "get_signals", "limit": 10}
{"command": "get_status"}
{"command": "subscribe", "category": "oil"}
```

## D3.js 圖形（獨立 HTML）

直接用瀏覽器打開 `dashboard/index.html`，會自動連接 WebSocket。

**圖形功能：**
- 情緒著色（綠=正面、紅=負面、灰=中性）
- 關鍵詞共享 → 連線
- 拖曳節點
- 滾輪縮放
- 點擊節點 → 開啟原文

## MiniMax API 配置

系統使用 MiniMax M2.7 生成交易信號。API 格式：

```python
import anthropic

client = anthropic.Anthropic(
    base_url='https://api.minimax.io/anthropic',
    api_key='sk-cp-ml_你的key'
)

response = client.messages.create(
    model='MiniMax-M2.7',
    max_tokens=1000,
    system='你係金融新聞分析師...',
    messages=[{'role': 'user', 'content': '分析這條新聞...'}]
)
```

**注意：** 舊版 `/v1/text/chatcompletion_v2` 端點已廢棄，必須用 Anthropic SDK 格式。

## cron Job 自動化

每小時自動收集 + 分析：

```bash
# 创建 cron job（需要完整路徑）
crontab -e

# 添加：
0 * * * * cd /mnt/c/Users/enoma/Desktop/golden_news && python3 src/collector.py >> logs/collector.log 2>&1
5 * * * * cd /mnt/c/Users/enoma/Desktop/golden_news && python3 src/ai_analyzer.py >> logs/analyzer.log 2>&1
```

## 數據庫結構

9 張表：
- `news_sources` - API 配置 + 健康狀態
- `news_articles` - 新聞文章 + 情緒分析
- `trading_signals` - AI 交易信號
- `api_request_log` - API 調用日誌
- `websocket_connections` - 連接記錄
- `keywords` / `article_keywords` - 關鍵詞索引
- `news_trading_links` - 新聞-信號關係
- `analytics_summary` - 每日統計

## 依賴

```
requests>=2.28.0
feedparser>=6.0.0
websockets>=10.0
flask-socketio>=2.9.0
dash>=2.14.0
plotly>=5.18.0
anthropic>=0.18.0
openai>=1.0.0
python-dateutil>=2.8.0
```

## 疑難解答

**Q: collector.py 報 `ModuleNotFoundError: No module named 'feedparser'`**
```bash
pip install feedparser -q --break-system-packages
```

**Q: AI analyzer 沒有生成信號**
- 檢查 `config/api_keys.json` 中 `minimax_chat` 是否正確
- 確認有未分析的新聞：`SELECT COUNT(*) FROM news_articles WHERE is_analyzed=0`

**Q: WebSocket 連接失敗**
- 確認服務器已啟動：`python3 src/websocket_server.py`
- 檢查端口：`lsof -i :8765`

**Q: Dashboard 空白**
- 先運行 collector + analyzer 填充數據
- 檢查數據庫：`SELECT COUNT(*) FROM news_articles`

## License

MIT
