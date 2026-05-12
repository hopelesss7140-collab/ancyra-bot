import os
import json
import hmac
import hashlib
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BINANCE_API_KEY    = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY", "")
BASE_URL           = "https://fapi.binance.com"

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        print("Telegram hatasi: " + str(e))

def get_signature(params):
    query = "&".join([str(k) + "=" + str(v) for k, v in params.items()])
    sig = hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return query + "&signature=" + sig

def binance_post(endpoint, params):
    params["timestamp"]  = int(time.time() * 1000)
    params["recvWindow"] = 5000
    signed = get_signature(params)
    url = BASE_URL + endpoint + "?" + signed
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    resp = requests.post(url, headers=headers)
    return resp.json()

def binance_get(endpoint, params):
    params["timestamp"]  = int(time.time() * 1000)
    params["recvWindow"] = 5000
    signed = get_signature(params)
    url = BASE_URL + endpoint + "?" + signed
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    resp = requests.get(url, headers=headers)
    return resp.json()

def close_position(symbol):
    try:
        result = binance_get("/fapi/v2/positionRisk", {"symbol": symbol})
        if isinstance(result, list):
            for pos in result:
                amt = float(pos.get("positionAmt", 0))
                if amt != 0:
                    side = "SELL" if amt > 0 else "BUY"
                    binance_post("/fapi/v1/order", {
                        "symbol":     symbol,
                        "side":       side,
                        "type":       "MARKET",
                        "quantity":   abs(amt),
                        "reduceOnly": "true"
                    })
                    print(symbol + " pozisyon kapatildi")
    except Exception as e:
        print("Pozisyon kapatma hatasi: " + str(e))

def place_order(symbol, side, usdt_amount=50, leverage=5):
    try:
        binance_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
        price_url  = BASE_URL + "/fapi/v1/ticker/price?symbol=" + symbol
        price_resp = requests.get(price_url)
        price_data = price_resp.json()
if isinstance(price_data, list):
    price = float(price_data[0]["price"])
else:
    price = float(price_data["price"])
        quantity   = round((usdt_amount * leverage) / price, 3)
        result = binance_post("/fapi/v1/order", {
            "symbol":   symbol,
            "side":     side,
            "type":     "MARKET",
            "quantity": quantity
        })
        print("Order gonderildi: " + symbol + " " + side + " " + str(quantity) + " @ " + str(price))
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
        print("Sinyal alindi: " + str(data))
        action = data.get("action", "").upper()
        symbol = data.get("symbol", "")
        price  = data.get("price", 0)
        symbol = symbol.replace(".P", "").replace("PERP", "")
        if not symbol.endswith("USDT"):
            symbol = symbol + "USDT"
        print("Action: " + action + " | Symbol: " + symbol + " | Price: " + str(price))
        if action == "STOP":
            send_telegram("ANCYRA KILL SWITCH!")
            return jsonify({"status": "stopped"})
        if action == "BUY":
            close_position(symbol)
            result = place_order(symbol, "BUY")
            send_telegram("ANCYRA LONG\n" + symbol + "\nFiyat: " + str(price))
            return jsonify({"status": "long_opened", "result": result})
        if action == "SELL":
            close_position(symbol)
            result = place_order(symbol, "SELL")
            send_telegram("ANCYRA SHORT\n" + symbol + "\nFiyat: " + str(price))
            return jsonify({"status": "short_opened", "result": result})
        return jsonify({"status": "unknown"})
    except Exception as e:
        print("Webhook hatasi: " + str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def index():
    return jsonify({"bot": "Ancyra Trading Bot", "status": "online", "version": "2.0"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
