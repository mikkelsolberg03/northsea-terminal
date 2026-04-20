"""
Oil & Gas Terminal — Backend Server
------------------------------------
Krever: pip install flask flask-cors yfinance requests
Start:  python server.py
Åpner:  http://localhost:5000
"""

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import yfinance as yf
import requests
import json
import os
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__, static_folder='.')
CORS(app)

NEWS_API_KEY     = "e0a774cffe04469eb6f84c24fc584840"
OILPRICE_API_KEY = "c3efab204f01f02aebe6fd9cef29154c5f302e75d8cd0752ddd62906e97c297a"

# ─── CACHE (unngår for mange API-kall) ───────────────────────────────────────
cache = {}
CACHE_TTL = {
    "prices":  60,    # sekunder
    "history": 300,
    "news":    300,
}

def get_cache(key):
    if key in cache:
        data, ts = cache[key]
        ttl = CACHE_TTL.get(key.split("_")[0], 60)
        if time.time() - ts < ttl:
            return data
    return None

def set_cache(key, data):
    cache[key] = (data, time.time())

# ─── HJELPEFUNKSJONER ────────────────────────────────────────────────────────
def safe_float(val, decimals=2):
    try:
        return round(float(val), decimals)
    except:
        return None

def ticker_info(symbol):
    """Henter grunndata for ett symbol via yfinance"""
    try:
        t = yf.Ticker(symbol)
        info = t.fast_info
        price     = safe_float(info.last_price)
        prev      = safe_float(info.previous_close)
        if price and prev:
            change  = safe_float(price - prev)
            pct     = safe_float((price - prev) / prev * 100)
        else:
            change = pct = None
        return {"price": price, "change": change, "pctChange": pct, "prev": prev}
    except Exception as e:
        print(f"  [WARN] {symbol}: {e}")
        return {"price": None, "change": None, "pctChange": None}

# ─── ENDEPUNKTER ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "NorthSea Terminal.html")

def fetch_oilprice(code):
    """Henter pris fra OilPriceAPI for ett symbol"""
    try:
        url = f"https://api.oilpriceapi.com/v1/prices/latest"
        headers = {
            "Authorization": f"Token {OILPRICE_API_KEY}",
            "Content-Type": "application/json"
        }
        r = requests.get(url, params={"by_code": code}, headers=headers, timeout=8)
        data = r.json()
        if data.get("status") == "success":
            price = safe_float(data["data"]["price"])
            return {"price": price, "change": None, "pctChange": None}
    except Exception as e:
        print(f"  [WARN] OilPriceAPI {code}: {e}")
    return {"price": None, "change": None, "pctChange": None}


def fetch_oilprice_history(code, period):
    """Henter historikk fra OilPriceAPI"""
    endpoint_map = {
        "1M": "past_month",
        "3M": "past_month",  # free tier has past_month as max
        "6M": "past_month",
        "1Y": "past_month",
    }
    endpoint = endpoint_map.get(period, "past_month")
    try:
        url = f"https://api.oilpriceapi.com/v1/prices/{endpoint}"
        headers = {
            "Authorization": f"Token {OILPRICE_API_KEY}",
            "Content-Type": "application/json"
        }
        r = requests.get(url, params={"by_code": code}, headers=headers, timeout=10)
        data = r.json()
        if data.get("status") == "success":
            prices = data.get("data", [])
            result = []
            for p in prices:
                try:
                    dt = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
                    result.append({"x": dt.strftime("%d %b"), "y": safe_float(p["price"])})
                except:
                    pass
            return sorted(result, key=lambda x: x["x"])
    except Exception as e:
        print(f"  [WARN] OilPriceAPI history {code}: {e}")
    return []


@app.route("/api/prices")
def api_prices():
    cached = get_cache("prices_main")
    if cached:
        return jsonify(cached)

    print("[INFO] Fetching oil prices from OilPriceAPI...")

    # Fetch Brent, WTI, Natural Gas from OilPriceAPI
    brent = fetch_oilprice("BRENT_CRUDE_USD")
    wti   = fetch_oilprice("WTI_USD")
    gas   = fetch_oilprice("NATURAL_GAS_USD")

    # USD/NOK still from yfinance (not in OilPriceAPI)
    nok = ticker_info("USDNOK=X")

    # Calculate change vs previous close using yfinance as fallback
    for key, sym, data in [("brent","BZ=F",brent),("wti","CL=F",wti),("gas","NG=F",gas)]:
        if data["price"] and data["change"] is None:
            yf_data = ticker_info(sym)
            if yf_data.get("prev") and data["price"]:
                data["change"]    = safe_float(data["price"] - yf_data["prev"])
                data["pctChange"] = safe_float((data["price"] - yf_data["prev"]) / yf_data["prev"] * 100)

    result = {"brent": brent, "wti": wti, "gas": gas, "nok": nok}

    # Brent-WTI spread
    try:
        bp = brent["price"]
        wp = wti["price"]
        if bp and wp:
            result["spread"] = {"price": safe_float(bp - wp), "change": None, "pctChange": None}
    except:
        result["spread"] = {"price": None, "change": None, "pctChange": None}

    set_cache("prices_main", result)
    return jsonify(result)


@app.route("/api/stocks")
def api_stocks():
    cached = get_cache("prices_stocks")
    if cached:
        return jsonify(cached)

    print("[INFO] Fetching Norwegian energy stocks...")

    stocks_def = [
        {"name": "Equinor",       "ticker": "EQNR.OL",  "sym": "EQNR.OL"},
        {"name": "Aker BP",       "ticker": "AKRBP.OL", "sym": "AKRBP.OL"},
        {"name": "TGS",           "ticker": "TGS.OL",   "sym": "TGS.OL"},
        {"name": "Subsea 7",      "ticker": "SUBC.OL",  "sym": "SUBC.OL"},
        {"name": "Vår Energi",    "ticker": "VAR.OL",   "sym": "VAR.OL"},
        {"name": "Okea",          "ticker": "OKEA.OL",  "sym": "OKEA.OL"},
        {"name": "Borr Drilling", "ticker": "BORR.OL",  "sym": "BORR.OL"},
    ]

    results = []
    for s in stocks_def:
        data = ticker_info(s["sym"])
        results.append({
            "name":    s["name"],
            "ticker":  s["ticker"],
            "price":   data["price"],
            "change":  data["change"],
            "pct":     data["pctChange"],
        })

    set_cache("prices_stocks", results)
    return jsonify(results)


@app.route("/api/history/<symbol>/<period>")
def api_history(symbol, period):
    cache_key = f"history_{symbol}_{period}"
    cached = get_cache(cache_key)
    if cached:
        return jsonify(cached)

    print(f"[INFO] Fetching history {symbol} / {period} from OilPriceAPI...")

    code_map = {
        "brent": "BRENT_CRUDE_USD",
        "wti":   "WTI_USD",
        "gas":   "NATURAL_GAS_USD",
    }
    code = code_map.get(symbol)

    if code:
        data = fetch_oilprice_history(code, period)
        if data:
            set_cache(cache_key, data)
            return jsonify(data)

    # Fallback to yfinance if OilPriceAPI fails
    print(f"  [INFO] Falling back to yfinance for {symbol}...")
    period_map = {
        "1M": ("1mo", "1d"),
        "3M": ("3mo", "1d"),
        "6M": ("6mo", "1d"),
        "1Y": ("1y",  "1wk"),
    }
    yf_period, interval = period_map.get(period, ("1mo", "1d"))
    sym_map = {"brent": "BZ=F", "wti": "CL=F", "gas": "NG=F"}
    yf_sym = sym_map.get(symbol, symbol)

    try:
        import numpy as np
        t = yf.Ticker(yf_sym)
        df = t.history(period=yf_period, interval=interval)
        df = df.dropna(subset=["Close"])
        closes = df["Close"].values
        median = float(np.median(closes))
        df = df[df["Close"].between(median * 0.5, median * 1.5)]
        data = []
        for idx, row in df.iterrows():
            label = idx.strftime("%d %b") if hasattr(idx, "strftime") else str(idx)[:10]
            data.append({"x": label, "y": safe_float(row["Close"])})
        set_cache(cache_key, data)
        return jsonify(data)
    except Exception as e:
        print(f"  [ERR] history fallback {symbol}: {e}")
        return jsonify([])


@app.route("/api/news")
def api_news():
    cached = get_cache("news_main")
    if cached:
        return jsonify(cached)

    print("[INFO] Fetching news from NewsAPI...")

    queries = [
        ("Brent crude oil price OPEC", "crude"),
        ("Equinor Aker BP Okea Norwegian energy stocks", "equity"),
        ("oil gas Norway NCS Norskehavet Barentshavet", "macro"),
        ("IEA EIA oil demand supply macro", "macro"),
    ]

    articles = []
    for q, tag in queries:
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q":        q,
                "language": "en",
                "sortBy":   "publishedAt",
                "pageSize": 6,
                "apiKey":   NEWS_API_KEY,
            }
            r = requests.get(url, params=params, timeout=8)
            data = r.json()
            for a in data.get("articles", []):
                if not a.get("title") or a["title"] == "[Removed]":
                    continue
                pub = a.get("publishedAt", "")
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    now = datetime.now(dt.tzinfo)
                    diff = now - dt
                    if diff.seconds < 3600:
                        age = f"{diff.seconds // 60}m ago"
                    elif diff.days == 0:
                        age = f"{diff.seconds // 3600}h ago"
                    else:
                        age = f"{diff.days}d ago"
                    time_str = dt.strftime("%H:%M")
                except:
                    age = ""
                    time_str = ""

                articles.append({
                    "time":     time_str,
                    "src":      a.get("source", {}).get("name", ""),
                    "headline": a.get("title", ""),
                    "url":      a.get("url", ""),
                    "tag":      tag,
                    "age":      age,
                })
        except Exception as e:
            print(f"  [ERR] news '{q}': {e}")

    # Sorter på tid (nyeste først)
    articles.sort(key=lambda x: x["time"], reverse=True)

    # Prioriter norske og olje-spesifikke kilder
    priority_sources = ["e24", "dn.no", "offshore", "rigzone", "reuters", "bloomberg", "oilprice"]
    def source_priority(a):
        src = a.get("src", "").lower()
        for i, p in enumerate(priority_sources):
            if p in src:
                return i
        return 99
    articles.sort(key=lambda x: (source_priority(x), x["time"]), reverse=False)
    articles = articles[:20]

    set_cache("news_main", articles)
    return jsonify(articles)


@app.route("/api/macro")
def api_macro():
    """Statiske makrotall — oppdateres manuelt eller via EIA API"""
    return jsonify({
        "opec_prod":   "40.1",
        "rig_count":   "483",
        "us_stocks":   "442.9",
        "demand":      "103.8",
        "breakeven":   "$51",
        "eqnr_yield":  None,  # hentes live fra yfinance
    })


@app.route("/api/eqnr_yield")
def api_eqnr_yield():
    try:
        t = yf.Ticker("EQNR.OL")
        info = t.info
        div_yield = info.get("dividendYield")
        if div_yield and div_yield < 1:  # sanity check: must be <100%
            return jsonify({"yield": f"{div_yield*100:.1f}%"})
        # fallback: calculate from trailing annual dividend / price
        price = safe_float(t.fast_info.last_price)
        div = info.get("trailingAnnualDividendRate")
        if price and div and price > 0:
            yield_val = (div / price) * 100
            if yield_val < 30:
                return jsonify({"yield": f"{yield_val:.1f}%"})
        return jsonify({"yield": "N/A"})
    except:
        return jsonify({"yield": "N/A"})


if __name__ == "__main__":
    print("="*50)
    print("  Oil & Gas Terminal — Backend")
    print("  http://localhost:5000")
    print("="*50)
    app.run(debug=False, port=5000, threaded=True)
