# main.py
from dotenv import load_dotenv
load_dotenv()
import os
import json
import logging
import re
from fastapi import FastAPI, Request
from pydantic import BaseModel
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import uvicorn

# --------------------- LOGGING ---------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("trilokana_bot")

# --------------------- CONFIG / ENV ---------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Trilokana_Marketing_Bot_Data")

logger.info(f"BOT_TOKEN set? {BOT_TOKEN is not None}")
logger.info(f"WEBHOOK_URL set? {WEBHOOK_URL is not None}")
logger.info(f"SPREADSHEET_NAME: {SPREADSHEET_NAME}")

# --------------------- GOOGLE SHEETS ---------------------
creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not creds_json:
    raise ValueError("GOOGLE_CREDENTIALS_JSON not set in env.")
creds_dict = json.loads(creds_json)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).sheet1

# --------------------- FASTAPI ---------------------
app = FastAPI()

# --------------------- TELEGRAM APPLICATION ---------------------
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN env var missing.")
application = Application.builder().token(BOT_TOKEN).build()

# --------------------- USER STATE ---------------------
# Simple in-memory state: { user_id: { step: int, Option, Name, Email, Phone, Query } }
user_data = {}
KNOWN_OPTIONS = ["Digital Marketing Strategy", "Paid Marketing", "SEO", "Creatives"]

# --------------------- VALIDATION ---------------------
def is_valid_email(email: str) -> bool:
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None

def is_valid_phone(phone: str) -> bool:
    # allow international with + and digits, or plain digits (min 7)
    normalized = phone.strip().replace(" ", "").replace("-", "")
    if normalized.startswith("+"):
        normalized = normalized[1:]
    return normalized.isdigit() and len(normalized) >= 7

# --------------------- HELPERS ---------------------
def reset_user(user_id: int):
    if user_id in user_data:
        logger.info("Resetting user_data for %s", user_id)
        del user_data[user_id]

def save_to_sheet_sync(data: dict):
    """Synchronous save (gspread is sync)."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp, data["Option"], data["Name"], data["Email"], data["Phone"], data["Query"]]
        sheet.append_row(row)
        logger.info("Saved row to Google Sheet: %s", row)
        return True
    except Exception as e:
        logger.exception("Failed saving to Google Sheet: %s", e)
        return False

# --------------------- HANDLERS ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Digital Marketing Strategy", callback_data="option_Digital Marketing Strategy"),
            InlineKeyboardButton("Paid Marketing", callback_data="option_Paid Marketing"),
        ],
        [
            InlineKeyboardButton("SEO", callback_data="option_SEO"),
            InlineKeyboardButton("Creatives", callback_data="option_Creatives"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        "Welcome to Trilokana Marketing!\n"
        "Visit our website: https://trilokana.com\n\n"
        "What are you looking for?"
    )
    logger.info("User %s invoked /start", update.effective_user.id if update.effective_user else "unknown")
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    elif update.effective_chat:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        logger.warning("button_handler called without callback_query")
        return

    user = query.from_user
    user_id = user.id
    data = query.data
    logger.info("CallbackQuery from user %s: %s", user_id, data)

    # Always answer to remove spinner immediately
    try:
        await query.answer()
    except Exception as e:
        logger.warning("query.answer() failed: %s", e)

    # Option selection
    if data.startswith("option_"):
        selected_option = data.replace("option_", "")
        user_data[user_id] = {
            "step": 2,
            "Option": selected_option,
            "Name": "",
            "Email": "",
            "Phone": "",
            "Query": ""
        }
        logger.info("User %s selected option: %s ; state=%s", user_id, selected_option, user_data[user_id])
        # remove inline keyboard to avoid duplicate clicks
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("Could not edit reply_markup (maybe message too old)")
        await query.message.reply_text(f"You selected: {selected_option}\nEnter your Name:")
        return

    # unknown callback_data -> log and ignore
    logger.warning("Unknown callback_data received: %s from user %s", data, user_id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    user = message.from_user
    user_id = user.id
    text = message.text.strip()
    logger.info("Message from %s: %s", user_id, text[:120])

    # If user hasn't started by clicking option, allow typing a known option as fallback
    if user_id not in user_data:
        if text in KNOWN_OPTIONS:
            user_data[user_id] = {
                "step": 2,
                "Option": text,
                "Name": "",
                "Email": "",
                "Phone": "",
                "Query": ""
            }
            logger.info("User %s typed known option: %s", user_id, text)
            await message.reply_text("Enter your Name:")
            return
        else:
            await message.reply_text("Please select a service using /start (buttons) or type one of: " + ", ".join(KNOWN_OPTIONS))
            return

    # Continue flow based on step
    step = user_data[user_id].get("step", 2)
    logger.info("User %s current step: %s", user_id, step)

    # 2 -> Name
    if step == 2:
        user_data[user_id]["Name"] = text
        user_data[user_id]["step"] = 3
        await message.reply_text("Enter your Email:")
        return

    # 3 -> Email
    if step == 3:
        if not is_valid_email(text):
            await message.reply_text("Invalid email format. Please enter a valid email (example@example.com):")
            return
        user_data[user_id]["Email"] = text
        user_data[user_id]["step"] = 4
        await message.reply_text("Enter your Phone Number (digits, min 7):")
        return

    # 4 -> Phone
    if step == 4:
        if not is_valid_phone(text):
            await message.reply_text("Invalid phone! Please enter digits only (min 7). You may include + for country code.")
            return
        user_data[user_id]["Phone"] = text
        user_data[user_id]["step"] = 5
        await message.reply_text("Enter your Query / Message:")
        return

    # 5 -> Query (final) -> SAVE immediately (Flow A)
    if step == 5:
        user_data[user_id]["Query"] = text
        logger.info("User %s completed data collection: %s", user_id, user_data[user_id])
        # Save synchronously to Google Sheets
        success = save_to_sheet_sync(user_data[user_id])
        if success:
            await message.reply_text("✅ Thank you! Your details have been recorded. We will contact you soon.")
            await message.reply_text("Contact us via WhatsApp: https://wa.me/7760225959")
        else:
            await message.reply_text("Sorry, there was an error saving your data. Please try again later.")
        # cleanup user state
        reset_user(user_id)
        return

    # fallback
    logger.warning("Unhandled step %s for user %s", step, user_id)
    await message.reply_text("Something went wrong. Please send /start to begin again.")
    reset_user(user_id)

# --------------------- REGISTER HANDLERS ---------------------
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# --------------------- WEBHOOK ---------------------
class TelegramUpdate(BaseModel):
    update_id: int
    message: dict = None
    callback_query: dict = None

@app.post("/webhook")
async def telegram_webhook(update: TelegramUpdate, request: Request):
    update_dict = update.dict()
    logger.info("Incoming update id=%s", update_dict.get("update_id"))
    telegram_update = Update.de_json(update_dict, application.bot)
    await application.process_update(telegram_update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"message": "Trilokana Telegram Bot is running!"}

# --------------------- STARTUP & SHUTDOWN ---------------------
@app.on_event("startup")
async def startup():
    logger.info("Initializing Telegram application...")
    await application.initialize()
    if WEBHOOK_URL:
        try:
            await application.bot.set_webhook(WEBHOOK_URL)
            logger.info("Webhook set to %s", WEBHOOK_URL)
        except Exception as e:
            logger.exception("Failed to set webhook: %s", e)
    else:
        logger.warning("WEBHOOK_URL not set; bot will not set webhook (use polling locally).")

@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down Telegram application...")
    await application.shutdown()

# --------------------- RUN ---------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
