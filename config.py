"""Configuration for the RowRunner label print worker.

All values come from environment variables (loaded from a local .env if present).
Nothing secret lives here — the worker uses ONLY the public Supabase anon key.
"""
import os

# Load .env if python-dotenv is installed. It's optional: if the founder exports
# the vars another way (systemd unit, Windows env, launchd), the worker still runs.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _bool(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.environ.get(name, "").strip())
    except (ValueError, AttributeError):
        return default


# ── Supabase (shared orders table) ──────────────────────────────────────────
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://kboevpucqjoftgmhrkzq.supabase.co"
).rstrip("/")
# PUBLIC anon key only. Reads are public; the two RPCs are security-definer.
# NEVER put the service_role key on the venue PC.
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# ── Printer (Brother QL-820NWB) ─────────────────────────────────────────────
PRINTER_MODEL = os.environ.get("PRINTER_MODEL", "QL-820NWB")
PRINTER_BACKEND = os.environ.get("PRINTER_BACKEND", "network")  # network | pyusb | linux_kernel
PRINTER_IDENTIFIER = os.environ.get("PRINTER_IDENTIFIER", "tcp://192.168.1.50:9100")

# ── Label ───────────────────────────────────────────────────────────────────
LABEL_SIZE = os.environ.get("LABEL_SIZE", "62")   # "62" continuous or "29x90" die-cut
LABEL_RED = _bool("LABEL_RED", True)               # print ⚠ note in red (needs black/red roll)
LABEL_LOGO = _bool("LABEL_LOGO", True)             # show the RowRunner logo at the top

# Optional font overrides (absolute paths to .ttf/.ttc). Blank = auto-detect.
FONT_BOLD = os.environ.get("FONT_BOLD", "").strip()
FONT_REGULAR = os.environ.get("FONT_REGULAR", "").strip()

# ── Behaviour ───────────────────────────────────────────────────────────────
DRY_RUN = _bool("DRY_RUN", True)     # 1 = render PNG to out/ only, no hardware
POLL_SECONDS = _int("POLL_SECONDS", 4)
OUT_DIR = os.environ.get("OUT_DIR", "out")

# Trigger guard: a delivered order (stage 4) never needs a kitchen label, so we
# never print for it even if it somehow has ready_at set and printed_at null.
# Stage: 0 received · 1 preparing · 2 picked up · 3 on the way · 4 delivered.
MAX_PRINT_STAGE = _int("MAX_PRINT_STAGE", 3)  # print only when stage <= this


def missing():
    """Return a list of required settings that are unset, for a clear startup error."""
    gaps = []
    if not SUPABASE_URL:
        gaps.append("SUPABASE_URL")
    if not SUPABASE_ANON_KEY:
        gaps.append("SUPABASE_ANON_KEY")
    return gaps
