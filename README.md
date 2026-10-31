# Living Mod

A Minecraft Java server where an AI agent builds and evolves a mod while friends play. The world starts blank, players choose a theme, and the agent builds from there.

Status: M0, foundation. No agent yet.

## Layout

| Path | What it is |
|---|---|
| `versions.env`, `infra/mods.lock` | Every pinned version and checksum |
| `infra/` | Docker Compose stack: Velocity proxy, prod and shadow servers |
| `mods/conduit/` | Stable server infrastructure |
| `assetkit/` | Asset generation |
| `scripts/` | Host setup, builds, checks |

## Development on Windows

Everything runs in a dedicated WSL distro called `livingmod`. It can't see Windows drives or start Windows programs, so code is pushed in from this side. Remove the whole environment with `wsl --unregister livingmod`.

Push your working tree into the distro, from Git Bash:

```bash
bash scripts/wsl-sync.sh
```

Then, inside the distro at `/srv/livingmod/repo`:

```bash
./scripts/init-host.sh            # first time only
./scripts/build-mods.sh current   # build our mods
./scripts/stack.sh build          # build the images
```

The server won't start until you've read the [Minecraft EULA](https://aka.ms/MinecraftEULA) and set `MINECRAFT_EULA=true` in `.env`.

Start and stop the stack from Git Bash. WSL stops an idle distro even with Docker running, so these hold a session open while the server is up:

```bash
bash scripts/wsl-up.sh
```

```bash
bash scripts/wsl-down.sh
```

Connect a Minecraft 26.3 client to `localhost`. Inside the distro, run a server command with:

```bash
./scripts/mc.sh list
```

To test the whole join path without a game (login, resource pack, entering the world), run this inside the distro. It needs `PROXY_ONLINE_MODE=false` in `.env`, which is only acceptable while the port is reachable from this PC alone:

```bash
python3 scripts/smoketest_join.py
```

The rented server must keep `PROXY_ONLINE_MODE=true`.
