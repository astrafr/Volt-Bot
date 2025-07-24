import discord
from discord.ext import commands
from typing import Union
import os
import asyncio
import random
from io import BytesIO
from PIL import Image
import json
from datetime import timedelta, datetime

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.presences = True  # For presence updates in ActivityWatcher

bot = commands.Bot(command_prefix=",", intents=intents)

WARN_FILE = "warnings.json"
IP_BAN_FILE = "ip_bans.json"
LEVELS_FILE = "levels.json"

# ---------------- File helpers ---------------- #
def load_json(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

def load_warnings():
    return load_json(WARN_FILE)

def save_warnings(data):
    save_json(WARN_FILE, data)

def load_ip_bans():
    return load_json(IP_BAN_FILE)

def save_ip_bans(data):
    save_json(IP_BAN_FILE, data)

def load_levels():
    return load_json(LEVELS_FILE)

def save_levels(data):
    save_json(LEVELS_FILE, data)

# ---------------- Moderation Cog ---------------- #
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
        deleted = 0
        while amount > 0:
            to_delete = min(amount, 1000)
            batch = await ctx.channel.purge(limit=to_delete, bulk=True)
            deleted += len(batch)
            amount -= len(batch)
            if len(batch) == 0:
                break
        confirm = await ctx.send(f"🧹 Cleared {deleted} messages.")
        await asyncio.sleep(2)
        await confirm.delete()
        await self.log_action(ctx, "Clear Messages", f"{deleted} messages", f"by {ctx.author}")

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

# ---------------- Fun Cog ---------------- #
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
            await ctx.send(f"❌ Failed to convert image: {e}")

# ---------------- ActivityWatcher Cog ---------------- #
class ActivityWatcher(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.watch_data = {}

    @commands.command()
    async def watch(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        data = self.watch_data.get(str(member.id))
        if not data:
            return await ctx.send(f"⚠️ No watch data found for {member.display_name}.")
        await ctx.send(f"👀 Watching {member.display_name}: {data}")

    @commands.command()
    async def setwatch(self, ctx, *, info: str):
        self.watch_data[str(ctx.author.id)] = info
        await ctx.send(f"✅ Watch info set for {ctx.author.display_name}: {info}")

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        # Could update watch_data or trigger alerts here
        pass

# ---------------- CustomVC Cog ---------------- #
class CustomVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_channels = {}

    @commands.command()
    async def createvc(self, ctx, *, name="Private VC"):
        category = discord.utils.get(ctx.guild.categories, name="Custom VCs")
        if not category:
            category = await ctx.guild.create_category("Custom VCs")
        vc = await ctx.guild.create_voice_channel(name, category=category)
        await vc.set_permissions(ctx.author, manage_channels=True)
        self.temp_channels[vc.id] = ctx.author.id
        await ctx.send(f"🎙️ Created custom voice channel: **{vc.name}**")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        for vc_id, owner_id in list(self.temp_channels.items()):
            vc = member.guild.get_channel(vc_id)
            if vc and len(vc.members) == 0:
                await vc.delete()
                self.temp_channels.pop(vc_id)

# ---------------- Leveling Cog ---------------- #
class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.levels = load_levels()

    def get_xp(self, guild_id, user_id):
        return self.levels.get(str(guild_id), {}).get(str(user_id), 0)

    def set_xp(self, guild_id, user_id, xp):
        self.levels.setdefault(str(guild_id), {})[str(user_id)] = xp
        save_levels(self.levels)

    def xp_to_level(self, xp):
        return int((xp / 50) ** 0.5)

    def level_to_xp(self, level):
        return 50 * (level ** 2)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        current_xp = self.get_xp(guild_id, user_id)
        current_level = self.xp_to_level(current_xp)
        xp_gain = random.randint(5, 15)
        new_xp = current_xp + xp_gain
        new_level = self.xp_to_level(new_xp)
        self.set_xp(guild_id, user_id, new_xp)
        if new_level > current_level:
            await message.channel.send(f"🎉 Congrats {message.author.mention}, you leveled up to level **{new_level}**!")

    @commands.command()
    async def level(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        xp = self.get_xp(guild_id, user_id)
        level = self.xp_to_level(xp)
        await ctx.send(f"⭐ {member.display_name} is level {level} with {xp} XP.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def addlevel(self, ctx, member: discord.Member, levels: int):
        if levels < 1:
            return await ctx.send("❌ Levels to add must be at least 1.")
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        current_xp = self.get_xp(guild_id, user_id)
        current_level = self.xp_to_level(current_xp)
        new_level = current_level + levels
        new_xp = self.level_to_xp(new_level)
        self.set_xp(guild_id, user_id, new_xp)
        await ctx.send(f"✅ Added {levels} levels to {member.display_name}. Now level {new_level}.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def removelevel(self, ctx, member: discord.Member, levels: int):
        if levels < 1:
            return await ctx.send("❌ Levels to remove must be at least 1.")
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        current_xp = self.get_xp(guild_id, user_id)
        current_level = self.xp_to_level(current_xp)
        new_level = max(0, current_level - levels)
        new_xp = self.level_to_xp(new_level)
        self.set_xp(guild_id, user_id, new_xp)
        await ctx.send(f"✅ Removed {levels} levels from {member.display_name}. Now level {new_level}.")

    @commands.command()
    async def leaderboard(self, ctx):
        guild_id = str(ctx.guild.id)
        if guild_id not in self.levels or not self.levels[guild_id]:
            return await ctx.send("No leveling data available.")
        sorted_users = sorted(self.levels[guild_id].items(), key=lambda x: x[1], reverse=True)
        top = sorted_users[:10]
        embed = discord.Embed(title="🏆 Level Leaderboard", color=discord.Color.gold())
        for i, (user_id, xp) in enumerate(top, start=1):
            member = ctx.guild.get_member(int(user_id))
            name = member.display_name if member else f"User ID {user_id}"
            level = self.xp_to_level(xp)
            embed.add_field(name=f"#{i} - {name}", value=f"Level {level} ({xp} XP)", inline=False)
        await ctx.send(embed=embed)

# ---------------- Polls Cog ---------------- #
class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def poll(self, ctx, *, question):
        message = await ctx.send(f"📊 **Poll:** {question}")
        await message.add_reaction("👍")
        await message.add_reaction("👎")
        await ctx.send("✅ Poll created! React with 👍 or 👎.")

# ---------------- VoiceChannels Cog ---------------- #
class VoiceChannels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Placeholder: add your voice channel related commands here
    @commands.command()
    async def join(self, ctx):
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
            await ctx.send(f"Joined {channel.name}!")
        else:
            await ctx.send("You must be in a voice channel first!")

    @commands.command()
    async def leave(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Left the voice channel.")
        else:
            await ctx.send("I'm not in a voice channel!")

# ---------------- AutoMod Cog ---------------- #
class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        # Simple automod example: delete messages with banned words
        banned_words = ["badword1", "badword2"]  # replace with your list
        if any(word in message.content.lower() for word in banned_words):
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention}, that word is not allowed here!", delete_after=5)

async def main():
    await bot.add_cog(Moderation(bot))
    await bot.add_cog(Fun(bot))
    await bot.add_cog(ActivityWatcher(bot))
    await bot.add_cog(CustomVC(bot))
    await bot.add_cog(Leveling(bot))
    await bot.add_cog(Polls(bot))
    await bot.add_cog(VoiceChannels(bot))
    await bot.add_cog(AutoMod(bot))

    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("ERROR: Please set your DISCORD_TOKEN environment variable.")
        return

    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
