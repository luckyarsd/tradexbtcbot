import logging
import requests
import pandas as pd
import datetime
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import ta  # Technical Analysis library

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8173553498:AAHTSN8Dv5B04yPhOewl3zJgHswhZYRXsKk"
BOT_GENERAL_DESCRIPTION = "Crypto trading assistant bot with advanced multi-indicator signals on 5m timeframe."
BOT_PREDICTION_PURPOSE = "Providing BTC/USDT trade signals using RSI, EMA, MACD, Bollinger Bands, Volume surge, and candle patterns."

def detect_candlestick_pattern(df):
    """
    Detect Bullish or Bearish Engulfing pattern on the last candle.
    Returns 'bullish_engulfing', 'bearish_engulfing', or None.
    """
    if len(df) < 2:
        return None
    
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Bullish Engulfing: Last candle body engulfs previous, last is green
    if (last['close'] > last['open'] and
        prev['close'] < prev['open'] and
        last['close'] > prev['open'] and
        last['open'] < prev['close']):
        return 'bullish_engulfing'

    # Bearish Engulfing: Last candle body engulfs previous, last is red
    if (last['close'] < last['open'] and
        prev['close'] > prev['open'] and
        last['open'] > prev['close'] and
        last['close'] < prev['open']):
        return 'bearish_engulfing'

    return None

async def fetch_and_analyze():
    """Fetch 5m BTCUSDT data and analyze using multiple indicators."""
    url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=100"

    # Run blocking requests.get in a separate thread asynchronously
    response = await asyncio.to_thread(requests.get, url)
    data = response.json()

    df = pd.DataFrame(data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])

    # Convert types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)

    # Indicators
    df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
    df['ema20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
    df['ema50'] = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()
    macd = ta.trend.MACD(close=df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_diff'] = macd.macd_diff()
    bollinger = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_high'] = bollinger.bollinger_hband()
    df['bb_low'] = bollinger.bollinger_lband()
    df['bb_mid'] = bollinger.bollinger_mavg()

    # Volume surge: compare last volume to 2-period avg volume, surge if > 1.3x (less strict)
    df['vol_avg2'] = df['volume'].rolling(window=2).mean()
    last = df.iloc[-1]

    # Candlestick pattern detection
    candle_pattern = detect_candlestick_pattern(df)

    # Scoring System (weighted)
    score = 0
    reasons = []

    # RSI weight 2
    if last['rsi'] < 35:
        score += 2
        reasons.append("🔻 RSI < 35 (Oversold)")
    elif last['rsi'] > 65:
        score -= 2
        reasons.append("🔺 RSI > 65 (Overbought)")

    # EMA weight 1
    if last['ema20'] > last['ema50']:
        score += 1
        reasons.append("🟢 EMA20 > EMA50 (Uptrend)")
    elif last['ema20'] < last['ema50']:
        score -= 1
        reasons.append("🔴 EMA20 < EMA50 (Downtrend)")

    # MACD weight 1
    if last['macd'] > last['macd_signal']:
        score += 1
        reasons.append("📈 MACD Bullish")
    elif last['macd'] < last['macd_signal']:
        score -= 1
        reasons.append("📉 MACD Bearish")

    # Bollinger Mid weight 0.5
    if last['close'] > last['bb_mid']:
        score += 0.5
        reasons.append("🟢 Above BB Mid")
    else:
        score -= 0.5
        reasons.append("🔴 Below BB Mid")

    # Volume surge weight 0.5 (threshold relaxed)
    if last['volume'] > 1.3 * last['vol_avg2']:
        score += 0.5
        reasons.append("💥 Volume Surge")

    # Candle pattern weight 1
    if candle_pattern == 'bullish_engulfing':
        score += 1
        reasons.append("🕯️ Bullish Engulfing")
    elif candle_pattern == 'bearish_engulfing':
        score -= 1
        reasons.append("🕯️ Bearish Engulfing")

    # Final signal decision
    if score >= 2.5:
        signal = "🟢 *BUY* — Momentum building"
    elif score <= -2.5:
        signal = "🔴 *SELL* — Possible downside"
    else:
        signal = "⚪️ *WAIT* — No clear trend"

    return {
        'price': last['close'],
        'rsi': last['rsi'],
        'ema20': last['ema20'],
        'ema50': last['ema50'],
        'macd': last['macd'],
        'macd_signal': last['macd_signal'],
        'bb_high': last['bb_high'],
        'bb_low': last['bb_low'],
        'volume': last['volume'],
        'vol_avg2': last['vol_avg2'],
        'candle_pattern': candle_pattern,
        'signal': signal,
        'reasons': reasons,
        'score': score,
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

async def handle_trade_prediction_callback(update: Update, context: object) -> None:
    query = update.callback_query
    await query.answer()

    try:
        await query.edit_message_text("🔄 *Refreshing data...* Please wait.", parse_mode='Markdown')

        analysis = await fetch_and_analyze()

        text = (
            f"📊 *BTC/USDT 5m Analysis*\n\n"
            f"💰 Price: `${analysis['price']:.2f}`\n"
            f"📈 RSI: `{analysis['rsi']:.2f}`\n"
            f"📊 EMA20: `{analysis['ema20']:.2f}`\n"
            f"📊 EMA50: `{analysis['ema50']:.2f}`\n"
            f"📉 MACD: `{analysis['macd']:.4f}`\n"
            f"📉 MACD Signal: `{analysis['macd_signal']:.4f}`\n"
            f"🎢 Bollinger Bands: High `{analysis['bb_high']:.2f}`, Low `{analysis['bb_low']:.2f}`\n"
            f"📊 Volume: `{analysis['volume']:.4f}` (Avg2 `{analysis['vol_avg2']:.4f}`)\n"
            f"🕯️ Candle Pattern: `{analysis['candle_pattern'] or 'None'}`\n\n"
            f"🧠 Signal Score: `{analysis['score']:.2f}`\n"
            f"{analysis['signal']}\n\n"
            f"🔍 *Reasons:*\n" + "\n".join(analysis['reasons']) + "\n\n"
            f"⏰ _Updated at {analysis['timestamp']}_"
        )

        keyboard = [[InlineKeyboardButton("🔁 Refresh Again", callback_data='start_trade_prediction')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in trade prediction: {e}")
        await query.edit_message_text(f"❌ Error fetching data:\n{e}")

async def start(update: Update, context: object) -> None:
    user_name = update.effective_user.first_name if update.effective_user else "there"
    keyboard = [[InlineKeyboardButton("Start Prediction", callback_data='start_trade_prediction')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(f"Hello {user_name}! I am your crypto assistant bot.")
    await update.message.reply_text(
        "Tap the button below to get BTC/USDT 5-minute timeframe trade predictions.",
        reply_markup=reply_markup
    )

async def handle_greeting(update: Update, context: object) -> None:
    user_name = update.effective_user.first_name if update.effective_user else "there"
    await update.message.reply_text(f"Hi {user_name}! How can I help you today?")

async def handle_purpose_query(update: Update, context: object) -> None:
    await update.message.reply_text(BOT_GENERAL_DESCRIPTION)

async def handle_message(update: Update, context: object) -> None:
    text = update.message.text.lower()
    user_name = update.effective_user.first_name if update.effective_user else "there"

    if "how are you" in text:
        await update.message.reply_text("I'm a bot, so I don't have feelings, but I'm operating perfectly!")
    elif "thank you" in text or "thanks" in text:
        await update.message.reply_text("You're most welcome!")
    elif "your name" in text:
        await update.message.reply_text("I don't have a personal name, but you can call me Bot!")
    elif "test" in text:
        await update.message.reply_text("Test successful! I received your message.")
    else:
        await update.message.reply_text("I'm sorry, I didn't understand that. Try /start or tap a button.")

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^(hey|hi|hello)\b'), handle_greeting))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'.*(purpose|why created|what are you).*'), handle_purpose_query))
    application.add_handler(CallbackQueryHandler(handle_trade_prediction_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
