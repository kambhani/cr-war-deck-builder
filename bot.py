import discord
from dotenv import load_dotenv
import os

load_dotenv()
CR_API_TOKEN = os.getenv("CR_API_TOKEN")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f'{client.user} has connected to discord!')


client.run(DISCORD_BOT_TOKEN)
