import os
import sqlite3
import threading
import datetime
import telebot
from telebot import types
from flask import Flask
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app for Replit hosting
app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET')

# Bot token and owner ID from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))  # Set this in Replit Secrets

if not BOT_TOKEN:
    logger.error("BOT_TOKEN not found in environment variables!")
    exit(1)

if OWNER_ID == 0:
    logger.error("OWNER_ID not set! Please add your Telegram user ID to environment variables.")
    exit(1)

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Dictionary to store temporary upload data for guided content creation
upload_sessions = {}

# Database setup
def init_database():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            join_date TEXT,
            total_stars_spent INTEGER DEFAULT 0,
            interaction_count INTEGER DEFAULT 0,
            last_interaction TEXT
        )
    ''')
    
    # Loyal fans table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS loyal_fans (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            date_marked TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # AI-style responses table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS responses (
            key TEXT PRIMARY KEY,
            text TEXT
        )
    ''')
    
    # Content items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS content_items (
            name TEXT PRIMARY KEY,
            price_stars INTEGER,
            file_path TEXT,
            description TEXT,
            created_date TEXT
        )
    ''')
    
    # Scheduled posts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datetime TEXT,
            content TEXT,
            created_date TEXT
        )
    ''')
    
    # User backup table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_backups (
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            join_date TEXT,
            total_stars_spent INTEGER,
            interaction_count INTEGER,
            last_interaction TEXT,
            backup_date TEXT
        )
    ''')
    
    # VIP subscriptions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vip_subscriptions (
            user_id INTEGER PRIMARY KEY,
            start_date TEXT,
            expiry_date TEXT,
            is_active INTEGER DEFAULT 1,
            total_payments INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # VIP settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vip_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Insert default VIP settings
    vip_settings = [
        ('vip_price_stars', '399'),
        ('vip_duration_days', '30'),
        ('vip_description', 'Premium VIP access with exclusive content and direct chat')
    ]
    
    for key, value in vip_settings:
        cursor.execute('INSERT OR IGNORE INTO vip_settings (key, value) VALUES (?, ?)', (key, value))
    
    # Insert default AI responses
    default_responses = [
        ('greeting', 'Hey there! 😊 Thanks for reaching out! I love connecting with my fans. What\'s on your mind?'),
        ('question', 'That\'s a great question! I appreciate you asking. Feel free to check out my content or ask me anything else! 💕'),
        ('compliment', 'Aww, you\'re so sweet! Thank you! That really makes my day. You\'re amazing! ✨'),
        ('default', 'Thanks for the message! I love hearing from you. Don\'t forget to check out my exclusive content! 😘')
    ]
    
    for key, text in default_responses:
        cursor.execute('INSERT OR IGNORE INTO responses (key, text) VALUES (?, ?)', (key, text))
    
    # Insert sample content
    sample_content = [
        ('photo_set_1', 25, 'https://example.com/photo1.jpg', 'Exclusive photo set - Behind the scenes', datetime.datetime.now().isoformat()),
        ('video_preview', 50, 'https://example.com/video1.mp4', 'Special video content just for you', datetime.datetime.now().isoformat())
    ]
    
    for name, price, path, desc, date in sample_content:
        cursor.execute('INSERT OR IGNORE INTO content_items (name, price_stars, file_path, description, created_date) VALUES (?, ?, ?, ?, ?)', 
                      (name, price, path, desc, date))
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

def get_user_data(user_id):
    """Get user data from database"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def add_or_update_user(user):
    """Add new user or update existing user data"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    now = datetime.datetime.now().isoformat()
    
    # Check if user exists
    existing_user = get_user_data(user.id)
    
    if existing_user:
        # Update interaction count and last interaction
        cursor.execute('''
            UPDATE users 
            SET interaction_count = interaction_count + 1, 
                last_interaction = ?,
                username = ?,
                first_name = ?
            WHERE user_id = ?
        ''', (now, user.username, user.first_name, user.id))
    else:
        # Add new user
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, join_date, last_interaction, interaction_count)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (user.id, user.username, user.first_name, now, now))
        
        # Send welcome notification to owner
        try:
            bot.send_message(OWNER_ID, f"🎉 New fan joined!\n👤 {user.first_name} (@{user.username})\n🆔 ID: {user.id}")
        except:
            pass
    
    conn.commit()
    conn.close()

def get_ai_response(message_text):
    """Get AI-style response based on message content"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    message_lower = message_text.lower()
    
    # Determine response type based on keywords
    if any(word in message_lower for word in ['hi', 'hello', 'hey', 'good morning', 'good evening']):
        response_key = 'greeting'
    elif any(word in message_lower for word in ['beautiful', 'gorgeous', 'amazing', 'love', 'perfect']):
        response_key = 'compliment'
    elif '?' in message_text:
        response_key = 'question'
    else:
        response_key = 'default'
    
    cursor.execute('SELECT text FROM responses WHERE key = ?', (response_key,))
    result = cursor.fetchone()
    
    if result:
        response = result[0]
    else:
        response = "Thanks for the message! 😊"
    
    conn.close()
    return response

# VIP Management Functions

def check_vip_status(user_id):
    """Check if user has active VIP subscription"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT start_date, expiry_date, is_active 
        FROM vip_subscriptions 
        WHERE user_id = ? AND is_active = 1
    ''', (user_id,))
    
    subscription = cursor.fetchone()
    conn.close()
    
    if not subscription:
        return {'is_vip': False, 'days_left': 0, 'expired': False}
    
    start_date, expiry_date, is_active = subscription
    
    # Parse expiry date
    try:
        expiry_datetime = datetime.datetime.fromisoformat(expiry_date)
        now = datetime.datetime.now()
        
        if expiry_datetime > now:
            days_left = (expiry_datetime - now).days
            return {'is_vip': True, 'days_left': days_left, 'expired': False}
        else:
            # Subscription expired, deactivate it
            deactivate_expired_vip(user_id)
            return {'is_vip': False, 'days_left': 0, 'expired': True}
    except:
        return {'is_vip': False, 'days_left': 0, 'expired': False}

def deactivate_expired_vip(user_id):
    """Deactivate expired VIP subscription"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE vip_subscriptions SET is_active = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_vip_settings(key):
    """Get VIP setting value"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM vip_settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def update_vip_settings(key, value):
    """Update VIP setting"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO vip_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def activate_vip_subscription(user_id):
    """Activate or renew VIP subscription for user"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    # Get VIP duration from settings
    duration_days = int(get_vip_settings('vip_duration_days') or 30)
    
    now = datetime.datetime.now()
    
    # Check if user already has an active subscription
    cursor.execute('SELECT expiry_date FROM vip_subscriptions WHERE user_id = ? AND is_active = 1', (user_id,))
    existing = cursor.fetchone()
    
    if existing:
        # Extend existing subscription
        try:
            current_expiry = datetime.datetime.fromisoformat(existing[0])
            # If still active, extend from expiry date, otherwise from now
            extend_from = max(current_expiry, now)
        except:
            extend_from = now
        
        new_expiry = extend_from + datetime.timedelta(days=duration_days)
        
        cursor.execute('''
            UPDATE vip_subscriptions 
            SET expiry_date = ?, is_active = 1, total_payments = total_payments + 1
            WHERE user_id = ?
        ''', (new_expiry.isoformat(), user_id))
    else:
        # Create new subscription
        expiry_date = now + datetime.timedelta(days=duration_days)
        
        cursor.execute('''
            INSERT OR REPLACE INTO vip_subscriptions 
            (user_id, start_date, expiry_date, is_active, total_payments)
            VALUES (?, ?, ?, 1, 1)
        ''', (user_id, now.isoformat(), expiry_date.isoformat()))
    
    conn.commit()
    conn.close()
    
    return duration_days

def deliver_vip_content(chat_id, user_id, content_name):
    """Deliver content for free to VIP users"""
    # Verify VIP status
    vip_status = check_vip_status(user_id)
    if not vip_status['is_vip']:
        bot.send_message(chat_id, "❌ VIP membership required! Please upgrade to VIP to access this content for free.")
        return
    
    # Get content details
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT file_path, description FROM content_items WHERE name = ?', (content_name,))
    content = cursor.fetchone()
    conn.close()
    
    if not content:
        bot.send_message(chat_id, f"❌ Content '{content_name}' not found.")
        return
    
    file_path, description = content
    
    # Send VIP access message
    vip_message = f"""
💎 <b>VIP EXCLUSIVE ACCESS</b> 💎

🎉 Here's your free content as a VIP member!

<b>{content_name}</b>
{description}

💕 Thank you for being an amazing VIP supporter!
⏰ Your VIP expires in {vip_status['days_left']} days
"""
    
    bot.send_message(chat_id, vip_message, parse_mode='HTML')
    
    # Send the actual content (same logic as paid content delivery)
    try:
        if file_path.startswith('http'):
            # It's a URL
            if any(ext in file_path.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                bot.send_photo(chat_id, file_path, caption=f"💎 VIP: {content_name}")
            elif any(ext in file_path.lower() for ext in ['.mp4', '.mov', '.avi']):
                bot.send_video(chat_id, file_path, caption=f"💎 VIP: {content_name}")
            else:
                bot.send_document(chat_id, file_path, caption=f"💎 VIP: {content_name}")
        elif len(file_path) > 50 and not file_path.startswith('/'):
            # It's a Telegram file_id
            try:
                bot.send_photo(chat_id, file_path, caption=f"💎 VIP: {content_name}")
            except:
                try:
                    bot.send_video(chat_id, file_path, caption=f"💎 VIP: {content_name}")
                except:
                    try:
                        bot.send_document(chat_id, file_path, caption=f"💎 VIP: {content_name}")
                    except:
                        bot.send_message(chat_id, f"💎 Your VIP content: {content_name}\n\nFile ID: {file_path}\n\n⚠️ If you have trouble accessing this content, please contact me!")
        else:
            # It's a local file path
            with open(file_path, 'rb') as file:
                if any(ext in file_path.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    bot.send_photo(chat_id, file, caption=f"💎 VIP: {content_name}")
                elif any(ext in file_path.lower() for ext in ['.mp4', '.mov', '.avi']):
                    bot.send_video(chat_id, file, caption=f"💎 VIP: {content_name}")
                else:
                    bot.send_document(chat_id, file, caption=f"💎 VIP: {content_name}")
    except Exception as e:
        bot.send_message(chat_id, f"💎 Your VIP content: {content_name}\n\n⚠️ There was an issue delivering your content. Please contact me and I'll send it manually!")
        logger.error(f"Error sending VIP content {content_name}: {e}")
    
    # Notify owner of VIP content access
    try:
        user_data = get_user_data(user_id)
        if user_data:
            username = user_data[1] or "none"
            first_name = user_data[2] or "N/A"
            
            bot.send_message(OWNER_ID, f"""
💎 <b>VIP CONTENT ACCESS</b>

👤 VIP Member: {first_name} (@{username})
🎁 Content: {content_name}
🆔 User ID: {user_id}
⏰ VIP expires in {vip_status['days_left']} days
""", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error notifying owner of VIP access: {e}")

# Bot command handlers

@bot.message_handler(commands=['start'])
def start_command(message):
    """Handle /start command"""
    add_or_update_user(message.from_user)
    
    # Check VIP status
    vip_status = check_vip_status(message.from_user.id)
    vip_text = ""
    if vip_status['is_vip']:
        days_left = vip_status['days_left']
        vip_text = f"\n💎 VIP MEMBER (expires in {days_left} days)\n"
    
    welcome_text = f"""
🌟 Welcome to my exclusive content hub, {message.from_user.first_name}! 🌟
{vip_text}
I'm so excited to have you here! This is where I share my most intimate and exclusive content with my amazing fans like you.

✨ What you can do here:
• Get FREE teasers and previews
• Purchase exclusive content with Telegram Stars
• Chat with me personally
• Access special fan-only material

💫 Quick actions:
"""
    
    # Create inline keyboard with only 3 buttons in specified order
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🌟 VIP Access", callback_data="vip_access"))
    markup.add(types.InlineKeyboardButton("🎬 View Teasers", callback_data="teasers"))
    markup.add(types.InlineKeyboardButton("ℹ️ Help", callback_data="help"))
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

@bot.message_handler(commands=['teaser'])
def teaser_command(message):
    """Handle /teaser command with VIP-exclusive content"""
    add_or_update_user(message.from_user)
    
    # Check VIP status
    vip_status = check_vip_status(message.from_user.id)
    is_vip = vip_status['is_vip']
    
    if is_vip:
        teaser_text = f"""
💎 **VIP EXCLUSIVE TEASERS** 💎

🎉 Special VIP preview just for you!

*[VIP members get access to premium teasers, behind-the-scenes content, and exclusive previews not available to regular users]*

🌟 **VIP Perks Active:**
• Unlimited free access to all content
• Exclusive VIP-only material
• Direct personal communication priority
• Monthly bonus content drops

⏰ Your VIP expires in {vip_status['days_left']} days

💕 You're absolutely amazing for being VIP! Here's what's new this week...

✨ *"The best content is exclusively yours!"* ✨
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎁 Access All VIP Content FREE", callback_data="browse_content"))
        markup.add(types.InlineKeyboardButton("🔄 Extend VIP Membership", callback_data="vip_access"))
        
    else:
        teaser_text = """
🎬 **FREE TEASER CONTENT** 🎬

Here's a little preview of what's waiting for you in my exclusive collection... 

*[This would include actual teaser content - photos, short videos, or enticing descriptions]*

💝 This is just a taste of what I have for my special fans. Want to see more? Check out my full content library!

💡 **VIP members get:**
• FREE access to ALL content
• Exclusive VIP-only teasers (like this one, but better!)
• Direct personal chat priority
• Monthly bonus content

✨ *"The best is yet to come..."* ✨
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP for FREE Access", callback_data="vip_access"))
        markup.add(types.InlineKeyboardButton("🛒 Browse Content to Purchase", callback_data="browse_content"))
    
    bot.send_message(message.chat.id, teaser_text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['buy'])
def buy_command(message):
    """Handle /buy command"""
    add_or_update_user(message.from_user)
    
    # Parse command for specific item
    command_parts = message.text.split(' ', 1)
    if len(command_parts) > 1:
        item_name = command_parts[1].strip()
        # Try to find and purchase specific item
        purchase_item(message.chat.id, message.from_user.id, item_name)
    else:
        # Show available content for purchase
        show_content_catalog(message.chat.id)

def purchase_item(chat_id, user_id, item_name):
    """Process purchase for specific item"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM content_items WHERE name = ?', (item_name,))
    item = cursor.fetchone()
    conn.close()
    
    if item:
        name, price_stars, file_path, description, created_date = item
        
        # Create invoice for Telegram Stars
        prices = [types.LabeledPrice(label=name, amount=price_stars)]
        
        bot.send_invoice(
            chat_id=chat_id,
            title=f"Premium Content: {name}",
            description=description,
            invoice_payload=f"content_{name}_{user_id}",
            provider_token=None,  # None for Telegram Stars
            currency='XTR',  # Telegram Stars currency
            prices=prices,
            start_parameter='purchase'
        )
    else:
        bot.send_message(chat_id, f"Sorry, I couldn't find content named '{item_name}'. Use /help to see available content.")

def show_vip_access(chat_id, user_id):
    """Show VIP access options and current status"""
    vip_status = check_vip_status(user_id)
    vip_price = int(get_vip_settings('vip_price_stars') or 399)
    vip_description = get_vip_settings('vip_description') or 'Premium VIP access with exclusive content and direct chat'
    
    if vip_status['is_vip']:
        # User is already VIP
        status_text = f"""
💎 <b>VIP MEMBER STATUS</b> 💎

🎉 You are currently a VIP member!
⏰ <b>Expires in:</b> {vip_status['days_left']} days

🌟 <b>Your VIP Benefits:</b>
• Unlimited exclusive content access
• Direct personal chat with me
• Priority responses to messages
• Special VIP-only teasers and previews
• Monthly exclusive photo sets
• Behind-the-scenes content

💫 Want to extend your VIP membership?
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"🔄 Extend VIP ({vip_price} Stars)", callback_data="buy_vip"))
        markup.add(types.InlineKeyboardButton("🛒 Browse Content", callback_data="browse_content"))
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
        
    else:
        # User is not VIP
        status_text = f"""
🌟 <b>BECOME A VIP MEMBER</b> 🌟

💰 <b>Price:</b> {vip_price} Telegram Stars/month
📅 <b>Duration:</b> 30 days

💎 <b>VIP Benefits Include:</b>
• Unlimited access to all exclusive content
• Direct personal chat with me
• Priority responses to all your messages
• Special VIP-only teasers and previews
• Monthly exclusive photo sets
• Behind-the-scenes content and stories
• Early access to new content

✨ <b>"{vip_description}"</b>

🚀 Ready to become VIP and get unlimited access?
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"💎 Subscribe VIP ({vip_price} Stars)", callback_data="buy_vip"))
        markup.add(types.InlineKeyboardButton("🎬 View Free Teasers", callback_data="teasers"))
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
    
    bot.send_message(chat_id, status_text, reply_markup=markup, parse_mode='HTML')

def purchase_vip_subscription(chat_id, user_id):
    """Process VIP subscription purchase"""
    vip_price = int(get_vip_settings('vip_price_stars') or 399)
    vip_description = get_vip_settings('vip_description') or 'Premium VIP access'
    
    # Create invoice for VIP subscription
    prices = [types.LabeledPrice(label="VIP Subscription", amount=vip_price)]
    
    bot.send_invoice(
        chat_id=chat_id,
        title="🌟 VIP Membership Subscription",
        description=f"{vip_description} - 30 days unlimited access",
        invoice_payload=f"vip_subscription_{user_id}",
        provider_token=None,  # None for Telegram Stars
        currency='XTR',  # Telegram Stars currency
        prices=prices,
        start_parameter='vip_purchase'
    )

def show_content_catalog(chat_id, user_id=None):
    """Show available content for purchase with VIP access controls"""
    # Get user ID if not provided (for callback compatibility)
    if user_id is None:
        # This is a fallback for when called from callback without user_id
        # In practice, we should always pass user_id
        user_id = chat_id  # Assuming direct message context
    
    # Check VIP status
    vip_status = check_vip_status(user_id)
    is_vip = vip_status['is_vip']
    
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name, price_stars, description FROM content_items')
    items = cursor.fetchall()
    conn.close()
    
    if items:
        if is_vip:
            catalog_text = "💎 <b>VIP EXCLUSIVE CONTENT</b> 💎\n\n"
            catalog_text += f"🎉 As a VIP member, you have <b>FREE ACCESS</b> to all content!\n"
            catalog_text += f"⏰ Your VIP expires in {vip_status['days_left']} days\n\n"
        else:
            catalog_text = "🛒 <b>EXCLUSIVE CONTENT CATALOG</b> 🛒\n\n"
            catalog_text += "💡 <b>Tip:</b> VIP members get FREE access to all content!\n\n"
        
        markup = types.InlineKeyboardMarkup()
        
        for name, price, description in items:
            # Escape HTML special characters to prevent parsing errors
            safe_name = name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            safe_description = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            catalog_text += f"✨ <b>{safe_name}</b>\n"
            
            if is_vip:
                catalog_text += f"💎 <b>VIP FREE ACCESS</b>\n"
                markup.add(types.InlineKeyboardButton(f"🎁 Get {name} (VIP FREE)", callback_data=f"vip_get_{name}"))
            else:
                catalog_text += f"💰 {price} Stars\n"
                markup.add(types.InlineKeyboardButton(f"⭐ Buy {name} ({price} Stars)", callback_data=f"buy_{name}"))
            
            catalog_text += f"📝 {safe_description}\n\n"
        
        # Add VIP upgrade option for non-VIP users
        if not is_vip:
            markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP for FREE Access", callback_data="vip_access"))
        
        # Add back button
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
        
        bot.send_message(chat_id, catalog_text, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, "No content available right now. Check back soon! 💕")

@bot.message_handler(commands=['help'])
def help_command(message):
    """Handle /help command"""
    add_or_update_user(message.from_user)
    
    help_text = """
📚 **HOW TO USE THIS BOT** 📚

💬 **Natural Chat:**
Just type anything and I'll respond! I love chatting with my fans.

⭐ **Telegram Stars:**
Use Telegram Stars to purchase my exclusive content. It's safe, secure, and instant!

🎯 **Quick Actions:**
Use the buttons below to navigate - no need to type commands!

💕 Questions? Just join the VIP - I read everything - Waiting for you!
"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    # Row 1: Main actions
    markup.add(
        types.InlineKeyboardButton("🏠 VIPEntry", callback_data="cmd_start"),
        types.InlineKeyboardButton("🎬 Free Teasers", callback_data="cmd_teaser")
    )
    # Row 2: Shopping
    markup.add(
        types.InlineKeyboardButton("🛒 Browse Content", callback_data="browse_content"),
        types.InlineKeyboardButton("💬 Ask Me Anything", callback_data="ask_question")
    )
    # Row 3: Help refresh
    markup.add(types.InlineKeyboardButton("🔄 Refresh Help", callback_data="cmd_help"))
    
    bot.send_message(message.chat.id, help_text, reply_markup=markup, parse_mode='Markdown')

# Owner/Admin commands

@bot.message_handler(commands=['owner_add_content'])
def owner_add_content(message):
    """Handle /owner_add_content command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    try:
        # Parse command: /owner_add_content [name] [price_stars] [file_path_or_url] [description]
        parts = message.text.split(' ', 4)
        if len(parts) < 4:
            bot.send_message(message.chat.id, "❌ Usage: /owner_add_content [name] [price_stars] [file_path_or_url] [description]")
            return
        
        name = parts[1]
        price_stars = int(parts[2])
        file_path = parts[3]
        description = parts[4] if len(parts) > 4 else "Exclusive content"
        
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO content_items (name, price_stars, file_path, description, created_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, price_stars, file_path, description, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, f"✅ Content '{name}' added successfully!\n💰 Price: {price_stars} Stars\n📝 {description}")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid price. Please enter a number for Stars.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error adding content: {str(e)}")

@bot.message_handler(commands=['owner_delete_content'])
def owner_delete_content(message):
    """Handle /owner_delete_content command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    parts = message.text.split(' ', 1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Usage: /owner_delete_content [name]")
        return
    
    name = parts[1]
    
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM content_items WHERE name = ?', (name,))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    if deleted_count > 0:
        bot.send_message(message.chat.id, f"✅ Content '{name}' deleted successfully!")
    else:
        bot.send_message(message.chat.id, f"❌ Content '{name}' not found.")

@bot.message_handler(commands=['owner_upload'])
def owner_upload_content(message):
    """Handle /owner_upload command - start guided upload flow"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    # Initialize upload session
    upload_sessions[OWNER_ID] = {
        'step': 'waiting_for_file',
        'name': None,
        'price': None,
        'description': None,
        'file_path': None
    }
    
    upload_text = """
📤 <b>GUIDED CONTENT UPLOAD</b> 📤

I'll help you upload new content step by step!

<b>Step 1:</b> Send me the file (photo, video, or document)
- Just upload/send the file directly to this chat
- Supported: Photos, Videos, Documents

After you send the file, I'll ask for the name, price, and description.

💡 <b>Tip:</b> You can also use /owner_add_content [name] [price] [url] [description] for web URLs.
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_upload"))
    
    bot.send_message(message.chat.id, upload_text, reply_markup=markup, parse_mode='HTML')

@bot.message_handler(content_types=['photo', 'video', 'document'])
def handle_file_upload(message):
    """Handle file uploads for content creation"""
    if message.from_user.id != OWNER_ID:
        return  # Only owner can upload content
    
    # Check if we're in an upload session
    if OWNER_ID not in upload_sessions or upload_sessions[OWNER_ID]['step'] != 'waiting_for_file':
        bot.send_message(message.chat.id, "📤 To upload content, start with `/owner_upload` command first!")
        return
    
    # Get file info based on content type
    file_info = None
    file_type = ""
    
    if message.content_type == 'photo':
        file_info = bot.get_file(message.photo[-1].file_id)  # Get highest resolution
        file_type = "Photo"
    elif message.content_type == 'video':
        file_info = bot.get_file(message.video.file_id)
        file_type = "Video"
    elif message.content_type == 'document':
        file_info = bot.get_file(message.document.file_id)
        file_type = "Document"
    
    if file_info:
        # Store file_id instead of download URL to avoid exposing bot token
        file_id = None
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
        elif message.content_type == 'video':
            file_id = message.video.file_id
        elif message.content_type == 'document':
            file_id = message.document.file_id
        else:
            bot.send_message(message.chat.id, "❌ Unsupported file type. Please send a photo, video, or document.")
            return
        
        upload_sessions[OWNER_ID]['file_path'] = file_id  # Store file_id instead of URL
        upload_sessions[OWNER_ID]['file_type'] = file_type
        upload_sessions[OWNER_ID]['step'] = 'waiting_for_name'
        
        # Ask for content name
        name_text = f"""
✅ **{file_type} uploaded successfully!**

<b>Step 2:</b> What should I call this content?
Type a unique name (no spaces, use underscores):

Example: beach_photoshoot_1 or exclusive_video_dec

This name will be used internally to identify the content.
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_upload"))
        
        bot.send_message(message.chat.id, name_text, reply_markup=markup, parse_mode='HTML')

@bot.message_handler(func=lambda message: message.from_user.id == OWNER_ID and OWNER_ID in upload_sessions)
def handle_upload_flow(message):
    """Handle the guided upload flow steps"""
    if OWNER_ID not in upload_sessions:
        return
    
    session = upload_sessions[OWNER_ID]
    
    if session['step'] == 'waiting_for_name':
        # Validate name (no spaces, alphanumeric + underscores)
        name = message.text.strip()
        if not name or ' ' in name or not all(c.isalnum() or c == '_' for c in name):
            bot.send_message(message.chat.id, "❌ Invalid name! Use only letters, numbers, and underscores (no spaces).\nExample: beach_photos_1")
            return
        
        # Check if name already exists
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM content_items WHERE name = ?', (name,))
        existing = cursor.fetchone()
        conn.close()
        
        if existing:
            bot.send_message(message.chat.id, f"❌ Content with name '{name}' already exists! Choose a different name.")
            return
        
        session['name'] = name
        session['step'] = 'waiting_for_price'
        
        price_text = f"""
✅ <b>Name set:</b> {name}

<b>Step 3:</b> How much should this cost?
Enter the price in Telegram Stars (just the number):

Examples: 25, 50, 100

💡 Typical prices:
• Photo sets: 20-50 Stars
• Videos: 50-200 Stars
• Exclusive content: 100+ Stars
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_upload"))
        
        bot.send_message(message.chat.id, price_text, reply_markup=markup, parse_mode='HTML')
    
    elif session['step'] == 'waiting_for_price':
        try:
            price = int(message.text.strip())
            if price <= 0:
                bot.send_message(message.chat.id, "❌ Price must be a positive number!")
                return
            
            session['price'] = price
            session['step'] = 'waiting_for_description'
            
            desc_text = f"""
✅ <b>Price set:</b> {price} Stars

<b>Step 4:</b> Add a description (optional)
Write a short description that customers will see:

Example: "Exclusive behind-the-scenes photos from my latest shoot"

Or type skip to use a default description.
"""
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("⏭️ Skip Description", callback_data="skip_description"),
                types.InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_upload")
            )
            
            bot.send_message(message.chat.id, desc_text, reply_markup=markup, parse_mode='HTML')
            
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid price! Enter just the number (e.g., 25)")
    
    elif session['step'] == 'waiting_for_description':
        description = message.text.strip()
        if description.lower() == 'skip':
            description = f"Exclusive {session.get('file_type', 'content').lower()} content"
        
        session['description'] = description
        
        # Save content to database
        save_uploaded_content(session)

def save_uploaded_content(session):
    """Save the uploaded content to database and finish the flow"""
    try:
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO content_items (name, price_stars, file_path, description, created_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (session['name'], session['price'], session['file_path'], session['description'], datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        # Success message
        success_text = f"""
🎉 <b>CONTENT ADDED SUCCESSFULLY!</b> 🎉

📦 <b>Name:</b> {session['name']}
💰 <b>Price:</b> {session['price']} Stars
📝 <b>Description:</b> {session['description']}
📁 <b>Type:</b> {session.get('file_type', 'File')}

Your content is now available for purchase! Fans can buy it using:
• The browse content menu
• /buy {session['name']} command

🛒 Content will be delivered automatically after payment.
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📦 Add Another", callback_data="start_upload"))
        markup.add(types.InlineKeyboardButton("👥 View Users", callback_data="owner_list_users"))
        
        bot.send_message(OWNER_ID, success_text, reply_markup=markup, parse_mode='HTML')
        
        # Clear upload session
        if OWNER_ID in upload_sessions:
            del upload_sessions[OWNER_ID]
            
    except Exception as e:
        bot.send_message(OWNER_ID, f"❌ Error saving content: {str(e)}")
        if OWNER_ID in upload_sessions:
            del upload_sessions[OWNER_ID]

@bot.message_handler(commands=['owner_list_users'])
def owner_list_users(message):
    """Handle /owner_list_users command - show only paying customers"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    # Only show paying customers (total_stars_spent > 0) and exclude bot user ID
    cursor.execute('''
        SELECT u.user_id, u.username, u.first_name, u.total_stars_spent, u.interaction_count, 
               CASE WHEN l.user_id IS NOT NULL THEN 'Yes' ELSE 'No' END as is_loyal
        FROM users u
        LEFT JOIN loyal_fans l ON u.user_id = l.user_id
        WHERE u.total_stars_spent > 0 AND u.user_id != ?
        ORDER BY u.total_stars_spent DESC
    ''', (bot.get_me().id,))
    paying_customers = cursor.fetchall()
    
    # Get all customers stats for comparison
    cursor.execute('SELECT COUNT(*), SUM(total_stars_spent) FROM users WHERE total_stars_spent > 0 AND user_id != ?', (bot.get_me().id,))
    total_paying_customers, total_revenue = cursor.fetchone()
    
    conn.close()
    
    if paying_customers:
        user_text = "💰 <b>PAYING CUSTOMERS</b> 💰\n\n"
        
        user_text += f"👥 Total Paying Customers: {total_paying_customers or 0}\n"
        user_text += f"💰 Total Revenue: {total_revenue or 0} Stars\n"
        user_text += f"📈 Average Revenue per Customer: {(total_revenue or 0) / max(total_paying_customers or 1, 1):.1f} Stars\n\n"
        
        for user_id, username, first_name, stars_spent, interactions, is_loyal in paying_customers[:15]:  # Show top 15
            # Escape HTML characters in usernames to prevent parsing errors
            safe_username = (username or 'none').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            safe_first_name = (first_name or 'N/A').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            user_text += f"👤 {safe_first_name} (@{safe_username})\n"
            user_text += f"   💰 {stars_spent} Stars | 💬 {interactions} interactions"
            if is_loyal == 'Yes':
                user_text += " | ⭐ LOYAL"
            user_text += f"\n   🆔 ID: {user_id}\n\n"
        
        if len(paying_customers) > 15:
            user_text += f"... and {len(paying_customers) - 15} more paying customers"
        
        bot.send_message(message.chat.id, user_text, parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "💰 No paying customers yet. Share your content to start earning! 🚀")

@bot.message_handler(commands=['owner_analytics'])
def owner_analytics(message):
    """Handle /owner_analytics command - show accurate analytics for paying customers only"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    # Get paying customers statistics (exclude bot)
    cursor.execute('SELECT COUNT(*), SUM(total_stars_spent), SUM(interaction_count) FROM users WHERE total_stars_spent > 0 AND user_id != ?', (bot.get_me().id,))
    paying_customers, total_revenue, paying_interactions = cursor.fetchone()
    
    # Get all users statistics for comparison (exclude bot)
    cursor.execute('SELECT COUNT(*), SUM(interaction_count) FROM users WHERE user_id != ?', (bot.get_me().id,))
    total_users, total_interactions = cursor.fetchone()
    
    # Get top spenders (only paying customers)
    cursor.execute('SELECT first_name, username, total_stars_spent FROM users WHERE total_stars_spent > 0 AND user_id != ? ORDER BY total_stars_spent DESC LIMIT 5', (bot.get_me().id,))
    top_spenders = cursor.fetchall()
    
    # Get content performance
    cursor.execute('SELECT name, price_stars FROM content_items')
    content_items = cursor.fetchall()
    
    conn.close()
    
    # Calculate conversion rate
    conversion_rate = (paying_customers / max(total_users or 1, 1)) * 100 if total_users else 0
    
    analytics_text = f"""
📈 **ANALYTICS DASHBOARD** 📈

📊 **Overall Stats:**
👥 Total Visitors: {total_users or 0}
💰 Paying Customers: {paying_customers or 0}
📈 Conversion Rate: {conversion_rate:.1f}%
💰 Total Revenue: {total_revenue or 0} Stars
📱 Average per Customer: {(total_revenue or 0) / max(paying_customers or 1, 1):.1f} Stars

🏆 **Top Spenders:**
"""
    
    if top_spenders:
        for i, (first_name, username, spent) in enumerate(top_spenders, 1):
            analytics_text += f"{i}. {first_name or 'N/A'} (@{username or 'none'}): {spent} Stars\n"
    else:
        analytics_text += "No paying customers yet.\n"
    
    analytics_text += f"\n🛒 **Content Catalog:**\n"
    analytics_text += f"📦 Total Items: {len(content_items)}\n"
    
    if content_items:
        avg_price = sum(price for _, price in content_items) / len(content_items)
        analytics_text += f"💰 Average Price: {avg_price:.1f} Stars"
    
    bot.send_message(message.chat.id, analytics_text, parse_mode='Markdown')

@bot.message_handler(commands=['owner_set_response'])
def owner_set_response(message):
    """Handle /owner_set_response command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    parts = message.text.split(' ', 2)
    if len(parts) < 3:
        bot.send_message(message.chat.id, "❌ Usage: /owner_set_response [key] [text]\nKeys: greeting, question, compliment, default")
        return
    
    key = parts[1]
    text = parts[2]
    
    valid_keys = ['greeting', 'question', 'compliment', 'default']
    if key not in valid_keys:
        bot.send_message(message.chat.id, f"❌ Invalid key. Valid keys: {', '.join(valid_keys)}")
        return
    
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO responses (key, text) VALUES (?, ?)', (key, text))
    conn.commit()
    conn.close()
    
    bot.send_message(message.chat.id, f"✅ AI response for '{key}' updated successfully!")

@bot.message_handler(commands=['owner_help'])
def owner_help(message):
    """Handle /owner_help command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    help_text = """
🔧 **OWNER COMMANDS** 🔧

📦 **Content Management:**
• `/owner_upload` - Guided file upload (photos/videos/documents)
• `/owner_add_content [name] [price] [url] [description]` - Add content via URL
• `/owner_delete_content [name]` - Remove content

👥 **User Management:**
• `/owner_list_users` - View paying customers only
• `/owner_analytics` - Detailed analytics dashboard

🤖 **Bot Configuration:**
• `/owner_set_response [key] [text]` - Update AI responses
  Keys: greeting, question, compliment, default

ℹ️ **Information:**
• `/owner_help` - Show this help message

💡 **Tips:**
- Upload files directly for automatic Telegram hosting
- Analytics show only paying customers
- AI responses support emojis and markdown
- All changes take effect immediately
"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📤 Upload File", callback_data="start_upload"),
        types.InlineKeyboardButton("🔗 Add URL", callback_data="owner_add_content")
    )
    markup.add(types.InlineKeyboardButton("👥 View Customers", callback_data="owner_list_users"))
    
    bot.send_message(message.chat.id, help_text, reply_markup=markup, parse_mode='Markdown')

# Owner VIP Management Commands

@bot.message_handler(commands=['owner_set_vip_price'])
def owner_set_vip_price(message):
    """Handle /owner_set_vip_price command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    parts = message.text.split(' ', 1)
    if len(parts) < 2:
        current_price = get_vip_settings('vip_price_stars') or '399'
        bot.send_message(message.chat.id, f"❌ Usage: /owner_set_vip_price [price_in_stars]\n\nCurrent VIP price: {current_price} Stars")
        return
    
    try:
        new_price = int(parts[1])
        if new_price <= 0:
            bot.send_message(message.chat.id, "❌ Price must be a positive number!")
            return
        
        update_vip_settings('vip_price_stars', str(new_price))
        bot.send_message(message.chat.id, f"✅ VIP price updated to {new_price} Stars/month")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid price. Please enter a number.")

@bot.message_handler(commands=['owner_vip_analytics'])
def owner_vip_analytics(message):
    """Handle /owner_vip_analytics command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    # Get VIP statistics
    cursor.execute('SELECT COUNT(*) FROM vip_subscriptions WHERE is_active = 1')
    active_vip_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM vip_subscriptions')
    total_vip_subscriptions = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(total_payments) FROM vip_subscriptions')
    total_vip_payments = cursor.fetchone()[0] or 0
    
    # Get VIP settings
    vip_price = int(get_vip_settings('vip_price_stars') or 399)
    total_vip_revenue = total_vip_payments * vip_price
    
    # Get VIP users details
    cursor.execute('''
        SELECT u.first_name, u.username, v.start_date, v.expiry_date, v.total_payments
        FROM vip_subscriptions v
        JOIN users u ON v.user_id = u.user_id
        WHERE v.is_active = 1
        ORDER BY v.total_payments DESC
        LIMIT 10
    ''')
    active_vips = cursor.fetchall()
    
    conn.close()
    
    analytics_text = f"""
💎 **VIP ANALYTICS DASHBOARD** 💎

📊 **VIP Statistics:**
👑 Active VIP Members: {active_vip_count}
📈 Total VIP Subscriptions Ever: {total_vip_subscriptions}
💰 Total VIP Payments: {total_vip_payments}
💵 Total VIP Revenue: {total_vip_revenue} Stars
💰 Current VIP Price: {vip_price} Stars/month

🏆 **Top VIP Members:**
"""
    
    for i, (first_name, username, start_date, expiry_date, payments) in enumerate(active_vips[:5], 1):
        safe_first_name = (first_name or 'N/A').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        safe_username = (username or 'none').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        analytics_text += f"{i}. {safe_first_name} (@{safe_username}) - {payments} payments\n"
    
    bot.send_message(message.chat.id, analytics_text, parse_mode='HTML')

@bot.message_handler(commands=['owner_list_vips'])
def owner_list_vips(message):
    """Handle /owner_list_vips command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    # Get all active VIP users
    cursor.execute('''
        SELECT u.user_id, u.first_name, u.username, v.start_date, v.expiry_date, v.total_payments
        FROM vip_subscriptions v
        JOIN users u ON v.user_id = u.user_id
        WHERE v.is_active = 1
        ORDER BY v.expiry_date DESC
    ''')
    vip_users = cursor.fetchall()
    
    conn.close()
    
    if vip_users:
        vip_text = "💎 <b>ACTIVE VIP MEMBERS</b> 💎\n\n"
        
        for user_id, first_name, username, start_date, expiry_date, payments in vip_users:
            safe_first_name = (first_name or 'N/A').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            safe_username = (username or 'none').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            # Calculate days left
            try:
                expiry_datetime = datetime.datetime.fromisoformat(expiry_date)
                days_left = (expiry_datetime - datetime.datetime.now()).days
                days_text = f"{days_left} days left"
            except:
                days_text = "Invalid date"
            
            vip_text += f"👤 {safe_first_name} (@{safe_username})\n"
            vip_text += f"   ⏰ {days_text} | 💰 {payments} payments\n"
            vip_text += f"   🆔 ID: {user_id}\n\n"
        
        bot.send_message(message.chat.id, vip_text, parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "💎 No active VIP members yet.")

# Callback query handlers

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """Handle inline keyboard callbacks"""
    
    if call.data == "vip_access":
        show_vip_access(call.message.chat.id, call.from_user.id)
    elif call.data == "buy_vip":
        purchase_vip_subscription(call.message.chat.id, call.from_user.id)
    elif call.data == "teasers":
        teaser_command(call.message)
    elif call.data == "browse_content":
        show_content_catalog(call.message.chat.id, call.from_user.id)
    elif call.data == "ask_question":
        bot.send_message(call.message.chat.id, "💬 Feel free to ask me anything! Just type your message and I'll respond personally. 😊")
    elif call.data == "help":
        help_command(call.message)
    elif call.data == "cmd_help":
        help_command(call.message)
    elif call.data == "cmd_start":
        # Create proper message object with callback user info
        fake_message = type('obj', (object,), {
            'chat': call.message.chat,
            'from_user': call.from_user,
            'message_id': call.message.message_id
        })
        start_command(fake_message)
    elif call.data == "cmd_teaser":
        # Create proper message object with callback user info
        fake_message = type('obj', (object,), {
            'chat': call.message.chat,
            'from_user': call.from_user,
            'message_id': call.message.message_id
        })
        teaser_command(fake_message)
    elif call.data == "buy_premium":
        show_content_catalog(call.message.chat.id)
    elif call.data.startswith("buy_"):
        item_name = call.data.replace("buy_", "")
        purchase_item(call.message.chat.id, call.from_user.id, item_name)
    elif call.data.startswith("vip_get_"):
        item_name = call.data.replace("vip_get_", "")
        deliver_vip_content(call.message.chat.id, call.from_user.id, item_name)
    elif call.data == "owner_add_content":
        if call.from_user.id != OWNER_ID:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
        else:
            bot.send_message(call.message.chat.id, "📦 Use: /owner_add_content [name] [price] [url] [description]")
    elif call.data == "owner_list_users":
        if call.from_user.id != OWNER_ID:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
        else:
            # Create a fake message object for the owner_list_users function
            fake_message = type('obj', (object,), {
                'chat': call.message.chat,
                'from_user': call.from_user
            })
            owner_list_users(fake_message)
    elif call.data == "cancel_upload":
        if call.from_user.id == OWNER_ID and OWNER_ID in upload_sessions:
            del upload_sessions[OWNER_ID]
            bot.send_message(call.message.chat.id, "❌ Upload cancelled.")
        else:
            bot.send_message(call.message.chat.id, "❌ No active upload session.")
    elif call.data == "skip_description":
        if call.from_user.id == OWNER_ID and OWNER_ID in upload_sessions:
            session = upload_sessions[OWNER_ID]
            if session['step'] == 'waiting_for_description':
                session['description'] = f"Exclusive {session.get('file_type', 'content').lower()} content"
                save_uploaded_content(session)
            else:
                bot.send_message(call.message.chat.id, "❌ Invalid step for skipping description.")
        else:
            bot.send_message(call.message.chat.id, "❌ No active upload session.")
    elif call.data == "start_upload":
        if call.from_user.id == OWNER_ID:
            # Create a fake message object for the owner_upload_content function
            fake_message = type('obj', (object,), {
                'chat': call.message.chat,
                'from_user': call.from_user,
                'text': '/owner_upload'
            })
            owner_upload_content(fake_message)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    
    # Answer callback to remove loading state
    bot.answer_callback_query(call.id)

# Payment handlers

@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout_handler(pre_checkout_query):
    """Handle pre-checkout queries for Telegram Stars payments"""
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def successful_payment_handler(message):
    """Handle successful payment and deliver content"""
    payment = message.successful_payment
    
    # Parse payload to get content info
    payload_parts = payment.invoice_payload.split('_')
    
    # Handle VIP subscription payments
    if len(payload_parts) >= 2 and payload_parts[0] == 'vip' and payload_parts[1] == 'subscription':
        user_id = int(payload_parts[2])
        
        # Update user's total spent
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET total_stars_spent = total_stars_spent + ? WHERE user_id = ?', 
                      (payment.total_amount, user_id))
        conn.commit()
        conn.close()
        
        # Activate VIP subscription
        duration_days = activate_vip_subscription(user_id)
        
        # Send confirmation message
        vip_welcome_message = f"""
💎 **VIP SUBSCRIPTION ACTIVATED!** 💎

🎉 Congratulations! You are now a VIP member!
⏰ **Duration:** {duration_days} days
💰 **Amount:** {payment.total_amount} Stars

🌟 **Your VIP Benefits Are Now Active:**
• Unlimited access to all exclusive content
• Direct personal chat with me
• Priority responses to all messages
• Special VIP-only teasers and previews
• Monthly exclusive photo sets
• Behind-the-scenes content

💫 Welcome to the VIP family! You're absolutely amazing! ✨

Use the buttons below to explore your new VIP privileges:
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🛒 Browse All Content", callback_data="browse_content"))
        markup.add(types.InlineKeyboardButton("🎬 VIP Exclusive Teasers", callback_data="teasers"))
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
        
        bot.send_message(message.chat.id, vip_welcome_message, reply_markup=markup, parse_mode='Markdown')
        
        # Notify owner of new VIP subscription
        try:
            bot.send_message(OWNER_ID, f"💎 NEW VIP SUBSCRIPTION!\n👤 {message.from_user.first_name} (@{message.from_user.username})\n💰 {payment.total_amount} Stars\n🆔 ID: {user_id}")
        except:
            pass
            
    elif len(payload_parts) >= 3 and payload_parts[0] == 'content':
        content_name = payload_parts[1]
        user_id = int(payload_parts[2])
        
        # Update user's total spent
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET total_stars_spent = total_stars_spent + ? WHERE user_id = ?', 
                      (payment.total_amount, user_id))
        
        # Get content details
        cursor.execute('SELECT file_path, description FROM content_items WHERE name = ?', (content_name,))
        content = cursor.fetchone()
        conn.commit()
        conn.close()
        
        if content:
            file_path, description = content
            
            # Send content to user
            thank_you_message = f"""
🎉 **PAYMENT SUCCESSFUL!** 🎉

Thank you for your purchase! Here's your exclusive content:

**{content_name}**
{description}

💕 You're amazing for supporting me! Enjoy your content!
"""
            
            bot.send_message(message.chat.id, thank_you_message, parse_mode='Markdown')
            
            # Send the actual content (photo/video/document)
            try:
                if file_path.startswith('http'):
                    # It's a URL
                    if any(ext in file_path.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                        bot.send_photo(message.chat.id, file_path, caption=f"🎁 {content_name}")
                    elif any(ext in file_path.lower() for ext in ['.mp4', '.mov', '.avi']):
                        bot.send_video(message.chat.id, file_path, caption=f"🎁 {content_name}")
                    else:
                        bot.send_document(message.chat.id, file_path, caption=f"🎁 {content_name}")
                elif len(file_path) > 50 and not file_path.startswith('/'):
                    # It's a Telegram file_id (file_ids are long strings)
                    try:
                        # Try to send as photo first (most common)
                        bot.send_photo(message.chat.id, file_path, caption=f"🎁 {content_name}")
                    except:
                        try:
                            # Try as video
                            bot.send_video(message.chat.id, file_path, caption=f"🎁 {content_name}")
                        except:
                            try:
                                # Try as document
                                bot.send_document(message.chat.id, file_path, caption=f"🎁 {content_name}")
                            except:
                                # Last resort - show file_id
                                bot.send_message(message.chat.id, f"🎁 Your content: {content_name}\n\nFile ID: {file_path}\n\n⚠️ If you have trouble accessing this content, please contact me!")
                else:
                    # It's a local file path
                    with open(file_path, 'rb') as file:
                        if any(ext in file_path.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            bot.send_photo(message.chat.id, file, caption=f"🎁 {content_name}")
                        elif any(ext in file_path.lower() for ext in ['.mp4', '.mov', '.avi']):
                            bot.send_video(message.chat.id, file, caption=f"🎁 {content_name}")
                        else:
                            bot.send_document(message.chat.id, file, caption=f"🎁 {content_name}")
            except Exception as e:
                bot.send_message(message.chat.id, f"🎁 Your content: {content_name}\n\n⚠️ There was an issue delivering your content. Please contact me and I'll send it manually!")
                logger.error(f"Error sending content {content_name}: {e}")
            
            # Notify owner of sale
            try:
                user_data = get_user_data(user_id)
                if user_data:
                    username = user_data[1] or "none"
                    first_name = user_data[2] or "N/A"
                    total_spent = user_data[4]  # Don't add payment.total_amount again - it's already updated in DB
                    
                    bot.send_message(OWNER_ID, f"""
💰 **NEW SALE!** 💰

👤 Customer: {first_name} (@{username})
🛒 Item: {content_name}
⭐ Amount: {payment.total_amount} Stars
💎 Total Spent: {total_spent} Stars
🆔 User ID: {user_id}
""")
            except Exception as e:
                logger.error(f"Error notifying owner: {e}")

# Natural text message handler

@bot.message_handler(content_types=['text'])
def handle_text_messages(message):
    """Handle natural text messages with AI-style responses"""
    # Skip if it's a command
    if message.text.startswith('/'):
        return
    
    add_or_update_user(message.from_user)
    
    # Get AI-style response
    response = get_ai_response(message.text)
    
    # Add inline keyboard for engagement
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎬 View Teasers", callback_data="teasers"))
    markup.add(types.InlineKeyboardButton("🛒 Browse Content", callback_data="browse_content"))
    
    bot.send_message(message.chat.id, response, reply_markup=markup)

# Flask routes for Replit hosting

@app.route('/')
def home():
    """Basic health check endpoint"""
    return "🤖 Content Creator Bot is running! 🌟"

@app.route('/health')
def health():
    """Health check for monitoring"""
    return {"status": "healthy", "bot": "running"}

def run_bot():
    """Run the bot with infinity polling"""
    logger.info("Starting bot polling...")
    bot.infinity_polling(none_stop=True)

def main():
    """Main function to initialize and start the bot"""
    logger.info("Initializing Content Creator Bot...")
    
    # Initialize database
    init_database()
    
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Start Flask server
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask server on 0.0.0.0:{port}...")
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()