# Living Mod

A Minecraft Java server where an AI agent builds and evolves a mod while friends play. The world starts blank. The agent talks privately with each player, chooses one direction and stays in character from then on, building outward from the early game while people play.

`RUNBOOK.md` covers running it for real and moving to a rented server.

## Layout

| Path | What it is |
|---|---|
| `versions.env`, `infra/mods.lock` | Every pinned version and checksum |
| `infra/` | Docker Compose stack: Velocity proxy, prod and shadow servers, agent, and the egress and web proxies that limit its network |
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

Inside the distro, start the agent. It greets each new player with a private conversation, then waits for your go-ahead before it chooses a theme and starts building:

```bash
./scripts/agent-up.sh
```

```bash
touch /srv/livingmod/runtime/control/decide_now
```

Watch it with `docker logs -f livingmod-agent-1`, and stop it with `./scripts/agent-down.sh`. It uses your Claude plan while it's running. To start over from a blank world, run `./scripts/reset-dev-world.sh --yes`.

## Tests

Inside the distro:

| Command | What it proves |
|---|---|
| `python3 -m unittest broker.tests.test_balance broker.tests.test_bytecode broker.tests.test_hooks broker.tests.test_sign broker.tests.test_prune broker.tests.test_progression broker.tests.test_player_guide broker.tests.test_guide broker.tests.test_daemon_order` | The gates' rules, the world's progression, `tune` and pruning, with no servers |
| `python3 -m broker.tests.m2_test` | Bad releases are stopped at the right gate, and a crash rolls back |
| `python3 -m broker.tests.m3_test` | Records survive a restart, modules hot-swap, and a crash holds players |
| `python3 -m broker.tests.m7_test` | Signed modules run on a real client, and unsigned or unsafe ones are refused |
| `python3 -m broker.tests.m8_test` | A real client learns recipes, uses a machine, reads the codex and sees mobs |
| `python3 -m broker.tests.m22_test` | The Codex in Patchouli on a real client: only what a player knows, opened by command, key and link, with new pages arriving live |
| `python3 -m broker.tests.m10_test` | Templated content goes live with its real numbers, the progression refuses what doesn't fit, what players have is protected, and `tune` and the server icon work |
| `python3 -m broker.tests.m11_test` | Sculpted creatures and a model block on a real client, then 150 more models at once |
| `python3 -m broker.tests.m12_test` | Mobs with minds, on a real client with the real fast model: they answer, remember, gossip and keep to their limits. Uses a little of your plan |
| `python3 -m broker.tests.m15_test` | What players ask for, on the real agent and models: a server rule changes on the spot, a small ask gets its own builder and reaches the game, a big one goes to the director, and the player hears about each. Uses a little of your plan |
| `python3 -m broker.tests.m16_test` | What modules can hook into, on a real client: sounds by name, world events, blocks removed, feeding mobs, ruins that vary, and inventory helpers, with what players type kept out of reach. Start from a blank world |
| `python3 -m broker.tests.language_test` | The world in German on a real client, set in its own options: names, tooltips, the Codex, panels and what modules say, and all of it unchanged in English. Start from a blank world and a baseline |
| `python3 -m broker.tests.m17_test` | The larger things the engine can do, on a real client: machine inventories and hoppers, menus and books, crops, connected blocks, items with timed uses and changing pictures, tinted and baby mobs. Start from a blank world |
| `./scripts/stack.sh --profile agent run --rm -T agent python3 /spikes/dm_voice.py` | The voices on the real model, in character: plain, real answers over `/dm` and in chat, and nothing that isn't out. Uses a tiny bit of your plan |
| `./spikes/m4_e2e.sh` | The whole agent, from a blank world to shipped features, a tuned number and a mid-game machine. Uses your plan |
| `python3 scripts/smoketest_join.py` | Login, resource pack and joining, with no game |

These tests need `PROXY_ONLINE_MODE=false` in `.env`, which is only acceptable while the port is reachable from this PC alone. The rented server must keep `PROXY_ONLINE_MODE=true`.
