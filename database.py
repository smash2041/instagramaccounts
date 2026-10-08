import re
import datetime
import libsql_client
from config import TURSO_DB_URL, TURSO_AUTH_TOKEN

def get_db_client():
    """Returns a client for Turso DB or falls back to local SQLite file:accounts.db."""
    url = TURSO_DB_URL.strip().strip("'\"")
    auth_token = TURSO_AUTH_TOKEN.strip().strip("'\"")

    # Convert libsql:// to https:// to use robust HTTPS instead of WebSocket (wss://)
    if url.startswith("libsql://"):
        url = url.replace("libsql://", "https://")

    if url and auth_token:
        return libsql_client.create_client_sync(url=url, auth_token=auth_token)
    elif url:
        return libsql_client.create_client_sync(url=url)
    else:
        return libsql_client.create_client_sync("file:accounts.db")

def init_db():
    """Initializes tables and indexes."""
    client = get_db_client()
    try:
        client.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                two_fa_secret TEXT,
                category TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'AVAILABLE',
                timestamp TEXT,
                two_fa_added TEXT,
                fb_status TEXT,
                consumed_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        client.execute("CREATE INDEX IF NOT EXISTS idx_status_cat ON accounts (status, category);")
        client.execute("CREATE INDEX IF NOT EXISTS idx_username ON accounts (username);")
    finally:
        client.close()

def parse_accounts_from_text(text: str):
    """
    Parses accounts formatted in blocks like saved_accounts.txt.
    Returns list of dicts.
    """
    # Split by standard separator line or double newlines
    blocks = re.split(r'={10,}', text)
    accounts = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        username_match = re.search(r'Username:\s*([^\r\n]+)', block, re.IGNORECASE)
        password_match = re.search(r'Password:\s*([^\r\n]+)', block, re.IGNORECASE)
        if not username_match or not password_match:
            continue

        username = username_match.group(1).strip()
        password = password_match.group(1).strip()

        ts_match = re.search(r'Timestamp:\s*([^\r\n]+)', block, re.IGNORECASE)
        timestamp = ts_match.group(1).strip() if ts_match else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        fa_match = re.search(r'2FA Secret:\s*([^\r\n]+)', block, re.IGNORECASE)
        two_fa_secret = fa_match.group(1).strip().replace(" ", "") if fa_match else ""

        fa_added_match = re.search(r'2FA Added:\s*([^\r\n]+)', block, re.IGNORECASE)
        two_fa_added = fa_added_match.group(1).strip() if fa_added_match else ""

        fb_match = re.search(r'FB Status:\s*([^\r\n]+)', block, re.IGNORECASE)
        fb_status = fb_match.group(1).strip() if fb_match else ""

        # Categorization logic:
        # 1. FB Fixed: if fb status has 'fb fix'
        # 2. Fresh: if 'fresh' is present in fb_status or tags
        # 3. Not Fixed: default when status line is absent or empty
        lower_fb = fb_status.lower()
        if "fb fix" in lower_fb or "fixed" in lower_fb:
            category = "FB_FIXED"
        elif "fresh" in lower_fb:
            category = "FRESH"
        else:
            category = "NOT_FIXED"

        accounts.append({
            "username": username,
            "password": password,
            "two_fa_secret": two_fa_secret,
            "category": category,
            "timestamp": timestamp,
            "two_fa_added": two_fa_added,
            "fb_status": fb_status
        })

    return accounts

def import_accounts_text(text: str):
    """
    Imports accounts from saved_accounts.txt content.
    - If account is brand new: inserts it.
    - If username exists but password/2FA changed: updates credentials.
    - If username and password are identical: ignores duplicate.
    Returns stats dict.
    """
    parsed = parse_accounts_from_text(text)
    total_found = len(parsed)
    if total_found == 0:
        return {"total_found": 0, "new_added": 0, "updated": 0, "ignored": 0, "categories": {"FB_FIXED": 0, "FRESH": 0, "NOT_FIXED": 0}}

    client = get_db_client()
    new_added = 0
    updated = 0
    ignored = 0
    cat_counts = {"FB_FIXED": 0, "FRESH": 0, "NOT_FIXED": 0}

    try:
        for acc in parsed:
            res = client.execute("SELECT id, password, two_fa_secret FROM accounts WHERE username = ?;", [acc["username"]])
            if len(res.rows) > 0:
                existing_pass = res.rows[0][1]
                existing_2fa = res.rows[0][2]
                # If password or 2FA key changed, update it to the latest credentials
                if acc["password"] != existing_pass or (acc["two_fa_secret"] and acc["two_fa_secret"] != existing_2fa):
                    client.execute("""
                        UPDATE accounts 
                        SET password = ?, two_fa_secret = ?, timestamp = ?, fb_status = ?, category = ?, status = 'AVAILABLE' 
                        WHERE username = ?;
                    """, [
                        acc["password"],
                        acc["two_fa_secret"] or existing_2fa,
                        acc["timestamp"],
                        acc["fb_status"],
                        acc["category"],
                        acc["username"]
                    ])
                    updated += 1
                else:
                    ignored += 1
                continue

            client.execute("""
                INSERT INTO accounts (username, password, two_fa_secret, category, status, timestamp, two_fa_added, fb_status, created_at)
                VALUES (?, ?, ?, ?, 'AVAILABLE', ?, ?, ?, CURRENT_TIMESTAMP);
            """, [
                acc["username"],
                acc["password"],
                acc["two_fa_secret"],
                acc["category"],
                acc["timestamp"],
                acc["two_fa_added"],
                acc["fb_status"]
            ])
            new_added += 1
            cat_counts[acc["category"]] = cat_counts.get(acc["category"], 0) + 1

    finally:
        client.close()

    return {
        "total_found": total_found,
        "new_added": new_added,
        "updated": updated,
        "ignored": ignored,
        "categories": cat_counts
    }

def get_stats():
    """Returns inventory stats broken down by category and status."""
    client = get_db_client()
    try:
        res = client.execute("""
            SELECT category, status, COUNT(*) 
            FROM accounts 
            GROUP BY category, status;
        """)
        
        stats = {
            "available": {"FB_FIXED": 0, "FRESH": 0, "NOT_FIXED": 0, "TOTAL": 0},
            "consumed": 0,
            "suspended": 0,
            "total_all": 0
        }

        for row in res.rows:
            category, status, count = row[0], row[1], row[2]
            stats["total_all"] += count
            if status == "AVAILABLE":
                stats["available"][category] = count
                stats["available"]["TOTAL"] += count
            elif status == "CONSUMED":
                stats["consumed"] += count
            elif status == "SUSPENDED":
                stats["suspended"] += count

        return stats
    finally:
        client.close()

def fetch_candidate_account(category=None, sort_mode="oldest"):
    """
    Fetches one candidate account based on category and sorting order.
    Sort modes:
      - 'oldest': ORDER BY timestamp ASC (FIFO / Aged IDs first)
      - 'newest': ORDER BY timestamp DESC
      - 'random': ORDER BY RANDOM()
    """
    client = get_db_client()
    try:
        order_clause = "ORDER BY timestamp ASC"
        if sort_mode == "newest":
            order_clause = "ORDER BY timestamp DESC"
        elif sort_mode == "random":
            order_clause = "ORDER BY RANDOM()"

        if category and category != "ALL":
            query = f"SELECT id, username, password, two_fa_secret, category, timestamp, two_fa_added, fb_status FROM accounts WHERE status = 'AVAILABLE' AND category = ? {order_clause} LIMIT 1;"
            res = client.execute(query, [category])
        else:
            query = f"SELECT id, username, password, two_fa_secret, category, timestamp, two_fa_added, fb_status FROM accounts WHERE status = 'AVAILABLE' {order_clause} LIMIT 1;"
            res = client.execute(query)

        if not res.rows:
            return None

        row = res.rows[0]
        return {
            "id": row[0],
            "username": row[1],
            "password": row[2],
            "two_fa_secret": row[3],
            "category": row[4],
            "timestamp": row[5],
            "two_fa_added": row[6],
            "fb_status": row[7]
        }
    finally:
        client.close()

def mark_account_status(username: str, status: str):
    """Updates account status (AVAILABLE, CONSUMED, SUSPENDED)."""
    client = get_db_client()
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if status == "CONSUMED":
            client.execute("UPDATE accounts SET status = ?, consumed_at = ? WHERE username = ?;", [status, now, username])
        else:
            client.execute("UPDATE accounts SET status = ? WHERE username = ?;", [status, username])
    finally:
        client.close()

def get_account_by_username(username: str):
    """
    Searches account by username (active or consumed) to fetch 2FA secret.
    """
    client = get_db_client()
    try:
        # Clean @ symbol if present
        clean_user = username.strip().lstrip("@")
        res = client.execute("""
            SELECT username, password, two_fa_secret, category, status, timestamp, two_fa_added 
            FROM accounts 
            WHERE username = ? 
            LIMIT 1;
        """, [clean_user])

        if not res.rows:
            return None

        row = res.rows[0]
        return {
            "username": row[0],
            "password": row[1],
            "two_fa_secret": row[2],
            "category": row[3],
            "status": row[4],
            "timestamp": row[5],
            "two_fa_added": row[6]
        }
    finally:
        client.close()

def fetch_accounts_for_export(category: str, limit: int):
    """
    Picks N available accounts without marking them as consumed yet.
    """
    client = get_db_client()
    try:
        if category and category != "ALL":
            res = client.execute("""
                SELECT id, username, password, two_fa_secret, category, timestamp, two_fa_added, fb_status 
                FROM accounts 
                WHERE status = 'AVAILABLE' AND category = ? 
                ORDER BY timestamp ASC 
                LIMIT ?;
            """, [category, limit])
        else:
            res = client.execute("""
                SELECT id, username, password, two_fa_secret, category, timestamp, two_fa_added, fb_status 
                FROM accounts 
                WHERE status = 'AVAILABLE' 
                ORDER BY timestamp ASC 
                LIMIT ?;
            """, [limit])

        accounts = []
        for row in res.rows:
            accounts.append({
                "id": row[0],
                "username": row[1],
                "password": row[2],
                "two_fa_secret": row[3],
                "category": row[4],
                "timestamp": row[5],
                "two_fa_added": row[6],
                "fb_status": row[7]
            })
        return accounts
    finally:
        client.close()

def mark_accounts_consumed_by_ids(ids: list):
    """Marks a list of account IDs as CONSUMED."""
    if not ids:
        return
    client = get_db_client()
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for acc_id in ids:
            client.execute("UPDATE accounts SET status = 'CONSUMED', consumed_at = ? WHERE id = ?;", [now, acc_id])
    finally:
        client.close()

def bulk_export_accounts(category: str, limit: int):
    """
    Legacy wrapper: fetches accounts, marks them as consumed, and returns list.
    """
    accounts = fetch_accounts_for_export(category, limit)
    if accounts:
        mark_accounts_consumed_by_ids([a["id"] for a in accounts])
    return accounts

def get_suspended_accounts():
    """Returns list of suspended accounts."""
    client = get_db_client()
    try:
        res = client.execute("SELECT id, username, timestamp, category FROM accounts WHERE status = 'SUSPENDED';")
        return [{"id": r[0], "username": r[1], "timestamp": r[2], "category": r[3]} for r in res.rows]
    finally:
        client.close()

def delete_all_suspended():
    """Permanently deletes accounts marked as SUSPENDED."""
    client = get_db_client()
    try:
        res = client.execute("SELECT COUNT(*) FROM accounts WHERE status = 'SUSPENDED';")
        count = res.rows[0][0] if res.rows else 0
        client.execute("DELETE FROM accounts WHERE status = 'SUSPENDED';")
        return count
    finally:
        client.close()

def reset_suspended_to_available():
    """Reverts all suspended accounts back to AVAILABLE for re-verification."""
    client = get_db_client()
    try:
        res = client.execute("SELECT COUNT(*) FROM accounts WHERE status = 'SUSPENDED';")
        count = res.rows[0][0] if res.rows else 0
        client.execute("UPDATE accounts SET status = 'AVAILABLE' WHERE status = 'SUSPENDED';")
        return count
    finally:
        client.close()

def get_all_available_accounts():
    """Returns all available accounts for scanning."""
    client = get_db_client()
    try:
        res = client.execute("SELECT username FROM accounts WHERE status = 'AVAILABLE' ORDER BY id ASC;")
        return [r[0] for r in res.rows]
    finally:
        client.close()

def export_full_database_text():
    """Exports full database in saved_accounts.txt format for backup."""
    client = get_db_client()
    try:
        res = client.execute("""
            SELECT username, password, two_fa_secret, timestamp, two_fa_added, fb_status, category, status 
            FROM accounts 
            ORDER BY id ASC;
        """)
        lines = []
        for row in res.rows:
            username, password, two_fa_secret, timestamp, two_fa_added, fb_status, category, status = row
            lines.append("========================================")
            lines.append(f"Timestamp: {timestamp or ''}")
            lines.append(f"Username: {username}")
            lines.append(f"Password: {password}")
            if two_fa_secret:
                lines.append(f"2FA Secret: {two_fa_secret}")
            if two_fa_added:
                lines.append(f"2FA Added: {two_fa_added}")
            if fb_status:
                lines.append(f"FB Status: {fb_status}")
            lines.append(f"Category: {category}")
            lines.append(f"Status: {status}")
            lines.append("========================================\n")
        return "\n".join(lines)
    finally:
        client.close()

def update_account_category(username: str, category: str, fb_status: str = ""):
    """Updates the category and fb_status for an account."""
    client = get_db_client()
    try:
        client.execute("""
            UPDATE accounts 
            SET category = ?, fb_status = ? 
            WHERE username = ?;
        """, [category, fb_status, username.lstrip("@")])
    finally:
        client.close()

def get_recent_consumed(limit: int = 10):
    """Fetches the last N consumed accounts ordered by consumed_at DESC."""
    client = get_db_client()
    try:
        res = client.execute("""
            SELECT username, password, two_fa_secret, category, consumed_at, timestamp 
            FROM accounts 
            WHERE status = 'CONSUMED' 
            ORDER BY consumed_at DESC 
            LIMIT ?;
        """, [limit])
        return [{
            "username": r[0],
            "password": r[1],
            "two_fa_secret": r[2],
            "category": r[3],
            "consumed_at": r[4],
            "timestamp": r[5]
        } for r in res.rows]
    finally:
        client.close()

