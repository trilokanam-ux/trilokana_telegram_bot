from dotenv import load_dotenv
load_dotenv()
import os
import json
import logging
from fastapi import FastAPI, Request
from pydantic import BaseModel
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --------------------- CONFIG ---------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Trilokana_Marketing_Bot_Data")

# --------------------- LOGGING ---------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------- GOOGLE SHEETS ---------------------
creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not creds_json:
    raise ValueError("Environment variable GOOGLE_CREDENTIALS_JSON not set")

# Convert JSON string from env into dictionary
creds_dict = json.loads(creds_json)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).sheet1

# --------------------- FASTAPI ---------------------
app = FastAPI()

# --------------------- TELEGRAM ---------------------
application = Application.builder().token(BOT_TOKEN).build()

# User session data
user_data = {}

# --------------------- HANDLERS ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Digital Marketing Strategy", "Paid Marketing"], ["SEO", "Creatives"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    welcome_text = (
        "Welcome to Trilokana Marketing!\n"
        "Visit our website: https://trilokana.com\n\n"
        "What are you looking for?"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    if user_id not in user_data:
        user_data[user_id] = {"step": 1, "Option": text, "Name": "", "Email": "", "Phone": "", "Query": ""}
        user_data[user_id]["step"] = 2
        await update.message.reply_text("Enter your Name:")
    elif user_data[user_id]["step"] == 2:
        user_data[user_id]["Name"] = text
        user_data[user_id]["step"] = 3
        await update.message.reply_text("Enter your Email:")
    elif user_data[user_id]["step"] == 3:
        user_data[user_id]["Email"] = text
        user_data[user_id]["step"] = 4
        await update.message.reply_text("Enter your Phone Number:")
    elif user_data[user_id]["step"] == 4:
        user_data[user_id]["Phone"] = text
        user_data[user_id]["step"] = 5
        await update.message.reply_text("Enter your Query:")
    elif user_data[user_id]["step"] == 5:
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

# Add handlers to the Telegram application
application.add_handler(CommandHandler("start", start))
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
