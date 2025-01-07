import os
import sys
import time
import json
import typing
import asyncio
import discord
import logging
from typing import Dict
from functools import wraps
from datetime import datetime
from dotenv import load_dotenv
from discord import app_commands, ui

load_dotenv(".env")

print("\n") #Prevent logging looks ugly when restarting

#SETUP
class _ColourFormatter(logging.Formatter):

    # ANSI codes are a bit weird to decipher if you're unfamiliar with them, so here's a refresher
    # It starts off with a format like \x1b[XXXm where XXX is a semicolon separated list of commands
    # The important ones here relate to colour.
    # 30-37 are black, red, green, yellow, blue, magenta, cyan and white in that order
    # 40-47 are the same except for the background
    # 90-97 are the same but "bright" foreground
    # 100-107 are the same as the bright ones but for the background.
    # 1 means bold, 2 means dim, 0 means reset, and 4 means underline.

    LEVEL_COLOURS = [
        (logging.DEBUG, '\x1b[40;1m'),
        (logging.INFO, '\x1b[34;1m'),
        (logging.WARNING, '\x1b[33;1m'),
        (logging.ERROR, '\x1b[31m'),
        (logging.CRITICAL, '\x1b[41m'),
    ]

    FORMATS = {
        level: logging.Formatter(
            f'\x1b[30;1m%(asctime)s\x1b[0m {colour}%(levelname)-8s\x1b[0m \x1b[35m%(name)s\x1b[0m %(message)s',
            '%Y-%m-%d %H:%M:%S',
        )
        for level, colour in LEVEL_COLOURS
    }

    def format(self, record):
        formatter = self.FORMATS.get(record.levelno)
        if formatter is None:
            formatter = self.FORMATS[logging.DEBUG]

        # Override the traceback to always print in red
        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            record.exc_text = f'\x1b[31m{text}\x1b[0m'

        output = formatter.format(record)

        # Remove the cache layer
        record.exc_text = None
        return output

#Logger init
pCoreLogger = logging.getLogger(f"protonn.{__name__.partition('.')[0]}")
pCoreLoggerHandler = logging.StreamHandler()
pCoreLoggerHandler.setFormatter(_ColourFormatter())
pCoreLogger.setLevel(logging.INFO)
pCoreLogger.addHandler(pCoreLoggerHandler)
#Guild data init
default_guild = 850912717107625984
default_channel = 1090320030094348389
default_tracking = 1130863192332058675

if not os.path.isfile("./data.json"):
    with open('data.json', 'w') as f:
        #Default configuration
        data = {
            "mainGuild": default_guild,
            "mainChannel": default_channel,
            "trackingChannel": default_tracking
        }
        json.dump(data, f, indent=2)
        main_guild = default_guild
        main_channel = default_channel
        tracking_channel = default_tracking
else:
    with open('data.json', 'r') as f:
        data = json.load(f);
        main_guild = data["mainGuild"]
        main_channel = data["mainChannel"]
        tracking_channel = data["trackingChannel"]

#Custom rate limit made by frozenpirate, modified by me
class RateLimit:
    def __init__(self, times: int = 1, seconds: int = 5, ephemeral: bool = True, ignoreManageGuildPermission: bool = False):
        self.times = times
        self.seconds = seconds
        self.ephemeral = ephemeral
        self.ignoreAdmin = ignoreManageGuildPermission
        self._user_commands: Dict[int, list] = typing.DefaultDict(list)
        self._cleanup_task = None
    
    async def _cleanup_old_entries(self):
        while True:
            current_time = datetime.now()
            for user_id in list(self._user_commands.keys()):
                self._user_commands[user_id] = [
                    timestamp for timestamp in self._user_commands[user_id]
                    if (current_time - timestamp).total_seconds() < self.seconds
                ]
                if not self._user_commands[user_id]:
                    del self._user_commands[user_id]
            await asyncio.sleep(self.seconds)

    def __call__(self, func):
        @wraps(func)
        async def wrapped(interaction: discord.Interaction, *args, **kwargs):
            if self._cleanup_task is None:
                self._cleanup_task = asyncio.create_task(self._cleanup_old_entries())
            pCoreLogger.debug("RateLimit decorator successfully executed")

            current_time = datetime.now()
            user_id = interaction.user.id

            # Check if user has exceeded rate limit
            recent_commands = len([
                t for t in self._user_commands[user_id]
                if (current_time - t).total_seconds() < self.seconds
            ])

            if recent_commands >= self.times:
                if self.ignoreAdmin and interaction.user.guild_permissions.manage_guild:
                    pCoreLogger.debug(f"Ignoring user {interaction.user.name} with manage guild permissions")
                    self._user_commands[user_id].append(current_time)
                    return await func(interaction, *args, **kwargs)
                else:
                    time_left = self.seconds - (current_time - min(self._user_commands[user_id])).seconds
                    embed = discord.Embed(
                        title="Rate Limited",
                        description=f"Please wait `{time_left}` seconds before using this command again.",
                        color=discord.Color.red()
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=self.ephemeral)
            self._user_commands[user_id].append(current_time)
            return await func(interaction, *args, **kwargs)

        return wrapped

#CLIENT
class aclient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.synced = False
        self.added = False
    
    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:
            await tree.sync(guild=discord.Object(id=main_guild))
            self.synced = True
        if not self.added:
            self.add_view(ticket_buttons())
            self.added = True
        pCoreLogger.info(f"Logged in as {self.user}")
    
client = aclient()
tree = app_commands.CommandTree(client)

#COMMAND CLASSES / FUNCTIONS
async def check_claimed(interaction: discord.Interaction):
    old_embed = interaction.message.embeds[0]
    claimed = False
    claimed_by = None
    on_streak = False
    claimed_by_id = ""
    for field in old_embed.fields:
        if field.name.lower() == "status":
            if "Claimed by" in field.value:
                claimed = True
                for _, letter_ in enumerate(field.value):
                    letter = str(letter_)
                    if letter.isdecimal():
                        on_streak = True
                        claimed_by_id = claimed_by_id + letter
                    else:
                        if on_streak:
                            on_streak = False
                            break
                claimed_by = await client.fetch_user(int(claimed_by_id))
                break
    if claimed:
        return True, claimed_by
    else:
        return False

async def get_current_unix():
    return f"<t:{int(time.mktime(datetime.now().timetuple()))}:R>"

async def track_ticket(ticket_message: discord.Message, delete: bool=False):
    track_channel = await client.fetch_channel(tracking_channel)
    messages = [message async for message in track_channel.history(limit=123)]
    trackMessage = None
    found = False
    for message in messages:
        if message.author == client.user and str(message.embeds[0].footer.text) == str(client.user.id):
            trackMessage = message
            found = True
            break
    if not found:
        embd = discord.Embed(title="Bugs not claimed/resolved", description="Bugs that are not claimed or not resolved is saved here", color=discord.Color.blue())
        embd.set_footer(text=str(client.user.id), icon_url=client.user.avatar.url)
        trackMessage = await track_channel.send(embed=embd)
    
    if delete:
        trackEmbed = trackMessage.embeds[0]
        ticketEmbed = ticket_message.embeds[0]
        ticketTitle = ticketEmbed.fields[1].value
        fieldsToAdd = []
        for field in trackEmbed.fields:
            if not field.name == ticketTitle and not field.value == ticket_message.jump_url:
                fieldsToAdd.append(field)
        newTrackEmbed = discord.Embed(title=trackEmbed.title, description=trackEmbed.description, color=discord.Color.blue())
        newTrackEmbed.set_footer(text=trackEmbed.footer.text, icon_url=client.user.avatar.url)
        for field_ in fieldsToAdd:
            newTrackEmbed.add_field(name=field_.name, value=field_.value, inline=False)
        await trackMessage.edit(embed=newTrackEmbed)
    else:
        trackEmbed = trackMessage.embeds[0]
        ticketEmbed = ticket_message.embeds[0]
        ticketTitle = ticketEmbed.fields[1].value
        trackEmbed.add_field(name=ticketTitle, value=ticket_message.jump_url, inline=False)
        await trackMessage.edit(embed=trackEmbed)
        

class ticket_buttons(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.children[1].disabled = True
        self.children[2].disabled = True

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.blurple, custom_id="claim_btn")
    async def claim(self, interaction: discord.Interaction, button: discord.Button):
        data = await check_claimed(interaction)
        if type(data) is bool:
            claimed = data
        else:
            claimed = data[0]
        if claimed:
            return await interaction.response.send_message("This ticket is already claimed!", ephemeral=True)
        old_embed = interaction.message.embeds[0]
        embed = discord.Embed(title=old_embed.title, description=old_embed.description, color=discord.Color.blue(), timestamp=old_embed.timestamp)
        embed.set_author(name=old_embed.author.name, icon_url=old_embed.author.icon_url)
        embed.set_thumbnail(url=old_embed.thumbnail.url)
        for field in old_embed.fields:
            if field.name.lower() == "status":
                embed.add_field(name=field.name, value=f"Claimed by {interaction.user.mention} at {await get_current_unix()}", inline=False)
            else:
                embed.add_field(name=field.name, value=field.value, inline=False)
        embed.set_footer(icon_url=old_embed.footer.icon_url, text=old_embed.footer.text)
        button.disabled = True
        self.children[1].disabled = False
        self.children[2].disabled = False
        await interaction.message.edit(embed=embed, view=self)
        return await interaction.response.send_message("You've claimed this ticket!", ephemeral=True)
    
    @discord.ui.button(label="Resolved", style=discord.ButtonStyle.green, custom_id="resolved_btn")
    async def resolved(self, interaction: discord.Interaction, button: discord.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        data = await check_claimed(interaction)
        if type(data) is bool:
            claimed = data
        else:
            claimed = data[0]
            claimed_by = data[1]
        if not claimed:
            return await interaction.response.send_message("You have to claim this ticket first!", ephemeral=True)
        else:
            claimed_by = data[1]
            if interaction.user == claimed_by:
                old_embed = interaction.message.embeds[0]
                embed = discord.Embed(title=old_embed.title, description=old_embed.description, color=discord.Color.green(), timestamp=old_embed.timestamp)
                embed.set_author(name=old_embed.author.name, icon_url=old_embed.author.icon_url)
                embed.set_thumbnail(url=old_embed.thumbnail.url)
                for field in old_embed.fields:
                    if field.name.lower() == "status":
                        embed.add_field(name=field.name, value=f"Resolved by {interaction.user.mention} at {await get_current_unix()}", inline=False)
                    else:
                        embed.add_field(name=field.name, value=field.value, inline=False)
                    if field.name.lower() == "title":
                        title = field.value
                embed.set_footer(icon_url=old_embed.footer.icon_url, text=old_embed.footer.text)
                for item in self.children:
                    item.disabled = True
                ticketmsg = await interaction.message.edit(embed=embed, view=self)
                await track_ticket(ticketmsg, True)
                user = await client.fetch_user(int(old_embed.footer.text))
                await user.send(f"Your ticket has been marked as resolved!\nTicket title: `{title}`\nResolved At: {await get_current_unix()}")
                return await interaction.followup.send("Ticket marked as resolved!", ephemeral=True)
            else:
                return await interaction.follwoup.send("You can not mark this ticket as resolved since you didn't claim this ticket!", ephemeral=True)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.red, custom_id="close_btn")
    async def close(self, interaction: discord.Interaction, button: discord.Button):
        data = await check_claimed(interaction)
        if type(data) is bool:
            claimed = data
        else:
            claimed = data[0]
            claimed_by = data[1]
        if claimed:
            if interaction.user == claimed_by:
                self_ = self
                class close_reason_modal(ui.Modal, title="Reason"):
                    reason = ui.TextInput(label="Enter the reason why the ticket was closed:", style=discord.TextStyle.short, required=True, min_length=2, max_length=500, row=0)

                    async def on_submit(self, interaction: discord.Interaction):
                        old_embed = interaction.message.embeds[0]
                        embed = discord.Embed(title=old_embed.title, description=old_embed.description, color=discord.Color.purple(), timestamp=old_embed.timestamp)
                        embed.set_author(name=old_embed.author.name, icon_url=old_embed.author.icon_url)
                        embed.set_thumbnail(url=old_embed.thumbnail.url)
                        for field in old_embed.fields:
                            if field.name.lower() == "status":
                                embed.add_field(name=field.name, value=f"Closed by {interaction.user.mention} at {await get_current_unix()}", inline=False)
                            else:
                                embed.add_field(name=field.name, value=field.value, inline=False)
                            if field.name.lower() == "title":
                                title = field.value
                        embed.set_footer(icon_url=old_embed.footer.icon_url, text=old_embed.footer.text)
                        for item in self_.children:
                            item.disabled = True
                        ticketmsg = await interaction.message.edit(embed=embed, view=self_)
                        await track_ticket(ticketmsg, True)
                        await interaction.response.send_message("Ticket marked as closed!", ephemeral=True)
                        user = await client.fetch_user(int(old_embed.footer.text))
                        await user.send(f"Your ticket was closed!\nTicket title: {title}\nReason: `{self.reason}`\nClosed at: {await get_current_unix()}")
                await interaction.response.send_modal(close_reason_modal())
            else:
                return await interaction.response.send_message("You can not mark this ticket as closed since you didn't claim this ticket!", ephemeral=True)
        else:
            return await interaction.response.send_message("You have to claim this ticket first!", ephemeral=True)

class ticket_modal(ui.Modal, title="Bug report"):
    title_ = ui.TextInput(label="Please give a general title to your ticket:", style=discord.TextStyle.short, required=True, row=0, max_length=45)
    bug = ui.TextInput(label="Please describe what bug you've experienced:", style=discord.TextStyle.long, required=True, row=1, max_length=700)
    impacted = ui.TextInput(label="What part of our/other service is impacted?", style=discord.TextStyle.short, required=True, row=2, max_length=400, min_length=2, placeholder="pro-tonn host, pro-tonn bot, pro-tonn activities, others...")
    notes = ui.TextInput(label="Notes for developers", style=discord.TextStyle.long, required=False, row=3, max_length=400)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Bug report", description="A bug report has been submitted", color=discord.Color.red(), timestamp=datetime.now())
        embed.set_author(name="Pro-tonn Ticket", icon_url=client.user.avatar.url if not client.user.avatar is None else "https://cdn.discordapp.com/embed/avatars/0.png")
        embed.set_thumbnail(url=interaction.user.avatar.url)
        embed.add_field(name="Submission Info", value=f"Submitted by {interaction.user.mention} at {await get_current_unix()}", inline=False)
        embed.add_field(name="Title", value=self.title_, inline=False)
        embed.add_field(name="Description", value=self.bug, inline=False)
        embed.add_field(name="Impacted Service(s)", value=self.impacted, inline=False)
        embed.add_field(name="Ticket Notes", value=self.notes if not str(self.notes).replace(" ", "") == "" else "None", inline=False)
        embed.add_field(name="Status", value="Waiting to be claimed/closed", inline=False)
        embed.set_footer(icon_url=client.user.avatar.url if not client.user.avatar is None else "https://cdn.discordapp.com/embed/avatars/0.png", text=str(interaction.user.id))
        channel = await client.fetch_channel(main_channel)
        ticketMsg = await channel.send(embed=embed, view=ticket_buttons())
        await track_ticket(ticketMsg)
        await interaction.response.send_message("Your feedback was sent to the developers!", ephemeral=True)

@tree.command(guild=discord.Object(id=main_guild), name="ticket", description="Open a ticket for bug report")
@RateLimit(times=1, seconds=180, ephemeral=True, ignoreManageGuildPermission=True)
async def ticket_bug_report(interaction: discord.Interaction):
    await interaction.response.send_modal(ticket_modal())

@tree.command(guild=discord.Object(id=main_guild), name="restart", description="(Admin Only) Restart the bot")
@app_commands.checks.has_permissions(manage_guild=True)
async def restart_bot(interaction: discord.Interaction):
    embed = discord.Embed(title="Restarting bot", description="Bot is currently restarting, this process will take up to a minute!", color=discord.Color.blue())
    embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url if not interaction.user.avatar is None else "https://cdn.discordapp.com/embed/avatars/0.png")
    embed.add_field(name="Restart info", value=f"\n**Executable:** `{sys.executable}`\n\n**Args:** `{sys.argv}`", inline=True)
    embed.set_footer(icon_url=client.user.avatar.url if not client.user.avatar is None else "https://cdn.discordapp.com/embed/avatars/0.png", text="Pro-tonn bug report")
    await interaction.response.send_message(embed=embed)
    pCoreLogger.info(f"Restarting bot(Issued by {interaction.user.name})...")
    return os.execv(sys.executable, ['python'] + sys.argv)

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        return await interaction.response.send_message(error, ephemeral=True)
    else:
        return await interaction.response.send_message(error, ephemeral=True)

pCoreLogger.info("Functions intitialized")
pCoreLogger.info("Trying to log in with token...")

async def main():
    await client.start(os.getenv("TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())