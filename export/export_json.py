"""
Export-Script (v2): Liest die vom Discord-Bot gefüllte fights.db und
schreibt data.json für die Webseite.

Neues Schema (im Vergleich zum alten Eden-API-Fetcher):
  - Eine Zeile pro Fight: winner_name/winner_class + loser_1..8_name/_class
  - Kein Realm Rank (RR), keine Damage/Healing-Werte, keine Player-IDs
  - "Underdog"-Fights ergeben sich direkt daraus, dass ein Fight mehr als
    einen Loser hat - keine separate Datenbank/Tabelle mehr nötig.
  - duration ist ein Textstring ("21s", "1m 06s") statt Sekunden als Zahl
  - zone ist bereits ein Klartext-Name, keine numerische Zone-ID

Intern wird die breite fights-Tabelle beim Einlesen in eine "lange" Form
entnormalisiert (eine Zeile pro Fight-Teilnehmer), das macht die
nachfolgenden Auswertungen einfacher und konsistent mit dem bisherigen
Code-Stil.
"""

import sqlite3
import json
import re
import subprocess
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import config

DB_PATH   = config.DB_PATH
JSON_PATH = config.JSON_PATH
DAYS_KEEP = 180  # 180 Tage = ~6 Monate; 0 = alle Daten (sehr langsam bei großen DBs)
MIN_FIGHTS_LEADERBOARD = 1
MAX_LOSERS = 8

CLASS_REALM = {
    "Paladin":1,"Armsman":1,"Scout":1,"Minstrel":1,"Theurgist":1,
    "Cleric":1,"Wizard":1,"Sorcerer":1,"Infiltrator":1,"Friar":1,
    "Mercenary":1,"Necromancer":1,"Cabalist":1,"Reaver":1,
    "Heretic":1,"Occultist":1,
    "Thane":2,"Warrior":2,"Shadowblade":2,"Skald":2,"Hunter":2,
    "Healer":2,"Spiritmaster":2,"Shaman":2,"Runemaster":2,
    "Bonedancer":2,"Berserker":2,"Savage":2,"Valkyrie":2,"Warlock":2,
    "Bainshee":3,"Eldritch":3,"Enchanter":3,"Mentalist":3,
    "Blademaster":3,"Hero":3,"Champion":3,"Warden":3,"Druid":3,
    "Bard":3,"Nightshade":3,"Ranger":3,"Animist":3,"Valewalker":3,"Vampiir":3,
}
REALM_NAMES = {1: "Albion", 2: "Midgard", 3: "Hibernia"}

# Stabile, sortierte Liste aller bekannten Klassen -> wird als "class_id"
# genutzt (Index in dieser Liste), damit das Frontend weiterhin mit
# numerischen IDs arbeiten kann (z.B. für Icon-Lookups), auch wenn die
# Datenbank selbst nur Klartext-Namen liefert.
_ALL_CLASS_NAMES = sorted(CLASS_REALM.keys())
CLASS_NAME_TO_ID = {name: i + 1 for i, name in enumerate(_ALL_CLASS_NAMES)}
CLASS_ID_TO_NAME = {v: k for k, v in CLASS_NAME_TO_ID.items()}


def class_id_for(name):
    return CLASS_NAME_TO_ID.get(name)


def realm_for_class_name(name):
    return CLASS_REALM.get(name, 0)


def parse_duration(text):
    """'21s' -> 21, '1m 06s' -> 66, None/leer -> 0"""
    if not text:
        return 0
    m = re.match(r"(?:(\d+)m)?\s*(?:(\d+)s)?", text.strip())
    if not m:
        return 0
    minutes = int(m.group(1)) if m.group(1) else 0
    seconds = int(m.group(2)) if m.group(2) else 0
    return minutes * 60 + seconds


def load_excluded_players():
    try:
        with open("excluded_players.txt") as f:
            return {line.strip() for line in f if line.strip() and not line.startswith("#")}
    except FileNotFoundError:
        return set()


EXCLUDED_PLAYERS = load_excluded_players()


def wilson_score(wins, fights, z=1.96):
    if fights == 0:
        return 0
    p = wins / fights
    denom = 1 + z * z / fights
    centre = p + z * z / (2 * fights)
    margin = z * ((p * (1 - p) + z * z / (4 * fights)) / fights) ** 0.5
    return round((centre - margin) / denom * 100, 2)


# ──────────────────────────────────────────────
# Rohdaten laden & entnormalisieren
# ──────────────────────────────────────────────
def load_fights(con, since_dt=None):
    """Liest alle Fights aus der DB und gibt eine Liste von Dicts zurück:
    {
        "id": ..., "timestamp": datetime, "zone": str, "duration_s": int,
        "winner": {"name": ..., "class": ..., "class_id": ...},
        "losers": [{"name": ..., "class": ..., "class_id": ...}, ...],
    }
    Fights mit fehlendem winner_name oder ohne gültigen Zeitstempel werden
    übersprungen (defensiv gegen unvollständige Bot-Schreibvorgänge).
    """
    cur = con.cursor()
    cols = ["id", "fight_timestamp", "zone", "winner_name", "winner_class", "duration", "fight_url", "scoreboard_code"]
    for i in range(1, MAX_LOSERS + 1):
        cols.append(f"loser_{i}_name")
        cols.append(f"loser_{i}_class")

    rows = cur.execute(f"SELECT {', '.join(cols)} FROM fights").fetchall()

    fights = []
    for row in rows:
        d = dict(zip(cols, row))
        if not d["winner_name"] or not d["fight_timestamp"]:
            continue
        try:
            ts = datetime.fromisoformat(d["fight_timestamp"])
        except ValueError:
            continue
        if since_dt and ts < since_dt:
            continue

        losers = []
        for i in range(1, MAX_LOSERS + 1):
            name = d.get(f"loser_{i}_name")
            cls = d.get(f"loser_{i}_class")
            if name:
                losers.append({
                    "name": name,
                    "class": cls,
                    "class_id": class_id_for(cls),
                })

        fights.append({
            "id": d["id"],
            "timestamp": ts,
            "zone": d["zone"],
            "duration_s": parse_duration(d["duration"]),
            "fight_url": d.get("fight_url"),
            "scoreboard_code": d.get("scoreboard_code"),
            "winner": {
                "name": d["winner_name"],
                "class": d["winner_class"],
                "class_id": class_id_for(d["winner_class"]),
            },
            "losers": losers,
        })

    fights.sort(key=lambda f: f["timestamp"])
    return fights


def build_recent_fights(fights, limit=None):
    """Letzte Fights als flache Liste für die Recent Fights Karte/Drilldown."""
    out = []
    for f in reversed(fights):  # neueste zuerst
        loser_names = [l["name"] for l in f["losers"]]
        loser_classes = [l["class"] for l in f["losers"]]
        loser_class_ids = [l["class_id"] for l in f["losers"]]
        out.append({
            "timestamp": f["timestamp"].isoformat(),
            "zone": f["zone"],
            "duration_s": f["duration_s"],
            "fight_url": f.get("fight_url"),
            "winner_name": f["winner"]["name"],
            "winner_class": f["winner"]["class"],
            "winner_class_id": f["winner"]["class_id"],
            "loser_names": loser_names,
            "loser_classes": loser_classes,
            "loser_class_ids": loser_class_ids,
            "size": f"1v{len(f['losers'])}",
        })
        if limit and len(out) >= limit:
            break
    return out


def is_1v1(fight):
    return len(fight["losers"]) == 1


def is_excluded(fight):
    names = [fight["winner"]["name"]] + [l["name"] for l in fight["losers"]]
    return any(n in EXCLUDED_PLAYERS for n in names)


# ──────────────────────────────────────────────
# Auswertungen
# ──────────────────────────────────────────────
def build_class_id_map():
    return {
        "class_names": CLASS_ID_TO_NAME,
        "class_realm": {str(cid): realm_for_class_name(name) for cid, name in CLASS_ID_TO_NAME.items()},
    }


def build_leaderboard(fights_1v1, min_fights=MIN_FIGHTS_LEADERBOARD):
    wins = defaultdict(int)
    losses = defaultdict(int)
    last_class = {}
    last_fight = {}

    for f in fights_1v1:
        if is_excluded(f):
            continue
        w = f["winner"]["name"]
        l = f["losers"][0]["name"]
        wins[w] += 1
        losses[l] += 1
        last_class[w] = f["winner"]["class_id"]
        last_class[l] = f["losers"][0]["class_id"]
        last_fight[w] = f["timestamp"].isoformat()
        last_fight[l] = f["timestamp"].isoformat()

    names = set(wins) | set(losses)
    rows = []
    for name in names:
        w = wins.get(name, 0)
        l = losses.get(name, 0)
        total = w + l
        if total < min_fights:
            continue
        cid = last_class.get(name)
        rows.append({
            "name": name,
            "class_id": cid,
            "class_name": CLASS_ID_TO_NAME.get(cid, "Unknown"),
            "realm": realm_for_class_name(CLASS_ID_TO_NAME.get(cid, "")),
            "realm_name": REALM_NAMES.get(realm_for_class_name(CLASS_ID_TO_NAME.get(cid, "")), ""),
            "fights": total,
            "wins": w,
            "losses": l,
            "winrate": round(w / total * 100) if total else 0,
            "wilson": wilson_score(w, total),
            "last_fight": last_fight.get(name),
        })
    rows.sort(key=lambda r: -r["wilson"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def build_class_stats(fights_1v1):
    wins = defaultdict(int)
    fights_count = defaultdict(int)
    players_by_class = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "fights": 0}))

    for f in fights_1v1:
        if is_excluded(f):
            continue
        w_cid = f["winner"]["class_id"]
        l_cid = f["losers"][0]["class_id"]
        w_name = f["winner"]["name"]
        l_name = f["losers"][0]["name"]

        if w_cid:
            wins[w_cid] += 1
            fights_count[w_cid] += 1
            players_by_class[w_cid][w_name]["wins"] += 1
            players_by_class[w_cid][w_name]["fights"] += 1
        if l_cid:
            fights_count[l_cid] += 1
            players_by_class[l_cid][l_name]["fights"] += 1

    stats = []
    total_fights_all = sum(fights_count.values())
    for cid, total in fights_count.items():
        w = wins.get(cid, 0)
        stats.append({
            "class_id": cid,
            "class_name": CLASS_ID_TO_NAME.get(cid, "Unknown"),
            "realm": realm_for_class_name(CLASS_ID_TO_NAME.get(cid, "")),
            "fights": total,
            "wins": w,
            "winrate": round(w / total * 100) if total else 0,
            "share": round(total / total_fights_all * 100, 1) if total_fights_all else 0,
        })
    stats.sort(key=lambda s: -s["fights"])

    class_players = {}
    for cid, players in players_by_class.items():
        lst = []
        for name, pdata in players.items():
            w, total = pdata["wins"], pdata["fights"]
            lst.append({
                "name": name,
                "fights": total,
                "wins": w,
                "losses": total - w,
                "winrate": round(w / total * 100) if total else 0,
                "wilson": wilson_score(w, total),
            })
        lst.sort(key=lambda p: -p["wilson"])
        class_players[cid] = lst

    return stats, class_players


def build_matchup_matrix(fights_1v1):
    """matchups[a_class_id][b_class_id] = {"wins": a-vs-b Siege von a, "fights": ...}"""
    matrix = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "fights": 0}))
    for f in fights_1v1:
        if is_excluded(f):
            continue
        w_cid = f["winner"]["class_id"]
        l_cid = f["losers"][0]["class_id"]
        if not w_cid or not l_cid:
            continue
        matrix[w_cid][l_cid]["wins"] += 1
        matrix[w_cid][l_cid]["fights"] += 1
        matrix[l_cid][w_cid]["fights"] += 1

    out = {}
    for a, opponents in matrix.items():
        out[str(a)] = {}
        for b, data in opponents.items():
            total = data["fights"]
            out[str(a)][str(b)] = {
                "wins": data["wins"],
                "fights": total,
                "winrate": round(data["wins"] / total * 100) if total else 0,
            }
    return out


def build_matchup_matrix_sql(con):
    """Matchup Matrix direkt per SQL — kein Python-Loop über alle Fights.
    Nur winner_class und loser_1_class werden gelesen, alle Daten, sehr schnell.
    """
    rows = con.execute("""
        SELECT winner_class, loser_1_class, count(*) as cnt
        FROM fights
        WHERE winner_class IS NOT NULL
          AND loser_1_class IS NOT NULL
          AND loser_1_name IS NOT NULL
          AND loser_2_name IS NULL
        GROUP BY winner_class, loser_1_class
    """).fetchall()

    matrix = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "fights": 0}))
    for w_cls, l_cls, cnt in rows:
        w_cid = class_id_for(w_cls)
        l_cid = class_id_for(l_cls)
        if not w_cid or not l_cid:
            continue
        matrix[w_cid][l_cid]["wins"] += cnt
        matrix[w_cid][l_cid]["fights"] += cnt
        matrix[l_cid][w_cid]["fights"] += cnt

    out = {}
    for a, opponents in matrix.items():
        out[str(a)] = {}
        for b, data in opponents.items():
            total = data["fights"]
            out[str(a)][str(b)] = {
                "wins": data["wins"],
                "fights": total,
                "winrate": round(data["wins"] / total * 100) if total else 0,
            }
    return out


def build_zone_activity(fights, hours=0, cutoff=None):
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    counts = defaultdict(int)
    for f in fights:
        if f["timestamp"] >= cutoff:
            counts[f["zone"]] += 1
    total = sum(counts.values())
    rows = [
        {"name": zone, "count": cnt, "pct": round(cnt / total * 100, 1) if total else 0}
        for zone, cnt in counts.items()
    ]
    rows.sort(key=lambda r: -r["count"])
    return rows


def build_zone_activity_hourly(fights, days=1):
    """Durchschnittliche stündliche Fight-Zahlen pro Zone, gemittelt über alle Tage im Datensatz.
    Zeigt repräsentative Werte statt kumulativer Summen über mehrere Tage."""
    if not fights:
        return []

    # Fights pro Tag+Zone+Stunde
    by_day_zone_hour = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for f in fights:
        day = f["timestamp"].strftime("%Y-%m-%d")
        hour = f["timestamp"].hour
        by_day_zone_hour[day][f["zone"]][hour] += 1

    num_days = max(len(by_day_zone_hour), 1)

    # Alle Zonen sammeln und Durchschnitt berechnen
    zone_hour_totals = defaultdict(lambda: defaultdict(int))
    zone_totals = defaultdict(int)
    for day, zones in by_day_zone_hour.items():
        for zone, hours_dict in zones.items():
            for hour, cnt in hours_dict.items():
                zone_hour_totals[zone][hour] += cnt
                zone_totals[zone] += cnt

    out = []
    for zone, hours_dict in zone_hour_totals.items():
        data = [{"hour": h, "count": round(hours_dict.get(h, 0) / num_days, 1)} for h in range(24)]
        out.append({"name": zone, "data": data, "total": round(zone_totals[zone] / num_days, 1)})
    out.sort(key=lambda z: -z["total"])
    return out


def build_classes_played(fights, hours=0, cutoff=None):
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    counts = defaultdict(int)
    for f in fights:
        if f["timestamp"] < cutoff:
            continue
        participants = [f["winner"]] + f["losers"]
        for p in participants:
            if p["class_id"]:
                counts[p["class_id"]] += 1
    total = sum(counts.values())
    rows = [
        {
            "class_id": cid,
            "class_name": CLASS_ID_TO_NAME.get(cid, "Unknown"),
            "realm": realm_for_class_name(CLASS_ID_TO_NAME.get(cid, "")),
            "realm_name": REALM_NAMES.get(realm_for_class_name(CLASS_ID_TO_NAME.get(cid, "")), ""),
            "count": cnt,
            "pct": round(cnt / total * 100, 1) if total else 0,
        }
        for cid, cnt in counts.items()
    ]
    rows.sort(key=lambda r: -r["count"])
    return rows


def build_win_streaks(fights_1v1, since_dt=None):
    """Höchste Win-Streak pro Spieler (chronologisch, Niederlage setzt zurück)."""
    by_player = defaultdict(list)  # name -> [(timestamp, won), ...]
    for f in fights_1v1:
        if is_excluded(f):
            continue
        if since_dt and f["timestamp"] < since_dt:
            continue
        w, l = f["winner"]["name"], f["losers"][0]["name"]
        by_player[w].append((f["timestamp"], True, f["winner"]["class_id"]))
        by_player[l].append((f["timestamp"], False, f["losers"][0]["class_id"]))

    best = {}
    last_class = {}
    for name, events in by_player.items():
        events.sort(key=lambda e: e[0])
        streak = 0
        max_streak = 0
        for _, won, cid in events:
            if won:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
            last_class[name] = cid
        best[name] = max_streak

    rows = [
        {"name": name, "class_id": last_class.get(name), "opponents": streak}
        for name, streak in best.items() if streak > 0
    ]
    rows.sort(key=lambda r: -r["opponents"])
    return rows


def build_underdogs(fights, since_dt=None, limit=5):
    """Top-Spieler nach dem höchsten je geschafften 1-vs-X-Sieg.
    Ein Fight mit N Losern ist automatisch ein 1-vs-N Underdog-Sieg des Winners.
    """
    best = {}  # name -> {"max_opponents": int, "wins_at_max": int, "class_id": ...}
    for f in fights:
        if since_dt and f["timestamp"] < since_dt:
            continue
        if is_excluded(f):
            continue
        n_losers = len(f["losers"])
        if n_losers < 2:
            continue
        name = f["winner"]["name"]
        cid = f["winner"]["class_id"]
        cur = best.get(name)
        if cur is None or n_losers > cur["max_opponents"]:
            best[name] = {"max_opponents": n_losers, "wins_at_max": 1, "class_id": cid,
                          "fight_url": f.get("fight_url")}
        elif n_losers == cur["max_opponents"]:
            cur["wins_at_max"] += 1

    rows = [{"name": name, **data} for name, data in best.items()]
    rows.sort(key=lambda r: (-r["max_opponents"], -r["wins_at_max"]))
    return rows[:limit]


def build_underdog_wins_by_player(fights):
    """{player_name: {opponent_count: win_count}} - all-time, für Profile/Class-Drilldown."""
    result = defaultdict(lambda: defaultdict(int))
    for f in fights:
        if is_excluded(f):
            continue
        n_losers = len(f["losers"])
        if n_losers < 2:
            continue
        result[f["winner"]["name"]][n_losers] += 1
    return {name: dict(counts) for name, counts in result.items()}


def build_top_kills_last_hour(fights, limit=5):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    kills = defaultdict(int)
    last_class = {}
    for f in fights:
        if f["timestamp"] < cutoff or is_excluded(f):
            continue
        kills[f["winner"]["name"]] += 1
        last_class[f["winner"]["name"]] = f["winner"]["class_id"]
    rows = [
        {"name": name, "class_id": last_class.get(name),
         "class_name": CLASS_ID_TO_NAME.get(last_class.get(name), "Unknown"), "kills": c}
        for name, c in kills.items()
    ]
    rows.sort(key=lambda r: -r["kills"])
    return rows[:limit]


def build_fights_heatmap(fights):
    """Durchschnittliche Fights pro Wochentag (0=Mo, 6=So) und Stunde (0-23).
    Geteilt durch die Anzahl der Wochen im Datensatz für aussagekräftige Werte.
    Rückgabe: [[avg_count für hour 0..23] für day 0..6]
    """
    if not fights:
        return [[0]*24 for _ in range(7)]

    # Zähle Vorkommen jedes Wochentags im Datensatz
    day_counts = defaultdict(set)  # weekday -> set of date strings
    grid_totals = [[0]*24 for _ in range(7)]

    for f in fights:
        if is_excluded(f):
            continue
        ts = f["timestamp"]
        day = ts.weekday()
        hour = ts.hour
        grid_totals[day][hour] += 1
        day_counts[day].add(ts.strftime("%Y-%m-%d"))

    # Durchschnitt: geteilt durch Anzahl Tage dieses Wochentags im Zeitraum
    grid = [[0]*24 for _ in range(7)]
    for day in range(7):
        num_days = max(len(day_counts[day]), 1)
        for hour in range(24):
            grid[day][hour] = round(grid_totals[day][hour] / num_days, 1)
    return grid


def build_active_players_per_hour(fights):
    """Durchschnittliche unique aktive Spieler pro Stunde (0-23).
    Berechnet den Schnitt über alle Tage im Datensatz statt kumulative Summe.
    """
    if not fights:
        return [{"hour": h, "count": 0} for h in range(24)]

    # Unique Spieler pro Tag+Stunde
    players_by_day_hour = defaultdict(lambda: defaultdict(set))
    for f in fights:
        if is_excluded(f):
            continue
        day = f["timestamp"].strftime("%Y-%m-%d")
        hour = f["timestamp"].hour
        players_by_day_hour[day][hour].add(f["winner"]["name"])
        for l in f["losers"]:
            players_by_day_hour[day][hour].add(l["name"])

    num_days = len(players_by_day_hour)
    if num_days == 0:
        return [{"hour": h, "count": 0} for h in range(24)]

    # Durchschnitt pro Stunde über alle Tage
    totals = defaultdict(int)
    for day, hours in players_by_day_hour.items():
        for hour, players in hours.items():
            totals[hour] += len(players)

    return [{"hour": h, "count": round(totals.get(h, 0) / num_days, 1)} for h in range(24)]


def build_unique_players_by_class(fights):
    """Zählt unique Spieler pro Klasse — jeder Spieler wird nur einmal gezählt,
    unabhängig wie viele Fights er gespielt hat.
    Rückgabe: [{"class_id":..., "class_name":..., "players": n}, ...]
    """
    players_by_class = defaultdict(set)
    for f in fights:
        if is_excluded(f):
            continue
        w_cid = f["winner"]["class_id"]
        if w_cid:
            players_by_class[w_cid].add(f["winner"]["name"])
        for l in f["losers"]:
            l_cid = l["class_id"]
            if l_cid:
                players_by_class[l_cid].add(l["name"])

    rows = [
        {
            "class_id": cid,
            "class_name": CLASS_ID_TO_NAME.get(cid, "Unknown"),
            "realm": realm_for_class_name(CLASS_ID_TO_NAME.get(cid, "")),
            "players": len(players),
        }
        for cid, players in players_by_class.items()
    ]
    rows.sort(key=lambda r: -r["players"])
    return rows


def build_top_matchups(fights_1v1, limit=5):
    """Häufigste Klassen-Paarungen mit Winrate.
    Rückgabe: [{"class_a_id":..., "class_a_name":..., "class_b_id":..., "class_b_name":...,
                "fights":..., "winrate_a":...}, ...]
    """
    counts = defaultdict(int)
    wins_a = defaultdict(int)
    for f in fights_1v1:
        if is_excluded(f):
            continue
        a = f["winner"]["class_id"]
        b = f["losers"][0]["class_id"]
        if not a or not b:
            continue
        key = tuple(sorted([a, b]))
        counts[key] += 1
        if key[0] == a:
            wins_a[key] += 1
    rows = []
    for (ca, cb), total in counts.items():
        wa = wins_a[(ca, cb)]
        rows.append({
            "class_a_id": ca,
            "class_a_name": CLASS_ID_TO_NAME.get(ca, "Unknown"),
            "class_b_id": cb,
            "class_b_name": CLASS_ID_TO_NAME.get(cb, "Unknown"),
            "fights": total,
            "winrate_a": round(wa / total * 100) if total else 50,
        })
    rows.sort(key=lambda r: -r["fights"])
    return rows[:limit]


def build_player_profile(fights, fights_1v1, name, underdog_wins_by_player=None):
    """Einzelnes Profil — nur noch für Kompatibilität, intern wird build_all_player_profiles genutzt."""
    profiles = build_all_player_profiles(fights_1v1, underdog_wins_by_player)
    return profiles.get(name, {
        "top_zones": [], "top_hours": [], "won_vs": [], "lost_vs": [],
        "won_vs_player": [], "lost_vs_player": [],
        "total_wins": 0, "total_fights": 0, "winrate": 0, "underdog_wins": {},
    })


def build_all_player_profiles(fights_1v1, underdog_wins_by_player=None):
    """Baut alle Spielerprofile in einem einzigen Pass über fights_1v1.
    O(Fights) statt O(Spieler × Fights).
    """
    zones       = defaultdict(lambda: defaultdict(int))
    hours       = defaultdict(lambda: defaultdict(int))
    won_vs      = defaultdict(lambda: defaultdict(int))
    lost_vs     = defaultdict(lambda: defaultdict(int))
    won_vs_p    = defaultdict(lambda: defaultdict(int))
    lost_vs_p   = defaultdict(lambda: defaultdict(int))
    total_wins  = defaultdict(int)
    total_fights= defaultdict(int)
    cur_streak  = defaultdict(int)
    best_streak = defaultdict(int)

    for f in sorted(fights_1v1, key=lambda x: x["timestamp"]):
        if is_excluded(f):
            continue
        w = f["winner"]["name"]
        l = f["losers"][0]["name"]
        zone = f["zone"]
        hour = f["timestamp"].hour
        w_cls = f["winner"]["class"]
        l_cls = f["losers"][0]["class"]

        # Winner
        zones[w][zone] += 1
        hours[w][hour] += 1
        total_wins[w]  += 1
        total_fights[w]+= 1
        won_vs[w][l_cls]+= 1
        won_vs_p[w][l]  += 1
        cur_streak[w]   += 1
        if cur_streak[w] > best_streak[w]:
            best_streak[w] = cur_streak[w]

        # Loser
        zones[l][zone]  += 1
        hours[l][hour]  += 1
        total_fights[l] += 1
        lost_vs[l][w_cls]+= 1
        lost_vs_p[l][w]  += 1
        cur_streak[l]    = 0  # Niederlage setzt Streak zurück

    def top_n(d, n=5):
        return sorted(d.items(), key=lambda kv: -kv[1])[:n]

    all_names = set(total_fights.keys())
    profiles = {}
    for name in all_names:
        tw = total_wins[name]
        tf = total_fights[name]
        profiles[name] = {
            "top_zones":     [{"name": z, "count": c} for z, c in top_n(zones[name])],
            "top_hours":     [{"hour": h, "count": c} for h, c in sorted(hours[name].items())],
            "won_vs":        [{"class_name": c, "count": n} for c, n in top_n(won_vs[name])],
            "lost_vs":       [{"class_name": c, "count": n} for c, n in top_n(lost_vs[name])],
            "won_vs_player": [{"name": p, "count": n} for p, n in top_n(won_vs_p[name])],
            "lost_vs_player":[{"name": p, "count": n} for p, n in top_n(lost_vs_p[name])],
            "total_wins":    tw,
            "total_fights":  tf,
            "winrate":       round(tw / tf * 100) if tf else 0,
            "best_streak":   best_streak[name],
            "underdog_wins": underdog_wins_by_player.get(name, {}) if underdog_wins_by_player else {},
        }
    return profiles


# ──────────────────────────────────────────────
# Hauptexport
# ──────────────────────────────────────────────
def compute_stats(con):
    now = datetime.now(timezone.utc)

    # ── Zeitgrenzen ──
    today_start        = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start    = today_start - timedelta(days=1)
    cutoff_24h         = now - timedelta(hours=24)
    cutoff_1d          = now - timedelta(days=1)
    cutoff_3d          = now - timedelta(days=3)
    cutoff_7d          = now - timedelta(days=7)
    cutoff_30d         = now - timedelta(days=30)
    cutoff_1h          = now - timedelta(hours=1)
    now_time_yesterday = yesterday_start + (now - today_start)

    ACTIVITY_WINDOWS = {
        "1d": cutoff_1d, "3d": cutoff_3d,
        "7d": cutoff_7d, "30d": cutoff_30d,
    }
    TIME_WINDOWS_HOURS = {
        "1h": cutoff_1h, "24h": cutoff_24h,
        "3d": cutoff_3d, "7d": cutoff_7d, "30d": cutoff_30d,
    }

    # ── Schnelle SQL-Zähler ──
    def sql_count(where, params=()):
        return con.execute(f"SELECT count(*) FROM fights {where}", params).fetchone()[0]

    fights_today               = sql_count("WHERE fight_timestamp >= ?", (today_start.isoformat(),))
    fights_yesterday           = sql_count("WHERE fight_timestamp >= ? AND fight_timestamp < ?",
                                           (yesterday_start.isoformat(), today_start.isoformat()))
    fights_yesterday_until_now = sql_count("WHERE fight_timestamp >= ? AND fight_timestamp < ?",
                                           (yesterday_start.isoformat(), now_time_yesterday.isoformat()))
    total_fights               = sql_count("")
    tracking_since_str         = con.execute("SELECT MIN(fight_timestamp) FROM fights").fetchone()[0]

    active_players_rows = con.execute("""
        SELECT winner_name FROM fights WHERE fight_timestamp >= ?
        UNION
        SELECT loser_1_name FROM fights WHERE fight_timestamp >= ? AND loser_1_name IS NOT NULL
        UNION
        SELECT loser_2_name FROM fights WHERE fight_timestamp >= ? AND loser_2_name IS NOT NULL
    """, (cutoff_24h.isoformat(),)*3).fetchall()
    active_players_count = len(active_players_rows)

    # ── Fights laden: nur 30d für alle Python-Berechnungen ──
    # Matchup Matrix wird direkt per SQL berechnet (alle Daten, sehr schnell)
    all_fights     = load_fights(con, since_dt=cutoff_30d)
    fights_30d     = all_fights  # alias
    fights_1v1_all = [f for f in all_fights if is_1v1(f)]
    fights_1v1_30d = fights_1v1_all  # alias

    # ── Matchup Matrix — alle Daten per SQL (kein Python-Loop) ──
    matchup_matrix = build_matchup_matrix_sql(con)

    # ── Einzel-Pass ueber all_fights ──
    daily_counts = defaultdict(int)
    kills_1h     = defaultdict(lambda: {"kills": 0, "class_id": None})
    for f in all_fights:
        ts = f["timestamp"]
        daily_counts[ts.strftime("%Y-%m-%d")] += 1
        if ts >= cutoff_1h:
            w = f["winner"]["name"]
            kills_1h[w]["kills"] += 1
            kills_1h[w]["class_id"] = f["winner"]["class_id"]

    daily_fights = [{"day": d, "count": c} for d, c in sorted(daily_counts.items())]
    top_kills_last_hour = sorted(
        [{"name": n, "kills": v["kills"], "class_id": v["class_id"],
          "class_name": CLASS_ID_TO_NAME.get(v["class_id"], "Unknown")}
         for n, v in kills_1h.items()],
        key=lambda x: -x["kills"]
    )[:5]

    # ── Leaderboard ──
    leaderboard_by_days = {}
    for d, cutoff in [(1, cutoff_1d), (3, cutoff_3d), (7, cutoff_7d)]:
        leaderboard_by_days[d] = build_leaderboard([f for f in fights_1v1_30d if f["timestamp"] >= cutoff])
    leaderboard_by_days[30] = build_leaderboard(fights_1v1_30d)

    # ── Class Stats ──
    class_stats, class_players = build_class_stats(fights_1v1_all)
    class_stats_by_days  = {}
    class_players_by_days = {}
    for d, cutoff in [(1, cutoff_1d), (3, cutoff_3d), (7, cutoff_7d)]:
        w = [f for f in fights_1v1_30d if f["timestamp"] >= cutoff]
        cs, cp = build_class_stats(w)
        class_stats_by_days[d]  = cs
        class_players_by_days[d] = cp

    # ── Spielerprofile — ein Pass für alle ──
    underdog_wins = build_underdog_wins_by_player(all_fights)

    player_profiles = build_all_player_profiles(fights_1v1_all, underdog_wins)
    # Zeitgefilterte Profile NUR für 30d (Zonen/Stunden immer all-time, W/L zeitgefiltert)
    profile_windows = {}
    for d_key, cutoff in [("1d", cutoff_1d), ("3d", cutoff_3d), ("7d", cutoff_7d)]:
        f1v1_w = [f for f in fights_1v1_30d if f["timestamp"] >= cutoff]
        # Nur W/L-Daten zeitgefiltert speichern, nicht alle Profile
        pw = build_all_player_profiles(f1v1_w, underdog_wins)
        # Nur Spieler mit Aktivität im Zeitfenster speichern
        profile_windows[d_key] = {
            name: {k: v for k, v in prof.items()
                   if k in ("won_vs", "lost_vs", "won_vs_player", "lost_vs_player",
                            "total_wins", "total_fights", "winrate")}
            for name, prof in pw.items()
            if prof["total_fights"] > 0
        }

    # underdog_wins in class_players einbauen
    for cid, players in class_players.items():
        for p in players:
            p["underdog_wins"] = underdog_wins.get(p["name"], {})
    for d, cp in class_players_by_days.items():
        for cid, players in cp.items():
            for p in players:
                p["underdog_wins"] = underdog_wins.get(p["name"], {})

    # ── Zeitgefilterte Activity (30d reicht) ──
    classes_played_by_window = {k: build_classes_played(fights_30d, 0, cutoff)
                                 for k, cutoff in TIME_WINDOWS_HOURS.items()}
    active_zones_by_window_h  = {k: build_zone_activity(fights_30d, 0, cutoff)
                                  for k, cutoff in TIME_WINDOWS_HOURS.items()}

    zone_activity_by_window           = {}
    heatmap_by_window                 = {}
    active_players_per_hour_by_window = {}
    top_matchups_by_window            = {}
    recent_fights_by_window           = {}
    unique_players_by_class_by_window = {}
    for key, cutoff in ACTIVITY_WINDOWS.items():
        fw    = [f for f in fights_30d if f["timestamp"] >= cutoff]
        f1v1w = [f for f in fw if is_1v1(f)]
        zone_activity_by_window[key]             = build_zone_activity_hourly(fw)
        heatmap_by_window[key]                   = build_fights_heatmap(fw)
        active_players_per_hour_by_window[key]   = build_active_players_per_hour(fw)
        top_matchups_by_window[key]              = build_top_matchups(f1v1w, limit=999)
        recent_fights_by_window[key]             = build_recent_fights(fw, limit=200)
        unique_players_by_class_by_window[key]   = build_unique_players_by_class(fw)

    # ── Underdogs & Streaks ──
    top_underdog_7d       = build_underdogs(all_fights, since_dt=cutoff_7d, limit=5)
    top_underdogs_overall = build_underdogs(all_fights, since_dt=None, limit=5)
    top_streak_7d         = build_win_streaks(fights_1v1_all, since_dt=cutoff_7d)[:5]
    top_streak_all        = build_win_streaks(fights_1v1_all, since_dt=None)[:10]
    recent_fights         = build_recent_fights(all_fights, limit=5)

    return {
        "generated_at": now.isoformat(),
        "summary": {
            "fights_today":               fights_today,
            "fights_yesterday":           fights_yesterday,
            "fights_yesterday_until_now": fights_yesterday_until_now,
            "total_fights":               total_fights,
            "active_players":             active_players_count,
            "tracking_since":             tracking_since_str,
        },
        "class_meta":                         build_class_id_map(),
        "leaderboard":                        leaderboard_by_days[30],
        "leaderboard_1d":                     leaderboard_by_days[1],
        "leaderboard_3d":                     leaderboard_by_days[3],
        "leaderboard_7d":                     leaderboard_by_days[7],
        "class_stats":                        class_stats,
        "class_stats_1d":                     class_stats_by_days[1],
        "class_stats_3d":                     class_stats_by_days[3],
        "class_stats_7d":                     class_stats_by_days[7],
        "class_players":                      class_players,
        "class_players_1d":                   class_players_by_days[1],
        "class_players_3d":                   class_players_by_days[3],
        "class_players_7d":                   class_players_by_days[7],
        "matchup_matrix":                     matchup_matrix,
        "classes_played_by_window":           classes_played_by_window,
        "active_zones_by_window":             active_zones_by_window_h,
        "zone_activity_by_window":            zone_activity_by_window,
        "daily_fights":                       daily_fights,
        "top_underdog_7d":                    top_underdog_7d,
        "top_underdogs_overall":              top_underdogs_overall,
        "top_streak_7d":                      top_streak_7d,
        "top_underdog":                       top_streak_all,
        "top_kills_last_hour":                top_kills_last_hour,
        "heatmap_by_window":                  heatmap_by_window,
        "active_players_per_hour_by_window":  active_players_per_hour_by_window,
        "top_matchups_by_window":             top_matchups_by_window,
        "unique_players_by_class_by_window":  unique_players_by_class_by_window,
        "recent_fights":                      recent_fights,
        "recent_fights_by_window":            recent_fights_by_window,
        "player_profiles":                    player_profiles,
        "player_profiles_1d":                 profile_windows["1d"],
        "player_profiles_3d":                 profile_windows["3d"],
        "player_profiles_7d":                 profile_windows["7d"],
    }


def export(push=True):
    con = sqlite3.connect(DB_PATH)
    stats = compute_stats(con)
    con.close()

    # Player-Profile in separate Datei auslagern (reduziert data.json deutlich)
    profiles_path = str(Path(JSON_PATH).parent / "profiles.json")
    profiles_data = {
        "player_profiles": stats.pop("player_profiles", {}),
        "player_profiles_1d": stats.pop("player_profiles_1d", {}),
        "player_profiles_3d": stats.pop("player_profiles_3d", {}),
        "player_profiles_7d": stats.pop("player_profiles_7d", {}),
    }
    with open(profiles_path, "w") as f:
        json.dump(profiles_data, f, separators=(",", ":"))

    with open(JSON_PATH, "w") as f:
        json.dump(stats, f, separators=(",", ":"))

    print(f"  ✓ data.json geschrieben ({len(json.dumps(stats))} bytes)")
    print(f"  ✓ profiles.json geschrieben ({len(json.dumps(profiles_data))} bytes)")

    if push and config.GIT_PUSH:
        web_dir = str(Path(JSON_PATH).parent)
        try:
            subprocess.run(["git", "add", "data.json", "profiles.json", "elo.json", "elo_history.json", "elo_fights.json"], check=True, cwd=web_dir)
            subprocess.run(["git", "commit", "-m", "update fight data"], check=True, cwd=web_dir)
            subprocess.run(["git", "push"], check=True, cwd=web_dir)
            print("  ✓ GitHub Push erfolgreich")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ Git Push fehlgeschlagen: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export fights.db -> data.json (Discord-Bot-Schema)")
    parser.add_argument("--no-push", action="store_true", help="Kein Git Push")
    args = parser.parse_args()
    export(push=not args.no_push)