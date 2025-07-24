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
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_warnings(data):
    with open(WARN_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_ip_bans():
    try:
        with open(IP_BAN_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_ip_bans(data):
    with open(IP_BAN_FILE, "w") as f:
        json.dump(data, f, indent=4)

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

class ActivityWatcher(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.watch_data = {}

    @commands.command()
    async def watch(self, ctx, friend: discord.Member):
        self.watch_data[ctx.author.id] = friend.id
        await ctx.send(f"📡 Now watching {friend.display_name}'s activities for {ctx.author.display_name}.")

    @commands.command()
    async def unwatch(self, ctx):
        if ctx.author.id in self.watch_data:
            del self.watch_data[ctx.author.id]
            await ctx.send("❌ Stopped watching anyone.")
        else:
            await ctx.send("You weren't watching anyone.")

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        for watcher_id, friend_id in self.watch_data.items():
            if after.id == friend_id:
                watcher = self.bot.get_user(watcher_id)
                if watcher:
                    # Send a DM to watcher about friend's activity change
                    before_activities = {a.type: a.name for a in before.activities} if before else {}
                    after_activities = {a.type: a.name for a in after.activities} if after else {}
                    if before_activities != after_activities:
                        msg = f"👀 Your friend **{after.display_name}** updated their activities:\n"
                        msg += "\n".join(f"- {k.name}: {v}" for k, v in after_activities.items())
                        try:
                            await watcher.send(msg)
                        except discord.Forbidden:
                            pass

# ---------------- CUSTOM VOICE CHANNELS COG ---------------- #
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


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.levels = {}  # {guild_id: {user_id: xp}}

    def add_xp(self, guild_id, user_id, amount=5):
        self.levels.setdefault(str(guild_id), {}).setdefault(str(user_id), 0)
        self.levels[str(guild_id)][str(user_id)] += amount

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        self.add_xp(message.guild.id, message.author.id)
        # Optionally save to file here for persistence

    @commands.command()
    async def level(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        xp = self.levels.get(str(ctx.guild.id), {}).get(str(member.id), 0)
        level = int(xp ** 0.5)  # Example level calc
        await ctx.send(f"⭐ {member.display_name} is level {level} with {xp} XP.")

class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def poll(self, ctx, *, question):
        embed = discord.Embed(title="📊 Poll", description=question, color=discord.Color.blue())
        message = await ctx.send(embed=embed)
        await message.add_reaction("👍")
        await message.add_reaction("👎")

class VoiceChannels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Placeholder for voice channel management commands

class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # Simple example: delete message if it contains banned words
        banned_words = ["badword1", "badword2"]
        if any(word in message.content.lower() for word in banned_words):
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention}, your message contained a banned word.")
            except discord.Forbidden:
                pass

async def main():
    await bot.add_cog(Moderation(bot))
    await bot.add_cog(Fun(bot))
    await bot.add_cog(ActivityWatcher(bot))
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
