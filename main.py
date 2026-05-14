import os
import time
import requests
import pandas as pd
import ta
from dotenv import load_dotenv
import asyncio
from telegram import Bot

load_dotenv()

# ==================================================

# CONFIG

# ==================================================

SYMBOLS      = [“XRPUSDT”, “XLMUSDT”, “MASKUSDT”]
INTERVAL     = “15”
LEVERAGE     = 10
SL_MULT      = 2.5
TP_MULT      = 2.75
ATR_PERIOD   = 11
COOLDOWN_SEC = 900
SL_LOOKBACK  = 3
SL_BUFFER    = 0.0003

EMA_FAST   = 15
EMA_SLOW   = 65
EMA_TREND  = 150
RSI_PERIOD = 18
RSI_HIGH   = 70
RSI_LOW    = 30
RSI_MID    = 50
ADX_PERIOD = 15
ADX_MIN    = 19

# ==================================================

# STATE

# ==================================================

def new_state():
return {
“in_position”: False,
“pos_type”:    None,
“entry”:       0.0,
“sl”:          0.0,
“tp”:          0.0,
“last_signal”: 0,
“trades”:      0,
“wins”:        0,
}

states = {s: new_state() for s in SYMBOLS}

# ==================================================

# TELEGRAM

# ==================================================

TELEGRAM_TOKEN = os.getenv(“TELEGRAM_TOKEN”)
CHAT_ID        = os.getenv(“TELEGRAM_CHAT_ID”)

async def send_async(msg):
bot = Bot(token=TELEGRAM_TOKEN)
async with bot:
await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=“HTML”)

def send_telegram(msg):
try:
asyncio.run(send_async(msg))
except Exception as e:
print(f”Telegram Error: {e}”)

# ==================================================

# GET KLINES — hata yakalama ile

# ==================================================

def get_klines(symbol, interval=INTERVAL, limit=300):
url = (
f”https://api.bybit.com/v5/market/kline”
f”?category=linear&symbol={symbol}”
f”&interval={interval}&limit={limit}”
)
try:
r = requests.get(url, timeout=15).json()

```
    # API yanıt kontrolü
    if "result" not in r:
        raise ValueError(f"API yanıt hatası: {r}")
    if "list" not in r["result"]:
        raise ValueError(f"Liste bulunamadı: {r['result']}")

    data = r["result"]["list"]

    if len(data) == 0:
        raise ValueError("Boş veri döndü")

    df = pd.DataFrame(data)
    df = df.iloc[::-1].reset_index(drop=True)
    df.columns = ["time","open","high","low","close","volume","turnover"]
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    return df

except requests.exceptions.Timeout:
    raise Exception("Bybit API timeout")
except requests.exceptions.ConnectionError:
    raise Exception("Bybit API bağlantı hatası")
except Exception as e:
    raise Exception(f"Veri hatası: {e}")
```

# ==================================================

# INDICATORS

# ==================================================

def add_indicators(df):
df[“ema_fast”]  = ta.trend.ema_indicator(df[“close”], window=EMA_FAST)
df[“ema_slow”]  = ta.trend.ema_indicator(df[“close”], window=EMA_SLOW)
df[“ema_trend”] = ta.trend.ema_indicator(df[“close”], window=EMA_TREND)
df[“rsi”]       = ta.momentum.rsi(df[“close”], window=RSI_PERIOD)
adx_ind         = ta.trend.ADXIndicator(df[“high”], df[“low”], df[“close”], window=ADX_PERIOD)
df[“adx”]       = adx_ind.adx()
df[“atr”]       = ta.volatility.average_true_range(df[“high”], df[“low”], df[“close”], window=ATR_PERIOD)
df[“vwap”]      = ta.volume.volume_weighted_average_price(
df[“high”], df[“low”], df[“close”], df[“volume”], window=20)
df[“vol_sma”]   = df[“volume”].rolling(20).mean()
return df

# ==================================================

# STRUCTURE SL

# ==================================================

def get_structure_sl(df, idx, direction):
recent = df.iloc[max(0, idx - SL_LOOKBACK):idx]
if direction == “LONG”:
red = recent[recent[“close”] < recent[“open”]]
sl  = red[“low”].min() if len(red) > 0 else recent[“low”].min()
return round(sl - SL_BUFFER, 6)
else:
green = recent[recent[“close”] > recent[“open”]]
sl    = green[“high”].max() if len(green) > 0 else recent[“high”].max()
return round(sl + SL_BUFFER, 6)

# ==================================================

# POSITION CHECK

# ==================================================

def check_position(symbol, last_close):
state = states[symbol]
if not state[“in_position”]:
return

```
ptype = state["pos_type"]
sl    = state["sl"]
tp    = state["tp"]
entry = state["entry"]

hit_sl = (ptype == "LONG"  and last_close <= sl) or \
         (ptype == "SHORT" and last_close >= sl)
hit_tp = (ptype == "LONG"  and last_close >= tp) or \
         (ptype == "SHORT" and last_close <= tp)

if hit_sl:
    pnl_pct = -abs(entry - sl) / entry * 100 * LEVERAGE
    state["in_position"] = False
    state["trades"]     += 1
    send_telegram(
        f"🔴 <b>STOP LOSS — {ptype}</b>\n\n"
        f"Sembol: {symbol}\n"
        f"Giriş:  {entry:.6f}\n"
        f"SL:     {sl:.6f}\n"
        f"PnL:    {pnl_pct:.2f}%\n\n"
        f"📊 İşlem: {state['trades']} | Win: {state['wins']} | "
        f"WR: {state['wins']/max(1,state['trades'])*100:.1f}%"
    )

elif hit_tp:
    pnl_pct = abs(tp - entry) / entry * 100 * LEVERAGE
    state["in_position"] = False
    state["trades"]     += 1
    state["wins"]       += 1
    send_telegram(
        f"✅ <b>TAKE PROFIT — {ptype}</b>\n\n"
        f"Sembol: {symbol}\n"
        f"Giriş:  {entry:.6f}\n"
        f"TP:     {tp:.6f}\n"
        f"PnL:    +{pnl_pct:.2f}%\n\n"
        f"📊 İşlem: {state['trades']} | Win: {state['wins']} | "
        f"WR: {state['wins']/max(1,state['trades'])*100:.1f}%"
    )
```

# ==================================================

# ANALYZE

# ==================================================

def analyze(symbol):
state = states[symbol]
df    = get_klines(symbol)
df    = add_indicators(df)
df    = df.dropna().reset_index(drop=True)

```
last  = df.iloc[-1]
prev  = df.iloc[-2]
idx   = len(df) - 1

check_position(symbol, last["close"])

now = time.time()
if (now - state["last_signal"]) < COOLDOWN_SEC:
    print(f"{symbol} | Cooldown: {int(COOLDOWN_SEC-(now-state['last_signal']))}s")
    return

if state["in_position"]:
    print(f"{symbol} | Pozisyon: {state['pos_type']} @ {state['entry']:.6f}")
    return

long_signal = (
    last["close"] > last["ema_trend"] and
    last["ema_fast"] > last["ema_slow"] and
    RSI_MID < last["rsi"] < RSI_HIGH and
    last["adx"] > ADX_MIN and
    last["volume"] > last["vol_sma"] and
    prev["close"] < prev["vwap"] and last["close"] > last["vwap"]
)

short_signal = (
    last["close"] < last["ema_trend"] and
    last["ema_fast"] < last["ema_slow"] and
    RSI_LOW < last["rsi"] < RSI_MID and
    last["adx"] > ADX_MIN and
    last["volume"] > last["vol_sma"] and
    prev["close"] > prev["vwap"] and last["close"] < last["vwap"]
)

if long_signal:
    entry = last["close"]
    sl    = get_structure_sl(df, idx, "LONG")
    risk  = entry - sl
    if risk <= 0 or risk < last["atr"] * 0.3:
        sl   = round(entry - last["atr"] * SL_MULT, 6)
        risk = entry - sl
    tp     = round(entry + risk * TP_MULT, 6)
    sl_pct = round((entry - sl) / entry * 100, 2)
    tp_pct = round((tp - entry) / entry * 100, 2)

    state.update({"in_position": True, "pos_type": "LONG",
                  "entry": entry, "sl": sl, "tp": tp, "last_signal": now})

    send_telegram(
        f"🚀 <b>LONG SİNYAL</b>\n\n"
        f"Sembol: {symbol}\n"
        f"TF: {INTERVAL}dk\n"
        f"Fiyat: {entry:.6f}\n\n"
        f"🛡 SL: {sl:.6f} (-%{sl_pct})\n"
        f"🎯 TP: {tp:.6f} (+%{tp_pct})\n"
        f"⚖️ R/R: 1:{TP_MULT}\n\n"
        f"📊 RSI: {last['rsi']:.1f} | ADX: {last['adx']:.1f}\n"
        f"📈 Trend: YUKARI | VWAP: KIRILDI ✅"
    )
    print(f"{symbol} | LONG → {entry:.6f} | SL: {sl:.6f} | TP: {tp:.6f}")

elif short_signal:
    entry = last["close"]
    sl    = get_structure_sl(df, idx, "SHORT")
    risk  = sl - entry
    if risk <= 0 or risk < last["atr"] * 0.3:
        sl   = round(entry + last["atr"] * SL_MULT, 6)
        risk = sl - entry
    tp     = round(entry - risk * TP_MULT, 6)
    sl_pct = round((sl - entry) / entry * 100, 2)
    tp_pct = round((entry - tp) / entry * 100, 2)

    state.update({"in_position": True, "pos_type": "SHORT",
                  "entry": entry, "sl": sl, "tp": tp, "last_signal": now})

    send_telegram(
        f"🔻 <b>SHORT SİNYAL</b>\n\n"
        f"Sembol: {symbol}\n"
        f"TF: {INTERVAL}dk\n"
        f"Fiyat: {entry:.6f}\n\n"
        f"🛡 SL: {sl:.6f} (+%{sl_pct})\n"
        f"🎯 TP: {tp:.6f} (-%{tp_pct})\n"
        f"⚖️ R/R: 1:{TP_MULT}\n\n"
        f"📊 RSI: {last['rsi']:.1f} | ADX: {last['adx']:.1f}\n"
        f"📉 Trend: AŞAĞI | VWAP: KIRILDI ✅"
    )
    print(f"{symbol} | SHORT → {entry:.6f} | SL: {sl:.6f} | TP: {tp:.6f}")

else:
    print(f"{symbol} | Sinyal yok | {last['close']:.6f} | RSI: {last['rsi']:.1f} | ADX: {last['adx']:.1f}")
```

# ==================================================

# MAIN

# ==================================================

send_telegram(
f”✅ <b>ANCYRA STRUCTURE BOT BAŞLADI</b>\n\n”
f”📊 Coinler: {’ | ’.join(SYMBOLS)}\n”
f”TF: {INTERVAL}dk\n”
f”SL: Yapısal (Son kırmızı/yeşil mum)\n”
f”TP: Risk x {TP_MULT}\n”
f”Kaldıraç: {LEVERAGE}x”
)

while True:
for symbol in SYMBOLS:
try:
analyze(symbol)
except Exception as e:
print(f”{symbol} | ERROR: {e}”)
time.sleep(3)
time.sleep(54)
