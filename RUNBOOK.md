# Running the Living Mod server

Everything here is run on the host from the repo folder unless it says otherwise.

## Moving to a rented server

Aim for about 8 fast cores and 32 GB of RAM. That's an estimate: prod 8 to 10 GB, shadow 6, test client 4, builds 4, agent 4. This has been run on Ubuntu 26.04.

1. **Fix your Minecraft login first.** Your client gets "Invalid session" from Mojang, which is why the development proxy has login checks off. The rented server has to keep them on, so you can't join it until this is sorted. Realms' error message points at your account's profile rather than anything on this side.
2. **Get the code and install Docker,** as root. This also creates the `livingmod` user the stack runs as, which needs uid 1000:
   ```bash
   mkdir -p /srv/livingmod
   git clone https://github.com/CherryWorm/minecraft-livemod.git /srv/livingmod/repo
   bash /srv/livingmod/repo/infra/wsl/bootstrap.sh
   chown -R livingmod:livingmod /srv/livingmod
   ```
3. **As `livingmod`, set up the host:** `./scripts/init-host.sh --public YOUR.ADDRESS`. This writes `.env` and makes up the password, which you read with `cat ../runtime/secrets/password.secret`.
4. **Edit `.env`:**
   - `MINECRAFT_EULA=true`, once you've read and accepted it.
   - `OWNER_UUID=` your Minecraft account's UUID, so `/agentstop` works for you in game.
   - `PROXY_ONLINE_MODE` stays `true`. Never turn this off on anything reachable from the internet.
5. **Build and start it,** as `livingmod`. The first boot also makes the signing key that goes in the friend pack:
   ```bash
   ./scripts/stack.sh build
   ./scripts/build-mods.sh current
   ./scripts/stack.sh up -d
   ./scripts/make-friend-pack.sh
   python3 -m broker.promote --source "$(pwd)" --release-id baseline
   ```
6. **Start the broker as a service,** as root: `cp infra/systemd/livingmod-broker.service /etc/systemd/system/ && systemctl enable --now livingmod-broker`.
7. **Set the Claude token,** as root, with `./scripts/set-claude-token.sh`. Don't copy it from the dev machine in a chat or a file you keep.
8. **Check the agent's sandbox.** A host with AppArmor may block the namespaces credential scrubbing needs, so rerun both of these and read the results:
   ```bash
   ./scripts/stack.sh --profile agent build
   ./scripts/stack.sh --profile agent run --rm -T agent python3 /spikes/s5_plan_login.py
   ./scripts/stack.sh --profile agent run --rm -T agent python3 /spikes/s6_agent_smoke.py
   ```
9. **Set up off-box backups.** World backups land in `runtime/backups`. Copy them somewhere the agent can't reach, and copy `runtime/broker/signing` to somewhere safer still, because losing it means every friend has to reinstall.
10. **Start the agent** with `./scripts/agent-up.sh`. It asks whoever joins what they'd like, and waits for your go-ahead before it does anything else. See "The opening".

To update the code later: `git pull` as `livingmod`, then `./scripts/stack.sh build`, `python3 -m broker.promote --source "$(pwd)" --release-id update-$(date +%s)`, `./scripts/stack.sh up -d`, and as root `systemctl restart livingmod-broker`. A changed `infra/site/Caddyfile` also needs `./scripts/stack.sh up -d --force-recreate site`, because the container keeps the old file until then.

**What's open to the internet:** only what's in `compose.yaml` with no `127.0.0.1` in front of it, which is 25565 for the game, plus 80 and 443 for the site. 25566, 25567, 25568 and RCON aren't published beyond this machine. Docker writes its own firewall rules, so `ufw` can't close a published port, and that's why nothing else is published.

## The password

There's one password for the website and the game, kept in `runtime/secrets/password.secret`. Change it with `./scripts/set-password.sh`, which makes up a new one, or `./scripts/set-password.sh --ask` to type your own. Nothing needs restarting. Everyone is asked again the next time they join.

- **Website:** the browser's own login box. The user name is `player`. The zip is behind it too.
- **Game:** Minecraft's own dialog, shown before the player gets any further than logging in, so without the password they get no world, no resource pack and no chat, and the agent never hears of them. Getting it right is remembered per account. Three wrong answers disconnect them, and ten in an hour lock that account out for the hour. What's typed into the box is visible on screen, because Minecraft's dialogs have no hidden text field.
- **What isn't behind it:** anyone can see that a Minecraft server is there and read its name in the server list, because Minecraft needs that to connect at all. The resource pack's address can't have a password either, because Minecraft can't send one, so it has a long random token instead. Only someone who has passed the password is ever told it.

Mojang's login check still runs first, so people need a real Minecraft account as well.

## The opening

Until the first release reaches players, the world is small and safe: a border `OPENING_BORDER` blocks wide around spawn, marked by a tall glowing wall, with Peaceful difficulty, so there are no hostile mobs and no hunger, and players can't break blocks. The first release ends it once and for all: the wall and border go, players can break things, the difficulty in `server.properties` comes back, and it becomes morning. The game runs this itself, so it holds from the first boot, even with no agent running. To end it by hand, run `./scripts/mc.sh conduit open`.

**The agent waits for you.** Until you give the go-ahead, it only asks whoever joins what they'd like. When you've heard from enough people, run `touch ../runtime/control/decide_now` from the repo folder. It then chooses the theme from the answers it has so far and starts building. Anyone still partway through their interview can finish it, and their answers steer what comes later, as do those of anyone who joins afterwards.

The wall exists only on players' screens, so no blocks are placed in the world.

## Talking to the agent

Players talk to the agent privately with `/dm <message>`. Everything else in chat is public. The first thing a new player hears is the agent's first question and how to answer it. Their interview is saved after every message, so it carries on if they leave or the agent restarts, and coming back repeats where things had got to, along with how to answer. After the interview, `/dm` stays a private conversation: it answers every message, in character once there is a character, remembers that player's last few messages and passes any suggestions on to the agent.

**What the agent can reach:** the game servers have no route to the internet at all, even though agent-written code runs in them. Clients reach their resource packs through the site's container. builders and their shell commands only reach Anthropic, through the `egress` proxy. Research goes through a separate `web` proxy, which can reach any public HTTPS site and refuses this machine and private networks. Only the research role holds its password, and that role has no shell, no files and nothing private in its prompt. The others get its answer as text. A misleading page can still mislead a builder through that text, so every release still goes through all the gates and the review.

## Before friends install anything

Each friend has to agree to two things, knowing what they mean:

- Their chat and private interview answers go to Anthropic, including whatever they say to creatures. Creatures can repeat what they're told to other players as gossip. Their ideas can also shape what the agent looks up on the public web. A check keeps player names and long phrases from private answers out of those searches, but it can't catch a paraphrase.
- The companion runs code an AI wrote on their PC. It's signed and checked, and it can't use files, the network or their login, but Java has no true sandbox, so this reduces risk rather than removing it. `/companion off` turns it off on their machine at any time.

The website says all of this, above the download. The pack comes from `./scripts/make-friend-pack.sh`, which also updates the site's copy, so send people the site's address and the password. They need [Prism Launcher](https://prismlauncher.org/) and their own Minecraft account: *Add Instance → Import → choose the zip*. The server is already in the game's list. The first launch takes a few minutes.

Prism's handling of the pack hasn't been tested on a real install yet, so try it on your own PC first.

Once anyone runs a client module, everyone needs the companion. Turn that on with `touch "$RUNTIME_DIR/prod/config/conduit/require_companion"`.

## Day to day

| To do this | Run this |
|---|---|
| See what the agent's doing | `docker logs -f livingmod-agent-1` |
| See what it's released | `tail runtime/timeline.jsonl` and `cat runtime/agent-workspace/state/features.jsonl` |
| See what it's asked the engine to add | `cat runtime/agent-workspace/state/host_requests.jsonl` |
| See how much of your plan it's used | `cat runtime/agent-workspace/state/governor.json` |
| See the world's progression and what's built on it | `cat runtime/agent-workspace/repo/bible/progression.json` |
| See which numbers it's changed from feedback | `cat runtime/agent-workspace/state/tunes.jsonl` |
| See what creatures with minds have been up to | `tail runtime/agent-workspace/state/minds.jsonl`, and `cat runtime/agent-workspace/state/rumours.jsonl` |
| Turn minds off, or back on | `touch runtime/control/no_minds`, or `rm` the same file. `AGENT_MIND_USAGE_LIMIT` in `.env` sets their daily share, a tenth of the daily limit by default |
| See what it's looked up | `ls runtime/agent-workspace/research`, and `docker logs livingmod-web-1 \| grep CONNECT` for every site |
| Turn its research off, or back on | `touch runtime/control/no_research`, or `rm` the same file |
| Give the go-ahead to choose the theme and start building | `touch runtime/control/decide_now` |
| End the opening by hand | `./scripts/mc.sh conduit open` |
| Stop the agent, from the host | `touch runtime/control/agent_disabled` |
| Stop the agent, in game (owner only) | `/agentstop`, then `/agentstart` |
| Stop and restart the agent's process | `./scripts/agent-down.sh`, `./scripts/agent-up.sh` |
| Open up land that's already generated to new biomes | Stop the server, then `python3 -m broker.prune runtime/prod/world` (add `--dry-run` first) |

The kill switch stops releases and silences the character. The game keeps running, and everything already shipped keeps working.

## What the numbers hold it to

Everything the agent builds is checked against limits in `broker/gates/progression.py` and `broker/gates/static.py`: gear and mob strength by stage, automation rates, and how many moving parts a model can have. They're starting values, so tune them after you've played. Real frame rates on your friends' PCs are the thing to watch, because the test client renders in software and can't measure them.

## When something goes wrong

- **A bad release reached players.** The broker rolls back on its own if the server crashes or logs errors within a minute. If it's only bad as content, tell it in chat, or disable the feature by deleting its folder from the agent's repo. Its blocks and items stay in the world as blanks.
- **The agent keeps failing gates.** Five failures in a row pause it for 30 minutes. `docker logs` and `runtime/broker/last.json` say why.
- **It ran out of plan usage.** It stops by itself and resumes when your limits reset. The character goes quiet, and the game isn't affected. `AGENT_DAILY_USAGE_LIMIT` and `AGENT_MAX_BUILDERS` in `.env` control how quickly it spends.
- **The world is damaged.** Stop the server and restore from `runtime/backups`. Chunk data holds which patches each chunk has had, so a restored world is consistent with itself. Only you can do this. The agent can't reach backups.

## Upgrading Minecraft

Don't move until every library supports the new version. Rehearse on a copy of the world, on the shadow server, and regenerate the packet IDs in `scripts/smoketest_join.py` and `scripts/playtest_bot.py`. Friends need a new pack. Minecraft 26.4 snapshots reportedly default to Vulkan, which may break client rendering code, so check that first.
