import requests 
import json
import logging
import os
import datetime
import tempfile
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
    PicklePersistence,
    Application
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

# ========================== CONFIG ==========================
TOKEN = os.environ.get("TOKEN")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
WEBAPP_URL = os.environ.get("WEBAPP_URL")

# --- NEW: Add Ultramsg Config ---
ULTRAMSG_INSTANCE_ID = os.environ.get("ULTRAMSG_INSTANCE_ID")
ULTRAMSG_TOKEN = os.environ.get("ULTRAMSG_TOKEN")
ADMIN_WHATSAPP_NUMBER = os.environ.get("ADMIN_WHATSAPP_NUMBER")
# --------------------------------

SHEET_ID = "1RicQuJRGK5ZmlVZGGRZmU-mEtbYx_4kmzzsLPcgdyFE"
DRIVE_FOLDER_ID = "14bDZ23j2jhXLWs_XxFb3xnOr-8GPlQhj"

EXAM_OPTIONS = ["CBSE", "ICSE", "School Exam", "JEE", "NEET", "Other Competitive"]

# ========================== GOOGLE API Setup ==========================
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(GOOGLE_CREDS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

if creds.access_token_expired:
    client.login()

doubts_sheet = client.open_by_key(SHEET_ID).worksheet("Doubts")
users_sheet = client.open_by_key(SHEET_ID).worksheet("Users")
blacklist_sheet = client.open_by_key(SHEET_ID).worksheet("Blacklisted")

gauth = GoogleAuth()
gauth.credentials = creds
drive = GoogleDrive(gauth)

# ========================== TELEGRAM BOT ==========================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

(
    AUTH_DECISION,
    LOGIN_PHONE, LOGIN_PIN,
    SIGNUP_NAME, SIGNUP_PHONE, SIGNUP_CLASS, SIGNUP_EXAMS, SIGNUP_PIN,
    LOGGED_IN
) = range(9)

# ========================== HELPER FUNCTIONS ==========================

def get_blacklist(context: ContextTypes.DEFAULT_TYPE) -> set:
    current_time = datetime.datetime.now()
    if 'blacklist' not in context.bot_data or \
       (current_time - context.bot_data.get('blacklist_last_updated', datetime.datetime.min)).total_seconds() > 300:
        logging.info("Refreshing blacklist from Google Sheet...")
        blacklisted_numbers = blacklist_sheet.col_values(1)[1:]
        context.bot_data['blacklist'] = set(blacklisted_numbers)
        context.bot_data['blacklist_last_updated'] = current_time
    return context.bot_data['blacklist']

async def is_user_blacklisted(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    phone = context.user_data.get('phone')
    if not phone:
        return True
    if phone in get_blacklist(context):
        await update.message.reply_text("Oops! Your access to unlimited doubt-solving has ended. To keep getting those tricky questions answered in a snap, please top up your plan. Click on the link below to recharge:\n\n https://pages.razorpay.com/stores/st_QNHI3mHvLWmx9D")
        context.user_data.clear()
        return True
    return False

# ========================== NEW NOTIFICATION FUNCTION ==========================
def send_whatsapp_notification(name: str, phone: str, user_class: str):
    """Sends a WhatsApp notification to the admin using Ultramsg API."""
    if not all([ULTRAMSG_INSTANCE_ID, ULTRAMSG_TOKEN, ADMIN_WHATSAPP_NUMBER]):
        logging.warning("Ultramsg credentials not set. Skipping WhatsApp notification.")
        return

    url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE_ID}/messages/chat"
    
    # Format the message body
    message_body = (
        f"🎉 *New User Signup!*\n\n"
        f"👤 *Name:* {name}\n"
        f"📞 *Phone:* {phone}\n"
        f"📚 *Class:* {user_class}"
    )
    
    params = {
        "token": ULTRAMSG_TOKEN,
        "to": ADMIN_WHATSAPP_NUMBER,
        "body": message_body,
        "priority": 10
    }
    
    headers = {'Content-type': 'application/x-www-form-urlencoded'}
    
    try:
        response = requests.post(url, data=params, headers=headers)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        logging.info(f"Successfully sent WhatsApp notification for user {name}.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send WhatsApp notification: {e}")

# ========================== AUTHENTICATION FLOW ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get('phone'):
        if await is_user_blacklisted(update, context):
            pass
        else:
            await update.message.reply_text("Great to see you again! You're still logged in. Let's crush those doubts and keep your preparation on track.\n\nWhat's your question?")
            return LOGGED_IN

    keyboard = [[InlineKeyboardButton("✅ Login", callback_data='login')], [InlineKeyboardButton("✍️ Signup", callback_data='signup')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text("Welcome!\nNote : If bot freezes or doesn't respond please use /cancel and then restart the bot by /start\nHelpline 📞: 9625060017\n\nFor payment after free trial ends use this link (Browse Plans) : https://rzp.io/rzp/HgGGEvWO\nNote: After recharge bot may take upto 3 hours to update your account, please kindly have patience \n\nPlease log in or sign up to continue:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Welcome! \nNote : If bot freezes or doesn't respond please use /cancel and then restart the bot by /start\nHelpline 📞: 9625060017\n\nFor payment after free trial ends use this link (Browse Plans) : https://rzp.io/rzp/HgGGEvWO\nNote: After recharge bot may take upto 3 hours to update your account, please kindly have patience \n\nPlease log in or sign up to continue:", reply_markup=reply_markup)
    return AUTH_DECISION

async def auth_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'login':
        await query.edit_message_text("Please enter your registered phone number to log in:\n\nNote : If bot freezes or doesn't respond please use /cancel and then restart the bot by /start\nHelpline 📞: 9625060017")
        return LOGIN_PHONE
    elif query.data == 'signup':
        await query.edit_message_text("Great! Let's get you signed up. What is your full name?")
        return SIGNUP_NAME

async def signup_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['signup_name'] = update.message.text.strip()
    await update.message.reply_text("Got it. Now, please enter your phone number:")
    return SIGNUP_PHONE

async def signup_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    try:
        cell = users_sheet.find(phone, in_column=1)
        if cell:
            await update.message.reply_text("This phone number is already registered. Please log in instead using /start.")
            return ConversationHandler.END
    except gspread.exceptions.CellNotFound:
        pass
    context.user_data['signup_phone'] = phone
    await update.message.reply_text("Thanks. Which class are you in?")
    return SIGNUP_CLASS

async def signup_class(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['signup_class'] = update.message.text.strip()
    context.user_data['selected_exams'] = set()
    keyboard = [[InlineKeyboardButton(exam, callback_data=f"exam_{exam}")] for exam in EXAM_OPTIONS]
    keyboard.append([InlineKeyboardButton("➡️ Done", callback_data="exam_done")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Which exam(s) are you preparing for?\nSelect (multiple options) then press Done", reply_markup=reply_markup)
    return SIGNUP_EXAMS

async def signup_exams_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split('_', 1)[1]
    if action == "done":
        await query.edit_message_text("Perfect. Lastly, please create a 4-digit PIN for your account:")
        return SIGNUP_PIN
    selected_exams = context.user_data.get('selected_exams', set())
    if action in selected_exams:
        selected_exams.remove(action)
    else:
        selected_exams.add(action)
    context.user_data['selected_exams'] = selected_exams
    keyboard = []
    for exam in EXAM_OPTIONS:
        text = f"✅ {exam}" if exam in selected_exams else exam
        keyboard.append([InlineKeyboardButton(text, callback_data=f"exam_{exam}")])
    keyboard.append([InlineKeyboardButton("➡️ Done", callback_data="exam_done")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_reply_markup(reply_markup)
    return SIGNUP_EXAMS

# ========================== MODIFIED SIGNUP FUNCTION ==========================
async def signup_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pin = update.message.text.strip()
    if not (pin.isdigit() and len(pin) == 4):
        await update.message.reply_text("Invalid PIN. Please enter a 4-digit number.")
        return SIGNUP_PIN
        
    user_data = context.user_data
    timestamp = datetime.datetime.now().isoformat()
    exams_str = ", ".join(sorted(list(user_data['selected_exams'])))
    
    new_user_name = user_data['signup_name']
    new_user_phone = user_data['signup_phone']
    new_user_class = user_data['signup_class']

    new_row = [ new_user_phone, str(update.message.from_user.id), new_user_name, new_user_class, exams_str, pin, timestamp ]
    
    try:
        users_sheet.append_row(new_row)
        
        # --- NEW: Call the notification function here ---
        send_whatsapp_notification(
            name=new_user_name,
            phone=new_user_phone,
            user_class=new_user_class
        )
        # ----------------------------------------------

        context.user_data.clear()
        await update.message.reply_text("🎉 Signup successful! Please now log in to continue.")
        return await start(update, context)
        
    except gspread.exceptions.GSpreadException as e:
        logging.error(f"Failed to append new user to Google Sheet: {e}")
        await update.message.reply_text("Sorry, there was a problem saving your details. Please try signing up again.")
        return await start(update, context)

async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    if phone in get_blacklist(context):
        await update.message.reply_text("Oops! Your access to unlimited doubt-solving has ended. To keep getting those tricky questions answered in a snap, please top up your plan. Click on the link below to recharge:\n\n https://pages.razorpay.com/stores/st_QNHI3mHvLWmx9D")
        return ConversationHandler.END
    try:
        cell = users_sheet.find(phone, in_column=1)
        if not cell:
            raise gspread.exceptions.CellNotFound
        user_data = users_sheet.row_values(cell.row)
        context.user_data['login_data'] = user_data
        await update.message.reply_text("Phone number found. Please enter your 4-digit PIN:")
        return LOGIN_PIN
    except gspread.exceptions.CellNotFound:
        await update.message.reply_text("This number is not registered. Please use /start to sign up.\nHelpline 📞: 9625060017")
        return await start(update, context)
    except gspread.exceptions.GSpreadException as e:
        logging.error(f"A Google Sheets API error occurred during login for phone {phone}: {e}")
        await update.message.reply_text("Sorry, there was a problem connecting to our database. Please try again in a few moments.\nHelpline 📞: 9625060017")
        return ConversationHandler.END

async def login_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pin = update.message.text.strip()
    user_data_row = context.user_data['login_data']
    correct_pin = user_data_row[5]
    if pin == correct_pin:
        stored_telegram_id = user_data_row[1]
        current_telegram_id = str(update.message.from_user.id)
        if stored_telegram_id == current_telegram_id:
            phone_number = user_data_row[0]
            context.user_data.clear()
            context.user_data['phone'] = phone_number
            await update.message.reply_text("✅ Login successful! You can now send your doubts.")
            return LOGGED_IN
        else:
            await update.message.reply_text("❌ Access Denied. This phone number is registered to a different Telegram account.\nHelpline 📞: 9625060017")
            return ConversationHandler.END
    else:
        await update.message.reply_text("Incorrect PIN. Please try the PIN again, or use /cancel to start over.")
        return LOGIN_PIN

async def handle_doubt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_user_blacklisted(update, context):
        return
    phone = context.user_data.get('phone')
    if not phone:
        await update.message.reply_text("An error occurred. Please log in again with /start.\nHelpline 📞: 9625060017")
        return
    try:
        cell = users_sheet.find(phone, in_column=1)
        if not cell:
            raise gspread.exceptions.CellNotFound
        user_data = users_sheet.row_values(cell.row)
        name = user_data[2]
    except gspread.exceptions.CellNotFound:
        await update.message.reply_text("An error occurred with your account. Please try logging in again with /start.\nHelpline 📞: 9625060017")
        return
    user_id = update.message.from_user.id
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    whatsapp_link = f"https://wa.me/91{phone}"
    text_doubt = "-"
    drive_link = "-"
    if update.message.photo:
        text_doubt = update.message.caption or "-"
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            await file.download_to_drive(custom_path=temp_file.name)
            gfile = drive.CreateFile({'parents': [{'id': DRIVE_FOLDER_ID}], 'title': os.path.basename(temp_file.name)})
            gfile.SetContentFile(temp_file.name)
            gfile.Upload()
            drive_link = f"https://drive.google.com/uc?id={gfile['id']}"
        os.unlink(temp_file.name)
        await update.message.reply_text("✅ Your image doubt has been recorded!")
    elif update.message.text:
        text_doubt = update.message.text
        await update.message.reply_text("✅ Your text doubt has been recorded!")
    doubts_sheet.append_row([now, name, phone, str(user_id), text_doubt, drive_link, "Pending", whatsapp_link])

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("You have been successfully logged out. Use /start to log in again.")
    return await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Process cancelled. Use /start to begin again.\nHelpline 📞: 9625060017")
    return ConversationHandler.END

async def notify_users_on_restart(app: Application):
    logging.info("Checking for logged-in users to notify about restart...")
    for user_id, user_data in list(app.user_data.items()):
        if user_data.get('phone'):
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text="Server has been restarted. Please use /start to continue asking doubts."
                )
                logging.info(f"Sent restart notification to user {user_id}")
            except Exception as e:
                logging.warning(f"Could not send restart notification to user {user_id}: {e}")

if __name__ == "__main__":
    persistence = PicklePersistence(filepath="bot_session_data.pickle")
    app = ApplicationBuilder().token(TOKEN).persistence(persistence).post_init(notify_users_on_restart).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            AUTH_DECISION: [CallbackQueryHandler(auth_decision_callback)],
            LOGIN_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone)],
            LOGIN_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_pin)],
            SIGNUP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, signup_name)],
            SIGNUP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, signup_phone)],
            SIGNUP_CLASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, signup_class)],
            SIGNUP_EXAMS: [CallbackQueryHandler(signup_exams_callback)],
            SIGNUP_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, signup_pin)],
            LOGGED_IN: [
                CommandHandler('logout', logout),
                MessageHandler(filters.TEXT | filters.PHOTO, handle_doubt)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start)],
        per_message=False
    )
    app.add_handler(conv_handler)
    PORT = int(os.environ.get('PORT', 8080))
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{WEBAPP_URL}/{TOKEN}"
    )