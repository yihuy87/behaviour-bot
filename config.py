import os
from dotenv import load_dotenv

load_dotenv()

# === TELEGRAM ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID", "")
TELEGRAM_ADMIN_USERNAME = os.getenv("TELEGRAM_ADMIN_USERNAME", "")

# === BINANCE FUTURES (USDT PERP) ===
BINANCE_REST_URL = "https://fapi.binance.com"
BINANCE_STREAM_URL = "wss://fstream.binance.com/stream"

# Filtering volume minimum (dalam USDT) untuk pilih pair
MIN_VOLUME_USDT = float(os.getenv("MIN_VOLUME_USDT", "1000000"))

# Berapa banyak pair USDT yang discan
MAX_USDT_PAIRS = int(os.getenv("MAX_USDT_PAIRS", "300"))

# Tier minimum sinyal yang dikirim: "A+", "A", "B"
MIN_TIER_TO_SEND = os.getenv("MIN_TIER_TO_SEND", "A")

# Cooldown default antar sinyal per pair (detik)
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "600"))

# Refresh interval untuk daftar pair (jam)
REFRESH_PAIR_INTERVAL_HOURS = int(os.getenv("REFRESH_PAIR_INTERVAL_HOURS", "24"))
