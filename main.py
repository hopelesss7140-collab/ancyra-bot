import os
import json
import hmac
import hashlib
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================
# BINANCE API AYARLARI
# ============================================================

BINANCE_API_KEY    = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY", "")
BINANCE_BASE_URL   = "https://fapi.binance.com"  # Futures

# ============================================================
# TELEGRAM BİLDİRİM (opsiyonel)
# ============================================================

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print(f"Telegram hatasi: {e}")

# ============================================================
# BINANCE İMZA
# ============================================================

def sign_request(params):
    query = "&".join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return query + f"&signature={signature}"

def def binance_request(method, endpoint, params={}):
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    signed = sign_request(params)
    url = f"https://{BINANCE_BASE_URL}{endpoint}?{signed}"
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    if method == "POST":
        response = requests.post(url, headers=headers)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers)
    else:
        response = requests.get(url, headers=headers)
    return response.json()

# ============================================================
# POZİSYON BOYUTU HESAPLA
# ============================================================

def get_position_size(symbol, usdt_amount, leverage=5):
    try:
        # Kaldıraç ayarla
        binance_request("POST", "/fapi/v1/leverage", {
            "symbol": symbol,
            "leverage": leverage
        })
        # Güncel fiyat al
        price_resp = requests.get(f"{BINANCE_BASE_URL}/fapi/v1/ticker/price?symbol={symbol}")
        price = float(price_resp.json()["price"])
        # Pozisyon miktarı
        quantity = round((usdt_amount * leverage) / price, 3)
        return quantity, price
    except Exception as e:
        print(f"Pozisyon boyutu hatasi: {e}")
        return None, None

# ============================================================
# MEVCUT POZİSYONU KAPAT
# ============================================================

def close_position(symbol):
    try:
        pos_resp = binance_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        for pos in pos_resp:
            if pos["symbol"] == symbol:
                amt = float(pos["positionAmt"])
                if amt != 0:
                    side = "SELL" if amt > 0 else "BUY"
                    binance_request("POST", "/fapi/v1/order", {
                        "symbol": symbol,
                        "side": side,
                        "type": "MARKET",
                        "quantity": abs(amt),
                        "reduceOnly": "true"
                    })
                    print(f"{symbol} pozisyon kapatildi")
    except Exception as e:
        print(f"Pozisyon kapatma hatasi: {e}")

# ============================================================
# ORDER GONDER
# ============================================================

def place_order(symbol, side, usdt_amount=100, leverage=5):
    try:
        quantity, price = get_position_size(symbol, usdt_amount, leverage)
        if not quantity:
            return {"error": "Pozisyon boyutu hesaplanamadi"}

        params = {
            "symbol":   symbol,
            "side":     side,
            "type":     "MARKET",
            "quantity": quantity
        }

        result = binance_request("POST", "/fapi/v1/order", params)
        print(f"Order gonderildi: {symbol} {side} {quantity} @ ~{price}")
        return result

    except Exception as e:
        print(f"Order hatasi: {e}")
        return {"error": str(e)}

# ============================================================
# WEBHOOK ENDPOINT
# ============================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Veri yok"}), 400

        print(f"Sinyal alindi: {data}")

        action = data.get("action", "").upper()
        symbol = data.get("symbol", "").replace(".P", "").replace("PERP", "")
        price  = data.get("price", 0)

        # Sembol düzelt (XRPUSDT.P → XRPUSDT)
        if not symbol.endswith("USDT"):
            symbol = symbol + "USDT"

        print(f"Action: {action} | Symbol: {symbol} | Price: {price}")

        # Kill switch
        if action == "STOP":
            reason = data.get("reason", "unknown")
            msg = f"🚨 ANCYRA KILL SWITCH\nSebep: {reason}\nTüm işlemler durduruldu!"
            send_telegram(msg)
            return jsonify({"status": "kill_switch", "reason": reason})

        # Profit lock
        if action == "PROFIT_LOCK":
            msg = f"🔒 ANCYRA KAR KİLİDİ\n{symbol} - Günlük kar hedefine ulaşıldı"
            send_telegram(msg)
            return jsonify({"status": "profit_locked"})

        # Long sinyal
        if action == "BUY":
            close_position(symbol)  # Önce karşı pozisyonu kapat
            result = place_order(symbol, "BUY")
            msg = f"🚀 ANCYRA LONG\n{symbol}\nFiyat: {price}\nSonuç: {result.get('status', 'gönderildi')}"
            send_telegram(msg)
            return jsonify({"status": "long_opened", "symbol": symbol, "result": result})

        # Short sinyal
        if action == "SELL":
            close_position(symbol)  # Önce karşı pozisyonu kapat
            result = place_order(symbol, "SELL")
            msg = f"💥 ANCYRA SHORT\n{symbol}\nFiyat: {price}\nSonuç: {result.get('status', 'gönderildi')}"
            send_telegram(msg)
            return jsonify({"status": "short_opened", "symbol": symbol, "result": result})

        return jsonify({"status": "unknown_action", "action": action})

    except Exception as e:
        print(f"Webhook hatasi: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================
# SAĞLIK KONTROLÜ
# ============================================================

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "online",
        "bot": "Ancyra Trading Bot",
        "version": "1.0"
    })

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"})

# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
