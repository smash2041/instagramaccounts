import logging
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

import config
import database
from keep_alive import start_keep_alive_server
from bot import (
    start_command,
    help_command,
    history_command,
    scan_command,
    callback_router,
    handle_document_upload,
    handle_text_messages,
    send_backup_file
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def on_startup(application):
    """Initializes Database and launches Render Keep-Alive HTTP Server."""
    logger.info("Connecting to database & initializing tables...")
    database.init_db()
    logger.info("Database initialized successfully.")

    logger.info("Starting Render Keep-Alive HTTP web server...")
    await start_keep_alive_server()
    logger.info("Keep-Alive HTTP server running.")

def main():
    if not config.BOT_TOKEN:
        logger.error("[ERROR] TELEGRAM_BOT_TOKEN is missing! Please configure it in .env")
        print("\n=======================================================")
        print("[!] Error: TELEGRAM_BOT_TOKEN is missing!")
        print("Please edit .env and set your TELEGRAM_BOT_TOKEN from @BotFather.")
        print("=======================================================\n")
        return

    logger.info("Building Telegram Application...")
    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .post_init(on_startup)
        .build()
    )

    # Register Handlers
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

    logger.info("Instagram & 2FA Telegram Bot is starting polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
