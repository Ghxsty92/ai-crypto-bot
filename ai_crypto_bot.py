# Creating a Render-ready project zip with the requested files.
from pathlib import Path, PurePosixPath
import zipfile, os, textwrap, json, io

project_name = "ai_crypto_render_package"
base_dir = Path("/mnt/data") / project_name
base_dir.mkdir(parents=True, exist_ok=True)

# File contents
ai_code = r'''#!/usr/bin/env python3
"""
ai_crypto_bot.py - Render-ready MOCK trading bot with learning and Telegram alerts.
Mock-only mode, portfolio summaries in GBP (uses GBP_RATE from .env).
Includes a small Flask dashboard so Render can keep the service alive.
"""

import os, time, json, random, requests
from datetime import datetime, timezone
from flask import Flask, jsonify
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BACKUP_FILE = "ai_bot_state.json"
LEARNING_FILE = "ai_bot_learning.json"

MOCK_MODE = True
START_BALANCE = float(os.getenv("START_BALANCE", "10000"))
SYMBOLS = json.loads(os.getenv("SYMBOLS", '["BTC/USDT","ETH/USDT"]'))
LOOP_DELAY = int(os.getenv("LOOP_DELAY", "10"))
GBP_RATE = float(os.getenv("GBP_RATE", "0.78"))

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured (missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID).")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code != 200:
            print("Telegram send failed:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)

def load_state():
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"balance": START_BALANCE, "positions": {}, "pnl": 0.0}

def save_state(state):
    with open(BACKUP_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_learning():
    if os.path.exists(LEARNING_FILE):
        try:
            with open(LEARNING_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    if "memory" not in data:
        data["memory"] = {}
    if "global" not in data:
        data["global"] = {"loops": 0}
    for s in SYMBOLS:
        if s not in data["memory"]:
            data["memory"][s] = {"avg": None, "stability": 0.0}
    return data

def save_learning(data):
    with open(LEARNING_FILE, "w") as f:
        json.dump(data, f, indent=2)

def fetch_mock_price(symbol: str) -> float:
    if "BTC" in symbol:
        base = 107000.0
        drift = random.uniform(-400, 400)
    else:
        base = 3700.0
        drift = random.uniform(-40, 40)
    return round(base + drift, 2)

def decide_signal(symbol: str, price: float, learning: dict):
    mem = learning["memory"].get(symbol, {"avg": None, "stability": 0.0})
    avg = mem.get("avg")
    stability = mem.get("stability", 0.0)
    if avg is None:
        avg = price
        stability = 0.1
    thr_pct = 0.01 * (1.0 - min(0.9, stability))
    up_thr = avg * (1 + thr_pct)
    down_thr = avg * (1 - thr_pct)
    if price > up_thr:
        signal = "SELL"
    elif price < down_thr:
        signal = "BUY"
    else:
        signal = "HOLD"
    distance = abs(price - avg) / max(1.0, avg)
    new_avg = (avg * 0.9) + (price * 0.1)
    if distance < thr_pct * 1.5:
        new_stability = min(1.0, stability + 0.03)
    else:
        new_stability = max(0.0, stability - 0.02)
    learning["memory"][symbol] = {"avg": new_avg, "stability": round(new_stability, 3)}
    diff_pct = (price - new_avg) / max(1.0, new_avg) * 100
    print(f"🧠 Learning {symbol}: avg={new_avg:.2f}, stability={new_stability:.2f}, diff={diff_pct:+.2f}%")
    return signal

def execute_trade(state: dict, symbol: str, signal: str, price: float):
    base = symbol.split("/")[0]
    balance = state.get("balance", 0.0)
    usd_size = balance * 0.10
    if signal == "BUY":
        if usd_size <= 0 or balance < 1:
            print("⚠️ Not enough balance to buy.")
            return
        qty = usd_size / price
        state["positions"][base] = state["positions"].get(base, 0.0) + qty
        state["balance"] = round(state["balance"] - usd_size, 4)
        msg = f"🟢 BUY {base} {qty:.6f} @ {price:.2f} (spent ${usd_size:.2f})"
        print(msg)
        send_telegram(f"*Trade* — {msg}")
    elif signal == "SELL":
        held = state["positions"].get(base, 0.0)
        if held <= 0:
            print(f"⚠️ Nothing to sell for {base}")
            return
        proceeds = held * price
        state["balance"] = round(state["balance"] + proceeds, 4)
        state["positions"][base] = 0.0
        msg = f"🔴 SELL {base} {held:.6f} @ {price:.2f} (received ${proceeds:.2f})"
        print(msg)
        send_telegram(f"*Trade* — {msg}")

def total_portfolio_value(state: dict) -> float:
    total = state.get("balance", 0.0)
    for base, qty in state.get("positions", {}).items():
        try:
            qty_val = float(qty)
        except Exception:
            qty_val = 0.0
        if qty_val > 0:
            sym = f"{base}/USDT"
            price = fetch_mock_price(sym)
            total += qty_val * price
    return round(total, 2)

def send_summary(state: dict, learning: dict):
    total_usd = total_portfolio_value(state)
    total_gbp = round(total_usd * GBP_RATE, 2)
    positions_list = []
    for base, qty in state.get("positions", {}).items():
        if qty and qty > 0:
            positions_list.append(f"• {base}: {qty:.6f}")
    positions_text = "\n".join(positions_list) if positions_list else "None (all in cash)"
    learn_lines = []
    for sym, mem in learning.get("memory", {}).items():
        avg = mem.get("avg", 0.0) or 0.0
        stab = mem.get("stability", 0.0) or 0.0
        learn_lines.append(f"📘 {sym}: avg={avg:.2f}, stability={stab:.2f}")
    learn_text = "\n".join(learn_lines) if learn_lines else "No learning data yet."
    msg = (
        f"📊 *Portfolio Summary*\n\n"
        f"💰 Balance: ${state.get('balance',0.0):,.2f}\n"
        f"💎 Positions:\n{positions_text}\n\n"
        f"💷 Total (GBP): £{total_gbp:,.2f}\n\n"
        f"📈 PnL: ${state.get('pnl',0.0):,.2f}\n\n"
        f"🧠 *Learning Status*\n{learn_text}\n\n"
        f"🕒 {now_iso()}"
    )
    send_telegram(msg)
    print("Summary sent to Telegram.")
    print(msg)

app = Flask(__name__)

@app.route('/')
def dashboard():
    state = load_state()
    total = total_portfolio_value(state)
    return jsonify({
        "balance": state.get("balance", 0.0),
        "positions": state.get("positions", {}),
        "total_value_gbp": round(total * GBP_RATE, 2)
    })

def main_loop():
    state = load_state()
    learning = load_learning()
    print("Starting AI Crypto Bot (MOCK) with visible learning.")
    send_telegram("🤖 *AI Crypto Bot (Mock Mode)* started — learning active")
    loop = 0
    while True:
        loop += 1
        learning["global"]["loops"] = learning["global"].get("loops", 0) + 1
        for sym in SYMBOLS:
            price = fetch_mock_price(sym)
            signal = decide_signal(sym, price, learning)
            print(f"{now_iso()} {sym} price={price:.2f} signal={signal}")
            if signal != "HOLD":
                execute_trade(state, sym, signal, price)
        save_state(state)
        save_learning(learning)
        if loop % int(os.getenv("SUMMARY_EVERY", "6")) == 0:
            send_summary(state, learning)
        time.sleep(LOOP_DELAY)

if __name__ == '__main__':
    from threading import Thread
    t = Thread(target=main_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", "5000")))
'''

env_content = textwrap.dedent(f"""\
TELEGRAM_TOKEN=8497267885:AAHg4s6YDwfyU2gCBvhfQMVmpAeBd_x9jWc
TELEGRAM_CHAT_ID=8350756715
MOCK_MODE=true
START_BALANCE=10000
LOOP_DELAY=10
GBP_RATE=0.78
SUMMARY_EVERY=6
""")

requirements = textwrap.dedent("""\
flask==2.2.5
python-dotenv==1.0.0
requests==2.31.0
pandas==2.2.2
""")

readme = textwrap.dedent("""\
# AI Crypto Bot - Render Deployment Package

This package contains a mock-mode AI trading bot ready to deploy to Render.com.

## Files
- `ai_crypto_bot.py` - main bot (Flask + background loop)
- `.env` - contains environment variables (Telegram token, chat id, settings)
- `requirements.txt` - python dependencies
- `README.md` - this file

## How to deploy on Render
1. Push this repo to GitHub.
2. On Render: New -> Web Service -> Connect GitHub repository.
3. For **Environment** variables, you can leave values as in `.env` or set in Render's UI.
4. **Build Command**: `pip install -r requirements.txt`
5. **Start Command**: `python ai_crypto_bot.py`
6. Deploy. The service will run the Flask endpoint and the background bot loop.

## Notes
- This is mock mode by default. It will **not** place real trades.
- The bot sends Telegram updates; ensure your `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` are valid.
- Portfolio values are converted to GBP using `GBP_RATE` in `.env`.
""")

# Create files
files = {
    "ai_crypto_bot.py": ai_code,
    ".env": env_content,
    "requirements.txt": requirements,
    "README.md": readme
}

for name, content in files.items():
    p = base_dir / name
    p.write_text(content, encoding="utf-8")

# Create zip
zip_path = base_dir.with_suffix(".zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for name in files:
        zf.write(base_dir / name, arcname=name)

zip_path_str = str(zip_path)
zip_path_str

