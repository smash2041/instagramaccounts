import re
import logging
import httpx
from config import PROXY_PRIMARY, PROXY_BACKUP

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def _fetch_status_with_proxy(username: str, proxy_url: str) -> str:
    """
    Checks an Instagram username status using the given proxy.
    Returns: 'LIVE' or 'SUSPENDED'.
    Reads only until </title> is encountered (typically 2-4 KB) to preserve bandwidth.
    """
    url = f"https://www.instagram.com/{username}/"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    transport = httpx.AsyncHTTPTransport(proxy=proxy_url) if proxy_url else None
    async with httpx.AsyncClient(transport=transport, timeout=12.0, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 404:
                return "SUSPENDED"

            buffer = ""
            async for text_chunk in response.aiter_text():
                buffer += text_chunk
                if "</title>" in buffer.lower() or len(buffer) > 150000:
                    break

            title_match = re.search(r'<title>(.*?)</title>', buffer, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else ""

            # Dead / suspended profiles have title "Instagram" or "Page Not Found"
            if not title or title.lower() == "instagram" or "page not found" in title.lower():
                return "SUSPENDED"

            # Active profiles contain the handle, &#064; (@), or photos/videos text
            return "LIVE"

async def check_instagram_username(username: str) -> str:
    """
    Checks if an Instagram username is LIVE or SUSPENDED.
    Attempts Primary Proxy first; if error occurs, falls back to Backup Proxy.
    """
    clean_user = username.strip().lstrip("@")
    
    # 1. Try Primary Proxy (Proxygen - India)
    if PROXY_PRIMARY:
        try:
            status = await _fetch_status_with_proxy(clean_user, PROXY_PRIMARY)
            if status in ["LIVE", "SUSPENDED"]:
                return status
        except Exception as e:
            logger.warning(f"Primary proxy failed for {clean_user}: {e}. Trying backup...")

    # 2. Try Backup Proxy (Turnoxy - Europe)
    if PROXY_BACKUP:
        try:
            status = await _fetch_status_with_proxy(clean_user, PROXY_BACKUP)
            if status in ["LIVE", "SUSPENDED"]:
                return status
        except Exception as e:
            logger.warning(f"Backup proxy failed for {clean_user}: {e}.")

    # 3. Direct check fallback
    try:
        status = await _fetch_status_with_proxy(clean_user, "")
        return status
    except Exception as e:
        logger.error(f"Direct check error for {clean_user}: {e}")
        return "LIVE"
