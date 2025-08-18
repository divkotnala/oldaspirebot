import logging
import os
import datetime
import tempfile
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

# ========================== CONFIG ==========================
TOKEN = os.environ.get("TOKEN")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
WEBAPP_URL = os.environ.get("WEBAPP_URL")

SHEET_ID = "1RicQuJRGK5ZmlVZGGRZmU-mEtbYx_4kmzzsLPcgdyFE"
DRIVE_FOLDER_ID = "14bDZ23j2jhXLWs_XxFb3xnOr-8GPlQhj"

EXAM_OPTIONS = ["CBSE", "ICSE", "School Exam", "JEE", "NEET", "Other Competitive"]

# ========================== GOOGLE API Setup ==========================
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(GOOGLE_CREDS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# IMPROVED: Re-authenticate if credentials have expired to prevent stale sessions
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

# Define states for conversation
(
    AUTH_DECISION,
    LOGIN_PHONE, LOGIN_PIN,
    SIGNUP_NAME, SIGNUP_PHONE, SIGNUP_CLASS, SIGNUP_EXAMS, SIGNUP_PIN,
    LOGGED_IN
) = range(9)

# ========================== HELPER FUNCTIONS ==========================

def get_blacklist(context: ContextTypes.DEFAULT_TYPE) -> set:
    """
    Fetches the blacklist from Google Sheets and caches it for 5 minutes
    to avoid hitting API limits and improve performance.
    """
    current_time = datetime.datetime.now()
    if 'blacklist' not in context.bot_data or \
       (current_time - context.bot_data.get('blacklist_last_updated', datetime.datetime.min)).total_seconds() > 300:
        
        logging.info("Refreshing blacklist from Google Sheet...")
        blacklisted_numbers = blacklist_sheet.col_values(1)[1:] # Get all phone numbers, skipping header
        context.bot_data['blacklist'] = set(blacklisted_numbers)
        context.bot_data['blacklist_last_updated'] = current_time
    
    return context.bot_data['blacklist']

async def is_user_blacklisted(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if the logged-in user has been blacklisted."""
    phone = context.user_data.get('phone')
    if not phone:
        return True # Not logged in, treat as unauthorized

    blacklist = get_blacklist(context)
    if phone in blacklist:
        await update.message.reply_text("Sorry, your plan has expired. Please recharge to continue services.")
        return True
    return False

# ========================== AUTHENTICATION FLOW ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Greets user and offers Login / Signup options."""
    keyboard = [
        [InlineKeyboardButton("✅ Login", callback_data='login')],
        [InlineKeyboardButton("✍️ Signup", callback_data='signup')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome! Please log in or sign up to continue:", reply_markup=reply_markup)
    return AUTH_DECISION

async def auth_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's choice to login or signup."""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'login':
        await query.edit_message_text("Please enter your phone number to log in:")
        return LOGIN_PHONE
    elif query.data == 'signup':
        await query.edit_message_text("Great! Let's get you signed up. What is your full name?")
        return SIGNUP_NAME

# --- Signup Handlers ---
async def signup_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['signup_name'] = update.message.text.strip()
    await update.message.reply_text("Got it. Now, please enter your phone number:")
    return SIGNUP_PHONE

async def signup_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles phone number during signup, checking if it already exists."""
    phone = update.message.text.strip()
    
    # FIXED: Explicitly check the result of .find()
    try:
        cell = users_sheet.find(phone, in_column=1)
        if cell: # If a cell is found, the user exists
            await update.message.reply_text("This phone number is already registered. Please log in instead using /start.")
            return ConversationHandler.END
    except gspread.exceptions.CellNotFound:
        # This is the correct path for a new user, so we just continue
        pass
    
    # If we reach here, the number is new
    context.user_data['signup_phone'] = phone
    await update.message.reply_text("Thanks. Which class are you in?")
    return SIGNUP_CLASS


async def signup_class(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['signup_class'] = update.message.text.strip()
    context.user_data['selected_exams'] = set()
    
    keyboard = [
        [InlineKeyboardButton(exam, callback_data=f"exam_{exam}")] for exam in EXAM_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton("➡️ Done", callback_data="exam_done")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Which exam(s) are you preparing for? (Select multiple then press Done)", reply_markup=reply_markup)
    return SIGNUP_EXAMS

async def signup_exams_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    action = query.data.split('_', 1)[1]
    
    if action == "done":
        await query.edit_message_text("Perfect. Lastly, please create a 4-digit PIN for your account:")
        return SIGNUP_PIN

    # Toggle selection
    selected_exams = context.user_data.get('selected_exams', set())
    if action in selected_exams:
        selected_exams.remove(action)
    else:
        selected_exams.add(action)
    context.user_data['selected_exams'] = selected_exams
    
    # Update the keyboard to show checkmarks
    keyboard = []
    for exam in EXAM_OPTIONS:
        text = f"✅ {exam}" if exam in selected_exams else exam
        keyboard.append([InlineKeyboardButton(text, callback_data=f"exam_{exam}")])
    keyboard.append([InlineKeyboardButton("➡️ Done", callback_data="exam_done")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_reply_markup(reply_markup)
    
    return SIGNUP_EXAMS

async def signup_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pin = update.message.text.strip()
    if not (pin.isdigit() and len(pin) == 4):
        await update.message.reply_text("Invalid PIN. Please enter a 4-digit number.")
        return SIGNUP_PIN
        
    # All data collected, save to Google Sheet
    user_data = context.user_data
    timestamp = datetime.datetime.now().isoformat()
    exams_str = ", ".join(sorted(list(user_data['selected_exams'])))
    
    new_row = [
        user_data['signup_phone'],
        str(update.message.from_user.id),
        user_data['signup_name'],
        user_data['signup_class'],
        exams_str,
        pin,
        timestamp
    ]
    users_sheet.append_row(new_row)
    
    # Log the user in
    context.user_data.clear()
    context.user_data['phone'] = user_data['signup_phone']
    
    await update.message.reply_text("🎉 Signup complete! You are now logged in. You can send your doubts as text or images.")
    return LOGGED_IN

# --- Login Handlers ---
async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles phone number during login."""
    phone = update.message.text.strip()
    
    # Check if blacklisted first
    if phone in get_blacklist(context):
        await update.message.reply_text("Sorry, your plan has expired. Please recharge to continue services.")
        return ConversationHandler.END
        
    # FIXED: Explicitly check the result of .find()
    try:
        cell = users_sheet.find(phone, in_column=1)
        if not cell:
            # This handles the case where .find() returns None
            raise gspread.exceptions.CellNotFound

        user_data = users_sheet.row_values(cell.row)
        context.user_data['login_data'] = user_data
        await update.message.reply_text("Phone number found. Please enter your 4-digit PIN:")
        return LOGIN_PIN

    except gspread.exceptions.CellNotFound:
        await update.message.reply_text("This phone number is not registered. Please sign up first using /start.")
        return ConversationHandler.END


async def login_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pin = update.message.text.strip()
    correct_pin = context.user_data['login_data'][5] # PIN is in the 6th column (index 5)
    
    if pin == correct_pin:
        phone_number = context.user_data['login_data'][0]
        context.user_data.clear()
        context.user_data['phone'] = phone_number
        await update.message.reply_text("✅ Login successful! You can now send your doubts.")
        return LOGGED_IN
    else:
        await update.message.reply_text("Incorrect PIN. Please try again or use /start to restart the process.")
        return ConversationHandler.END

# ========================== MAIN BOT FUNCTIONALITY ==========================
async def handle_doubt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text or photo doubts after user is logged in."""
    if await is_user_blacklisted(update, context):
        return # Stop processing if user is blacklisted

    phone = context.user_data.get('phone')
    if not phone:
        await update.message.reply_text("An error occurred. Please log in again with /start.")
        return

    try:
        cell = users_sheet.find(phone, in_column=1)
        if not cell:
            raise gspread.exceptions.CellNotFound
        user_data = users_sheet.row_values(cell.row)
        name = user_data[2] # Name is in the 3rd column (index 2)
    except gspread.exceptions.CellNotFound:
        await update.message.reply_text("An error occurred with your account. Please try logging in again with /start.")
        return

    user_id = update.message.from_user.id
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text_doubt = "-"
    drive_link = "-"
    
    if update.message.text:
        text_doubt = update.message.text
        await update.message.reply_text("✅ Your text doubt has been recorded!")
    elif update.message.photo:
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

    doubts_sheet.append_row([now, name, phone, str(user_id), text_doubt, drive_link, "Pending"])

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text("Process cancelled. Use /start to begin again.")
    context.user_data.clear()
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

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
            LOGGED_IN: [MessageHandler(filters.TEXT | filters.PHOTO, handle_doubt)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
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