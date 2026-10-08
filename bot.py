import io
import time
import asyncio
import logging
import datetime
import pyotp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import config
import database
import checker

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# State flag for stock scanner
is_scanner_running = False

# --- Helper Functions ---

def is_admin(user_id: int) -> bool:
    """Checks if the user is authorized. If ADMIN_ID is 0, auto-authorizes the first user."""
    if config.ADMIN_ID == 0:
        return True
    return user_id == config.ADMIN_ID

def get_live_totp(secret: str):
    """Calculates live OTP and remaining seconds for a given 2FA secret."""
    if not secret:
        return "NO_2FA_SECRET", 0
    try:
        totp = pyotp.TOTP(secret.strip().replace(" ", ""))
        code = totp.now()
        rem = 30 - (int(time.time()) % 30)
        return code, rem
    except Exception as e:
        logger.error(f"Error generating TOTP: {e}")
        return "INVALID_KEY", 0

def build_main_menu_keyboard():
    """Generates the main interactive dashboard keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("🎯 Get 1 Account", callback_data="menu_get_account"),
            InlineKeyboardButton("📦 Bulk Export (.txt)", callback_data="menu_bulk_export")
        ],
        [
            InlineKeyboardButton("📊 Refresh Stats", callback_data="menu_stats"),
            InlineKeyboardButton("📜 Last 10 History", callback_data="menu_history")
        ],
        [
            InlineKeyboardButton("🔍 Live Scan Stock (Proxy)", callback_data="menu_live_scan"),
            InlineKeyboardButton("🔴 Suspended Accounts", callback_data="menu_suspended")
        ],
        [
            InlineKeyboardButton("📥 Import .txt File", callback_data="menu_import_info"),
            InlineKeyboardButton("💾 Full DB Backup", callback_data="menu_backup")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_stats_message():
    """Formats current inventory statistics."""
    stats = database.get_stats()
    avail = stats["available"]
    
    text = (
        "🚀 **Instagram & 2FA Accounts Manager**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 **Available Stock (Ready to use):**\n"
        f"  • 🔵 FB Fixed: `{avail.get('FB_FIXED', 0)}` accounts\n"
        f"  • 🟢 Fresh:    `{avail.get('FRESH', 0)}` accounts\n"
        f"  • ⚪ Not Fixed: `{avail.get('NOT_FIXED', 0)}` accounts\n"
        f"  ────────────────────\n"
        f"  👉 **Total Ready Stock: `{avail.get('TOTAL', 0)}` accounts**\n\n"
        "📊 **Lifetime History:**\n"
        f"  • 📦 Dispatched / Used: `{stats['consumed']}` accounts\n"
        f"  • 🔴 Suspended (Dead):  `{stats['suspended']}` accounts\n"
        f"  • 📁 Total in DB:       `{stats['total_all']}` accounts\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Tip: Send any @username to get instant Live 2FA OTP!*"
    )
    return text

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ **Access Denied.** This is a private management bot.")
        return

    # If ADMIN_ID was not configured in .env, announce it
    if config.ADMIN_ID == 0:
        logger.info(f"Admin connected with Telegram ID: {user.id}")

    text = format_stats_message()
    await update.message.reply_text(
        text,
        reply_markup=build_main_menu_keyboard(),
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /help command."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    help_text = (
        "📖 **Bot Commands & Shortcuts:**\n\n"
        "• `/start` or `/menu` - Open Main Dashboard\n"
        "• `/history` - View last 10 dispatched accounts (with 2FA Keys)\n"
        "• `/scan` - Live scan all stock accounts via Turnoxy proxy\n"
        "• `/backup` - Download complete database as .txt file\n"
        "• **Send Username:** Send any username (e.g. `user_123` or `@user_123`) to get instant 2FA OTP & credentials!\n"
        "• **Upload File:** Drag and drop `saved_accounts.txt` anytime to import new accounts!\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /history command: displays recently consumed accounts with 2FA Keys."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    recent = database.get_recent_consumed(limit=10)
    if not recent:
        await update.message.reply_text("📂 No consumed accounts found yet.", parse_mode="Markdown")
        return

    lines = ["📜 **Recently Dispatched Accounts (Last 10):**\n━━━━━━━━━━━━━━━━━━━━━━"]
    for i, acc in enumerate(recent, 1):
        ts = acc['consumed_at'] or acc['timestamp'] or "N/A"
        clean_cat = acc['category'].replace('_', ' ')
        lines.append(
            f"{i}. `@{acc['username']}` | 🕒 `{ts}`\n"
            f"   🔑 Pass: `{acc['password']}`\n"
            f"   🛡️ 2FA Key: `{acc['two_fa_secret'] or 'N/A'}`\n"
            f"   🏷️ Cat: `{clean_cat}`"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n💡 _Send any username above to get fresh 2FA OTP!_")

    keyboard = [
        [InlineKeyboardButton("📥 Export History (.txt)", callback_data="export_history_txt")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="menu_stats")]
    ]
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# --- Interactive Callback Handlers ---

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main router for inline keyboard callback queries."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not is_admin(user.id):
        await query.answer("⛔ Access Denied.", show_alert=True)
        return

    data = query.data

    if data == "menu_stats":
        text = format_stats_message()
        await query.edit_message_text(text, reply_markup=build_main_menu_keyboard(), parse_mode="Markdown")

    elif data == "menu_get_account":
        # Step 1: Select Sort Order
        keyboard = [
            [InlineKeyboardButton("⏳ Oldest First (Aged IDs)", callback_data="get_sort:oldest")],
            [InlineKeyboardButton("⚡ Newest First (Fresh IDs)", callback_data="get_sort:newest")],
            [InlineKeyboardButton("🎲 Random Pick", callback_data="get_sort:random")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_stats")]
        ]
        await query.edit_message_text(
            "🎯 **Step 1: Choose Sorting Priority:**\n\n"
            "• **Oldest First:** Uses aged timestamp accounts first (FIFO)\n"
            "• **Newest First:** Uses recently added accounts first\n"
            "• **Random:** Picks any available account",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("get_sort:"):
        sort_mode = data.split(":")[1]
        context.user_data["sort_mode"] = sort_mode

        # Step 2: Select Category
        keyboard = [
            [
                InlineKeyboardButton("🔵 FB Fixed", callback_data="get_cat:FB_FIXED"),
                InlineKeyboardButton("🟢 Fresh", callback_data="get_cat:FRESH")
            ],
            [
                InlineKeyboardButton("⚪ Not Fixed", callback_data="get_cat:NOT_FIXED"),
                InlineKeyboardButton("🌐 Any Category", callback_data="get_cat:ALL")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_get_account")]
        ]
        await query.edit_message_text(
            f"🎯 **Step 2: Choose Account Category:**\n(Sort Mode: `{sort_mode.upper()}`)",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("get_cat:"):
        category = data.split(":")[1]
        sort_mode = context.user_data.get("sort_mode", "oldest")
        await process_single_account_dispatch(query, context, category, sort_mode)

    elif data.startswith("refresh_otp:"):
        username = data.split(":")[1]
        await handle_refresh_otp(query, username)

    elif data.startswith("copy_key:"):
        username = data.split(":")[1]
        acc = database.get_account_by_username(username)
        if acc and acc["two_fa_secret"]:
            await query.answer(f"2FA Key: {acc['two_fa_secret']}", show_alert=True)
        else:
            await query.answer("No 2FA secret found for this account.", show_alert=True)

    elif data == "menu_import_info":
        await query.edit_message_text(
            "📥 **How to Import New Accounts:**\n\n"
            "Simply send or upload your `saved_accounts.txt` file directly in this chat!\n\n"
            "✨ **Features:**\n"
            "• Existing accounts in the DB will be **automatically ignored** (Zero duplicates).\n"
            "• Only brand-new accounts will be added.\n"
            "• Instant category-wise report will be generated.\n\n"
            "Send the `.txt` file now!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_stats")]]),
            parse_mode="Markdown"
        )

    elif data == "menu_bulk_export":
        keyboard = [
            [
                InlineKeyboardButton("🔵 FB Fixed", callback_data="bulk_cat:FB_FIXED"),
                InlineKeyboardButton("🟢 Fresh", callback_data="bulk_cat:FRESH")
            ],
            [
                InlineKeyboardButton("⚪ Not Fixed", callback_data="bulk_cat:NOT_FIXED"),
                InlineKeyboardButton("🌐 Any Category", callback_data="bulk_cat:ALL")
            ],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_stats")]
        ]
        await query.edit_message_text(
            "📦 **Bulk Export (.txt Generator)**\n\nSelect the category you want to export:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("bulk_cat:"):
        cat = data.split(":")[1]
        context.user_data["bulk_cat"] = cat
        keyboard = [
            [
                InlineKeyboardButton("5", callback_data="bulk_qty:5"),
                InlineKeyboardButton("10", callback_data="bulk_qty:10"),
                InlineKeyboardButton("25", callback_data="bulk_qty:25"),
                InlineKeyboardButton("50", callback_data="bulk_qty:50")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_bulk_export")]
        ]
        await query.edit_message_text(
            f"📦 **Category:** `{cat}`\n\nChoose how many accounts to export:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("bulk_qty:"):
        qty = int(data.split(":")[1])
        cat = context.user_data.get("bulk_cat", "ALL")
        await process_bulk_export(query, context, cat, qty)

    elif data == "menu_suspended":
        suspended_list = database.get_suspended_accounts()
        count = len(suspended_list)
        keyboard = [
            [InlineKeyboardButton("🗑️ Bulk Delete All Suspended", callback_data="action_delete_suspended")],
            [InlineKeyboardButton("🔄 Re-Verify (Reset to Available)", callback_data="action_reset_suspended")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_stats")]
        ]
        await query.edit_message_text(
            f"🔴 **Suspended Accounts Manager**\n\n"
            f"Currently **`{count}` accounts** are marked as suspended.\n\n"
            "• **Bulk Delete:** Permanently purges all dead accounts from database.\n"
            "• **Re-Verify:** Moves them back to available stock to re-check them.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data == "action_delete_suspended":
        count = database.delete_all_suspended()
        await query.answer(f"Deleted {count} suspended accounts!", show_alert=True)
        text = format_stats_message()
        await query.edit_message_text(text, reply_markup=build_main_menu_keyboard(), parse_mode="Markdown")

    elif data == "action_reset_suspended":
        count = database.reset_suspended_to_available()
        await query.answer(f"Reset {count} accounts back to Available!", show_alert=True)
        text = format_stats_message()
        await query.edit_message_text(text, reply_markup=build_main_menu_keyboard(), parse_mode="Markdown")

    elif data == "menu_backup":
        await query.answer("Generating database backup...")
        await send_backup_file(query.message.chat_id, context)

    elif data == "menu_history":
        recent = database.get_recent_consumed(limit=10)
        if not recent:
            await query.edit_message_text(
                "📂 **No consumed accounts in history yet.**\n"
                "Once you dispatch or search accounts, they will appear here.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_stats")]]),
                parse_mode="Markdown"
            )
        else:
            lines = ["📜 **Recently Dispatched Accounts (Last 10):**\n━━━━━━━━━━━━━━━━━━━━━━"]
            for i, acc in enumerate(recent, 1):
                ts = acc['consumed_at'] or acc['timestamp'] or "N/A"
                clean_cat = acc['category'].replace('_', ' ')
                lines.append(
                    f"{i}. `@{acc['username']}` | 🕒 `{ts}`\n"
                    f"   🔑 Pass: `{acc['password']}`\n"
                    f"   🛡️ 2FA Key: `{acc['two_fa_secret'] or 'N/A'}`\n"
                    f"   🏷️ Cat: `{clean_cat}`"
                )
            lines.append("━━━━━━━━━━━━━━━━━━━━━━\n💡 _Send any username above to get fresh 2FA OTP!_")
            keyboard = [
                [InlineKeyboardButton("📥 Export History (.txt)", callback_data="export_history_txt")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_stats")]
            ]
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

    elif data == "export_history_txt":
        recent = database.get_recent_consumed(limit=50)
        if not recent:
            await query.answer("No consumed accounts to export.", show_alert=True)
            return

        await query.answer("Generating history file...")
        lines = [
            "# ==========================================",
            "# RECENTLY CONSUMED ACCOUNTS HISTORY",
            "# Format: username:password:2fa_secret",
            "# =========================================="
        ]
        for acc in recent:
            lines.append(f"{acc['username']}:{acc['password']}:{acc['two_fa_secret'] or ''}")

        lines.append("\n# ==========================================")
        lines.append("# DETAILED ACCOUNT BLOCKS")
        lines.append("# ==========================================")
        for acc in recent:
            lines.append("========================================")
            lines.append(f"Username: {acc['username']}")
            lines.append(f"Password: {acc['password']}")
            lines.append(f"2FA Secret: {acc['two_fa_secret'] or ''}")
            lines.append(f"Category: {acc['category']}")
            lines.append(f"Consumed At: {acc['consumed_at'] or ''}")
            lines.append(f"Timestamp: {acc['timestamp'] or ''}")
            lines.append("========================================\n")

        export_text = "\n".join(lines)
        file_bytes = io.BytesIO(export_text.encode("utf-8"))
        filename = f"consumed_history_{len(recent)}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_bytes.name = filename
        file_bytes.seek(0)

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_bytes,
            filename=filename,
            caption=f"📜 Exported history of {len(recent)} consumed accounts with 2FA keys."
        )

    elif data == "menu_live_scan":
        await query.answer("Starting live stock scan...")
        await run_live_stock_scanner(query.message.chat_id, context)

    elif data.startswith("mark_dead:"):
        username = data.split(":")[1]
        database.mark_account_status(username, "SUSPENDED")
        await query.answer("Account marked as DEAD / SUSPENDED!", show_alert=True)
        try:
            await query.edit_message_text(
                f"🔴 **Account @{username} marked as DEAD / CHECKPOINT.**\nMoved to Suspended inventory.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu_stats")]]),
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif data.startswith("mark_fb_fixed:"):
        username = data.split(":")[1]
        database.update_account_category(username, "FB_FIXED", "fb fix")
        await query.answer("Category updated to FB FIXED!", show_alert=True)
        acc = database.get_account_by_username(username)
        if acc:
            otp, rem = get_live_totp(acc["two_fa_secret"])
            msg = (
                "✅ **Account Details (Updated: FB FIXED)**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 **Username:** `{acc['username']}`\n"
                f"🔑 **Password:** `{acc['password']}`\n"
                f"🛡️ **2FA Key:** `{acc['two_fa_secret'] or 'N/A'}`\n"
                f"🕒 **Timestamp:** `{acc['timestamp']}`\n"
                f"🏷️ **Category:** `FB_FIXED` (Updated ✅)\n"
                f"📦 **Status:** `{acc['status']}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔐 **Live 2FA OTP:** `{otp}`\n"
                f"⏳ **Validity:** `{rem} seconds left`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "_(Tap username, password, 2FA key, or OTP to copy instantly)_"
            )
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh OTP", callback_data=f"refresh_otp:{acc['username']}"),
                    InlineKeyboardButton("📋 Copy 2FA Key", callback_data=f"copy_key:{acc['username']}")
                ],
                [
                    InlineKeyboardButton("❌ Mark Dead / Checkpoint", callback_data=f"mark_dead:{acc['username']}"),
                    InlineKeyboardButton("🔙 Main Menu", callback_data="menu_stats")
                ]
            ]
            try:
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            except Exception:
                pass

# --- Dispatch & Checker Logic ---

async def process_single_account_dispatch(query, context, category: str, sort_mode: str):
    """Picks candidate, checks Instagram status via rotating proxy, and dispatches."""
    await query.edit_message_text(
        f"⏳ **Searching & Checking Instagram Status via Proxy...**\n"
        f"Category: `{category}` | Mode: `{sort_mode}`\n\n"
        "_Please wait while we verify account is live..._",
        parse_mode="Markdown"
    )

    max_attempts = 8
    attempt = 0

    while attempt < max_attempts:
        candidate = database.fetch_candidate_account(category=category, sort_mode=sort_mode)
        if not candidate:
            await query.edit_message_text(
                f"❌ **No available accounts found** in category `{category}`.\n"
                "Please upload more accounts or select a different category.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_stats")]]),
                parse_mode="Markdown"
            )
            return

        username = candidate["username"]
        attempt += 1

        # Check Instagram Status via Residential Proxy
        ig_status = await checker.check_instagram_username(username)

        if ig_status == "LIVE":
            # Mark consumed in database
            database.mark_account_status(username, "CONSUMED")
            
            # Generate Live OTP
            otp, rem = get_live_totp(candidate["two_fa_secret"])

            card_text = (
                "✅ **Account Dispatched (Live Verified)**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 **Username:** `{candidate['username']}`\n"
                f"🔑 **Password:** `{candidate['password']}`\n"
                f"🛡️ **2FA Key:** `{candidate['two_fa_secret'] or 'N/A'}`\n"
                f"🕒 **Timestamp:** `{candidate['timestamp']}`\n"
                f"🏷️ **Category:** `{candidate['category']}`\n"
            )
            if candidate["fb_status"]:
                card_text += f"🌐 **FB Status:** `{candidate['fb_status']}`\n"

            card_text += (
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔐 **Live 2FA OTP:** `{otp}`\n"
                f"⏳ **Time Remaining:** `{rem} seconds`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "_(Tap username, password, 2FA key, or OTP above to copy instantly)_"
            )

            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh OTP", callback_data=f"refresh_otp:{candidate['username']}"),
                    InlineKeyboardButton("📋 Copy 2FA Key", callback_data=f"copy_key:{candidate['username']}")
                ],
                [
                    InlineKeyboardButton("🎯 Get Another", callback_data="menu_get_account"),
                    InlineKeyboardButton("🔙 Main Menu", callback_data="menu_stats")
                ]
            ]

            await query.edit_message_text(
                card_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        else:
            # Account is suspended
            logger.info(f"Account @{username} detected SUSPENDED. Marking in DB and fetching next...")
            database.mark_account_status(username, "SUSPENDED")

    await query.edit_message_text(
        f"⚠️ Checked {max_attempts} candidates but all were marked suspended. Please verify your stock.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu_stats")]]),
        parse_mode="Markdown"
    )

async def handle_refresh_otp(query, username: str):
    """Refreshes the TOTP inline without creating new messages."""
    acc = database.get_account_by_username(username)
    if not acc:
        await query.answer("Account not found in database.", show_alert=True)
        return

    otp, rem = get_live_totp(acc["two_fa_secret"])

    card_text = (
        "✅ **Account Dispatched (Live Verified)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Username:** `{acc['username']}`\n"
        f"🔑 **Password:** `{acc['password']}`\n"
        f"🛡️ **2FA Key:** `{acc['two_fa_secret'] or 'N/A'}`\n"
        f"🕒 **Timestamp:** `{acc['timestamp']}`\n"
        f"🏷️ **Category:** `{acc['category']}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔐 **Live 2FA OTP:** `{otp}`\n"
        f"⏳ **Time Remaining:** `{rem} seconds`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "_(Tap username, password, 2FA key, or OTP above to copy instantly)_"
    )

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh OTP", callback_data=f"refresh_otp:{acc['username']}"),
            InlineKeyboardButton("📋 Copy 2FA Key", callback_data=f"copy_key:{acc['username']}")
        ],
        [
            InlineKeyboardButton("🎯 Get Another", callback_data="menu_get_account"),
            InlineKeyboardButton("🔙 Main Menu", callback_data="menu_stats")
        ]
    ]

    try:
        await query.edit_message_text(
            card_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        await query.answer(f"OTP Updated: {otp} ({rem}s left)")
    except Exception as e:
        # Avoid error if message content is identical
        await query.answer(f"Latest OTP: {otp} ({rem}s left)")

# --- Text Message Handlers (Auto-OTP by Username) ---

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles text input:
    When a username is sent, marks the account as CONSUMED and displays full credentials + Live OTP.
    """
    user = update.effective_user
    if not is_admin(user.id):
        return

    text = update.message.text.strip()
    if text.startswith("/"):
        return

    clean_user = text.lstrip("@").strip()
    acc = database.get_account_by_username(clean_user)

    if acc:
        # Mark as consumed upon username request as requested
        database.mark_account_status(clean_user, "CONSUMED")
        otp, rem = get_live_totp(acc["two_fa_secret"])

        msg = (
            "✅ **Account Dispatched (Marked as Consumed)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Username:** `{acc['username']}`\n"
            f"🔑 **Password:** `{acc['password']}`\n"
            f"🛡️ **2FA Key:** `{acc['two_fa_secret'] or 'N/A'}`\n"
            f"🕒 **Timestamp:** `{acc['timestamp']}`\n"
            f"🏷️ **Category:** `{acc['category']}`\n"
            f"📦 **Status:** `CONSUMED`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔐 **Live 2FA OTP:** `{otp}`\n"
            f"⏳ **Validity:** `{rem} seconds left`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_(Tap username, password, 2FA key, or OTP to copy instantly)_"
        )
        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh OTP", callback_data=f"refresh_otp:{acc['username']}"),
                InlineKeyboardButton("📋 Copy 2FA Key", callback_data=f"copy_key:{acc['username']}")
            ],
            [
                InlineKeyboardButton("❌ Mark Dead / Checkpoint", callback_data=f"mark_dead:{acc['username']}"),
                InlineKeyboardButton("🏷️ Mark as FB Fixed", callback_data=f"mark_fb_fixed:{acc['username']}")
            ],
            [
                InlineKeyboardButton("🔙 Main Menu", callback_data="menu_stats")
            ]
        ]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"❌ Username `@{clean_user}` not found in database.\n"
            "Please make sure the account is imported.",
            parse_mode="Markdown"
        )

# --- File Upload & Bulk Export Handlers ---

async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles saved_accounts.txt file upload, ignores duplicates, and reports summary."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("⚠️ Please upload a valid `.txt` file (e.g. `saved_accounts.txt`).")
        return

    status_msg = await update.message.reply_text("⏳ **Downloading and parsing accounts...**", parse_mode="Markdown")

    file_obj = await context.bot.get_file(doc.file_id)
    file_bytes = await file_obj.download_as_bytearray()
    content = file_bytes.decode("utf-8", errors="ignore")

    res = database.import_accounts_text(content)
    total_found = res.get("total_found", 0)
    new_added = res.get("new_added", 0)
    updated = res.get("updated", 0)
    ignored = res.get("ignored", 0)
    cats = res.get("categories", {})

    stats = database.get_stats()
    total_stock = stats["available"]["TOTAL"]

    summary = (
        "📥 **File Import Complete!**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 **Total Found in File:** `{total_found}` accounts\n"
        f"✨ **Newly Added to Stock:** `{new_added}` accounts\n"
        f"🔄 **Passwords/2FA Updated:** `{updated}` accounts\n"
        f"⏭️ **Exact Duplicates (Ignored):** `{ignored}` accounts\n\n"
        "📊 **Category Breakdown (New Additions):**\n"
        f"  • 🔵 FB Fixed:  `+{cats.get('FB_FIXED', 0)}`\n"
        f"  • 🟢 Fresh:     `+{cats.get('FRESH', 0)}`\n"
        f"  • ⚪ Not Fixed: `+{cats.get('NOT_FIXED', 0)}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 **Total Ready Stock in DB Now:** `{total_stock}` accounts"
    )

    await status_msg.edit_text(
        summary,
        reply_markup=build_main_menu_keyboard(),
        parse_mode="Markdown"
    )

async def process_bulk_export(query, context, category: str, count: int):
    """Exports N accounts as a .txt document and sends to chat."""
    clean_cat_display = category.replace("_", " ")
    await query.edit_message_text(f"⏳ Generating export file for **{count} accounts** ({clean_cat_display})...")

    accounts = database.fetch_accounts_for_export(category, count)
    if not accounts:
        await query.edit_message_text(
            f"❌ No available accounts in category `{category}` to export.",
            reply_markup=build_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    # Build clean txt file containing COMBO list (user:pass:2fa) and detailed blocks
    lines = [
        "# ==========================================",
        "# COMBO FORMAT (username:password:2fa_secret)",
        "# =========================================="
    ]
    for acc in accounts:
        lines.append(f"{acc['username']}:{acc['password']}:{acc['two_fa_secret'] or ''}")

    lines.append("\n# ==========================================")
    lines.append("# DETAILED ACCOUNT BLOCKS")
    lines.append("# ==========================================")
    for acc in accounts:
        lines.append("========================================")
        lines.append(f"Timestamp: {acc['timestamp']}")
        lines.append(f"Username: {acc['username']}")
        lines.append(f"Password: {acc['password']}")
        lines.append(f"2FA Secret: {acc['two_fa_secret'] or ''}")
        if acc.get("two_fa_added"):
            lines.append(f"2FA Added: {acc['two_fa_added']}")
        if acc.get("fb_status"):
            lines.append(f"FB Status: {acc['fb_status']}")
        lines.append(f"Category: {acc['category']}")
        lines.append("========================================\n")

    export_text = "\n".join(lines)
    file_bytes = io.BytesIO(export_text.encode("utf-8"))
    clean_cat_fn = category.lower().replace("_", "")
    filename = f"exported_{clean_cat_fn}_{len(accounts)}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    file_bytes.name = filename
    file_bytes.seek(0)

    try:
        clean_cat = category.replace("_", " ")
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_bytes,
            filename=filename,
            caption=f"📦 Export Successful!\nDelivered {len(accounts)} accounts ({clean_cat}).\nMarked as consumed in DB."
        )
        # Mark consumed ONLY AFTER document is successfully sent!
        database.mark_accounts_consumed_by_ids([a["id"] for a in accounts])

        await query.message.reply_text(
            format_stats_message(),
            reply_markup=build_main_menu_keyboard(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send export document: {e}")
        await query.message.reply_text(
            f"❌ Error sending export file: {e}\nAccounts were NOT marked as consumed.",
            reply_markup=build_main_menu_keyboard()
        )

async def run_live_stock_scanner(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Scans all available accounts in stock via proxy and marks suspended accounts."""
    global is_scanner_running
    if is_scanner_running:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ **A scan is already in progress!** Please wait for it to complete.",
            parse_mode="Markdown"
        )
        return

    usernames = database.get_all_available_accounts()
    total = len(usernames)
    if total == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ **No available accounts in stock to scan.**\nPlease import accounts first.",
            reply_markup=build_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    is_scanner_running = True
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🔍 **Starting Live Stock Scan via Turnoxy Proxy...**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Total Accounts to Check: `{total}`\n"
            f"⚡ Checking each username live on Instagram...\n"
            f"_Please wait..._"
        ),
        parse_mode="Markdown"
    )

    live_count = 0
    suspended_count = 0

    try:
        for idx, username in enumerate(usernames, 1):
            status = await checker.check_instagram_username(username)
            if status == "SUSPENDED":
                database.mark_account_status(username, "SUSPENDED")
                suspended_count += 1
            else:
                live_count += 1

            # Update progress every 5 accounts or at the end
            if idx % 5 == 0 or idx == total:
                try:
                    await msg.edit_text(
                        f"⏳ **Live Stock Scanning in Progress...**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🔄 Checked: `{idx}/{total}` accounts\n"
                        f"🟢 Live: `{live_count}`\n"
                        f"🔴 Suspended: `{suspended_count}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"_Current: @{username}_",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

            await asyncio.sleep(0.5)

        # Final Report
        report_lines = [
            "✅ **Live Stock Scan Complete!**",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 **Total Checked:** `{total}` accounts",
            f"🟢 **Live (Active):** `{live_count}` accounts",
            f"🔴 **Suspended (Dead):** `{suspended_count}` accounts",
            "━━━━━━━━━━━━━━━━━━━━━━"
        ]
        if suspended_count > 0:
            report_lines.append(f"ℹ️ _All {suspended_count} suspended accounts have been automatically moved to the Suspended group in the database._")
        else:
            report_lines.append("🎉 _All scanned accounts are 100% LIVE and healthy!_")

        keyboard = [
            [
                InlineKeyboardButton("🔴 View Suspended", callback_data="menu_suspended"),
                InlineKeyboardButton("🗑️ Delete Suspended", callback_data="action_delete_suspended")
            ],
            [
                InlineKeyboardButton("📊 Refresh Stats", callback_data="menu_stats"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="menu_stats")
            ]
        ]

        await msg.edit_text(
            "\n".join(report_lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error during stock scan: {e}")
        await msg.edit_text(f"❌ Scan interrupted due to error: {e}", reply_markup=build_main_menu_keyboard())
    finally:
        is_scanner_running = False

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /scan or /scan_stock command: starts live verification of all stock accounts."""
    user = update.effective_user
    if not is_admin(user.id):
        return
    await run_live_stock_scanner(update.effective_chat.id, context)

async def send_backup_file(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Sends full database backup as a .txt file."""
    backup_text = database.export_full_database_text()
    if not backup_text:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Database is empty. Nothing to backup.")
        return

    file_bytes = io.BytesIO(backup_text.encode("utf-8"))
    filename = f"db_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    file_bytes.name = filename
    file_bytes.seek(0)
    await context.bot.send_document(
        chat_id=chat_id,
        document=file_bytes,
        filename=filename,
        caption="💾 Full Database Backup Snapshot\nContains all available, consumed, and suspended accounts."
    )

# --- Application Builder ---

def build_telegram_app():
    """Builds and returns the python-telegram-bot application."""
    if not config.BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured in .env!")

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("scan_stock", scan_command))
    app.add_handler(CommandHandler("backup", lambda u, c: send_backup_file(u.effective_chat.id, c)))

    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    return app
