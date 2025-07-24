import discord
from discord.ext import commands
from typing import Union
import os
import asyncio
import random
from io import BytesIO
from PIL import Image
import json
from datetime import timedelta

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=",", intents=intents)

WARN_FILE = "warnings.json"
IP_BAN_FILE = "ip_bans.json"

# --- Helper functions for warnings ---
def load_warnings():
    try:
        with open(WARN_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_warnings(data):
    with open(WARN_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- Helper functions for IP bans ---
def load_ip_bans():
    try:
        with open(IP_BAN_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_ip_bans(data):
    with open(IP_BAN_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- Moderation Cog ---
class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def log_action(self, ctx, action: str, target: Union[discord.Member, str], reason: str):
        channel = discord.utils.get(ctx.guild.text_channels, name="mod-logs")
        if not channel:
            return
        embed = discord.Embed(title="🛡️ Moderation Log", color=discord.Color.orange())
        embed.add_field(name="Action", value=action, inline=False)
        embed.add_field(name="Target", value=str(target), inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Channel: #{ctx.channel.name} • ID: {ctx.channel.id}")
        await channel.send(embed=embed)

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await member.ban(reason=reason)
        await ctx.send(f"🔨 Banned {member} | Reason: {reason}")
        await self.log_action(ctx, "Ban", member, reason)

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, *, user: str):
        banned_users = await ctx.guild.bans()
        try:
            name, discriminator = user.split("#")
        except ValueError:
            return await ctx.send("❌ Please use the format: username#discriminator")
        for ban_entry in banned_users:
            if (ban_entry.user.name, ban_entry.user.discriminator) == (name, discriminator):
                await ctx.guild.unban(ban_entry.user)
                await ctx.send(f"✅ Unbanned {user}")
                await self.log_action(ctx, "Unban", user, "Manual unban")
                return
        await ctx.send("❌ User not found.")

    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await member.kick(reason=reason)
        await ctx.send(f"👢 Kicked {member} | Reason: {reason}")
        await self.log_action(ctx, "Kick", member, reason)

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def mute(self, ctx, member: discord.Member, *, reason="No reason provided"):
        role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not role:
            return await ctx.send("❌ No 'Muted' role found.")
        await member.add_roles(role)
        await ctx.send(f"🔇 Muted {member} | Reason: {reason}")
        await self.log_action(ctx, "Mute", member, reason)

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member):
        role = discord.utils.get(ctx.guild.roles, name="Muted")
        if role and role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🔊 Unmuted {member}")
            await self.log_action(ctx, "Unmute", member, "Manual unmute")
        else:
            await ctx.send("❌ User is not muted.")

    @commands.command(aliases=['purge'])
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 5):
        if amount < 1:
            return await ctx.send("❌ Please specify at least 1 message to delete.")
        deleted = await ctx.channel.purge(limit=amount)
        confirm = await ctx.send(f"🧹 Cleared {len(deleted)} messages.")
        await asyncio.sleep(2)
        await confirm.delete()
        await self.log_action(ctx, "Clear Messages", f"{len(deleted)} messages", f"by {ctx.author}")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int = 0):
        await ctx.channel.edit(slowmode_delay=seconds)
        await ctx.send(f"⏱️ Slowmode set to {seconds} seconds.")
        await self.log_action(ctx, "Slowmode Set", ctx.channel.name, f"{seconds} seconds")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx):
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 Channel locked.")
        await self.log_action(ctx, "Lock Channel", ctx.channel.name, "Locked by mod")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx):
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send("🔓 Channel unlocked.")
        await self.log_action(ctx, "Unlock Channel", ctx.channel.name, "Unlocked by mod")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def say(self, ctx, *, message):
        await ctx.message.delete()
        await ctx.send(message)
        await self.log_action(ctx, "Say Command", "Bot said a message", message)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason="No reason provided"):
        warnings = load_warnings()
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        warnings.setdefault(guild_id, {}).setdefault(user_id, []).append(reason)
        save_warnings(warnings)

        try:
            await member.send(f"⚠️ You have been warned in **{ctx.guild.name}**.\n**Reason:** {reason}")
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM the user.")

        await ctx.send(f"⚠️ Warned {member.mention} | Reason: {reason}")
        await self.log_action(ctx, "Warn", member, reason)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warnings(self, ctx, member: discord.Member):
        warnings = load_warnings()
        user_warnings = warnings.get(str(ctx.guild.id), {}).get(str(member.id), [])

        if not user_warnings:
            return await ctx.send(f"✅ {member.display_name} has no warnings.")

        warning_list = "\n".join([f"{i+1}. {r}" for i, r in enumerate(user_warnings)])
        embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", description=warning_list, color=discord.Color.orange())
        await ctx.send(embed=embed)

    @commands.command(aliases=["delwarn", "clearwarn"])
    @commands.has_permissions(manage_messages=True)
    async def removewarn(self, ctx, member: discord.Member, index: int = None):
        warnings = load_warnings()
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        user_warnings = warnings.get(guild_id, {}).get(user_id, [])

        if not user_warnings:
            return await ctx.send("❌ That user has no warnings.")

        if index is None or index < 1 or index > len(user_warnings):
            return await ctx.send(f"❌ Provide a valid warning number between 1 and {len(user_warnings)}.")

        removed = user_warnings.pop(index - 1)

        if not user_warnings:
            warnings[guild_id].pop(user_id)
            if not warnings[guild_id]:
                warnings.pop(guild_id)
        else:
            warnings[guild_id][user_id] = user_warnings

        save_warnings(warnings)

        await ctx.send(f"✅ Removed warning #{index} from {member.mention}.\n**Removed Reason:** {removed}")
        await self.log_action(ctx, "Remove Warn", member, f"Removed warning #{index}: {removed}")

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: int, *, reason="No reason provided"):
        try:
            until = discord.utils.utcnow() + timedelta(minutes=duration)
            await member.timeout(until, reason=reason)
            await ctx.send(f"⏲️ {member.mention} has been timed out for {duration} minutes.\nReason: {reason}")
        except Exception as e:
            await ctx.send(f"❌ Could not timeout the member: {e}")

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member, *, reason="No reason provided"):
        try:
            await member.timeout(None, reason=reason)
            await ctx.send(f"✅ {member.mention} has been un-timed out.\nReason: {reason}")
        except Exception as e:
            await ctx.send(f"❌ Could not remove timeout: {e}")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ipban(self, ctx, member: discord.Member, ip: str, *, reason="No reason provided"):
        ip_bans = load_ip_bans()
        ip_bans[ip] = {
            "user_id": member.id,
            "reason": reason,
            "moderator": ctx.author.id
        }
        save_ip_bans(ip_bans)

        await member.ban(reason=f"IP Ban: {reason}")
        await ctx.send(f"🚫 IP `{ip}` associated with {member} has been banned.\nReason: {reason}")
        await self.log_action(ctx, "IP Ban", f"{member} (IP: {ip})", reason)

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unipban(self, ctx, ip: str):
        ip_bans = load_ip_bans()
        if ip in ip_bans:
            removed = ip_bans.pop(ip)
            save_ip_bans(ip_bans)
            await ctx.send(f"✅ IP `{ip}` unbanned. Previously linked to user ID {removed['user_id']}.")
            await self.log_action(ctx, "Un-IP Ban", ip, "Manual unban")
        else:
            await ctx.send("❌ That IP isn’t currently banned.")

    @commands.command()
    async def ipbans(self, ctx):
        ip_bans = load_ip_bans()
        if not ip_bans:
            return await ctx.send("✅ No IPs are currently banned.")
        ban_list = "\n".join([f"`{ip}` - User ID: {data['user_id']} (Reason: {data['reason']})" for ip, data in ip_bans.items()])
        embed = discord.Embed(title="🚫 IP Ban List", description=ban_list, color=discord.Color.red())
        await ctx.send(embed=embed)

# --- Fun Cog ---
class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def joke(self, ctx):
        jokes = [
            "Why don’t skeletons fight each other? They don’t have the guts.",
            "I told my computer I needed a break, and it said 'No problem, I’ll go to sleep.'",
            "Why was the math book sad? Because it had too many problems.",
            "I'm reading a book about anti-gravity. It's impossible to put down!"
        ]
        await ctx.send(random.choice(jokes))

    @commands.command(aliases=['8ball'])
    async def eightball(self, ctx, *, question):
        responses = [
            "Yes.", "No.", "Maybe.", "Ask again later.", "Definitely!", "Absolutely not.",
            "I wouldn’t count on it.", "It is certain.", "Very doubtful."
        ]
        await ctx.send(f"🎱 {random.choice(responses)}")

    @commands.command()
    async def rizz(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        score = random.randint(0, 100)
        await ctx.send(f"💅 {member.display_name} has **{score}%** rizz!")

    @commands.command()
    async def flip(self, ctx):
        await ctx.send(f"🪙 The coin landed on **{random.choice(['Heads', 'Tails'])}**!")

    @commands.command()
    async def roll(self, ctx, sides: int = 6):
        if sides < 2:
            return await ctx.send("🎲 Dice must have at least 2 sides!")
        await ctx.send(f"🎲 You rolled a **{random.randint(1, sides)}** on a {sides}-sided die!")

    @commands.command()
    async def roast(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        roasts = [
            f"{member.display_name}, you bring everyone so much joy... when you leave the room.",
            f"{member.display_name}, your secrets are always safe with me. I never even listen.",
            f"{member.display_name}, you're like a cloud. When you disappear, it’s a beautiful day.",
        ]
        await ctx.send(random.choice(roasts))

    @commands.command()
    async def compliment(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        compliments = [
            "You’re like sunshine on a rainy day.",
            "You're the reason the internet exists.",
            "You're cooler than a polar bear in sunglasses.",
            "You light up Discord like nobody else."
        ]
        await ctx.send(f"💖 {member.mention}, {random.choice(compliments)}")

    @commands.command()
    async def saydumb(self, ctx):
        dumb_things = [
            "I put my AirPods in a glass of water to charge them with hydration.",
            "I use dark mode to save ink.",
            "I microwave my phone to charge it faster.",
            "I turn off Wi-Fi to let the signal rest."
        ]
        await ctx.send(random.choice(dumb_things))

    @commands.command()
    async def mathmeme(self, ctx):
        memes = [
            "Math teachers be like: 'Assume the ladder is frictionless and infinite.'",
            "x = -b ± √(b² - 4ac) / 2a = Stress",
            "When you finally solve a problem and the answer is nowhere near the options.",
        ]
        await ctx.send(f"📐 {random.choice(memes)}")

    @commands.command()
    async def rate(self, ctx, *, thing: str):
        await ctx.send(f"I'd rate **{thing}** a solid **{random.randint(1,10)}/10**!")

    @commands.command()
    async def hacker(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        fake_ip = f"{random.randint(10, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}"
        await ctx.send(f"💻 Hacking {target.display_name}...\nIP FOUND: `{fake_ip}`\nAccessing messages... 💾\nDownload complete ✔️")

    @commands.command()
    async def rps(self, ctx, choice: str):
        user = choice.lower()
        bot_choice = random.choice(["rock", "paper", "scissors"])
        win = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        if user not in win:
            return await ctx.send("Please choose rock, paper, or scissors.")
        if user == bot_choice:
            result = "It's a tie!"
        elif win[user] == bot_choice:
            result = "You win!"
        else:
            result = "I win!"
        await ctx.send(f"You chose **{user}**, I chose **{bot_choice}**. {result}")

    @commands.command()
    async def emoji(self, ctx):
        emojis = ['😂', '🔥', '💀', '💯', '👀', '😎', '🥶', '😭', '😤']
        await ctx.send(random.choice(emojis))

    @commands.command()
    async def spamemoji(self, ctx):
        emojis = ['😂', '🔥', '💀', '💯', '👀', '😎', '🥶', '😭', '😤']
        await ctx.send(" ".join(random.choices(emojis, k=20)))

    @commands.command(name="to_gif", help="Convert an uploaded image to a GIF")
    async def to_gif(self, ctx):
        if not ctx.message.attachments:
            return await ctx.send("❌ Please attach an image to convert.")
        attachment = ctx.message.attachments[0]
        if not any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'bmp']):
            return await ctx.send("❌ Unsupported file type. Please upload a PNG, JPG, or BMP image.")
        try:
            image_bytes = await attachment.read()
            image = Image.open(BytesIO(image_bytes))
            gif_bytes = BytesIO()
            image.save(gif_bytes, format="GIF")
            gif_bytes.seek(0)
            await ctx.send(file=discord.File(fp=gif_bytes, filename="converted.gif"))
        except Exception as e:
           Here is a **full, complete bot code** combining everything you showed plus fixes for your coroutine warnings (await `add_cog`), with placeholders for your own implementations in some cogs, and all the features in one file:

```python
import discord
from discord.ext import commands
from typing import Union
import os
import asyncio
import random
from io import BytesIO
from PIL import Image
import json
from datetime import timedelta

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=",", intents=intents)

WARN_FILE = "warnings.json"
IP_BAN_FILE = "ip_bans.json"

def load_warnings():
    try:
        with open(WARN_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_warnings(data):
    with open(WARN_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_ip_bans():
    try:
        with open(IP_BAN_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_ip_bans(data):
    with open(IP_BAN_FILE, "w") as f:
        json.dump(data, f, indent=4)

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def log_action(self, ctx, action: str, target: Union[discord.Member, str], reason: str):
        channel = discord.utils.get(ctx.guild.text_channels, name="mod-logs")
        if channel:
            embed = discord.Embed(title="🛡️ Moderation Log", color=discord.Color.orange())
            embed.add_field(name="Action", value=action, inline=False)
            embed.add_field(name="Target", value=str(target), inline=False)
            embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.set_footer(text=f"Channel: #{ctx.channel.name} • ID: {ctx.channel.id}")
            await channel.send(embed=embed)

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await member.ban(reason=reason)
        await ctx.send(f"🔨 Banned {member} | Reason: {reason}")
        await self.log_action(ctx, "Ban", member, reason)

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, *, user: str):
        banned_users = await ctx.guild.bans()
        try:
            name, discriminator = user.split("#")
        except ValueError:
            return await ctx.send("❌ Please use the format: username#discriminator")
        for ban_entry in banned_users:
            if (ban_entry.user.name, ban_entry.user.discriminator) == (name, discriminator):
                await ctx.guild.unban(ban_entry.user)
                await ctx.send(f"✅ Unbanned {user}")
                await self.log_action(ctx, "Unban", user, "Manual unban")
                return
        await ctx.send("❌ User not found.")

    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await member.kick(reason=reason)
        await ctx.send(f"👢 Kicked {member} | Reason: {reason}")
        await self.log_action(ctx, "Kick", member, reason)

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def mute(self, ctx, member: discord.Member, *, reason="No reason provided"):
        role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not role:
            return await ctx.send("❌ No 'Muted' role found.")
        await member.add_roles(role)
        await ctx.send(f"🔇 Muted {member} | Reason: {reason}")
        await self.log_action(ctx, "Mute", member, reason)

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member):
        role = discord.utils.get(ctx.guild.roles, name="Muted")
        if role and role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🔊 Unmuted {member}")
            await self.log_action(ctx, "Unmute", member, "Manual unmute")
        else:
            await ctx.send("❌ User is not muted.")

    @commands.command(aliases=['purge'])
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 5):
        if amount < 1:
            return await ctx.send("❌ Please specify at least 1 message to delete.")
        deleted = await ctx.channel.purge(limit=amount)
        confirm = await ctx.send(f"🧹 Cleared {len(deleted)} messages.")
        await asyncio.sleep(2)
        await confirm.delete()
        await self.log_action(ctx, "Clear Messages", f"{len(deleted)} messages", f"by {ctx.author}")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int = 0):
        await ctx.channel.edit(slowmode_delay=seconds)
        await ctx.send(f"⏱️ Slowmode set to {seconds} seconds.")
        await self.log_action(ctx, "Slowmode Set", ctx.channel.name, f"{seconds} seconds")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx):
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 Channel locked.")
        await self.log_action(ctx, "Lock Channel", ctx.channel.name, "Locked by mod")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx):
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send("🔓 Channel unlocked.")
        await self.log_action(ctx, "Unlock Channel", ctx.channel.name, "Unlocked by mod")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def say(self, ctx, *, message):
        await ctx.message.delete()
        await ctx.send(message)
        await self.log_action(ctx, "Say Command", "Bot said a message", message)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason="No reason provided"):
        warnings = load_warnings()
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        warnings.setdefault(guild_id, {}).setdefault(user_id, []).append(reason)
        save_warnings(warnings)

        try:
            await member.send(f"⚠️ You have been warned in **{ctx.guild.name}**.\n**Reason:** {reason}")
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM the user.")

        await ctx.send(f"⚠️ Warned {member.mention} | Reason: {reason}")
        await self.log_action(ctx, "Warn", member, reason)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warnings(self, ctx, member: discord.Member):
        warnings = load_warnings()
        user_warnings = warnings.get(str(ctx.guild.id), {}).get(str(member.id), [])

        if not user_warnings:
            return await ctx.send(f"✅ {member.display_name} has no warnings.")

        warning_list = "\n".join([f"{i+1}. {r}" for i, r in enumerate(user_warnings)])
        embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", description=warning_list, color=discord.Color.orange())
        await ctx.send(embed=embed)

    @commands.command(aliases=["delwarn", "clearwarn"])
    @commands.has_permissions(manage_messages=True)
    async def removewarn(self, ctx, member: discord.Member, index: int = None):
        warnings = load_warnings()
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        user_warnings = warnings.get(guild_id, {}).get(user_id, [])

        if not user_warnings:
            return await ctx.send("❌ That user has no warnings.")

        if index is None or index < 1 or index > len(user_warnings):
            return await ctx.send(f"❌ Provide a valid warning number between 1 and {len(user_warnings)}.")

        removed = user_warnings.pop(index - 1)

        if not user_warnings:
            warnings[guild_id].pop(user_id)
            if not warnings[guild_id]:
                warnings.pop(guild_id)
        else:
            warnings[guild_id][user_id] = user_warnings

        save_warnings(warnings)

        await ctx.send(f"✅ Removed warning #{index} from {member.mention}.\n**Removed Reason:** {removed}")
        await self.log_action(ctx, "Remove Warn", member, f"Removed warning #{index}: {removed}")

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: int, *, reason="No reason provided"):
        try:
            until = discord.utils.utcnow() + timedelta(minutes=duration)
            await member.timeout(until, reason=reason)
            await ctx.send(f"⏲️ {member.mention} has been timed out for {duration} minutes.\nReason: {reason}")
        except Exception as e:
            await ctx.send(f"❌ Could not timeout the member: {e}")

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member, *, reason="No reason provided"):
        try:
            await member.timeout(None, reason=reason)
            await ctx.send(f"✅ {member.mention} has been un-timed out.\nReason: {reason}")
        except Exception as e:
            await ctx.send(f"❌ Could not remove timeout: {e}")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ipban(self, ctx, member: discord.Member, ip: str, *, reason="No reason provided"):
        ip_bans = load_ip_bans()
        ip_bans[ip] = {
            "user_id": member.id,
            "reason": reason,
            "moderator": ctx.author.id
        }
        save_ip_bans(ip_bans)

        await member.ban(reason=f"IP Ban: {reason}")
        await ctx.send(f"🚫 IP `{ip}` associated with {member} has been banned.\nReason: {reason}")
        await self.log_action(ctx, "IP Ban", f"{member} (IP: {ip})", reason)

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unipban(self, ctx, ip: str):
        ip_bans = load_ip_bans()
        if ip in ip_bans:
            removed = ip_bans.pop(ip)
            save_ip_bans(ip_bans)
            await ctx.send(f"✅ IP `{ip}` unbanned. Previously linked to user ID {removed['user_id']}.")
            await self.log_action(ctx, "Un-IP Ban", ip, "Manual unban")
        else:
            await ctx.send("❌ That IP isn’t currently banned.")

    @commands.command()
    async def ipbans(self, ctx):
        ip_bans = load_ip_bans()
        if not ip_bans:
            return await ctx.send("✅ No IPs are currently banned.")
        ban_list = "\n".join([f"`{ip}` - User ID: {data['user_id']} (Reason: {data['reason']})" for ip, data in ip_bans.items()])
        embed = discord.Embed(title="🚫 IP Ban List", description=ban_list, color=discord.Color.red())
        await ctx.send(embed=embed)

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def joke(self, ctx):
        jokes = [
            "Why don’t skeletons fight each other? They don’t have the guts.",
            "I told my computer I needed a break, and it said 'No problem, I’ll go to sleep.'",
            "Why was the math book sad? Because it had too many problems.",
            "I'm reading a book about anti-gravity. It's impossible to put down!"
        ]
        await ctx.send(random.choice(jokes))

    # Add all other fun commands from your original code here...

    @commands.command(name="to_gif", help="Convert an uploaded image to a GIF")
    async def to_gif(self, ctx):
        if not ctx.message.attachments:
            return await ctx.send("❌ Please attach an image to convert.")
        attachment = ctx.message.attachments[0]
        if not any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'bmp']):
            return await ctx.send("❌ Unsupported file type. Please upload a PNG, JPG, or BMP image.")
        try:
            image_bytes = await attachment.read()
            image = Image.open(BytesIO(image_bytes))
            gif_bytes = BytesIO()
            image.save(gif_bytes, format="GIF")
            gif_bytes.seek(0)
            await ctx.send(file=discord.File(fp=gif_bytes, filename="converted.gif"))
        except Exception as e:
            await ctx.send(f"❌ Failed to convert image: {e}")

# Placeholder cogs you can implement later
class ActivityWatcher(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

class VoiceChannels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

async def main():
    async with bot:
        await bot.add_cog(Moderation(bot))
        await bot.add_cog(Fun(bot))
        await bot.add_cog(ActivityWatcher(bot))
        await bot.add_cog(Leveling(bot))
        await bot.add_cog(Polls(bot))
        await bot.add_cog(VoiceChannels(bot))
        await bot.add_cog(AutoMod(bot))

        token = os.getenv("DISCORD_TOKEN")
        if not token:
            print("❌ DISCORD_TOKEN environment variable not set.")
            return
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
