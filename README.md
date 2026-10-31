# Living Mod

A Minecraft Java server where an AI agent builds and evolves a mod while friends play. The world starts blank. The agent talks privately with each player, chooses one direction and stays in character from then on, building outward from the early game while people play.

`RUNBOOK.md` covers running it for real and moving to a rented server.

## Layout

| Path | What it is |
|---|---|
| `versions.env`, `infra/mods.lock` | Every pinned version and checksum |
| `infra/` | Docker Compose stack: Velocity proxy, prod and shadow servers, agent, egress proxy |
| `mods/conduit/` | Stable server infrastructure: slots, patches, knowledge, mobs, bridge, kill switch |
| `mods/companion/` | The client mod friends install once, which loads signed modules |
| `broker/` | Plain code that gates, signs, deploys and rolls back. No AI |
| `orchestrator/` | The agent: interviews, direction, chat, watcher, builder, reviewer |
| `assetkit/` | Makes textures, mob models and sounds |
| `docs/` | What the agent's builders read about the content format |
| `spikes/`, `broker/tests/` | Tests against the real stack |
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

## Playing with the agent, locally

Inside the distro, say who to wait for, then start the agent. It greets each new player with a private conversation:

```bash
printf 'YourName\n' > /srv/livingmod/runtime/control/roster.txt
```

```bash
./scripts/agent-up.sh
```

Watch it with `docker logs -f livingmod-agent-1`, and stop it with `./scripts/agent-down.sh`. It uses your Claude plan while it's running. To start over from a blank world, run `./scripts/reset-dev-world.sh --yes`.

## Tests

Inside the distro:

| Command | What it proves |
|---|---|
| `python3 -m unittest broker.tests.test_balance broker.tests.test_bytecode broker.tests.test_sign broker.tests.test_prune` | The gates' rules and pruning, with no servers |
| `python3 -m broker.tests.m2_test` | Bad releases are stopped at the right gate, and a crash rolls back |
| `python3 -m broker.tests.m3_test` | Records survive a restart, modules hot-swap, and a crash holds players |
| `python3 -m broker.tests.m7_test` | Signed modules run on a real client, and unsigned or unsafe ones are refused |
| `python3 -m broker.tests.m8_test` | A real client learns recipes, uses a machine, reads the codex and sees mobs |
| `./spikes/m4_e2e.sh` | The whole agent, from a blank world to a shipped feature. Uses your plan |
| `python3 scripts/smoketest_join.py` | Login, resource pack and joining, with no game |

These tests need `PROXY_ONLINE_MODE=false` in `.env`, which is only acceptable while the port is reachable from this PC alone. The rented server must keep `PROXY_ONLINE_MODE=true`.
