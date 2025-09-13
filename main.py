# main.py
from dotenv import load_dotenv
load_dotenv()
import os
import json
import logging
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
logger = logging.getLogger(__name__)

# --------------------- CONFIG / ENV ---------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # e.g. https://<your-railway-domain>/webhook
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Trilokana_Marketing_Bot_Data")

logging.info(f"BOT_TOKEN set? {BOT_TOKEN is not None}")
logging.info(f"WEBHOOK_URL set? {WEBHOOK_URL is not None}")
logging.info(f"SPREADSHEET_NAME: {SPREADSHEET_NAME}")

# --------------------- GOOGLE SHEETS ---------------------
creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not creds_json:
    raise ValueError("Environment variable GOOGLE_CREDENTIALS_JSON not set. Paste service account JSON as string.")

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

# Simple in-memory user state
user_data = {}

KNOWN_OPTIONS = ["Digital Marketing Strategy", "Paid Marketing", "SEO", "Creatives"]

# --------------------- HANDLERS ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Digital Marketing Strategy", callback_data="Digital Marketing Strategy"),
            InlineKeyboardButton("Paid Marketing", callback_data="Paid Marketing"),
        ],
        [
            InlineKeyboardButton("SEO", callback_data="SEO"),
            InlineKeyboardButton("Creatives", callback_data="Creatives"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        "Welcome to Trilokana Marketing!\n"
        "Visit our website: https://trilokana.com\n\n"
        "What are you looking for?"
    )
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    elif update.effective_chat:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    # ✅ Acknowledge the callback so spinner disappears
    await query.answer()

    selected_option = query.data
    user_id = query.from_user.id

    user_data[user_id] = {
        "step": 2,
        "Option": selected_option,
        "Name": "",
        "Email": "",
        "Phone": "",
        "Query": ""
    }

    # Try to remove inline buttons (but don’t fail if it errors)
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Could not edit message markup: {e}")

    # ✅ Always send a new message (safer than reply_text here)
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=f"You selected: {selected_option}\nEnter your Name:"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id not in user_data:
        if text in KNOWN_OPTIONS:
            user_data[user_id] = {"step": 2, "Option": text, "Name": "", "Email": "", "Phone": "", "Query": ""}
            await message.reply_text("Enter your Name:")
            return
        else:
            await message.reply_text("Please choose a service using /start or type one of: " + ", ".join(KNOWN_OPTIONS))
            return

    step = user_data[user_id].get("step", 2)

    if step == 2:
        user_data[user_id]["Name"] = text
        user_data[user_id]["step"] = 3
        await message.reply_text("Enter your Email:")
    elif step == 3:
        user_data[user_id]["Email"] = text
        user_data[user_id]["step"] = 4
        await message.reply_text("Enter your Phone Number:")
    elif step == 4:
        user_data[user_id]["Phone"] = text
        user_data[user_id]["step"] = 5
        await message.reply_text("Enter your Query:")
    elif step == 5:
        user_data[user_id]["Query"] = text
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            timestamp,
            user_data[user_id]["Option"],
            user_data[user_id]["Name"],
            user_data[user_id]["Email"],
            user_data[user_id]["Phone"],
            user_data[user_id]["Query"],
        ]
        try:
            sheet.append_row(row)
            await message.reply_text("Thank you! Your details have been recorded. We will contact you soon.")
            await message.reply_text("Contact us via WhatsApp: https://wa.me/7760225959")
        except Exception as e:
            logger.exception("Error appending to Google Sheet: %s", e)
            await message.reply_text("Sorry, there was an error saving your data. Please try again later.")
        if user_id in user_data:
            del user_data[user_id]

# --------------------- REGISTER HANDLERS ---------------------
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# --------------------- WEBHOOK ROUTE ---------------------
class TelegramUpdate(BaseModel):
    update_id: int
    message: dict = None
    callback_query: dict = None  # ✅ Add this so InlineKeyboard updates parse correctly

@app.post("/webhook")
async def telegram_webhook(update: TelegramUpdate, request: Request):
    update_dict = update.dict()
    logger.info(f"Incoming update: {update_dict.get('update_id')}")
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
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")
    else:
        logger.warning("WEBHOOK_URL is not set. Webhook will not be configured.")

@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down Telegram application...")
    await application.shutdown()

# --------------------- RUN ---------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
