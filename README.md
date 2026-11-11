# Home media server with language choices

Plex playback, Sonarr/Radarr media management, Prowlarr sources, Bazarr subtitles,
and qBittorrent routed through Surfshark. A new language page shows whether your
files contain German, English, or Japanese audio and your chosen subtitles.
Caddy and Authelia protect the browser apps with HTTPS and a 30-day Remember Me
session. Redis persists sessions through container restarts.

## What language selection does

1. Open the media homepage and choose **German**, **English**, or **Japanese**.
2. Choose subtitles: English, German, Japanese, or Off. Japanese requires subtitles.
3. Pick a library and search for a movie or episode. Choose **Check languages**.
4. If a file version contains the requested tracks, choose **Use these tracks**,
   then **Open in Plex**. Select the matching version if Plex asks.

The page checks actual Plex stream metadata for every part of a file version.
It never combines audio from one version with subtitles from another. Full
subtitles are required; a forced-only track does not satisfy the subtitle choice.
Commentary and audio-description tracks do not count as a dub.

- **Available in your library:** the requested audio and subtitles were found.
- **German/English/Japanese audio is not available in your library:** no matching
  tagged audio track was found. No fallback is selected.
- **Subtitles are not available with this audio:** the audio exists, but the
  requested full subtitles are missing from that version.
- **Availability unknown:** audio or requested subtitles are untagged/unanalysed.
  If Plex cannot be reached, a connection error is shown separately and is never
  presented as a missing dub.

This cannot prove that an edition does not exist anywhere. It checks your own
library, not every streaming service or release source. It does not generate dubs,
translate audio, download missing tracks, or splice separately acquired audio.
Bazarr can fetch subtitles once you configure its providers.

**Plex remains the player.** The portal is for one connected Plex account. Saved
track selections apply to the account owning `PLEX_TOKEN`; use that same account
in Plex. Your browser remembers your language choice. Native Plex/TV apps retain
their own login and can override selections. During playback, the Plex player's
Audio & Subtitles controls also let you switch between existing tracks.

## First installation

Requires Linux Docker Engine, the Compose plugin **v2.20+**, Python 3, a Surfshark
subscription, and your own media/sources. Do this on the machine hosting the
server. No VPN credentials or Plex tokens belong in GitHub or in chat.

### 1. Configure the server address and VPN

```sh
cp .env.example .env
```

Edit `.env` locally:

- `MEDIA_DOMAIN`: a dedicated subdomain such as `media.home.arpa` (private LAN) or
  `media.example.com`. Resolve it and **auth, sonarr, radarr, prowlarr, bazarr,
  requests, downloads** beneath it to the server's LAN IP in your router's DNS.
  A hosts-file entry for each name also works for initial testing.
- Surfshark → VPN → Manual Setup → WireGuard: register/generate a key, download
  its configuration, and copy the **private key** and IPv4 **Address including
  CIDR** into `WIREGUARD_PRIVATE_KEY` and `WIREGUARD_ADDRESSES`.
- `VPN_COUNTRIES`: your preferred exit country; this does not determine audio.
- `PLEX_BIND_IP`: set to the server's LAN IP for TV/device access. It defaults to
  `127.0.0.1`, so Plex starts restricted to the server itself. Do not forward it
  from your router unless you deliberately configure authenticated Plex remote access.
- `PUID` / `PGID`: the user/group owning your media folders. `TZ` defaults to
  Europe/Luxembourg.

### 2. Create the password-protected account

```sh
python3 scripts/setup.py
```

The script tells you how to generate an Argon2 password hash interactively using
Authelia. Paste the digest locally. The script creates private, ignored config
files and random secrets, and refuses to overwrite an existing account.

Validate before starting:

```sh
docker compose config --quiet
docker compose run --rm --no-deps authelia authelia config validate --config /config/configuration.yml
docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose up -d --build
```

Caddy uses an **internal certificate authority** for LAN HTTPS. Copy
`provision/caddy/data/caddy/pki/authorities/local/root.crt` from the server and
trust that root certificate on each client device. Do not distribute its private
key or disable TLS verification. For a real public DNS name, replace `tls internal`
in `deploy/Caddyfile` with your preferred public certificate configuration.

Visit `https://MEDIA_DOMAIN`, sign in, and tick **Remember me**. The browser session
lasts up to 30 days, with persisted Redis storage. Without Remember Me, sessions
expire after 12 hours or 1 hour inactivity. Clearing cookies, logging out, or
revoking sessions requires a new login. App-native accounts are still required;
Authelia adds a shared front door, not universal single sign-on to every app.

### 3. Connect Plex and the management apps

Use an SSH tunnel for initial setup if these apps are not running on your desktop:

```sh
ssh -L 32400:127.0.0.1:32400 -L 8989:127.0.0.1:8989 -L 7878:127.0.0.1:7878 -L 9696:127.0.0.1:9696 -L 8080:127.0.0.1:8080 your-server
```

If `PLEX_BIND_IP` is your LAN IP, forward that LAN address for Plex instead.
Claim Plex at `http://localhost:32400/web` using its normal sign-in, or use a fresh
`PLEX_CLAIM` from https://plex.tv/claim on first launch. Add these library folders:

- Movies: `/data/media/movies`
- Series: `/data/media/tv`

Enable automatic library scanning. Add a Plex account token to `PLEX_TOKEN` in
`.env` (see https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/),
then run `docker compose up -d portal`. Tokens stay server-side. Remove the
short-lived claim token from `.env` after claiming the server.

The homepage links to the protected apps. Set a native strong password in each
app as well; keep authentication required and do not enable broad LAN bypasses.

- **qBittorrent:** username `admin`; get the temporary password from
  `docker compose logs qbittorrent`, then set your own password. There is no fixed
  `adminadmin` password. Set the network interface to **tun0** in Advanced settings
  as an additional VPN safeguard. Use `/data/torrents`, automatic management, and
  categories `radarr` → `/data/torrents/movies`, `sonarr` → `/data/torrents/tv`.
- **Sonarr/Radarr download client:** host **gluetun**, port **8080**, and your
  qBittorrent credentials. The downloader shares Gluetun's network namespace.
  Do not use the old `qbittorrent` hostname. Use the matching category above.
- **Prowlarr:** add your permitted indexers and connect to
  `http://sonarr:8989` and `http://radarr:7878` with their API keys.
- **Sonarr/Radarr roots:** `/data/media/tv` and `/data/media/movies`. Enable
  hardlinks instead of copies. All three containers mount `./content` at `/data`;
  keep torrents and media on the same filesystem for hardlinks to work.
- **Bazarr:** connect to those same Sonarr/Radarr endpoints with API keys. Create
  profiles for full English/German subtitles (plus Japanese if wanted), assign
  them to movies/series, and configure your subtitle providers. Missing subtitle
  searches can then run on its schedule. Plex must rescan to detect new tracks.
- **Overseerr:** connect Plex and your Arr apps. Choose a default download profile.
  Review/change the profile when requesting another audio language.

### 4. Add strict acquisition profiles

Run on the server (API keys are entered at a hidden prompt):

```sh
python3 scripts/language_profiles.py sonarr
python3 scripts/language_profiles.py radarr
```

Creates `Media audio · German`, `Media audio · English`, and
`Media audio · Japanese` profiles using each app's current language IDs and
custom-format schema. Profiles require the matching audio score and allow HD
720p/1080p WEB/Bluray; there is **no English fallback** in the German profile.
Select a profile per movie/series or in the request app. It leaves existing
profiles, assignments and files alone and does not trigger searches/downloads.
Reruns preserve existing profiles. Upgrades are disabled to avoid repeated
replacement downloads; enable deliberately if you want that behavior.

Release-language tags can be inaccurate; the portal verifies actual tracks after
import. A Japanese acquisition profile does not guarantee subtitles: configure
Bazarr and check the portal. Sonarr/Radarr generally manage one chosen release per
movie/episode; switching the acquisition profile can replace that file on a later
search. Prefer dual/multi-audio media when you want several audio languages
available immediately without replacing files.

## VPN verification and outages

```sh
bash scripts/vpn-check.sh
```

The public IP inside qBittorrent must be a Surfshark exit, not your home IP.
Gluetun's firewall stays enabled, qBittorrent has no independent network, and it
starts only after Gluetun is healthy. A healthy Compose startup alone is not a
proof against leaks: run this outage test on your actual host before downloads.

1. Pause downloads and run the check above.
2. Run `docker compose exec gluetun ip link set tun0 down` and immediately run
   `docker compose exec -T qbittorrent curl --fail --max-time 3 https://api.ipify.org`.
   It must fail while the tunnel is down or return a Surfshark IP if Gluetun has
   already reconnected; it must never return the home IP.
3. Restore with `docker compose restart gluetun qbittorrent`, then repeat the check.

Plex stays outside the VPN. Surfshark does not provide incoming port forwarding;
peer connectivity/seeding may be limited. The VPN does not give remote access to
your home server. DNS/indexer searches in Prowlarr are outside Surfshark in this
setup; only downloader traffic is routed through it.

## Backups, health and updates

```sh
bash scripts/backup.sh
python3 scripts/health.py
```

Backups briefly stop the currently running services for consistent databases and
restart those services afterward. They include `.env`, app configuration,
databases, certificates and credentials, **not media files**. Archives are private
and checksummed; copy them to encrypted storage on another disk. No automatic
retention/deletion is enabled. For restore: stop the stack, verify the `.sha256`
file, extract the archive into a clean checkout, check ownership, then start.
This restores authentication/session state too; revoke sessions if restoring after
a security incident. Test restore on an isolated host.

Run `scripts/health.py` from your own cron/systemd schedule to check missing,
stopped/unhealthy containers and disk space. It logs problems and exits nonzero.
Optional `ALERT_WEBHOOK` must be exported in that scheduler's environment to send
JSON `{ "text": "..." }` alerts; it is not automatically loaded from `.env`.
No scheduled jobs or external notifications are created by installing this repo.

Sonarr, Radarr, qBittorrent, Gluetun, Caddy and Authelia are versioned in Compose.
Other inherited images still follow their release channels; review and pin them
to tested tags/digests before a production rollout. Back up before pulling newer
images. No automatic container updater is enabled. Plex no longer runs privileged.
Logs rotate at 10 MiB × 3 files per container.

Extra inherited services are opt-in via `docker compose --profile extras up -d`:
Lidarr, Jackett, Ombi, Heimdall, Huntarr, Suggestarr and FlareSolverr. Their ports
are loopback-only and have no default public reverse-proxy routes. Prowlarr and
Overseerr are the default source/request apps. Older setup context is archived in
[docs/upstream-setup.md](docs/upstream-setup.md); its port/network assumptions are
historical.

## Validation

```sh
python3 -m pip install PyYAML
python3 -m unittest discover -s tests -v
bash -n scripts/backup.sh scripts/vpn-check.sh
```

CI also runs Docker Compose interpolation checks, Authelia/Caddy native config
validation, and a portal image build using public dummy credentials. Live Plex
playback, client behavior, Surfshark credentials, kill-switch operation, TLS trust
and real release-language detection require a configured deployment and are not
claimed by the unit tests.
