import asyncio
import re
import os
import sqlite3
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pycoingecko import CoinGeckoAPI
from telegram import Bot
from playwright.async_api import async_playwright

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWITTER_EMAIL = os.getenv("TWITTER_EMAIL")
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME")
TWITTER_PASSWORD = os.getenv("TWITTER_PASSWORD")

cg = CoinGeckoAPI()
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Connect to SQLite database
conn = sqlite3.connect('tokens.db')
cursor = conn.cursor()

# Create tables
cursor.execute('''
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_symbol TEXT UNIQUE,
    influencer TEXT,
    tweet TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    price_at_detection REAL,
    current_price REAL,
    percent_change REAL
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS influencer_stats (
    influencer TEXT PRIMARY KEY,
    total_mentions INTEGER DEFAULT 0,
    avg_percent_change REAL DEFAULT 0
)
''')
conn.commit()

# Influencers to monitor
influencers = ["rektdiomedes", "DOLAK1NG", "AltcoinDailyio", "blockchain_goat", "xDora_ai", "EzMoneyGems", "gemxbt_agent", "gem_detecter", " MaisonGhost", "ashrobinqt", "open4profit", "0xOnlyCalls", "Sophiajett_", "BaseHubHB", "BaseCaptainHB", "GotrillaGorilla", "crypticd22"]

# Scrape tweets function
async def scrape_tweets(username, tweet_count=5):
    async with async_playwright() as p:
        user_data_dir = "./twitter_profile"
        browser = await p.chromium.launch_persistent_context(user_data_dir=user_data_dir, headless=True)
        page = browser.pages[0] if browser.pages else await browser.new_page()

        await page.goto("https://twitter.com/home")
        await page.wait_for_timeout(3000)

        if "login" in page.url.lower():
            print("[-] Not logged in. Performing automatic login...")
            await page.goto("https://twitter.com/i/flow/login")
            await page.wait_for_selector('input[autocomplete="username"]', timeout=10000)
            await page.fill('input[autocomplete="username"]', TWITTER_EMAIL)
            await page.wait_for_selector('button[role="button"]:has-text("Next")', timeout=40000)
            await page.click('button[role="button"]:has-text("Next")')

            try:
                await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                await page.fill('input[data-testid="ocfEnterTextTextInput"]', TWITTER_USERNAME)
                await page.click('button[role="button"]:has-text("Next")')
                print("[+] Username filled and clicked Next.")
            except:
                print("[*] Username step skipped.")

            await page.wait_for_selector('input[autocomplete="current-password"]', timeout=50000)
            await page.fill('input[autocomplete="current-password"]', TWITTER_PASSWORD)
            await page.click('button[data-testid="LoginForm_Login_Button"]')
            await page.wait_for_timeout(5000)
            print("[+] Login successful.")

        await page.goto(f"https://twitter.com/{username}")
        await page.wait_for_timeout(3000)
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(2000)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        tweets = []
        for tweet in soup.find_all("article"):
            content = tweet.get_text(separator=" ").strip()
            tweets.append(content)
            if len(tweets) >= tweet_count:
                break

        await browser.close()
        print(f"[+] Scraped {len(tweets)} tweets from @{username}.")
        return tweets

# Utility functions
def extract_tokens_from_text(text):
    pattern = r"\\$[A-Za-z0-9]{2,8}"
    return re.findall(pattern, text)

async def send_telegram_alert(message):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message)
        print(f"[+] Sent alert: {message}")
    except Exception as e:
        print(f"[x] Telegram error: {e}")

async def is_valid_token(symbol):
    try:
        coins = cg.get_coins_list()
        for coin in coins:
            if symbol.lower() == coin['symbol'].lower():
                return coin['id']
        return None
    except Exception as e:
        print(f"[x] CoinGecko error: {e}")
        return None

async def fetch_trending_tokens_from_dexscreener():
    try:
        url = "https://api.dexscreener.com/latest/dex/tokens"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            trending_tokens = [token['baseToken']['symbol'].lower() for token in data['pairs'][:50]]
            return trending_tokens
    except Exception as e:
        print(f"[x] DEX Screener error: {e}")
    return []

# Main modules
async def monitor_influencers():
    found_tokens = set()
    for influencer in influencers:
        print(f"Scraping {influencer}...")
        tweets = await scrape_tweets(influencer, tweet_count=5)

        for tweet in tweets:
            tokens = extract_tokens_from_text(tweet)
            if tokens:
                for token in tokens:
                    token_upper = token.upper()
                    if token_upper not in found_tokens:
                        coin_id = await is_valid_token(token)
                        if coin_id:
                            try:
                                coin_data = cg.get_coin_by_id(coin_id)
                                price_now = coin_data['market_data']['current_price']['usd']
                                cursor.execute('''
                                    INSERT INTO tokens (token_symbol, influencer, tweet, price_at_detection)
                                    VALUES (?, ?, ?, ?)
                                ''', (token_upper, influencer, tweet[:150], price_now))
                                conn.commit()
                                found_tokens.add(token_upper)
                                await send_telegram_alert(f"[ALERT] {token_upper} mentioned by @{influencer}\\nTweet: {tweet[:100]}...")
                            except sqlite3.IntegrityError:
                                print(f"[-] {token_upper} already tracked.")
                        else:
                            print(f"[-] {token_upper} not found on CoinGecko.")
    if not found_tokens:
        print("[-] No new tokens found.")

async def update_prices_periodically():
    try:
        cursor.execute('SELECT id, token_symbol, price_at_detection FROM tokens')
        rows = cursor.fetchall()
        for token_id, token_symbol, price_at_detection in rows:
            symbol_clean = token_symbol.replace('$', '').lower()
            coins = cg.get_coins_list()
            for coin in coins:
                if symbol_clean == coin['symbol'].lower():
                    coin_data = cg.get_coin_by_id(coin['id'])
                    current_price = coin_data['market_data']['current_price']['usd']
                    if current_price and price_at_detection:
                        percent_change = ((current_price - price_at_detection) / price_at_detection) * 100
                        cursor.execute('''
                            UPDATE tokens
                            SET current_price = ?, percent_change = ?
                            WHERE id = ?
                        ''', (current_price, percent_change, token_id))
                        conn.commit()
    except Exception as e:
        print(f"[x] Error updating prices: {e}")

async def match_trending_tokens_with_mentions():
    trending = await fetch_trending_tokens_from_dexscreener()
    cursor.execute('SELECT token_symbol FROM tokens')
    tracked = [row[0].replace('$', '').lower() for row in cursor.fetchall()]
    for token in trending:
        if token in tracked:
            await send_telegram_alert(f"🚀 Token ${token.upper()} you're tracking is trending on DEX Screener!")

async def scan_top_gainers_losers():
    cursor.execute('SELECT token_symbol, percent_change FROM tokens')
    tokens = cursor.fetchall()

    gainers = []
    losers = []

    for token, percent in tokens:
        if percent and percent >= 50:
            gainers.append((token, percent))
        elif percent and percent <= -20:
            losers.append((token, percent))

    if gainers:
        message = "🚀 Top Gainers:\\n" + "\\n".join([f"{token}: +{percent:.2f}%" for token, percent in gainers])
        await send_telegram_alert(message)
    if losers:
        message = "⚠️ Top Losers:\\n" + "\\n".join([f"{token}: {percent:.2f}%" for token, percent in losers])
        await send_telegram_alert(message)

async def update_influencer_stats():
    cursor.execute('SELECT influencer, percent_change FROM tokens WHERE percent_change IS NOT NULL')
    rows = cursor.fetchall()

    stats = {}
    for influencer, change in rows:
        if influencer not in stats:
            stats[influencer] = []
        stats[influencer].append(change)

    for influencer, changes in stats.items():
        total = len(changes)
        avg_change = sum(changes) / total if total else 0
        cursor.execute('''
            INSERT INTO influencer_stats (influencer, total_mentions, avg_percent_change)
            VALUES (?, ?, ?)
            ON CONFLICT(influencer) DO UPDATE SET
                total_mentions=excluded.total_mentions,
                avg_percent_change=excluded.avg_percent_change
        ''', (influencer, total, avg_change))
    conn.commit()

# Main runner
async def main():
    await asyncio.gather(
        monitor_influencers(),
        update_prices_periodically(),
        match_trending_tokens_with_mentions(),
        scan_top_gainers_losers(),
        update_influencer_stats()
    )

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            print(f"[x] Error: {e}")
        finally:
            print("[+] Waiting for 1 hour...")
            asyncio.run(asyncio.sleep(3600))
