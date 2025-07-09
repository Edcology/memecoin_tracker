import requests
import time
from telegram import Bot
import csv
from datetime import datetime
import os

# === CONFIG ===
TELEGRAM_TOKEN = '7753742212:AAHTMNdQMKvmgZM9hmbyMFBQKCaHjW8iers'
TELEGRAM_CHAT_ID = 5164253005  # your Telegram user ID
LIQ_THRESHOLD = 500  # Minimum liquidity in USD
VOLUME_THRESHOLD = 2000  # USD


bot = Bot(token=TELEGRAM_TOKEN)
seen = set()

MEME_KEYWORDS = ["pepe", "doge", "elon", "floki", "turbo", "rekt", "baby", "moon", "bonk"]

def fetch_profiles(limit=50):
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    try:
        resp = requests.get(url, timeout=10, headers={"Accept": "*/*"})
        resp.raise_for_status()
        data = resp.json()
        return data[:limit] if isinstance(data, list) else []
    except Exception as e:
        print("❌ Profile fetch error:", e)
        return []


def fetch_liquidity_and_volume(token_address):
    url = f"https://api.dexscreener.com/orders/v1/solana/{token_address}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        pools = r.json()  # list of pools

        best_liq = 0
        best_vol = 0
        best_url = ""

        for p in pools:
            liq = float(p.get("liquidity", {}).get("usd", 0))
            vol = float(p.get("volume", {}).get("h24", 0))
            if liq > best_liq and vol > VOLUME_THRESHOLD:
                best_liq = liq
                best_vol = vol
                best_url = p.get("url", "")
        return best_liq, best_vol, best_url
    except Exception as e:
        print(f"❌ Liquidity/Volume fetch error for {token_address}: {e}")
        return 0, 0, ""


def alert(name, liquidity, volume, url):
    msg = f"""
        🚨 *New Solana Token* 🚨
        *Name:* {name}
        *Liquidity:* ${liquidity:,.0f}
        *24h Volume:* ${volume:,.0f}
        [📈 View on DexScreener]({url})
        """
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="Markdown")
    log_to_csv(name, liquidity, volume, url)

def log_to_csv(name, liquidity, volume, url):
    filename = "ml_token_dataset.csv"
    is_new = not os.path.exists(filename)

    with open(filename, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if is_new:
            writer.writerow(["timestamp", "name", "liquidity", "volume", "url", "label"])  # header
        writer.writerow([
            datetime.now().isoformat(),
            name,
            liquidity,
            volume,
            url,
            ""  # empty label to fill manually later
        ])



def run_bot():
    print("🚀 Solana Alert Bot w/ Liquidity Filter running...")
    while True:
        tokens = fetch_profiles()
        for token in tokens:
            addr = token["tokenAddress"]
            name = token.get("header", "") or token.get("url", "").split("/")[-1]
            chain = token.get("chainId", "").lower()
            
            if addr in seen or chain != "solana":
                continue

            if not any(k in name.lower() for k in MEME_KEYWORDS):
                continue
            print(f"🔍 Processing {name} ({addr})...")
            liquidity, volume, url = fetch_liquidity_and_volume(addr)
            if liquidity >= LIQ_THRESHOLD and volume >= VOLUME_THRESHOLD:
                alert(name, addr, liquidity, url)
                seen.add(addr)

        time.sleep(180)

if __name__ == "__main__":
    run_bot()
