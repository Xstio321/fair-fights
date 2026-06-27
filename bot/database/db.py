import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "fights.db"


def extract_zone_from_title(embed_title):
    if not embed_title:
        return None

    match = re.search(r"\bin\s+(.+)$", embed_title.strip(), re.IGNORECASE)
    return match.group(1).strip() if match else None


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                scoreboard_code TEXT UNIQUE NOT NULL,
                fight_url TEXT NOT NULL,
                discord_message_id TEXT,

                fight_timestamp TEXT,

                zone TEXT,

                winner_name TEXT,
                winner_class TEXT,

                loser_1_name TEXT,
                loser_1_class TEXT,
                loser_2_name TEXT,
                loser_2_class TEXT,
                loser_3_name TEXT,
                loser_3_class TEXT,
                loser_4_name TEXT,
                loser_4_class TEXT,
                loser_5_name TEXT,
                loser_5_class TEXT,
                loser_6_name TEXT,
                loser_6_class TEXT,
                loser_7_name TEXT,
                loser_7_class TEXT,
                loser_8_name TEXT,
                loser_8_class TEXT,

                duration TEXT
            )
        """)

        # Spalte nachrüsten falls DB schon existiert (ohne discord_message_id)
        try:
            conn.execute("ALTER TABLE fights ADD COLUMN discord_message_id TEXT")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits

        # Index auf fight_timestamp für schnelle Zeitfilter
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON fights(fight_timestamp)")
        # Index auf discord_message_id für schnellen Max-Lookup
        conn.execute("CREATE INDEX IF NOT EXISTS idx_message_id ON fights(discord_message_id)")

        conn.commit()


def get_latest_message_id():
    """Gibt die höchste Discord Message-ID aus der DB zurück, oder None."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT discord_message_id FROM fights "
                "WHERE discord_message_id IS NOT NULL "
                "ORDER BY CAST(discord_message_id AS INTEGER) DESC LIMIT 1"
            ).fetchone()
            return int(row[0]) if row and row[0] else None
    except Exception:
        return None


def save_fight(
    scoreboard_code,
    fight_url,
    fight_timestamp,
    zone,
    winner_name,
    winner_class,
    losers,
    duration,
    discord_message_id=None,
):
    init_db()

    losers = losers[:8]

    loser_values = {}

    for i in range(1, 9):
        if i <= len(losers):
            loser_values[f"loser_{i}_name"] = losers[i - 1].get("name")
            loser_values[f"loser_{i}_class"] = losers[i - 1].get("class")
        else:
            loser_values[f"loser_{i}_name"] = None
            loser_values[f"loser_{i}_class"] = None

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO fights (
                scoreboard_code,
                fight_url,
                discord_message_id,
                fight_timestamp,
                zone,
                winner_name,
                winner_class,

                loser_1_name,
                loser_1_class,
                loser_2_name,
                loser_2_class,
                loser_3_name,
                loser_3_class,
                loser_4_name,
                loser_4_class,
                loser_5_name,
                loser_5_class,
                loser_6_name,
                loser_6_class,
                loser_7_name,
                loser_7_class,
                loser_8_name,
                loser_8_class,

                duration
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(scoreboard_code) DO UPDATE SET
                fight_url = excluded.fight_url,
                discord_message_id = COALESCE(excluded.discord_message_id, fights.discord_message_id),
                fight_timestamp = excluded.fight_timestamp,
                zone = excluded.zone,
                winner_name = excluded.winner_name,
                winner_class = excluded.winner_class,

                loser_1_name = excluded.loser_1_name,
                loser_1_class = excluded.loser_1_class,
                loser_2_name = excluded.loser_2_name,
                loser_2_class = excluded.loser_2_class,
                loser_3_name = excluded.loser_3_name,
                loser_3_class = excluded.loser_3_class,
                loser_4_name = excluded.loser_4_name,
                loser_4_class = excluded.loser_4_class,
                loser_5_name = excluded.loser_5_name,
                loser_5_class = excluded.loser_5_class,
                loser_6_name = excluded.loser_6_name,
                loser_6_class = excluded.loser_6_class,
                loser_7_name = excluded.loser_7_name,
                loser_7_class = excluded.loser_7_class,
                loser_8_name = excluded.loser_8_name,
                loser_8_class = excluded.loser_8_class,

                duration = excluded.duration
        """, (
            scoreboard_code,
            fight_url,
            str(discord_message_id) if discord_message_id else None,
            fight_timestamp,
            zone,
            winner_name,
            winner_class,

            loser_values["loser_1_name"],
            loser_values["loser_1_class"],
            loser_values["loser_2_name"],
            loser_values["loser_2_class"],
            loser_values["loser_3_name"],
            loser_values["loser_3_class"],
            loser_values["loser_4_name"],
            loser_values["loser_4_class"],
            loser_values["loser_5_name"],
            loser_values["loser_5_class"],
            loser_values["loser_6_name"],
            loser_values["loser_6_class"],
            loser_values["loser_7_name"],
            loser_values["loser_7_class"],
            loser_values["loser_8_name"],
            loser_values["loser_8_class"],

            duration
        ))

        conn.commit()
    init_db()

    losers = losers[:8]

    loser_values = {}

    for i in range(1, 9):
        if i <= len(losers):
            loser_values[f"loser_{i}_name"] = losers[i - 1].get("name")
            loser_values[f"loser_{i}_class"] = losers[i - 1].get("class")
        else:
            loser_values[f"loser_{i}_name"] = None
            loser_values[f"loser_{i}_class"] = None

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO fights (
                scoreboard_code,
                fight_url,
                fight_timestamp,
                zone,
                winner_name,
                winner_class,

                loser_1_name,
                loser_1_class,
                loser_2_name,
                loser_2_class,
                loser_3_name,
                loser_3_class,
                loser_4_name,
                loser_4_class,
                loser_5_name,
                loser_5_class,
                loser_6_name,
                loser_6_class,
                loser_7_name,
                loser_7_class,
                loser_8_name,
                loser_8_class,

                duration
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(scoreboard_code) DO UPDATE SET
                fight_url = excluded.fight_url,
                fight_timestamp = excluded.fight_timestamp,
                zone = excluded.zone,
                winner_name = excluded.winner_name,
                winner_class = excluded.winner_class,

                loser_1_name = excluded.loser_1_name,
                loser_1_class = excluded.loser_1_class,
                loser_2_name = excluded.loser_2_name,
                loser_2_class = excluded.loser_2_class,
                loser_3_name = excluded.loser_3_name,
                loser_3_class = excluded.loser_3_class,
                loser_4_name = excluded.loser_4_name,
                loser_4_class = excluded.loser_4_class,
                loser_5_name = excluded.loser_5_name,
                loser_5_class = excluded.loser_5_class,
                loser_6_name = excluded.loser_6_name,
                loser_6_class = excluded.loser_6_class,
                loser_7_name = excluded.loser_7_name,
                loser_7_class = excluded.loser_7_class,
                loser_8_name = excluded.loser_8_name,
                loser_8_class = excluded.loser_8_class,

                duration = excluded.duration
        """, (
            scoreboard_code,
            fight_url,
            fight_timestamp,
            zone,
            winner_name,
            winner_class,

            loser_values["loser_1_name"],
            loser_values["loser_1_class"],
            loser_values["loser_2_name"],
            loser_values["loser_2_class"],
            loser_values["loser_3_name"],
            loser_values["loser_3_class"],
            loser_values["loser_4_name"],
            loser_values["loser_4_class"],
            loser_values["loser_5_name"],
            loser_values["loser_5_class"],
            loser_values["loser_6_name"],
            loser_values["loser_6_class"],
            loser_values["loser_7_name"],
            loser_values["loser_7_class"],
            loser_values["loser_8_name"],
            loser_values["loser_8_class"],

            duration
        ))

        conn.commit()