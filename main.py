# Package Imports

from alive_progress import alive_bar, alive_it
import config  # Contains cr_api_token, the private API token
from datetime import datetime, timezone
from functools import cmp_to_key
from heapq import nlargest
import lxml.html
import lxml.cssselect
import math
import requests
import sqlite3


# Create a connection to the database. We terminate the program if the
# connection cannot be made.
def create_connection(db_file_name: str):
    try:
        return sqlite3.connect(db_file_name)
    except sqlite3.Error:
        print("Could not connect to database, terminating program...")
        quit()


# Create the cards table if it does not already exist
def create_table(conn: sqlite3.Connection, create_table: str):
    if conn is not None:
        c = conn.cursor()
        c.execute(create_table)
        conn.commit()


# Fill in the cards database with the cards from the game
# We check to make sure that we only add cards that don't already exist
def populate_cards(conn: sqlite3.Connection):
    url = "https://royaleapi.github.io/cr-api-data/json/cards.json"
    sql = """
        INSERT INTO cards(id, name, elixir, type, rarity)
        VALUES(?, ?, ?, ?, ?)
    """

    try:
        c = conn.cursor()
        card_json = requests.get(url).json()
        for card in card_json:
            try:
                c.execute(sql, (card["key"], card["name"], card["elixir"], card["type"], card["rarity"]))
            except Exception as e:
                pass
        conn.commit()
    except Exception as e:
        print(e)
        print("Could not update card list...")


# Create and update the levels table if necessary
# Columns use underscores instead of dashes due to SQL column naming rules
def update_levels_table(conn: sqlite3.Connection):
    sql_create_levels_table = "CREATE TABLE IF NOT EXISTS levels (\n\tid text PRIMARY KEY,\n\t"
    c = conn.cursor()
    for row in c.execute("SELECT * FROM cards"):
        sql_create_levels_table += row[0].replace("-", "_") + " integer,\n\t"
    sql_create_levels_table = sql_create_levels_table[:-3]
    sql_create_levels_table += "\n);"
    create_table(conn, sql_create_levels_table)
    columns = [(row[1]) for row in c.execute("PRAGMA table_info(levels)").fetchall()]
    for row in c.execute("SELECT * FROM cards"):
        if row[0].replace("-", "_") not in columns:
            c.execute("ALTER TABLE levels ADD COLUMN %s integer" % row[0].replace("-", "_"))
    conn.commit()


# Load the player's levels in for better war deck advice
def load_levels(conn: sqlite3.Connection, cr_api_token: str, tag: str):
    if len(tag) == 0:
        print("Player tag cannot be empty!")
        return

    if tag[0] == "#":
        tag = tag[1:]
    tag = tag.upper()

    url = "https://proxy.royaleapi.dev/v1/players/%23" + tag
    player_info = requests.get(url, headers={"Authorization": "Bearer " + cr_api_token}).json()
    tag = "#" + tag

    if "reason" in player_info:
        print("Could not load player info")
    else:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO levels(id) VALUES(?)", (tag,))
        for card in player_info["cards"]:
            card_name = card["name"].lower().replace(" ", "_").replace(".", "").replace("-", "_")
            if c.execute("SELECT EXISTS(SELECT 1 FROM cards WHERE id='%s')" % card_name.replace("_", "-")).fetchone()[
                0] == 0:
                print("Found unknown card %s. Please report to developer." % card_name)
            c.execute("UPDATE levels SET %s=? WHERE id=?" % card_name, (14 - card["maxLevel"] + card["level"], tag))
        print("Levels for player " + player_info["name"] + " successfully loaded")
        conn.commit()


# Loads a single RoyaleAPI webpage into the database by scraping
def load_deck(conn: sqlite3.Connection, url: str):
    sql = """
        INSERT OR REPLACE INTO decks(id, card_1, card_2, card_3, card_4, card_5, card_6,
            card_7, card_8, rating, usage, win_rate, entry_date)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    try:
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


# Loads more decks into the database
def load_decks(conn: sqlite3.Connection):
    option = -1
    repeat = False
    while option != "1" and option != "2" and option != "3" and option != "4":
        if repeat:
            print("Invalid option, please select again")
        else:
            print("Would you like to:")
        print("(1) Load decks without a card inclusion")
        print("(2) Load decks with a specified card inclusion")
        print("(3) Load decks with all card inclusions (this will take a while)")
        print("(4) Exit the deck loader")
        option = input().strip()
        repeat = True

    try:
        match option:
            case "1":
                load_deck(conn, "https://royaleapi.com/decks/popular?type=GC&time=7d&size=30")
                print("Decks successfully loaded!\n")
                load_decks(conn)
            case "2":
                card = input("Enter the card you would like to include: ").lower().replace(" ", "-")
                c = conn.cursor()
                if c.execute("SELECT 1 FROM cards WHERE id='" + card + "'").fetchone():
                    load_deck(conn, "https://royaleapi.com/decks/popular?type=GC&time=7d&size=30&inc=" + card)
                    print("Decks successfully loaded!\n")
                    load_decks(conn)
                else:
                    print("Invalid card, please try again...\n")
                    load_decks(conn)
            case "3":
                c = conn.cursor()
                num_cards = len(c.execute("SELECT * FROM cards").fetchall())
                with alive_bar(num_cards) as bar:
                    for row in c.execute("SELECT * FROM cards"):
                        load_deck(conn, "https://royaleapi.com/decks/popular?type=GC&time=7d&size=30&inc=" + row[0])
                        bar()
            case "4":
                print("Returning to main screen...\n")
                return
            case _:
                print("Unknown error, returning to main screen...\n")
                return
    except Exception as e:
        print("An unknown error occurred. Returning to the main screen...")


# This function computes the score of a deck, or how good it is
# Modifying how the score is computing will affect which decks get returned
def deck_score(c: sqlite3.Cursor, decks, tag: str, prev_score: int, used: [], prev_decks: [], max_idx: int):
    for cur_idx in range(max_idx + 1, len(decks)):
        deck = decks[cur_idx]
        score = deck[10] * deck[11]  # Initial score
        score *= 1 - (datetime.now(timezone.utc) - datetime.strptime(deck[12], "%Y-%m-%d %H:%M:%S.%f%z")).days * 0.02
        used_set = set(used)  # The set version of the currently used cards
        can_add = True  # Initial value of can_add
        levels_off_max = 0  # Number of levels off of having the war deck maxed
        for i in range(1, 9):
            if deck[i] in used_set:
                # If we already used a card, we can't use this deck
                can_add = False
            level = c.execute("SELECT " + deck[i].replace('-', '_') + " FROM levels WHERE id='" + tag + "'").fetchone()
            if level is None:
                # If the player doesn't have this card, we also can't use this deck
                can_add = False
            else:
                levels_off_max += 14 - level[0]
        if not can_add:
            score = -100000
        if score > 0:
            score *= pow(math.e, -0.2 * levels_off_max)

        new_decks = list(prev_decks)
        new_decks.append(deck[0])
        new_used = list(used)
        for i in range(1, 9):
            new_used.append(deck[i])
        yield prev_score + score, new_used, new_decks, cur_idx


# This function actually performs the generation
def generate(conn: sqlite3.Connection, tag: str, decks_to_return: int, pruning: int, variation: int):
    num_decks = 7 if pruning == 2 else 80

    # Get all decks from the database
    c = conn.cursor()
    decks = c.execute("SELECT * FROM decks").fetchall()

    # Get the most optimal first decks
    print("Getting optimal first decks...")
    deck_1 = nlargest(num_decks, deck_score(c, decks, tag, 0, [], [], -1))

    # Get the most optimal second decks
    print("Getting optimal second decks...")
    deck_2 = []
    for deck in alive_it(deck_1):
        cur_decks = nlargest(num_decks, deck_score(c, decks, tag, deck[0], deck[1], deck[2], deck[3]))
        for cur_deck in cur_decks:
            if float(cur_deck[0]) > 0:
                deck_2.append(cur_deck)
    if pruning == 1:
        deck_2 = nlargest(num_decks, deck_2)

    # Get the most optimal third decks
    print("Getting optimal third decks...")
    deck_3 = []
    for deck in alive_it(deck_2):
        cur_decks = nlargest(num_decks, deck_score(c, decks, tag, deck[0], deck[1], deck[2], deck[3]))
        for cur_deck in cur_decks:
            if float(cur_deck[0] > 0):
                deck_3.append(cur_deck)
    if pruning == 1:
        deck_3 = nlargest(num_decks, deck_3)

    # Get the most optimal fourth decks
    print("Getting optimal fourth decks...")
    deck_4 = []
    for deck in alive_it(deck_3):
        cur_decks = nlargest(num_decks, deck_score(c, decks, tag, deck[0], deck[1], deck[2], deck[3]))
        for cur_deck in cur_decks:
            if float(cur_deck[0] > 0):
                deck_4.append(cur_deck)
    if pruning == 1:
        deck_4 = nlargest(num_decks, deck_4)

    if variation == 1:
        deck_4 = sorted(deck_4, key=cmp_to_key(lambda deck1, deck2: float(deck2[0]) - float(deck1[0])))
        printed = 0
        used_cards_sets = []
        for deck_obj in deck_4:
            cur_card_set = set(deck_obj[1])
            can_add = True
            for used_card_set in used_cards_sets:
                if len(cur_card_set.intersection(used_card_set)) > 23:
                    can_add = False
                    break
            if can_add:
                print("Deck %d with a score of %s" % (printed + 1, deck_obj[0]))
                for deck in deck_obj[2]:
                    print("https://royaleapi.com/decks/stats/" + deck)
                print("--------------------------------------")
                printed += 1
                used_cards_sets.append(cur_card_set)
            if printed == decks_to_return:
                print()
                return
        print()
    else:
        deck_4 = nlargest(decks_to_return, deck_4)
        # Print out the decks
        for idx, decks in enumerate(deck_4):
            if float(decks[0]) > 0:
                print("Deck %d with a score of %s" % (idx + 1, decks[0]))
                for deck in decks[2]:
                    print("https://royaleapi.com/decks/stats/" + deck)
                print("--------------------------------------")
        print()


# Generates optimal war decks
def generate_war_decks(conn: sqlite3.Connection, tag: str):
    c = conn.cursor()
    if tag[0] != '#':
        tag = '#' + tag
    tag = tag.upper()
    levels = c.execute("SELECT * FROM levels WHERE id='" + tag + "'").fetchone()

    if not levels:
        print("Player tag not loaded, returning to main screen...\n")
        return

    decks_to_return = -1
    repeat = False
    while not isinstance(decks_to_return, int) or decks_to_return < 0 or decks_to_return > 20:
        if repeat:
            print("Invalid entry, please enter again")
        decks_to_return = input("Enter the number of decks to return (between 1 and 20 inclusive) or press q to quit: ")
        if decks_to_return == "q":
            print()
            return
        try:
            decks_to_return = int(decks_to_return)
        except ValueError as e:
            pass
        repeat = True
    decks_to_return = int(decks_to_return)

    repeat = False
    pruning = -1
    while pruning != "1" and pruning != "2" and pruning != "3":
        if repeat:
            print("Invalid entry, please enter again")
        print("Do you want to use iterative pruning?")
        print("(1) Yes")
        print("(2) No")
        print("(3) Quit")
        pruning = input()
        repeat = True
    pruning = int(pruning)
    if pruning == 3:
        return

    repeat = False
    variation = -1
    while variation != "1" and variation != "2" and variation != "3":
        if repeat:
            print("Invalid entry, please enter again")
        print("Do you want to force variation in the returned decks (at the expense of optimality)?")
        print("(1) Yes")
        print("(2) No")
        print("(3) Quit")
        variation = input()
        repeat = True
    variation = int(variation)
    if variation == 3:
        return

    generate(conn, tag, decks_to_return, pruning, variation)


# The driver code for the program
def main():
    # Necessary variables
    db_file_name = "database.db"
    cr_api_token = config.cr_api_token
    sql_create_cards_table = """
        CREATE TABLE IF NOT EXISTS cards (
            id text PRIMARY KEY,
            name text NOT NULL,
            elixir integer NOT NULL,
            type text NOT NULL,
            rarity text NOT NULL
        );
    """
    sql_create_decks_table = """
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

    levels = None

    # Create the connection
    conn = create_connection(db_file_name)

    # Create the cards table if it doesn't already exist
    create_table(conn, sql_create_cards_table)

    # Fill in the cards table with the cards from Clash Royale
    populate_cards(conn)

    # Create the decks table if it doesn't already exist
    create_table(conn, sql_create_decks_table)

    # Create and update the levels table if necessary
    update_levels_table(conn)

    # Print the disclaimer
    print("This content is not affiliated with, endorsed, sponsored, or specifically approved by Supercell and "
          "Supercell is not responsible for it.\nFor more information see Supercell’s Fan Content "
          "Policy:\nhttps://supercell.com/en/fan-content-policy/en/\n")

    # Start the menu
    option = "0"

    while option != "4":
        print("Welcome to the Clash Royale War Deck Builder! What would you like to do today?")
        print("(1) Load player info via player tag")
        print("(2) Load more decks into the database")
        print("(3) Generate war decks")
        print("(4) Exit")
        option = input()

        match option:
            case "1":
                tag = input("Please input your player tag: ")
                load_levels(conn, cr_api_token, tag)
            case "2":
                load_decks(conn)
            case "3":
                tag = input("Please input your player tag: ")
                generate_war_decks(conn, tag)
            case "4":
                print("Exiting program...")
                conn.close()
                quit()
            case _:
                print("Unknown error, terminating program...")
                conn.close()
                quit()

    # Final close for safety purposes
    conn.close()


# Run the program
if __name__ == '__main__':
    main()
