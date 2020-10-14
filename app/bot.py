import asyncio
import os
import discord
import youtube_dl
from discord import ClientException
from discord.ext import commands
import requests


# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ''


ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.directing = False
        self.cam_stats = {"live": "",
                              "queued": ""}
        self.new_cam_stats = {"live": "",
                              "queued": ""}

    @commands.command()
    async def join(self, ctx, *, channel: discord.VoiceChannel):
        """Joins a voice channel"""
        print(channel.id)
        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        await channel.connect()

    @commands.command()
    async def play(self, ctx, *, query, **kwargs):
        """Plays a file from the local filesystem"""

        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(query))
        ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)
        if kwargs['disconnect']:

            not_done = True
            while not_done:
                try:
                        ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)
                        await ctx.voice_client.disconnect()
                        not_done = False
                except ClientException:
                    await asyncio.sleep(1)  # task runs every 60 seconds

        if kwargs['notify']:
            await ctx.send('Now playing: {}'.format(query))

    @commands.command()
    async def direct(self, ctx):
        self.directing = not self.directing
        try:
            if self.directing:
                await self.join(ctx=ctx, channel=ctx.author.voice.channel)
                await self.play(ctx, query='sounds/directorIsOn.mp3', notify=False, disconnect=False)
            else:
                await self.play(ctx, query='sounds/directorIsOff.mp3', notify=False, disconnect=True)
                return
        except AttributeError:
            self.directing = False
            await ctx.send(f"Can not start directing until {ctx.author} is in a voice channel.\n"
                           f"```Whoever issues the !direct command has to be in a voice channel first.```")
            return

        await ctx.send(f"Director is {self.directing}")
        while self.directing:
            response = requests.request('GET', os.environ.get('CAM_API_URL'))
            new_cam_stats = response.json()
            if self.cam_stats != new_cam_stats:
                if new_cam_stats['live'] != self.cam_stats['live']:
                    await self.cam_announce(ctx, f'{new_cam_stats["live"]+"Live"}')
                else:
                    print("Announce Que Change")
                    await self.cam_announce(ctx, f'{new_cam_stats["queued"]+"Queue"}')
                self.cam_stats = new_cam_stats
            await asyncio.sleep(1)  # task runs every 60 seconds

    @commands.command()
    async def cam_announce(self, ctx, cam_announecment):
        """Plays a file from the local filesystem"""
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(f'sounds/{cam_announecment}.mp3'))
        for i in range(3):
            try:
                ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)
                break
            except ClientException:
                await asyncio.sleep(1)  # task runs every 60 seconds


        # await ctx.send(f'Now playing: {cam_announecment}.mp3')


    @commands.command()
    async def yt(self, ctx, *, url):
        """Plays from a url (almost anything youtube_dl supports)"""

        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('Now playing: {}'.format(player.title))

    @commands.command()
    async def stream(self, ctx, *, url):
        """Streams from a url (same as yt, but doesn't predownload)"""

        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('Now playing: {}'.format(player.title))

    @commands.command()
    async def volume(self, ctx, volume: int):
        """Changes the player's volume"""

        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send("Changed volume to {}%".format(volume))

    @commands.command()
    async def stop(self, ctx):
        """Stops and disconnects the bot from voice"""

        await ctx.voice_client.disconnect()

    @play.before_invoke
    @yt.before_invoke
    @stream.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()


bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"),
                   description='Relatively simple music bot example')

@bot.event
async def on_ready():
    print('Logged in as {0} ({0.id})'.format(bot.user))
    print('------')

bot.add_cog(Music(bot))
bot.run(os.environ.get('BOT_TOKEN'))
