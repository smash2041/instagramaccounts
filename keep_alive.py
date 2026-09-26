import asyncio
import logging
from aiohttp import web
from config import PORT

logger = logging.getLogger(__name__)

async def health_check(request):
    """Health check endpoint for UptimeRobot / Render."""
    return web.json_response({
        "status": "online",
        "service": "Instagram-2FA-Telegram-Bot",
        "message": "UptimeRobot ping successful. Bot is running 24/7."
    })

def create_web_app():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    return app

async def start_keep_alive_server():
    """Runs a background web server on the assigned PORT."""
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Keep-alive web server started on http://0.0.0.0:{PORT}")
