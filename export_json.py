"""
Export-Script: Liest fights.db und schreibt data.json (letzte 30 Tage).
"""

import sqlite3
import json
import subprocess
from datetime import datetime, timezone, timedelta

DB_PATH   = "fights.db"
JSON_PATH = "data.json"
DAYS_KEEP = 30
MIN_FIGHTS_LEADERBOARD = 1
MIN_FIGHTS_MATCHUP     = 1

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


def compute_stats(con, since_dt):
    cur = con.cursor()

    # ── Daily fights (letzte 7 Tage) ──
    daily = cur.execute("""
        SELECT date(started_at) as day, count(*) as cnt
        FROM fights
        WHERE started_at >= ?
        GROUP BY day ORDER BY day ASC
    """, ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),)).fetchall()

    # ── Summary ──
    total_all = cur.execute("SELECT count(*) FROM fights").fetchone()[0]
    fights_today = cur.execute(
        "SELECT count(*) FROM fights WHERE date(started_at) = date('now')"
    ).fetchone()[0]
    fights_yesterday = cur.execute(
        "SELECT count(*) FROM fights WHERE date(started_at) = date('now','-1 day')"
    ).fetchone()[0]
    avg_duration = cur.execute(
        "SELECT avg(duration) FROM fights WHERE started_at >= ?", (since_dt.isoformat(),)
    ).fetchone()[0] or 0
    active_classes = cur.execute("""
        SELECT count(DISTINCT p.class_id) FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        WHERE f.started_at >= datetime('now','-1 day')
    """).fetchone()[0]

    # ── Class Stats ──
    class_rows = cur.execute("""
        SELECT p.class_id,
               count(DISTINCT f.id) as fights,
               sum(t.won) as wins,
               avg(CASE WHEN t.won=1 THEN f.duration END) as avg_dur_win,
               avg(CASE WHEN t.won=0 THEN f.duration END) as avg_dur_loss
        FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        JOIN fight_teams t ON t.fight_id = f.id AND t.side = p.side
        WHERE f.started_at >= ?
        GROUP BY p.class_id HAVING fights >= 3
        ORDER BY fights DESC
    """, (since_dt.isoformat(),)).fetchall()

    class_stats = []
    for row in class_rows:
        cid, fights, wins, awd, ald = row
        wins = wins or 0
        class_stats.append({
            "class_id":     cid,
            "class_name":   CLASSES.get(cid, f"Class {cid}"),
            "realm":        CLASS_REALM.get(cid, 0),
            "realm_name":   REALM_NAMES.get(CLASS_REALM.get(cid, 0), ""),
            "fights":       fights,
            "wins":         wins,
            "winrate":      round(wins / fights * 100) if fights > 0 else 0,
            "avg_dur_win":  round(awd) if awd else None,
            "avg_dur_loss": round(ald) if ald else None,
        })

    # ── Matchup Matrix ──
    matchup_rows = cur.execute("""
        SELECT pa.class_id, pb.class_id, count(*) as fights, sum(ta.won) as wins_a
        FROM fights f
        JOIN fight_teams ta ON ta.fight_id = f.id AND ta.side = 'a'
        JOIN fight_teams tb ON tb.fight_id = f.id AND tb.side = 'b'
        JOIN fight_players pa ON pa.fight_id = f.id AND pa.side = 'a'
        JOIN fight_players pb ON pb.fight_id = f.id AND pb.side = 'b'
        WHERE f.started_at >= ?
        GROUP BY pa.class_id, pb.class_id HAVING fights >= ?
    """, (since_dt.isoformat(), MIN_FIGHTS_MATCHUP)).fetchall()

    matchups = []
    for ca, cb, fights, wins_a in matchup_rows:
        matchups.append({
            "class_a": ca, "class_a_name": CLASSES.get(ca, f"Class {ca}"),
            "class_b": cb, "class_b_name": CLASSES.get(cb, f"Class {cb}"),
            "fights": fights,
            "winrate_a": round(wins_a / fights * 100) if fights > 0 else 0,
        })

    # ── Häufigste Matchups ──
    top_matchups = cur.execute("""
        SELECT pa.class_id, pb.class_id, count(*) as cnt
        FROM fights f
        JOIN fight_players pa ON pa.fight_id = f.id AND pa.side = 'a'
        JOIN fight_players pb ON pb.fight_id = f.id AND pb.side = 'b'
        WHERE f.started_at >= ?
        GROUP BY pa.class_id, pb.class_id ORDER BY cnt DESC LIMIT 8
    """, (since_dt.isoformat(),)).fetchall()

    common_matchups = []
    seen = set()
    for ca, cb, cnt in top_matchups:
        key = tuple(sorted([ca, cb]))
        if key in seen: continue
        seen.add(key)
        common_matchups.append({
            "class_a": ca, "class_a_name": CLASSES.get(ca, f"Class {ca}"),
            "realm_a": CLASS_REALM.get(ca, 0),
            "class_b": cb, "class_b_name": CLASSES.get(cb, f"Class {cb}"),
            "realm_b": CLASS_REALM.get(cb, 0),
            "count": cnt,
        })

    # ── Leaderboard ──
    lb_rows = cur.execute("""
        SELECT
            p.name,
            p.class_id,
            max(p.realm_pts) as realm_pts,
            count(DISTINCT f.id) as fights,
            sum(t.won) as wins,
            avg(CASE WHEN t.won=1 THEN f.duration END) as avg_dur_win,
            avg(CASE WHEN t.won=0 THEN f.duration END) as avg_dur_loss
        FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        JOIN fight_teams t ON t.fight_id = f.id AND t.side = p.side
        WHERE f.started_at >= ?
        GROUP BY p.name
        HAVING fights >= ?
        ORDER BY wins * 1.0 / fights DESC
    """, (since_dt.isoformat(), MIN_FIGHTS_LEADERBOARD)).fetchall()

    leaderboard = []
    for row in lb_rows:
        name, cid, rp, fights, wins, awd, ald = row
        wins = wins or 0
        losses = fights - wins
        leaderboard.append({
            "name":         name,
            "class_id":     cid,
            "class_name":   CLASSES.get(cid, f"Class {cid}"),
            "realm":        CLASS_REALM.get(cid, 0),
            "realm_name":   REALM_NAMES.get(CLASS_REALM.get(cid, 0), ""),
            "rr":           rp_to_rr(rp),
            "fights":       fights,
            "wins":         wins,
            "losses":       losses,
            "winrate":      round(wins / fights * 100) if fights > 0 else 0,
            "avg_dur_win":  round(awd) if awd else None,
            "avg_dur_loss": round(ald) if ald else None,
        })

    return {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "summary": {
            "fights_today":     fights_today,
            "fights_yesterday": fights_yesterday,
            "total_fights":     total_all,
            "active_classes":   active_classes,
            "avg_duration":     round(avg_duration),
        },
        "class_stats":     class_stats,
        "matchups":        matchups,
        "common_matchups": common_matchups,
        "daily_fights":    [{"day": r[0], "count": r[1]} for r in daily],
        "leaderboard":     leaderboard,
    }


def export(push=True):
    con = sqlite3.connect(DB_PATH)
    since = datetime.now(timezone.utc) - timedelta(days=DAYS_KEEP)

    deleted = con.execute(
        "DELETE FROM fights WHERE started_at < ?", (since.isoformat(),)
    ).rowcount
    con.execute("DELETE FROM fight_teams WHERE fight_id NOT IN (SELECT id FROM fights)")
    con.execute("DELETE FROM fight_players WHERE fight_id NOT IN (SELECT id FROM fights)")
    con.commit()
    if deleted:
        print(f"  🗑  {deleted} alte Fights gelöscht (>30 Tage)")

    stats = compute_stats(con, since)
    con.close()

    with open(JSON_PATH, "w") as f:
        json.dump(stats, f, separators=(",", ":"))

    print(f"  ✓ data.json geschrieben ({len(json.dumps(stats))} bytes)")

    if push:
        try:
            subprocess.run(["git", "add", JSON_PATH], check=True)
            subprocess.run(["git", "commit", "-m", "update fight data"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("  ✓ GitHub Push erfolgreich")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ Git Push fehlgeschlagen: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()
    export(push=not args.no_push)