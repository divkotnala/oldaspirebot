import logging
import os
import datetime
import tempfile
import json

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

# ========================== CONFIG ==========================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON") 

approved_numbers = ["7217684362", "9625060017", "9798393702","9354197496"]

SHEET_ID = "1RicQuJRGK5ZmlVZGGRZmU-mEtbYx_4kmzzsLPcgdyFE"
DRIVE_FOLDER_ID = "14bDZ23j2jhXLWs_XxFb3xnOr-8GPlQhj"

# ========================== GOOGLE API Setup ==========================
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(GOOGLE_CREDS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

gauth = GoogleAuth()
gauth.credentials = creds
drive = GoogleDrive(gauth)

# ========================== TELEGRAM BOT ==========================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

user_phone_numbers = {}
user_names = {}

ASK_NAME, ASK_PHONE, WAITING_FOR_DOUBT = range(3)

# Welcome message
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to AspireSetGo Doubt Solving Portal! 🙏\n\n"
        "To get started, please {provide your name}. This is required for registration."

    )
    return ASK_NAME

# Ask for the user's name
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.text.strip()
    user_names[update.message.from_user.id] = user_name
    await update.message.reply_text(
        "Thank you, {0}! Now, please send your **registered phone number** to continue. "
        "Don't share your phone number with others as it is the key to start conversations. "
        "If others have it, they can access your account and you may get banned.".format(user_name)
    )
    return ASK_PHONE

# Phone number handler
async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()

    if phone in approved_numbers:
        user_phone_numbers[update.message.from_user.id] = phone
        # Add the user's name and phone number to the spreadsheet
        name = user_names[update.message.from_user.id]
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, name, phone, str(update.message.from_user.id), "-", "Verified"])
        await update.message.reply_text("✅ Verified! Now whenever you want to post any doubt just simply send Image/text to us. Now send your doubt as text or image.\n**If you don't get confirmation your doubt is recorded then try restarting the bot by /start**")
        return WAITING_FOR_DOUBT
    else:
        await update.message.reply_text("❌ Your number is not authorized. Contact admin or Restart the bot by /start command \nNeed any help call 📞 9625060017")
        return ConversationHandler.END

# Handle text doubts
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_phone_numbers:
        await update.message.reply_text("❗ Please verify your phone number first by /start")
        return

    text_doubt = update.message.text
    phone = user_phone_numbers[user_id]
    name = user_names[user_id]

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, name, phone, str(user_id), text_doubt, "Pending"])

    await update.message.reply_text("✅ Your text doubt has been recorded! We will get back soon.")

# Handle image doubts
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_phone_numbers:
        await update.message.reply_text("❗ Please verify your phone number first by restarting the bot by /start command.")
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file_name = temp_file.name
    await file.download_to_drive(custom_path=temp_file_name)

    gfile = drive.CreateFile({'parents': [{'id': DRIVE_FOLDER_ID}], 'title': os.path.basename(temp_file_name)})
    gfile.SetContentFile(temp_file_name)
    gfile.Upload()
    drive_link = f"https://drive.google.com/uc?id={gfile['id']}"

    phone = user_phone_numbers[user_id]
    name = user_names[user_id]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, name, phone, str(user_id), "-", drive_link, "Pending"])
    await update.message.reply_text("✅ Your Image doubt has been recorded! We will get back soon.")

    temp_file.close()
    os.unlink(temp_file_name)

    await update.message.reply_text("✅ Your image doubt has been recorded! We will get back soon.")

# Unknown messages
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❗ Sorry, I don't understand that command.")

# Main function
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            WAITING_FOR_DOUBT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                MessageHandler(filters.PHOTO, handle_photo)
            ]
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    
    # Railway provides the PORT environment variable for web applications.
    PORT = int(os.environ.get('PORT', 8443))
    
    # This is a made-up URL for now. Railway will provide the real one.
    # We will set it later via a bot command.
    HEROKU_APP_NAME = os.environ.get("RAILWAY_STATIC_URL") # Railway provides this
    
    # Start the bot
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{HEROKU_APP_NAME}/{BOT_TOKEN}"
    )