# Package Imports
import datetime
import lxml.html
import lxml.cssselect
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


# Load the player's levels in for better war deck advice
def load_levels(cr_api_token: str, tag: str):
    if len(tag) == 0:
        print("Player tag cannot be empty!")
        return;

    if tag[0] == "#":
        tag = tag[1:]

    url = "https://proxy.royaleapi.dev/v1/players/%23" + tag
    player_info = requests.get(url, headers={"Authorization": "Bearer " + cr_api_token}).json()

    if "reason" in player_info:
        print("Could not load player info")
    else:
        print("Levels for player " + player_info["name"] + " successfully loaded")
        return player_info["cards"]


# Loads a single RoyaleAPI webpage into the database by scraping
def load_deck(conn: sqlite3.Connection, url:str):
    sql = """
        INSERT OR REPLACE INTO decks(id, card_1, card_2, card_3, card_4, card_5, card_6,
            card_7, card_8, rating, use_rate, win_rate)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            use_rate = float(stats[1].strip()[:-1])
            win_rate = float(stats[2].strip()[:-1])
            try:
                c.execute(sql, (deck_id, cards[0], cards[1], cards[2], cards[3], cards[4], cards[5], cards[6],
                          cards[7], rating, use_rate, win_rate))
            except Exception as e:
                pass
            conn.commit()
    except Exception as e:
        print(e)
        print("Could not load decks...")
        return


# Loads more decks into the database
def load_decks(conn: sqlite3.Connection):
    print("For consistency purposes, this program only pulls data from Grand Challenges in the last seven days")
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

    match option:
        case "1":
            print("Case 1")
            load_deck(conn, "https://royaleapi.com/decks/popular?type=GC&time=7d&size=10")
        case "2":
            print("Case 2")
        case "3":
            print("Case 3")
        case "4":
            print("Case 4")
            return
        case _:
            print("Unknown error, returning to main screen")
            return


# The driver code for the program
def main():
    # Necessary variables
    db_file_name = "database.db"
    cr_api_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiIsImtpZCI6IjI4YTMxOGY3LTAwMDAtYTFlYi03ZmExLTJjNzQzM2M2Y2NhNSJ9.eyJpc3MiOiJzdXBlcmNlbGwiLCJhdWQiOiJzdXBlcmNlbGw6Z2FtZWFwaSIsImp0aSI6IjE1YjJlODJjLWVjOGEtNDljNy05MzViLWMwMzFhNGZmNTk1NiIsImlhdCI6MTY3NzkwMDE1Miwic3ViIjoiZGV2ZWxvcGVyLzZmMDliMjM1LWViMDUtMzhjOS04ZTEyLTMxYjViMjJkM2VkNCIsInNjb3BlcyI6WyJyb3lhbGUiXSwibGltaXRzIjpbeyJ0aWVyIjoiZGV2ZWxvcGVyL3NpbHZlciIsInR5cGUiOiJ0aHJvdHRsaW5nIn0seyJjaWRycyI6WyI0NS43OS4yMTguNzkiLCIxMjguMjExLjI1Mi4xNDAiXSwidHlwZSI6ImNsaWVudCJ9XX0.cSUEksrJZF5MZDhaFDFrnioJtx_Co3tKajRHr_4tzb3aGUP6pqbS_ktXI7c1id62yxEFRgq63odXKb-OGgc11A"
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
            use_rate DECIMAL(4,1) NOT NULL,
            win_rate DECIMAL(4,1) NOT NULL,
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
                levels = load_levels(cr_api_token, tag)
                print(levels)
            case "2":
                load_decks(conn)
            case "3":
                print("Option 3 was selected")
            case "4":
                print("Option 4 was selected")
            case _:
                print("Unknown error, terminating program...")
                conn.close()
                quit()

    conn.close()


# Run the program
if __name__ == '__main__':
    main()
