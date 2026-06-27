"""
Zentrale Konfiguration für den DAoC Fair Fights Tracker.
Alle Einstellungen können über Umgebungsvariablen oder eine .env-Datei
im export/-Ordner überschrieben werden.

Wichtigste Variablen für den Server-Umzug:
  JSON_PATH   → Pfad zu data.json (Webserver-Ordner)
  DB_PATH     → Pfad zur SQLite-Datenbank
  GIT_PUSH    → "false" um den Git-Push zu deaktivieren
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    # .env im Root-Ordner (fair-fights/.env) — eine Ebene über export/
    _ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_ENV_PATH)
except ImportError:
    pass

_ROOT = Path(__file__).resolve().parent.parent
_EXPORT = Path(__file__).resolve().parent


def _optional(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


# ── Datenbank ──────────────────────────────────────────────────────────────────
DB_PATH  = _optional("DB_PATH",  str(_ROOT / "data" / "fights.db"))
LOG_PATH = _optional("LOG_PATH", str(_EXPORT / "export.log"))

# ── Web-Output ────────────────────────────────────────────────────────────────
# Auf dem Server z.B. auf "/var/www/fair-fights/" setzen
JSON_PATH = _optional("JSON_PATH", str(_ROOT / "web" / "data.json"))

# ── Export-Verhalten ──────────────────────────────────────────────────────────
# GIT_PUSH="false" deaktiviert den automatischen Git-Push (für Server-Hosting)
GIT_PUSH        = _optional("GIT_PUSH", "true").lower() == "true"
EXPORT_INTERVAL = int(_optional("EXPORT_INTERVAL", "300"))  # Sekunden

# ── ELO-System ────────────────────────────────────────────────────────────────
ELO_START_DATE  = _optional("ELO_START_DATE",  "2026-06-01")
ELO_MIN_FIGHTS  = int(_optional("ELO_MIN_FIGHTS",  "10"))
ELO_DEFAULT     = int(_optional("ELO_DEFAULT",     "1500"))
ELO_RESET_MONTHS= int(_optional("ELO_RESET_MONTHS","3"))