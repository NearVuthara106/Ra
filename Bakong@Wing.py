# ----------------------------------------------------------------------
# KHQR Telegram Bot for Python (Enhanced with Inline 'Confirm Payment' Button)
# Implemented Auto-Confirmation (Polling) and Manual Check via Button.
# ----------------------------------------------------------------------

# Required Libraries:
# 1. pyTelegramBotAPI (install via pip: pip install pyTelegramBotAPI)
# 2. bakong-khqr (install via pip: pip install bakong-khqr[image])
#    (The [image] dependency installs Pillow and qrcode for image generation)

import telebot
import os
import io
import time
import threading
# Import necessary types for inline keyboard
from telebot import types 
from bakong_khqr import KHQR 

# --- 1. CONFIGURATION ---
# IMPORTANT: REPLACE THESE PLACEHOLDERS WITH YOUR REAL CREDENTIALS
# The Telegram Bot Token, obtained from BotFather.
BOT_TOKEN = "YOUR_BOT_TOKEN"

# Bakong/KHQR Credentials (MUST be obtained from NBC/member FI registration)
BAKONG_TOKEN = "ey..." # JWT token for API calls
BANK_ACCOUNT = "USERNAME@YOUR-BANK"             # Your Bakong settlement account ID
MERCHANT_NAME = "YOUR NAME"
MERCHANT_CITY = "Phnom Penh"
CURRENCY = "KHR" # Or 'USD'

# --- GLOBAL STATE & CONSTANTS ---
# Time constant for expiration (5 minutes)
EXPIRATION_SECONDS = 5 * 60 
# Interval for checking payment status (30 seconds)
CHECK_INTERVAL_SECONDS = 30 
# Callback data prefix for the confirm button
CONFIRM_CALLBACK_PREFIX = "confirm_"

# Dictionary to store active dynamic transactions for status checking and cleanup
# Format: { bill_number: { 'md5_hash': str, 'expiry_time': float, 'chat_id': int, 'message_id': int } }
active_transactions = {}

# Lock for safely modifying the active_transactions dictionary across threads
transaction_lock = threading.Lock()

# Initialize the Bot and the KHQR client
bot = telebot.TeleBot(BOT_TOKEN)
try:
    # Initialize the Bakong KHQR client with the developer token
    khqr_client = KHQR(BAKONG_TOKEN)
except Exception as e:
    print(f"Error initializing KHQR client: {e}. Check your BAKONG_TOKEN.")
    khqr_client = None

# --- UTILITY FUNCTION FOR PAYMENT CHECK ---

def check_payment_status(bill_number, md5_hash, chat_id, message_id):
    """
    Checks the payment status for a specific transaction and handles success/failure.
    Returns True if payment was confirmed and transaction was removed, False otherwise.
    """
    try:
        payment_status = khqr_client.check_payment(md5_hash)
        
        if payment_status == "PAID":
            # Payment confirmed!
            
            # 1. DELETE the QR code image message
            if message_id:
                try:
                    bot.delete_message(chat_id, message_id)
                    print(f"Deleted QR message {message_id} for successful payment {bill_number}.")
                except Exception as delete_e:
                    print(f"Failed to delete QR message {message_id}: {delete_e}")

            # 2. Send the success confirmation message
            bot.send_message(chat_id, 
                f"🎉 **បានទូទាត់រួចរាល់ហើយ! (Payment Completed)**\n"
                f"លេខបង្កាន់ដៃ: `{bill_number}`\n"
                f"ស្ថានភាព: **{payment_status}**\n"
                f"សូមអរrគុណសម្រាប់ការទូទាត់!", 
                parse_mode="Markdown"
            )
            
            # 3. Remove from tracking dictionary
            with transaction_lock:
                if bill_number in active_transactions:
                    del active_transactions[bill_number]
                    print(f"Transaction {bill_number} removed from tracking after success.")

            return True # Payment confirmed and cleaned up
        else:
            # Payment still UNPAID or other status
            return False

    except Exception as e:
        print(f"Error checking payment for {bill_number}: {e}")
        # Notify the user that the manual check failed
        try:
            bot.send_message(chat_id, "⚠️ **កំហុសត្រួតពិនិត្យ (Check Error):** មានបញ្ហាក្នុងការពិនិត្យស្ថានភាពទូទាត់។")
        except:
             pass # Ignore if this message also fails to send
        return False

# --- 2. THREADED AUTO-CONFIRMATION FUNCTION ---

def check_and_cleanup_transactions():
    """
    Runs in a background thread to automatically check payment status and clean up expired transactions.
    """
    while True:
        current_time = time.time()
        transactions_to_remove = []
        
        # 1. Process active transactions
        with transaction_lock:
            # Create a list of items to iterate over
            items_to_check = list(active_transactions.items())

        for bill_number, data in items_to_check:
            md5_hash = data['md5_hash']
            chat_id = data['chat_id']
            expiry_time = data['expiry_time']
            message_id = data.get('message_id')
            
            # A. Check for expiration first
            if expiry_time < current_time:
                # Transaction has expired
                
                # Try to delete the QR message if it exists
                if message_id:
                    try:
                        bot.delete_message(chat_id, message_id)
                    except Exception as delete_e:
                        print(f"Failed to delete expired QR message {message_id}: {delete_e}")

                bot.send_message(chat_id, 
                    f"❌ **ការទូទាត់ផុតកំណត់ (Expired)**\nលេខបង្កាន់ដៃ `{bill_number}` បានផុតកំណត់ក្នុងរយៈពេល 5 នាទីហើយ。\nសូមបង្កើត QR ថ្មីដើម្បីបង់ប្រាក់។", 
                    parse_mode="Markdown"
                )
                transactions_to_remove.append(bill_number)
                continue

            # B. Check payment status for unexpired transactions
            # This uses the utility function which handles success message and cleanup
            payment_confirmed = check_payment_status(bill_number, md5_hash, chat_id, message_id)
            if payment_confirmed:
                # Add to removal list if the utility function confirmed payment and cleaned up
                transactions_to_remove.append(bill_number)
                
        # 2. Remove transactions marked for removal
        with transaction_lock:
            for key in transactions_to_remove:
                if key in active_transactions:
                    # Double-check removal, though handled by utility function
                    del active_transactions[key]
                    print(f"Transaction {key} removed from tracking.")
        
        # Sleep until the next check
        time.sleep(CHECK_INTERVAL_SECONDS)

# --- 3. BOT COMMAND HANDLERS ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Handles /start and /help commands."""
    help_text = (
        "  👋 **សូមស្វាគមន៍មកកាន់ប្រព័ន្ធទូទាត់ (Payment Bot) របស់ Ra--For Payment**\n\n"
        "**បង្កើត QR សូមចុច:**\n"
        "📲 `/pay <ទឹកប្រាក់> <គោលបំណង> (ស្រេចចិត្ត)`\n\n"
        "❕ _ឧទាហរណ៍:_ `/pay 5000 នំ`\n\n"
        "(QR នេះនឹងផុតកំណត់ក្នុងរយៈពេល **5 នាទី** ហើយនឹងត្រូវបានត្រួតពិនិត្យដោយស្វ័យប្រវត្តិ។)"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['pay'])
def generate_khqr_payment(message):
    """Handles the /pay command to generate a dynamic KHQR code with a button."""
    if khqr_client is None:
        bot.reply_to(message, "Error: Bakong service is not initialized. សូមពិនិត្យមើល `BAKONG_TOKEN` របស់អ្នក។")
        return

    try:
        # 1. Parse the command arguments
        parts = message.text.split(maxsplit=2)
        if len(parts) < 2:
            bot.reply_to(message, " ❗**កំហុស:** សូមបញ្ចូលទឹកប្រាក់។ _ឧទាហរណ៍:_ `/pay 5000` (កុំប្រើប្រាស់សញ្ញា $ និង ៛ ឲ្យសោះ)")
            return

        amount = float(parts[1])
        description = parts[2] if len(parts) == 3 else f"Payment Ref {time.time():.0f}" 
        
        # 2. Generate a unique reference and calculate expiration time
        bill_number = f"TRX{int(time.time() * 1000)}" 
        expiry_time = time.time() + EXPIRATION_SECONDS
        
        expiry_datetime = time.strftime('%I:%M:%S %p', time.localtime(expiry_time))

        bot.reply_to(message, f"កំពុងបង្កើត KHQR ទឹកប្រាក់ចំនួន {amount} {CURRENCY} (លេខបង្កាន់ដៃ `{bill_number}`)...")

        # 3. Call the Bakong KHQR generation method
        qr_string = khqr_client.create_qr(
            bank_account=BANK_ACCOUNT,
            merchant_name=MERCHANT_NAME,
            merchant_city=MERCHANT_CITY,
            amount=amount,
            currency=CURRENCY,
            bill_number=bill_number,
            store_label=description[:25], 
            phone_number='85512345678', 
            terminal_label='Bot Terminal',
            static=False 
        )
        
        # 4. Generate MD5 hash 
        md5_hash = khqr_client.generate_md5(qr_string)

        # 5. Convert the QR string into an image (in memory)
        try:
            qr_image_bytes = khqr_client.qr_image(
                qr_string, 
                format='bytes'
            )
        except Exception as img_e:
            error_message = (
                f"❌ **កំហុសបង្កើតរូបភាព (Image Error):** មិនអាចបង្កើតរូបភាព QR បានទេ។\n"
                f"សូមដំឡើងកញ្ចប់ដែលត្រូវការ៖ `pip install \"bakong-khqr[image]\"`"
            )
            bot.reply_to(message, error_message)
            print(f"Image generation failed: {img_e}")
            return

        photo_file = io.BytesIO(qr_image_bytes)
        photo_file.name = 'khqr_payment.png'
        
        # 6. Create the Inline Keyboard with the 'Confirm Payment' button
        keyboard = types.InlineKeyboardMarkup()
        # The callback_data includes the transaction bill_number
        callback_data = f"{CONFIRM_CALLBACK_PREFIX}{bill_number}"
        confirm_button = types.InlineKeyboardButton("✅ ពិនិត្យការទូទាត់ (Confirm Payment)", callback_data=callback_data)
        keyboard.add(confirm_button)

        # 7. Send the QR code image and instructions
        caption = (
            f"💰 **អាចទូទាត់ជាមួយ KHQR ខាងលើបាន**\n"
            f"ទឹកប្រាក់ចំនួន **{amount:.2f} {CURRENCY}**\n"
            f"គោលបំណង: {description}\n"
            f"លេខបង្កាន់ដៃ: `{bill_number}`\n"
            f"⏰ **ផុតកំណត់នៅម៉ោង {expiry_datetime}**\n\n"
            f"✅ **ការទូទាត់នឹងត្រូវបានបញ្ជាក់ដោយស្វ័យប្រវត្តិ ឬចុចប៊ូតុងខាងក្រោម។**"
        )
        # Capture the message object returned by send_photo
        sent_message = bot.send_photo(
            message.chat.id, 
            photo_file, 
            caption=caption, 
            parse_mode="Markdown",
            reply_markup=keyboard # Attach the inline keyboard
        )

        # 8. Store transaction data, including the message ID
        with transaction_lock:
            active_transactions[bill_number] = {
                'md5_hash': md5_hash, 
                'expiry_time': expiry_time,
                'chat_id': message.chat.id,
                'message_id': sent_message.message_id
            }

    except ValueError:
        bot.reply_to(message, "❌ **កំហុស:** ទម្រង់ទឹកប្រាក់មិនត្រឹមត្រូវ។ សូមបញ្ចូលលេខតែប៉ុណ្ណោះ។")
    except Exception as e:
        print(f"An error occurred in /pay: {e}")
        bot.reply_to(message, f"❌ **កំហុស:** មានបញ្ហាណាមួយកើតឡើងពេលបង្កើត QR: {e}")

# --- 4. CALLBACK QUERY HANDLER FOR THE PAYMENT BUTTON ---

@bot.callback_query_handler(func=lambda call: call.data.startswith(CONFIRM_CALLBACK_PREFIX))
def handle_confirm_payment(call):
    """Handles the 'Confirm Payment' button click."""
    
    # 1. Answer the callback query to stop the 'loading' animation on the button
    bot.answer_callback_query(call.id, text="កំពុងពិនិត្យស្ថានភាព...")

    # 2. Extract the bill number
    bill_number = call.data[len(CONFIRM_CALLBACK_PREFIX):]
    
    # 3. Check if the transaction is still active
    with transaction_lock:
        if bill_number not in active_transactions:
            # Edit the message to reflect that the payment is no longer valid or was completed
            try:
                bot.edit_message_caption(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    caption=call.message.caption + "\n\n**⚠️ ការទូទាត់នេះលែងត្រួតពិនិត្យបានហើយ (Expired/Completed).**",
                    parse_mode="Markdown",
                    reply_markup=None # Remove the keyboard
                )
            except Exception as e:
                # This often fails if the message was already deleted by the cleanup thread
                print(f"Failed to edit expired/completed message: {e}")
            
            bot.send_message(call.message.chat.id, 
                f"❌ **លេខបង្កាន់ដៃ `{bill_number}` មិនត្រូវបានតាមដានទៀតទេ។** (ប្រហែលជាផុតកំណត់ ឬបានទូទាត់រួចហើយ)",
                parse_mode="Markdown"
            )
            return

        # Get transaction data
        data = active_transactions.get(bill_number)
        md5_hash = data['md5_hash']
        chat_id = data['chat_id']
        message_id = data['message_id']
        
    # 4. Perform the manual payment check
    payment_confirmed = check_payment_status(bill_number, md5_hash, chat_id, message_id)

    if not payment_confirmed:
        # If not confirmed, provide feedback to the user and update the button to prevent spam
        try:
             # Edit the caption to show status
            new_caption = call.message.caption.split('✅ **ការទូទាត់')[0] # Remove the existing status line
            new_caption += f"🔴 **ស្ថានភាពបច្ចុប្បន្ន: មិនទាន់បង់ប្រាក់ ❌ (UNPAID)**\n"
            new_caption += "❌ **ការទូទាត់នឹងត្រូវបានបញ្ជាក់ដោយស្វ័យប្រវត្តិ ឬចុចប៊ូតុងខាងក្រោម។**"
            
            # Re-attach the same keyboard
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=new_caption,
                parse_mode="Markdown",
                reply_markup=call.message.reply_markup
            )
        except Exception as e:
            print(f"Failed to edit caption after manual check: {e}")
            
        bot.send_message(chat_id, f"🔴 **លេខបង្កាន់ដៃ `{bill_number}`:** មិនទាន់បានទូទាត់ទេ។ សូមព្យាយាមម្តងទៀតក្នុងរយៈពេលខ្លី។")


# --- 5. START BOT POLLING & AUTO-CONFIRMATION THREAD ---

if __name__ == '__main__':
    # Start the background thread for auto-confirmation
    cleanup_thread = threading.Thread(target=check_and_cleanup_transactions, daemon=True)
    cleanup_thread.start()
    print("Background auto-confirmation thread started.")

    print("Bot is starting polling...")
    try:
        # Start the main bot polling loop
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Error during bot polling: {e}")
  
