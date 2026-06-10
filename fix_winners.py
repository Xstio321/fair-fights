"""
Korrigiert die won-Spalte in fight_teams anhand der deaths in fight_players.
Einmalig ausführen um die bestehende DB zu reparieren.
"""
import sqlite3

DB_PATH = "fights.db"

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

fights = cur.execute("SELECT id FROM fights").fetchall()
fixed = 0

for (fight_id,) in fights:
    deaths_a = cur.execute(
        "SELECT sum(deaths) FROM fight_players WHERE fight_id=? AND side='a'",
        (fight_id,)
    ).fetchone()[0] or 0

    deaths_b = cur.execute(
        "SELECT sum(deaths) FROM fight_players WHERE fight_id=? AND side='b'",
        (fight_id,)
    ).fetchone()[0] or 0

    if deaths_b > deaths_a:
        winner, loser = 'a', 'b'
    elif deaths_a > deaths_b:
        winner, loser = 'b', 'a'
    else:
        continue  # unentschieden, überspringen

    cur.execute("UPDATE fight_teams SET won=1 WHERE fight_id=? AND side=?", (fight_id, winner))
    cur.execute("UPDATE fight_teams SET won=0 WHERE fight_id=? AND side=?", (fight_id, loser))
    fixed += 1

con.commit()
con.close()
print(f"✓ {fixed} Fights korrigiert von {len(fights)} gesamt.")
