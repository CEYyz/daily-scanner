"""
每日機會分析系統 v10
====================
新增：
  ✅ 買入點分析（支撐位 / MACD金叉+放量 / RSI穿越50）
  ✅ Reddit 改抓一週熱帖（讚數正確）
  ✅ Dcard 熱門討論
  ✅ PTT 熱門看板
  ✅ Google Trends 台灣搜尋量（生活/食衣住行）
  ✅ YouTube 台灣熱門類別
  ✅ TikTok 商品話題

執行：
  python daily_opportunity_v10.py
  python daily_opportunity_v10.py --time 09:00
"""

import sys, os, re, time, datetime, logging, warnings, subprocess, argparse, json
warnings.filterwarnings("ignore")

parser = argparse.ArgumentParser()
parser.add_argument("--time", type=str, default=None)
args = parser.parse_args()

if args.time:
    try:
        h, m = map(int, args.time.split(":"))
        now    = datetime.datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        wait_sec = (target - now).total_seconds()
        print(f"⏰  排程：{target.strftime('%Y-%m-%d %H:%M')} 執行（還有 {int(wait_sec//3600)}h {int((wait_sec%3600)//60)}m）")
        time.sleep(wait_sec)
    except ValueError:
        print("❌  格式錯誤，請用 HH:MM"); sys.exit(1)

PKGS = ["yfinance","requests","beautifulsoup4","pandas","tqdm","deep-translator","pytrends"]
for pkg in PKGS:
    imp = pkg.replace("beautifulsoup4","bs4").replace("deep-translator","deep_translator")
    try: __import__(imp)
    except ImportError:
        print(f"⚙️  安裝 {pkg}...")
        subprocess.check_call([sys.executable,"-m","pip","install",pkg,"-q"])

import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from deep_translator import GoogleTranslator
from pytrends.request import TrendReq

# ══ LOG ══════════════════════════════════════
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_filename = os.path.join(LOG_DIR, f"scan_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("scanner")
log.info("=" * 70)
log.info("🔥  每日機會分析系統 v10")
log.info(f"📅  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
log.info("=" * 70)

results = {}
HDR = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

STOCK_NAMES = {
    "3293.TWO":"鈊象電子", "00909.TW":"國泰智能電動車ETF",
    "0056.TW":"元大高股息", "6111.TWO":"6111擎亞",
    "00878.TW":"國泰永續高股息", "3017.TW":"奇鋐",
    "00713.TW":"元大高息低波", "00919.TW":"群益台灣精選高息",
    "NVDA":"NVIDIA", "GEV":"GE Vernova",
    "2330.TW":"台積電", "AMD":"AMD",
    "TSM":"台積電ADR", "2317.TW":"鴻海",
    "2530.TW":"華建", "MU":"美光",
    "LRCX":"科林研發", "00631L.TW":"元大台灣50正2",
    "00910.TW":"第一金太空衛星", "2308.TW":"台達電",
}

def safe_get(url, timeout=14, extra_headers=None):
    h = {**HDR, **(extra_headers or {})}
    try:
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"    ⚠️  {url.split('/')[2] if '/' in url else url} → {e}")
        return None

def translate(text, src="auto"):
    try: return GoogleTranslator(source=src, target="zh-TW").translate(str(text)[:500])
    except: return text

# ══ 技術指標 ══════════════════════════════════
def calc_rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(p).mean()
    l = (-d.clip(upper=0)).rolling(p).mean()
    return float((100 - 100/(1+g/l)).iloc[-1])

def calc_macd(s, f=12, slow=26, sig=9):
    ef = s.ewm(span=f,adjust=False).mean()
    es = s.ewm(span=slow,adjust=False).mean()
    ml = ef - es
    sl = ml.ewm(span=sig,adjust=False).mean()
    return float(ml.iloc[-1]), float(sl.iloc[-1]), float((ml-sl).iloc[-1])

def calc_bb(s, p=20, n=2):
    ma = s.rolling(p).mean()
    sd = s.rolling(p).std()
    return float((ma+n*sd).iloc[-1]), float(ma.iloc[-1]), float((ma-n*sd).iloc[-1])

def ma_trend(close):
    if len(close)<20: return "數據不足"
    p=float(close.iloc[-1])
    m5=float(close.iloc[-5:].mean()); m10=float(close.iloc[-10:].mean()); m20=float(close.iloc[-20:].mean())
    if p>m5>m10>m20: return "多頭排列"
    if p<m5<m10<m20: return "空頭排列"
    return "MA20上方" if p>m20 else "MA20下方"

def timeframe_dir(df):
    if df is None or len(df)<6: return "?"
    c=df["Close"].squeeze()
    r=float(c.iloc[-3:].mean()); p=float(c.iloc[-6:-3].mean())
    if r>p*1.005: return "↑"
    if r<p*0.995: return "↓"
    return "─"

def three_line_label(d,w,m):
    sc=sum(1 for x in [d,w,m] if x=="↑")-sum(1 for x in [d,w,m] if x=="↓")
    if sc==3:  return ("三線多頭","bullish3")
    if sc==2:  return ("偏多","bullish2")
    if sc==-3: return ("三線空頭","bearish3")
    if sc==-2: return ("偏空","bearish2")
    return ("多空分歧","neutral")

# ══ 買入點計算 ════════════════════════════════
def calc_entry_points(df_d, price, rsi, macd_line, macd_signal, macd_h, bbu, bbm, bbl, vr):
    """
    三種買入點條件，各自獨立計算
    不是 rule base 推薦，是客觀條件標注
    """
    signals = []
    close = df_d["Close"].squeeze()
    high  = df_d["High"].squeeze()
    low   = df_d["Low"].squeeze()

    # ── 1. 支撐位 / 壓力位 ──────────────────
    # 近20日低點（支撐）
    support_20  = float(low.iloc[-20:].min())
    resist_20   = float(high.iloc[-20:].max())
    # 近5日低點（近期支撐）
    support_5   = float(low.iloc[-5:].min())
    # MA20 支撐
    ma20_support = bbm  # bbm 就是 MA20

    # 距離支撐的 %
    dist_support = (price - support_20) / support_20 * 100
    dist_ma20    = (price - ma20_support) / ma20_support * 100

    support_signal = None
    if price <= support_20 * 1.005:
        support_signal = f"🎯 貼近20日支撐 ${support_20:,.1f}（距離{dist_support:.1f}%）"
    elif price <= ma20_support * 1.01:
        support_signal = f"👀 貼近MA20支撐 ${ma20_support:,.1f}（距離{dist_ma20:.1f}%）"
    elif price <= bbl * 1.01:
        support_signal = f"💡 貼近布林下軌 ${bbl:,.1f}"

    signals.append({
        "type": "支撐位",
        "support_20": support_20,
        "resist_20":  resist_20,
        "support_5":  support_5,
        "ma20":       ma20_support,
        "bb_lower":   bbl,
        "bb_upper":   bbu,
        "dist_support": dist_support,
        "signal":     support_signal,
        "triggered":  support_signal is not None
    })

    # ── 2. MACD 金叉 + 放量 ──────────────────
    # 判斷金叉：今天 macd_h > 0 且昨天 macd_h <= 0（剛剛金叉）
    if len(close) >= 27:
        close_sq = df_d["Close"].squeeze()
        ef_prev  = close_sq.iloc[:-1].ewm(span=12,adjust=False).mean()
        es_prev  = close_sq.iloc[:-1].ewm(span=26,adjust=False).mean()
        ml_prev  = ef_prev - es_prev
        sl_prev  = ml_prev.ewm(span=9,adjust=False).mean()
        h_prev   = float((ml_prev - sl_prev).iloc[-1])
        just_crossed = h_prev <= 0 < macd_h
    else:
        just_crossed = False

    macd_signal_txt = None
    if just_crossed and vr >= 1.3:
        macd_signal_txt = f"🎯 MACD剛金叉 + 放量{vr:.1f}x，買入信號最強"
    elif just_crossed:
        macd_signal_txt = f"👀 MACD剛金叉（量能{vr:.1f}x 尚未放量，等放量確認）"
    elif macd_h > 0 and vr >= 1.3:
        macd_signal_txt = f"👀 MACD持續向上 + 放量{vr:.1f}x"
    elif macd_h > 0:
        macd_signal_txt = f"➡️ MACD向上但未放量（{vr:.1f}x）"
    else:
        macd_signal_txt = f"❌ MACD向下（histogram {macd_h:.2f}）"

    signals.append({
        "type": "MACD金叉+放量",
        "macd_h": macd_h,
        "just_crossed": just_crossed,
        "vol_ratio": vr,
        "signal": macd_signal_txt,
        "triggered": just_crossed and vr >= 1.2
    })

    # ── 3. RSI 穿越50 ──────────────────────
    # 計算前一根的 RSI
    rsi_prev = None
    if len(close) >= 20:
        try:
            rsi_prev = float(calc_rsi(close.iloc[:-1]))
        except: pass

    rsi_signal_txt = None
    if rsi_prev is not None:
        if rsi_prev < 50 <= rsi:
            rsi_signal_txt = f"🎯 RSI剛突破50（{rsi_prev:.0f}→{rsi:.0f}），動能轉強"
        elif rsi_prev < 30 and rsi >= 30:
            rsi_signal_txt = f"👀 RSI從超賣回升（{rsi_prev:.0f}→{rsi:.0f}）"
        elif 45 <= rsi <= 55:
            rsi_signal_txt = f"➡️ RSI在50附近（{rsi:.0f}），方向待確認"
        elif rsi >= 70:
            rsi_signal_txt = f"⚠️ RSI超買（{rsi:.0f}），不宜追買"
        elif rsi <= 30:
            rsi_signal_txt = f"💡 RSI超賣（{rsi:.0f}），等止跌再進"
        else:
            rsi_signal_txt = f"RSI {rsi:.0f}"
    else:
        rsi_signal_txt = f"RSI {rsi:.0f}"

    signals.append({
        "type": "RSI穿越50",
        "rsi": rsi,
        "rsi_prev": rsi_prev,
        "signal": rsi_signal_txt,
        "triggered": rsi_prev is not None and rsi_prev < 50 <= rsi
    })

    # ── 綜合買入點評估 ─────────────────────
    triggered_count = sum(1 for s in signals if s["triggered"])
    if triggered_count == 3:
        entry_summary = "🎯🎯🎯 三條件同時滿足 — 強買入點"
        entry_key = "strong_buy"
    elif triggered_count == 2:
        entry_summary = "🎯🎯 兩條件滿足 — 觀察買入點"
        entry_key = "watch_buy"
    elif triggered_count == 1:
        entry_summary = "🎯 一條件滿足 — 待確認"
        entry_key = "weak_buy"
    else:
        entry_summary = "— 目前無買入信號"
        entry_key = "no_signal"

    # 建議進場區間
    entry_zone_low  = min(support_20, bbl, ma20_support) * 0.995
    entry_zone_high = min(support_20, bbl, ma20_support) * 1.015
    stop_loss       = support_20 * 0.97  # 支撐下方3%

    return {
        "signals": signals,
        "triggered_count": triggered_count,
        "entry_summary": entry_summary,
        "entry_key": entry_key,
        "entry_zone": f"${entry_zone_low:,.1f} ~ ${entry_zone_high:,.1f}",
        "stop_loss": f"${stop_loss:,.1f}",
        "resist_20": f"${resist_20:,.1f}",
    }

def stock_rating(s):
    score = 0
    tl = s["tl_key"]
    if tl=="bullish3": score+=3
    elif tl=="bullish2": score+=2
    elif tl=="bearish3": score-=3
    elif tl=="bearish2": score-=2
    if s["macd_h"]>0: score+=1
    if s["rsi"]>=75: score-=1
    if s["vr"]>=1.3 and s["pct"]>0: score+=1
    if s["vr"]>=1.3 and s["pct"]<0: score-=1
    if s.get("foreign_dir")=="外資買超": score+=1
    if s.get("foreign_dir")=="外資賣超": score-=1
    rg = s.get("rev_growth") or 0
    if rg>0.3: score+=1
    if rg<0: score-=1
    # 買入點加分
    ec = s.get("entry",{}).get("triggered_count",0)
    if ec>=2: score+=1
    if score>=5:   return ("強勢★★★","strong")
    if score>=3:   return ("稍強★★","mild_strong")
    if score>=1:   return ("中性★","neutral")
    if score>=-1:  return ("偏弱","mild_weak")
    return ("迴避","weak")

def stock_analysis_text(s):
    sections = {}
    pct=s["pct"]; rsi=s["rsi"]; mh=s["macd_h"]; vr=s["vr"]
    tl=s["tl"]; ma=s["ma_txt"]; pos=s["pos52"]
    pe=s["pe"]; rg=s["rev_growth"]; fd=s.get("foreign_dir","")

    # 技術面
    sit = f"日{s['dir_d']}週{s['dir_w']}月{s['dir_m']}，{ma}，52W位置{pos:.0f}%，RSI {rsi:.0f}"
    ana = []
    if s["dir_d"]==s["dir_w"]==s["dir_m"]=="↑": ana.append("三線同向向上")
    elif s["dir_d"]==s["dir_w"]==s["dir_m"]=="↓": ana.append("三線同向向下")
    else: ana.append("多空分歧")
    if rsi>=75: ana.append(f"RSI超買({rsi:.0f})")
    elif rsi<=30: ana.append(f"RSI超賣({rsi:.0f})")
    if mh>0: ana.append("MACD金叉")
    else: ana.append("MACD死叉")
    if pos>=90: res="接近52週高點，追高謹慎"
    elif pos<=10: res="接近52週低點"
    elif tl=="三線多頭" and mh>0: res="趨勢+動能雙強"
    elif tl=="三線空頭" and mh<0: res="趨勢+動能雙弱"
    else: res="訊號混合"
    sections["技術面"]={"情況":sit,"分析":"，".join(ana),"結果":res,"建議":"觀察量能確認" if "多頭" in tl else "等方向明朗"}

    # 基本面
    pe_s = f"PE {pe:.1f}" if pe else "PE 無"
    rg_s = f"營收 {rg*100:.0f}%" if rg else "營收 無"
    ana2=[]
    if pe:
        if pe<15: ana2.append("PE偏低估值便宜")
        elif pe>60: ana2.append("PE偏高需高成長支撐")
        else: ana2.append("PE合理")
    if rg:
        if rg>0.5: ana2.append(f"高速成長{rg*100:.0f}%")
        elif rg>0.1: ana2.append(f"穩定成長{rg*100:.0f}%")
        elif rg<0: ana2.append(f"營收衰退{rg*100:.0f}%")
    peg=(pe/(rg*100)) if (pe and rg and rg>0) else None
    res2=f"PEG {peg:.1f}，{'便宜' if peg and peg<1 else '偏貴' if peg and peg>2 else '中性'}" if peg else "數據不足"
    sections["基本面"]={"情況":f"{pe_s}，EPS {s['eps_txt'].replace('EPS:','')}，{rg_s}","分析":"，".join(ana2) if ana2 else "數據不足","結果":res2,"建議":"搭配技術面進出"}

    # 籌碼面
    ana3=[]
    if vr>=2: ana3.append("爆量主力動作明顯")
    elif vr>=1.3: ana3.append("放量資金流入")
    elif vr<=0.6: ana3.append("縮量觀望")
    else: ana3.append("量能正常")
    if fd=="外資買超": ana3.append("外資加碼")
    elif fd=="外資賣超": ana3.append("外資減碼")
    res3="放量上漲籌碼偏多" if (vr>=1.3 and pct>0) else ("放量下跌籌碼偏空" if (vr>=1.3 and pct<0) else "籌碼中性")
    sections["籌碼面"]={"情況":f"量能{vr:.1f}x，{'外資'+fd if fd else '外資盤後更新'}","分析":"，".join(ana3),"結果":res3,"建議":"放量方向可信度高"}

    return sections

# ══════════════════════════════════════════════
# ① CRYPTO
# ══════════════════════════════════════════════
CRYPTO = ["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD"]
log.info("\n① 🌕  CRYPTO")
crypto_list = []
for ticker in tqdm(CRYPTO, desc="  Crypto", ncols=65):
    try:
        df_d=yf.download(ticker,period="60d",interval="1d",progress=False,auto_adjust=True)
        df_w=yf.download(ticker,period="1y",interval="1wk",progress=False,auto_adjust=True)
        df_m=yf.download(ticker,period="3y",interval="1mo",progress=False,auto_adjust=True)
        if len(df_d)<26: continue
        close=df_d["Close"].squeeze()
        price=float(close.iloc[-1])
        pct=(price-float(close.iloc[-2]))/float(close.iloc[-2])*100
        vr=float(df_d["Volume"].iloc[-1])/float(df_d["Volume"].mean())
        rsi=calc_rsi(close)
        ml,ms,mh=calc_macd(close)
        bbu,bbm,bbl=calc_bb(close)
        dir_d=timeframe_dir(df_d); dir_w=timeframe_dir(df_w); dir_m=timeframe_dir(df_m)
        tl,tl_key=three_line_label(dir_d,dir_w,dir_m)
        entry=calc_entry_points(df_d,price,rsi,ml,ms,mh,bbu,bbm,bbl,vr)
        name=ticker.replace("-USD","")
        crypto_list.append(dict(name=name,price=price,pct=pct,vr=vr,
                                dir_d=dir_d,dir_w=dir_w,dir_m=dir_m,
                                tl=tl,tl_key=tl_key,rsi=rsi,macd_h=mh,
                                bbu=bbu,bbl=bbl,entry=entry))
        log.info(f"  {name:<6} ${price:>12,.2f} {pct:+6.2f}% 日{dir_d}週{dir_w}月{dir_m} {tl}")
        log.info(f"           買入點：{entry['entry_summary']}")
    except Exception as e:
        log.error(f"  {ticker}: {e}")
    time.sleep(0.3)
crypto_list.sort(key=lambda x:x["pct"],reverse=True)
results["crypto"]=crypto_list
log.info(f"  ✅ Crypto {len(crypto_list)} 筆")

# ══════════════════════════════════════════════
# ② 股票
# ══════════════════════════════════════════════
MY_STOCKS = [
    "3293.TWO","00909.TW","0056.TW","6111.TWO","00878.TW",
    "3017.TW","00713.TW","00919.TW",
    "NVDA","GEV","2330.TW","AMD","TSM",
    "2317.TW","2530.TW","MU","LRCX",
    "00631L.TW","00910.TW","2308.TW",
]
log.info("\n② 📈  股票")
stock_list=[]
for ticker in tqdm(MY_STOCKS,desc="  Stocks",ncols=65):
    try:
        tk=yf.Ticker(ticker)
        df_d=tk.history(period="1y",interval="1d",auto_adjust=True)
        df_w=tk.history(period="3y",interval="1wk",auto_adjust=True)
        df_m=tk.history(period="5y",interval="1mo",auto_adjust=True)
        if len(df_d)<26:
            log.warning(f"  {ticker}: 數據不足，跳過"); continue
        close=df_d["Close"].squeeze()
        price=float(close.iloc[-1])
        pct=(price-float(close.iloc[-2]))/float(close.iloc[-2])*100
        vr=float(df_d["Volume"].iloc[-1])/float(df_d["Volume"].mean())
        rsi=calc_rsi(close)
        ml,ms,mh=calc_macd(close)
        bbu,bbm,bbl=calc_bb(close)
        ma_txt=ma_trend(close)
        high52=float(df_d["High"].max()); low52=float(df_d["Low"].min())
        pos52=(price-low52)/(high52-low52)*100 if high52!=low52 else 50
        dir_d=timeframe_dir(df_d); dir_w=timeframe_dir(df_w); dir_m=timeframe_dir(df_m)
        tl,tl_key=three_line_label(dir_d,dir_w,dir_m)
        entry=calc_entry_points(df_d,price,rsi,ml,ms,mh,bbu,bbm,bbl,vr)
        pe=eps=rev_growth=None
        try:
            info=tk.info; pe=info.get("trailingPE"); eps=info.get("trailingEps"); rev_growth=info.get("revenueGrowth")
        except: pass
        pe_txt=f"PE:{pe:.1f}" if pe else "PE:--"
        eps_txt=f"EPS:{eps:.2f}" if eps else "EPS:--"
        rev_txt=f"營收:{rev_growth*100:.0f}%" if rev_growth else "營收:--"
        mkt="台" if (".TW" in ticker or ".TWO" in ticker) else "美"
        s=dict(
            ticker=ticker,name=STOCK_NAMES.get(ticker,ticker),mkt=mkt,
            price=price,pct=pct,vr=vr,
            dir_d=dir_d,dir_w=dir_w,dir_m=dir_m,tl=tl,tl_key=tl_key,
            rsi=rsi,macd_h=mh,bbu=bbu,bbl=bbl,
            ma_txt=ma_txt,pos52=pos52,
            pe=pe,eps=eps,rev_growth=rev_growth,
            pe_txt=pe_txt,eps_txt=eps_txt,rev_txt=rev_txt,
            foreign_net=None,foreign_dir="",entry=entry
        )
        rt,rk=stock_rating(s); s["rating"]=rt; s["rating_key"]=rk
        s["analysis"]=stock_analysis_text(s)
        stock_list.append(s)
        log.info(f"  [{mkt}] {ticker:<12} {STOCK_NAMES.get(ticker,ticker):<12} ${price:>10,.2f} {pct:+6.2f}% {tl}")
        log.info(f"           買入點：{entry['entry_summary']}  進場區：{entry['entry_zone']}  止損：{entry['stop_loss']}")
    except Exception as e:
        log.error(f"  {ticker}: {e}")
    time.sleep(0.4)
stock_list.sort(key=lambda x:x["pct"],reverse=True)
results["stocks"]=stock_list

# 外資
now_h=datetime.datetime.now().hour
if now_h>=16:
    try:
        today_str=datetime.datetime.now().strftime("%Y%m%d")
        r=safe_get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={today_str}&selectType=ALLBUT0999&response=json")
        if r:
            j=r.json(); fd={}
            for row in (j.get("data") or []):
                try: fd[row[0].strip()]=int(row[4].replace(",",""))-int(row[5].replace(",",""))
                except: pass
            for s in stock_list:
                code=s["ticker"].replace(".TW","").replace(".TWO","")
                if code in fd:
                    net=fd[code]; s["foreign_net"]=net
                    s["foreign_dir"]="外資買超" if net>0 else "外資賣超"
            for s in stock_list:
                s["rating"],s["rating_key"]=stock_rating(s)
    except Exception as e:
        log.warning(f"  外資失敗: {e}")
else:
    log.info(f"  ⏰ {now_h}:xx 外資 16:30 後更新")
log.info(f"  ✅ 股票 {len(stock_list)} 筆")

# ══════════════════════════════════════════════
# ③ 生活熱門趨勢（食衣住行娛樂）
# ══════════════════════════════════════════════
log.info("\n③ 🌟  生活熱門趨勢")
lifestyle_data = {
    "google_trends_tw": {},   # Google Trends 台灣
    "dcard": [],              # Dcard 熱門
    "ptt": [],                # PTT 熱門
    "youtube_tw": [],         # YouTube 台灣熱門
    "tiktok": [],             # TikTok
    "shopee": [],             # Shopee 熱銷
    "reddit_deals": [],       # Reddit 熱賣
}

# A. Google Trends 台灣 — 食衣住行娛樂
log.info("  📊 Google Trends 台灣（生活/食衣住行）...")
TW_LIFESTYLE = {
    "食品飲料":  ["珍珠奶茶","泡麵","外送","美食","手搖飲"],
    "服飾美妝":  ["穿搭","保養品","防曬","口紅","香水"],
    "居家生活":  ["空氣清淨機","掃地機器人","電動床","家具","收納"],
    "娛樂3C":   ["手機","耳機","遊戲","追劇","電影"],
    "健康運動":  ["健身","瑜珈","跑步","蛋白質","減脂"],
    "旅遊交通":  ["日本旅遊","機票","訂房","泰國","歐洲"],
}
try:
    pt=TrendReq(hl="zh-TW",tz=480,timeout=(10,25))
    for cat,kws in tqdm(TW_LIFESTYLE.items(),desc="  GTW",ncols=65):
        try:
            pt.build_payload(kws[:4],timeframe="now 7-d",geo="TW")
            df_t=pt.interest_over_time()
            if df_t.empty:
                lifestyle_data["google_trends_tw"][cat]={"score":0,"momentum":0,"top_kw":""}; continue
            scores={k:float(df_t[k].mean()) for k in kws[:4] if k in df_t.columns}
            top_kw=max(scores,key=scores.get) if scores else kws[0]
            recent=float(df_t[kws[:4]].iloc[-6:].mean().mean())
            week=float(df_t[kws[:4]].mean().mean())
            mom=(recent-week)/week*100 if week>0 else 0
            lifestyle_data["google_trends_tw"][cat]={"score":int(recent),"momentum":round(mom,1),"top_kw":top_kw,"kw_scores":scores}
            icon="🔥🔥🔥" if mom>20 else ("🔥🔥" if mom>5 else ("🔥" if mom>0 else "❄️"))
            log.info(f"  [{cat}] 熱度:{int(recent)} 動能:{mom:+.0f}% 最熱關鍵字：{top_kw} {icon}")
            time.sleep(2)
        except Exception as e:
            log.warning(f"  [{cat}] {e}")
            lifestyle_data["google_trends_tw"][cat]={"score":0,"momentum":0,"top_kw":""}
            time.sleep(3)
except Exception as e:
    log.warning(f"  pytrends: {e}")

# B. Dcard 熱門討論
log.info("  💬 Dcard 熱門...")
try:
    r=safe_get("https://www.dcard.tw/f/trending",extra_headers={"Accept-Language":"zh-TW,zh;q=0.9"})
    if r:
        soup=BeautifulSoup(r.text,"html.parser")
        dcard_items=[]
        for tag in soup.find_all(["h2","h3","a"],limit=60):
            t=tag.get_text(strip=True)
            if 10<len(t)<100 and "Dcard" not in t:
                dcard_items.append(t)
        dcard_items=list(dict.fromkeys(dcard_items))[:10]
        # 備用：Dcard API
        if len(dcard_items)<3:
            r2=safe_get("https://www.dcard.tw/service/api/v2/posts?popular=true&limit=10")
            if r2:
                j=r2.json()
                if isinstance(j,list):
                    for p in j[:10]:
                        t=p.get("title","")
                        if t: dcard_items.append(t[:80])
        for i,t in enumerate(dcard_items[:8],1):
            log.info(f"  [Dcard] #{i} {t}")
            lifestyle_data["dcard"].append({"rank":i,"title":t})
except Exception as e:
    log.warning(f"  Dcard: {e}")

# C. PTT 熱門（八卦/Stock/beauty/movie）
log.info("  📋 PTT 熱門...")
PTT_BOARDS = ["Gossiping","Stock","beauty","movie","food"]
for board in PTT_BOARDS:
    try:
        r=safe_get(f"https://www.ptt.cc/bbs/{board}/index.html",
                   extra_headers={"Cookie":"over18=1"})
        if not r: continue
        soup=BeautifulSoup(r.text,"html.parser")
        for item in soup.find_all("div",class_="r-ent")[:5]:
            title_tag=item.find("a")
            pop_tag=item.find("div",class_="nrec")
            if not title_tag: continue
            title=title_tag.get_text(strip=True)
            pop=pop_tag.get_text(strip=True) if pop_tag else "0"
            if title:
                log.info(f"  [PTT/{board}] [{pop}] {title[:60]}")
                lifestyle_data["ptt"].append({"board":board,"title":title[:80],"pop":pop})
        time.sleep(0.5)
    except Exception as e:
        log.warning(f"  PTT {board}: {e}")

# D. YouTube 台灣熱門（改用更精準的regex）
log.info("  📺 YouTube 台灣熱門...")
r=safe_get("https://www.youtube.com/feed/trending?gl=TW&hl=zh-TW")
yt_titles=[]
YT_BLACKLIST={"輸入搜尋字詞，開始使用 YouTube","鍵盤快速鍵","YouTube","搜尋","首頁","Shorts","訂閱","媒體庫","近期觀看","稍後觀看"}
if r:
    # 從 ytInitialData 抓 videoRenderer
    matches=re.findall(r'"videoRenderer".*?"title"\s*:\s*\{"runs"\s*:\s*\[\{"text"\s*:\s*"([^"]{5,100})"',r.text)
    for t in matches:
        if t not in YT_BLACKLIST and not t.startswith("http"):
            yt_titles.append(t)
        if len(yt_titles)>=10: break
    # 備用
    if not yt_titles:
        matches2=re.findall(r'"simpleText"\s*:\s*"([^"]{8,100})"',r.text)
        for t in matches2:
            if t not in YT_BLACKLIST and not re.match(r'^[\d,]+$',t):
                yt_titles.append(t)
            if len(yt_titles)>=10: break
yt_titles=list(dict.fromkeys(yt_titles))
for i,t in enumerate(yt_titles[:8],1):
    log.info(f"  [YouTube TW] #{i} {t}")
    lifestyle_data["youtube_tw"].append({"rank":i,"title":t})

# E. TikTok 商品話題
log.info("  🎵 TikTok...")
tiktok_items=[]
for url in ["https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en",
            "https://www.tiktok.com/tag/trending"]:
    r=safe_get(url)
    if not r: continue
    soup=BeautifulSoup(r.text,"html.parser")
    for tag in soup.find_all(["span","a","p"],limit=100):
        t=tag.get_text(strip=True)
        if t.startswith("#") and 2<len(t)<50:
            tiktok_items.append(t)
    tiktok_items=list(dict.fromkeys(tiktok_items))
    if tiktok_items: break
    time.sleep(1)
if not tiktok_items:
    r=safe_get("https://news.google.com/rss/search?q=tiktok+trending+products+taiwan&hl=zh-TW&gl=TW&ceid=TW:zh-Hant&tbs=qdr:d")
    if r:
        soup=BeautifulSoup(r.text,"html.parser")
        for item in soup.find_all("item")[:6]:
            tt=item.find("title")
            if tt:
                t=re.sub(r'\s+-\s+[^-]{2,30}$','',tt.get_text(strip=True)).strip()
                tiktok_items.append(t[:60])
for i,t in enumerate(tiktok_items[:8],1):
    log.info(f"  [TikTok] #{i} {t}")
    lifestyle_data["tiktok"].append({"rank":i,"tag":t})

# F. Shopee 台灣熱銷（具體商品+品牌+型號）
log.info("  🛍️  Shopee 台灣熱銷...")
SHOPEE_CATS=[("3C配件","11036246"),("美妝保養","11036279"),
             ("家電","11036239"),("服飾","11036257"),("食品飲料","11036228")]
for cat_name,cat_id in tqdm(SHOPEE_CATS,desc="  Shopee",ncols=65):
    try:
        r=requests.get(
            f"https://shopee.tw/api/v4/recommend/recommend?bundle=category_landing_page&cat_id={cat_id}&limit=10&offset=0&sort_type=2",
            headers={"User-Agent":HDR["User-Agent"],"Referer":"https://shopee.tw/"},timeout=12)
        if r.status_code!=200: continue
        j=r.json()
        items=j.get("data",{}).get("sections",[{}])[0].get("data",{}).get("item",[])
        for i,item in enumerate(items[:5],1):
            name=item.get("name","")[:60]
            price=item.get("price",0)/100000
            sold=item.get("historical_sold",item.get("sold",0))
            rating=item.get("item_rating",{}).get("rating_star",0)
            if name:
                log.info(f"  [Shopee {cat_name}] #{i} {name} NT${price:,.0f} 售:{sold} ⭐{rating:.1f}")
                lifestyle_data["shopee"].append({"category":cat_name,"rank":i,"name":name,"price":price,"sold":sold,"rating":rating})
    except Exception as e:
        log.warning(f"  Shopee [{cat_name}]: {e}")
    time.sleep(1)

# G. Reddit 熱賣（改成 t=week 才有真實讚數）
log.info("  💬 Reddit 熱賣（本週）...")
for sub in ["deals","shutupandtakemymoney","BuyItForLife"]:
    try:
        r=requests.get(f"https://www.reddit.com/r/{sub}/top.json?limit=5&t=week",
                       headers={"User-Agent":"DailyScanner/3.0"},timeout=10)
        if r.status_code!=200: continue
        for p in r.json()["data"]["children"]:
            d=p["data"]
            log.info(f"  [r/{sub}] [{d['score']:>5}👍] {d['title'][:65]}")
            lifestyle_data["reddit_deals"].append({"sub":sub,"score":d["score"],"title":d["title"][:80]})
        time.sleep(1)
    except Exception as e:
        log.error(f"  r/{sub}: {e}")

results["lifestyle"]=lifestyle_data
log.info(f"  ✅ 生活趨勢完成")

# ══════════════════════════════════════════════
# ④ 消息面（四國新聞）
# ══════════════════════════════════════════════
log.info("\n④ 📰  消息面")
content_list=[]
GNEWS={
    "🇹🇼 台灣":("https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",None),
    "🇯🇵 日本":("https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja","ja"),
    "🇰🇷 韓國":("https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko","ko"),
    "🇺🇸 美國":("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",None),
}
for region,(url,lang) in GNEWS.items():
    r=safe_get(url)
    if not r: continue
    soup=BeautifulSoup(r.text,"html.parser")
    for i,item in enumerate(soup.find_all("item")[:6],1):
        tt=item.find("title")
        if not tt: continue
        title=re.sub(r'\s+-\s+[^-]{2,30}$','',tt.get_text(strip=True)).strip()
        if lang:
            zh=translate(title,src=lang)
            content_list.append(dict(source=region,title=zh,original=title,heat=80-i*8))
            log.info(f"  [{region}] {zh}")
        else:
            content_list.append(dict(source=region,title=title,original=title,heat=80-i*8))
            log.info(f"  [{region}] {title}")
    time.sleep(0.5)

# Reddit 財經（改成 t=week）
for sub in ["artificial","ChatGPT","stocks","investing"]:
    try:
        r=requests.get(f"https://www.reddit.com/r/{sub}/top.json?limit=5&t=week",
                       headers={"User-Agent":"DailyScanner/3.0"},timeout=10)
        if r.status_code!=200: continue
        for p in r.json()["data"]["children"]:
            d=p["data"]
            content_list.append(dict(source=f"Reddit r/{sub}",title=d["title"],original=d["title"],heat=d["score"]))
            log.info(f"  [r/{sub}] [{d['score']:>5}👍] {d['title'][:60]}")
        time.sleep(1)
    except: pass

content_list.sort(key=lambda x:x["heat"],reverse=True)
results["content"]=content_list

# ══════════════════════════════════════════════
# ⑤ 四國關鍵字統計
# ══════════════════════════════════════════════
COUNTRY_SOURCES={
    "🇺🇸 美國":["https://finance.yahoo.com/news/","https://apnews.com/business"],
    "🇯🇵 日本":["https://finance.yahoo.co.jp/news/","https://www.nikkei.com/"],
    "🇰🇷 韓國":["https://koreajoongangdaily.joins.com/section/business","https://www.koreatimes.co.kr/www/biz/"],
    "🇹🇼 台灣":["https://tw.stock.yahoo.com/news/","https://www.moneydj.com/KMDJ/News/NewsViewer.aspx?a=mb010000"],
}
KEYWORDS={
    "AI/科技":["AI","人工智能","ChatGPT","chip","半導體","semiconductor","NVIDIA","AMD","tech","科技"],
    "加密貨幣":["crypto","bitcoin","BTC","ETH","blockchain","加密","幣"],
    "電動車":["EV","Tesla","electric","電動","battery","BYD"],
    "ETF/基金":["ETF","fund","基金","dividend","yield","指數","配息"],
    "總經/利率":["Fed","rate","inflation","GDP","通膨","升息","降息","economy","利率","關稅","tariff"],
    "地緣政治":["war","戰爭","Iran","伊朗","Hormuz","Ukraine","烏克蘭","strike","攻擊"],
}
def fetch_headlines(url):
    r=safe_get(url)
    if not r: return []
    soup=BeautifulSoup(r.text,"html.parser")
    out=[]
    for tag in soup.find_all(["h3","h2","h1","a"],limit=80):
        t=tag.get_text(strip=True)
        if 8<len(t)<200: out.append(t)
    return list(dict.fromkeys(out))[:30]

country_results={}; all_cats={}
for country in list(COUNTRY_SOURCES.keys()):
    all_h=[]
    for url in COUNTRY_SOURCES[country]:
        all_h+=fetch_headlines(url); time.sleep(0.8)
    all_h=list(dict.fromkeys(all_h))
    kw={k:0 for k in KEYWORDS}
    for hl in all_h:
        for cat,words in KEYWORDS.items():
            if any(w.lower() in hl.lower() for w in words): kw[cat]+=1
    total=len(all_h) or 1
    hot=[(cat,cnt,round(cnt/total*100,1)) for cat,cnt in sorted(kw.items(),key=lambda x:-x[1]) if cnt>0]
    country_results[country]=hot
    for cat,cnt,_ in hot: all_cats[cat]=all_cats.get(cat,0)+1
results["trends"]=country_results; results["all_cats"]=all_cats

# ══════════════════════════════════════════════
# HTML 報告
# ══════════════════════════════════════════════
log.info("\n🖥️  產生 HTML 報告...")
REPORT_DATE=datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

def tl_color(k): return {"bullish3":"#1a9e5c","bullish2":"#5cb85c","neutral":"#f0ad4e","bearish2":"#e8834a","bearish3":"#d9534f"}.get(k,"#888")
def rt_color(k): return {"strong":"#1a9e5c","mild_strong":"#5cb85c","neutral":"#f0ad4e","mild_weak":"#e8834a","weak":"#d9534f"}.get(k,"#888")
def pc(p): return "#1a9e5c" if p>=3 else ("#5cb85c" if p>=0 else ("#e8834a" if p>=-3 else "#d9534f"))
def entry_color(k): return {"strong_buy":"#1a9e5c","watch_buy":"#f0ad4e","weak_buy":"#3a7bd5","no_signal":"#555"}.get(k,"#555")

def build_html():
    # Crypto
    crypto_html=""
    for c in results["crypto"]:
        e=c["entry"]
        ec=entry_color(e["entry_key"])
        crypto_html+=f"""
        <div class="crypto-card">
          <div class="crypto-name">{c['name']}</div>
          <div class="crypto-price">${c['price']:,.2f}</div>
          <div style="color:{pc(c['pct'])};font-weight:700">{c['pct']:+.2f}%</div>
          <div style="margin:6px 0"><span class="tl-badge" style="background:{tl_color(c['tl_key'])}">{c['tl']}</span></div>
          <div style="color:{ec};font-size:0.78rem;margin-top:4px">{e['entry_summary']}</div>
          <div style="color:#666;font-size:0.75rem">進場：{e['entry_zone']}</div>
        </div>"""

    # 股票總表
    rows_html=""
    for s in results["stocks"]:
        e=s["entry"]; ec=entry_color(e["entry_key"])
        fd=s.get("foreign_dir","—"); fdc="#1a9e5c" if "買超" in fd else ("#d9534f" if "賣超" in fd else "#888")
        vrc="#d9534f" if s["vr"]>=2 else ("#1a9e5c" if s["vr"]>=1.3 else ("#888" if s["vr"]<=0.6 else "#ccc"))
        rows_html+=f"""
        <tr>
          <td><b>{s['ticker']}</b><br><small style="color:#888">{s['name']}</small></td>
          <td>${s['price']:,.2f}</td>
          <td style="color:{pc(s['pct'])};font-weight:700">{s['pct']:+.2f}%</td>
          <td><span class="tl-badge" style="background:{tl_color(s['tl_key'])}">{s['tl']}</span></td>
          <td><span class="rsi-badge {'rsi-overbought' if s['rsi']>=75 else 'rsi-oversold' if s['rsi']<=30 else 'rsi-normal'}">RSI {s['rsi']:.0f}</span></td>
          <td style="color:{fdc}">{fd}</td>
          <td style="color:{vrc}">{s['vr']:.1f}x</td>
          <td><span class="rating-badge" style="background:{rt_color(s['rating_key'])}">{s['rating']}</span></td>
          <td style="color:{ec};font-size:0.8rem">{e['entry_summary'].split('—')[0].strip()}</td>
        </tr>"""

    # 個股詳細
    detail_html=""
    for s in results["stocks"]:
        e=s["entry"]; ec=entry_color(e["entry_key"])
        ana=s.get("analysis",{})
        sig_html=""
        for sig in e["signals"]:
            sc="#1a9e5c" if sig["triggered"] else "#888"
            sig_html+=f'<div style="color:{sc};font-size:0.82rem;margin:3px 0">{"✅" if sig["triggered"] else "⭕"} <b>{sig["type"]}</b>：{sig["signal"]}</div>'
        detail_html+=f"""
        <div class="stock-detail">
          <div class="stock-detail-header">
            <div>
              <span class="stock-code">{s['ticker']}</span>
              <span class="stock-name">{s['name']}</span>
              <span class="tl-badge" style="background:{tl_color(s['tl_key'])}">{s['tl']}</span>
            </div>
            <div style="text-align:right">
              <div style="font-size:1.2rem;font-weight:700;color:{pc(s['pct'])}">{s['pct']:+.2f}%  ${s['price']:,.2f}</div>
              <span class="rating-badge" style="background:{rt_color(s['rating_key'])}">{s['rating']}</span>
            </div>
          </div>
          <div class="entry-box" style="border-color:{ec}">
            <div style="font-weight:700;color:{ec};margin-bottom:6px">🎯 買入點分析</div>
            {sig_html}
            <div style="margin-top:8px;font-size:0.82rem">
              <span style="color:#888">進場參考區間：</span><b style="color:{ec}">{e['entry_zone']}</b>
              <span style="color:#888;margin-left:12px">止損參考：</span><b style="color:#d9534f">{e['stop_loss']}</b>
              <span style="color:#888;margin-left:12px">近期壓力：</span><b style="color:#f0ad4e">{e['resist_20']}</b>
            </div>
          </div>
          <div class="analysis-grid">"""
        for face,content in ana.items():
            icons={"技術面":"📈","基本面":"💰","籌碼面":"🔬"}
            detail_html+=f"""
            <div class="analysis-card">
              <div class="analysis-face">{icons.get(face,'')} {face}</div>
              <div class="analysis-row"><span class="al">情況</span><span>{content.get('情況','')}</span></div>
              <div class="analysis-row"><span class="al">分析</span><span>{content.get('分析','')}</span></div>
              <div class="analysis-row"><span class="al">結果</span><span><b>{content.get('結果','')}</b></span></div>
              <div class="analysis-row"><span class="al">建議</span><span style="color:#5cb85c">{content.get('建議','')}</span></div>
            </div>"""
        detail_html+="</div></div>"

    # Google Trends 台灣生活
    gt_html=""
    for cat,data in sorted(results["lifestyle"]["google_trends_tw"].items(),key=lambda x:x[1].get("score",0),reverse=True):
        sc=data.get("score",0); mom=data.get("momentum",0); top=data.get("top_kw","")
        bc="#1a9e5c" if mom>5 else ("#d9534f" if mom<-5 else "#f0ad4e")
        bw=min(sc,100)
        gt_html+=f"""
        <div class="trend-card">
          <div class="trend-header"><span class="trend-cat">{cat}</span><span style="color:{bc};font-weight:700">{mom:+.0f}%</span></div>
          <div class="trend-bar-bg"><div class="trend-bar" style="width:{bw}%;background:{bc}"></div></div>
          <div style="color:#888;font-size:0.78rem">熱度:{sc}  最熱：<b style="color:#fff">{top}</b></div>
        </div>"""

    # Shopee
    shopee_html=""; by_cat={}
    for item in results["lifestyle"]["shopee"]:
        by_cat.setdefault(item["category"],[]).append(item)
    for cat,items in by_cat.items():
        shopee_html+=f'<div class="shopee-cat">{cat}</div>'
        for item in items[:3]:
            shopee_html+=f"""
            <div class="shopee-item">
              <span class="shopee-rank">#{item['rank']}</span>
              <span class="shopee-name">{item['name']}</span>
              <span class="shopee-price">NT${item['price']:,.0f}</span>
              <span class="shopee-sold">售{item['sold']}</span>
            </div>"""

    # Dcard + PTT
    dcard_html="".join(f'<div class="social-item"><span class="social-src">Dcard</span>{d["title"]}</div>' for d in results["lifestyle"]["dcard"][:6])
    ptt_html="".join(f'<div class="social-item"><span class="social-src">PTT/{d["board"]}</span>[{d["pop"]}] {d["title"][:50]}</div>' for d in results["lifestyle"]["ptt"][:8])
    yt_html="".join(f'<div class="social-item"><span class="social-src">YT台灣</span>#{d["rank"]} {d["title"][:55]}</div>' for d in results["lifestyle"]["youtube_tw"][:6])
    tiktok_html="".join(f'<div class="social-item"><span class="social-src">TikTok</span>{d["tag"]}</div>' for d in results["lifestyle"]["tiktok"][:8])

    # Reddit deals（本週 = 真實讚數）
    deals_html="".join(f'<div class="deal-item"><span class="deal-score">{d["score"]}👍</span><span class="deal-sub">r/{d["sub"]}</span><span>{d["title"][:65]}</span></div>' for d in sorted(results["lifestyle"]["reddit_deals"],key=lambda x:x["score"],reverse=True)[:8])

    # 四國新聞
    news_html=""
    src_colors={"🇹🇼 台灣":"#1a9e5c","🇯🇵 日本":"#e8834a","🇰🇷 韓國":"#3a7bd5","🇺🇸 美國":"#5a5a9e"}
    for c in results["content"][:15]:
        sc=src_colors.get(c["source"],"#888")
        news_html+=f'<div class="news-item"><span class="news-src" style="background:{sc}">{c["source"]}</span><span class="news-title">{c["title"]}</span></div>'

    hot_html=""
    for cat,n in sorted(results["all_cats"].items(),key=lambda x:-x[1]):
        if n>=2:
            hot_html+=f'<div class="hot-row"><span class="hot-cat">{cat}</span><div class="hot-bar-bg"><div class="hot-bar" style="width:{n/4*100}%"></div></div><span class="hot-n">{n}/4</span></div>'

    return f"""<!DOCTYPE html>
<html lang="zh-TW"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>每日機會分析 {REPORT_DATE}</title>
<style>
:root{{--bg:#0f1117;--card:#1a1d27;--card2:#22263a;--text:#e8eaf0;--muted:#8890a4;--border:#2e3450;--green:#1a9e5c;--red:#d9534f;--yellow:#f0ad4e;--blue:#3a7bd5;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI','PingFang TC',sans-serif;padding:20px;max-width:1400px;margin:0 auto;}}
h1{{font-size:1.6rem;font-weight:800;margin-bottom:4px;}}
h2{{font-size:1.05rem;font-weight:700;color:var(--muted);margin:28px 0 12px;border-left:3px solid var(--blue);padding-left:10px;text-transform:uppercase;letter-spacing:0.05em;}}
h3{{font-size:0.88rem;font-weight:600;color:var(--muted);margin:14px 0 8px;}}
.header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--border);}}
.date{{color:var(--muted);font-size:0.85rem;}}
.table-wrap{{overflow-x:auto;}}
table{{width:100%;border-collapse:collapse;font-size:0.85rem;}}
th{{background:var(--card2);color:var(--muted);padding:10px 12px;text-align:left;font-weight:600;white-space:nowrap;}}
td{{padding:9px 12px;border-bottom:1px solid var(--border);vertical-align:middle;}}
tr:hover td{{background:var(--card2);}}
.tl-badge{{display:inline-block;padding:2px 8px;border-radius:10px;color:#fff;font-size:0.75rem;font-weight:600;white-space:nowrap;}}
.rating-badge{{display:inline-block;padding:2px 10px;border-radius:10px;color:#fff;font-size:0.78rem;font-weight:700;}}
.rsi-badge{{display:inline-block;padding:2px 8px;border-radius:8px;font-size:0.75rem;font-weight:600;}}
.rsi-overbought{{background:#d9534f22;color:#d9534f;border:1px solid #d9534f44;}}
.rsi-oversold{{background:#1a9e5c22;color:#1a9e5c;border:1px solid #1a9e5c44;}}
.rsi-normal{{background:#88888822;color:#aaa;border:1px solid #88888844;}}
.crypto-row{{display:flex;gap:12px;flex-wrap:wrap;}}
.crypto-card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;min-width:140px;flex:1;text-align:center;}}
.crypto-name{{font-weight:800;font-size:1.05rem;}}
.crypto-price{{color:var(--muted);font-size:0.85rem;margin:3px 0;}}
.stock-detail{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:12px;}}
.stock-detail-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;}}
.stock-code{{font-size:1.05rem;font-weight:800;margin-right:6px;}}
.stock-name{{color:var(--muted);margin-right:6px;font-size:0.9rem;}}
.entry-box{{background:var(--card2);border:1px solid;border-radius:8px;padding:12px;margin-bottom:12px;}}
.analysis-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;}}
.analysis-card{{background:var(--card2);border-radius:8px;padding:12px;}}
.analysis-face{{font-weight:700;margin-bottom:8px;color:var(--blue);font-size:0.85rem;}}
.analysis-row{{font-size:0.8rem;margin-bottom:5px;display:flex;gap:6px;line-height:1.4;}}
.al{{color:var(--muted);min-width:28px;flex-shrink:0;}}
.trend-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;}}
.trend-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;}}
.trend-header{{display:flex;justify-content:space-between;margin-bottom:6px;font-size:0.88rem;}}
.trend-cat{{font-weight:700;}}
.trend-bar-bg{{background:#2e3450;border-radius:4px;height:5px;margin:5px 0;}}
.trend-bar{{height:5px;border-radius:4px;}}
.shopee-cat{{font-weight:700;color:var(--yellow);margin:10px 0 5px;font-size:0.85rem;}}
.shopee-item{{display:flex;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:0.8rem;}}
.shopee-rank{{color:var(--muted);min-width:22px;}}
.shopee-name{{flex:1;}}
.shopee-price{{color:var(--green);font-weight:600;}}
.shopee-sold{{color:var(--muted);min-width:55px;text-align:right;}}
.social-item{{display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--border);font-size:0.82rem;line-height:1.4;}}
.social-src{{display:inline-block;padding:1px 7px;border-radius:8px;background:var(--blue);color:#fff;font-size:0.7rem;white-space:nowrap;flex-shrink:0;margin-top:1px;}}
.news-item{{display:flex;gap:8px;align-items:flex-start;padding:7px 0;border-bottom:1px solid var(--border);font-size:0.83rem;}}
.news-src{{display:inline-block;padding:2px 8px;border-radius:8px;color:#fff;font-size:0.7rem;white-space:nowrap;flex-shrink:0;}}
.news-title{{line-height:1.4;}}
.hot-row{{display:flex;align-items:center;gap:10px;margin-bottom:7px;font-size:0.85rem;}}
.hot-cat{{min-width:90px;font-weight:600;}}
.hot-bar-bg{{flex:1;background:#2e3450;border-radius:4px;height:7px;}}
.hot-bar{{height:7px;border-radius:4px;background:var(--blue);}}
.hot-n{{color:var(--muted);min-width:40px;text-align:right;}}
.deal-item{{display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--border);font-size:0.8rem;}}
.deal-score{{color:var(--green);font-weight:700;min-width:60px;flex-shrink:0;}}
.deal-sub{{color:var(--blue);min-width:90px;flex-shrink:0;}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:14px;}}
.three-col{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;}}
@media(max-width:900px){{.two-col,.three-col{{grid-template-columns:1fr;}}}}
</style></head><body>

<div class="header">
  <div><h1>📊 每日機會分析報告</h1><div class="date">{REPORT_DATE}</div></div>
</div>

<h2>🌕 Crypto 三線 + 買入點</h2>
<div class="crypto-row">{crypto_html}</div>

<h2>📈 股票評級總表</h2>
<div class="table-wrap"><table>
  <thead><tr><th>標的</th><th>價格</th><th>漲跌</th><th>三線</th><th>RSI</th><th>外資</th><th>量能</th><th>評級</th><th>買入點</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table></div>

<h2>📝 個股詳細分析（技術/基本/籌碼 + 買入點）</h2>
{detail_html}

<h2>🌟 生活熱門趨勢（食衣住行娛樂）</h2>
<h3>Google Trends 台灣 — 各生活類別搜尋熱度（7天）</h3>
<div class="trend-grid">{gt_html}</div>

<div class="three-col" style="margin-top:14px">
  <div class="card"><h3>💬 Dcard 熱門討論</h3>{dcard_html or '<div style="color:var(--muted)">未取得</div>'}</div>
  <div class="card"><h3>📋 PTT 熱門</h3>{ptt_html or '<div style="color:var(--muted)">未取得</div>'}</div>
  <div class="card"><h3>📺 YouTube 台灣熱門</h3>{yt_html or '<div style="color:var(--muted)">未取得</div>'}</div>
</div>

<div class="two-col" style="margin-top:14px">
  <div class="card"><h3>🎵 TikTok 熱門話題</h3>{tiktok_html or '<div style="color:var(--muted)">未取得</div>'}</div>
  <div class="card"><h3>💬 Reddit 本週熱賣（真實讚數）</h3>{deals_html or '<div style="color:var(--muted)">未取得</div>'}</div>
</div>

<div class="card" style="margin-top:14px"><h3>🛍️ Shopee 台灣熱銷（具體商品）</h3>{shopee_html or '<div style="color:var(--muted)">未取得</div>'}</div>

<h2>🌏 四國消息面</h2>
<div class="two-col">
  <div class="card"><h3>四國共同話題熱度</h3>{hot_html}</div>
  <div class="card"><h3>今日重要新聞</h3>{news_html}</div>
</div>

</body></html>"""

html=build_html()
html_fname=f"報告_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.html"
with open(html_fname,"w",encoding="utf-8") as f: f.write(html)

rows=[]
for s in results["stocks"]:
    e=s["entry"]
    rows.append({"標的":s["ticker"],"名稱":s["name"],"價格":s["price"],"漲跌%":round(s["pct"],2),
                 "三線":s["tl"],"RSI":round(s["rsi"],1),"MACD":"↑" if s["macd_h"]>0 else "↓",
                 "均線":s["ma_txt"],"52W":f"{s['pos52']:.0f}%","PE":s["pe_txt"],
                 "EPS":s["eps_txt"],"營收":s["rev_txt"],"量能":f"{s['vr']:.1f}x",
                 "外資":s.get("foreign_dir",""),"評級":s["rating"],
                 "買入點":e["entry_summary"],"進場區間":e["entry_zone"],"止損":e["stop_loss"]})
csv_fname=f"機會分析_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv"
pd.DataFrame(rows).to_csv(csv_fname,index=False,encoding="utf-8-sig")

log.info(f"\n✅  HTML：{html_fname}")
log.info(f"✅  CSV：{csv_fname}")
log.info(f"📝  Log：{log_filename}")
print(f"\n🌐  用瀏覽器開啟：{os.path.abspath(html_fname)}")