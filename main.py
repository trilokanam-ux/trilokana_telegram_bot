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
logger = logging.getLogger(__name__)

# --------------------- CONFIG / ENV ---------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Trilokana_Marketing_Bot_Data")

logging.info(f"BOT_TOKEN set? {BOT_TOKEN is not None}")
logging.info(f"WEBHOOK_URL set? {WEBHOOK_URL is not None}")
logging.info(f"SPREADSHEET_NAME: {SPREADSHEET_NAME}")

# --------------------- GOOGLE SHEETS ---------------------
creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not creds_json:
    raise ValueError("GOOGLE_CREDENTIALS_JSON not set.")
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
user_data = {}
KNOWN_OPTIONS = ["Digital Marketing Strategy", "Paid Marketing", "SEO", "Creatives"]

# --------------------- VALIDATION ---------------------
def is_valid_email(email: str) -> bool:
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None

def is_valid_phone(phone: str) -> bool:
    return phone.isdigit() and len(phone) >= 10

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
    user_id = query.from_user.id
    selected_option = query.data

    # ✅ Immediately answer callback to remove spinner
    await query.answer()

    # Clear keyboard first
    try:
        await query.message.edit_reply_markup(None)
    except Exception:
        pass

    # ----- Confirmation -----
    if selected_option == "Yes":
        data = user_data.get(user_id)
        if data:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [timestamp, data["Option"], data["Name"], data["Email"], data["Phone"], data["Query"]]
            try:
                sheet.append_row(row)
            except Exception as e:
                logger.exception("Error appending to Google Sheet: %s", e)
        user_data.pop(user_id, None)
        await context.bot.send_message(chat_id=query.message.chat_id,
                                       text="✅ Thank you! Your details have been recorded.\nWe will contact you soon.")
        await context.bot.send_message(chat_id=query.message.chat_id,
                                       text="Contact us via WhatsApp: https://wa.me/7760225959")
        return

    elif selected_option == "No":
        user_data.pop(user_id, None)
        await context.bot.send_message(chat_id=query.message.chat_id,
                                       text="Let's start over. Use /start to select a service again.")
        return

    # ----- Normal option selection -----
    user_data[user_id] = {"step": 2, "Option": selected_option, "Name": "", "Email": "", "Phone": "", "Query": ""}
    await context.bot.send_message(chat_id=query.message.chat_id,
                                   text=f"You selected: {selected_option}\nEnter your Name:")

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
        if not is_valid_email(text):
            await message.reply_text("Invalid email! Please enter a valid email address:")
            return
        user_data[user_id]["Email"] = text
        user_data[user_id]["step"] = 4
        await message.reply_text("Enter your Phone Number:")
    elif step == 4:
        if not is_valid_phone(text):
            await message.reply_text("Invalid phone number! Please enter a valid phone number (digits only, min 10 digits):")
            return
        user_data[user_id]["Phone"] = text
        user_data[user_id]["step"] = 5
        await message.reply_text("Enter your Query:")
    elif step == 5:
        user_data[user_id]["Query"] = text
        data = user_data[user_id]
        summary_text = (
            f"Please confirm your details:\n\n"
            f"Service: {data['Option']}\n"
            f"Name: {data['Name']}\n"
            f"Email: {data['Email']}\n"
            f"Phone: {data['Phone']}\n"
            f"Query: {data['Query']}\n"
        )
        keyboard = [[InlineKeyboardButton("Yes", callback_data="Yes"),
                     InlineKeyboardButton("No", callback_data="No")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(summary_text, reply_markup=reply_markup)

# --------------------- REGISTER HANDLERS ---------------------
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# --------------------- WEBHOOK ---------------------
class TelegramUpdate(BaseModel):
    update_id: int
    message: dict = None

@app.post("/webhook")
async def telegram_webhook(update: TelegramUpdate, request: Request):
    update_dict = update.dict()
    telegram_update = Update.de_json(update_dict, application.bot)
    await application.process_update(telegram_update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"message": "Trilokana Telegram Bot is running!"}

# --------------------- STARTUP & SHUTDOWN ---------------------
@app.on_event("startup")
async def startup():
    await application.initialize()
    if WEBHOOK_URL:
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")

@app.on_event("shutdown")
async def shutdown():
    await application.shutdown()

# --------------------- RUN ---------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
