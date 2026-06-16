"""
8v8 Leaderboard Export – liest fights_8v8.db, schreibt data_8v8.json
Gruppen-Leaderboard: eine Zeile pro Gruppe (Leader), Dropdown zeigt Einzelspieler
"""

import sqlite3
import json
import subprocess
from datetime import datetime, timezone, timedelta
from collections import defaultdict

DB_PATH   = "fights_8v8.db"
JSON_PATH = "data_8v8.json"
MIN_FIGHTS = 3

CLASSES = {
    1:"Paladin",2:"Armsman",3:"Scout",4:"Minstrel",5:"Theurgist",6:"Cleric",
    7:"Wizard",8:"Sorcerer",9:"Infiltrator",10:"Friar",11:"Mercenary",12:"Necromancer",
    13:"Cabalist",19:"Reaver",33:"Heretic",63:"Occultist",
    21:"Thane",22:"Warrior",23:"Shadowblade",24:"Skald",25:"Hunter",26:"Healer",
    27:"Spiritmaster",28:"Shaman",29:"Runemaster",30:"Bonedancer",31:"Berserker",
    32:"Savage",34:"Valkyrie",59:"Warlock",
    39:"Bainshee",40:"Eldritch",41:"Enchanter",42:"Mentalist",43:"Blademaster",
    44:"Hero",45:"Champion",46:"Warden",47:"Druid",48:"Bard",49:"Nightshade",
    50:"Ranger",55:"Animist",56:"Valewalker",58:"Vampiir",
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
    (9111713,"11L1"),(10114001,"11L2"),(11226541,"11L3"),(12461460,"11L4"),
    (13832221,"11L5"),(15353765,"11L6"),(17042680,"11L7"),(18917374,"11L8"),(20998286,"11L9"),
    (23308097,"12L0"),(25871988,"12L1"),(28717906,"12L2"),(31876876,"12L3"),(35383333,"12L4"),
    (39275499,"12L5"),(43595804,"12L6"),(48391343,"12L7"),(53714390,"12L8"),(59622973,"12L9"),
    (66181501,"13L0"),(73461466,"13L1"),(81542227,"13L2"),(90511872,"13L3"),(100468178,"13L4"),
    (111519678,"13L5"),(123786843,"13L6"),(137403395,"13L7"),(152517769,"13L8"),(169294723,"13L9"),
    (187917143,"14L0"),(223084000,"14L1"),(278317600,"14L2"),(355644640,"14L3"),(445902496,"14L4"),
    (555928241,"14L5"),(680853214,"14L6"),(820594584,"14L7"),(990514251,"14L8"),(1230285525,"14L9"),
    (1650444126,"15L0"),
]

def rp_to_rr(rp):
    label = "1L1"
    for min_rp, lbl in REALM_RANKS:
        if rp and rp >= min_rp:
            label = lbl
    return label

def wilson_score(wins, n):
    if n == 0: return 0
    z = 1.96
    p = wins / n
    score = (p + z*z/(2*n) - z * (p*(1-p)/n + z*z/(4*n*n))**0.5) / (1 + z*z/n)
    return round(score * 100, 2)

def compute_stats(con):
    cur = con.cursor()

    def build_leaderboard(days=None):
        where = "WHERE 1=1"
        params = []
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            where += " AND f.started_at >= ?"
            params.append(cutoff)

        rows = cur.execute(f"""
            SELECT g.leader, g.realm,
                   count(DISTINCT f.id) as fights,
                   sum(g.won) as wins,
                   max(f.started_at) as last_fight
            FROM fight_groups g
            JOIN fights f ON f.id = g.fight_id
            {where}
            GROUP BY g.leader
            HAVING fights >= ?
            ORDER BY wins * 1.0 / fights DESC
        """, params + [MIN_FIGHTS]).fetchall()

        result = []
        for leader, realm, fights, wins, last_fight in rows:
            wins = wins or 0
            losses = fights - wins
            result.append({
                "leader":     leader,
                "realm":      realm or 0,
                "realm_name": REALM_NAMES.get(realm or 0, ""),
                "fights":     fights,
                "wins":       wins,
                "losses":     losses,
                "winrate":    round(wins / fights * 100) if fights > 0 else 0,
                "wilson":     wilson_score(wins, fights),
                "last_fight": last_fight,
            })
        return result

    def build_fight_history():
        # Pro Gruppe (leader) die letzten 20 Fights mit allen Spielern
        rows = cur.execute("""
            SELECT g.leader, g.side, g.won, f.id, f.started_at, f.zone_id,
                   p.name, p.class_id, p.realm_pts, p.dmg_done, p.heal_done, p.dmg_taken
            FROM fight_groups g
            JOIN fights f ON f.id = g.fight_id
            JOIN fight_players p ON p.fight_id = f.id AND p.side = g.side
            ORDER BY g.leader, f.started_at DESC
        """).fetchall()

        group_fights = defaultdict(lambda: defaultdict(lambda: {
            "fight_id": None, "started_at": None, "zone_id": None,
            "won": None, "players": []
        }))

        for leader, side, won, fid, started_at, zone_id, name, cid, rp, dmg, heal, taken in rows:
            gf = group_fights[leader][fid]
            gf["fight_id"] = fid
            gf["started_at"] = started_at
            gf["zone_id"] = zone_id
            gf["won"] = won
            gf["players"].append({
                "name":       name,
                "class_id":   cid,
                "class_name": CLASSES.get(cid, f"Class {cid}"),
                "rr":         rp_to_rr(rp),
                "dmg_done":   dmg or 0,
                "heal_done":  heal or 0,
                "dmg_taken":  taken or 0,
            })

        result = {}
        for leader, fights in group_fights.items():
            sorted_fights = sorted(fights.values(), key=lambda x: x["started_at"] or "", reverse=True)[:20]
            result[leader] = sorted_fights
        return result

    total = cur.execute("SELECT count(*) FROM fights").fetchone()[0]
    today = cur.execute("SELECT count(*) FROM fights WHERE date(started_at) = date('now')").fetchone()[0]
    yesterday = cur.execute("SELECT count(*) FROM fights WHERE date(started_at) = date('now','-1 day')").fetchone()[0]
    active = cur.execute("""
        SELECT count(DISTINCT leader) FROM fight_groups g
        JOIN fights f ON f.id = g.fight_id
        WHERE f.started_at >= datetime('now', '-1 day')
    """).fetchone()[0]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "fights_today":     today,
            "fights_yesterday": yesterday,
            "total_fights":     total,
            "active_groups":    active,
        },
        "leaderboard":    build_leaderboard(30),
        "leaderboard_1d": build_leaderboard(1),
        "leaderboard_3d": build_leaderboard(3),
        "leaderboard_7d": build_leaderboard(7),
        "fight_history":  build_fight_history(),
    }

def export(push=True):
    con = sqlite3.connect(DB_PATH)
    data = compute_stats(con)
    con.close()

    with open(JSON_PATH, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"  ✓ {JSON_PATH} geschrieben ({len(data['leaderboard'])} Gruppen)")

    if push:
        try:
            subprocess.run(["git", "add", JSON_PATH], check=True)
            subprocess.run(["git", "commit", "-m", "update 8v8 data"], check=True)
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