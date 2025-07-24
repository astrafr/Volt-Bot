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
from discord.utils import get

# --- Simple keep_alive webserver embedded ---
from aiohttp import web

async def handle(request):
    return web.Response(text="Bot is alive!")

def keep_alive():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    loop.run_until_complete(site.start())

# --- Bot setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=",", intents=intents, help_command=None)

# --- Files for persistence ---
WARN_FILE = "warnings.json"
IP_BAN_FILE = "ip_bans.json"
LEVELS_FILE = "levels.json"

def load_json(file):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except:
        return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

# ---------------- MODERATION COG ---------------- #
class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def log_action(self, ctx, action: str, target: Union[discord.Member, str], reason: str):
        channel = get(ctx.guild.text_channels, name="mod-logs")
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
        role = get(ctx.guild.roles, name="Muted")
        if not role:
            return await ctx.send("❌ No 'Muted' role found.")
        await member.add_roles(role)
        await ctx.send(f"🔇 Muted {member} | Reason: {reason}")
        await self.log_action(ctx, "Mute", member, reason)

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member):
        role = get(ctx.guild.roles, name="Muted")
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
        warnings = load_json(WARN_FILE)
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        warnings.setdefault(guild_id, {}).setdefault(user_id, []).append(reason)
        save_json(WARN_FILE, warnings)
        try:
            await member.send(f"⚠️ You have been warned in **{ctx.guild.name}**.\n**Reason:** {reason}")
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM the user.")
        await ctx.send(f"⚠️ Warned {member.mention} | Reason: {reason}")
        await self.log_action(ctx, "Warn", member, reason)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warnings(self, ctx, member: discord.Member):
        warnings = load_json(WARN_FILE)
        user_warnings = warnings.get(str(ctx.guild.id), {}).get(str(member.id), [])
        if not user_warnings:
            return await ctx.send(f"✅ {member.display_name} has no warnings.")
        warning_list = "\n".join([f"{i+1}. {r}" for i, r in enumerate(user_warnings)])
        embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", description=warning_list, color=discord.Color.orange())
        await ctx.send(embed=embed)

    @commands.command(aliases=["delwarn", "clearwarn"])
    @commands.has_permissions(manage_messages=True)
    async def removewarn(self, ctx, member: discord.Member, index: int = None):
        warnings = load_json(WARN_FILE)
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
        save_json(WARN_FILE, warnings)
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
        ip_bans = load_json(IP_BAN_FILE)
        ip_bans[ip] = {
            "user_id": member.id,
            "reason": reason,
            "moderator": ctx.author.id
        }
        save_json(IP_BAN_FILE, ip_bans)
        await member.ban(reason=f"IP Ban: {reason}")
        await ctx.send(f"🚫 IP `{ip}` associated with {member} has been banned.\nReason: {reason}")
        await self.log_action(ctx, "IP Ban", f"{member} (IP: {ip})", reason)

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unipban(self, ctx, ip: str):
        ip_bans = load_json(IP_BAN_FILE)
        if ip in ip_bans:
            removed = ip_bans.pop(ip)
            save_json(IP_BAN_FILE, ip_bans)
            await ctx.send(f"✅ IP `{ip}` unbanned. Previously linked to user ID {removed['user_id']}.")
            await self.log_action(ctx, "Un-IP Ban", ip, "Manual unban")
        else:
            await ctx.send("❌ That IP isn’t currently banned.")

    @commands.command()
    async def ipbans(self, ctx):
        ip_bans = load_json(IP_BAN_FILE)
        if not ip_bans:
            return await ctx.send("✅ No IPs are currently banned.")
        ban_list = "\n".join([f"`{ip}` - User ID: {data['user_id']} (Reason: {data['reason']})" for ip, data in ip_bans.items()])
        embed = discord.Embed(title="🚫 IP Ban List", description=ban_list, color=discord.Color.red())
        await ctx.send(embed=embed)

# ---------------- FUN COG ---------------- #
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
            await ctx.send(f"❌ Error converting image: {e}")

# ---------------- ACTIVITY WATCHER COG ---------------- #
class ActivityWatcher(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.watch_data = {}

    @commands.command()
    async def watch(self, ctx, friend: discord.Member):
        self.watch_data[ctx.author.id] = friend.id
        await ctx.send(f"📡 Now watching {friend.display_name}. You’ll be DM’d when they talk.")

    @commands.command()
    async def unwatch(self, ctx):
        if ctx.author.id in self.watch_data:
            del self.watch_data[ctx.author.id]
            await ctx.send("🛑 No longer watching anyone.")
        else:
            await ctx.send("❌ You're not watching anyone.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        for watcher_id, watched_id in self.watch_data.items():
            if message.author.id == watched_id:
                watcher = self.bot.get_user(watcher_id)
                if watcher:
                    try:
                        await watcher.send(
                            f"👀 {message.author.display_name} just sent a message in #{message.channel.name} on **{message.guild.name}**."
                        )
                    except discord.Forbidden:
                        print(f"Could not DM {watcher.name}")

    @commands.command()
    async def testdm(self, ctx):
        try:
            await ctx.author.send("✅ This is a test DM!")
            await ctx.send("Sent you a DM!")
        except:
            await ctx.send("❌ I couldn't DM you. Check your settings.")

# ---------------- LEVELING SYSTEM ---------------- #
class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.levels = load_json(LEVELS_FILE)

    def save(self):
        save_json(LEVELS_FILE, self.levels)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        self.levels.setdefault(guild_id, {}).setdefault(user_id, {"xp":0, "level":1})
        user_data = self.levels[guild_id][user_id]
        user_data["xp"] += random.randint(5, 15)  # Random XP per message
        xp_to_next = 5 * (user_data["level"] ** 2) + 50 * user_data["level"] + 100
        if user_data["xp"] >= xp_to_next:
            user_data["level"] += 1
            await message.channel.send(f"🎉 {message.author.mention} leveled up to **{user_data['level']}**!")
        self.save()

    @commands.command()
    async def level(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        user_data = self.levels.get(guild_id, {}).get(user_id, {"xp":0, "level":1})
        await ctx.send(f"📊 {member.display_name} is level **{user_data['level']}** with **{user_data['xp']} XP**.")

    @commands.command()
    async def leaderboard(self, ctx):
        guild_id = str(ctx.guild.id)
        if guild_id not in self.levels:
            return await ctx.send("No leveling data for this server.")
        leaderboard = sorted(self.levels[guild_id].items(), key=lambda x: x[1]["xp"], reverse=True)[:10]
        embed = discord.Embed(title=f"🏆 Leaderboard for {ctx.guild.name}", color=discord.Color.gold())
        for i, (user_id, data) in enumerate(leaderboard, start=1):
            user = ctx.guild.get_member(int(user_id))
            embed.add_field(name=f"{i}. {user.display_name if user else 'Unknown User'}", value=f"Level {data['level']} - {data['xp']} XP", inline=False)
        await ctx.send(embed=embed)

# ---------------- POLL COMMANDS ---------------- #
class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def poll(self, ctx, *, question_and_options):
        # Example input: "Best color?; Red; Blue; Green"
        parts = question_and_options.split(";")
        if len(parts) < 2:
            return await ctx.send("❌ Use: `,poll Question; Option1; Option2; ...`")
        question = parts[0].strip()
        options = [opt.strip() for opt in parts[1:] if opt.strip()]
        if not (2 <= len(options) <= 10):
            return await ctx.send("❌ Provide between 2 and 10 options.")
        description = ""
        reactions = []
        emojis = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟']
        for i, option in enumerate(options):
            description += f"{emojis[i]} {option}\n"
            reactions.append(emojis[i])
        embed = discord.Embed(title=f"📊 {question}", description=description, color=discord.Color.blue())
        poll_msg = await ctx.send(embed=embed)
        for r in reactions:
            await poll_msg.add_reaction(r)

# ---------------- VOICE CHANNELS AUTO MANAGE ---------------- #
class VoiceChannels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_voice_channels = {}  # {guild_id: {channel_id: creator_id}}

    @commands.command()
    async def createvc(self, ctx, *, name="Temporary Voice"):
        """Create a temporary voice channel."""
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
            ctx.author: discord.PermissionOverwrite(manage_channels=True)
        }
        channel = await ctx.guild.create_voice_channel(name, overwrites=overwrites)
        self.temp_voice_channels.setdefault(str(ctx.guild.id), {})[str(channel.id)] = ctx.author.id
        await ctx.send(f"✅ Created voice channel {channel.mention}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not before.channel and after.channel:
            # Joined a channel
            pass
        elif before.channel and not after.channel:
            # Left a channel, check if it's a temp vc and empty
            guild_id = str(before.channel.guild.id)
            channel_id = str(before.channel.id)
            if guild_id in self.temp_voice_channels and channel_id in self.temp_voice_channels[guild_id]:
                channel = before.channel
                if len(channel.members) == 0:
                    try:
                        await channel.delete()
                        self.temp_voice_channels[guild_id].pop(channel_id)
                    except:
                        pass

# ---------------- AUTOMOD COG ---------------- #
class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bad_words = {"badword1", "badword2", "badword3"}
        self.anti_link = True
        self.spam_tracker = {}  # {user_id: [timestamps]}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        # Check bad words
        if any(word in message.content.lower() for word in self.bad_words):
            try:
                await message.delete()
                await message.channel.send(f"❌ {message.author.mention}, please do not use bad language.")
            except:
                pass
        # Check links if anti_link enabled
        if self.anti_link and "http" in message.content.lower():
            try:
                await message.delete()
                await message.channel.send(f"❌ {message.author.mention}, links are not allowed.")
            except:
                pass
        # Spam detection
        user_id = message.author.id
        now = discord.utils.utcnow().timestamp()
        timestamps = self.spam_tracker.get(user_id, [])
        timestamps = [t for t in timestamps if now - t < 5]  # keep last 5 seconds only
        timestamps.append(now)
        self.spam_tracker[user_id] = timestamps
        if len(timestamps) > 5:
            try:
                await message.delete()
                await message.channel.send(f"⚠️ {message.author.mention}, please stop spamming.")
            except:
                pass

# ---------------- HELP COMMAND ---------------- #
@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Help Menu", color=discord.Color.green())
    embed.add_field(name="Moderation", value="ban, unban, kick, mute, unmute, warn, warnings, removewarn, timeout, untimeout, clear, slowmode, lock, unlock, say", inline=False)
    embed.add_field(name="Fun", value="joke, eightball, rizz, flip, roll, roast, compliment, saydumb, mathmeme, rate, hacker, rps, emoji, spamemoji, to_gif", inline=False)
    embed.add_field(name="Activity", value="watch, unwatch, testdm", inline=False)
    embed.add_field(name="Leveling", value="level, leaderboard", inline=False)
    embed.add_field(name="Polls", value="poll", inline=False)
    embed.add_field(name="Voice", value="createvc", inline=False)
    await ctx.send(embed=embed)

# --- Register cogs ---
bot.add_cog(Moderation(bot))
bot.add_cog(Fun(bot))
bot.add_cog(ActivityWatcher(bot))
bot.add_cog(Leveling(bot))
bot.add_cog(Polls(bot))
bot.add_cog(VoiceChannels(bot))
bot.add_cog(AutoMod(bot))

# --- Events ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print("Bot is ready!")

@bot.event
async def on_command(ctx):
    print(f"Command invoked: {ctx.command} by {ctx.author}")

# --- Run keep_alive and start bot ---
keep_alive()

token = os.getenv("DISCORD_TOKEN")
if not token:
    print("❌ DISCORD_TOKEN not found in environment variables.")
else:
    bot.run(token)
