# Import Statements
from datetime import datetime, timezone
import discord
from discord import option
from discord.ext import pages
from dotenv import load_dotenv
from functools import cmp_to_key
from heapq import nlargest
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


# Printing a message when the bot has been loaded
@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")
    try:
        global conn
        conn = sqlite3.connect(db_file_name)
    except sqlite3.Error:
        print("Could not connect to database, terminating program...")
        quit()


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
        await ctx.respond("Invalid player tag!")
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
async def generate_war_decks(ctx: discord.ApplicationContext, tag: str, decks_to_return: int, pruning: str, variation: str):
    try:
        c = conn.cursor()
        if tag[0] != '#':
            tag = '#' + tag
        tag = tag.upper()
        levels = c.execute("SELECT * FROM levels WHERE id='" + tag + "'").fetchone()

        if not levels:
            await ctx.respond("Player tag not loaded, war deck generation failed.")
            return

        await ctx.defer()  # Our code takes longer to run, so defer the final message
        pruning = 7 if pruning == "Yes" else 80
        variation = 1 if variation == "Yes" else 2

        num_decks = 2 if pruning == 2 else 5

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


# Running the bot
bot.run(DISCORD_BOT_TOKEN)  # run the bot with the token
