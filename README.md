# 🚀 Instagram & 2FA Accounts Manager (Telegram Bot)

A high-performance, automated Telegram Bot designed to manage Instagram accounts with 2FA TOTP verification, Turso (libSQL) cloud database synchronization, residential proxy health-checking, and Render 24/7 hosting.

---

## ✨ Features Included

1. **Turso Cloud Database (libSQL) & Local SQLite:**
   - Seamless sync with Turso DB in the cloud.
   - Fallback to local SQLite (`accounts.db`) when running offline.
   - Categorized stock: `FB_FIXED`, `FRESH`, `NOT_FIXED`.
   - Status tracking: `AVAILABLE`, `CONSUMED`, `SUSPENDED`.

2. **Smart Ingestion & Deduplication:**
   - Upload `saved_accounts.txt` directly to Telegram.
   - Automatically skips existing accounts (Zero duplicates).
   - Instant category-wise breakdown report.

3. **On-Demand Single Account Dispatch:**
   - **Sorting Priority Modes:**
     - ⏳ **Oldest First (Aged FIFO):** Picks the oldest timestamp accounts first.
     - ⚡ **Newest First:** Picks recently added accounts.
     - 🎲 **Random:** Picks any available account.
   - **Pre-Dispatch Instagram Live Check:**
     - Verifies account status via rotating residential proxies (Proxygen / Turnoxy).
     - If suspended, automatically moves it to `SUSPENDED` and fetches the next matching candidate until a live account is found.
   - **Interactive Live 2FA OTP Card:**
     - Monospace format (1-tap to copy username, password, or OTP).
     - Inline `[ 🔄 Refresh OTP ]` button updates code & countdown in-place without chat spam.

4. **Auto-OTP by Username:**
   - Send any `@username` to the bot to get instant live TOTP codes anytime.

5. **Bulk Export Engine:**
   - Select category and quantity (5, 10, 25, 50).
   - Generates formatted `.txt` document and marks accounts as consumed.

6. **Suspended Accounts Cleaner:**
   - 1-click bulk purge of dead/suspended accounts.
   - Re-verify option to move them back to stock if needed.

7. **Render 24/7 Keep-Alive Web Server:**
   - Built-in lightweight HTTP server listening on `$PORT`.
   - Compatible with UptimeRobot (ping every 5 minutes to prevent sleep on Render Free).

---

## 🛠️ Local Setup & Testing

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure `.env`:**
   Copy `.env.example` to `.env` and fill in:
   - `TELEGRAM_BOT_TOKEN`: From [@BotFather](https://t.me/BotFather)
   - `ADMIN_USER_ID`: Your numeric Telegram ID (from [@userinfobot](https://t.me/userinfobot))
   - `TURSO_DATABASE_URL`: Your Turso DB URL (e.g. `libsql://your-db-org.turso.io`)
   - `TURSO_AUTH_TOKEN`: Your Turso Auth Token

3. **Run Locally:**
   ```bash
   python main.py
   ```

---

## 🌐 Deploy to Render (Free 24/7) with UptimeRobot

### Step 1: Push to GitHub
1. Create a **Private Repository** on GitHub (e.g., `insta-accounts-bot`).
2. Run these commands in your project folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit of Instagram 2FA Bot"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/insta-accounts-bot.git
   git push -u origin main
   ```

### Step 2: Create Web Service on Render
1. Go to [render.com](https://render.com) and click **New +** -> **Web Service**.
2. Connect your GitHub repository.
3. Configure settings:
   - **Name:** `insta-accounts-bot`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Instance Type:** `Free`
4. Add **Environment Variables** in Render settings:
   - `TELEGRAM_BOT_TOKEN` = `your_token`
   - `ADMIN_USER_ID` = `your_user_id`
   - `TURSO_DATABASE_URL` = `libsql://your-db.turso.io`
   - `TURSO_AUTH_TOKEN` = `your_turso_token`
   - `PROXY_PRIMARY` = `http://user6101-country-IN:DnFbe3qNqH@as.residential.proxygen.io:1010`
   - `PROXY_BACKUP` = `http://sub_Hzu7N0Hx:Rujm61dQa861evho@gate.turnoxy.com:1318`
5. Click **Create Web Service**.

### Step 3: Keep Alive with UptimeRobot (24/7 Free)
1. Copy your Render service URL (e.g. `https://insta-accounts-bot.onrender.com`).
2. Go to [uptimerobot.com](https://uptimerobot.com) and click **Add New Monitor**.
3. Settings:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `Insta Bot Keep-Alive`
   - **URL (or IP):** `https://insta-accounts-bot.onrender.com/health`
   - **Monitoring Interval:** `Every 5 minutes`
4. Click **Create Monitor**.
   *Render will never sleep, and your bot will stay online 24/7 completely free!*
