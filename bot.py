# Import Statements
from alive_progress import alive_bar
from datetime import datetime, timezone
import discord
from discord import option
from discord.ext import pages, tasks
from dotenv import load_dotenv
from functools import cmp_to_key
from heapq import nlargest
import lxml.html
import lxml.cssselect
import math
import os
import requests
import sqlite3

# Loading auth tokens
load_dotenv()
CR_API_TOKEN = os.getenv("CR_API_TOKEN")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Initializing the bot
bot = discord.Bot()

# Initializing the sqlite3 database connection object
# The program will terminate if a connection cannot be established to the database
conn = None

# Initializing other miscellaneous variables
db_file_name = "database.db"


# Create a table if it does not already exist
def create_table(table_creation_sql: str):
    if conn is not None:
        c = conn.cursor()
        c.execute(table_creation_sql)
        conn.commit()


# Loads a single RoyaleAPI webpage into the database by scraping
def load_deck(url: str):
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


# Computes the score for generated war decks
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
            score = -1000000000
        if score > 0:
            score *= pow(math.e, -0.2 * levels_off_max)

        new_decks = list(prev_decks)
        new_decks.append(deck[0])
        new_used = list(used)
        for i in range(1, 9):
            new_used.append(deck[i])
        yield prev_score + score, new_used, new_decks, cur_idx


@bot.slash_command(name="load_levels", description="Load a player's levels into the database")
@option("tag", description="Your player tag")
async def load_levels(ctx, tag: str):
    if len(tag) == 0:
        await ctx.respond("Invalid player tag!")
        return

    if tag[0] == "#":
        tag = tag[1:]
    tag = tag.upper()

    url = "https://proxy.royaleapi.dev/v1/players/%23" + tag
    player_info = requests.get(url, headers={"Authorization": "Bearer " + CR_API_TOKEN}).json()
    tag = "#" + tag

    if "reason" in player_info:
        await ctx.respond("Invalid player tag!", ephemeral=True)
        return
    else:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO levels(id) VALUES(?)", (tag,))
        for card in player_info["cards"]:
            card_name = card["name"].lower().replace(" ", "_").replace(".", "").replace("-", "_")
            if c.execute("SELECT EXISTS(SELECT 1 FROM cards WHERE id='%s')" % card_name.replace("_", "-")).fetchone()[
                0] == 0:
                print("Found unknown card %s. Please report to developer." % card_name)
            c.execute("UPDATE levels SET %s=? WHERE id=?" % card_name, (14 - card["maxLevel"] + card["level"], tag))
        conn.commit()
        await ctx.respond(f"Levels for player " + player_info["name"] + " successfully loaded")


@bot.slash_command(name="generate_war_decks", description="Generate optimal war decks for a player")
@option("tag", description="Your player tag")
@option("decks_to_return", description="The number of decks to return (between 1 and 10)",
        choices=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
@option("pruning", description="Whether to prune the search tree, select 1 for yes and 2 for no",
        choices=["Yes", "No"])
@option("variation", description="Whether to force variation in the decks, select 1 for yes and 2 for no",
        choices=["Yes", "No"])
async def generate_war_decks(ctx: discord.ApplicationContext, tag: str, decks_to_return: int, pruning: str,
                             variation: str):
    try:
        c = conn.cursor()
        if tag[0] != '#':
            tag = '#' + tag
        tag = tag.upper()
        levels = c.execute("SELECT * FROM levels WHERE id='" + tag + "'").fetchone()

        if not levels:
            await ctx.respond("Player tag not loaded, war deck generation failed.", ephemeral=True)
            return

        await ctx.defer()  # Our code takes longer to run, so defer the final message
        pruning = 1 if pruning == "Yes" else 2
        variation = 1 if variation == "Yes" else 2

        num_decks = 6 if pruning == 2 else 70

        # Get all decks from the database
        c = conn.cursor()
        decks = c.execute("SELECT * FROM decks").fetchall()

        # Get the most optimal first decks
        message = await ctx.send("Computing optimal first decks...")
        deck_1 = nlargest(num_decks, deck_score(c, decks, tag, 0, [], [], -1))

        # Get the most optimal second decks
        await message.edit("Computing optimal second decks...")
        deck_2 = []
        for deck in deck_1:
            cur_decks = nlargest(num_decks, deck_score(c, decks, tag, deck[0], deck[1], deck[2], deck[3]))
            for cur_deck in cur_decks:
                if float(cur_deck[0]) > 0:
                    deck_2.append(cur_deck)
        if pruning == 1:
            deck_2 = nlargest(num_decks, deck_2)

        # Get the most optimal third decks
        await message.edit("Computing optimal third decks...")
        deck_3 = []
        for deck in deck_2:
            cur_decks = nlargest(num_decks, deck_score(c, decks, tag, deck[0], deck[1], deck[2], deck[3]))
            for cur_deck in cur_decks:
                if float(cur_deck[0] > 0):
                    deck_3.append(cur_deck)
        if pruning == 1:
            deck_3 = nlargest(num_decks, deck_3)

        # Get the most optimal fourth decks
        await message.edit("Computing optimal fourth decks...")
        deck_4 = []
        for deck in deck_3:
            cur_decks = nlargest(num_decks, deck_score(c, decks, tag, deck[0], deck[1], deck[2], deck[3]))
            for cur_deck in cur_decks:
                if float(cur_deck[0] > 0):
                    deck_4.append(cur_deck)
        if pruning == 1:
            deck_4 = nlargest(num_decks, deck_4)

        # Find the best decks
        best_decks = []

        await message.edit("Computing best overall deck sets...")
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
                    to_add = ["This war deck combination has a score of %d. Check the decks out below." % deck_obj[0]]
                    for deck in deck_obj[2]:
                        to_add.append(deck)
                    best_decks.append(to_add)
                    printed += 1
                    used_cards_sets.append(cur_card_set)
                if printed == decks_to_return:
                    break
        else:
            deck_4 = nlargest(decks_to_return, deck_4)
            for idx, decks in enumerate(deck_4):
                if float(decks[0]) > 0:
                    to_add = ["This war deck combination has a score of %d. Check the decks out below." % decks[0]]
                    for deck in decks[2]:
                        to_add.append(deck)
                    best_decks.append(to_add)

        # Return the best decks
        ret = []
        idx = 1
        for deck in best_decks:
            cur = []
            for i in range(1, 5):
                if i == 1:
                    embed = discord.Embed(
                        title=f"War Deck Set %d" % idx,
                        description=deck[0],
                        color=discord.Colour.dark_magenta(),
                        url="https://royaleapi.com/decks/duel-search"
                    )
                    for j in range(1, 5):
                        embed.add_field(name=f"Deck %d" % j, value="https://royaleapi.com/decks/stats/" + deck[j],
                                        inline=False)
                    embed.set_footer(text="Generated with ❤️ by TheBest")
                    embed.set_author(name="CR War Deck Builder")
                else:
                    embed = discord.Embed(
                        url="https://royaleapi.com/decks/duel-search"
                    )
                embed.set_image(
                    url=f"https://media.royaleapi.com/deck/{datetime.today().strftime('%Y-%m-%d')}/{deck[i]}.jpg")

                cur.append(embed)
            idx += 1
            ret.append(cur)

        paginator = pages.Paginator(
            pages=ret, loop_pages=True
        )

        await message.delete()
        await paginator.respond(ctx.interaction, ephemeral=False)
    except Exception as e:
        print(e)
        await message.delete()
        await ctx.send_followup("Error occurred, please try again later")


# Get the latest meta decks every 24 hours
# Also deletes old decks
@tasks.loop(hours=24)
async def update_decks():
    print("Updating deck list...\t\t\t\t", datetime.now())
    c = conn.cursor()
    num_cards = len(c.execute("SELECT * FROM cards").fetchall())
    '''with alive_bar(num_cards) as bar:
        for row in c.execute("SELECT * FROM cards"):
            load_deck("https://royaleapi.com/decks/popular?type=GC&time=7d&size=20&inc=" + row[0])
            bar()'''
    c.execute("DELETE FROM decks WHERE entry_date < date('now', '-60 day')")  # Delete decks older than 60 days
    conn.commit()
    print("Decks updated...\t\t\t\t", datetime.now())


# Get the latest card list every 24 hours
# This ensures that any newly released card is in the database quickly
@tasks.loop(hours=24)
async def update_cards():
    print("Updating card list...\t\t\t\t", datetime.now())
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


@tasks.loop(hours=24)
async def update_levels():
    print("Updating levels...\t\t\t\t", datetime.now())
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


# We delete all user levels every thirty days to avoid storing inactive users
@tasks.loop(hours=720)
async def delete_levels():
    print("Deleting levels...\t\t\t\t", datetime.now())
    c = conn.cursor()
    c.execute("DELETE FROM levels")
    conn.commit()


# Printing a message when the bot has been loaded
@bot.event
async def on_ready():
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
    print(f"{bot.user} is ready and online!\n")
    try:
        # Initialize the database connection
        global conn
        conn = sqlite3.connect(db_file_name)

        # Create the cards table if it doesn't already exist
        create_table(sql_create_cards_table)

        # Create the decks table if it doesn't already exist
        create_table(sql_create_decks_table)

        # Start tasks if they aren't in progress
        if not update_decks.is_running():
            update_decks.start()
        if not update_cards.is_running():
            update_cards.start()
        if not update_levels.is_running():
            update_levels.start()
        if not delete_levels.is_running():
            delete_levels.start()

    except Exception as e:
        print(e)
        quit()


# Running the bot
bot.run(DISCORD_BOT_TOKEN)  # run the bot with the token
