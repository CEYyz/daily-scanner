"""
telegram_notify.py
==================
讀取最新的分析結果，推送重點到 Telegram
需要設定兩個 GitHub Secrets：
  TELEGRAM_BOT_TOKEN  — Bot Token（從 @BotFather 取得）
  TELEGRAM_CHAT_ID    — 你的 Chat ID（從 @userinfobot 取得）
"""

import os, json, glob, re, datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID","")

if not BOT_TOKEN or not CHAT_ID:
    print("⚠️  未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，跳過推送")
    exit(0)

import requests

def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)
    if r.status_code != 200:
        print(f"Telegram 失敗：{r.text}")
    return r.status_code == 200

# ── 讀取最新 CSV ───────────────────────────────
csv_files = sorted(glob.glob("機會分析_*.csv"))
if not csv_files:
    send("⚠️ 今日分析完成，但找不到 CSV 檔案")
    exit(0)

import pandas as pd
df = pd.read_csv(csv_files[-1], encoding="utf-8-sig")
stocks = df[df["類型"].str.startswith("股票")]

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

# ── 讀取最新 LOG 抓買入點資訊 ──────────────────
log_files = sorted(glob.glob("logs/scan_*.log"))
buy_signals = []
if log_files:
    with open(log_files[-1], encoding="utf-8") as f:
        for line in f:
            if "🎯🎯🎯" in line or "🎯🎯" in line:
                # 抓標的名稱
                m = re.search(r'\[..\] (\S+)\s+(\S+)', line)
                if m:
                    buy_signals.append(f"{m.group(1)} {m.group(2)}")
            if "買入點：" in line and ("🎯🎯🎯" in line or "🎯🎯" in line):
                buy_signals.append(line.split("買入點：")[-1].strip()[:60])

# ── 組合訊息 ──────────────────────────────────
# 訊息1：標題 + 市場概況
msg1 = f"""📊 <b>每日機會分析報告</b>
🕐 {now} (台灣時間)

<b>股票強弱概況：</b>"""

strong, weak = [], []
for _, row in stocks.iterrows():
    ticker = str(row.get("標的",""))
    name   = str(row.get("名稱",""))
    pct    = row.get("漲跌%", 0)
    rating = str(row.get("評級",""))
    tl     = str(row.get("三線",""))
    try: pct = float(pct)
    except: pct = 0
    if "強" in rating or "三線多頭" in tl:
        strong.append(f"  🟢 {ticker} {name} {pct:+.2f}%")
    elif "迴避" in rating or "三線空頭" in tl:
        weak.append(f"  🔴 {ticker} {name} {pct:+.2f}%")

if strong:
    msg1 += "\n<b>強勢：</b>\n" + "\n".join(strong[:5])
if weak:
    msg1 += "\n<b>迴避：</b>\n" + "\n".join(weak[:3])

send(msg1)

# 訊息2：買入點信號（最重要的部分）
if buy_signals:
    unique_signals = list(dict.fromkeys(buy_signals))[:6]
    msg2 = "🎯 <b>今日買入點信號</b>\n\n"
    msg2 += "\n".join(f"  • {s}" for s in unique_signals)
    msg2 += "\n\n<i>以上為技術條件標注，非投資建議</i>"
    send(msg2)
else:
    send("🎯 <b>買入點</b>\n今日無明確買入信號，建議觀望")

# 訊息3：完整報告連結
# 把你的 GitHub username 和 repo name 填進去
GITHUB_USER = os.environ.get("GITHUB_REPOSITORY","your-username/your-repo").split("/")[0]
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY","your-username/your-repo").split("/")[-1]
report_url  = f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}/"

msg3 = f"""🌐 <b>完整報告</b>
{report_url}

📁 包含：
  • 所有股票三線+買入點分析
  • 個股技術/基本/籌碼四面分析
  • 台灣生活趨勢（Dcard/PTT/YouTube）
  • 四國新聞消息面"""
send(msg3)

print("✅ Telegram 推送完成")
