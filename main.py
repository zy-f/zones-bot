import json
import asyncio
import datetime
import aiohttp
import os
import datetime

import discord
from discord.ext import commands, tasks
from addict import Dict as dotdict
import aiofiles

REQUEST_URL = "https://splatoon3.ink/data/schedules.json"
MODES = ["Bankara", "BankaraOpen", "X"]
REVERSE_MODE_MAP = {'x': "X", 'open': 'BankaraOpen', 'series': 'Bankara'}
LETTERS = 'abcdefghijkl'

SUB_FILE = ".subscribers.json"

async def load_subscribers():
    if not os.path.exists(SUB_FILE):
        return {}
    async with aiofiles.open(SUB_FILE, "r") as fh:
        data = await fh.read()
        return json.loads(data)


async def save_subscribers(users):
    data = json.dumps(users, indent=2)
    async with aiofiles.open(SUB_FILE, "w") as fh:
        await fh.write(data)


async def get_rot_data():
    async with aiohttp.ClientSession() as session:
        async with session.get(REQUEST_URL) as res:
            if res.status != 200:
                print("Failed to fetch schedules.json")
                return []
            data = await res.json()
            rotations = data.get("normal", [])
            return [dotdict(r) for r in rotations]
        
with open('.config.json', 'r') as fh:
    cfg = dotdict(json.load(fh))

with open('splatoon_data.json', 'r') as fh:
    spl_id_map = dotdict(json.load(fh))
    for i in spl_id_map.stages:
        spl_id_map.stages[i] = spl_id_map.stages[i].split(' ')[0]

# IMPORTANT: Enable 'Message Content Intent' in Discord Developer Portal
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)


async def build_zones_message(modes):
    rotations = await get_rot_data()
    out_data = []

    now = datetime.datetime.utcnow()
    cutoff = now + datetime.timedelta(hours=24)

    for r in rotations:
        start_time = datetime.datetime.fromisoformat(r.startTime.replace("Z", "+00:00"))
        if start_time > cutoff:
            continue  # only next 24 hours

        sz = None
        for m in modes:
            if r[m].rule == "Area":
                sz = dotdict(
                    mode=spl_id_map.modes[m],
                    stages=[spl_id_map.stages[str(i)] for i in r[m].stages]
                )
                break

        if sz is not None:
            unix_time = int(start_time.timestamp())
            out_data.append(
                f"{LETTERS[len(out_data)]}) <t:{unix_time}:t> - {sz.mode} - {sz.stages[0]} / {sz.stages[1]}"
            )

    if out_data:
        return "Zones rotations in the next 24 hours:\n" + "\n".join(out_data)
    return "No zones rotations found for the next 24H."


@bot.event
async def on_ready():
    print(f'{bot.user} connected')
    # Set the bot's status and activity
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=".zones (x, series, open)"
        )
    )

    if not daily_dm_task.is_running():
        daily_dm_task.start()


@bot.command(brief="show zones rotations", help="shows next 24H of rotations; specify x/open/series separated by spaces")
async def zones(ctx, *modes):
    if not modes:
        modes = MODES
    else:
        true_modes = []
        for m in modes:
            if not m.lower() in REVERSE_MODE_MAP:
                await ctx.send(f"{m} is not a valid mode -- valid modes are {list(REVERSE_MODE_MAP.keys())}.")
                return
            true_modes.append(REVERSE_MODE_MAP[m.lower()])
        modes = true_modes
    try:
        msg = await build_zones_message(modes)
        await ctx.send(msg)
    except Exception as e:
        print("zones failed:", e)


@bot.command(brief="sub for daily rotation notif; use @time to specify hour")
async def sub(ctx, time=""):
    try:
        time = time.strip()
        if not (time.startswith('<t:') and time.endswith('>')):
            time = 0
        else: # parse timestamp
            start = len('<t:')
            end = time.find(':', start)
            time = int(time[start:end])
        hour = datetime.datetime.utcfromtimestamp(time).hour
        users = await load_subscribers()
        uid = str(ctx.author.id)
        users[uid] = hour
        await save_subscribers(users)
        await ctx.send(f"Subscribed for notifs daily at <t:{time}:t>.")
    except Exception as e:
        print("sub failed:", e)


@bot.command(brief="unsubscribe from daily notifs, if subbed")
async def unsub(ctx):
    try:
        users = await load_subscribers()
        uid = str(ctx.author.id)
        if uid in users:
            users.pop(uid)
            await save_subscribers(users)
            await ctx.send("Unsubscribed.")
        else:
            await ctx.send("Already not subscribed.")
    except Exception as e:
        print("unsub failed:", e)



task_times = [datetime.time(hour=i, tzinfo=datetime.timezone.utc) \
    for i in range(24)]

@tasks.loop(time=task_times)
async def daily_dm_task():
    cur_hour = datetime.datetime.now(datetime.timezone.utc).hour
    users = await load_subscribers()
    if not users:
        return
    try:
        msg = await build_zones_message(MODES)
    except Exception as e:
        print("something happened: ", e)
        return
    for user_id, user_hour in users.items():
        if user_hour != cur_hour:
            continue
        try:
            uid = int(user_id)
            user = await bot.fetch_user(uid)
            await user.send(msg)
        except Exception as e:
            print(f"failed to DM {user_id}:", e)

bot.run(cfg.token)
