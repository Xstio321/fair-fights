"""
DAoC Fair Fight Fetcher
Holt automatisch alle neuen Fights vom Server und speichert sie in SQLite.

Endpoints (aus fights.js reverse-engineered):
  Fight-Liste: GET /hrald/proxy.php?fights/list
  1v1 Filter:  GET /hrald/proxy.php?fights/list?min=1&max=1
  Nach Spieler: GET /hrald/proxy.php?fights/player/{name}
  Fight-Detail: GET /fghts/fight.php?{id}
"""

import requests
import sqlite3
import time
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# KONFIGURATION
# ──────────────────────────────────────────────
BASE_URL   = "https://eden-daoc.net"
LIST_URL   = f"{BASE_URL}/hrald/proxy.php?fights/list"
DETAIL_URL = f"{BASE_URL}/fghts/fight.php?"
DB_PATH    = "fights.db"
POLL_INTERVAL = 300  # Sekunden zwischen Abfragen (5 Minuten)

# Session-Cookies (einmalig aus dem Browser kopieren)
COOKIES = {
    "eden_daoc_sid": "2c74d8b84d64c93a4b89e961f6c4e49e",
    "eden_daoc_u":   "39665",
}

HEADERS = {
    "X-Herald-Api":      "minified",
    "X-Requested-With":  "XMLHttpRequest",
    "Accept":            "application/json, text/javascript, */*; q=0.01",
    "User-Agent":        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15",
    "Referer":           f"{BASE_URL}/fights",
}

# ──────────────────────────────────────────────
# DATENBANK
# ──────────────────────────────────────────────
def init_db(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS fights (
            id          TEXT PRIMARY KEY,
            started_at  TEXT NOT NULL,
            duration    INTEGER NOT NULL,
            zone_id     INTEGER,
            size        INTEGER,
            fetched_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fight_teams (
            fight_id    TEXT NOT NULL REFERENCES fights(id),
            side        TEXT NOT NULL CHECK(side IN ('a','b')),
            realm       INTEGER,
            won         INTEGER NOT NULL CHECK(won IN (0,1)),
            PRIMARY KEY (fight_id, side)
        );

        CREATE TABLE IF NOT EXISTS fight_players (
            fight_id    TEXT NOT NULL REFERENCES fights(id),
            side        TEXT NOT NULL CHECK(side IN ('a','b')),
            player_id   INTEGER NOT NULL,
            name        TEXT NOT NULL,
            class_id    INTEGER NOT NULL,
            race_id     INTEGER NOT NULL,
            realm_pts   INTEGER,
            mmr         INTEGER,
            dmg_done    INTEGER DEFAULT 0,
            dmg_taken   INTEGER DEFAULT 0,
            heal_done   INTEGER DEFAULT 0,
            heal_rcvd   INTEGER DEFAULT 0,
            deaths      INTEGER DEFAULT 0,
            PRIMARY KEY (fight_id, player_id)
        );
    """)
    con.commit()
    return con


# ──────────────────────────────────────────────
# API-AUFRUFE
# ──────────────────────────────────────────────
def make_session() -> requests.Session:
    s = requests.Session()
    s.cookies.update(COOKIES)
    s.headers.update(HEADERS)
    return s


def fetch_fight_list(session: requests.Session, min_size=1, max_size=8) -> list:
    url = LIST_URL
    extra = []
    if min_size != 1:
        extra.append(f"min={min_size}")
    if max_size != 8:
        extra.append(f"max={max_size}")
    if extra:
        url += "?" + "&".join(extra)
    log.debug(f"Fetching list: {url}")

    r = session.get(url, timeout=15)

    if r.status_code == 403:
        raise Exception("HTTP 403 - Session abgelaufen")

    r.raise_for_status()
    data = r.json()

    # Antwort ist {"0": {...}, "1": {...}, "t": ...}
    fights = []
    for key, val in data.items():
        if key == "t":
            continue
        if isinstance(val, dict) and "id" in val:
            fights.append(val)

    return fights


def fetch_fight_detail(session: requests.Session, fight_id: str):
    url = DETAIL_URL + fight_id
    log.debug(f"Fetching detail: {url}")

    r = session.get(url, timeout=15)
    if r.status_code == 404:
        log.warning(f"Fight {fight_id} nicht gefunden (404)")
        return None
    r.raise_for_status()
    return r.json()


# ──────────────────────────────────────────────
# DATEN PARSEN & SPEICHERN
# ──────────────────────────────────────────────
def race_to_realm(race_id: int) -> int:
    alb = {1, 2, 3, 4, 13, 16}
    mid = {5, 6, 7, 8, 14, 17, 20}
    hib = {9, 10, 11, 12, 15, 18, 21}
    if race_id in alb: return 1
    if race_id in mid: return 2
    if race_id in hib: return 3
    return 0


def determine_winner(fight: dict) -> tuple:
    """Verlierer hat deaths > 0, Gewinner hat deaths = 0."""
    deaths_a = sum(p.get("s", {}).get("d", 0) for p in fight["a"].get("p", []))
    deaths_b = sum(p.get("s", {}).get("d", 0) for p in fight["b"].get("p", []))
    if deaths_b > deaths_a:
        return "a", "b"
    if deaths_a > deaths_b:
        return "b", "a"
    return "a", "b"  # Fallback (unentschieden)


def save_fight(con: sqlite3.Connection, fight: dict) -> bool:
    fight_id = fight["id"]
    cur = con.cursor()

    if cur.execute("SELECT 1 FROM fights WHERE id=?", (fight_id,)).fetchone():
        return False

    winner_side, _ = determine_winner(fight)

    size_a = fight["a"].get("s", 1)
    size_b = fight["b"].get("s", 1)
    size   = max(size_a, size_b)

    def realm_from_players(group):
        players = group.get("p", [])
        if not players:
            return None
        return race_to_realm(players[0].get("r", 0))

    now = datetime.now(timezone.utc).isoformat()

    cur.execute("""
        INSERT INTO fights (id, started_at, duration, zone_id, size, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        fight_id,
        fight.get("s"),
        int(fight.get("d", 0)),
        fight.get("z"),
        size,
        now,
    ))

    for side in ("a", "b"):
        group = fight[side]
        won   = 1 if side == winner_side else 0
        realm = realm_from_players(group)

        cur.execute("""
            INSERT INTO fight_teams (fight_id, side, realm, won)
            VALUES (?, ?, ?, ?)
        """, (fight_id, side, realm, won))

        for p in group.get("p", []):
            stats = p.get("s", {})
            cur.execute("""
                INSERT OR IGNORE INTO fight_players
                    (fight_id, side, player_id, name, class_id, race_id,
                     realm_pts, mmr, dmg_done, dmg_taken, heal_done, heal_rcvd, deaths)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fight_id, side,
                p.get("id", 0),
                p.get("n", ""),
                p.get("c", 0),
                p.get("r", 0),
                p.get("rp"),
                p.get("m"),
                stats.get("dd", 0),
                stats.get("dt", 0),
                stats.get("hd", 0),
                stats.get("hr", 0),
                stats.get("d", 0),
            ))

    con.commit()
    return True


# ──────────────────────────────────────────────
# HAUPTSCHLEIFE
# ──────────────────────────────────────────────
def run_once(session: requests.Session, con: sqlite3.Connection, only_1v1=True):
    min_s = 1
    max_s = 1 if only_1v1 else 8

    log.info(f"Fetching fight list (size {min_s}v{min_s}–{max_s}v{max_s})...")
    try:
        fights_summary = fetch_fight_list(session, min_size=min_s, max_size=max_s)
    except Exception as e:
        log.error(f"Fehler beim Listenabruf: {e}")
        return

    log.info(f"  → {len(fights_summary)} Fights in der Liste")

    new_count = 0
    for summary in fights_summary:
        fight_id = summary.get("id")
        if not fight_id:
            continue

        cur = con.cursor()
        if cur.execute("SELECT 1 FROM fights WHERE id=?", (fight_id,)).fetchone():
            continue

        try:
            detail = fetch_fight_detail(session, fight_id)
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"  Fehler bei Fight {fight_id}: {e}")
            continue

        if not detail:
            continue

        if save_fight(con, detail):
            new_count += 1
            log.info(f"  ✓ Neuer Fight gespeichert: {fight_id}")

    log.info(f"Durchlauf fertig. {new_count} neue Fights gespeichert.")

    # Automatisch exportieren und pushen
    import subprocess
    subprocess.run(["python", "export_json.py"], check=False)
    subprocess.run(["python", "elo_calculator.py"], check=False)


def run_loop(only_1v1=True):
    session = make_session()
    con     = init_db(DB_PATH)

    log.info(f"Fight Fetcher gestartet. Polling alle {POLL_INTERVAL}s.")
    while True:
        try:
            run_once(session, con, only_1v1=only_1v1)
        except Exception as e:
            log.error(f"Unerwarteter Fehler: {e}", exc_info=True)

        log.info(f"Warte {POLL_INTERVAL}s bis zum nächsten Durchlauf...")
        time.sleep(POLL_INTERVAL)


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DAoC Fight Fetcher")
    parser.add_argument("--once",    action="store_true", help="Nur einmal fetchen, keine Schleife")
    parser.add_argument("--all",     action="store_true", help="Alle Größen (nicht nur 1v1)")
    parser.add_argument("--init-db", action="store_true", help="Nur DB initialisieren")
    args = parser.parse_args()

    if args.init_db:
        con = init_db(DB_PATH)
        log.info(f"Datenbank initialisiert: {DB_PATH}")
    elif args.once:
        session = make_session()
        con     = init_db(DB_PATH)
        run_once(session, con, only_1v1=not args.all)
    else:
        run_loop(only_1v1=not args.all)