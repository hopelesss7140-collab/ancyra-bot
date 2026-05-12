import os
import hmac
import hashlib
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BINANCE_API_KEY    = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY", "")
BASE_URL           = "https://fapi.binance.com"
TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

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

def sign(params):
    query = "&".join([str(k) + "=" + str(v) for k, v in params.items()])
    sig   = hmac.new(BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig

def bpost(endpoint, params):
    params["timestamp"]  = int(time.time() * 1000)
    params["recvWindow"] = 5000
    url     = BASE_URL + endpoint + "?" + sign(params)
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    return requests.post(url, headers=headers, timeout=10).json()

def bget(endpoint, params):
    params["timestamp"]  = int(time.time() * 1000)
    params["recvWindow"] = 5000
    url     = BASE_URL + endpoint + "?" + sign(params)
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    return requests.get(url, headers=headers, timeout=10).json()

def get_price(symbol):
    resp = requests.get(BASE_URL + "/fapi/v2/ticker/price?symbol=" + symbol, timeout=5)
    data = resp.json()
    return float(data["price"])

def close_position(symbol):
    try:
        positions = bget("/fapi/v2/positionRisk", {"symbol": symbol})
        if isinstance(positions, list):
            for pos in positions:
                amt = float(pos.get("positionAmt", 0))
                if amt != 0:
                    side = "SELL" if amt > 0 else "BUY"
                    bpost("/fapi/v1/order", {
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
        bpost("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
        price    = get_price(symbol)
        quantity = round((usdt_amount * leverage) / price, 3)
        result   = bpost("/fapi/v1/order", {
            "symbol":   symbol,
            "side":     side,
            "type":     "MARKET",
            "quantity": quantity
        })
        print("Order: " + symbol + " " + side + " " + str(quantity) + " @ " + str(price))
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
            send_telegram("ANCYRA LONG\n" + symbol + "\nFiyat: " + str(price) + "\n" + str(result.get("status", "")))
            return jsonify({"status": "long_opened", "result": result})

        if action == "SELL":
            close_position(symbol)
            result = place_order(symbol, "SELL")
            send_telegram("ANCYRA SHORT\n" + symbol + "\nFiyat: " + str(price) + "\n" + str(result.get("status", "")))
            return jsonify({"status": "short_opened", "result": result})

        return jsonify({"status": "unknown"})

    except Exception as e:
        print("Webhook hatasi: " + str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def index():
    return jsonify({"bot": "Ancyra Trading Bot", "status": "online", "version": "3.0"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
