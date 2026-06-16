"""
DAoC 8v8 Fair Fight Fetcher
Holt alle Fights vom normalen Endpoint, filtert auf exakt 8v8 (16 Spieler total),
speichert in fights_8v8.db – vollständig unabhängig von fights.db.
"""

import requests
import sqlite3
import time
import logging
import subprocess
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL      = "https://eden-daoc.net"
LIST_URL      = f"{BASE_URL}/hrald/proxy.php?fights/list"
DETAIL_URL    = f"{BASE_URL}/fghts/fight.php?"
DB_PATH       = "fights_8v8.db"
POLL_INTERVAL = 300

COOKIES = {
    "eden_daoc_sid": "a8320f13bee0f757a8523a5b6315f3fc",
    "eden_daoc_u":   "39665",
}
HEADERS = {
    "X-Herald-Api":     "minified",
    "X-Requested-With": "XMLHttpRequest",
    "Accept":           "application/json, text/javascript, */*; q=0.01",
    "User-Agent":       "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15",
    "Referer":          f"{BASE_URL}/fights",
}

def init_db(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS fights (
            id          TEXT PRIMARY KEY,
            started_at  TEXT NOT NULL,
            duration    INTEGER NOT NULL,
            zone_id     INTEGER,
            fetched_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fight_groups (
            fight_id    TEXT NOT NULL REFERENCES fights(id),
            side        TEXT NOT NULL CHECK(side IN ('a','b')),
            leader      TEXT NOT NULL,
            won         INTEGER NOT NULL CHECK(won IN (0,1)),
            realm       INTEGER,
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
            dmg_done    INTEGER DEFAULT 0,
            dmg_taken   INTEGER DEFAULT 0,
            heal_done   INTEGER DEFAULT 0,
            deaths      INTEGER DEFAULT 0,
            PRIMARY KEY (fight_id, player_id)
        );
    """)
    con.commit()
    return con

def make_session():
    s = requests.Session()
    s.cookies.update(COOKIES)
    s.headers.update(HEADERS)
    return s

def fetch_fight_list(session):
    r = session.get(LIST_URL, timeout=15)
    if r.status_code == 403:
        raise Exception("HTTP 403 - Session abgelaufen")
    r.raise_for_status()
    data = r.json()
    return [v for k, v in data.items() if k != "t" and isinstance(v, dict) and "id" in v]

def fetch_fight_detail(session, fight_id):
    r = session.get(DETAIL_URL + fight_id, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()

def race_to_realm(race_id):
    if race_id in {1,2,3,4,13,16}: return 1
    if race_id in {5,6,7,8,14,17,20}: return 2
    if race_id in {9,10,11,12,15,18,21}: return 3
    return 0

def determine_winner(fight):
    deaths_a = sum(p.get("s",{}).get("d",0) for p in fight["a"].get("p",[]))
    deaths_b = sum(p.get("s",{}).get("d",0) for p in fight["b"].get("p",[]))
    if deaths_b > deaths_a: return "a","b"
    if deaths_a > deaths_b: return "b","a"
    return "a","b"

def save_fight(con, fight):
    fight_id = fight["id"]
    if con.execute("SELECT 1 FROM fights WHERE id=?", (fight_id,)).fetchone():
        return False

    players_a = fight["a"].get("p", [])
    players_b = fight["b"].get("p", [])

    # Nur echte 8v8 mit exakt 8 Spielern pro Seite
    if len(players_a) != 8 or len(players_b) != 8:
        return False

    winner_side, _ = determine_winner(fight)
    now = datetime.now(timezone.utc).isoformat()

    con.execute("""
        INSERT INTO fights (id, started_at, duration, zone_id, fetched_at)
        VALUES (?, ?, ?, ?, ?)
    """, (fight_id, fight.get("s"), int(fight.get("d",0)), fight.get("z"), now))

    for side in ("a","b"):
        group = fight[side]
        won = 1 if side == winner_side else 0
        players = group.get("p",[])
        # Erster Spieler = Gruppenleader
        leader = players[0].get("n","Unknown") if players else "Unknown"
        realm = race_to_realm(players[0].get("r",0)) if players else None

        con.execute("""
            INSERT INTO fight_groups (fight_id, side, leader, won, realm)
            VALUES (?, ?, ?, ?, ?)
        """, (fight_id, side, leader, won, realm))

        for p in players:
            s = p.get("s",{})
            con.execute("""
                INSERT OR IGNORE INTO fight_players
                    (fight_id, side, player_id, name, class_id, race_id,
                     realm_pts, dmg_done, dmg_taken, heal_done, deaths)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fight_id, side,
                p.get("id",0), p.get("n",""), p.get("c",0), p.get("r",0),
                p.get("rp"),
                s.get("dd",0), s.get("dt",0), s.get("hd",0), s.get("d",0),
            ))

    con.commit()
    return True

def run_once(session, con):
    log.info("Fetching fight list...")
    try:
        fights = fetch_fight_list(session)
    except Exception as e:
        log.error(f"Fehler: {e}")
        return
    log.info(f"  → {len(fights)} fights gefunden")

    new_count = 0
    for summary in fights:
        fight_id = summary.get("id")
        if not fight_id:
            continue
        if con.execute("SELECT 1 FROM fights WHERE id=?", (fight_id,)).fetchone():
            continue
        try:
            detail = fetch_fight_detail(session, fight_id)
            time.sleep(0.3)
        except Exception as e:
            log.warning(f"  Fehler bei {fight_id}: {e}")
            continue
        if not detail:
            continue
        if save_fight(con, detail):
            new_count += 1
            log.info(f"  ✓ Neuer 8v8 Fight: {fight_id}")

    log.info(f"Fertig. {new_count} neue 8v8 Fights gespeichert.")
    subprocess.run(["python", "elo_calculator_8v8.py"], check=False)

def run_loop():
    session = make_session()
    con = init_db(DB_PATH)
    log.info(f"8v8 Fetcher gestartet. Polling alle {POLL_INTERVAL}s.")
    while True:
        try:
            run_once(session, con)
        except Exception as e:
            log.error(f"Fehler: {e}", exc_info=True)
        log.info(f"Warte {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db(DB_PATH)
        log.info(f"DB initialisiert: {DB_PATH}")
    elif args.once:
        session = make_session()
        con = init_db(DB_PATH)
        run_once(session, con)
    else:
        run_loop()