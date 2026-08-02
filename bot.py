import os
import re
import logging
from datetime import datetime, timedelta

import requests
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_BASE_URL = "https://open.er-api.com/v6/latest/{base}"
CACHE_TTL = timedelta(minutes=10)

_rate_cache = {}  # base_currency -> (timestamp, rates_dict)


def get_rates(base: str):
    base = base.upper()
    now = datetime.utcnow()
    cached = _rate_cache.get(base)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    resp = requests.get(API_BASE_URL.format(base=base), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise ValueError(data.get("error-type", "unknown error fetching rates"))

    rates = data["rates"]
    _rate_cache[base] = (now, rates)
    return rates


def convert(amount: float, from_cur: str, to_cur: str):
    from_cur = from_cur.upper()
    to_cur = to_cur.upper()
    rates = get_rates(from_cur)
    if to_cur not in rates:
        raise ValueError(f"Unknown currency code: {to_cur}")
    rate = rates[to_cur]
    return amount * rate, rate


CONVERT_PATTERN = re.compile(
    r"^\s*([\d.,]+)\s*([a-zA-Z]{3})\s*(?:to|in|->|=)?\s*([a-zA-Z]{3})\s*$"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "\U0001F44B *Welcome to CurrencyConvertrBot!*\n\n"
        "I convert currencies using live exchange rates.\n\n"
        "*Commands:*\n"
        "/convert <amount> <from> <to> \u2014 e.g. /convert 100 USD EUR\n"
        "/rate <from> <to> \u2014 e.g. /rate USD EUR\n"
        "/currencies \u2014 list supported currency codes\n"
        "/help \u2014 show this message\n\n"
        "Or just type naturally: `100 USD to EUR`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def convert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(
            "Usage: /convert <amount> <from> <to>\nExample: /convert 100 USD EUR"
        )
        return
    amount_str, from_cur, to_cur = args
    await _do_convert(update, amount_str, from_cur, to_cur)


async def rate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "Usage: /rate <from> <to>\nExample: /rate USD EUR"
        )
        return
    from_cur, to_cur = args
    await _do_convert(update, "1", from_cur, to_cur)


async def currencies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rates = get_rates("USD")
    except Exception as e:
        await update.message.reply_text(f"\u26A0\uFE0F Couldn't fetch currency list: {e}")
        return
    codes = sorted(rates.keys())
    chunk = ", ".join(codes)
    await update.message.reply_text(f"Supported currencies ({len(codes)}):\n{chunk}")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    match = CONVERT_PATTERN.match(text)
    if not match:
        await update.message.reply_text(
            "I didn't understand that. Try: `100 USD to EUR` or /help",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    amount_str, from_cur, to_cur = match.groups()
    await _do_convert(update, amount_str, from_cur, to_cur)


async def _do_convert(update: Update, amount_str: str, from_cur: str, to_cur: str):
    try:
        amount = float(amount_str.replace(",", ""))
    except ValueError:
        await update.message.reply_text("\u26A0\uFE0F Invalid amount.")
        return

    try:
        result, rate = convert(amount, from_cur, to_cur)
    except Exception as e:
        await update.message.reply_text(f"\u26A0\uFE0F Error: {e}")
        return

    from_cur = from_cur.upper()
    to_cur = to_cur.upper()
    await update.message.reply_text(
        f"\U0001F4B1 {amount:,.2f} {from_cur} = *{result:,.4f} {to_cur}*\n"
        f"Rate: 1 {from_cur} = {rate:,.6f} {to_cur}",
        parse_mode=ParseMode.MARKDOWN,
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("convert", convert_cmd))
    app.add_handler(CommandHandler("rate", rate_cmd))
    app.add_handler(CommandHandler("currencies", currencies_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
