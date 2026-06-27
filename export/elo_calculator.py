"""
ELO-Ranking Calculator für den DAoC Fair Fights Tracker.

Berechnet ELO-Ratings aus 1v1 Kämpfen seit dem letzten Reset-Datum.
Reset-Rhythmus: alle 3 Monate ab ELO_START_DATE (config).
Mindest-Fights für Aufnahme in die Rangliste: ELO_MIN_FIGHTS (config).
K-Faktor: 32 (< 30 Fights), 16 (≥ 30 Fights).
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone, date
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
import config

# ── Konfiguration ──────────────────────────────────────────────────────────────
DB_PATH          = Path(config.DB_PATH)
_WEB_DIR         = Path(config.JSON_PATH).parent
ELO_JSON_PATH    = _WEB_DIR / "elo.json"
ELO_HISTORY_PATH = _WEB_DIR / "elo_history.json"

ELO_START_DATE = date.fromisoformat(config.ELO_START_DATE)
RESET_MONTHS   = config.ELO_RESET_MONTHS
DEFAULT_ELO    = config.ELO_DEFAULT
MIN_FIGHTS     = config.ELO_MIN_FIGHTS
K_HIGH         = 32
K_LOW          = 16
K_THRESHOLD    = 30


# ── Reset-Datum berechnen ──────────────────────────────────────────────────────
def get_current_reset_date(today: date = None) -> date:
    """Gibt das aktuellste Reset-Datum zurück (1. Juni, Sept, Dez, März...)."""
    if today is None:
        today = date.today()

    # Reset-Monate: 6, 9, 12, 3 (relativ zu ELO_START_DATE)
    start = ELO_START_DATE
    reset = start

    while True:
        month = reset.month + RESET_MONTHS
        year  = reset.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        next_reset = date(year, month, 1)
        if next_reset > today:
            break
        reset = next_reset

    return reset


def get_next_reset_date(today: date = None) -> date:
    """Gibt das nächste Reset-Datum zurück."""
    if today is None:
        today = date.today()
    current = get_current_reset_date(today)
    month   = current.month + RESET_MONTHS
    year    = current.year + (month - 1) // 12
    month   = ((month - 1) % 12) + 1
    return date(year, month, 1)


# ── ELO-Berechnung ────────────────────────────────────────────────────────────
def expected_score(elo_a: float, elo_b: float) -> float:
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def k_factor(fights_played: int) -> int:
    return K_LOW if fights_played >= K_THRESHOLD else K_HIGH


def calculate_elo(fights: list) -> dict:
    elos        = defaultdict(lambda: float(DEFAULT_ELO))
    peak_elos   = defaultdict(lambda: float(DEFAULT_ELO))
    fights_cnt  = defaultdict(int)
    wins        = defaultdict(int)
    losses      = defaultdict(int)
    class_info  = {}
    fight_history = defaultdict(list)  # name -> [{timestamp, opponent, result, elo_change, elo_after}]

    for f in sorted(fights, key=lambda x: x["timestamp"]):
        w_name = f["winner"]["name"]
        l_name = f["losers"][0]["name"]

        class_info[w_name] = (f["winner"]["class_id"], f["winner"]["class"])
        class_info[l_name] = (f["losers"][0]["class_id"], f["losers"][0]["class"])

        elo_w = elos[w_name]
        elo_l = elos[l_name]

        k_w = k_factor(fights_cnt[w_name])
        k_l = k_factor(fights_cnt[l_name])

        exp_w = expected_score(elo_w, elo_l)
        exp_l = expected_score(elo_l, elo_w)

        new_elo_w = elo_w + k_w * (1 - exp_w)
        new_elo_l = elo_l + k_l * (0 - exp_l)

        change_w = new_elo_w - elo_w
        change_l = new_elo_l - elo_l

        elos[w_name] = new_elo_w
        elos[l_name] = new_elo_l

        if elos[w_name] > peak_elos[w_name]:
            peak_elos[w_name] = elos[w_name]
        if elos[l_name] > peak_elos[l_name]:
            peak_elos[l_name] = elos[l_name]

        ts = f["timestamp"].isoformat()
        fight_history[w_name].append({
            "timestamp": ts,
            "opponent": l_name,
            "opponent_class_id": f["losers"][0]["class_id"],
            "result": "W",
            "elo_change": round(change_w, 2),
            "elo_after": round(new_elo_w, 2),
        })
        fight_history[l_name].append({
            "timestamp": ts,
            "opponent": w_name,
            "opponent_class_id": f["winner"]["class_id"],
            "result": "L",
            "elo_change": round(change_l, 2),
            "elo_after": round(new_elo_l, 2),
        })

        fights_cnt[w_name] += 1
        fights_cnt[l_name] += 1
        wins[w_name]        += 1
        losses[l_name]      += 1

    result = {}
    for name in set(list(wins.keys()) + list(losses.keys())):
        total = fights_cnt[name]
        if total < MIN_FIGHTS:
            continue
        cid, cname = class_info.get(name, (None, "Unknown"))
        result[name] = {
            "elo":          round(elos[name], 2),
            "peak_elo":     round(peak_elos[name], 2),
            "fights":       total,
            "wins":         wins[name],
            "losses":       losses[name],
            "winrate":      round(wins[name] / total * 100) if total else 0,
            "class_id":     cid,
            "class_name":   cname,
            "fight_history": list(reversed(fight_history[name])),  # neueste zuerst
        }

    return result


# ── Laden aus DB ───────────────────────────────────────────────────────────────
def load_1v1_fights_since(con: sqlite3.Connection, since: date) -> list:
    """Lädt alle 1v1 Fights seit einem Datum aus der DB."""
    since_str = datetime(since.year, since.month, since.day,
                         tzinfo=timezone.utc).isoformat()
    rows = con.execute("""
        SELECT fight_timestamp, winner_name, winner_class,
               loser_1_name, loser_1_class
        FROM fights
        WHERE fight_timestamp >= ?
          AND loser_1_name IS NOT NULL
          AND loser_2_name IS NULL
          AND winner_name IS NOT NULL
          AND winner_class IS NOT NULL
          AND loser_1_class IS NOT NULL
        ORDER BY fight_timestamp ASC
    """, (since_str,)).fetchall()

    fights = []
    for ts_str, w_name, w_cls, l_name, l_cls in rows:
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        fights.append({
            "timestamp": ts,
            "winner": {
                "name":     w_name,
                "class":    w_cls,
                "class_id": class_id_for(w_cls),
            },
            "losers": [{
                "name":     l_name,
                "class":    l_cls,
                "class_id": class_id_for(l_cls),
            }],
        })
    return fights


# Minimale class_id_for — gleiche Logik wie in export_json.py
_CLASS_NAME_TO_ID: dict = {}

def _init_class_map(con: sqlite3.Connection):
    global _CLASS_NAME_TO_ID
    if _CLASS_NAME_TO_ID:
        return
    rows = con.execute(
        "SELECT DISTINCT winner_class FROM fights WHERE winner_class IS NOT NULL"
    ).fetchall()
    # Importiere aus export_json falls möglich, sonst einfache Zuordnung
    try:
        import sys, importlib
        sys.path.insert(0, str(Path(__file__).parent))
        ej = importlib.import_module("export_json")
        _CLASS_NAME_TO_ID = {name: cid for cid, name in ej.CLASS_ID_TO_NAME.items()}
    except Exception:
        pass

def class_id_for(class_name: str):
    if not _CLASS_NAME_TO_ID:
        return None
    return _CLASS_NAME_TO_ID.get(class_name)


# ── Export ─────────────────────────────────────────────────────────────────────
def run_export():
    today        = date.today()
    reset_date   = get_current_reset_date(today)
    next_reset   = get_next_reset_date(today)

    con = sqlite3.connect(str(DB_PATH))
    _init_class_map(con)

    fights = load_1v1_fights_since(con, reset_date)
    con.close()

    elo_data = calculate_elo(fights)

    # Ranking sortiert nach ELO
    # fight_history aus dem Ranking entfernen — zu groß für elo.json
    # Wird in elo_fights.json gespeichert und lazy geladen
    elo_fights = {}
    for name, data in elo_data.items():
        history = data.pop("fight_history", [])
        elo_fights[name] = history

    ranking = sorted(elo_data.items(), key=lambda x: -x[1]["elo"])
    ranking_list = [
        {"rank": i + 1, "name": name, **data}
        for i, (name, data) in enumerate(ranking)
    ]

    # elo_fights.json separat speichern
    elo_fights_path = _WEB_DIR / "elo_fights.json"
    with open(elo_fights_path, "w") as f:
        json.dump(elo_fights, f, separators=(",", ":"))

    # Season-History: Top 10 Peak ELOs der aktuellen Season speichern
    history_path = ELO_HISTORY_PATH
    try:
        with open(history_path) as f:
            history = json.load(f)
    except Exception:
        history = []

    # Aktuelle Season in History updaten (oder neu anlegen)
    season_key = reset_date.isoformat()
    season_entry = next((s for s in history if s["season_start"] == season_key), None)
    top10_peak = sorted(elo_data.items(), key=lambda x: -x[1]["peak_elo"])[:10]
    current_season_data = {
        "season_start": season_key,
        "season_end":   next_reset.isoformat(),
        "top10": [
            {"rank": i+1, "name": name,
             "peak_elo": data["peak_elo"],
             "elo": data["elo"],
             "class_id": data["class_id"],
             "class_name": data["class_name"]}
            for i, (name, data) in enumerate(top10_peak)
        ]
    }
    if season_entry:
        history[history.index(season_entry)] = current_season_data
    else:
        history.append(current_season_data)

    # History sortiert nach Season-Start (neueste zuerst)
    history.sort(key=lambda s: s["season_start"], reverse=True)
    with open(history_path, "w") as f:
        json.dump(history, f, separators=(",", ":"))

    output = {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "season_start":  reset_date.isoformat(),
        "next_reset":    next_reset.isoformat(),
        "reset_months":  RESET_MONTHS,
        "min_fights":    MIN_FIGHTS,
        "default_elo":   DEFAULT_ELO,
        "total_players": len(ranking_list),
        "ranking":       ranking_list,
        "by_player":     {name: data for name, data in elo_data.items()},
    }

    ELO_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ELO_JSON_PATH, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"  ✓ elo.json geschrieben ({len(ranking_list)} Spieler, "
          f"Season seit {reset_date}, nächster Reset {next_reset})")


if __name__ == "__main__":
    run_export()