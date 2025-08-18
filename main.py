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
# UPDATED: Renamed BOT_TOKEN to TOKEN for clarity
TOKEN = os.environ.get("TOKEN")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
# NEW: Get the WEBAPP_URL you will set in Railway
WEBAPP_URL = os.environ.get("WEBAPP_URL")

approved_numbers = ["7217684362", "9625060017", "9798393702", "9354197496"]

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

# REMOVED: Global dictionaries for user data are unreliable on Railway
# user_phone_numbers = {}
# user_names = {}

ASK_NAME, ASK_PHONE, WAITING_FOR_DOUBT = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation and asks for the user's name."""
    await update.message.reply_text(
        "Welcome to AspireSetGo Doubt Solving Portal! 🙏\n\n"
        "To get started, please provide your name. This is required for registration."
    )
    return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the name in context and asks for the phone number."""
    user_name = update.message.text.strip()
    # UPDATED: Use context.user_data to store data for this specific user
    context.user_data['name'] = user_name
    await update.message.reply_text(
        f"Thank you, {user_name}! Now, please send your **registered phone number** to continue. "
        "This is your key to start conversations, so don't share it."
    )
    return ASK_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Verifies the phone number and stores it in context."""
    phone = update.message.text.strip()
    # UPDATED: Retrieve name from context.user_data
    name = context.user_data.get('name', 'N/A')

    if phone in approved_numbers:
        # UPDATED: Store phone number and verification status in context
        context.user_data['phone'] = phone
        context.user_data['is_verified'] = True
        
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # FIXED: Standardized sheet columns
        sheet.append_row([now, name, phone, str(update.message.from_user.id), "-", "-", "Verified"])
        
        await update.message.reply_text(
            "✅ Verified! You can now send your doubts as text or images.\n\n"
            "If you don't get a confirmation, try restarting with /start"
        )
        return WAITING_FOR_DOUBT
    else:
        await update.message.reply_text(
            "❌ Your number is not authorized. Contact an admin or restart with /start.\n"
            "Need help? Call 📞 9625060017"
        )
        return ConversationHandler.END

def is_user_verified(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Helper function to check if a user is verified via context data."""
    return context.user_data.get('is_verified', False)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text doubts from verified users."""
    if not is_user_verified(context):
        await update.message.reply_text("❗ Please verify your phone number first using /start.")
        return

    text_doubt = update.message.text
    phone = context.user_data['phone']
    name = context.user_data['name']
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # FIXED: Standardized sheet columns (Text Doubt, Drive Link, Status)
    sheet.append_row([now, name, phone, str(update.message.from_user.id), text_doubt, "-", "Pending"])
    await update.message.reply_text("✅ Your text doubt has been recorded! We'll get back to you soon.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles image doubts from verified users."""
    if not is_user_verified(context):
        await update.message.reply_text("❗ Please verify your phone number first using /start.")
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
        await file.download_to_drive(custom_path=temp_file.name)
        
        gfile = drive.CreateFile({
            'parents': [{'id': DRIVE_FOLDER_ID}], 'title': os.path.basename(temp_file.name)
        })
        gfile.SetContentFile(temp_file.name)
        gfile.Upload()
        drive_link = f"https://drive.google.com/uc?id={gfile['id']}"

    os.unlink(temp_file.name)

    phone = context.user_data['phone']
    name = context.user_data['name']
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # FIXED: Standardized sheet columns for consistency
    sheet.append_row([now, name, phone, str(update.message.from_user.id), "-", drive_link, "Pending"])
    
    # FIXED: Removed duplicate reply message
    await update.message.reply_text("✅ Your image doubt has been recorded! We'll get back to you soon.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """NEW: Allows users to cancel the registration process."""
    await update.message.reply_text("Registration cancelled. You can start again with /start.")
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles any commands that are not recognized."""
    await update.message.reply_text("❗ Sorry, I don't understand that command.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

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
        fallbacks=[CommandHandler('cancel', cancel)], # NEW: Added a cancel fallback for better UX
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    
    # --- Webhook Setup for Railway ---
    PORT = int(os.environ.get('PORT', 8080))
    
    # FIXED: Using the correct variable names for the webhook URL
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{WEBAPP_URL}/{TOKEN}"
    )