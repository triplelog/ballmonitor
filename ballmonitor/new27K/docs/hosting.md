# Hosting 27K for other people

The server (`npm run serve`, i.e. `node tools/serve.js`) is the whole thing:
it serves the game and runs the multiplayer API. It has no dependencies and
keeps multiplayer games as JSON files, so hosting it is small.

## Settings

| Variable | Default | |
| --- | --- | --- |
| `PORT` | 8027 | |
| `HOST` | every interface | Use `127.0.0.1` when a reverse proxy sits in front. |
| `MP_DATA_DIR` | `data/mp` | Where games are kept: put it on a disk that's backed up. |
| `TRUST_PROXY` | off | Set to `1` behind a proxy so rate limits see real addresses. |
| `ALLOW_ORIGINS` | none | Other sites whose copy of the game may use this server's multiplayer, comma-separated: `https://ballmonitor.com,https://html-classic.itch.zone`. See *One server, several copies of the game*. |
| `ADMIN_TOKEN` | off | Enables `GET /api/mp/admin/games/<id>/pitches?token=…`, every pitch's inputs, for looking into a game. |

## The live server: 27k.ballmonitor.com

It runs on the shared Vultr box (64.177.56.111, with rnbqkbnr, gifsaw,
csshole and the digitizer.fun games server), behind that box's shared Caddy.

| | |
| --- | --- |
| Code | `/srv/ballmonitor-27k` (the game folder minus `dist/`, `docs/`, `test/`), owned by rwilcox |
| Runs as | system user `ballmonitor-27k`, unit `ballmonitor-27k.service`, `127.0.0.1:3004` |
| Games | `/var/lib/ballmonitor-27k/*.json` (back up with `scp`) |
| Caddy | `/etc/caddy/sites/27k.caddy` (`deploy/27k.caddy`): `/api/mp/*` to the server, anything else redirected to ballmonitor.com/27k/ |
| Allowed sites | `ALLOW_ORIGINS` in `deploy/ballmonitor-27k.service`: ballmonitor.com and itch.io's game frames |
| Secrets | optional `/etc/ballmonitor-27k.env` (`ADMIN_TOKEN=…`) |

**Deploy** from your computer, in a terminal (sudo asks for the password):
`deploy/deploy.sh`. The first run creates the folder, user and unit and
installs the Caddy site (`deploy/install.sh`); later runs copy the code,
`npm ci`, restart, and reload Caddy only if `27k.caddy` changed and the whole
config validates (otherwise the old file is put back, so the other sites keep
working). Never replace the shared `/etc/caddy/Caddyfile` or change ufw from
here.

**Check:** `curl https://27k.ballmonitor.com/api/mp/ping` gives `{"ok":true}`.
Status `systemctl status ballmonitor-27k`, errors `journalctl -u ballmonitor-27k -e`.

**Take it down:** `sudo systemctl disable --now ballmonitor-27k`,
`sudo rm /etc/caddy/sites/27k.caddy`,
`sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy`.

## Option 1: friends only, from your own computer (easiest)

- **Same network**: run `npm run serve`; share the "on your network" address it prints.
- **Anywhere, privately**: install [Tailscale](https://tailscale.com) on your computer and your friends' devices (or share the machine to them) and use its Tailscale address. Nothing is exposed to the internet.
- **Anywhere, by link**: a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (`cloudflared tunnel --url http://localhost:8027`) gives you an `https://…` address without opening ports. Run the server with `HOST=127.0.0.1 TRUST_PROXY=1`.

Your computer has to be on for people to play, and games live on it.

## Option 2: a small server (recommended for hosting regularly)

Any $4–6/month VPS (Hetzner, DigitalOcean, Linode…) or a container host
(Fly.io, Railway, Render with a persistent volume) is plenty: a game is a
few hundred KB, and a pitch is a few milliseconds of work.

With Docker:

```bash
docker build -t 27k .
docker run -d --restart unless-stopped -p 127.0.0.1:8027:8027 \
  -e TRUST_PROXY=1 -e ADMIN_TOKEN=$(openssl rand -hex 16) \
  -v 27k-data:/data --name 27k 27k
```

Or without Docker, as a systemd service (`/etc/systemd/system/27k.service`):

```ini
[Unit]
Description=27K
After=network.target

[Service]
WorkingDirectory=/opt/27k
ExecStart=/usr/bin/node tools/serve.js
Environment=HOST=127.0.0.1 PORT=8027 TRUST_PROXY=1 MP_DATA_DIR=/var/lib/27k
User=www-data
Restart=always

[Install]
WantedBy=multi-user.target
```

Put [Caddy](https://caddyserver.com) in front for HTTPS (it gets certificates by itself). `/etc/caddy/Caddyfile`:

```
27k.example.com {
    reverse_proxy 127.0.0.1:8027
}
```

Use HTTPS: the player id each browser sends is its password, and plain
HTTP would let anyone on the same Wi-Fi read it.

Games nobody has touched for a month (finished, never joined, or abandoned)
are deleted, at start-up and every hour. Back up `MP_DATA_DIR` (a nightly copy is enough). To update, replace the
files and restart; games in progress carry on.

## One server, several copies of the game

The game can live on static hosts (ballmonitor.com/27k/, itch.io) and use
one multiplayer server somewhere else.

1. **Tell each static copy where the server is** when you build it. The
   defaults are the live ones (`https://27k.ballmonitor.com`, invites to
   `https://ballmonitor.com/27k/`), so `npm run build` and `npm run itch`
   need nothing; to point a build elsewhere:

   ```bash
   MP_SERVER=https://27k.example.com INVITE_PAGE=https://example.com/27k/ npm run build   # MP_SERVER= for none
   ```

   `MP_SERVER` is the server's address. `INVITE_PAGE` is the page invite
   links open; set it to a page anyone can open (itch runs the game in a
   frame whose own address is no use to a friend). Both are written into
   `dist/src/config.js`. Without `MP_SERVER`, a static copy has no
   multiplayer and the menu shows it as *coming later*.
2. **Tell the server which sites may use it:**
   `ALLOW_ORIGINS=https://ballmonitor.com,https://html-classic.itch.zone`.
   Use the address of the page the game actually runs on: for itch that is
   the game frame's address (open the game on itch, look at the frame's
   address in the browser's developer tools), not `itch.io` itself.
3. The game asks the server once whether it is there (`/api/mp/ping`); if
   it answers, Multiplayer appears on the menu.

`node test/serve.js` checks the permissions; a whole game was played
between two browsers on a static copy at one address and the server at
another (2026-11-12).

## Cheating: what's handled, what isn't

**Handled by the server** (since the multiplayer referee change):

- **Outcomes**: browsers send only inputs (pitch, effort, aim, time); the server runs the engine. A player can't edit the score, the count, or a result.
- **Dice**: the random-number state never leaves the server, so a player can't work out in advance which aim gives a hit or an out.
- **Retries**: each move must quote the game's current version; replays and double-sends are refused.
- **Rules**: lineups (nine players, one per position, only before the team bats), substitutions (bench players only; no re-entry), pitching changes (available arms, pitch limits) and pitch inputs (effort 0–100, aim within reach) are all checked.
- **Turns and time**: only the player whose turn it is can move; time limits are kept by the server's clock.
- **Identity**: player ids are never shown to anyone else (not in game data, not in URLs), so a player can't act as their opponent.
- **Abuse**: request size limits and a per-address rate limit.
- **Evidence**: every pitch's inputs are logged (`ADMIN_TOKEN` to read them).

**Not handled** (the limits of a skill game played in a browser):

- **Aim assistance.** The moving zone runs in the browser, which has to know where the zone is to draw it, so a modified client (or a script) could click perfectly every time. You can't stop that outright; you can make it noticeable:
  - look at the pitch log: superhuman consistency, identical timings, or aims that always land exactly on an edge;
  - a later improvement: the server picks each pitch's zone path, the browser reports only the click time and position, and the server works out the aim. That stops casual tampering (and lets the server check click timing), though a determined bot could still compute the perfect click.
- **The pitch clock** is kept by the browser; the server only knows the turn's time limit. (It does reject absurd values.)
- **Multiple identities.** A player id is just a browser's random secret. For a public site you'd want sign-in (email magic links or "Sign in with Google/GitHub"), which would also let players switch devices and keep their games.
- **Custom formulas.** A game created with "My custom formulas" plays by the creator's rules; the joining player should check them (a future improvement: show the rules on the join screen and require both players to accept).

For games among friends, what's in place is plenty. For a public, ranked
site, add sign-in, have the server generate the zone, and review the pitch
logs of top players.
