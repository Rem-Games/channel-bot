# Rem Channel Bot

A Discord bot that rotates configured channel names from an admin-managed candidate list.

## Features

- Slash-command administration only.
- Commands are restricted to the server owner or members with the Discord Administrator permission.
- A configured command channel gates operational commands and receives rotation notices.
- Rotates one configured channel per interval to avoid burst channel edits.
- JSON-backed state that can be backed up or moved with the bot.

## Discord Setup

Create an app in the Discord Developer Portal, then configure it for a server install:

- Scopes: `bot`, `applications.commands`
- Bot permissions: `Manage Channels`, `Send Messages`, `View Channels`
- Privileged intents: none required

Discord's bot guide starts at https://docs.discord.com/developers/platform/bots and the getting-started guide is at https://docs.discord.com/developers/quick-start/getting-started.

Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN`. `DISCORD_GUILD_ID` is optional, but recommended while developing because guild command sync is immediate for that server.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m remchannelbot
```

## First Use

After inviting the bot, run:

```text
/remchannel setup command-channel:#your-admin-channel
```

After setup, all operational commands must be run in that command channel.

## Commands

- `/remchannel setup command-channel` - choose the channel used for bot commands and bot responses.
- `/remchannel interval minutes` - set the rotation interval.
- `/remchannel rotation-add channel` - add a channel to the rotation.
- `/remchannel rotation-remove channel` - remove a channel from the rotation by channel, ID, or unique current name.
- `/remchannel rotation-list` - list configured channels with current names and IDs.
- `/remchannel name-add name` - add a candidate channel name.
- `/remchannel name-remove name` - remove a candidate channel name.
- `/remchannel names-list page export` - list candidate names, paginated or as an attached text file.
- `/remchannel rotate-now` - immediately rotate the next configured channel.

## Notes

Discord requires the bot to have `Manage Channels` to rename guild channels. Discord also rate-limits API calls; this bot rotates one channel per interval and enforces a minimum interval of 10 minutes.
