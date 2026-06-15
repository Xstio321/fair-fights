"""
ELO Rating Calculator für DAoC Fair Fights
Berechnet ELO Ratings für alle Spieler basierend auf 1v1 Fights.
"""

import sqlite3
import json
import subprocess
from datetime import datetime, timezone

DB_PATH      = "fights.db"
JSON_PATH    = "ranking.json"
START_RATING = 1000

def load_excluded_players():
    try:
        with open('excluded_players.txt') as f:
            return {line.strip() for line in f if line.strip() and not line.startswith('#')}
    except FileNotFoundError:
        return set()

EXCLUDED_PLAYERS = load_excluded_players()

PODIUM_PATH = "podium_history.json"

def load_podium():
    try:
        with open(PODIUM_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_podium(podium):
    with open(PODIUM_PATH, "w") as f:
        json.dump(podium, f, separators=(",", ":"))
K_NEW        = 32   # K-Faktor für Spieler < 30 Fights
K_STABLE     = 16   # K-Faktor für Spieler >= 30 Fights

CLASSES = {
    1:"Paladin",2:"Armsman",3:"Scout",4:"Minstrel",5:"Theurgist",
    6:"Cleric",7:"Wizard",8:"Sorcerer",9:"Infiltrator",10:"Friar",
    11:"Mercenary",12:"Necromancer",13:"Cabalist",19:"Reaver",
    33:"Heretic",63:"Occultist",
    21:"Thane",22:"Warrior",23:"Shadowblade",24:"Skald",25:"Hunter",
    26:"Healer",27:"Spiritmaster",28:"Shaman",29:"Runemaster",
    30:"Bonedancer",31:"Berserker",32:"Savage",34:"Valkyrie",59:"Warlock",
    39:"Bainshee",40:"Eldritch",41:"Enchanter",42:"Mentalist",
    43:"Blademaster",44:"Hero",45:"Champion",46:"Warden",47:"Druid",
    48:"Bard",49:"Nightshade",50:"Ranger",55:"Animist",56:"Valewalker",58:"Vampiir",
}
CLASS_REALM = {
    1:1,2:1,3:1,4:1,5:1,6:1,7:1,8:1,9:1,10:1,11:1,12:1,13:1,19:1,33:1,63:1,
    21:2,22:2,23:2,24:2,25:2,26:2,27:2,28:2,29:2,30:2,31:2,32:2,34:2,59:2,
    39:3,40:3,41:3,42:3,43:3,44:3,45:3,46:3,47:3,48:3,49:3,50:3,55:3,56:3,58:3,
}
REALM_NAMES = {1:"Albion", 2:"Midgard", 3:"Hibernia"}

REALM_RANKS = [
    (0,"1L1"),(25,"1L2"),(125,"1L3"),(350,"1L4"),(750,"1L5"),
    (1375,"1L6"),(2275,"1L7"),(3500,"1L8"),(5100,"1L9"),
    (7125,"2L0"),(9625,"2L1"),(12650,"2L2"),(16250,"2L3"),(20475,"2L4"),
    (25375,"2L5"),(31000,"2L6"),(37400,"2L7"),(44625,"2L8"),(52725,"2L9"),
    (61750,"3L0"),(71750,"3L1"),(82775,"3L2"),(94875,"3L3"),(108100,"3L4"),
    (122500,"3L5"),(138125,"3L6"),(155025,"3L7"),(173250,"3L8"),(192850,"3L9"),
    (213875,"4L0"),(236375,"4L1"),(260400,"4L2"),(286000,"4L3"),(313225,"4L4"),
    (342125,"4L5"),(372750,"4L6"),(405150,"4L7"),(439375,"4L8"),(475475,"4L9"),
    (513500,"5L0"),(553500,"5L1"),(595525,"5L2"),(639625,"5L3"),(685850,"5L4"),
    (734250,"5L5"),(784875,"5L6"),(837775,"5L7"),(893000,"5L8"),(950600,"5L9"),
    (1010625,"6L0"),(1073125,"6L1"),(1138150,"6L2"),(1205750,"6L3"),(1275975,"6L4"),
    (1348875,"6L5"),(1424500,"6L6"),(1502900,"6L7"),(1584125,"6L8"),(1668225,"6L9"),
    (1755250,"7L0"),(1845250,"7L1"),(1938275,"7L2"),(2034375,"7L3"),(2133600,"7L4"),
    (2236000,"7L5"),(2341625,"7L6"),(2450525,"7L7"),(2562750,"7L8"),(2678350,"7L9"),
    (2797375,"8L0"),(2919875,"8L1"),(3045900,"8L2"),(3175500,"8L3"),(3308725,"8L4"),
    (3445625,"8L5"),(3586250,"8L6"),(3730650,"8L7"),(3878875,"8L8"),(4030975,"8L9"),
    (4187000,"9L0"),(4347000,"9L1"),(4511025,"9L2"),(4679125,"9L3"),(4851350,"9L4"),
    (5027750,"9L5"),(5208375,"9L6"),(5393275,"9L7"),(5582500,"9L8"),(5776100,"9L9"),
    (5974125,"10L0"),(6176625,"10L1"),(6383650,"10L2"),(6595250,"10L3"),
    (6811475,"10L4"),(7032375,"10L5"),(7258000,"10L6"),(7488400,"10L7"),
    (7723625,"10L8"),(7963725,"10L9"),(8208750,"11L0"),
]

def rp_to_rr(rp):
    label = "1L1"
    for min_rp, lbl in REALM_RANKS:
        if rp and rp >= min_rp:
            label = lbl
    return label


def expected(rating_a, rating_b):
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def k_factor(fights_count):
    return K_NEW if fights_count < 30 else K_STABLE


def init_elo_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS elo_ratings (
            name        TEXT PRIMARY KEY,
            rating      REAL NOT NULL DEFAULT 1000,
            fights      INTEGER NOT NULL DEFAULT 0,
            wins        INTEGER NOT NULL DEFAULT 0,
            losses      INTEGER NOT NULL DEFAULT 0,
            peak_rating REAL NOT NULL DEFAULT 1000,
            last_fight  TEXT,
            class_id    INTEGER,
            realm_pts   INTEGER
        )
    """)
    con.commit()


def calculate_elo(con, reset=False):
    if reset:
        con.execute("DELETE FROM elo_ratings")
        con.commit()
        print("  ELO Tabelle zurückgesetzt.")

    # Alle 1v1 Fights chronologisch laden
    fights = con.execute("""
        SELECT
            f.id,
            f.started_at,
            pw.name as winner,
            pw.class_id as winner_class,
            max(pw.realm_pts) as winner_rp,
            pl.name as loser,
            pl.class_id as loser_class,
            max(pl.realm_pts) as loser_rp
        FROM fights f
        JOIN fight_players pw ON pw.fight_id = f.id
        JOIN fight_teams tw ON tw.fight_id = f.id AND tw.side = pw.side AND tw.won = 1
        JOIN fight_players pl ON pl.fight_id = f.id
        JOIN fight_teams tl ON tl.fight_id = f.id AND tl.side = pl.side AND tl.won = 0
        WHERE f.size = 1
        GROUP BY f.id
        ORDER BY f.started_at ASC
    """).fetchall()

    # Ratings Dict
    ratings = {}
    fights_count = {}
    wins_count = {}
    losses_count = {}
    peak_ratings = {}
    last_fight = {}
    class_ids = {}
    realm_pts = {}
    fight_history = {}  # name -> list of fights (neueste zuerst, max 200)

    def get_rating(name):
        return ratings.get(name, START_RATING)

    def get_fights(name):
        return fights_count.get(name, 0)

    processed = 0
    for fight in fights:
        fid, started_at, winner, w_class, w_rp, loser, l_class, l_rp = fight
        if winner in EXCLUDED_PLAYERS or loser in EXCLUDED_PLAYERS:
            continue

        r_w = get_rating(winner)
        r_l = get_rating(loser)

        exp_w = expected(r_w, r_l)
        exp_l = expected(r_l, r_w)

        k_w = k_factor(get_fights(winner))
        k_l = k_factor(get_fights(loser))

        new_r_w = r_w + k_w * (1 - exp_w)
        new_r_l = r_l + k_l * (0 - exp_l)

        ratings[winner] = round(new_r_w, 2)
        ratings[loser]  = round(new_r_l, 2)

        fights_count[winner] = get_fights(winner) + 1
        fights_count[loser]  = fights_count.get(loser, 0) + 1
        wins_count[winner]   = wins_count.get(winner, 0) + 1
        losses_count[loser]  = losses_count.get(loser, 0) + 1

        peak_ratings[winner] = max(peak_ratings.get(winner, START_RATING), new_r_w)
        peak_ratings[loser]  = max(peak_ratings.get(loser, START_RATING), new_r_l)

        last_fight[winner] = started_at
        last_fight[loser]  = started_at

        if w_class: class_ids[winner] = w_class
        if l_class: class_ids[loser]  = l_class
        if w_rp:    realm_pts[winner] = w_rp
        if l_rp:    realm_pts[loser]  = l_rp

        # Fight History aufzeichnen
        w_entry = {
            "date":       started_at,
            "opponent":   loser,
            "opp_class":  CLASSES.get(l_class, f"Class {l_class}") if l_class else "Unknown",
            "opp_class_id": l_class,
            "result":     "W",
            "elo_before": round(r_w, 1),
            "elo_after":  round(new_r_w, 1),
            "elo_change": round(new_r_w - r_w, 1),
        }
        l_entry = {
            "date":       started_at,
            "opponent":   winner,
            "opp_class":  CLASSES.get(w_class, f"Class {w_class}") if w_class else "Unknown",
            "opp_class_id": w_class,
            "result":     "L",
            "elo_before": round(r_l, 1),
            "elo_after":  round(new_r_l, 1),
            "elo_change": round(new_r_l - r_l, 1),
        }
        if winner not in fight_history: fight_history[winner] = []
        if loser  not in fight_history: fight_history[loser]  = []
        fight_history[winner].append(w_entry)
        fight_history[loser].append(l_entry)

        processed += 1

    # In DB speichern
    for name, rating in ratings.items():
        con.execute("""
            INSERT INTO elo_ratings (name, rating, fights, wins, losses, peak_rating, last_fight, class_id, realm_pts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                rating=excluded.rating,
                fights=excluded.fights,
                wins=excluded.wins,
                losses=excluded.losses,
                peak_rating=excluded.peak_rating,
                last_fight=excluded.last_fight,
                class_id=excluded.class_id,
                realm_pts=excluded.realm_pts
        """, (
            name,
            rating,
            fights_count.get(name, 0),
            wins_count.get(name, 0),
            losses_count.get(name, 0),
            peak_ratings.get(name, START_RATING),
            last_fight.get(name),
            class_ids.get(name),
            realm_pts.get(name),
        ))

    con.commit()
    print(f"  ✓ ELO berechnet: {processed} Fights, {len(ratings)} Spieler")
    return ratings, fight_history


def export_ranking(con, fight_history=None, push=True):
    rows = con.execute("""
        SELECT name, rating, fights, wins, losses, peak_rating, last_fight, class_id, realm_pts
        FROM elo_ratings
        WHERE fights >= 5
        ORDER BY rating DESC
    """).fetchall()

    ranking = []
    for i, row in enumerate(rows):
        name, rating, fights, wins, losses, peak, last, cid, rp = row
        winrate = round(wins / fights * 100) if fights > 0 else 0
        ranking.append({
            "rank":       i + 1,
            "name":       name,
            "rating":     rating,
            "peak":       peak,
            "fights":     fights,
            "wins":       wins,
            "losses":     losses,
            "winrate":    winrate,
            "class_id":   cid,
            "class_name": CLASSES.get(cid, "Unknown") if cid else "Unknown",
            "realm":      CLASS_REALM.get(cid, 0) if cid else 0,
            "realm_name": REALM_NAMES.get(CLASS_REALM.get(cid, 0), "") if cid else "",
            "rr":         rp_to_rr(rp) if rp else "1L1",
            "last_fight": last,
        })

    # Letztes Podium laden
    podium = load_podium()
    last_month = sorted(podium.keys())[-1] if podium else None
    last_month_podium = podium.get(last_month, []) if last_month else []

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_players": len(ranking),
        "ranking": ranking,
        "last_month_podium": last_month_podium,
        "last_month": last_month,
    }

    with open(JSON_PATH, "w") as f:
        json.dump(data, f, separators=(",", ":"))

    print(f"  ✓ ranking.json geschrieben ({len(ranking)} Spieler)")

    # fight_history.json schreiben (neueste zuerst)
    if fight_history:
        history_out = {}
        for name, fights in fight_history.items():
            history_out[name] = list(reversed(fights))  # neueste zuerst
        with open("fight_history.json", "w") as f:
            json.dump(history_out, f, separators=(",", ":"))
        print(f"  ✓ fight_history.json geschrieben ({len(history_out)} Spieler)")

    if push:
        try:
            import os; files=[JSON_PATH,"fight_history.json"]+([PODIUM_PATH] if os.path.exists(PODIUM_PATH) else []); subprocess.run(["git","add"]+files, check=True)
            subprocess.run(["git", "commit", "-m", "update ranking"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("  ✓ GitHub Push erfolgreich")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ Git Push fehlgeschlagen: {e}")


def run(reset=False, push=True):
    con = sqlite3.connect(DB_PATH)
    init_elo_table(con)

    # Auto-Reset am 1. des Monats
    now = datetime.now(timezone.utc)
    is_first_of_month = now.day == 1

    if is_first_of_month and not reset:
        # Podium des Vormonats speichern bevor Reset
        rows = con.execute("""
            SELECT name, rating, class_id, realm_pts
            FROM elo_ratings WHERE fights >= 5
            ORDER BY rating DESC LIMIT 3
        """).fetchall()
        if rows:
            podium = load_podium()
            month_key = now.strftime("%Y-%m")
            # Vormonat
            if now.month == 1:
                prev_month = f"{now.year-1}-12"
            else:
                prev_month = f"{now.year}-{now.month-1:02d}"
            podium[prev_month] = [
                {"name": r[0], "rating": round(r[1],1),
                 "class_id": r[2], "realm_pts": r[3]}
                for r in rows
            ]
            save_podium(podium)
            print(f"  ✓ Podium für {prev_month} gespeichert")
        reset = True
        print("  → Erster des Monats: ELO wird zurückgesetzt")

    _, fight_history = calculate_elo(con, reset=reset)
    export_ranking(con, fight_history=fight_history, push=push)
    con.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ELO Rating Calculator")
    parser.add_argument("--reset",    action="store_true", help="ELO neu berechnen")
    parser.add_argument("--no-push",  action="store_true", help="Kein Git Push")
    args = parser.parse_args()
    run(reset=args.reset, push=not args.no_push)