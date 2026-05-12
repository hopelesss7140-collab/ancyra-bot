import os
import hmac
import hashlib
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BYBIT_API_KEY    = os.environ.get("BYBIT_API_KEY", "")
BYBIT_SECRET_KEY = os.environ.get("BYBIT_SECRET_KEY", "")
BASE_URL         = "https://api.bybit.com"
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=5
        )
    except Exception as e:
        print("Telegram hatasi: " + str(e))

def get_signature(params, timestamp, recv_window):
    param_str = str(timestamp) + BYBIT_API_KEY + str(recv_window) + "&".join([str(k) + "=" + str(v) for k, v in sorted(params.items())])
    return hmac.new(BYBIT_SECRET_KEY.encode(), param_str.encode(), hashlib.sha256).hexdigest()

def bybit_post(endpoint, params):
    timestamp   = int(time.time() * 1000)
    recv_window = 5000
    signature   = get_signature(params, timestamp, recv_window)
    headers = {
        "X-BAPI-API-KEY":     BYBIT_API_KEY,
        "X-BAPI-SIGN":        signature,
        "X-BAPI-TIMESTAMP":   str(timestamp),
        "X-BAPI-RECV-WINDOW": str(recv_window),
        "Content-Type":       "application/json"
    }
    resp = requests.post(BASE_URL + endpoint, json=params, headers=headers, timeout=10)
    return resp.json()

def bybit_get(endpoint, params):
    timestamp   = int(time.time() * 1000)
    recv_window = 5000
    signature   = get_signature(params, timestamp, recv_window)
    headers = {
        "X-BAPI-API-KEY":     BYBIT_API_KEY,
        "X-BAPI-SIGN":        signature,
        "X-BAPI-TIMESTAMP":   str(timestamp),
        "X-BAPI-RECV-WINDOW": str(recv_window)
    }
    resp = requests.get(BASE_URL + endpoint, params=params, headers=headers, timeout=10)
    return resp.json()

def get_price(symbol):
    resp = requests.get(BASE_URL + "/v5/market/tickers?category=linear&symbol=" + symbol, timeout=5)
    data = resp.json()
    print("Fiyat yaniti: " + str(data))
    return float(data["result"]["list"][0]["lastPrice"])

def close_position(symbol):
    try:
        result = bybit_get("/v5/position/list", {"category": "linear", "symbol": symbol})
        if result.get("retCode") == 0:
            for pos in result["result"]["list"]:
                size = float(pos.get("size", 0))
                side = pos.get("side", "")
                if size > 0:
                    close_side = "Sell" if side == "Buy" else "Buy"
                    bybit_post("/v5/order/create", {
                        "category":   "linear",
                        "symbol":     symbol,
                        "side":       close_side,
                        "orderType":  "Market",
                        "qty":        str(size),
                        "reduceOnly": True
                    })
                    print(symbol + " pozisyon kapatildi")
    except Exception as e:
        print("Pozisyon kapatma hatasi: " + str(e))

def set_leverage(symbol, leverage):
    try:
        bybit_post("/v5/position/set-leverage", {
            "category":     "linear",
            "symbol":       symbol,
            "buyLeverage":  str(leverage),
            "sellLeverage": str(leverage)
        })
    except Exception as e:
        print("Leverage hatasi: " + str(e))

def place_order(symbol, side, usdt_amount=50, leverage=5):
    try:
        set_leverage(symbol, leverage)
        price    = get_price(symbol)
        quantity = round((usdt_amount * leverage) / price, 3)
        result   = bybit_post("/v5/order/create", {
            "category":  "linear",
            "symbol":    symbol,
            "side":      "Buy" if side == "BUY" else "Sell",
            "orderType": "Market",
            "qty":       str(quantity)
        })
        print("Order: " + symbol + " " + side + " " + str(quantity) + " @ " + str(price))
        print("Sonuc: " + str(result))
        return result
    except Exception as e:
        print("Order hatasi: " + str(e))
        return {"error": str(e)}

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Veri yok"}), 400

        print("Sinyal: " + str(data))

        action = data.get("action", "").upper()
        symbol = data.get("symbol", "").replace(".P", "").replace("PERP", "")
        price  = data.get("price", 0)

        if not symbol.endswith("USDT"):
            symbol = symbol + "USDT"

        print("Action: " + action + " | Symbol: " + symbol)

        if action == "STOP":
            send_telegram("ANCYRA KILL SWITCH!")
            return jsonify({"status": "stopped"})

        if action == "BUY":
            close_position(symbol)
            result = place_order(symbol, "BUY")
            msg = "ANCYRA LONG\n" + symbol + "\nFiyat: " + str(price)
            if "retCode" in result:
                msg += "\nSonuc: " + ("BASARILI" if result["retCode"] == 0 else "HATA: " + result.get("retMsg", ""))
            send_telegram(msg)
            return jsonify({"status": "long_opened", "result": result})

        if action == "SELL":
            close_position(symbol)
            result = place_order(symbol, "SELL")
            msg = "ANCYRA SHORT\n" + symbol + "\nFiyat: " + str(price)
            if "retCode" in result:
                msg += "\nSonuc: " + ("BASARILI" if result["retCode"] == 0 else "HATA: " + result.get("retMsg", ""))
            send_telegram(msg)
            return jsonify({"status": "short_opened", "result": result})

        return jsonify({"status": "unknown"})

    except Exception as e:
        print("Webhook hatasi: " + str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def index():
    return jsonify({"bot": "Ancyra Trading Bot", "status": "online", "version": "4.0 Bybit"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
