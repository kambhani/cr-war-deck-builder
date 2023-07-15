# Import Statements
from alive_progress import alive_bar
from datetime import datetime
import discord
from discord import option
from discord.ext import pages, tasks
import lxml.html
import lxml.cssselect
import os
import requests
import statistics
import sys
import utilities

# Initializing the bot
bot = discord.Bot()

# Create a table if it does not already exist
def create_table(table_creation_sql: str):
    if utilities.conn is not None:
        c = utilities.conn.cursor()
        c.execute(table_creation_sql)
        utilities.conn.commit()


def load_levels(tag: str):
    if len(tag) == 0:
        return None

    if tag[0] == "#":
        tag = tag[1:]
    tag = tag.upper()

    url = "https://proxy.royaleapi.dev/v1/players/%23" + tag
    player_info = requests.get(url, headers={"Authorization": "Bearer " + utilities.CR_API_TOKEN}).json()

    if "reason" in player_info:
        return None

    return player_info["cards"]


@bot.slash_command(name="generate_war_decks", description="Generate optimal war decks for a player")
@option("tag", description="Your player tag")
@option("decks_to_return", description="The number of decks to return (between 1 and 10)",
        choices=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
@option("pruning", description="Whether to prune the search tree, select 1 for yes and 2 for no",
        choices=["Yes", "No"])
@option("variation", description="Whether to force variation in the decks, select 1 for yes and 2 for no",
        choices=["Yes", "No"])
@option("include_cards", description="The cards to include in the war decks")
@option("exclude_cards", description="The cards to exclude in the war decks")
@option("decks_to_generate", description="The number of decks to generate (between 1 and 4)",
        choices=[1, 2, 3, 4])
async def generate_war_decks(ctx: discord.ApplicationContext, tag: str, decks_to_return: int = 5, pruning: str = "Yes",
                             variation: str = "No", include_cards: str = "", exclude_cards: str = "",
                             decks_to_generate: int = 4):
    try:
        # Adjust the inputted tag so it fits the API's required form
        if tag[0] != '#':
            tag = '#' + tag
        tag = tag.upper()

        # Load the player tag and return an error if something goes wrong
        player_info = load_levels(tag)
        if player_info is None:
            await ctx.respond("Error loading player levels...", ephemeral=True)
            return

        # Ensure that the include and exclude card lists are valid
        include_set = utilities.validate_card_list(include_cards)
        exclude_set = utilities.validate_card_list(exclude_cards)
        if not include_set[0] or not exclude_set[0]:
            await ctx.respond("Invalid card lists...", ephemeral=True)
            return
        include_set = include_set[1]
        exclude_set = exclude_set[1]

        # Convert the object array into a dictionary for faster processing
        levels = {}
        for card in player_info:
            levels[card["name"].lower().replace(" ", "-").replace(".", "")] = 14 - card["maxLevel"] + card["level"]

        # Indicate that this code will take longer to run
        await ctx.defer()

        # Adjust algorithm variables based on user input
        pruning = 1 if pruning == "Yes" else 2
        variation = 1 if variation == "Yes" else 2

        # Get all decks from the database
        c = utilities.conn.cursor()
        decks = c.execute("SELECT * FROM decks").fetchall()

        # Create the initial message
        message = await ctx.send("Starting computation...")

        # Get the best deck sets
        best_decks = await utilities.compute_war_decks(decks_to_return, pruning, variation, include_set,
                                                       exclude_set, decks_to_generate, decks, levels, message)

        # Return the best decks
        ret = []
        idx = 1
        for deck in best_decks:
            cur = []
            for i in range(0, len(deck[2])):
                if i == 0:
                    embed = discord.Embed(
                        title=f"War Deck Set {idx}",
                        description=f"This war deck combination has a score of {round(float(deck[0]), 2)} with a level "
                                    f"utilization rate of {round(utilities.level_utilization(deck[2], levels), 1)}%. "
                                    f"Check the decks out below.",
                        color=discord.Colour.dark_magenta(),
                        url="https://royaleapi.com/decks/duel-search"
                    )
                    for j in range(0, len(deck[2])):
                        embed.add_field(name="",
                                        value=f"**Deck %d** [AVG LEVEL: %.3f]\nhttps://royaleapi.com/decks/stats/%s" %
                                              (j + 1,
                                               statistics.mean(utilities.get_deck_card_levels(deck[2][j], levels)),
                                               deck[2][j]
                                               ),
                                        inline=False
                                        )
                    embed.set_footer(text="Generated with ❤️ by TheBest")
                    embed.set_author(name="CR War Deck Builder")
                else:
                    embed = discord.Embed(
                        url="https://royaleapi.com/decks/duel-search"
                    )
                embed.set_image(
                    url=f"https://media.royaleapi.com/deck/{datetime.today().strftime('%Y-%m-%d')}/{deck[2][i]}.jpg")

                cur.append(embed)
            idx += 1
            ret.append(cur)

        paginator = pages.Paginator(
            pages=ret, loop_pages=True
        )

        # Send the response
        if len(ret) > 0:
            await message.delete()
            await paginator.respond(ctx.interaction, ephemeral=False)
        else:
            await message.edit("Could not generate decks with matching criteria...")
    except Exception as e:
        print(e)
        await message.delete()
        await ctx.send_followup("Error occurred, please try again later")


@bot.slash_command(name="load_deck_info", description="Load info for a particular deck")
@option("link", description="The RoyaleAPI link to the deck")
@option("name", description="The name of the deck")
@option("description", description="A brief description of the deck")
@option("show_battle_outcomes", description="Whether to show battle outcome data", choices=["Yes", "No"])
@option("show_challenge_wins", description="Whether to show challenge win info", choices=["Yes", "No"])
async def load_deck_info(ctx: discord.ApplicationContext, link: str, name: str, description: str,
                         show_battle_outcomes: str = "No", show_challenge_wins: str = "No"):
    try:
        # Get the deck info from RoyaleAPI
        session = requests.Session()
        response = session.get(link, headers={"user-agent": "Mozilla/5.0"})
        html = lxml.html.fromstring(response.text)

        # Create the initial embed
        embed = discord.Embed(
            title=f"__{name}__",
            description=description,
            color=discord.Colour.dark_magenta(),
            url=link
        )
        embed.add_field(name="", value="", inline=False)  # Padding

        if show_battle_outcomes == "Yes":
            # Add battle outcome info
            embed.add_field(name="Battle Outcomes", value="", inline=False)
            outcomes = html.cssselect(".ui.very.basic.compact.stats.unstackable.table")[0].xpath("tbody/tr/*/text()")
            embed.add_field(name="", value=f"__{outcomes[0]}__\n{outcomes[1]} | {outcomes[2]}", inline=True)
            embed.add_field(name="", value="", inline=True)  # Padding
            embed.add_field(name="", value=f"__{outcomes[3]}__\n{outcomes[4]} | {outcomes[5]}", inline=True)
            embed.add_field(name="", value=f"__{outcomes[6]}__\n{outcomes[7]} | {outcomes[8]}", inline=True)
            embed.add_field(name="", value="", inline=True)  # Padding
            embed.add_field(name="", value=f"__{outcomes[9]}__\n{outcomes[10]} | {outcomes[11]}", inline=True)
            embed.add_field(name="", value="", inline=False)  # Padding

        if show_challenge_wins == "Yes":
            # Add CC and GC win info
            embed.add_field(name="CC and GC Wins", value="", inline=False)
            win_timeframe = ["7d", "28d"]
            for idx, row in enumerate(html.cssselect(".item.cc")):
                arr = row.xpath("div/*/text()")
                embed.add_field(name="",
                                value=f"__CC Wins | {win_timeframe[idx]}__\n{arr[2].strip()}", inline=True)
                if idx == 0:
                    embed.add_field(name="", value="", inline=True)  # Padding
            for idx, row in enumerate(html.cssselect(".item.gc")):
                arr = row.xpath("div/*/text()")
                embed.add_field(name="",
                                value=f"__GC Wins | {win_timeframe[idx]}__\n{arr[2].strip()}", inline=True)
                if idx == 0:
                    embed.add_field(name="", value="", inline=True)  # Padding
            embed.add_field(name="", value="", inline=False)  # Padding

        # Add the in-game link
        game_link = html.cssselect(".ui.blue.icon.circular.button.button_popup")[0].get("href")
        embed.add_field(name="", value=f"__**[Copy deck in-game]({game_link})**__", inline=False)  # Padding

        # Add the deck image
        embed.set_image(
            url=f"https://media.royaleapi.com/deck/{datetime.today().strftime('%Y-%m-%d')}/{link.split('/')[-1]}.jpg")

        # Add the author and footer
        embed.set_author(name="Clash Utilities")
        embed.set_footer(text="Generated with ❤️ by TheBest")

        # Send the embed
        await ctx.respond(embed=embed)
    except Exception as e:
        print(e)
        await ctx.respond("Could not load deck info...", ephemeral=True)


# Get the latest meta decks every 24 hours
# Also deletes old decks
@tasks.loop(hours=24)
async def update_decks():
    print("Updating deck list...\t\t\t\t", datetime.now())
    c = utilities.conn.cursor()
    num_cards = len(c.execute("SELECT * FROM cards").fetchall())
    with alive_bar(num_cards) as bar:
        for row in c.execute("SELECT * FROM cards"):
            utilities.load_deck("https://royaleapi.com/decks/popular?type=GC&time=7d&size=20&inc=" + row[0])
            bar()
    c.execute("DELETE FROM decks WHERE entry_date < date('now', '-60 day')")  # Delete decks older than 60 days
    utilities.conn.commit()
    print("Decks updated...\t\t\t\t", datetime.now())


# Get the latest card list every 24 hours
# This ensures that any newly released card is in the database quickly
@tasks.loop(hours=24)
async def update_cards():
    utilities.update_cards()


# Printing a message when the bot has been loaded
@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!\n")
    try:
        # Create the connection and ensure that it is valid
        utilities.create_connection()
        assert utilities.conn is not None

        # Create the cards table if it doesn't already exist
        create_table(utilities.SQL_CREATE_CARDS_TABLE)

        # Create the decks table if it doesn't already exist
        create_table(utilities.SQL_CREATE_DECKS_TABLE)

        # Start tasks if they aren't in progress
        if not update_cards.is_running():
            update_cards.start()
        #if not update_decks.is_running():
        #    update_decks.start()

    except Exception as e:
        print(e)
        quit()


# Running the bot
bot.run(utilities.DISCORD_BOT_TOKEN)  # Run the bot with the token
