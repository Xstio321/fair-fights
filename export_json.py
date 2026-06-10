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

ZONE_NAMES = {
    163: "Ellan Vannin",
    167: "Odin's Gate",
    168: "Jamtland Mountains",
    169: "Yggdra Forest",
    170: "Uppland",
    171: "Emain Macha",
    172: "Breifine",
    173: "Cruachan Gorge",
    174: "Mount Collory",
    175: "Snowdonia",
    176: "Forest Sauvage",
    177: "Pennine Mountains",
    178: "Hadrian's Wall",
}

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


def wilson_score(wins, fights):
    """Wilson Score Interval (untere Grenze, 95% Konfidenz)."""
    if fights == 0:
        return 0.0
    z = 1.96  # 95% Konfidenz
    p = wins / fights
    n = fights
    score = (p + z*z/(2*n) - z * ((p*(1-p)+z*z/(4*n))/n)**0.5) / (1 + z*z/n)
    return round(score * 100, 2)


def compute_stats(con, since_dt):
    cur = con.cursor()
    since_str = since_dt.isoformat()

    # ── Daily fights ──
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    daily = cur.execute("""
        SELECT date(started_at) as day, count(*) as cnt
        FROM fights
        WHERE started_at >= ?
        GROUP BY day ORDER BY day ASC
    """, ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),)).fetchall()

    # ── Zone Zeitreihe (heute + gestern getrennt, stündlich) ──
    from collections import defaultdict

    def fetch_zone_ts(date_filter):
        rows = cur.execute("""
            SELECT
                zone_id,
                CAST(strftime('%H', started_at) AS INTEGER) as hour,
                count(*) as cnt
            FROM fights
            WHERE date(started_at) = ? AND zone_id IS NOT NULL
            GROUP BY zone_id, hour
            ORDER BY hour ASC
        """, (date_filter,)).fetchall()
        ts = defaultdict(list)
        for zone_id, hour, cnt in rows:
            if zone_id in ZONE_NAMES:
                ts[zone_id].append({"hour": hour, "count": cnt})
        return [
            {"zone_id": zid, "name": ZONE_NAMES[zid], "data": data}
            for zid, data in sorted(ts.items(), key=lambda x: -sum(d["count"] for d in x[1]))
        ]

    today_str     = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
    zone_today     = fetch_zone_ts(today_str)
    zone_yesterday = fetch_zone_ts(yesterday_str)

    # Top 5 busiest zones last hour
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    busy_zones_rows = cur.execute("""
        SELECT zone_id, count(*) as cnt
        FROM fights
        WHERE started_at >= ? AND zone_id IS NOT NULL
        GROUP BY zone_id
        ORDER BY cnt DESC
        LIMIT 5
    """, (one_hour_ago,)).fetchall()
    busy_zones = [
        {"zone_id": r[0], "name": ZONE_NAMES.get(r[0], f"Zone {r[0]}"), "count": r[1]}
        for r in busy_zones_rows if r[0] in ZONE_NAMES
    ]

    # ── Summary ──
    total_all = cur.execute("SELECT count(*) FROM fights").fetchone()[0]
    fights_today = cur.execute(
        "SELECT count(*) FROM fights WHERE date(started_at) = date('now')"
    ).fetchone()[0]
    fights_yesterday = cur.execute(
        "SELECT count(*) FROM fights WHERE date(started_at) = date('now','-1 day')"
    ).fetchone()[0]

    # 1v1 aktive Spieler (letzte 24h) statt Klassen
    active_players = cur.execute("""
        SELECT count(DISTINCT p.name)
        FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        WHERE f.started_at >= datetime('now','-1 day')
    """).fetchone()[0]

    # ── Class Stats ──
    class_rows = cur.execute("""
        SELECT p.class_id,
               count(DISTINCT f.id) as fights,
               sum(t.won) as wins,
               max(f.started_at) as last_fight
        FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        JOIN fight_teams t ON t.fight_id = f.id AND t.side = p.side
        WHERE f.started_at >= ?
        GROUP BY p.class_id
        ORDER BY fights DESC
    """, (since_str,)).fetchall()

    class_stats = []
    for row in class_rows:
        cid, fights, wins, last_fight = row
        wins = wins or 0
        class_stats.append({
            "class_id":     cid,
            "class_name":   CLASSES.get(cid, f"Class {cid}"),
            "realm":        CLASS_REALM.get(cid, 0),
            "realm_name":   REALM_NAMES.get(CLASS_REALM.get(cid, 0), ""),
            "fights":       fights,
            "wins":         wins,
            "winrate":      round(wins / fights * 100) if fights > 0 else 0,
            "last_fight":   last_fight,
        })

    # ── Matchup Matrix ──
    def build_matchups_from_rows(rows):
        from collections import defaultdict
        data = defaultdict(lambda: {"total": 0, "wins_a": 0})
        for winner_class, loser_class in rows:
            ca = min(winner_class, loser_class)
            cb = max(winner_class, loser_class)
            data[(ca, cb)]["total"] += 1
            if winner_class == ca:
                data[(ca, cb)]["wins_a"] += 1
        result = []
        for (ca, cb), d in data.items():
            total = d["total"]
            if total < MIN_FIGHTS_MATCHUP:
                continue
            result.append({
                "class_a": ca, "class_a_name": CLASSES.get(ca, f"Class {ca}"),
                "class_b": cb, "class_b_name": CLASSES.get(cb, f"Class {cb}"),
                "fights": total,
                "winrate_a": round(d["wins_a"] / total * 100) if total > 0 else 0,
            })
        return result

    MATCHUP_SQL = """
        SELECT pw.class_id, pl.class_id
        FROM fights f
        JOIN fight_players pw ON pw.fight_id = f.id
        JOIN fight_teams tw ON tw.fight_id = f.id AND tw.side = pw.side AND tw.won = 1
        JOIN fight_players pl ON pl.fight_id = f.id
        JOIN fight_teams tl ON tl.fight_id = f.id AND tl.side = pl.side AND tl.won = 0
    """

    # Nach Zeitfenster (30d)
    rows_time = cur.execute(MATCHUP_SQL + " WHERE f.started_at >= ?", (since_str,)).fetchall()
    matchups = build_matchups_from_rows(rows_time)

    # Nach letzten N Fights PRO Klassen-Kombination
    def matchups_last_n(n):
        # Alle Fights holen mit Zeitstempel
        rows = cur.execute(MATCHUP_SQL + """
            ORDER BY f.started_at DESC
        """).fetchall()

        from collections import defaultdict
        # Pro Klassen-Paar die letzten N Fights sammeln
        pair_fights = defaultdict(list)
        for winner_class, loser_class in rows:
            ca = min(winner_class, loser_class)
            cb = max(winner_class, loser_class)
            pair_fights[(ca, cb)].append((winner_class, loser_class))

        # Pro Paar nur die letzten N nehmen
        limited = []
        for pair, fights in pair_fights.items():
            for f in fights[:n]:
                limited.append(f)

        return build_matchups_from_rows(limited)

    matchups_100  = matchups_last_n(100)
    matchups_500  = matchups_last_n(500)
    matchups_1000 = matchups_last_n(1000)

    # Alltime Matchups
    rows_all = cur.execute(MATCHUP_SQL).fetchall()
    matchups_all = build_matchups_from_rows(rows_all)

    # ── Häufigste Matchups (für verschiedene Zeitfenster) ──
    def build_common_matchups(days):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = cur.execute(MATCHUP_SQL + " WHERE f.started_at >= ? ORDER BY f.started_at DESC", (cutoff,)).fetchall()
        data = build_matchups_from_rows(rows)
        top = sorted(data, key=lambda x: x["fights"], reverse=True)[:8]
        return [{
            "class_a": m["class_a"], "class_a_name": m["class_a_name"],
            "realm_a": CLASS_REALM.get(m["class_a"], 0),
            "class_b": m["class_b"], "class_b_name": m["class_b_name"],
            "realm_b": CLASS_REALM.get(m["class_b"], 0),
            "count": m["fights"],
        } for m in top]

    common_out = build_common_matchups(30)
    common_1d  = build_common_matchups(1)
    common_3d  = build_common_matchups(3)
    common_7d  = build_common_matchups(7)

    # ── Leaderboard ──
    lb_rows = cur.execute("""
        SELECT
            p.name,
            p.class_id,
            max(p.realm_pts) as realm_pts,
            count(DISTINCT f.id) as fights,
            sum(t.won) as wins,
            max(f.started_at) as last_fight
        FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        JOIN fight_teams t ON t.fight_id = f.id AND t.side = p.side
        WHERE f.started_at >= ?
        GROUP BY p.name
        HAVING fights >= ?
        ORDER BY wins * 1.0 / fights DESC
    """, (since_str, MIN_FIGHTS_LEADERBOARD)).fetchall()

    # Avg RR der Gegner bei Wins und Losses pro Spieler
    opp_rp_rows = cur.execute("""
        SELECT
            p.name,
            t.won,
            avg(opp.realm_pts) as avg_opp_rp
        FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        JOIN fight_teams t ON t.fight_id = f.id AND t.side = p.side
        JOIN fight_players opp ON opp.fight_id = f.id AND opp.side != p.side
        WHERE f.started_at >= ? AND opp.realm_pts IS NOT NULL
        GROUP BY p.name, t.won
    """, (since_str,)).fetchall()

    opp_rp_map = {}
    for name, won, avg_rp in opp_rp_rows:
        if name not in opp_rp_map:
            opp_rp_map[name] = {}
        opp_rp_map[name][won] = int(avg_rp) if avg_rp else None

    leaderboard = []
    for row in lb_rows:
        name, cid, rp, fights, wins, last_fight = row
        wins = wins or 0
        losses = fights - wins
        orpm = opp_rp_map.get(name, {})
        avg_win_rp  = orpm.get(1)
        avg_loss_rp = orpm.get(0)
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
            "wilson":       wilson_score(wins, fights),
            "avg_win_rr":   rp_to_rr(avg_win_rp)  if avg_win_rp  else None,
            "avg_loss_rr":  rp_to_rr(avg_loss_rp) if avg_loss_rp else None,
            "last_fight":   last_fight,
        })

    # ── Class Drill-Down ──
    cp_rows = cur.execute("""
        SELECT p.class_id, p.name, max(p.realm_pts) as rp,
               count(DISTINCT f.id) as fights, sum(t.won) as wins
        FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        JOIN fight_teams t ON t.fight_id = f.id AND t.side = p.side
        WHERE f.started_at >= ?
        GROUP BY p.class_id, p.name
        ORDER BY p.class_id, wins * 1.0 / count(DISTINCT f.id) DESC
    """, (since_str,)).fetchall()

    class_players = {}
    for cid, name, rp, fights, wins in cp_rows:
        wins = wins or 0
        if cid not in class_players:
            class_players[cid] = []
        class_players[cid].append({
            "name": name, "rr": rp_to_rr(rp),
            "fights": fights, "wins": wins, "losses": fights - wins,
            "winrate": round(wins / fights * 100) if fights > 0 else 0,
            "wilson":  wilson_score(wins, fights),
        })

    # ── Spieler-Profile ──
    profile_rows = cur.execute("""
        SELECT
            p.name,
            p.class_id,
            f.zone_id,
            strftime('%H', f.started_at) as hour,
            t.won,
            opp.class_id as opp_class_id,
            opp.realm_pts as opp_rp
        FROM fight_players p
        JOIN fights f ON f.id = p.fight_id
        JOIN fight_teams t ON t.fight_id = f.id AND t.side = p.side
        JOIN fight_players opp ON opp.fight_id = f.id AND opp.side != p.side
        WHERE f.started_at >= ?
    """, (since_str,)).fetchall()

    from collections import defaultdict, Counter
    player_profiles = defaultdict(lambda: {
        "zones": Counter(), "hours": Counter(),
        "won_vs": Counter(), "lost_vs": Counter(),
        "won_vs_rp": defaultdict(list), "lost_vs_rp": defaultdict(list),
    })

    for name, cid, zone_id, hour, won, opp_cid, opp_rp in profile_rows:
        pp = player_profiles[name]
        if zone_id and zone_id in ZONE_NAMES:
            pp["zones"][ZONE_NAMES[zone_id]] += 1
        if hour:
            pp["hours"][int(hour)] += 1
        if won:
            pp["won_vs"][opp_cid] += 1
            if opp_rp: pp["won_vs_rp"][opp_cid].append(opp_rp)
        else:
            pp["lost_vs"][opp_cid] += 1
            if opp_rp: pp["lost_vs_rp"][opp_cid].append(opp_rp)

    player_profile_data = {}
    for name, pp in player_profiles.items():
        top_zones = [{"name": z, "count": c} for z, c in pp["zones"].most_common(5)]
        top_hours = [{"hour": h, "count": c} for h, c in sorted(pp["hours"].items(), key=lambda x: -x[1])[:5]]
        won_vs = []
        for cid, c in pp["won_vs"].most_common(5):
            rp_list = pp["won_vs_rp"].get(cid, [])
            avg_rp = int(sum(rp_list)/len(rp_list)) if rp_list else None
            won_vs.append({
                "class_id": cid, "class_name": CLASSES.get(cid, f"Class {cid}"),
                "count": c, "avg_rr": rp_to_rr(avg_rp) if avg_rp else None
            })
        lost_vs = []
        for cid, c in pp["lost_vs"].most_common(5):
            rp_list = pp["lost_vs_rp"].get(cid, [])
            avg_rp = int(sum(rp_list)/len(rp_list)) if rp_list else None
            lost_vs.append({
                "class_id": cid, "class_name": CLASSES.get(cid, f"Class {cid}"),
                "count": c, "avg_rr": rp_to_rr(avg_rp) if avg_rp else None
            })
        player_profile_data[name] = {
            "top_zones": top_zones,
            "top_hours": top_hours,
            "won_vs":    won_vs,
            "lost_vs":   lost_vs,
        }

    # ── Top Underdog Wins (1vX) ──
    # Nur Kämpfe wo der Gewinner alleine war (size = Anzahl Gegner, Gewinnerteam hat 1 Spieler)
    underdog_rows = cur.execute("""
        SELECT
            p.name,
            p.class_id,
            p.realm_pts,
            f.size as opponents,
            f.started_at
        FROM fights f
        JOIN fight_teams tw ON tw.fight_id = f.id AND tw.won = 1
        JOIN fight_players p ON p.fight_id = f.id AND p.side = tw.side
        WHERE f.size > 1
          AND f.started_at >= ?
          AND (
            SELECT count(*) FROM fight_players p2
            WHERE p2.fight_id = f.id AND p2.side = tw.side
          ) = 1
        ORDER BY f.size DESC, f.started_at DESC
    """, (since_str,)).fetchall()

    # Pro Spieler den besten (höchsten) Underdog-Win nehmen
    seen_underdog = {}
    for name, cid, rp, opponents, started_at in underdog_rows:
        if name not in seen_underdog or opponents > seen_underdog[name]['opponents']:
            seen_underdog[name] = {
                "name":       name,
                "class_id":   cid,
                "class_name": CLASSES.get(cid, f"Class {cid}"),
                "realm":      CLASS_REALM.get(cid, 0),
                "rr":         rp_to_rr(rp),
                "opponents":  opponents,
                "label":      f"1v{opponents}",
            }

    # Realm Rank zu numerischem Wert umrechnen für Sortierung
    def rr_to_sort_key(rr_label):
        # z.B. "4L2" -> 4*10+2 = 42, niedrigerer Wert = niedrigerer Rank
        try:
            parts = rr_label.replace('L','x').split('x')
            return int(parts[0]) * 10 + int(parts[1])
        except:
            return 999

    # Sortieren: erst nach Gegneranzahl (desc), dann nach RR (asc = niedrigster zuerst)
    top_underdog = sorted(
        seen_underdog.values(),
        key=lambda x: (-x['opponents'], rr_to_sort_key(x['rr']))
    )[:5]

    # ── Top 3 Klassen pro Realm (für verschiedene Zeitfenster) ──
    def build_top_classes(days):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = cur.execute("""
            SELECT p.class_id, count(DISTINCT p.name) as players
            FROM fight_players p
            JOIN fights f ON f.id = p.fight_id
            WHERE f.started_at >= ?
            GROUP BY p.class_id
            ORDER BY players DESC
        """, (cutoff,)).fetchall()
        from collections import defaultdict
        rc = defaultdict(list)
        for cid, players in rows:
            realm = CLASS_REALM.get(cid, 0)
            if realm > 0:
                rc[realm].append({"class_id": cid, "class_name": CLASSES.get(cid, f"Class {cid}"), "players": players})
        return {"albion": rc[1][:3], "midgard": rc[2][:3], "hibernia": rc[3][:3]}

    top_classes_by_realm    = build_top_classes(30)
    top_classes_by_realm_1d = build_top_classes(1)
    top_classes_by_realm_3d = build_top_classes(3)
    top_classes_by_realm_7d = build_top_classes(7)

    return {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "summary": {
            "fights_today":     fights_today,
            "fights_yesterday": fights_yesterday,
            "total_fights":     total_all,
            "active_players":   active_players,
        },
        "class_stats":     class_stats,
        "class_players":   class_players,
        "matchups":        matchups,
        "matchups_100":    matchups_100,
        "matchups_500":    matchups_500,
        "matchups_1000":   matchups_1000,
        "matchups_all":    matchups_all,
        "common_matchups":    common_out,
        "common_matchups_1d": common_1d,
        "common_matchups_3d": common_3d,
        "common_matchups_7d": common_7d,
        "daily_fights":    [{"day": r[0], "count": r[1]} for r in daily],
        "zone_today":      zone_today,
        "busy_zones":      busy_zones,
        "top_classes_by_realm":    top_classes_by_realm,
        "top_classes_by_realm_1d": top_classes_by_realm_1d,
        "top_classes_by_realm_3d": top_classes_by_realm_3d,
        "top_classes_by_realm_7d": top_classes_by_realm_7d,
        "zone_yesterday":  zone_yesterday,
        "leaderboard":     leaderboard,
        "top_underdog":    top_underdog,
        "player_profiles": player_profile_data,
    }


def export(push=True):
    con = sqlite3.connect(DB_PATH)
    since = datetime.now(timezone.utc) - timedelta(days=DAYS_KEEP)

    # Fights werden nie gelöscht - alltime Daten bleiben erhalten

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