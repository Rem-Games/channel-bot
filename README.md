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

Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN`. `DISCORD_GUILD_ID` is optional, but recommended while developing because guild command sync is immediate for that server. `.env` contains secrets and should never be committed.

`DISCORD_GUILD_ID` only controls where slash commands are synced quickly. It does not change how runtime settings are stored. Runtime bot settings are stored per Discord server ID, so one server's command channel, rotation channels, candidate names, interval, and rotation mode do not apply to another server.

If you want the same bot application to be usable in multiple servers, leave `DISCORD_GUILD_ID` blank and use global command sync. Global slash commands can take longer to appear or update in Discord.

`.venv` is different from `.env`. `.venv` is a generated Python virtual environment directory that contains Python executables and installed packages. It is OS-specific:

- Linux/WSL uses `.venv/bin/python`
- Windows uses `.venv\Scripts\python.exe`

A `.venv` created on Linux/WSL will not run as a native Windows service, and a Windows `.venv` will not run as a Linux systemd service.

Linux/WSL setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m remchannelbot
```

Windows PowerShell setup:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m remchannelbot
```

Python 3.13 and newer require the `audioop-lts` compatibility package, which is included in `requirements.txt`.

If startup fails with `403 Forbidden (error code: 50001): Missing Access` while syncing commands, check `DISCORD_GUILD_ID` and reinvite the bot. That error usually means the configured guild ID is not the target server ID, or the bot was not invited to that server with both `bot` and `applications.commands` scopes.

## First Use

After inviting the bot, run:

```text
/remchannel setup command-channel:#your-admin-channel
```

After setup, all operational commands must be run in that command channel.

## Commands

- `/remchannel setup command-channel` - choose the channel used for bot commands and bot responses.
- `/remchannel interval minutes` - set the rotation interval.
- `/remchannel mode mode` - switch between one-channel rotation and all-channel rotation.
- `/remchannel quiet enabled` - toggle scheduled rotation notices after setup/testing.
- `/remchannel rotation-add channel` - add a channel to the rotation.
- `/remchannel rotation-remove channel` - remove a channel from the rotation by channel, ID, or unique current name.
- `/remchannel rotation-list` - list configured channels with current names and IDs.
- `/remchannel name-add name` - add a candidate channel name.
- `/remchannel name-remove name` - remove a candidate channel name.
- `/remchannel names-list page export` - list candidate names, paginated or as an attached text file.
- `/remchannel rotate-now` - immediately rotate the next configured channel.

## Notes

Discord requires the bot to have `Manage Channels` to rename guild channels. Discord also rate-limits API calls; this bot rotates one channel per interval and enforces a minimum interval of 10 minutes.

The default rotation mode updates one configured channel per interval. All-channel mode attempts to update every configured channel each interval. In either mode, the bot will not rename a channel to a candidate name already used by another configured rotation channel.

Quiet mode suppresses scheduled rotation messages in the configured command channel. Manual commands still respond so admins can see command results.

## Linux systemd Service

Create `.env`, create a Linux `.venv`, and install `requirements.txt` first:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then install the service:

```bash
scripts/linux/install-systemd.sh
sudo systemctl start remchannelbot
sudo systemctl status remchannelbot
```

Useful commands:

```bash
sudo systemctl stop remchannelbot
sudo systemctl restart remchannelbot
sudo journalctl -u remchannelbot -f
```

To remove it:

```bash
scripts/linux/uninstall-systemd.sh
```

## Windows Service

Windows needs a service wrapper because Python console apps do not implement the Windows Service Control Manager protocol directly. These scripts use NSSM.

Install NSSM, create `.env`, create a Windows `.venv`, and install `requirements.txt` first. A virtual environment created on Linux/WSL will not run as a native Windows service.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then run PowerShell as Administrator:

```powershell
.\scripts\windows\install-service.ps1
.\scripts\windows\start-service.ps1
Get-Service RemChannelBot
```

Useful commands:

```powershell
.\scripts\windows\stop-service.ps1
.\scripts\windows\start-service.ps1
.\scripts\windows\uninstall-service.ps1
```
