"""
Ground Control — Scrape Daemon Scheduler
=========================================
Long-running daemon that orchestrates scraping, enrichment, translation,
and notifications between 07:00-16:00 Amsterdam time.

Usage:
    python scheduler.py          # Start daemon (runs until 16:00)
    python scheduler.py --once   # Run a single cycle and exit
"""

import argparse
import json
import logging
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
LOGS_DIR = PROJECT_ROOT / "logs"
STATE_FILE = PROJECT_ROOT / "scheduler_state.json"
TIMEZONE = ZoneInfo("Europe/Amsterdam")

WINDOW_START_HOUR = 7
WINDOW_END_HOUR = 16
MIN_INTERVAL_MINUTES = 40
MAX_INTERVAL_MINUTES = 90

# Ensure logs directory exists
LOGS_DIR.mkdir(exist_ok=True)

# Logging setup — both file and console
log_file = LOGS_DIR / "scheduler.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scheduler")

# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    log.info("Received signal %d, shutting down gracefully...", signum)
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ──────────────────────────────────────────────────────────────────────
# Time helpers
# ──────────────────────────────────────────────────────────────────────

def _now_ams() -> datetime:
    """Current time in Amsterdam timezone."""
    return datetime.now(TIMEZONE)


def _in_window() -> bool:
    """Check if current Amsterdam time is within the scraping window."""
    now = _now_ams()
    return WINDOW_START_HOUR <= now.hour < WINDOW_END_HOUR


def _seconds_until_window() -> float:
    """Seconds until the next 07:00 Amsterdam time."""
    now = _now_ams()
    tomorrow_start = now.replace(hour=WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
    if tomorrow_start <= now:
        tomorrow_start += timedelta(days=1)
    return (tomorrow_start - now).total_seconds()


# ──────────────────────────────────────────────────────────────────────
# State management
# ──────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_run": None, "next_run": None, "cycle_count": 0}


def _save_state(state: dict):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except OSError as e:
        log.warning("Could not save state: %s", e)


# ──────────────────────────────────────────────────────────────────────
# Cycle steps
# ──────────────────────────────────────────────────────────────────────

def _run_step(name: str, cmd: list[str], timeout: int = 600) -> bool:
    """Run a subprocess step. Returns True on success."""
    log.info("  [%s] Starting...", name)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            # Log last few lines of output
            output_lines = (result.stdout or "").strip().split("\n")
            for line in output_lines[-3:]:
                if line.strip():
                    log.info("  [%s] %s", name, line.strip())
            log.info("  [%s] Done (exit 0)", name)
            return True
        else:
            log.error("  [%s] Failed (exit %d)", name, result.returncode)
            stderr = (result.stderr or "").strip()
            if stderr:
                for line in stderr.split("\n")[-5:]:
                    log.error("  [%s] stderr: %s", name, line)
            return False
    except subprocess.TimeoutExpired:
        log.error("  [%s] Timed out after %ds", name, timeout)
        return False
    except Exception as e:
        log.error("  [%s] Error: %s", name, e)
        return False


def _find_python() -> str:
    """Find the Python executable (prefer venv)."""
    venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def run_cycle() -> dict:
    """
    Run one complete scrape-enrich-analyze-notify cycle.
    Returns stats dict with results from each step.
    """
    python = _find_python()
    cycle_stats = {
        "started_at": _now_ams().isoformat(),
        "steps": {},
    }

    log.info("=" * 60)
    log.info("CYCLE START — %s", _now_ams().strftime("%Y-%m-%d %H:%M:%S %Z"))
    log.info("=" * 60)

    # Step 1: Delta scrape
    cycle_stats["steps"]["scraper"] = _run_step(
        "scraper",
        [python, "scraper.py", "--city", "amsterdam", "--type", "buy", "--delta", "--db", "ground_control.db"],
        timeout=300,
    )

    # Step 2: Detail enrichment (limit 20)
    cycle_stats["steps"]["enricher"] = _run_step(
        "enricher",
        [python, "detail_enricher.py", "--limit", "20"],
        timeout=600,
    )

    # Step 3: Erfpacht extraction
    cycle_stats["steps"]["erfpacht"] = _run_step(
        "erfpacht",
        [python, "erfpacht_extractor.py"],
        timeout=120,
    )

    # Step 4: Translation (limit 20)
    cycle_stats["steps"]["translator"] = _run_step(
        "translator",
        [python, "translator.py", "--limit", "20"],
        timeout=300,
    )

    # Step 5: Neighbourhood analytics
    cycle_stats["steps"]["analytics"] = _run_step(
        "analytics",
        [python, "neighbourhood_analytics.py"],
        timeout=120,
    )

    # Step 6: Notifications (handled via notifier import)
    try:
        from db import get_dict_cursor
        with get_dict_cursor() as cur:
            cur.execute("""
                SELECT global_id, address, neighbourhood, price, price_numeric,
                       living_area, bedrooms, erfpacht_status
                FROM listings
                WHERE is_active = true
                  AND first_seen >= NOW() - INTERVAL '2 hours'
                ORDER BY first_seen DESC
            """)
            new_listings = [dict(r) for r in cur.fetchall()]

        if new_listings:
            from notifier import notify_new_listings
            sent = notify_new_listings(new_listings)
            cycle_stats["steps"]["notifier"] = sent > 0
            cycle_stats["new_listings_notified"] = sent
            log.info("  [notifier] Sent %d notifications for %d new listings", sent, len(new_listings))
        else:
            cycle_stats["steps"]["notifier"] = True
            cycle_stats["new_listings_notified"] = 0
            log.info("  [notifier] No new listings to notify about")
    except Exception as e:
        log.error("  [notifier] Error: %s", e)
        cycle_stats["steps"]["notifier"] = False

    cycle_stats["finished_at"] = _now_ams().isoformat()
    successful = sum(1 for v in cycle_stats["steps"].values() if v)
    total = len(cycle_stats["steps"])
    log.info("-" * 60)
    log.info("CYCLE DONE — %d/%d steps succeeded", successful, total)
    log.info("-" * 60)

    return cycle_stats


# ──────────────────────────────────────────────────────────────────────
# Daemon loop
# ──────────────────────────────────────────────────────────────────────

def run_daemon():
    """Main daemon loop. Runs cycles within the time window."""
    state = _load_state()
    log.info("Scheduler starting — Amsterdam time: %s", _now_ams().strftime("%Y-%m-%d %H:%M:%S %Z"))
    log.info("Window: %02d:00-%02d:00, interval: %d-%d min",
             WINDOW_START_HOUR, WINDOW_END_HOUR,
             MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES)

    while not _shutdown:
        if not _in_window():
            sleep_secs = _seconds_until_window()
            log.info("Outside window. Sleeping %.0f minutes until %02d:00",
                     sleep_secs / 60, WINDOW_START_HOUR)
            state["next_run"] = (_now_ams() + timedelta(seconds=sleep_secs)).isoformat()
            _save_state(state)

            # Sleep in chunks so we can respond to signals
            while sleep_secs > 0 and not _shutdown:
                chunk = min(sleep_secs, 60)
                time.sleep(chunk)
                sleep_secs -= chunk
            continue

        # Run a cycle
        cycle_stats = run_cycle()
        state["last_run"] = _now_ams().isoformat()
        state["cycle_count"] = state.get("cycle_count", 0) + 1

        if _shutdown:
            break

        # Sleep random interval before next cycle
        interval = random.randint(MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES)
        next_run = _now_ams() + timedelta(minutes=interval)
        state["next_run"] = next_run.isoformat()
        _save_state(state)

        log.info("Next cycle in %d minutes (at %s)", interval, next_run.strftime("%H:%M"))

        sleep_secs = interval * 60
        while sleep_secs > 0 and not _shutdown:
            chunk = min(sleep_secs, 60)
            time.sleep(chunk)
            sleep_secs -= chunk

    # Clean shutdown
    log.info("Scheduler stopped after %d cycles", state.get("cycle_count", 0))
    state["next_run"] = None
    _save_state(state)

    try:
        from db import close_pool
        close_pool()
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground Control — Scrape Daemon Scheduler")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    args = parser.parse_args()

    if args.once:
        log.info("Running single cycle...")
        stats = run_cycle()
        print(json.dumps(stats, indent=2, default=str))
        try:
            from db import close_pool
            close_pool()
        except Exception:
            pass
    else:
        run_daemon()
