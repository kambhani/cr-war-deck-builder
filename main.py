# Package Imports
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


# The driver code for the program
def main():
    db_file_name = "database.db"
    sql_create_cards_table = """
            CREATE TABLE IF NOT EXISTS cards (
                id text PRIMARY KEY,
                name text NOT NULL,
                elixir integer NOT NULL,
                type text NOT NULL,
                rarity text NOT NULL
        ); """

    # Create the connection
    conn = create_connection(db_file_name)

    # Create the cards table if it doesn't already exist
    create_table(conn, sql_create_cards_table)

    # Fill in the cards table with the cards from Clash Royale
    populate_cards(conn)

    conn.close()


# Run the program
if __name__ == '__main__':
    main()
