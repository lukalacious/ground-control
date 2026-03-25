# Ground Control — Next Steps to Go Live

## What's Done

- [x] Neon PostgreSQL project created (`jolly-rice-29956458`)
- [x] 6,436 listings migrated from SQLite to Neon
- [x] Next.js 16 app built with API routes (builds clean)
- [x] Python scripts migrated from sqlite3 to psycopg2
- [x] New modules written: erfpacht extractor, translator, analytics, scheduler, notifier
- [x] Code pushed to GitHub, pulled on Mac Mini
- [x] Mac Mini: psycopg2 installed, Neon connection verified
- [x] Mac Mini: LaunchAgent installed (scraper daemon, 7am–4pm)
- [x] Neighbourhood analytics computed (128 neighbourhoods with percentiles)
- [x] `web/.env` created on Mac Mini with Neon connection strings

---

## Step 1: Deploy to Vercel

From your MacBook, in the `web/` directory:

```bash
cd ~/Documents/code/projects/ground-control/web

# 1. Login to Vercel
vercel login

# 2. Deploy (creates project on first run)
vercel --prod
# When prompted:
#   - Set up and deploy? → Yes
#   - Which scope? → Your account
#   - Link to existing project? → No
#   - Project name? → ground-control
#   - Root directory? → ./

# 3. Add environment variables
vercel env add DATABASE_URL production
# Paste: postgresql://YOUR_NEON_USER:YOUR_NEON_PASSWORD@YOUR_NEON_HOST-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require

vercel env add DIRECT_DATABASE_URL production
# Paste: postgresql://YOUR_NEON_USER:YOUR_NEON_PASSWORD@YOUR_NEON_HOST.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require

# 4. Redeploy with env vars
vercel --prod

# 5. Verify
curl https://YOUR-URL.vercel.app/api/listings?limit=1
```

---

## Step 2: Set Up Translation (needs API key)

On the Mac Mini:

```bash
ssh mac-mini

# Add your Anthropic API key
echo 'ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE' >> ~/ground-control/web/.env

# Test with 10 descriptions first
cd ~/ground-control
source venv/bin/activate
python3 translator.py --limit 10

# If that works, translate all ~6,400 descriptions (~$0.70 total)
python3 translator.py
```

---

## Step 3: Set Up Telegram Notifications

Check what the existing morning report uses:

```bash
ssh mac-mini "grep -i 'token\|chat_id\|keychain' ~/ground-control/morning_report.py | head -10"
```

Then add the same credentials to the env:

```bash
ssh mac-mini
echo 'TELEGRAM_BOT_TOKEN=your-bot-token' >> ~/ground-control/web/.env
echo 'TELEGRAM_CHAT_ID=your-chat-id' >> ~/ground-control/web/.env

# Test
cd ~/ground-control
source venv/bin/activate
python3 notifier.py --test
```

---

## Step 4: Verify the Scraper Daemon

The LaunchAgent is already installed. It starts `scheduler.py` at 06:55 daily and scrapes every 40–90 min until 16:00.

```bash
# Check it's registered
ssh mac-mini "launchctl list | grep groundcontrol"

# Check logs after 7am
ssh mac-mini "tail -50 ~/ground-control/logs/scheduler.log"

# Or run one cycle manually to test
ssh mac-mini "cd ~/ground-control && source venv/bin/activate && python3 scheduler.py --once"
```

---

## Step 5: Run Erfpacht Extraction (if not already done)

Check if it finished:

```bash
ssh mac-mini "cd ~/ground-control && source venv/bin/activate && python3 -c \"
from db import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute(\\\"SELECT erfpacht_status, COUNT(*) FROM listings GROUP BY erfpacht_status\\\")
for row in cur.fetchall(): print(row)
conn.close()
\""
```

If most are still `NULL`, run it:

```bash
ssh mac-mini "cd ~/ground-control && source venv/bin/activate && python3 erfpacht_extractor.py"
```

---

## Connection Strings Reference

| Variable | Value | Used by |
|----------|-------|---------|
| `DATABASE_URL` | `postgresql://YOUR_NEON_USER:YOUR_NEON_PASSWORD@YOUR_NEON_HOST-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require` | App + Python |
| `DIRECT_DATABASE_URL` | `postgresql://YOUR_NEON_USER:YOUR_NEON_PASSWORD@YOUR_NEON_HOST.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require` | Prisma migrations |

The only difference is `-pooler` in the hostname. Pooled = app connections. Direct = migration commands.

---

## Ongoing Maintenance

- **Scraper runs automatically** 7am–4pm on Mac Mini (random 40–90 min intervals)
- **Nightly full scrape** at 6am (marks inactive listings, retrains ML model)
- **New listings** get erfpacht extracted, descriptions translated, analytics updated per cycle
- **Vercel** auto-deploys on push to `main` (once connected to GitHub)
- **Monitor** scraper health: `ssh mac-mini "tail -20 ~/ground-control/logs/scheduler.log"`
