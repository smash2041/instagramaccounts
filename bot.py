import io
import time
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
            InlineKeyboardButton("📥 Import .txt File", callback_data="menu_import_info"),
            InlineKeyboardButton("🔴 Suspended Accounts", callback_data="menu_suspended")
        ],
        [
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
        "• `/history` - View last 10 dispatched accounts\n"
        "• `/backup` - Download complete database as .txt file\n"
        "• **Send Username:** Just send any username (e.g. `user_123` or `@user_123`) to get instant 2FA OTP!\n"
        "• **Upload File:** Drag and drop `saved_accounts.txt` anytime to import new accounts (duplicates automatically skipped)!\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /history command: displays recently consumed accounts."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    recent = database.get_recent_consumed(limit=10)
    if not recent:
        await update.message.reply_text("📂 No consumed accounts found yet.", parse_mode="Markdown")
        return

    lines = ["📜 **Recently Dispatched Accounts (Last 10):**\n━━━━━━━━━━━━━━━━━━━━━━"]
    for i, acc in enumerate(recent, 1):
        lines.append(
            f"{i}. `@{acc['username']}` | 🕒 `{acc['consumed_at'] or acc['timestamp']}`\n"
            f"   Pass: `{acc['password']}` | Cat: `{acc['category']}`"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n_Send any username above to get fresh 2FA OTP!_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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
                lines.append(
                    f"{i}. `@{acc['username']}` | 🕒 `{ts}`\n"
                    f"   🔑 Pass: `{acc['password']}` | 🏷️ `{acc['category']}`"
                )
            lines.append("━━━━━━━━━━━━━━━━━━━━━━\n💡 _Send any username above to get fresh 2FA OTP instantly!_")
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_stats")]]),
                parse_mode="Markdown"
            )

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
                f"🕒 **Timestamp:** `{acc['timestamp']}`\n"
                f"🏷️ **Category:** `FB_FIXED` (Updated ✅)\n"
                f"📦 **Status:** `{acc['status']}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔐 **Live 2FA OTP:** `{otp}`\n"
                f"⏳ **Validity:** `{rem} seconds left`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "_(Tap username, password, or OTP to copy instantly)_"
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
                "_(Tap username/password/OTP above to copy instantly)_"
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
        f"🕒 **Timestamp:** `{acc['timestamp']}`\n"
        f"🏷️ **Category:** `{acc['category']}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔐 **Live 2FA OTP:** `{otp}`\n"
        f"⏳ **Time Remaining:** `{rem} seconds`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "_(Tap username/password/OTP above to copy instantly)_"
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
            f"🕒 **Timestamp:** `{acc['timestamp']}`\n"
            f"🏷️ **Category:** `{acc['category']}`\n"
            f"📦 **Status:** `CONSUMED`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔐 **Live 2FA OTP:** `{otp}`\n"
            f"⏳ **Validity:** `{rem} seconds left`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_(Tap username, password, or OTP to copy instantly)_"
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
    total_found = res["total_found"]
    new_added = res["new_added"]
    ignored = res["ignored"]
    cats = res["categories"]

    stats = database.get_stats()
    total_stock = stats["available"]["TOTAL"]

    summary = (
        "📥 **File Import Complete!**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 **Total Found in File:** `{total_found}` accounts\n"
        f"⏭️ **Already in DB (Ignored):** `{ignored}` duplicates\n"
        f"✨ **Newly Added to Stock:** `{new_added}` accounts\n\n"
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
    await query.edit_message_text(f"⏳ Generating export file for **{count} accounts** (`{category}`)...", parse_mode="Markdown")

    accounts = database.bulk_export_accounts(category, count)
    if not accounts:
        await query.edit_message_text(
            f"❌ No available accounts in category `{category}` to export.",
            reply_markup=build_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    # Format accounts into saved_accounts.txt blocks
    lines = []
    for acc in accounts:
        lines.append("========================================")
        lines.append(f"Timestamp: {acc['timestamp']}")
        lines.append(f"Username: {acc['username']}")
        lines.append(f"Password: {acc['password']}")
        if acc["two_fa_secret"]:
            lines.append(f"2FA Secret: {acc['two_fa_secret']}")
        if acc["two_fa_added"]:
            lines.append(f"2FA Added: {acc['two_fa_added']}")
        if acc["fb_status"]:
            lines.append(f"FB Status: {acc['fb_status']}")
        lines.append("========================================\n")

    export_text = "\n".join(lines)
    file_bytes = io.BytesIO(export_text.encode("utf-8"))
    filename = f"exported_{category.lower()}_{len(accounts)}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    await query.message.reply_document(
        document=file_bytes,
        filename=filename,
        caption=f"📦 **Export Successful!**\nDelivered `{len(accounts)}` accounts ({category}).\nThese accounts have been marked as consumed in DB.",
        parse_mode="Markdown"
    )

    await query.message.reply_text(format_stats_message(), reply_markup=build_main_menu_keyboard(), parse_mode="Markdown")

async def send_backup_file(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Sends full database backup as a .txt file."""
    backup_text = database.export_full_database_text()
    if not backup_text:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Database is empty. Nothing to backup.")
        return

    file_bytes = io.BytesIO(backup_text.encode("utf-8"))
    filename = f"db_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    await context.bot.send_document(
        chat_id=chat_id,
        document=file_bytes,
        filename=filename,
        caption="💾 **Full Database Backup Snapshot**\nContains all available, consumed, and suspended accounts.",
        parse_mode="Markdown"
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
    app.add_handler(CommandHandler("backup", lambda u, c: send_backup_file(u.effective_chat.id, c)))

    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    return app
