# main.py (updated for safe chat_id and full flow)
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Trilokana_Marketing_Bot_Data")

creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not creds_json:
    raise ValueError("GOOGLE_CREDENTIALS_JSON not set.")
creds_dict = json.loads(creds_json)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).sheet1

app = FastAPI()
application = Application.builder().token(BOT_TOKEN).build()

user_data = {}
KNOWN_OPTIONS = ["Digital Marketing Strategy", "Paid Marketing", "SEO", "Creatives"]

def is_valid_email(email: str) -> bool:
    return re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email) is not None

def is_valid_phone(phone: str) -> bool:
    return phone.isdigit() and len(phone) >= 10

def reset_user(user_id):
    if user_id in user_data:
        user_data.pop(user_id)

def save_to_sheet(data):
    try:
        row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data["Option"], data["Name"], data["Email"], data["Phone"], data["Query"]]
        sheet.append_row(row)
        logger.info("Saved to Google Sheet")
    except Exception as e:
        logger.exception("Error saving to Google Sheet: %s", e)

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
    welcome_text = "Welcome to Trilokana Marketing!\nVisit our website: https://trilokana.com\n\nWhat are you looking for?"
    chat_id = update.effective_chat.id if update.effective_chat else update.message.chat.id
    await context.bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=reply_markup)
    logger.info(f"/start sent to user {chat_id}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat.id if query.message else user_id
    data = query.data
    logger.info(f"Callback from user {user_id}: {data}")

    try:
        if query.message:
            await query.message.edit_reply_markup(None)
    except Exception:
        pass

    if data.startswith("option_"):
        selected_option = data.replace("option_", "")
        user_data[user_id] = {"step": 2, "Option": selected_option, "Name": "", "Email": "", "Phone": "", "Query": ""}
        await context.bot.send_message(chat_id=chat_id, text=f"You selected: {selected_option}\nEnter your Name:")
        return

    if data == "Yes":
        info = user_data.get(user_id)
        if info:
            save_to_sheet(info)
        reset_user(user_id)
        await context.bot.send_message(chat_id=chat_id, text="✅ Thank you! Your details have been recorded.")
        await context.bot.send_message(chat_id=chat_id, text="Contact us via WhatsApp: https://wa.me/7760225959")
        return
    elif data == "No":
        reset_user(user_id)
        await context.bot.send_message(chat_id=chat_id, text="Let's start over. Use /start to select a service again.")
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    user_id = message.from_user.id
    chat_id = message.chat_id
    text = message.text.strip()
    logger.info(f"Message from {user_id}: {text}")

    if user_id not in user_data:
        await message.reply_text("Please select a service first using /start")
        return

    step = user_data[user_id]["step"]
    if step == 2:
        user_data[user_id]["Name"] = text
        user_data[user_id]["step"] = 3
        await message.reply_text("Enter your Email:")
    elif step == 3:
        if not is_valid_email(text):
            await message.reply_text("Invalid email! Enter a valid email:")
            return
        user_data[user_id]["Email"] = text
        user_data[user_id]["step"] = 4
        await message.reply_text("Enter your Phone Number:")
    elif step == 4:
        if not is_valid_phone(text):
            await message.reply_text("Invalid phone number! Enter digits only (min 10 digits):")
            return
        user_data[user_id]["Phone"] = text
        user_data[user_id]["step"] = 5
        await message.reply_text("Enter your Query:")
    elif step == 5:
        user_data[user_id]["Query"] = text
        data = user_data[user_id]
        summary = (f"Please confirm your details:\n\nService: {data['Option']}\nName: {data['Name']}\nEmail: {data['Email']}\nPhone: {data['Phone']}\nQuery: {data['Query']}")
        keyboard = [[InlineKeyboardButton("Yes", callback_data="Yes"), InlineKeyboardButton("No", callback_data="No")]]
        await message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard))

application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

class TelegramUpdate(BaseModel):
    update_id: int
    message: dict = None

@app.post("/webhook")
async def telegram_webhook(update: TelegramUpdate):
    telegram_update = Update.de_json(update.dict(), application.bot)
    await application.process_update(telegram_update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"message": "Bot running"}

@app.on_event("startup")
async def startup():
    await application.initialize()
    if WEBHOOK_URL:
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")

@app.on_event("shutdown")
async def shutdown():
    await application.shutdown()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
