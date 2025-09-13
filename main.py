import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
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
import asyncio

# ----------------- Logging -----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------- Config -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Trilokana_Marketing_Bot_Data")

logger.info("BOT_TOKEN set? %s", bool(BOT_TOKEN))
logger.info("WEBHOOK_URL set? %s", bool(WEBHOOK_URL))
logger.info("SPREADSHEET_NAME: %s", SPREADSHEET_NAME)

# ----------------- FastAPI -----------------
app = FastAPI()

class TelegramRequest(BaseModel):
    update_id: int
    message: dict | None = None
    callback_query: dict | None = None

# ----------------- Google Sheets Setup -----------------
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SPREADSHEET_NAME).sheet1
except Exception as e:
    logger.error("Google Sheets setup failed: %s", e)
    sheet = None

# ----------------- Telegram App -----------------
application = Application.builder().token(BOT_TOKEN).build()

# Store user session data
user_data = {}

def reset_user(user_id):
    if user_id in user_data:
        del user_data[user_id]

# ----------------- Command Handlers -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    reset_user(user_id)

    keyboard = [
        [InlineKeyboardButton("Social Media Marketing", callback_data="opt_smm")],
        [InlineKeyboardButton("Performance Marketing", callback_data="opt_pm")],
        [InlineKeyboardButton("SEO", callback_data="opt_seo")],
        [InlineKeyboardButton("Website Development", callback_data="opt_web")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("👋 Welcome! Please choose an option:", reply_markup=reply_markup)

# ----------------- Callback Handler -----------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # Option selected
    if data.startswith("opt_"):
        option = data.split("_", 1)[1]
        user_data[user_id] = {"Option": option, "step": 1}
        await query.message.reply_text("Please enter your full name:")
        return

    # Confirmation step
    if data == "confirm_yes":
        if user_id not in user_data:
            await query.message.reply_text("Session expired. Please /start again.")
            return
        success = save_to_sheet_sync(user_data[user_id])
        if success:
            await query.message.reply_text("✅ Thank you! Your details have been recorded.")
            await query.message.reply_text("📩 Contact us via WhatsApp: https://wa.me/7760225959")
        else:
            await query.message.reply_text("⚠️ Error saving your details. Please try again.")
        reset_user(user_id)
        return

    if data == "confirm_no":
        reset_user(user_id)
        await query.message.reply_text("❌ Okay, let's start again. Use /start to restart.")
        return

# ----------------- Message Handler -----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    if user_id not in user_data:
        await update.message.reply_text("Please use /start to begin.")
        return

    step = user_data[user_id].get("step", 0)

    # Step 1 -> Name
    if step == 1:
        user_data[user_id]["Name"] = text
        user_data[user_id]["step"] = 2
        await update.message.reply_text("📧 Please enter your email address:")
        return

    # Step 2 -> Email
    if step == 2:
        user_data[user_id]["Email"] = text
        user_data[user_id]["step"] = 3
        await update.message.reply_text("📱 Please enter your phone number:")
        return

    # Step 3 -> Phone
    if step == 3:
        user_data[user_id]["Phone"] = text
        user_data[user_id]["step"] = 4
        await update.message.reply_text("💬 Please enter your query:")
        return

    # Step 4 -> Query (final input)
    if step == 4:
        user_data[user_id]["Query"] = text
        user_data[user_id]["step"] = 5

        summary = (
            f"Please confirm your details:\n\n"
            f"📝 Option: {user_data[user_id]['Option']}\n"
            f"👤 Name: {user_data[user_id]['Name']}\n"
            f"📧 Email: {user_data[user_id]['Email']}\n"
            f"📱 Phone: {user_data[user_id]['Phone']}\n"
            f"💬 Query: {user_data[user_id]['Query']}\n\n"
            "Are these correct?"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ No", callback_data="confirm_no"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(summary, reply_markup=reply_markup)
        return

# ----------------- Google Sheets Save -----------------
def save_to_sheet_sync(data: dict):
    try:
        if not sheet:
            return False
        sheet.append_row([
            data.get("Option", ""),
            data.get("Name", ""),
            data.get("Email", ""),
            data.get("Phone", ""),
            data.get("Query", ""),
        ])
        return True
    except Exception as e:
        logger.error("Error saving to sheet: %s", e)
        return False

# ----------------- Register Handlers -----------------
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ----------------- FastAPI Routes -----------------
@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return JSONResponse({"ok": True})

@app.on_event("startup")
async def startup():
    logger.info("Initializing Telegram application...")
    await application.bot.set_webhook(WEBHOOK_URL + "/webhook")

@app.on_event("shutdown")
async def shutdown():
    await application.shutdown()
    await application.stop()
