# Import Statements
from alive_progress import alive_it
import copy
from datetime import datetime, timezone
import discord
from dotenv import load_dotenv
from functools import cmp_to_key
from heapq import nlargest
import lxml.html
import lxml.cssselect
import math
import os
import requests
import sqlite3

# API Tokens
load_dotenv()
CR_API_TOKEN = os.getenv("CR_API_TOKEN")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# SQLite database name
DB_FILE_NAME = "database.db"

# SQL Database Schemas
SQL_CREATE_CARDS_TABLE = """
                            CREATE TABLE IF NOT EXISTS cards (
                                id text PRIMARY KEY,
                                name text NOT NULL,
                                elixir integer NOT NULL,
                                type text NOT NULL,
                                rarity text NOT NULL
                            );
                        """
SQL_CREATE_DECKS_TABLE = """
                            CREATE TABLE IF NOT EXISTS decks (
                                id text PRIMARY KEY,
                                card_1 text NOT NULL,
                                card_2 text NOT NULL,
                                card_3 text NOT NULL,
                                card_4 text NOT NULL,
                                card_5 text NOT NULL,
                                card_6 text NOT NULL,
                                card_7 text NOT NULL,
                                card_8 text NOT NULL,
                                rating integer NOT NULL,
                                usage integer NOT NULL,
                                win_rate DECIMAL(4,1) NOT NULL,
                                entry_date DATE NOT NULL,
                                FOREIGN KEY (card_1) REFERENCES cards (id),
                                FOREIGN KEY (card_2) REFERENCES cards (id),
                                FOREIGN KEY (card_3) REFERENCES cards (id),
                                FOREIGN KEY (card_4) REFERENCES cards (id),
                                FOREIGN KEY (card_5) REFERENCES cards (id),
                                FOREIGN KEY (card_6) REFERENCES cards (id),
                                FOREIGN KEY (card_7) REFERENCES cards (id),
                                FOREIGN KEY (card_8) REFERENCES cards (id)
                            );
                        """

# Database connection variable
conn = None


# This function creates a connection to the database
def create_connection():
    global conn
    try:
        conn = sqlite3.connect(DB_FILE_NAME)
    except sqlite3.Error as e:
        print(e)


# This function updates the card list in the database
def update_cards() -> str:
    try:
        assert isinstance(conn, sqlite3.Connection)
        c = conn.cursor()
        card_json = requests.get("https://royaleapi.github.io/cr-api-data/json/cards.json").json()
        for card in card_json:
            try:
                c.execute("""
                            INSERT INTO cards(id, name, elixir, type, rarity)
                            VALUES(?, ?, ?, ?, ?)
                          """,
                          (card["key"], card["name"], card["elixir"], card["type"], card["rarity"]))
            except sqlite3.Error as e:
                pass
        conn.commit()
        c.close()
        return "Updated card list...\t\t\t\t" + str(datetime.now())
    except Exception as e:
        print(e)
        return "Could not update card list...\t\t" + str(datetime.now())


# Create a table if it does not already exist
def create_table(table_creation_sql: str):
    if isinstance(conn, sqlite3.Connection):
        c = conn.cursor()
        c.execute(table_creation_sql)
        conn.commit()
        c.close()


# Loads a single RoyaleAPI webpage into the database
def load_deck(url: str):
    sql = """
        INSERT OR REPLACE INTO decks(id, card_1, card_2, card_3, card_4, card_5, card_6,
            card_7, card_8, rating, usage, win_rate, entry_date)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    try:
        assert isinstance(conn, sqlite3.Connection)
        c = conn.cursor()
        session = requests.Session()
        response = session.get(url, headers={"user-agent": "Mozilla/5.0"})
        html = lxml.html.fromstring(response.text)

        for element in html.cssselect(".ui.two.column.stackable.padded.grid"):
            links = list(element.iterlinks())
            deck_id = links[0][2][13:]
            cards = deck_id.split(",")
            stats = element.xpath("div/div/div/div/table/tbody/tr/*/text()")
            rating = int(stats[0].strip())
            usage = int(stats[5].strip().replace(',', ''))
            win_rate = float(stats[2].strip()[:-1])
            try:
                c.execute(sql, (deck_id, cards[0], cards[1], cards[2], cards[3], cards[4], cards[5], cards[6],
                                cards[7], rating, usage, win_rate, datetime.now(timezone.utc)))
            except Exception as e:
                print(e)
                pass

        conn.commit()
    except Exception as e:
        print(e)
        print("Could not load decks...\n")
        return


# Load the player's levels in for better war deck advice
def load_levels(tag: str) -> str:
    if len(tag) == 0:
        return "Player tag cannot be empty!"

    if tag[0] == "#":
        tag = tag[1:]
    tag = tag.upper()

    url = "https://proxy.royaleapi.dev/v1/players/%23" + tag
    player_info = requests.get(url, headers={"Authorization": "Bearer " + CR_API_TOKEN}).json()
    tag = "#" + tag

    if "reason" in player_info:
        return "Could not retrieve player info."
    else:
        if not isinstance(conn, sqlite3.Connection):
            return "Could not connect to database."
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO levels(id) VALUES(?)", (tag,))
        for card in player_info["cards"]:
            card_name = card["name"].lower().replace(" ", "_").replace(".", "").replace("-", "_")
            if c.execute("SELECT EXISTS(SELECT 1 FROM cards WHERE id='%s')" %
                         card_name.replace("_", "-")).fetchone()[0] == 0:
                print("Found unknown card %s. Please report to developer." % card_name)
            c.execute("UPDATE levels SET %s=? WHERE id=?" % card_name, (14 - card["maxLevel"] + card["level"], tag))
        conn.commit()
        c.close()
        return "Levels for player " + player_info["name"] + " successfully loaded."


# Create and update the levels table if necessary
# Columns use underscores instead of dashes due to SQL column naming rules
def update_levels_table():
    assert (isinstance(conn, sqlite3.Connection))
    sql_create_levels_table = "CREATE TABLE IF NOT EXISTS levels (\n\tid text PRIMARY KEY,\n\t"
    c = conn.cursor()
    for row in c.execute("SELECT * FROM cards"):
        sql_create_levels_table += row[0].replace("-", "_") + " integer,\n\t"
    sql_create_levels_table = sql_create_levels_table[:-3]
    sql_create_levels_table += "\n);"
    create_table(sql_create_levels_table)
    columns = [(row[1]) for row in c.execute("PRAGMA table_info(levels)").fetchall()]
    for row in c.execute("SELECT * FROM cards"):
        if row[0].replace("-", "_") not in columns:
            c.execute("ALTER TABLE levels ADD COLUMN %s integer" % row[0].replace("-", "_"))
    conn.commit()
    c.close()


# This function validates whether an inputted card list is valid
def validate_card_list(card_list: str) -> (bool, set):
    assert (isinstance(conn, sqlite3.Connection))
    c = conn.cursor()
    cards = card_list.strip().split(" ")

    if cards[0] == "":
        return True, set()

    is_valid = True
    for card in cards:
        if c.execute(f"SELECT * FROM cards WHERE id='{card}'").fetchone() is None:
            is_valid = False

    return is_valid, set(cards)


# This function computes the score of a deck, or how good it is
# Modifying how the score is computing will affect which decks get returned
def deck_score(decks, levels: dict, prev_score: int, used: set, prev_decks: [], max_idx: int, exclude_set: set):
    for cur_idx in range(max_idx + 1, len(decks)):
        deck = decks[cur_idx]
        score = deck[10] * deck[11]  # Initial score
        score *= 1 - (datetime.now(timezone.utc) - datetime.strptime(deck[12], "%Y-%m-%d %H:%M:%S.%f%z")).days * 0.02
        can_add = True  # Initial value of can_add
        levels_off_max = 0  # Number of levels off of having the war deck maxed

        for i in range(1, 9):
            if deck[i] in used or deck[i] in exclude_set:
                # If we already used a card, we can't use this deck
                can_add = False
                break

            # Get the card level, if it exists
            level = levels.get(deck[i])

            if level is None:
                # If the player doesn't have this card, we also can't use this deck
                can_add = False
                break
            else:
                levels_off_max += 14 - level
        if not can_add:
            score = -1000000000
        if score > 0:
            score *= pow(math.e, -0.2 * levels_off_max)

        new_decks = list(prev_decks)
        new_decks.append(deck[0])
        new_used = copy.deepcopy(used)
        for i in range(1, 9):
            new_used.add(deck[i])
        yield prev_score + score, new_used, new_decks, cur_idx


# This function gets the card levels of a deck, given the deck and the level dictionary
def get_deck_card_levels(deck: str, levels: dict) -> list:
    ret = []
    cards = deck.split(",")
    for card in cards:
        level = levels.get(card)
        if level is None:
            level = -1000
        ret.append(level)
    return ret


# This function computes the best war decks. It changes its output based on whether it is called from the bot file or
# the command-line file.
async def compute_war_decks(decks_to_return: int, pruning: int, variation: int, include_set: set, exclude_set: set,
                            decks_to_generate: int, decks: list, levels: dict, message: discord.Message | None):
    # Calculate the number of decks to generate in each iteration
    num_decks = 7 if pruning == 2 else 150

    # Display the initial message
    if message is None:
        print("Getting optimal decks for deck slot 1...")
    else:
        message = await message.edit("Getting optimal decks for deck slot 1...")

    # Get the most optimal first decks
    if decks_to_generate == 1:
        initial_decks = nlargest(len(decks), deck_score(decks, levels, 0, set(), [], -1, exclude_set))
    else:
        initial_decks = nlargest(num_decks, deck_score(decks, levels, 0, set(), [], -1, exclude_set))

    # Get the rest of the most optimal decks
    for i in range(2, decks_to_generate + 1):
        if message is None:
            print(f"Getting optimal decks for deck slot {i}...")
        else:
            await message.edit(f"Getting optimal decks for deck slot {i}...")

        new_decks = []
        for deck in alive_it(initial_decks):
            cur_decks = nlargest(num_decks, deck_score(decks, levels, deck[0], deck[1], deck[2], deck[3],
                                                       exclude_set))
            for cur_deck in cur_decks:
                if float(cur_deck[0]) > 0:
                    new_decks.append(cur_deck)
        initial_decks = new_decks
        if pruning == 1 and i < decks_to_generate:
            initial_decks = nlargest(num_decks, initial_decks)

    # Find the best decks
    if message is None:
        print("Getting best overall deck sets...")
    else:
        await message.edit("Getting best overall deck sets...")

    best_decks = []
    initial_decks = sorted(initial_decks, key=cmp_to_key(lambda deck1, deck2: float(deck2[0]) - float(deck1[0])))
    used_cards_sets = []
    for deck_obj in initial_decks:
        can_add = include_set.issubset(deck_obj[1])
        if variation == 1:
            for used_card_set in used_cards_sets:
                if len(deck_obj[1].intersection(used_card_set)) > 23:
                    can_add = False
                    break
        if can_add:
            best_decks.append(deck_obj)
            used_cards_sets.append(deck_obj[1])
        if len(best_decks) == decks_to_return:
            break

    return best_decks
