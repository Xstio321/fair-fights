import asyncio
import os
import re
from urllib.parse import urlparse, parse_qs

import discord
from dotenv import load_dotenv

from database.db import init_db, save_fight, extract_zone_from_title

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "0"))

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


def clean_value(value):
    value = value.strip()
    value = re.sub(r"<a?:[^:]+:\d+>", "", value)
    value = value.replace("**", "")
    value = value.replace("`", "")
    return value.strip()


def replace_markdown_link_with_text(value):
    value = value.strip()

    if value.startswith("[") and "](" in value:
        end_text = value.find("](")
        end_url = value.find(")", end_text)

        if end_url != -1:
            link_text = value[1:end_text]
            rest = value[end_url + 1:]
            return f"{link_text}{rest}".strip()

    return value


def parse_player_and_class(value):
    value = clean_value(value)
    value = replace_markdown_link_with_text(value)

    separators = ["·", "•", " - ", " – ", " — ", "|"]

    for separator in separators:
        if separator in value:
            parts = [part.strip() for part in value.split(separator, 1)]
            if len(parts) == 2:
                return parts[0], parts[1]

    return value, None


def parse_multiple_players(value):
    value = value.strip()

    lines = []
    for line in value.splitlines():
        line = line.strip()
        if line:
            lines.append(line)

    if not lines:
        lines = [value]

    players = []

    for line in lines:
        name, player_class = parse_player_and_class(line)
        players.append({
            "name": name,
            "class": player_class
        })

    return players[:8]


def extract_scoreboard_code_from_url(fight_url):
    parsed = urlparse(fight_url)
    query = parse_qs(parsed.query)

    if "id" in query and query["id"]:
        return query["id"][0]

    return fight_url.rstrip("/").split("/")[-1]


def build_fight_url_from_scoreboard(value):
    value = clean_value(value)

    if "http" in value:
        start = value.find("http")
        end = value.find(")", start)

        if end == -1:
            fight_url = value[start:].strip()
        else:
            fight_url = value[start:end].strip()

        scoreboard_code = extract_scoreboard_code_from_url(fight_url)
        return scoreboard_code, fight_url

    scoreboard_code = value.strip()
    fight_url = f"https://eden-daoc.net/fights?id={scoreboard_code}"

    return scoreboard_code, fight_url


def extract_fight_data_from_embed(embed):
    data = {
        "zone": extract_zone_from_title(embed.title or ""),
        "winner_name": None,
        "winner_class": None,
        "losers": [],
        "duration": None,
        "scoreboard_code": None,
        "fight_url": None,
        "raw_scoreboard_value": None,
    }

    for field in embed.fields:
        field_name = field.name.lower().strip()
        field_value = field.value.strip()

        if field_name.startswith("victory"):
            winners = parse_multiple_players(field_value)
            if winners:
                data["winner_name"] = winners[0]["name"]
                data["winner_class"] = winners[0]["class"]

        elif field_name.startswith("defeat"):
            data["losers"] = parse_multiple_players(field_value)

        elif field_name == "duration":
            data["duration"] = clean_value(field_value)

        elif field_name == "scoreboard":
            scoreboard_code, fight_url = build_fight_url_from_scoreboard(field_value)
            data["scoreboard_code"] = scoreboard_code
            data["fight_url"] = fight_url
            data["raw_scoreboard_value"] = field_value

    return data


def extract_scoreboard(message, source="LIVE"):
    found = False

    for embed in message.embeds:
        embed_title = embed.title or ""

        if "fight occurred" not in embed_title.lower():
            continue

        data = extract_fight_data_from_embed(embed)

        if not data["scoreboard_code"]:
            continue

        save_fight(
            scoreboard_code=data["scoreboard_code"],
            fight_url=data["fight_url"],
            fight_timestamp=message.created_at.isoformat(),
            zone=data["zone"],
            winner_name=data["winner_name"],
            winner_class=data["winner_class"],
            losers=data["losers"],
            duration=data["duration"],
            discord_message_id=message.id,
        )

        loser_text = ", ".join(
            f"{loser['name']} ({loser['class']})"
            for loser in data["losers"]
        )

        print(
            f"[{source}] Gespeichert/aktualisiert: "
            f"{data['scoreboard_code']} | "
            f"{data['winner_name']} ({data['winner_class']}) "
            f"vs {loser_text} | "
            f"{data['zone']} | {data['duration']}"
        )

        found = True

    return found


@client.event
async def on_ready():
    from database.db import get_latest_message_id
    init_db()

    print("-" * 50)
    print(f"Bot online als: {client.user}")
    print(f"Überwachter Channel: {CHANNEL_ID}")

    channel = client.get_channel(CHANNEL_ID)

    if channel is None:
        print("Channel nicht gefunden. Prüfe CHANNEL_ID und Berechtigungen.")
        return

    # Letzten bekannten Message-ID aus DB holen
    latest_id = get_latest_message_id()

    if latest_id:
        print(f"Letzter bekannter Fight: Message-ID {latest_id}")
        print("Scanne nur neue Nachrichten seit letztem Start...")
        after_obj = discord.Object(id=latest_id)
        history_kwargs = {"limit": None, "after": after_obj, "oldest_first": True}
    elif HISTORY_LIMIT == 0:
        print("Keine bekannten Daten — scanne komplette Channel-History...")
        history_kwargs = {"limit": None, "oldest_first": True}
    else:
        print(f"Scanne letzte {HISTORY_LIMIT} Nachrichten...")
        history_kwargs = {"limit": HISTORY_LIMIT, "oldest_first": True}

    print("-" * 50)

    total = 0
    found = 0

    async for message in channel.history(**history_kwargs):
        total += 1
        if extract_scoreboard(message, source="HISTORY"):
            found += 1

    print("-" * 50)
    print("Historischer Scan abgeschlossen.")
    print(f"Geprüfte Nachrichten: {total}")
    print(f"Fight-Posts gefunden: {found}")
    print("Warte jetzt auf neue Nachrichten...")
    print("-" * 50)


@client.event
async def on_message(message):
    if message.channel.id != CHANNEL_ID:
        return

    # Discord liefert Embeds bei neuen Nachrichten asynchron nach —
    # kurz warten damit die Embeds vollständig geladen sind, bevor
    # wir die Nachricht verarbeiten.
    await asyncio.sleep(2)

    # Nachricht neu abrufen damit die Embeds sicher vorhanden sind
    try:
        message = await message.channel.fetch_message(message.id)
    except Exception:
        pass

    extract_scoreboard(message, source="LIVE")


def start_bot():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN fehlt in .env")

    if CHANNEL_ID == 0:
        raise RuntimeError("CHANNEL_ID fehlt in .env")

    client.run(TOKEN)