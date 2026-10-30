# Rem Channel Bot

A Discord bot for rotating channel names and running Secret Santa drawings.

## Features

- Slash-command administration only.
- Channel rotation commands are restricted to the server owner or members with the Discord Administrator permission.
- A configured command channel gates operational commands and receives rotation notices.
- Rotates one configured channel per interval to avoid burst channel edits.
- Candidate names can be selected fully randomly or exhaustively before repeats.
- Secret Santa drawings with Open, Closed, and Completed states, private giftee lookup, and completed results.
- Best-effort exclusions from up to three previous drawings, with private selection menus.
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

After setup, channel rotation commands must be run in that command channel. Configure the separate Secret Santa channel with `/santa-channel`.

## Commands

### Channel rotation

- `/remchannel setup command-channel` - choose the channel used for bot commands and bot responses.
- `/remchannel interval minutes` - set the rotation interval.
- `/remchannel mode mode` - switch between one-channel rotation and all-channel rotation.
- `/remchannel list-mode mode` - switch between fully random candidate selection and exhaustive selection.
- `/remchannel quiet enabled` - toggle scheduled rotation notices after setup/testing.
- `/remchannel rotation-add channel` - add a channel to the rotation.
- `/remchannel rotation-remove channel` - remove a channel from the rotation by channel, ID, or unique current name.
- `/remchannel rotation-list` - list configured channels with current names and IDs.
- `/remchannel name-add name` - add a candidate channel name.
- `/remchannel name-remove name` - remove a candidate channel name.
- `/remchannel names-list page export` - list candidate names, paginated or as an attached text file.
- `/remchannel rotate-now` - immediately rotate the next configured channel.

### Secret Santa

Run these commands in the channel configured with `/santa-channel`. Anyone in that
channel can create drawings, join, leave, look up their giftee, and view completed
results. Managing a drawing requires its creator or a server admin, except
`admin-leave`, which requires a server admin. Server admins include the server owner.

`[name]` means the name is optional: omit it to use the selection workflow below.

| Command | Purpose | State when name is omitted |
| --- | --- | --- |
| `/santa-channel command-channel` | Set the Secret Santa channel (admins only). | — |
| `/santa create name` | Create a named drawing. | — |
| `/santa delete [name]` | Delete after private confirmation (creator/admins). | Any |
| `/santa join [name]` | Join a drawing. | Open |
| `/santa leave [name]` | Leave a drawing. | Open |
| `/santa close [name]` | Assign giftees and close entry (creator/admins). | Open |
| `/santa completed [name]` | Mark the game finished (creator/admins). | Closed |
| `/santa giftee [name]` | Privately show your giftee; an explicit name also allows Completed drawings. | Closed |
| `/santa details [name]` | Privately show the completion time, participant count, and every pairing. | Completed |
| `/santa exclusion [name]` | Add previous completed drawings as exclusions (creator/admins). | Open |
| `/santa exclusion-remove [name]` | Remove exclusions (creator/admins). | Open |
| `/santa admin-leave name member` | Remove a participant in an emergency (admins only). Closed drawings are redrawn. | Name required; Open or Closed only |

#### Drawing lifecycle and timestamps

Drawings move forward through **Open → Closed → Completed**. Open drawings accept
participants and exclusion changes. Closing requires at least two participants and
assigns each participant one unique giftee, never themselves. Completing indicates
the game has been played; participants and pairings can no longer be changed.
Completed drawings can still be deleted by their creator or an admin.

The bot records creation, closing, and completion timestamps. Existing saved
`closed: false` drawings load as Open and `closed: true` drawings load as Closed,
with their assignments preserved. Missing historical timestamps stay unknown
until a state transition: closing fills a missing creation timestamp with the
closing time; completing fills any missing creation/closing timestamps with the
completion time. Existing timestamps are preserved. Emergency redraws through
`admin-leave` preserve the original closing timestamp, including an unknown one.

Anyone in the Santa channel can use `/santa details` for a Completed drawing.
It shows the completion time in the viewer's own timezone using Discord timestamp
formatting, followed by `Participant <x> drew <y>` for each participant. Results
are private to the requester and paginated to stay within the message length limit.

#### Choosing a drawing without a name

If exactly one drawing matches the command's state, the command behaves just as
if its name had been supplied, including existing permission and already-joined /
not-joined messages. If multiple drawings match, choices are filtered by management
permission or participation: join offers drawings you have not joined, and leave
and giftee offer drawings you have joined. If filtering leaves one choice, it is
used automatically. Joining when you have joined all Open drawings reports that;
leaving when you belong to none reports that as well.

Multiple eligible choices open a private menu with up to five drawings per page
and numbered selection buttons. Drawings are ordered by their current state's
timestamp, newest first; deletion uses each drawing's latest state's timestamp.
Missing timestamps come last, with alphabetical ordering for equal or missing
timestamps. Pagination uses **⬅️ Previous**, **Page X / Y**, and **Next ➡️**.
Only the requester can use the buttons. Menus expire after five minutes without
interaction; rerun the command to open another menu.

#### Exclusions from previous games

Use `/santa exclusion [name]` on an Open drawing to add snapshots of up to **three**
Completed drawings. The private conversation shows how many more can be added,
lists up to five choices ordered by completion time (newest first), and omits
already-added drawings. Each selection refreshes the menu; reaching three ends
the conversation. `/santa exclusion-remove [name]` lists the saved exclusions with
up to three selection buttons and refreshes as they are removed. Only the creator
or admins can change exclusions, and both conversations expire after five minutes
without interaction.

**We will try our best to avoid repeated pairings.** The draw first tries to avoid
every giver-to-giftee pairing from all selected games. If that is impossible, it
relaxes the oldest game's restrictions and tries again, continuing oldest-first
until a valid drawing exists. Even the most recent exclusion may be relaxed if
necessary. Self-pairings are never allowed. The closing/redraw response reports
which exclusions had to be relaxed; the saved exclusion list remains intact.
Without exclusions, assignments use the original fully random drawing behavior.
Only pairings involving participants present in the new drawing affect it.

Exclusions preserve a snapshot of the source name, completion time, and pairings.
Deleting a source drawing does not remove those restrictions, and creating another
drawing with the same name does not replace the snapshot. Snapshots belong to the
drawing that uses them: removing an exclusion or deleting that drawing removes
its stored copy, so no separate orphan-history cleanup is currently required.

## Notes

Discord requires the bot to have `Manage Channels` to rename guild channels. Discord also rate-limits API calls; this bot rotates one channel per interval and enforces a minimum interval of 10 minutes.

The default rotation mode updates one configured channel per interval. All-channel mode attempts to update every configured channel each interval. In either mode, the bot will not rename a channel to a candidate name already used by another configured rotation channel.

The default list mode is fully random. Exhaustive list mode tracks candidate names as they are chosen and will not choose a candidate again until every configured candidate name has been chosen once. If an all-channel rotation exhausts the last remaining candidate while updating multiple channels, the exhausted list resets immediately so the rest of that rotation can still pick valid names.

Quiet mode suppresses scheduled rotation messages in the configured command channel. Manual commands still respond so admins can see command results.

Secret Santa commands use their own configured channel. Joining, leaving, and giftee lookup
are available to participants in that channel. The giftee response is ephemeral so only the
requesting user can see it. A drawing must have at least two participants before it can be
closed, and assignments never match a participant to themselves.

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
