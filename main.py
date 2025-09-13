from dotenv import load_dotenv
load_dotenv()
import os
import json
import logging
from fastapi import FastAPI, Request
from pydantic import BaseModel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import re

# --------------------- LOGGING ---------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"BOT_TOKEN set? {os.environ.get('BOT_TOKEN') is not None}")
logger.info(f"WEBHOOK_URL set? {os.environ.get('WEBHOOK_URL') is not None}")
logger.info(f"GOOGLE_CREDENTIALS_JSON set? {'GOOGLE_CREDENTIALS_JSON' in os.environ}")

# --------------------- CONFIG ---------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Trilokana_Marketing_Bot_Data")

# --------------------- GOOGLE SHEETS ---------------------
creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not creds_json:
    raise ValueError("Environment variable GOOGLE_CREDENTIALS_JSON not set")

creds_dict = json.loads(creds_json)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).sheet1

# --------------------- FASTAPI ---------------------
app = FastAPI()

# --------------------- TELEGRAM ---------------------
application = Application.builder().token(BOT_TOKEN).build()
user_data = {}

# --------------------- VALIDATION ---------------------
def is_valid_email(email):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email)

def is_valid_phone(phone):
    pattern = r'^\+?\d{10,15}$'
    return re.match(pattern, phone)

# --------------------- HANDLERS ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Digital Marketing Strategy", callback_data='Digital Marketing Strategy'),
         InlineKeyboardButton("Paid Marketing", callback_data='Paid Marketing')],
        [InlineKeyboardButton("SEO", callback_data='SEO'),
         InlineKeyboardButton("Creatives", callback_data='Creatives')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        "Welcome to Trilokana Marketing!\n"
        "Visit our website: https://trilokana.com\n\n"
        "What are you looking for?"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    option = query.data

    # Initialize user session
    user_data[user_id] = {"step": 2, "Option": option, "Name": "", "Email": "", "Phone": "", "Query": ""}
    await query.message.reply_text("Enter your Name:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    if user_id not in user_data:
        await update.message.reply_text("Please select a service first by typing /start")
        return

    step = user_data[user_id]["step"]

    if step == 2:
        user_data[user_id]["Name"] = text
        user_data[user_id]["step"] = 3
        await update.message.reply_text("Enter your Email:")
    elif step == 3:
        if not is_valid_email(text):
            await update.message.reply_text("Invalid email. Please enter a valid Email:")
            return
        user_data[user_id]["Email"] = text
        user_data[user_id]["step"] = 4
        await update.message.reply_text("Enter your Phone Number (digits only, e.g., +911234567890):")
    elif step == 4:
        if not is_valid_phone(text):
            await update.message.reply_text("Invalid phone number. Please enter a valid Phone Number:")
            return
        user_data[user_id]["Phone"] = text
        user_data[user_id]["step"] = 5
        await update.message.reply_text("Enter your Query:")
    elif step == 5:
        user_data[user_id]["Query"] = text
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([
            timestamp,
            user_data[user_id]["Option"],
            user_data[user_id]["Name"],
            user_data[user_id]["Email"],
            user_data[user_id]["Phone"],
            user_data[user_id]["Query"]
        ])
        await update.message.reply_text(
            "Thank you! Your details have been recorded. We will contact you soon."
        )
        await update.message.reply_text(
            "Contact us via WhatsApp: https://wa.me/7760225959"
        )
        del user_data[user_id]

# --------------------- ADD HANDLERS ---------------------
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
    logger.info(f"Incoming update: {update_dict}")
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
    await application.bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

@app.on_event("shutdown")
async def shutdown():
    await application.shutdown()

# --------------------- RUN ---------------------
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
