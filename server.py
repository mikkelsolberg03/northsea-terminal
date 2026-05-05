"""
NorthSea Terminal — Unified Backend
-------------------------------------
Krever: pip install flask flask-cors yfinance requests
Start:  python server.py
Åpner:  http://localhost:5000
"""

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import yfinance as yf
import requests
import os
from datetime import datetime
import time

app = Flask(__name__, static_folder='.')
CORS(app)

NEWS_API_KEY     = os.environ.get("NEWS_API_KEY", "e0a774cffe04469eb6f84c24fc584840")
OILPRICE_API_KEY = os.environ.get("OILPRICE_API_KEY", "c3efab204f01f02aebe6fd9cef29154c5f302e75d8cd0752ddd62906e97c297a")
EIA_API_KEY      = os.environ.get("EIA_API_KEY", "1UViC4ArhMLe0eZoRRJXoe4fHoonHjzjYGqoeCDE")

# ─── CACHE ───────────────────────────────────────────────────────────────────
cache = {}
CACHE_TTL = {
    "prices":  60,
    "history": 300,
    "news":    300,
    "eia":     300,
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

def safe_float(val, decimals=2):
    try:
        return round(float(val), decimals)
    except:
        return None

def ticker_info(symbol):
    try:
        t = yf.Ticker(symbol)
        info = t.fast_info
        price = safe_float(info.last_price)
        prev  = safe_float(info.previous_close)
        if price and prev:
            change = safe_float(price - prev)
            pct    = safe_float((price - prev) / prev * 100)
        else:
            change = pct = None
        return {"price": price, "change": change, "pctChange": pct, "prev": prev}
    except Exception as e:
        print(f"  [WARN] {symbol}: {e}")
        return {"price": None, "change": None, "pctChange": None}


# ─── SERVE FRONTEND ──────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "NorthSea Terminal Unified.html")


# ─── OIL & GAS API ───────────────────────────────────────────────────────────
def fetch_oilprice(code):
    try:
        url = "https://api.oilpriceapi.com/v1/prices/latest"
        headers = {
            "Authorization": f"Token {OILPRICE_API_KEY}",
            "Content-Type": "application/json"
        }
        r = requests.get(url, params={"by_code": code}, headers=headers, timeout=8)
        data = r.json()
        if data.get("status") == "success":
            return {"price": safe_float(data["data"]["price"]), "change": None, "pctChange": None}
    except Exception as e:
        print(f"  [WARN] OilPriceAPI {code}: {e}")
    return {"price": None, "change": None, "pctChange": None}


def fetch_oilprice_history(code, period):
    try:
        url = "https://api.oilpriceapi.com/v1/prices/past_month"
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

    print("[INFO] Fetching oil prices...")
    brent = fetch_oilprice("BRENT_CRUDE_USD")
    wti   = fetch_oilprice("WTI_USD")
    gas   = fetch_oilprice("NATURAL_GAS_USD")
    nok   = ticker_info("USDNOK=X")

    for key, sym, data in [("brent","BZ=F",brent),("wti","CL=F",wti),("gas","NG=F",gas)]:
        yf_data = ticker_info(sym)
        # If OilPriceAPI returned nothing, use yfinance price
        if not data["price"] and yf_data.get("price"):
            data["price"] = yf_data["price"]
        # Fill in change/pct from yfinance prev close
        if data["price"] and data["change"] is None and yf_data.get("prev"):
            data["change"]    = safe_float(data["price"] - yf_data["prev"])
            data["pctChange"] = safe_float((data["price"] - yf_data["prev"]) / yf_data["prev"] * 100)

    result = {"brent": brent, "wti": wti, "gas": gas, "nok": nok}
    try:
        bp, wp = brent["price"], wti["price"]
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

    print("[INFO] Fetching oil stocks...")
    stocks_def = [
        {"name": "Equinor",       "ticker": "EQNR",  "sym": "EQNR.OL"},
        {"name": "Aker BP",       "ticker": "AKRBP", "sym": "AKRBP.OL"},
        {"name": "Vår Energi",    "ticker": "VAR",   "sym": "VAR.OL"},
        {"name": "DNO",           "ticker": "DNO",   "sym": "DNO.OL"},
        {"name": "BW Energy",     "ticker": "BWE",   "sym": "BWE.OL"},
        {"name": "PGS",           "ticker": "PGS",   "sym": "PGS.OL"},
    ]
    results = []
    for s in stocks_def:
        data = ticker_info(s["sym"])
        results.append({
            "name":   s["name"],
            "ticker": s["ticker"],
            "price":  data["price"],
            "change": data["change"],
            "pct":    data["pctChange"],
        })
    set_cache("prices_stocks", results)
    return jsonify(results)


@app.route("/api/history/<symbol>/<period>")
def api_history(symbol, period):
    cache_key = f"history_{symbol}_{period}"
    cached = get_cache(cache_key)
    if cached:
        return jsonify(cached)

    print(f"[INFO] Fetching history {symbol}/{period}...")

    code_map = {"brent": "BRENT_CRUDE_USD", "wti": "WTI_USD", "gas": "NATURAL_GAS_USD"}
    code = code_map.get(symbol)
    if code:
        data = fetch_oilprice_history(code, period)
        if data:
            set_cache(cache_key, data)
            return jsonify(data)

    period_map = {"1W": ("5d","1d"), "1M": ("1mo","1d"), "3M": ("3mo","1d"), "6M": ("6mo","1d"), "1Y": ("1y","1wk")}
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
        data = [{"x": idx.strftime("%d %b"), "y": safe_float(row["Close"])} for idx, row in df.iterrows()]
        set_cache(cache_key, data)
        return jsonify(data)
    except Exception as e:
        print(f"  [ERR] history {symbol}: {e}")
        return jsonify([])


@app.route("/api/news")
def api_news():
    cached = get_cache("news_main")
    if cached:
        return jsonify(cached)

    print("[INFO] Fetching oil/gas news...")
    queries = [
        ("Brent crude oil price OPEC", "OPEC"),
        ("Equinor Aker BP Norwegian energy stocks", "EQUITY"),
        ("oil gas Norway NCS", "NCS"),
        ("IEA EIA oil demand supply macro", "MACRO"),
    ]
    articles = []
    for q, tag in queries:
        try:
            r = requests.get("https://newsapi.org/v2/everything", params={
                "q": q, "language": "en", "sortBy": "publishedAt", "pageSize": 6,
                "apiKey": NEWS_API_KEY,
            }, timeout=8)
            for a in r.json().get("articles", []):
                if not a.get("title") or a["title"] == "[Removed]":
                    continue
                pub = a.get("publishedAt", "")
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                except:
                    time_str = ""
                articles.append({
                    "time": time_str,
                    "src":  a.get("source", {}).get("name", ""),
                    "headline": a.get("title", ""),
                    "url": a.get("url", ""),
                    "tag": tag,
                })
        except Exception as e:
            print(f"  [ERR] news '{q}': {e}")

    articles = sorted(articles, key=lambda x: x["time"], reverse=True)[:20]
    set_cache("news_main", articles)
    return jsonify(articles)


@app.route("/api/macro")
def api_macro():
    return jsonify({
        "opec_prod": "40.7",
        "rig_count": "486",
        "us_stocks": "440.1",
        "demand":    "102.3",
        "breakeven": "38",
    })


@app.route("/api/eqnr_yield")
def api_eqnr_yield():
    try:
        t = yf.Ticker("EQNR.OL")
        info = t.info
        div_yield = info.get("dividendYield")
        if div_yield and div_yield < 1:
            return jsonify({"yield": f"{div_yield*100:.1f}%"})
        price = safe_float(t.fast_info.last_price)
        div = info.get("trailingAnnualDividendRate")
        if price and div and price > 0:
            y = (div / price) * 100
            if y < 30:
                return jsonify({"yield": f"{y:.1f}%"})
    except:
        pass
    return jsonify({"yield": "N/A"})


# ─── EIA API ─────────────────────────────────────────────────────────────────
def eia_fetch(path, params):
    try:
        r = requests.get(
            f"https://api.eia.gov/v2{path}",
            params={"api_key": EIA_API_KEY, **params},
            timeout=10
        )
        return r.json().get("response", {}).get("data", [])
    except Exception as e:
        print(f"  [WARN] EIA {path}: {e}")
        return []

@app.route("/api/eia/macro")
def api_eia_macro():
    cached = get_cache("eia_macro")
    if cached:
        return jsonify(cached)

    print("[INFO] Fetching EIA macro data...")
    result = {}

    # US crude inventories — weekly, thousand barrels → convert to mbbl
    inv = eia_fetch("/petroleum/stoc/wstk/data/", {
        "frequency": "weekly",
        "data[0]": "value",
        "facets[series][]": "WCRSTUS1",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 2,
    })
    if len(inv) >= 2:
        latest = inv[0]["value"]
        prev   = inv[1]["value"]
        draw   = round((latest - prev) / 1000, 1)
        result["us_inventories"] = {
            "value":  str(round(latest / 1000, 1)),
            "unit":   "mbbl",
            "change": f"{'+' if draw > 0 else ''}{draw} w/w",
            "up":     draw < 0,  # draw (negative) is bullish
        }

    # Brent spot price — daily
    brent = eia_fetch("/petroleum/pri/spt/data/", {
        "frequency": "daily",
        "data[0]": "value",
        "facets[series][]": "RBRTE",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 2,
    })
    if len(brent) >= 2:
        latest = brent[0]["value"]
        prev   = brent[1]["value"]
        pct    = round((latest - prev) / prev * 100, 2) if prev else None
        result["brent"] = {"price": safe_float(latest), "pctChange": pct, "period": brent[0]["period"]}

    # WTI spot price — daily
    wti = eia_fetch("/petroleum/pri/spt/data/", {
        "frequency": "daily",
        "data[0]": "value",
        "facets[series][]": "RWTC",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 2,
    })
    if len(wti) >= 2:
        latest = wti[0]["value"]
        prev   = wti[1]["value"]
        pct    = round((latest - prev) / prev * 100, 2) if prev else None
        result["wti"] = {"price": safe_float(latest), "pctChange": pct, "period": wti[0]["period"]}

    # OPEC production — STEO monthly forecast (mb/d)
    opec = eia_fetch("/steo/data/", {
        "frequency": "monthly",
        "data[0]": "value",
        "facets[seriesId][]": "COPRWOPEC",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 2,
    })
    if len(opec) >= 2:
        latest = opec[0]["value"]
        prev   = opec[1]["value"]
        change = round(latest - prev, 1)
        result["opec_prod"] = {
            "value":  str(round(latest, 1)),
            "unit":   "mbpd",
            "change": f"{'+' if change >= 0 else ''}{change} m/m",
        }

    # Global liquid fuels consumption — STEO monthly (mb/d)
    demand = eia_fetch("/steo/data/", {
        "frequency": "monthly",
        "data[0]": "value",
        "facets[seriesId][]": "PATC_WORLD",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 2,
    })
    if len(demand) >= 2:
        latest = demand[0]["value"]
        prev   = demand[1]["value"]
        change = round(latest - prev, 1)
        result["global_demand"] = {
            "value":  str(round(latest, 1)),
            "unit":   "mbpd",
            "change": f"{'+' if change >= 0 else ''}{change} m/m",
        }

    set_cache("eia_macro", result)
    return jsonify(result)


@app.route("/api/eia/history/brent")
def api_eia_brent_history():
    cached = get_cache("eia_brent_hist")
    if cached:
        return jsonify(cached)

    print("[INFO] Fetching EIA Brent history...")
    data = eia_fetch("/petroleum/pri/spt/data/", {
        "frequency": "daily",
        "data[0]": "value",
        "facets[series][]": "RBRTE",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 365,
    })
    result = [{"x": d["period"], "y": safe_float(d["value"])}
              for d in reversed(data) if d.get("value") is not None]
    set_cache("eia_brent_hist", result)
    return jsonify(result)


# ─── SALMON API (stub — wire real data source when available) ─────────────────
@app.route("/api/salmon/prices")
def api_salmon_prices():
    """Nasdaq Salmon index and FX. Wire to Fish Pool API when available."""
    cached = get_cache("prices_salmon")
    if cached:
        return jsonify(cached)

    eurnok = ticker_info("EURNOK=X")
    usdnok = ticker_info("USDNOK=X")

    result = {
        "nasdaq":  {"price": None, "change": None, "pctChange": None},
        "fpFw":    {"price": None, "change": None, "pctChange": None},
        "region3": {"price": None, "change": None, "pctChange": None},
        "region4": {"price": None, "change": None, "pctChange": None},
        "eurnok":  eurnok,
        "usdnok":  usdnok,
    }
    set_cache("prices_salmon", result)
    return jsonify(result)


@app.route("/api/salmon/stocks")
def api_salmon_stocks():
    cached = get_cache("prices_salmon_stocks")
    if cached:
        return jsonify(cached)

    print("[INFO] Fetching salmon stocks...")
    stocks_def = [
        {"name": "Mowi",          "ticker": "MOWI",  "sym": "MOWI.OL"},
        {"name": "SalMar",        "ticker": "SALM",  "sym": "SALM.OL"},
        {"name": "Lerøy",         "ticker": "LSG",   "sym": "LSG.OL"},
        {"name": "Bakkafrost",    "ticker": "BAKKA", "sym": "BAKKA.OL"},
        {"name": "Grieg Seafood", "ticker": "GSF",   "sym": "GSF.OL"},
        {"name": "Norway Royal",  "ticker": "NRS",   "sym": "NRS.OL"},
    ]
    results = []
    for s in stocks_def:
        data = ticker_info(s["sym"])
        results.append({
            "name":   s["name"],
            "ticker": s["ticker"],
            "price":  data["price"],
            "change": data["change"],
            "pct":    data["pctChange"],
        })
    set_cache("prices_salmon_stocks", results)
    return jsonify(results)


# ─── SHIPPING API (stub) ──────────────────────────────────────────────────────
@app.route("/api/shipping/stocks")
def api_shipping_stocks():
    cached = get_cache("prices_shipping_stocks")
    if cached:
        return jsonify(cached)

    stocks_def = [
        {"name": "Frontline",       "ticker": "FRO",   "sym": "FRO.OL"},
        {"name": "Flex LNG",        "ticker": "FLNG",  "sym": "FLNG.OL"},
        {"name": "Stolt-Nielsen",   "ticker": "SNI",   "sym": "SNI.OL"},
        {"name": "BW LPG",          "ticker": "BWLPG", "sym": "BWLPG.OL"},
        {"name": "Höegh Autoliners","ticker": "HAUTO", "sym": "HAUTO.OL"},
    ]
    results = []
    for s in stocks_def:
        data = ticker_info(s["sym"])
        results.append({
            "name":   s["name"],
            "ticker": s["ticker"],
            "price":  data["price"],
            "change": data["change"],
            "pct":    data["pctChange"],
        })
    set_cache("prices_shipping_stocks", results)
    return jsonify(results)


if __name__ == "__main__":
    print("=" * 50)
    print("  NorthSea Terminal — Unified Backend")
    print("  http://localhost:5000")
    print("=" * 50)
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
