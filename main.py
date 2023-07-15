# Package Imports

from alive_progress import alive_bar
import asyncio
import statistics
import sqlite3
import utilities


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
                utilities.load_deck("https://royaleapi.com/decks/popular?type=GC&time=7d&size=20")
                print("Decks successfully loaded!\n")
                load_decks(conn)
            case "2":
                card = input("Enter the card you would like to include: ").lower().replace(" ", "-")
                c = conn.cursor()
                if c.execute("SELECT 1 FROM cards WHERE id='" + card + "'").fetchone():
                    utilities.load_deck("https://royaleapi.com/decks/popular?type=GC&time=7d&size=20&inc=" + card)
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
                        utilities.load_deck("https://royaleapi.com/decks/popular?type=GC&time=7d&size=20&inc=" + row[0])
                        bar()
            case "4":
                print("Returning to main screen...\n")
                return
            case _:
                print("Unknown error, returning to main screen...\n")
                return
    except Exception as e:
        print("An unknown error occurred. Returning to the main screen...")


# This function actually performs the generation
def generate(tag: str, decks_to_return: int, pruning: int, variation: int, include_set: set,
             exclude_set: set, decks_to_generate: int):
    # Get all decks from the database
    c = utilities.conn.cursor()
    decks = c.execute("SELECT * FROM decks").fetchall()

    # Get the levels from the database and convert them to a dictionary
    levels_obj = c.execute("SELECT * FROM levels WHERE id='" + tag + "'").fetchone()
    levels_columns = [(row[1]) for row in c.execute("PRAGMA table_info(levels)").fetchall()]
    levels = {}
    for i in range(1, len(levels_obj)):
        levels[levels_columns[i].replace("_", "-")] = levels_obj[i]

    # Get the best deck sets
    best_decks = asyncio.run(utilities.compute_war_decks(decks_to_return, pruning, variation, include_set, exclude_set,
                                                         decks_to_generate, decks, levels, None))

    # Print out the best decks
    for idx, cur_decks in enumerate(best_decks):
        if float(cur_decks[0]) > 0:
            print(f"Deck set {idx + 1} with a score of {cur_decks[0]} and level utilization rate "
                  f"{round(utilities.level_utilization(cur_decks[2], levels), 1)}%")

            for deck in cur_decks[2]:
                print("https://royaleapi.com/decks/stats/%s [AVG LEVEL: %.3f]" %
                      (deck, statistics.mean(utilities.get_deck_card_levels(deck, levels))))
            print("--------------------------------------")

    # Fallback if no decks were found
    if len(best_decks) == 0:
        print("Could not generate decks matching required criteria...")

    print()


# Generates optimal war decks
def generate_war_decks(tag: str):
    c = utilities.conn.cursor()
    if tag[0] != '#':
        tag = '#' + tag
    tag = tag.upper()
    levels = c.execute("SELECT * FROM levels WHERE id='" + tag + "'").fetchone()

    if not levels:
        print("Player tag not loaded, returning to main screen...\n")
        return

    decks_to_return = utilities.get_integer(1, 20, "Enter the number of decks to return (between 1 and 20 inclusive) "
                                                   "or press q to quit: ", "q")
    if decks_to_return is None:
        return

    pruning = utilities.get_integer(1, 3, "Do you want to use iterative pruning?\n(1) Yes\n(2) No\n(3) Quit\n",
                                    "3")
    if pruning is None:
        return

    variation = utilities.get_integer(1, 3, "Do you want to force variation in the returned decks (at the expense of "
                                            "optimality)?\n(1) Yes\n(2) No\n(3) Quit\n", "3")
    if variation is None:
        return

    repeat = False
    include_set = set()
    while True:
        if repeat:
            print("Invalid entry, please enter valid cards")

        print("Enter the cards you wish to include in the war decks, space-separated and with dashes for spaces. As "
              "examples, to include the cards Three Musketeers, Archers, and Mini P.E.K.K.A, type [three-musketeers "
              "archers mini-pekka]. Enter nothing to apply no card inclusions. Alternatively, enter (q) to quit and "
              "return to the main screen.")
        card_list = input().strip()

        if card_list == "q":
            print("Exiting war deck builder...\n")
            return

        validation = utilities.validate_card_list(card_list)

        repeat = True
        if validation[0]:
            include_set = validation[1]
            break

    repeat = False
    exclude_set = set()
    while True:
        if repeat:
            print("Invalid entry, please enter valid cards")

        print("Enter the cards you wish to exclude in the war decks, space-separated and with dashes for spaces. As "
              "examples, to exclude the cards Three Musketeers, Archers, and Mini P.E.K.K.A, type [three-musketeers "
              "archers mini-pekka]. Enter nothing to apply no card exclusions. Alternatively, enter (q) to quit and "
              "return to the main screen.")
        card_list = input().strip()

        if card_list == "q":
            print("Exiting war deck builder...\n")
            return

        validation = utilities.validate_card_list(card_list)

        repeat = True
        if validation[0]:
            exclude_set = validation[1]
            break

    decks_to_generate = utilities.get_integer(1, 4, "Enter the number of decks to generate (between 1 and 4 "
                                                    "inclusive) or press q to quit: ", "q")
    if decks_to_generate is None:
        return

    generate(tag, decks_to_return, pruning, variation, include_set, exclude_set, decks_to_generate)


# The driver code for the program
def main():
    # Create the connection and ensure that it is valid
    utilities.create_connection()
    if not isinstance(utilities.conn, sqlite3.Connection):
        print("Failed to connect to database, terminating program...")
        quit()

    # Print the disclaimer
    print("This content is not affiliated with, endorsed, sponsored, or specifically approved by Supercell and "
          "Supercell is not responsible for it.\nFor more information see Supercell’s Fan Content "
          "Policy:\nhttps://supercell.com/en/fan-content-policy/en/\n")

    # Create the cards table if it doesn't already exist
    utilities.create_table(utilities.SQL_CREATE_CARDS_TABLE)

    # Fill in the cards table with the cards from Clash Royale
    utilities.update_cards()

    # Create the decks table if it doesn't already exist
    utilities.create_table(utilities.SQL_CREATE_DECKS_TABLE)

    # Create and update the levels table if necessary
    utilities.update_levels_table()

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
                print(utilities.load_levels(tag), "\n")
            case "2":
                load_decks(utilities.conn)
            case "3":
                tag = input("Please input your player tag: ")
                generate_war_decks(tag)
            case "4":
                print("Exiting program...")
                utilities.conn.close()
                quit()
            case _:
                print("Unknown error, terminating program...")
                utilities.conn.close()
                quit()

    # Final close for safety purposes
    utilities.conn.close()


# Run the program
if __name__ == '__main__':
    main()
