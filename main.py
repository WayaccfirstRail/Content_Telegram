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
            created_date TEXT,
            content_type TEXT DEFAULT 'browse'
        )
    ''')
    
    # Add content_type column to existing content_items table if it doesn't exist
    # This provides backward compatibility for existing databases
    try:
        cursor.execute("ALTER TABLE content_items ADD COLUMN content_type TEXT DEFAULT 'browse'")
        logger.info("Added content_type column to existing content_items table")
    except sqlite3.OperationalError:
        # Column already exists, which is fine
        pass
    
    # User purchases table - tracks individual content purchases for permanent access
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content_name TEXT,
            purchase_date TEXT,
            price_paid INTEGER,
            UNIQUE (user_id, content_name),
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (content_name) REFERENCES content_items (name)
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
    
    # Teasers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teasers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            file_type TEXT,
            description TEXT,
            created_date TEXT
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
        ('photo_set_1', 25, 'https://example.com/photo1.jpg', 'Exclusive photo set - Behind the scenes', datetime.datetime.now().isoformat(), 'browse'),
        ('video_preview', 50, 'https://example.com/video1.mp4', 'Special video content just for you', datetime.datetime.now().isoformat(), 'browse')
    ]
    
    for name, price, path, desc, date, content_type in sample_content:
        cursor.execute('INSERT OR IGNORE INTO content_items (name, price_stars, file_path, description, created_date, content_type) VALUES (?, ?, ?, ?, ?, ?)', 
                      (name, price, path, desc, date, content_type))
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

def get_db_connection():
    """Get SQLite database connection with proper settings"""
    conn = sqlite3.connect('content_bot.db')
    conn.execute('PRAGMA foreign_keys = ON')  # Enable foreign key constraints
    return conn

def get_user_data(user_id):
    """Get user data from database"""
    conn = get_db_connection()
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

def check_user_owns_content(user_id, content_name):
    """Check if user has already purchased specific content"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM user_purchases WHERE user_id = ? AND content_name = ?', (user_id, content_name))
    purchase = cursor.fetchone()
    conn.close()
    return purchase is not None

def get_user_purchased_content(user_id):
    """Get all BROWSE content purchased by a user - does not include VIP content"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT up.content_name, up.purchase_date, up.price_paid, ci.description, ci.file_path
        FROM user_purchases up
        JOIN content_items ci ON up.content_name = ci.name
        WHERE up.user_id = ? AND ci.content_type = ?
        ORDER BY up.purchase_date DESC
    ''', (user_id, 'browse'))
    purchases = cursor.fetchall()
    conn.close()
    return purchases

def deliver_owned_content(chat_id, user_id, content_name):
    """Re-deliver content that user already owns"""
    # First verify the user actually owns this content
    if not check_user_owns_content(user_id, content_name):
        bot.send_message(chat_id, "❌ You don't own this content. Please purchase it first!")
        return False
    
    # Get content details
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT file_path, description FROM content_items WHERE name = ?', (content_name,))
    content = cursor.fetchone()
    conn.close()
    
    if not content:
        bot.send_message(chat_id, f"❌ Content '{content_name}' not found.")
        return False
    
    file_path, description = content
    
    # Send re-access message
    reaccess_message = f"""
✅ <b>OWNED CONTENT ACCESS</b> ✅

🎁 Here's your purchased content again!

<b>{content_name}</b>
{description}

💕 Thank you for being an amazing supporter!
"""
    
    bot.send_message(chat_id, reaccess_message, parse_mode='HTML')
    
    # Send the actual content (same logic as purchase delivery)
    try:
        if file_path.startswith('http'):
            # It's a URL
            if any(ext in file_path.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                bot.send_photo(chat_id, file_path, caption=f"🎁 {content_name}")
            elif any(ext in file_path.lower() for ext in ['.mp4', '.mov', '.avi']):
                bot.send_video(chat_id, file_path, caption=f"🎁 {content_name}")
            else:
                bot.send_document(chat_id, file_path, caption=f"🎁 {content_name}")
        elif len(file_path) > 50 and not file_path.startswith('/'):
            # It's a Telegram file_id
            try:
                bot.send_photo(chat_id, file_path, caption=f"🎁 {content_name}")
            except:
                try:
                    bot.send_video(chat_id, file_path, caption=f"🎁 {content_name}")
                except:
                    try:
                        bot.send_document(chat_id, file_path, caption=f"🎁 {content_name}")
                    except:
                        bot.send_message(chat_id, f"🎁 Your content: {content_name}\n\nFile ID: {file_path}\n\n⚠️ If you have trouble accessing this content, please contact me!")
        else:
            # It's a local file path
            with open(file_path, 'rb') as file:
                if any(ext in file_path.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    bot.send_photo(chat_id, file, caption=f"🎁 {content_name}")
                elif any(ext in file_path.lower() for ext in ['.mp4', '.mov', '.avi']):
                    bot.send_video(chat_id, file, caption=f"🎁 {content_name}")
                else:
                    bot.send_document(chat_id, file, caption=f"🎁 {content_name}")
    except Exception as e:
        bot.send_message(chat_id, f"🎁 Your owned content: {content_name}\n\n⚠️ There was an issue delivering your content. Please contact me and I'll send it manually!")
        logger.error(f"Error sending owned content {content_name}: {e}")
        return False
    
    return True

def show_my_content(chat_id, user_id):
    """Show user's purchased content library with re-access options"""
    # Get user's purchased content
    purchases = get_user_purchased_content(user_id)
    
    if not purchases:
        no_content_message = """
📂 <b>MY CONTENT LIBRARY</b> 📂

🚫 You haven't purchased any content yet!

🛒 <b>Ready to get started?</b>
Browse our exclusive content catalog and treat yourself to something special!

💡 <b>Secret:</b> VIP members unlock exclusive content that regular users will never see... What are they experiencing that you're missing? 👀
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🛒 Browse Content", callback_data="browse_content"))
        markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP", callback_data="vip_access"))
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
        
        bot.send_message(chat_id, no_content_message, reply_markup=markup, parse_mode='HTML')
        return
    
    # Create content library message
    library_text = f"📂 <b>MY CONTENT LIBRARY</b> 📂\n\n"
    library_text += f"🎉 You own {len(purchases)} piece(s) of exclusive content!\n\n"
    
    markup = types.InlineKeyboardMarkup()
    
    for content_name, purchase_date, price_paid, description, file_path in purchases:
        # Escape HTML special characters
        safe_name = content_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        safe_description = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Format purchase date
        try:
            date_obj = datetime.datetime.fromisoformat(purchase_date)
            formatted_date = date_obj.strftime("%b %d, %Y")
        except:
            formatted_date = "Unknown"
        
        library_text += f"✨ <b>{safe_name}</b>\n"
        library_text += f"📅 Purchased: {formatted_date}\n"
        library_text += f"💰 Paid: {price_paid} Stars\n"
        library_text += f"📝 {safe_description}\n\n"
        
        # Add re-access button for each item
        markup.add(types.InlineKeyboardButton(f"🎁 Access {content_name}", callback_data=f"access_{content_name}"))
    
    # Add navigation buttons
    markup.add(types.InlineKeyboardButton("🛒 Browse More Content", callback_data="browse_content"))
    markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
    
    bot.send_message(chat_id, library_text, reply_markup=markup, parse_mode='HTML')

def show_analytics_dashboard(chat_id):
    """Show comprehensive analytics dashboard"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    # Get user statistics
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE last_interaction >= ?', (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat())
    active_users_7d = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE total_stars_spent > 0')
    paying_users = cursor.fetchone()[0]
    
    # Get VIP statistics
    cursor.execute('SELECT COUNT(*) FROM vip_subscriptions WHERE is_active = 1')
    active_vips = cursor.fetchone()[0]
    
    # Get content statistics
    cursor.execute('SELECT COUNT(*) FROM content_items WHERE content_type = ?', ('browse',))
    browse_content_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM content_items WHERE content_type = ?', ('vip',))
    vip_content_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM teasers')
    teaser_count = cursor.fetchone()[0]
    
    # Get revenue statistics
    cursor.execute('SELECT SUM(total_stars_spent) FROM users')
    total_revenue = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT AVG(total_stars_spent) FROM users WHERE total_stars_spent > 0')
    avg_spent = cursor.fetchone()[0] or 0
    
    # Get top customers
    cursor.execute('''
        SELECT first_name, username, total_stars_spent, interaction_count
        FROM users 
        WHERE total_stars_spent > 0 
        ORDER BY total_stars_spent DESC 
        LIMIT 5
    ''')
    top_customers = cursor.fetchall()
    
    conn.close()
    
    analytics_text = f"""📊 <b>ANALYTICS DASHBOARD</b> 📊

👥 <b>User Statistics:</b>
• Total Users: {total_users:,}
• Active (7 days): {active_users_7d:,}
• Paying Customers: {paying_users:,}
• VIP Members: {active_vips:,}

💰 <b>Revenue:</b>
• Total Revenue: {total_revenue:,} Stars
• Average per Customer: {avg_spent:.0f} Stars
• Conversion Rate: {(paying_users/max(total_users,1)*100):.1f}%

📱 <b>Content:</b>
• Browse Content: {browse_content_count}
• VIP Content: {vip_content_count}
• Teasers: {teaser_count}

🏆 <b>Top Customers:</b>"""
    
    if top_customers:
        for i, (first_name, username, spent, interactions) in enumerate(top_customers):
            safe_name = (first_name or 'N/A').replace('<', '&lt;').replace('>', '&gt;')
            safe_username = (username or 'none').replace('<', '&lt;').replace('>', '&gt;')
            analytics_text += f"\n{i+1}. {safe_name} (@{safe_username}) - {spent} Stars"
    else:
        analytics_text += "\nNo paying customers yet."
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👥 View All Users", callback_data="owner_list_users"))
    markup.add(types.InlineKeyboardButton("💎 VIP Analytics", callback_data="vip_analytics"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Owner Menu", callback_data="owner_help"))
    
    bot.send_message(chat_id, analytics_text, reply_markup=markup, parse_mode='HTML')

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

def get_teasers():
    """Get all teasers from database"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT file_path, file_type, description FROM teasers ORDER BY created_date DESC')
    teasers = cursor.fetchall()
    conn.close()
    return teasers

def get_teasers_with_id():
    """Get all teasers with IDs for management"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, file_path, file_type, description, created_date FROM teasers ORDER BY created_date DESC')
    teasers = cursor.fetchall()
    conn.close()
    return teasers

def delete_teaser(teaser_id):
    """Delete a teaser by ID"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM teasers WHERE id = ?', (teaser_id,))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count > 0

def add_teaser(file_path, file_type, description):
    """Add a teaser to the database"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO teasers (file_path, file_type, description, created_date)
        VALUES (?, ?, ?, ?)
    ''', (file_path, file_type, description, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

def start_vip_upload_session(chat_id, user_id):
    """Start guided VIP content upload session"""
    if user_id != OWNER_ID:
        bot.send_message(chat_id, "❌ Access denied. This is an owner-only command.")
        return
    
    # Initialize VIP upload session
    upload_sessions[OWNER_ID] = {
        'type': 'vip_content',
        'step': 'waiting_for_file',
        'content_type': 'vip',
        'name': None,
        'price': None,
        'description': None,
        'file_path': None,
        'file_type': None
    }
    
    upload_text = """
💎 <b>VIP CONTENT UPLOAD</b> 💎

📤 <b>Step 1: Upload File</b>
Send me the file you want to add as VIP content:

📱 <b>Supported Files:</b>
• Photos (JPG, PNG, etc.)
• Videos (MP4, MOV, AVI)
• Animated GIFs

🎯 <b>Tips:</b>
• Upload high-quality visual content only
• VIP members get FREE access
• Non-VIP users need subscription

📂 Just send the photo/video when ready!
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel VIP Upload", callback_data="cancel_vip_upload"))
    
    bot.send_message(chat_id, upload_text, reply_markup=markup, parse_mode='HTML')

def handle_vip_file_upload(message, file_id, file_type):
    """Handle VIP content file upload"""
    logger.info(f"VIP content handler called - Content type: {message.content_type}, File type: {file_type}")
    session = upload_sessions[OWNER_ID]
    
    # Store file information
    session['file_path'] = file_id
    session['file_type'] = file_type
    session['step'] = 'waiting_for_name'
    
    # Extract filename for smart default based on detected file type
    filename = "custom_content"
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if file_type.lower() == "photo":
        filename = f"vip_photo_{timestamp}"
    elif file_type.lower() == "video":
        filename = f"vip_video_{timestamp}"
    elif file_type.lower() == "gif":
        filename = f"vip_gif_{timestamp}"
    # Documents not supported for VIP content
    
    # Try to extract original filename for better defaults
    if message.content_type == 'video' and hasattr(message.video, 'file_name') and message.video.file_name:
        filename = message.video.file_name.split('.')[0]
    # Document handling removed for VIP content
    
    # Clean filename (replace spaces with underscores, keep alphanumeric)
    safe_filename = ''.join(c if c.isalnum() or c == '_' else '_' for c in filename.lower())
    session['suggested_name'] = safe_filename
    
    # Ask for content name
    name_text = f"""
✅ <b>{file_type.title()} uploaded successfully!</b>

📝 <b>Step 2: Content Name</b>
Choose a unique name for this VIP content:

💡 <b>Suggested:</b> <code>{safe_filename}</code>

🔤 <b>Naming Rules:</b>
• Use letters, numbers, and underscores only
• No spaces allowed
• Must be unique

✍️ Type your custom name or use the buttons below:
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(f"✅ Use: {safe_filename}", callback_data="use_suggested_name"))
    markup.add(types.InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_vip_upload"))
    
    bot.send_message(message.chat.id, name_text, reply_markup=markup, parse_mode='HTML')

def handle_vip_name_input(message):
    """Handle VIP content name input"""
    session = upload_sessions[OWNER_ID]
    name = message.text.strip()
    
    # Validate name
    if not name or ' ' in name or not all(c.isalnum() or c == '_' for c in name):
        bot.send_message(message.chat.id, "❌ Invalid name! Use only letters, numbers, and underscores (no spaces).\nExample: my_vip_content_1")
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
    
    # Store name and move to description step
    session['name'] = name
    session['step'] = 'waiting_for_description'
    
    desc_text = f"""
✅ <b>Name set:</b> {name}

📝 <b>Step 3: Description (Optional)</b>
Add a description that VIP members will see:

💡 <b>Examples:</b>
• "Exclusive behind-the-scenes content"
• "Special VIP-only photo set"
• "Premium video content for VIPs"

✍️ Type your description or skip to use a default:
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("⏭️ Skip Description", callback_data="skip_vip_description"))
    markup.add(types.InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_vip_upload"))
    
    bot.send_message(message.chat.id, desc_text, reply_markup=markup, parse_mode='HTML')

def handle_vip_description_input(message):
    """Handle VIP content description input"""
    session = upload_sessions[OWNER_ID]
    description = message.text.strip()
    
    if description.lower() == 'skip':
        description = f"Exclusive VIP {session.get('file_type', 'content').lower()}"
    
    session['description'] = description
    
    # Set VIP price (VIP content is free for VIP members, but has nominal price for display)
    session['price'] = 0  # VIP content is free for VIP members
    
    # Save VIP content
    save_uploaded_content(session)

def complete_vip_upload_with_defaults(session):
    """Complete VIP upload using default values"""
    # Use suggested name if no custom name provided
    if not session.get('name'):
        session['name'] = session.get('suggested_name', f"vip_content_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
    
    # Use default description if none provided
    if not session.get('description'):
        session['description'] = f"Exclusive VIP {session.get('file_type', 'content').lower()}"
    
    # Set VIP price (free for VIP members)
    session['price'] = 0
    
    # Save VIP content
    save_uploaded_content(session)

# VIP Content Management Functions

def get_vip_content_count():
    """Get count of VIP-only content"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM content_items WHERE content_type = ?', ('vip',))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_vip_content_list():
    """Get all VIP-only content with details"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT name, price_stars, file_path, description, created_date
        FROM content_items 
        WHERE content_type = ? 
        ORDER BY created_date DESC
    ''', ('vip',))
    vip_content = cursor.fetchall()
    conn.close()
    return vip_content

def add_vip_content(name, price_stars, file_path, description):
    """Add new VIP-only content"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO content_items (name, price_stars, file_path, description, created_date, content_type)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (name, price_stars, file_path, description, datetime.datetime.now().isoformat(), 'vip'))
    conn.commit()
    conn.close()

def update_vip_content(name, price_stars, file_path, description):
    """Update existing VIP content"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE content_items 
        SET price_stars = ?, file_path = ?, description = ?
        WHERE name = ? AND content_type = ?
    ''', (price_stars, file_path, description, name, 'vip'))
    updated_count = cursor.rowcount
    conn.commit()
    conn.close()
    return updated_count > 0

def delete_vip_content(name):
    """Delete VIP content by name"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM content_items WHERE name = ? AND content_type = ?', (name, 'vip'))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count > 0

def get_vip_content_by_name(name):
    """Get specific VIP content by name"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT name, price_stars, file_path, description, created_date
        FROM content_items 
        WHERE name = ? AND content_type = ?
    ''', (name, 'vip'))
    content = cursor.fetchone()
    conn.close()
    return content

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
    """Deliver VIP-only content for free to VIP users"""
    # Verify VIP status
    vip_status = check_vip_status(user_id)
    if not vip_status['is_vip']:
        bot.send_message(chat_id, "❌ VIP membership required! Please upgrade to VIP to access this content for free.")
        return
    
    # Get content details - ONLY access VIP content type
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT file_path, description, content_type FROM content_items WHERE name = ? AND content_type = ?', (content_name, 'vip'))
    content = cursor.fetchone()
    conn.close()
    
    if not content:
        bot.send_message(chat_id, f"❌ VIP content '{content_name}' not found. This content may not be available in the VIP library.")
        return
    
    file_path, description, content_type = content
    
    # Verify this is actually VIP content (double-check)
    if content_type != 'vip':
        bot.send_message(chat_id, f"❌ '{content_name}' is not VIP-exclusive content. This content requires individual purchase.")
        return
    
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
• Access special fan-only material

💫 Quick actions:
"""
    
    # Create inline keyboard with main menu buttons
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🌟 VIP Access", callback_data="vip_access"))
    markup.add(types.InlineKeyboardButton("🎬 View Teasers", callback_data="teasers"))
    markup.add(types.InlineKeyboardButton("📂 My Content", callback_data="my_content"))
    markup.add(types.InlineKeyboardButton("💎 VIP Content Library", callback_data="vip_content_catalog"))
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
        # Get teasers from database
        teasers = get_teasers()
        
        if teasers:
            # Send first teaser (most recent)
            file_path, file_type, description = teasers[0]
            
            # Escape HTML characters in description to prevent parsing errors
            safe_description = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            teaser_text = f"""
🎬 <b>FREE TEASER CONTENT</b> 🎬

Here's a little preview of what's waiting for you in my exclusive collection...

{safe_description}

💝 This is just a taste of what I have for my special fans. Want to see more? Check out my full content library!

💡 <b>VIP members get:</b>
• FREE access to ALL content
• Exclusive VIP-only teasers (like this one, but better!)
• Direct personal chat priority
• Monthly bonus content

✨ <i>"The best is yet to come..."</i> ✨
"""
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP for FREE Access", callback_data="vip_access"))
            markup.add(types.InlineKeyboardButton("🛒 Browse Content to Purchase", callback_data="browse_content"))
            
            bot.send_message(message.chat.id, teaser_text, reply_markup=markup, parse_mode='HTML')
            
            # Send the actual teaser media
            try:
                if file_path.startswith('http'):
                    # It's a URL
                    if file_type == 'photo':
                        bot.send_photo(message.chat.id, file_path, caption="🎬 Free Teaser Preview")
                    elif file_type == 'video':
                        bot.send_video(message.chat.id, file_path, caption="🎬 Free Teaser Preview")
                elif len(file_path) > 50 and not file_path.startswith('/'):
                    # It's a Telegram file_id
                    if file_type == 'photo':
                        bot.send_photo(message.chat.id, file_path, caption="🎬 Free Teaser Preview")
                    elif file_type == 'video':
                        bot.send_video(message.chat.id, file_path, caption="🎬 Free Teaser Preview")
                else:
                    # It's a local file path
                    with open(file_path, 'rb') as file:
                        if file_type == 'photo':
                            bot.send_photo(message.chat.id, file, caption="🎬 Free Teaser Preview")
                        elif file_type == 'video':
                            bot.send_video(message.chat.id, file, caption="🎬 Free Teaser Preview")
            except Exception as e:
                logger.error(f"Error sending teaser media: {e}")
                bot.send_message(message.chat.id, "🎬 Teaser content is being prepared...")
            
            return
        
        # No teasers available - show "COMING SOON"
        teaser_text = """
🎬 <b>FREE TEASER CONTENT</b> 🎬

Here's a little preview of what's waiting for you in my exclusive collection...

<b>COMING SOON</b>

💝 This is just a taste of what I have for my special fans. Want to see more? Check out my full content library!

💡 <b>VIP members get:</b>
• FREE access to ALL content
• Exclusive VIP-only teasers (like this one, but better!)
• Direct personal chat priority
• Monthly bonus content

✨ <i>"The best is yet to come..."</i> ✨
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP for FREE Access", callback_data="vip_access"))
        markup.add(types.InlineKeyboardButton("🛒 Browse Content to Purchase", callback_data="browse_content"))
    
    bot.send_message(message.chat.id, teaser_text, reply_markup=markup, parse_mode='HTML')

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
    """Process purchase for specific item - ONLY allows purchases of 'browse' content"""
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    # Only allow purchases of 'browse' content - VIP content is subscription-only
    cursor.execute('SELECT name, price_stars, file_path, description, created_date, content_type FROM content_items WHERE name = ? AND content_type = ?', (item_name, 'browse'))
    item = cursor.fetchone()
    conn.close()
    
    if item:
        name, price_stars, file_path, description, created_date, content_type = item
        
        # Verify this is browse content (double-check)
        if content_type != 'browse':
            bot.send_message(chat_id, f"❌ '{item_name}' is VIP-exclusive content and cannot be purchased individually. Please upgrade to VIP to access this content.")
            return
        
        # Check if user already owns this content
        if check_user_owns_content(user_id, name):
            bot.send_message(chat_id, f"✅ You already own '{name}'! Use 'My Content' to access it again.")
            return
        
        # Create invoice for Telegram Stars
        prices = [types.LabeledPrice(label=name, amount=price_stars)]
        
        bot.send_invoice(
            chat_id=chat_id,
            title=f"Browse Content: {name}",
            description=description,
            invoice_payload=f"content_{name}_{user_id}",
            provider_token=None,  # None for Telegram Stars
            currency='XTR',  # Telegram Stars currency
            prices=prices,
            start_parameter='purchase'
        )
    else:
        # Check if it's VIP content that user is trying to purchase
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name, content_type FROM content_items WHERE name = ?', (item_name,))
        vip_check = cursor.fetchone()
        conn.close()
        
        if vip_check and vip_check[1] == 'vip':
            bot.send_message(chat_id, f"❌ '{item_name}' is VIP-exclusive content and cannot be purchased individually.\n\n💎 Upgrade to VIP subscription for unlimited access to all VIP content!")
        else:
            bot.send_message(chat_id, f"❌ Content '{item_name}' not found in browse catalog. Check /help for available content.")

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
    """Show available BROWSE content for purchase - does not include VIP-only content"""
    # Get user ID if not provided (for callback compatibility)
    if user_id is None:
        # This is a fallback for when called from callback without user_id
        # In practice, we should always pass user_id
        user_id = chat_id  # Assuming direct message context
    
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    # Only show content marked as 'browse' type - not VIP-only content
    cursor.execute('SELECT name, price_stars, description FROM content_items WHERE content_type = ?', ('browse',))
    items = cursor.fetchall()
    conn.close()
    
    if items:
        catalog_text = "🛒 <b>BROWSE CONTENT CATALOG</b> 🛒\n\n"
        catalog_text += "💰 Purchase individual items with Telegram Stars\n"
        catalog_text += "💡 <b>Tip:</b> VIP members get access to exclusive VIP content library!\n\n"
        
        markup = types.InlineKeyboardMarkup()
        
        # Add VIP buttons at the top first
        markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP", callback_data="vip_access"))
        markup.add(types.InlineKeyboardButton("💎 Access VIP Content Library", callback_data="vip_content_catalog"))
        
        for name, price, description in items:
            # Escape HTML special characters to prevent parsing errors
            safe_name = name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            safe_description = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            catalog_text += f"✨ <b>{safe_name}</b>\n"
            
            # Check if user already owns this content
            owns_content = check_user_owns_content(user_id, name)
            
            if owns_content:
                catalog_text += f"✅ <b>OWNED</b> - You already purchased this!\n"
                markup.add(types.InlineKeyboardButton(f"🎁 Access {name} (Owned)", callback_data=f"access_{name}"))
            else:
                catalog_text += f"💰 {price} Stars\n"
                markup.add(types.InlineKeyboardButton(f"⭐ Buy {name} ({price} Stars)", callback_data=f"buy_{name}"))
            
            catalog_text += f"📝 {safe_description}\n\n"
        
        # VIP buttons already added at the top
        
        # Add back button
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
        
        bot.send_message(chat_id, catalog_text, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, "No browse content available right now. Check back soon! 💕\n\n💎 VIP members have access to exclusive VIP content library!")

def show_vip_catalog(chat_id, user_id=None):
    """Show VIP-only content catalog - requires active VIP subscription"""
    # Get user ID if not provided (for callback compatibility)
    if user_id is None:
        user_id = chat_id  # Assuming direct message context
    
    # Check VIP status - must be VIP to access this catalog
    vip_status = check_vip_status(user_id)
    if not vip_status['is_vip']:
        # Not VIP - show upgrade prompt
        no_vip_message = """
💎 <b>VIP CONTENT LIBRARY</b> 💎

🚫 <b>VIP Membership Required!</b>

This exclusive content library is only available to VIP members. Upgrade now to unlock:

✨ <b>VIP-Only Benefits:</b>
• Exclusive VIP content library
• Premium photos and videos
• Behind-the-scenes content
• Direct personal chat access
• Priority responses

🚀 Ready to upgrade and unlock everything?
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP", callback_data="vip_access"))
        markup.add(types.InlineKeyboardButton("🛒 Browse Regular Content", callback_data="browse_content"))
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
        
        bot.send_message(chat_id, no_vip_message, reply_markup=markup, parse_mode='HTML')
        return
    
    # User is VIP - show VIP content library
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    # Only show content marked as 'vip' type
    cursor.execute('SELECT name, price_stars, description FROM content_items WHERE content_type = ?', ('vip',))
    vip_items = cursor.fetchall()
    conn.close()
    
    if vip_items:
        catalog_text = f"💎 <b>VIP EXCLUSIVE CONTENT LIBRARY</b> 💎\n\n"
        catalog_text += f"🎉 Welcome VIP member! Free access to all VIP content!\n"
        catalog_text += f"⏰ Your VIP expires in {vip_status['days_left']} days\n\n"
        catalog_text += f"📚 <b>{len(vip_items)} exclusive VIP items available:</b>\n\n"
        
        markup = types.InlineKeyboardMarkup()
        
        for name, price, description in vip_items:
            # Escape HTML special characters to prevent parsing errors
            safe_name = name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            safe_description = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            catalog_text += f"💎 <b>{safe_name}</b>\n"
            catalog_text += f"🆓 <b>VIP FREE ACCESS</b>\n"
            catalog_text += f"📝 {safe_description}\n\n"
            
            # Add free access button for VIP content
            markup.add(types.InlineKeyboardButton(f"💎 Access {name} (VIP FREE)", callback_data=f"vip_get_{name}"))
        
        # Add navigation buttons
        markup.add(types.InlineKeyboardButton("🛒 Browse Regular Content", callback_data="browse_content"))
        markup.add(types.InlineKeyboardButton(f"🔄 Extend VIP", callback_data="buy_vip"))
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
        
        bot.send_message(chat_id, catalog_text, reply_markup=markup, parse_mode='HTML')
    else:
        # No VIP content available
        no_content_message = f"""
💎 <b>VIP EXCLUSIVE CONTENT LIBRARY</b> 💎

🎉 Welcome VIP member!
⏰ Your VIP expires in {vip_status['days_left']} days

📂 <b>VIP Content Status:</b>
🚧 No exclusive VIP content available yet, but stay tuned!

More premium VIP content is being added regularly. Check back soon for exclusive releases!

💡 <b>Meanwhile:</b> You can still browse and purchase regular content.
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🛒 Browse Regular Content", callback_data="browse_content"))
        markup.add(types.InlineKeyboardButton(f"🔄 Extend VIP", callback_data="buy_vip"))
        markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
        
        bot.send_message(chat_id, no_content_message, reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['help'])
def help_command(message):
    """Handle /help command"""
    add_or_update_user(message.from_user)
    
    help_text = """
😈 **Ready to Play? ELy La Bella** 

**HOW TO USE THIS BOT**

💬 **VIP Exclusive Chat:**
Only VIP members can chat directly with me! Upgrade to unlock personal conversations and priority responses.

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
    # Row 3: My Content and VIP Library
    markup.add(
        types.InlineKeyboardButton("📂 My Content", callback_data="my_content"),
        types.InlineKeyboardButton("💎 VIP Library", callback_data="vip_content_catalog")
    )
    # Row 4: Help refresh
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

@bot.message_handler(content_types=['photo', 'video', 'document', 'animation'], func=lambda message: message.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') not in ['teaser', 'vip_content'] and upload_sessions[OWNER_ID].get('step') == 'waiting_for_file')
def handle_file_upload(message):
    """Handle file uploads for content creation (excludes teaser sessions)"""
    logger.info(f"General content handler triggered - Content type: {message.content_type}, Session: {upload_sessions.get(OWNER_ID, 'None')}")
    
    # Check if we're in any upload session
    if OWNER_ID not in upload_sessions or upload_sessions[OWNER_ID]['step'] != 'waiting_for_file':
        bot.send_message(message.chat.id, "📤 To upload content, start with `/owner_upload` or use VIP upload!")
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
    elif message.content_type == 'animation':
        file_info = bot.get_file(message.animation.file_id)
        file_type = "GIF"
    elif message.content_type == 'document':
        file_info = bot.get_file(message.document.file_id)
        # Check if document is actually a video or gif
        if hasattr(message.document, 'file_name') and message.document.file_name:
            file_name = message.document.file_name.lower()
            if file_name.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
                file_type = "Video"
            elif file_name.endswith(('.gif')):
                file_type = "GIF"
            elif file_name.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                file_type = "Photo"
            else:
                file_type = "Document"
        else:
            # Check MIME type as fallback
            mime_type = getattr(message.document, 'mime_type', '')
            if mime_type.startswith('video/'):
                file_type = "Video"
            elif mime_type == 'image/gif':
                file_type = "GIF"
            elif mime_type.startswith('image/'):
                file_type = "Photo"
            else:
                file_type = "Document"
    
    if file_info:
        # Store file_id instead of download URL to avoid exposing bot token
        file_id = None
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
        elif message.content_type == 'video':
            file_id = message.video.file_id
        elif message.content_type == 'animation':
            file_id = message.animation.file_id
        elif message.content_type == 'document':
            file_id = message.document.file_id
        else:
            bot.send_message(message.chat.id, "❌ Unsupported file type. Please send a photo, video, animation, or document.")
            return
        
        # Check if this is a VIP upload session
        session = upload_sessions[OWNER_ID]
        if session.get('type') == 'vip_content':
            handle_vip_file_upload(message, file_id, file_type)
            return
        
        # Regular content upload
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
    
    # Handle VIP upload flow
    if session.get('type') == 'vip_content':
        if session['step'] == 'waiting_for_name':
            handle_vip_name_input(message)
            return
        elif session['step'] == 'waiting_for_description':
            handle_vip_description_input(message)
            return
    
    # Regular upload flow continues below
    
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
        
        # Check if this is VIP content
        content_type = session.get('content_type', 'browse')
        
        cursor.execute('''
            INSERT INTO content_items (name, price_stars, file_path, description, created_date, content_type)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session['name'], session['price'], session['file_path'], session['description'], datetime.datetime.now().isoformat(), content_type))
        conn.commit()
        conn.close()
        
        # Success message
        if content_type == 'vip':
            success_text = f"""
💎 <b>VIP CONTENT ADDED SUCCESSFULLY!</b> 💎

📦 <b>Name:</b> {session['name']}
💰 <b>Price:</b> {session['price']} Stars
📝 <b>Description:</b> {session['description']}
📁 <b>Type:</b> {session.get('file_type', 'File')} (VIP Exclusive)

🎉 Your VIP content is now live! VIP members get FREE access.
Non-VIP users can purchase VIP subscriptions to access this content.

💡 VIP content generates higher revenue through subscriptions!
"""
        else:
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
        if content_type == 'vip':
            markup.add(types.InlineKeyboardButton("💎 Add More VIP Content", callback_data="start_vip_upload"))
            markup.add(types.InlineKeyboardButton("📊 VIP Dashboard", callback_data="cmd_vip"))
        else:
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

@bot.message_handler(commands=['owner_upload_teaser'])
def owner_upload_teaser(message):
    """Handle /owner_upload_teaser command - guided teaser upload flow"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    # Start teaser upload session
    upload_sessions[OWNER_ID] = {
        'type': 'teaser',
        'step': 'waiting_for_file',
        'data': {}
    }
    
    upload_text = """
🎬 **TEASER UPLOAD** 🎬

📤 Send me the photo or video you want to use as a teaser.

This will be shown to non-VIP users when they use /teaser command.

💡 Tips:
• Upload high-quality images or short videos
• Keep it enticing but not revealing everything
• This builds anticipation for your full content

📱 Just send the file when ready!
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_teaser_upload"))
    
    bot.send_message(message.chat.id, upload_text, reply_markup=markup)

@bot.message_handler(content_types=['photo', 'video', 'animation'], func=lambda message: message.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'vip_content' and upload_sessions[OWNER_ID].get('step') == 'waiting_for_file')
def handle_vip_upload_files(message):
    """Handle VIP content file uploads - photos, videos, and animations only"""
    logger.info(f"VIP upload handler triggered - Content type: {message.content_type}, Session: {upload_sessions.get(OWNER_ID, 'None')}")
    
    # Get file information
    file_id = None
    file_type = None
    
    if message.content_type == 'photo':
        file_id = message.photo[-1].file_id  # Get highest resolution
        file_type = "Photo"
    elif message.content_type == 'video':
        file_id = message.video.file_id
        file_type = "Video"
    elif message.content_type == 'animation':
        file_id = message.animation.file_id
        file_type = "GIF"
    
    if file_id and file_type:
        handle_vip_file_upload(message, file_id, file_type)
    else:
        bot.send_message(message.chat.id, "❌ Unsupported file type for VIP content. Please send photos, videos, or GIFs only.")

@bot.message_handler(content_types=['photo', 'video', 'document', 'animation'], func=lambda message: message.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'teaser' and upload_sessions[OWNER_ID].get('step') == 'waiting_for_file')
def handle_teaser_upload(message):
    """Handle teaser file upload from owner"""
    logger.info(f"Teaser handler triggered - Content type: {message.content_type}, Session: {upload_sessions.get(OWNER_ID, 'None')}")
    session = upload_sessions[OWNER_ID]
    
    if session['step'] == 'waiting_for_file':
        # Store file information
        file_id = None
        file_type = None
        
        if message.photo:
            file_id = message.photo[-1].file_id  # Get highest resolution
            file_type = 'photo'
            session['file_type'] = 'photo'
        elif message.video:
            file_id = message.video.file_id
            file_type = 'video'
            session['file_type'] = 'video'
        elif message.animation:
            file_id = message.animation.file_id
            file_type = 'gif'
            session['file_type'] = 'gif'
        elif message.document:
            file_id = message.document.file_id
            # Detect actual file type for documents
            if hasattr(message.document, 'file_name') and message.document.file_name:
                file_name = message.document.file_name.lower()
                if file_name.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
                    file_type = 'video'
                    session['file_type'] = 'video'
                elif file_name.endswith(('.gif')):
                    file_type = 'gif'
                    session['file_type'] = 'gif'
                elif file_name.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    file_type = 'photo'
                    session['file_type'] = 'photo'
                else:
                    file_type = None  # Unsupported document type
            else:
                # Check MIME type as fallback
                mime_type = getattr(message.document, 'mime_type', '')
                if mime_type.startswith('video/'):
                    file_type = 'video'
                    session['file_type'] = 'video'
                elif mime_type == 'image/gif':
                    file_type = 'gif'
                    session['file_type'] = 'gif'
                elif mime_type.startswith('image/'):
                    file_type = 'photo'
                    session['file_type'] = 'photo'
                else:
                    file_type = None  # Unsupported document type
        
        if file_id and file_type:
            session['file_id'] = file_id
            session['step'] = 'waiting_for_description'
        else:
            bot.send_message(message.chat.id, "❌ Please send a photo, video, or GIF file. Supported formats: JPG, PNG, MP4, GIF, MOV, AVI.")
            return
        
        # Ask for description
        desc_text = f"""
✅ **{file_type.title()} received!**

📝 Now send me a description for this teaser (what fans will see):

Examples:
• "Behind the scenes sneak peek 😉"
• "A little taste of what's coming..."
• "Can't wait to show you the full version 💕"

Type your description:
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⏭ Skip Description", callback_data="skip_teaser_description"))
        markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_teaser_upload"))
        
        bot.send_message(message.chat.id, desc_text, reply_markup=markup)

@bot.message_handler(func=lambda message: message.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'vip_content' and upload_sessions[OWNER_ID].get('step') == 'waiting_for_name')
def handle_vip_name_message(message):
    """Handle VIP content name input from message"""
    handle_vip_name_input(message)

@bot.message_handler(func=lambda message: message.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'vip_content' and upload_sessions[OWNER_ID].get('step') == 'waiting_for_description')
def handle_vip_description_message(message):
    """Handle VIP content description input from message"""
    handle_vip_description_input(message)

@bot.message_handler(func=lambda message: message.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'teaser' and upload_sessions[OWNER_ID].get('step') == 'waiting_for_description')
def handle_teaser_description(message):
    """Handle teaser description from owner"""
    session = upload_sessions[OWNER_ID]
    description = message.text.strip()
    
    if description.lower() == 'skip':
        description = "Exclusive teaser content"
    
    # Save teaser to database
    try:
        add_teaser(session['file_id'], session['file_type'], description)
        
        success_text = f"""
🎉 **TEASER UPLOADED SUCCESSFULLY!** 🎉

🎬 **Type:** {session['file_type'].title()}
📝 **Description:** {description}

Your teaser is now live! Non-VIP users will see this when they use /teaser.

🔄 You can upload multiple teasers - the most recent one will be shown first.
"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎬 Upload Another Teaser", callback_data="start_teaser_upload"))
        markup.add(types.InlineKeyboardButton("👥 View Customers", callback_data="owner_list_users"))
        
        bot.send_message(OWNER_ID, success_text, reply_markup=markup)
        
    except Exception as e:
        bot.send_message(OWNER_ID, f"❌ Error saving teaser: {str(e)}")
    
    # Clear upload session
    if OWNER_ID in upload_sessions:
        del upload_sessions[OWNER_ID]

@bot.message_handler(commands=['owner_list_teasers'])
def owner_list_teasers(message):
    """Handle /owner_list_teasers command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    teasers = get_teasers_with_id()
    
    if not teasers:
        bot.send_message(message.chat.id, "📭 No teasers found. Upload your first teaser with /owner_upload_teaser!")
        return
    
    teaser_list = "🎬 **YOUR TEASERS** 🎬\n\n"
    
    for i, (teaser_id, file_path, file_type, description, created_date) in enumerate(teasers[:10]):
        # Parse creation date
        try:
            date_obj = datetime.datetime.fromisoformat(created_date)
            formatted_date = date_obj.strftime("%Y-%m-%d %H:%M")
        except:
            formatted_date = created_date
        
        teaser_list += f"**ID: {teaser_id}** | {file_type.title()}\n"
        teaser_list += f"📝 {description[:50]}{'...' if len(description) > 50 else ''}\n"
        teaser_list += f"📅 {formatted_date}\n"
        teaser_list += f"🗑️ Delete: `/owner_delete_teaser {teaser_id}`\n\n"
    
    if len(teasers) > 10:
        teaser_list += f"... and {len(teasers) - 10} more teasers\n\n"
    
    teaser_list += "💡 **Tips:**\n"
    teaser_list += "• Most recent teaser is shown first to users\n"
    teaser_list += "• Use `/owner_delete_teaser [ID]` to remove a teaser\n"
    teaser_list += "• Upload new teasers with `/owner_upload_teaser`"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎬 Upload New Teaser", callback_data="start_teaser_upload"))
    markup.add(types.InlineKeyboardButton("🔧 Owner Menu", callback_data="owner_help"))
    
    bot.send_message(message.chat.id, teaser_list, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['owner_delete_teaser'])
def owner_delete_teaser_command(message):
    """Handle /owner_delete_teaser command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    parts = message.text.split(' ', 1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Usage: /owner_delete_teaser [ID]\n\n💡 Use /owner_list_teasers to see teaser IDs.")
        return
    
    try:
        teaser_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid teaser ID. Please provide a valid number.\n\n💡 Use /owner_list_teasers to see teaser IDs.")
        return
    
    success = delete_teaser(teaser_id)
    
    if success:
        bot.send_message(message.chat.id, f"✅ Teaser ID {teaser_id} deleted successfully!")
    else:
        bot.send_message(message.chat.id, f"❌ Teaser ID {teaser_id} not found.")

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

💎 **VIP Management (PRIORITY):**
• `/vip` - VIP content management dashboard
• VIP content is exclusive to VIP subscribers only
• VIP members get FREE access to all VIP content
• Higher revenue potential through monthly subscriptions
• Focus here first for maximum profitability!

📦 **Content Management:**
• `/owner_upload` - Guided file upload (photos/videos/documents)
• `/owner_add_content [name] [price] [url] [description]` - Add content via URL
• `/owner_delete_content [name]` - Remove content

🎬 **Teaser Management:**
• `/owner_upload_teaser` - Upload teasers for non-VIP users
• `/owner_list_teasers` - View all uploaded teasers
• `/owner_delete_teaser [ID]` - Delete teaser by ID

👥 **User Management:**
• `/owner_list_users` - View paying customers only
• `/owner_analytics` - Detailed analytics dashboard
• `/owner_list_vips` - View active VIP subscribers

🤖 **Bot Configuration:**
• `/owner_set_response [key] [text]` - Update Responses
  Keys: greeting, question, compliment, default

ℹ️ **Information:**
• `/owner_help` - Show this help message

💡 **Pro Tips:**
- Start with VIP content for premium user experience
- VIP subscriptions generate more revenue than individual sales
- Upload files directly for automatic Telegram hosting
- Analytics show only paying customers
- Responses support emojis and markdown
- All changes take effect immediately
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # VIP Management - TOP PRIORITY section (keep as-is)
    vip_count = get_vip_content_count()
    markup.add(types.InlineKeyboardButton(f"💎 VIP Dashboard ({vip_count})", callback_data="cmd_vip"))
    
    # Section menus
    markup.add(types.InlineKeyboardButton("📦 Content Management", callback_data="content_management_menu"))
    markup.add(types.InlineKeyboardButton("🎬 Teaser Management", callback_data="teaser_management_menu"))
    markup.add(types.InlineKeyboardButton("👥 User Management", callback_data="user_management_menu"))
    markup.add(types.InlineKeyboardButton("🤖 Bot Configuration", callback_data="bot_config_menu"))
    
    bot.send_message(message.chat.id, help_text, reply_markup=markup, parse_mode='Markdown')

# Section menu functions
def show_content_management_menu(chat_id):
    """Show Content Management section menu"""
    menu_text = """
📦 *CONTENT MANAGEMENT* 📦

Choose an action below to manage your content:
"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📤 Upload Content", callback_data="start_upload"),
        types.InlineKeyboardButton("🔗 Add URL", callback_data="owner_add_content")
    )
    markup.add(
        types.InlineKeyboardButton("✏️ Edit Content", callback_data="show_edit_content_menu"),
        types.InlineKeyboardButton("❌ Delete Content", callback_data="show_delete_content_help")
    )
    markup.add(types.InlineKeyboardButton("🔙 Back to Owner Help", callback_data="owner_help"))
    
    bot.send_message(chat_id, menu_text, reply_markup=markup, parse_mode='Markdown')

def show_edit_content_menu(chat_id):
    """Show Edit Content menu with all content items as buttons"""
    # Get all content items (both browse and VIP types)
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name, price_stars, description, content_type, created_date FROM content_items ORDER BY created_date DESC')
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        empty_text = """
✏️ <b>EDIT CONTENT</b> ✏️

📭 <b>No content found!</b>

Add some content first to be able to edit it.
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📤 Upload Content", callback_data="start_upload"))
        markup.add(types.InlineKeyboardButton("🔙 Back to Content Management", callback_data="content_management_menu"))
        
        bot.send_message(chat_id, empty_text, reply_markup=markup, parse_mode='HTML')
        return
    
    edit_text = f"""
✏️ <b>EDIT CONTENT</b> ✏️

📝 <b>Select content to edit:</b>

Found {len(items)} content item(s). Click on any item below to edit its details:
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for name, price, description, content_type, created_date in items:
        # Format the display text
        try:
            date_obj = datetime.datetime.fromisoformat(created_date)
            formatted_date = date_obj.strftime("%b %d")
        except:
            formatted_date = "N/A"
        
        # Truncate long descriptions
        short_desc = description[:25] + "..." if len(description) > 25 else description
        
        # Add content type indicator
        type_indicator = "💎" if content_type == "vip" else "🛒"
        
        # Create button text with details
        button_text = f"{type_indicator} {name} | {price}⭐ | {formatted_date}"
        
        markup.add(types.InlineKeyboardButton(button_text, callback_data=f"edit_content_{name}"))
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Content Management", callback_data="content_management_menu"))
    
    bot.send_message(chat_id, edit_text, reply_markup=markup, parse_mode='HTML')

def show_delete_content_menu(chat_id):
    """Show Delete Content menu with all content items as buttons"""
    # Get all content items (both browse and VIP types)
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name, price_stars, description, content_type, created_date FROM content_items ORDER BY created_date DESC')
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        empty_text = """
🗑️ <b>DELETE CONTENT</b> 🗑️

📭 <b>No content found!</b>

You don't have any content to delete yet. Add some content first!
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📤 Upload Content", callback_data="start_upload"))
        markup.add(types.InlineKeyboardButton("🔙 Back to Content Management", callback_data="content_management_menu"))
        
        bot.send_message(chat_id, empty_text, reply_markup=markup, parse_mode='HTML')
        return
    
    delete_text = f"""
🗑️ <b>DELETE CONTENT</b> 🗑️

⚠️ <b>Select content to DELETE:</b>

Found {len(items)} content item(s). Click on any item below to permanently delete it:

<b>⚠️ WARNING:</b> This action cannot be undone!
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for name, price, description, content_type, created_date in items:
        # Format the display text
        try:
            date_obj = datetime.datetime.fromisoformat(created_date)
            formatted_date = date_obj.strftime("%b %d")
        except:
            formatted_date = "N/A"
        
        # Truncate long descriptions
        short_desc = description[:25] + "..." if len(description) > 25 else description
        
        # Add content type indicator
        type_indicator = "💎" if content_type == "vip" else "🛒"
        
        # Create button text with details
        button_text = f"🗑️ {type_indicator} {name} | {price}⭐ | {formatted_date}"
        
        markup.add(types.InlineKeyboardButton(button_text, callback_data=f"confirm_delete_{name}"))
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Content Management", callback_data="content_management_menu"))
    
    bot.send_message(chat_id, delete_text, reply_markup=markup, parse_mode='HTML')

def show_content_edit_interface(chat_id, content_name):
    """Show edit interface for a specific content item"""
    # Get content details
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name, price_stars, file_path, description, content_type, created_date FROM content_items WHERE name = ?', (content_name,))
    content = cursor.fetchone()
    conn.close()
    
    if not content:
        bot.send_message(chat_id, f"❌ Content '{content_name}' not found.")
        return
    
    name, price, file_path, description, content_type, created_date = content
    
    # Format creation date
    try:
        date_obj = datetime.datetime.fromisoformat(created_date)
        formatted_date = date_obj.strftime("%Y-%m-%d %H:%M")
    except:
        formatted_date = created_date
    
    # Escape HTML special characters
    safe_name = name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_description = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # Content type indicator
    type_indicator = "💎 VIP" if content_type == "vip" else "🛒 Browse"
    
    edit_text = f"""
✏️ <b>EDIT CONTENT</b> ✏️

📝 <b>Content Details:</b>

<b>Name:</b> {safe_name}
<b>Type:</b> {type_indicator}
<b>Price:</b> {price} Stars
<b>Created:</b> {formatted_date}

<b>Description:</b>
{safe_description}

<b>File Path:</b> {file_path[:50]}{"..." if len(file_path) > 50 else ""}

💡 <b>What would you like to edit?</b>
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(f"💰 Edit Price ({price} Stars)", callback_data=f"edit_price_{name}"))
    markup.add(types.InlineKeyboardButton("📝 Edit Description", callback_data=f"edit_description_{name}"))
    markup.add(types.InlineKeyboardButton("📁 Edit File Path", callback_data=f"edit_file_path_{name}"))
    
    # Add delete option
    markup.add(types.InlineKeyboardButton(f"🗑️ Delete {name}", callback_data=f"confirm_delete_content_{name}"))
    
    # Navigation buttons
    markup.add(types.InlineKeyboardButton("🔙 Back to Edit Menu", callback_data="show_edit_content_menu"))
    markup.add(types.InlineKeyboardButton("🏠 Content Management", callback_data="content_management_menu"))
    
    bot.send_message(chat_id, edit_text, reply_markup=markup, parse_mode='HTML')


def show_teaser_management_menu(chat_id):
    """Show Teaser Management section menu"""
    menu_text = """
🎬 *TEASER MANAGEMENT* 🎬

Choose an action below to manage your teasers:
"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎬 Upload Teaser", callback_data="start_teaser_upload"),
        types.InlineKeyboardButton("📝 Manage Teasers", callback_data="owner_list_teasers")
    )
    markup.add(types.InlineKeyboardButton("❌ Delete Teaser", callback_data="show_delete_teaser_menu"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Owner Help", callback_data="owner_help"))
    
    bot.send_message(chat_id, menu_text, reply_markup=markup, parse_mode='Markdown')

def show_delete_teaser_menu(chat_id):
    """Show Delete Teaser menu with all teasers as buttons"""
    teasers = get_teasers_with_id()
    
    if not teasers:
        empty_text = """
🎬 <b>DELETE TEASER</b> 🎬

📭 <b>No teasers found!</b>

Upload some teasers first to be able to delete them.
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎬 Upload Teaser", callback_data="start_teaser_upload"))
        markup.add(types.InlineKeyboardButton("🔙 Back to Teaser Management", callback_data="teaser_management_menu"))
        
        bot.send_message(chat_id, empty_text, reply_markup=markup, parse_mode='HTML')
        return
    
    delete_text = f"""
🎬 <b>DELETE TEASER</b> 🎬

🗑️ <b>Select teaser to delete:</b>

Found {len(teasers)} teaser(s). Click on any teaser below to delete it:

⚠️ <b>Warning:</b> This action cannot be undone!
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for teaser_id, file_path, file_type, description, created_date in teasers[:10]:
        # Format creation date
        try:
            date_obj = datetime.datetime.fromisoformat(created_date)
            formatted_date = date_obj.strftime("%b %d, %H:%M")
        except:
            formatted_date = "N/A"
        
        # Truncate long descriptions
        short_desc = description[:30] + "..." if len(description) > 30 else description
        
        # Add file type indicator
        type_icon = "📷" if file_type == "photo" else "🎥" if file_type == "video" else "📄"
        
        # Create button text with details
        button_text = f"{type_icon} ID:{teaser_id} | {short_desc} | {formatted_date}"
        
        markup.add(types.InlineKeyboardButton(button_text, callback_data=f"delete_teaser_{teaser_id}"))
    
    if len(teasers) > 10:
        delete_text += f"\n⚠️ <b>Note:</b> Showing first 10 teasers only.\n"
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Teaser Management", callback_data="teaser_management_menu"))
    
    bot.send_message(chat_id, delete_text, reply_markup=markup, parse_mode='HTML')

def show_user_management_menu(chat_id):
    """Show User Management section menu"""
    menu_text = """
👥 *USER MANAGEMENT* 👥

Choose an action below to manage users and analytics:
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("👥 View Customers", callback_data="owner_list_users"))
    markup.add(types.InlineKeyboardButton("📊 Analytics Dashboard", callback_data="owner_analytics"))
    markup.add(types.InlineKeyboardButton("💎 View VIP Members", callback_data="owner_list_vips"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Owner Help", callback_data="owner_help"))
    
    bot.send_message(chat_id, menu_text, reply_markup=markup, parse_mode='Markdown')

def show_bot_config_menu(chat_id):
    """Show Bot Configuration section menu"""
    menu_text = """
🤖 *BOT CONFIGURATION* 🤖

Choose an action below to configure bot settings:
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("✏️ Set Responses", callback_data="show_set_responses_help"))
    markup.add(types.InlineKeyboardButton("⚙️ Other Settings", callback_data="show_other_settings_help"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Owner Help", callback_data="owner_help"))
    
    bot.send_message(chat_id, menu_text, reply_markup=markup, parse_mode='Markdown')

# Owner VIP Management Commands


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

@bot.message_handler(commands=['vip'])
def vip_command(message):
    """Handle /vip command - VIP content management dashboard"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    # Get VIP content statistics
    vip_count = get_vip_content_count()
    vip_price = get_vip_settings('vip_price_stars') or '399'
    vip_duration = get_vip_settings('vip_duration_days') or '30'
    
    # Get VIP subscriber count
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM vip_subscriptions WHERE is_active = 1')
    vip_subscribers = cursor.fetchone()[0]
    conn.close()
    
    dashboard_text = f"""
💎 <b>VIP CONTENT MANAGEMENT DASHBOARD</b> 💎

📊 <b>VIP Statistics:</b>
• VIP Content Items: {vip_count}
• Active VIP Subscribers: {vip_subscribers}
• VIP Price: {vip_price} Stars
• VIP Duration: {vip_duration} days

🎯 <b>VIP Management Options:</b>
Use the buttons below to manage your VIP content and settings.

💡 <b>VIP Strategy:</b>
VIP content generates higher revenue through subscriptions.
VIP members get FREE access to all VIP-only content.
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(f"📦 Add VIP Content", callback_data="vip_add_content"))
    
    if vip_count > 0:
        markup.add(types.InlineKeyboardButton(f"📋 Manage VIP Content ({vip_count})", callback_data="vip_manage_content"))
    
    markup.add(types.InlineKeyboardButton("💎 VIP Members", callback_data="owner_list_vips"))
    markup.add(types.InlineKeyboardButton("⚙️ VIP Settings", callback_data="vip_settings"))
    markup.add(types.InlineKeyboardButton("📊 VIP Analytics", callback_data="vip_analytics"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Owner Help", callback_data="owner_help"))
    
    bot.send_message(message.chat.id, dashboard_text, reply_markup=markup, parse_mode='HTML')

def show_vip_add_content_interface(chat_id):
    """Show interface for adding new VIP content"""
    add_text = """
💎 <b>ADD VIP CONTENT</b> 💎

VIP content is exclusive to subscribers and generates more revenue.

📝 <b>Enhanced Upload Process:</b>
• Upload files directly from your device
• Custom naming with smart defaults  
• Optional descriptions
• Instant VIP content creation

💡 <b>VIP Benefits:</b>
• VIP members get FREE access to all VIP content
• Higher revenue potential through subscriptions  
• Exclusive feeling increases loyalty
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Start VIP Upload", callback_data="start_vip_upload"))
    markup.add(types.InlineKeyboardButton("🔙 Back to VIP Dashboard", callback_data="cmd_vip"))
    
    bot.send_message(chat_id, add_text, reply_markup=markup, parse_mode='HTML')

def show_vip_content_management(chat_id):
    """Show VIP content management interface"""
    vip_content = get_vip_content_list()
    
    if not vip_content:
        empty_text = """
💎 <b>VIP CONTENT MANAGEMENT</b> 💎

📭 <b>No VIP content found!</b>

Add your first VIP content to start earning premium subscription revenue.
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📦 Add VIP Content", callback_data="vip_add_content"))
        markup.add(types.InlineKeyboardButton("🔙 Back to VIP Dashboard", callback_data="cmd_vip"))
        
        bot.send_message(chat_id, empty_text, reply_markup=markup, parse_mode='HTML')
        return
    
    content_text = """
💎 <b>VIP CONTENT MANAGEMENT</b> 💎

🎯 <b>Your VIP Content:</b>

"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for i, (name, price, file_path, description, created_date) in enumerate(vip_content[:10]):
        # Format creation date
        try:
            date_obj = datetime.datetime.fromisoformat(created_date)
            formatted_date = date_obj.strftime("%b %d")
        except:
            formatted_date = "N/A"
        
        # Truncate long descriptions
        short_desc = description[:30] + "..." if len(description) > 30 else description
        
        content_text += f"<b>{i+1}. {name}</b>\n"
        content_text += f"   💰 {price} Stars | 📅 {formatted_date}\n"
        content_text += f"   📝 {short_desc}\n\n"
        
        # Add management buttons
        markup.add(types.InlineKeyboardButton(f"✏️ Edit {name}", callback_data=f"vip_edit_{name}"))
        markup.add(types.InlineKeyboardButton(f"🗑️ Delete {name}", callback_data=f"vip_delete_{name}"))
    
    if len(vip_content) > 10:
        content_text += f"... and {len(vip_content) - 10} more items\n\n"
    
    content_text += "💡 <b>Tip:</b> VIP members get FREE access to all this content!"
    
    markup.add(types.InlineKeyboardButton("➕ Add More VIP Content", callback_data="vip_add_content"))
    markup.add(types.InlineKeyboardButton("🔙 Back to VIP Dashboard", callback_data="cmd_vip"))
    
    bot.send_message(chat_id, content_text, reply_markup=markup, parse_mode='HTML')

def show_vip_settings_interface(chat_id):
    """Show VIP settings management interface"""
    vip_price = get_vip_settings('vip_price_stars') or '399'
    vip_duration = get_vip_settings('vip_duration_days') or '30'
    vip_description = get_vip_settings('vip_description') or 'Premium VIP access'
    
    settings_text = f"""
⚙️ <b>VIP SETTINGS</b> ⚙️

📋 <b>Current VIP Configuration:</b>

💰 <b>Price:</b> {vip_price} Stars
⏰ <b>Duration:</b> {vip_duration} days  
📝 <b>Description:</b> {vip_description}

🔧 <b>To modify settings, use these commands:</b>
• <code>/owner_set_vip_price [amount]</code>
• <code>/owner_set_vip_duration [days]</code>  
• <code>/owner_set_vip_description [text]</code>

💡 <b>Pricing Tips:</b>
• 399 Stars ≈ $4 USD (current default)
• Higher price = more exclusive feeling
• 30-day duration balances value and recurring revenue
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back to VIP Dashboard", callback_data="cmd_vip"))
    
    bot.send_message(chat_id, settings_text, reply_markup=markup, parse_mode='HTML')

def show_vip_analytics(chat_id):
    """Show VIP analytics dashboard"""
    # Get VIP statistics
    conn = sqlite3.connect('content_bot.db')
    cursor = conn.cursor()
    
    # Active VIP subscribers
    cursor.execute('SELECT COUNT(*) FROM vip_subscriptions WHERE is_active = 1')
    active_vips = cursor.fetchone()[0]
    
    # Total VIP revenue (all time)
    vip_price = int(get_vip_settings('vip_price_stars') or 399)
    cursor.execute('SELECT SUM(total_payments) FROM vip_subscriptions')
    total_payments = cursor.fetchone()[0] or 0
    total_vip_revenue = total_payments * vip_price
    
    # Top VIP subscribers
    cursor.execute('''
        SELECT vs.user_id, u.first_name, u.username, vs.total_payments, vs.expiry_date
        FROM vip_subscriptions vs
        LEFT JOIN users u ON vs.user_id = u.user_id
        WHERE vs.is_active = 1
        ORDER BY vs.total_payments DESC
        LIMIT 5
    ''')
    top_vips = cursor.fetchall()
    
    conn.close()
    
    analytics_text = f"""
📊 <b>VIP ANALYTICS DASHBOARD</b> 📊

💎 <b>VIP Statistics:</b>
• Active Subscribers: {active_vips}
• Total VIP Revenue: {total_vip_revenue:,} Stars
• Average Revenue per VIP: {(total_vip_revenue // max(active_vips, 1)):,} Stars

🏆 <b>Top VIP Subscribers:</b>
"""
    
    if top_vips:
        for i, (user_id, first_name, username, payments, expiry) in enumerate(top_vips):
            safe_first_name = (first_name or "N/A").replace('<', '&lt;').replace('>', '&gt;')
            safe_username = username or "none"
            
            # Calculate days left
            try:
                expiry_date = datetime.datetime.fromisoformat(expiry)
                days_left = (expiry_date - datetime.datetime.now()).days
                status = f"{days_left}d left" if days_left > 0 else "Expired"
            except:
                status = "Unknown"
            
            analytics_text += f"{i+1}. {safe_first_name} (@{safe_username})\n"
            analytics_text += f"   💰 {payments} payments | ⏰ {status}\n\n"
    else:
        analytics_text += "No VIP subscribers yet.\n\n"
    
    analytics_text += """
💡 <b>Growth Tips:</b>
• Add more exclusive VIP content
• Promote VIP benefits in teasers
• Offer limited-time VIP discounts
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back to VIP Dashboard", callback_data="cmd_vip"))
    
    bot.send_message(chat_id, analytics_text, reply_markup=markup, parse_mode='HTML')

def handle_vip_content_deletion(chat_id, content_name):
    """Handle VIP content deletion with confirmation"""
    content = get_vip_content_by_name(content_name)
    
    if not content:
        bot.send_message(chat_id, f"❌ VIP content '{content_name}' not found.")
        return
    
    name, price, file_path, description, created_date = content
    
    confirm_text = f"""
⚠️ <b>CONFIRM VIP CONTENT DELETION</b> ⚠️

You are about to delete:
<b>{name}</b>
💰 Price: {price} Stars
📝 {description}

⚠️ <b>Warning:</b> This action cannot be undone!

Are you sure you want to delete this VIP content?
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"🗑️ Yes, Delete {name}", callback_data=f"confirm_vip_delete_{name}"))
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="vip_manage_content"))
    
    bot.send_message(chat_id, confirm_text, reply_markup=markup, parse_mode='HTML')

def show_vip_content_edit_interface(chat_id, content_name):
    """Show VIP content edit interface"""
    content = get_vip_content_by_name(content_name)
    
    if not content:
        bot.send_message(chat_id, f"❌ VIP content '{content_name}' not found.")
        return
    
    name, price, file_path, description, created_date = content
    
    edit_text = f"""
✏️ <b>EDIT VIP CONTENT</b> ✏️

<b>Current Details:</b>
• Name: {name}
• Price: {price} Stars  
• Description: {description}
• File: {file_path[:50]}{'...' if len(file_path) > 50 else ''}

🔧 <b>Edit Commands:</b>
• <code>/owner_edit_vip_price {name} [new_price]</code>
• <code>/owner_edit_vip_description {name} [new_description]</code>
• <code>/owner_edit_vip_file {name} [new_file_path]</code>

💡 <b>Note:</b> Changes take effect immediately for new VIP subscribers.
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🗑️ Delete This Content", callback_data=f"vip_delete_{name}"))
    markup.add(types.InlineKeyboardButton("🔙 Back to VIP Content", callback_data="vip_manage_content"))
    
    bot.send_message(chat_id, edit_text, reply_markup=markup, parse_mode='HTML')

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

@bot.message_handler(commands=['owner_set_vip_price'])
def owner_set_vip_price(message):
    """Handle /owner_set_vip_price command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    try:
        # Parse command: /owner_set_vip_price [price]
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Usage: <code>/owner_set_vip_price [price_in_stars]</code>\nExample: <code>/owner_set_vip_price 399</code>", parse_mode='HTML')
            return
        
        new_price = int(parts[1])
        
        if new_price < 1 or new_price > 2500:
            bot.send_message(message.chat.id, "❌ Price must be between 1 and 2500 Stars.")
            return
        
        # Update VIP price setting
        update_vip_settings('vip_price_stars', str(new_price))
        
        bot.send_message(message.chat.id, f"✅ VIP subscription price updated to {new_price} Stars!")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid price. Please enter a number.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error updating VIP price: {str(e)}")

@bot.message_handler(commands=['owner_set_vip_duration'])
def owner_set_vip_duration(message):
    """Handle /owner_set_vip_duration command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    try:
        # Parse command: /owner_set_vip_duration [days]
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Usage: <code>/owner_set_vip_duration [days]</code>\nExample: <code>/owner_set_vip_duration 30</code>", parse_mode='HTML')
            return
        
        new_duration = int(parts[1])
        
        if new_duration < 1 or new_duration > 365:
            bot.send_message(message.chat.id, "❌ Duration must be between 1 and 365 days.")
            return
        
        # Update VIP duration setting
        update_vip_settings('vip_duration_days', str(new_duration))
        
        bot.send_message(message.chat.id, f"✅ VIP subscription duration updated to {new_duration} days!")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid duration. Please enter a number.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error updating VIP duration: {str(e)}")

@bot.message_handler(commands=['owner_set_vip_description'])
def owner_set_vip_description(message):
    """Handle /owner_set_vip_description command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    try:
        # Parse command: /owner_set_vip_description [description]
        parts = message.text.split(' ', 1)
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Usage: <code>/owner_set_vip_description [description]</code>\nExample: <code>/owner_set_vip_description Premium VIP access with exclusive content</code>", parse_mode='HTML')
            return
        
        new_description = parts[1].strip()
        
        if len(new_description) < 5 or len(new_description) > 200:
            bot.send_message(message.chat.id, "❌ Description must be between 5 and 200 characters.")
            return
        
        # Update VIP description setting
        update_vip_settings('vip_description', new_description)
        
        bot.send_message(message.chat.id, f"✅ VIP description updated to: {new_description}")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error updating VIP description: {str(e)}")

@bot.message_handler(commands=['owner_edit_price'])
def owner_edit_price(message):
    """Handle /owner_edit_price command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    try:
        # Parse command: /owner_edit_price [content_name] [new_price]
        parts = message.text.split()
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Usage: <code>/owner_edit_price [content_name] [new_price]</code>\nExample: <code>/owner_edit_price photo_set_1 75</code>", parse_mode='HTML')
            return
        
        content_name = parts[1]
        new_price = int(parts[2])
        
        if new_price < 0 or new_price > 2500:
            bot.send_message(message.chat.id, "❌ Price must be between 0 and 2500 Stars.")
            return
        
        # Update content price
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE content_items SET price_stars = ? WHERE name = ?', (new_price, content_name))
        updated_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if updated_count > 0:
            bot.send_message(message.chat.id, f"✅ Price for '{content_name}' updated to {new_price} Stars!")
        else:
            bot.send_message(message.chat.id, f"❌ Content '{content_name}' not found.")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid price. Please enter a number.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error updating price: {str(e)}")

@bot.message_handler(commands=['owner_edit_description'])
def owner_edit_description(message):
    """Handle /owner_edit_description command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    try:
        # Parse command: /owner_edit_description [content_name] [new_description]
        parts = message.text.split(' ', 2)
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Usage: <code>/owner_edit_description [content_name] [new_description]</code>\nExample: <code>/owner_edit_description photo_set_1 Amazing exclusive photo collection</code>", parse_mode='HTML')
            return
        
        content_name = parts[1]
        new_description = parts[2].strip()
        
        if len(new_description) < 5 or len(new_description) > 500:
            bot.send_message(message.chat.id, "❌ Description must be between 5 and 500 characters.")
            return
        
        # Update content description
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE content_items SET description = ? WHERE name = ?', (new_description, content_name))
        updated_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if updated_count > 0:
            bot.send_message(message.chat.id, f"✅ Description for '{content_name}' updated successfully!")
        else:
            bot.send_message(message.chat.id, f"❌ Content '{content_name}' not found.")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error updating description: {str(e)}")

@bot.message_handler(commands=['owner_edit_file_path'])
def owner_edit_file_path(message):
    """Handle /owner_edit_file_path command"""
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Access denied. This is an owner-only command.")
        return
    
    try:
        # Parse command: /owner_edit_file_path [content_name] [new_file_path]
        parts = message.text.split(' ', 2)
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Usage: <code>/owner_edit_file_path [content_name] [new_file_path]</code>\nExample: <code>/owner_edit_file_path photo_set_1 https://example.com/newphoto.jpg</code>", parse_mode='HTML')
            return
        
        content_name = parts[1]
        new_file_path = parts[2].strip()
        
        if len(new_file_path) < 5:
            bot.send_message(message.chat.id, "❌ File path too short. Please provide a valid file path or URL.")
            return
        
        # Update content file path
        conn = sqlite3.connect('content_bot.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE content_items SET file_path = ? WHERE name = ?', (new_file_path, content_name))
        updated_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if updated_count > 0:
            bot.send_message(message.chat.id, f"✅ File path for '{content_name}' updated successfully!")
        else:
            bot.send_message(message.chat.id, f"❌ Content '{content_name}' not found.")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error updating file path: {str(e)}")

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
    elif call.data == "vip_content_catalog":
        show_vip_catalog(call.message.chat.id, call.from_user.id)
    elif call.data == "my_content":
        show_my_content(call.message.chat.id, call.from_user.id)
    elif call.data == "ask_question":
        # Check if user has VIP or has purchased content
        user_id = call.from_user.id
        vip_status = check_vip_status(user_id)
        purchased_content = get_user_purchased_content(user_id)
        
        # User qualifies if they have VIP or have bought content
        user_qualifies = vip_status['is_vip'] or len(purchased_content) > 0
        
        if user_qualifies:
            # Show contact info for qualifying users
            contact_message = """
💬 **Direct Contact Available** 💬

🎉 Congratulations! As a valued customer, you can now contact me directly:

👤 **Contact me:** @elylabella_official

💕 I personally read and respond to all messages from my supporters!

🌟 **What you can expect:**
• Personal responses from me
• Behind-the-scenes conversations
• Priority attention to your messages
• Exclusive chat access

✨ Thank you for being an amazing supporter!
"""
            markup = types.InlineKeyboardMarkup()
            # Create URL button for direct contact
            markup.add(types.InlineKeyboardButton("💬 Message @elylabella_official", url="https://t.me/elylabella_official"))
            markup.add(types.InlineKeyboardButton("🛒 Browse More Content", callback_data="browse_content"))
            markup.add(types.InlineKeyboardButton("🏠 Back to Main", callback_data="cmd_start"))
            
            bot.send_message(call.message.chat.id, contact_message, reply_markup=markup)
        else:
            # Show VIP upgrade message for non-qualifying users
            fomo_message = """
🚫 **Chat Access Restricted** 🚫

💎 This feature is exclusive to VIP members and content purchasers only!

🌟 **You're missing out on:**
• Direct personal conversations with me
• Priority responses to all your messages  
• Exclusive behind-the-scenes chat access
• Personal attention and custom interactions

💰 Upgrade to VIP or purchase content to unlock direct chat access!
"""
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP Now", callback_data="vip_access"))
            markup.add(types.InlineKeyboardButton("🛒 Browse Content Instead", callback_data="browse_content"))
            
            bot.send_message(call.message.chat.id, fomo_message, reply_markup=markup)
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
    elif call.data.startswith("access_"):
        item_name = call.data.replace("access_", "")
        deliver_owned_content(call.message.chat.id, call.from_user.id, item_name)
    elif call.data == "owner_list_teasers":
        if call.from_user.id != OWNER_ID:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
        else:
            # Create fake message object for the owner_list_teasers function
            fake_message = type('obj', (object,), {
                'chat': call.message.chat,
                'from_user': call.from_user,
                'message_id': call.message.message_id
            })
            owner_list_teasers(fake_message)
    elif call.data == "owner_help":
        if call.from_user.id != OWNER_ID:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
        else:
            # Create fake message object for the owner_help function
            fake_message = type('obj', (object,), {
                'chat': call.message.chat,
                'from_user': call.from_user,
                'message_id': call.message.message_id
            })
            owner_help(fake_message)
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
    elif call.data == "start_teaser_upload":
        if call.from_user.id == OWNER_ID:
            # Create a fake message object for the teaser upload function
            fake_message = type('obj', (object,), {
                'chat': call.message.chat,
                'from_user': call.from_user,
                'text': '/owner_upload_teaser'
            })
            owner_upload_teaser(fake_message)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "cancel_teaser_upload":
        if call.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'teaser':
            del upload_sessions[OWNER_ID]
            bot.send_message(call.message.chat.id, "❌ Teaser upload cancelled.")
        else:
            bot.send_message(call.message.chat.id, "❌ No active teaser upload session.")
    elif call.data == "skip_teaser_description":
        if call.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'teaser':
            session = upload_sessions[OWNER_ID]
            if session['step'] == 'waiting_for_description':
                session['description'] = "Exclusive teaser content"
                # Save teaser to database
                try:
                    add_teaser(session['file_id'], session['file_type'], session['description'])
                    
                    success_text = f"""
🎉 **TEASER UPLOADED SUCCESSFULLY!** 🎉

🎬 **Type:** {session['file_type'].title()}
📝 **Description:** {session['description']}

Your teaser is now live! Non-VIP users will see this when they use /teaser.

🔄 You can upload multiple teasers - the most recent one will be shown first.
"""
                    
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🎬 Upload Another Teaser", callback_data="start_teaser_upload"))
                    markup.add(types.InlineKeyboardButton("👥 View Customers", callback_data="owner_list_users"))
                    
                    bot.send_message(call.message.chat.id, success_text, reply_markup=markup)
                    
                    # Clear upload session
                    del upload_sessions[OWNER_ID]
                    
                except Exception as e:
                    bot.send_message(call.message.chat.id, f"❌ Error saving teaser: {str(e)}")
                    if OWNER_ID in upload_sessions:
                        del upload_sessions[OWNER_ID]
            else:
                bot.send_message(call.message.chat.id, "❌ Invalid step for skipping description.")
        else:
            bot.send_message(call.message.chat.id, "❌ No active teaser upload session.")
    # VIP Management callbacks
    elif call.data == "cmd_vip":
        if call.from_user.id == OWNER_ID:
            # Create fake message object for the vip_command function
            fake_message = type('obj', (object,), {
                'chat': call.message.chat,
                'from_user': call.from_user,
                'text': '/vip'
            })
            vip_command(fake_message)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "owner_list_vips":
        if call.from_user.id == OWNER_ID:
            # Create fake message object for the owner_list_vips function
            fake_message = type('obj', (object,), {
                'chat': call.message.chat,
                'from_user': call.from_user,
                'text': '/owner_list_vips'
            })
            owner_list_vips(fake_message)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "vip_add_content":
        if call.from_user.id == OWNER_ID:
            show_vip_add_content_interface(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "start_vip_upload":
        if call.from_user.id == OWNER_ID:
            start_vip_upload_session(call.message.chat.id, call.from_user.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "cancel_vip_upload":
        if call.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'vip_content':
            del upload_sessions[OWNER_ID]
            bot.send_message(call.message.chat.id, "❌ VIP upload cancelled.")
        else:
            bot.send_message(call.message.chat.id, "❌ No active VIP upload session.")
    elif call.data == "use_suggested_name":
        if call.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'vip_content':
            session = upload_sessions[OWNER_ID]
            if session['step'] == 'waiting_for_name' and 'suggested_name' in session:
                # Check if suggested name is unique
                suggested_name = session['suggested_name']
                
                # Check if name already exists
                conn = sqlite3.connect('content_bot.db')
                cursor = conn.cursor()
                cursor.execute('SELECT name FROM content_items WHERE name = ?', (suggested_name,))
                existing = cursor.fetchone()
                conn.close()
                
                if existing:
                    # Make name unique by adding timestamp
                    timestamp = datetime.datetime.now().strftime('%H%M%S')
                    suggested_name = f"{suggested_name}_{timestamp}"
                
                session['name'] = suggested_name
                session['step'] = 'waiting_for_description'
                
                desc_text = f"""
✅ <b>Name set:</b> {suggested_name}

📝 <b>Step 3: Description (Optional)</b>
Add a description that VIP members will see:

💡 <b>Examples:</b>
• "Exclusive behind-the-scenes content"
• "Special VIP-only photo set"
• "Premium video content for VIPs"

✏️ Type your description or skip to use a default:
"""
                
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("⏭️ Skip Description", callback_data="skip_vip_description"))
                markup.add(types.InlineKeyboardButton("❌ Cancel Upload", callback_data="cancel_vip_upload"))
                
                bot.send_message(call.message.chat.id, desc_text, reply_markup=markup, parse_mode='HTML')
            else:
                bot.send_message(call.message.chat.id, "❌ Invalid step for using suggested name.")
        else:
            bot.send_message(call.message.chat.id, "❌ No active VIP upload session.")
    elif call.data == "skip_vip_description":
        if call.from_user.id == OWNER_ID and OWNER_ID in upload_sessions and upload_sessions[OWNER_ID].get('type') == 'vip_content':
            session = upload_sessions[OWNER_ID]
            if session['step'] == 'waiting_for_description':
                session['description'] = f"Exclusive VIP {session.get('file_type', 'content').lower()}"
                session['price'] = 0  # VIP content is free for VIP members
                save_uploaded_content(session)
            else:
                bot.send_message(call.message.chat.id, "❌ Invalid step for skipping description.")
        else:
            bot.send_message(call.message.chat.id, "❌ No active VIP upload session.")
    elif call.data == "vip_manage_content":
        if call.from_user.id == OWNER_ID:
            show_vip_content_management(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "vip_settings":
        if call.from_user.id == OWNER_ID:
            show_vip_settings_interface(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "vip_analytics":
        if call.from_user.id == OWNER_ID:
            show_vip_analytics(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("vip_delete_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("vip_delete_", "")
            handle_vip_content_deletion(call.message.chat.id, content_name)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("vip_edit_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("vip_edit_", "")
            show_vip_content_edit_interface(call.message.chat.id, content_name)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("confirm_vip_delete_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("confirm_vip_delete_", "")
            # Actually delete the VIP content
            if delete_vip_content(content_name):
                bot.send_message(call.message.chat.id, f"✅ VIP content '{content_name}' deleted successfully!")
                # Go back to VIP content management
                show_vip_content_management(call.message.chat.id)
            else:
                bot.send_message(call.message.chat.id, f"❌ Failed to delete VIP content '{content_name}'.")
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    
    # Edit Content handlers
    elif call.data == "show_edit_content_menu":
        if call.from_user.id == OWNER_ID:
            show_edit_content_menu(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("edit_content_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("edit_content_", "")
            show_content_edit_interface(call.message.chat.id, content_name)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("confirm_delete_content_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("confirm_delete_content_", "")
            # Delete the content
            conn = sqlite3.connect('content_bot.db')
            cursor = conn.cursor()
            cursor.execute('DELETE FROM content_items WHERE name = ?', (content_name,))
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted_count > 0:
                bot.send_message(call.message.chat.id, f"✅ Content '{content_name}' deleted successfully!")
                # Go back to edit content menu
                show_edit_content_menu(call.message.chat.id)
            else:
                bot.send_message(call.message.chat.id, f"❌ Failed to delete content '{content_name}'.")
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("confirm_delete_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("confirm_delete_", "")
            # Delete the content
            conn = sqlite3.connect('content_bot.db')
            cursor = conn.cursor()
            cursor.execute('DELETE FROM content_items WHERE name = ?', (content_name,))
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted_count > 0:
                bot.send_message(call.message.chat.id, f"✅ Content '{content_name}' deleted successfully!")
                # Go back to delete content menu to show updated list
                show_delete_content_menu(call.message.chat.id)
            else:
                bot.send_message(call.message.chat.id, f"❌ Failed to delete content '{content_name}'.")
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    
    # Edit Content field handlers
    elif call.data.startswith("edit_price_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("edit_price_", "")
            bot.send_message(call.message.chat.id, f"💰 To edit price for '{content_name}', use:\n<code>/owner_edit_price {content_name} [new_price]</code>\n\nExample: <code>/owner_edit_price {content_name} 50</code>", parse_mode='HTML')
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("edit_description_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("edit_description_", "")
            bot.send_message(call.message.chat.id, f"📝 To edit description for '{content_name}', use:\n<code>/owner_edit_description {content_name} [new_description]</code>\n\nExample: <code>/owner_edit_description {content_name} Amazing exclusive content!</code>", parse_mode='HTML')
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("edit_file_path_"):
        if call.from_user.id == OWNER_ID:
            content_name = call.data.replace("edit_file_path_", "")
            bot.send_message(call.message.chat.id, f"📁 To edit file path for '{content_name}', use:\n<code>/owner_edit_file_path {content_name} [new_file_path]</code>\n\nExample: <code>/owner_edit_file_path {content_name} https://example.com/newfile.jpg</code>", parse_mode='HTML')
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    
    # Analytics Dashboard handler
    elif call.data == "analytics_dashboard":
        if call.from_user.id == OWNER_ID:
            show_analytics_dashboard(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    
    # Section menu handlers
    elif call.data == "content_management_menu":
        if call.from_user.id == OWNER_ID:
            show_content_management_menu(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "teaser_management_menu":
        if call.from_user.id == OWNER_ID:
            show_teaser_management_menu(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "user_management_menu":
        if call.from_user.id == OWNER_ID:
            show_user_management_menu(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "bot_config_menu":
        if call.from_user.id == OWNER_ID:
            show_bot_config_menu(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    
    # Helper callbacks for section menus
    elif call.data == "show_delete_content_help":
        if call.from_user.id == OWNER_ID:
            show_delete_content_menu(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "show_delete_teaser_menu":
        if call.from_user.id == OWNER_ID:
            show_delete_teaser_menu(call.message.chat.id)
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data.startswith("delete_teaser_"):
        if call.from_user.id == OWNER_ID:
            teaser_id = int(call.data.replace("delete_teaser_", ""))
            # Delete the teaser
            success = delete_teaser(teaser_id)
            
            if success:
                bot.send_message(call.message.chat.id, f"✅ Teaser ID {teaser_id} deleted successfully!")
                # Go back to delete teaser menu
                show_delete_teaser_menu(call.message.chat.id)
            else:
                bot.send_message(call.message.chat.id, f"❌ Teaser ID {teaser_id} not found.")
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "show_set_responses_help":
        if call.from_user.id == OWNER_ID:
            bot.send_message(call.message.chat.id, "✏️ To set AI responses, use: `/owner_set_response [key] [text]`\n\n🔤 Valid keys: greeting, question, compliment, default\n\n💡 Example: `/owner_set_response greeting Hello there! 😊`")
        else:
            bot.send_message(call.message.chat.id, "❌ Access denied. This is an owner-only command.")
    elif call.data == "show_other_settings_help":
        if call.from_user.id == OWNER_ID:
            bot.send_message(call.message.chat.id, "⚙️ Other available settings:\n\n• `/owner_set_vip_price [stars]` - Set VIP subscription price\n• Use the 💎 VIP Dashboard for VIP settings\n• Most other settings are in the VIP dashboard")
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
            # Format date as requested
            today = datetime.datetime.now()
            formatted_date = today.strftime("%b %d").upper()
            
            # Create enhanced notification with clickable name
            owner_notification = f"""
💎 **NEW VIP SUBSCRIPTION!** 💎

👤 [{message.from_user.first_name}](tg://user?id={user_id})
🆔 User ID: {user_id}
📅 Date: {formatted_date}
💰 Amount: {payment.total_amount} Stars
⏰ Duration: {duration_days} days

💬 Click the name to message them directly!
"""
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error sending owner notification: {e}")
            # Fallback notification
            try:
                bot.send_message(OWNER_ID, f"💎 NEW VIP SUBSCRIPTION!\n👤 {message.from_user.first_name}\n💰 {payment.total_amount} Stars\n🆔 ID: {user_id}")
            except:
                pass
            
    elif len(payload_parts) >= 3 and payload_parts[0] == 'content':
        content_name = payload_parts[1]
        user_id = int(payload_parts[2])
        
        # Update user's total spent
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET total_stars_spent = total_stars_spent + ? WHERE user_id = ?', 
                      (payment.total_amount, user_id))
        
        # Record the purchase for permanent access (use INSERT OR IGNORE to prevent duplicates)
        purchase_date = datetime.datetime.now().isoformat()
        cursor.execute('''
            INSERT OR IGNORE INTO user_purchases (user_id, content_name, purchase_date, price_paid)
            VALUES (?, ?, ?, ?)
        ''', (user_id, content_name, purchase_date, payment.total_amount))
        
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
    """Run the bot with infinity polling and better error handling"""
    import time
    
    max_retries = 5
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Starting bot polling (attempt {attempt + 1}/{max_retries})...")
            bot.infinity_polling(
                none_stop=True,
                timeout=30,  # 30 second timeout for requests
                skip_pending=True  # Skip pending messages on restart
            )
            break  # If we reach here, polling started successfully
            
        except Exception as e:
            logger.error(f"Bot polling failed (attempt {attempt + 1}/{max_retries}): {str(e)}")
            
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error("Max retries reached. Bot polling could not be started.")
                # Don't exit, let Flask continue running for health checks
                break

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