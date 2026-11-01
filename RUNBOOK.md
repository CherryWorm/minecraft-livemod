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

To update the code later: run `./scripts/update-engine.sh` as root. It pauses the broker between jobs, pulls, releases the new engine with the world's own features through every gate, restarts the agent, and rebuilds the friend pack if the companion changed. Players get one restart, at a safe moment. Don't promote from the repo folder directly: it has none of the agent's features, so the gates refuse it once the world has any. A change under `infra/` also needs `./scripts/stack.sh build` and `./scripts/stack.sh up -d`. Those recreate the game server and the proxy at once, whether or not it's a safe moment, so only run them for that. A changed `infra/site/Caddyfile` also needs `./scripts/stack.sh up -d --force-recreate site`, because the container keeps the old file until then.

**What's open to the internet:** only what's in `compose.yaml` with no `127.0.0.1` in front of it, which is 25565 for the game, plus 80 and 443 for the site. 25566, 25567, 25568, the test lanes' ports from 25572 up, and RCON aren't published beyond this machine. Docker writes its own firewall rules, so `ufw` can't close a published port, and that's why nothing else is published.

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

Players talk to the agent privately with `/dm <message>`. Everything else in chat is public. The first thing a new player hears is the agent's first question and how to answer it. Their interview is saved after every message, so it carries on if they leave or the agent restarts, and coming back repeats where things had got to, along with how to answer. After the interview, `/dm` stays a private conversation: it answers every message, in character once there is a character, remembers that player's last few messages and passes any suggestions on to the agent. All the voices answer plainly, with real depths, biomes and recipes, from a guide generated from what's been released, so they can't give away what's still to come unless a feature's own summary mentions it.

Players report bugs with `/bug <what went wrong>`, and that doesn't go through the director or the job queue. An agent starts looking into it straight away, with what it can read: the features, the live server's warnings and errors with addresses taken out, and what that player is carrying and looking at. It can't change anything. The player hears what it found, whatever that is. If the cause is in one of this world's features, a fix starts at once, in a folder and on a branch of its own cut from what's live, with no limit on how many builders are running and without waiting for any builder working on that feature. Its gates go ahead of everything but quick checks and it's first into the next release, but it still passes the same gates and review as anything else. The player hears again when it's live. If the cause is in the engine, which the agent can't change, it comes to you in `state/host_requests.jsonl` with what was found, and the player's told that. So is anything that can't be fixed after three tries. Each player can have 3 reports open and send 10 a day, so nobody can spend the plan by repeating themselves. If a builder is partway through changing the same lines, the fix goes out first and that builder is shown both versions to settle. The kill switch and a used-up plan hold bugs up like everything else, and they carry on by themselves after, including through a restart.

The director is the one place the world's plan is decided: what gets built, in what order and what doesn't. Building the world to its own plan comes first, so it isn't there to fulfil requests. Vanilla's own mechanics don't change for free: wanting faster ladders or boats means an upgraded ladder or boat that fits the world and has to be earned. The chat voices refuse obvious no's straight away, with a reason: jokes and things that have nothing to do with the world. Everything else is recorded in `state/intents.jsonl` and tracked until it's decided, in `requests` in `state/opening.json`.

The director looks at new requests twice. Its quick pass, on a faster model, takes seconds: a listed server rule or a plainly broken number changes on the spot, and a bug fix or small convenience gets its own small builder, which has slots of its own (`AGENT_SMALL_BUILDERS`) and goes ahead of big features at the gates. Anything needing the whole picture waits for its next planning, within about 10 minutes, where it has to build it, leave it for later, decline it, or say the engine or client mod doesn't support it. All of those are its own decisions, and none waits on you. What the engine lacks is collected in `state/host_requests.jsonl`, which notifies nobody, and the player's told it isn't supported. Only planning can say no, because the quick pass has no way to, and a no has to name what would actually go wrong in the world or it doesn't count and the request comes back. Both see everything it's already decided, with the reasons, so nothing gets built twice, but an earlier no is a record to check and not a rule to repeat. At most two big features per planning can come from requests. The player's told what happened each time, even if they've logged off, and `/dm` can say what became of their requests. What's being built and what's waiting is saved too, so restarting the agent doesn't lose it.

Everything new has to be worth having the day it ships, so the director puts whatever has to arrive together in one feature, and a reviewer treats anything without a real use as serious. A real use gives players something vanilla doesn't, or does it better: turning back into vanilla items doesn't count. The director plans ahead whenever fewer features are waiting than can be built at once, so `/board` can show an empty queue only briefly.

JEI shows this world's recipes through a plugin in the companion, under "Recipes you know". The server sends each player only what they've earned: open recipes once they've held something it uses, gated ones once learned, and machine recipes the same way, or once made if they're there to be worked out. Players with an older companion just don't get it.

## More builders

Builders can run on more than the plan. Directing, reviewing, chat and minds always stay on Claude, and everything any builder makes goes through the same gates and review. Each is off until you set it up.

- **Another model.** `sudo ./scripts/set-selfhosted-model.sh [its URL]`. It takes the key, shows what models it offers, asks which and how many builders it can take at once, tests that it can do the job, and only then turns it on. By default builders, bug fixes, chat and minds run only on it, and don't use the plan. Answer no to that and Claude's builders fill up first, and this takes what's left over. The director, its quick pass, reviews, research, the icon and all art stay on Claude whatever you set. Builders ask for art through a `make_art` tool that runs Opus, and if one draws anything itself or leaves what a template made, Opus redoes it before testing. If the model stops answering, everything goes back to Claude until it does, and `state/host_requests.jsonl` says so. Langdock refuses any single request over about 150000 tokens, counted as characters divided by 4, with a 429 that says "tokens per minute" and never succeeds if tried again. It doesn't limit what's sent per minute in total. So keep `AGENT_SELFHOSTED_CONTEXT` well under that, because a builder only summarises its history when it reaches that figure. To turn it off, set `AGENT_SELFHOSTED_BUILDERS=0` in `.env` and run `./scripts/agent-up.sh`. The key only ever stays in the agent's main process, and builders talk to a small translator there.
- **Other machines.** On the server, `sudo ./scripts/add-worker.sh <name> <slots>` prints a token once. On the other machine, which needs Docker and a checkout of this repository at the same commit, run `./scripts/worker-up.sh <https://server> <slots> <self_hosted|claude>`. It connects out over HTTPS, so it can be behind a router. It only has a model write code: compiling, gates and releases stay on the main server, so more builders eventually queue there. Remove a machine by deleting its entry from `runtime/control/workers.json`. After updating the server, update each machine's checkout and start it again, because a machine on different code is refused when it connects.

Each feature still goes through the gates alone, so that a reviewer can see its pictures. After that, finished features go out together: a release takes everything ready when it starts, up to 8, and the rest go in the next one, straight after. The whole group goes through every gate once more, because that's what will really be running. If it fails, each half goes on its own until the bad feature is found, and that one goes back to its builder while the others ship. A rollback restarts the server, so a bad feature that only fails once it's live can cost players a few restarts while that happens.

A builder can change other features, because a mod is one codebase. It says which ones and why in `changes_features` in its own `feature.json`, and plain code refuses anything else it changed. The gates check the whole world at that commit anyway, and the reviewer is shown the reason beside exactly what changed. Two builders working on the same feature only find out when the second goes to merge what the first shipped. Different lines just come together, and the same lines come back to the second builder with both versions marked, which doesn't count as one of its tries. To see what's been changed this way, read `changes_features` in the features themselves, or `git log -- mods/genesis/features/<id>` in the agent's repository.

`/board` turns a sidebar on or off for the player who types it, and it stays that way until they change it. It shows how many things have shipped, are being built and are queued, and a spoiler-free line about each thing being built. A small model writes those lines from the brief, and they're refused for anything that looks like a name. Nothing needs installing. If the agent stops, the board says so within about 90 seconds.

`/plan` shows any player what's being built and what's next, in order. Bug fixes and small conveniences are named, and everything else is only its stage and a category from a fixed list, like "early game mob", so nothing's spoiled. Plain code writes it.

Anything only you can change, like a bug in the engine, is in `state/host_requests.jsonl` along with what builders wished the engine could do.

**What the agent can reach:** the game servers have no route to the internet at all, even though agent-written code runs in them. Clients reach their resource packs through the site's container. builders and their shell commands only reach Anthropic and any other model you've set up, through the `egress` proxy. Research goes through a separate `web` proxy, which can reach any public HTTPS site and refuses this machine and private networks. Only the research role holds its password, and that role has no shell, no files and nothing private in its prompt. The others get its answer as text. A misleading page can still mislead a builder through that text, so every release still goes through all the gates and the review.

## Before friends install anything

Each friend has to agree to two things, knowing what they mean:

- Their chat and private interview answers go to Langdock and Anthropic, including whatever they say to creatures. If you change where chat runs, change what the site's install page says too. Creatures can repeat what they're told to other players as gossip. Their ideas can also shape what the agent looks up on the public web. A check keeps player names and long phrases from private answers out of those searches, but it can't catch a paraphrase.
- The companion runs code an AI wrote on their PC. It's signed and checked, and it can't use files, the network or their login, but Java has no true sandbox, so this reduces risk rather than removing it. `/companion off` turns it off on their machine at any time.

The website says all of this, above the download. The pack comes from `./scripts/make-friend-pack.sh`, which also updates the site's copy, so send people the site's address and the password. They need [Prism Launcher](https://prismlauncher.org/) and their own Minecraft account: *Add Instance → Import → choose the zip*. The server is already in the game's list. The first launch takes a few minutes.

Prism's handling of the pack hasn't been tested on a real install yet, so try it on your own PC first.

Once anyone runs a client module, everyone needs the companion. Turn that on with `touch "$RUNTIME_DIR/prod/config/conduit/require_companion"`.

**A new companion.** The pack keeps itself up to date: Prism runs `updater/Updater.java` before each launch, and it installs whatever's in the latest update. After pushing a change to `mods/companion` or to the client mods in `infra/mods.lock`, run `LIVE_HOST=<server address> scripts/publish-client.sh` from Git Bash on your PC, and everyone gets it the next time they start the game. It builds what's on main and signs it in the dev distro, with a key that must never go on the server, because it can install anything on friends' PCs. If you lose `runtime/secrets/client_release.pem` in the distro, make a new one with `python3 -m broker.client_release key`, put the public half in `infra/client_release.pub`, and everyone downloads the pack once more. They also download it once more for a change to the updater itself or to the Minecraft or Fabric version, which it can't update. On a server made before the updater, add `UPDATE_TOKEN` to `.env` (a long random string), run `./scripts/stack.sh up -d --no-deps --force-recreate site`, and rebuild the pack. Someone on a companion from before inventory hooks is told so in chat when they join. Until they update, only the modules that use those hooks don't work for them, with `failed to load` and a `NoSuchMethodError` in their game's log, and everything else carries on.

**When the engine can do more.** A request the director passed to you stays with you, so once you've added what it needed, run `touch ../runtime/control/engine_updated` from the repo folder. Everything waiting on you goes back to the director at its next planning, and it starts one straight away. It decides afresh, and anything it still can't do stays with you, without telling you or the player again. For a change players need a new companion for, do this after they've got it, so the first thing built with it works for them.

## Day to day

| To do this | Run this |
|---|---|
| See what the agent's doing | `docker logs -f livingmod-agent-1` |
| See what it's released | `tail runtime/timeline.jsonl` and `cat runtime/agent-workspace/state/features.jsonl` |
| See what it's asked the engine to add | `cat runtime/agent-workspace/state/host_requests.jsonl` |
| See what players have reported with `/bug`, and what became of it | `cat runtime/agent-workspace/state/bugs.jsonl` |
| See how much of your plan it's used | `cat runtime/agent-workspace/state/governor.json` |
| See the world's progression and what's built on it | `cat runtime/agent-workspace/repo/bible/progression.json` |
| See which numbers it's changed from feedback | `cat runtime/agent-workspace/state/tunes.jsonl` |
| See what creatures with minds have been up to | `tail runtime/agent-workspace/state/minds.jsonl`, and `cat runtime/agent-workspace/state/rumours.jsonl` |
| Turn minds off, or back on | `touch runtime/control/no_minds`, or `rm` the same file. `AGENT_MIND_USAGE_LIMIT` in `.env` sets their daily share, a tenth of the daily limit by default |
| See what it's looked up | `ls runtime/agent-workspace/research`, and `docker logs livingmod-web-1 \| grep CONNECT` for every site |
| Turn its research off, or back on | `touch runtime/control/no_research`, or `rm` the same file |
| Give the go-ahead to choose the theme and start building | `touch runtime/control/decide_now` |
| Send requests that were waiting on you back to the director, after changing the engine | `touch runtime/control/engine_updated` |
| End the opening by hand | `./scripts/mc.sh conduit open` |
| Stop the agent, from the host | `touch runtime/control/agent_disabled` |
| Stop the agent, in game (owner only) | `/agentstop`, then `/agentstart` |
| Stop and restart the agent's process | `./scripts/agent-down.sh`, `./scripts/agent-up.sh` |
| Open up land that's already generated to new biomes | Stop the server, then `python3 -m broker.prune runtime/prod/world` (add `--dry-run` first) |

The kill switch stops releases and silences the character. The game keeps running, and everything already shipped keeps working.

## How the broker shares the machine

Lookups, lint and the other small jobs start as soon as they're asked for. Each job that's bigger than that has a lane, which is a set of folders under `runtime/lanes` that nothing else uses, and its own copy of Gradle's files. `CHECK_LANES` in `.env` says how many compile checks can run side by side, 1 by default. A lane costs about 1.4 GB of disk, and it's copied from `runtime/cache` the first time it's used.

`GATE_LANES` in `.env` says how many test runs can go side by side, 1 by default. Releases use a test lane too, but only one goes at a time, whatever this says. The first lane is the `shadow` and `shadow-proxy` services as they've always been. Each one after it is those same services, plus `shadow-pack`, as a compose project of its own called `livingmod-gates-N`, with folders under `runtime/lanes/gates-N` and two ports on this machine only: 25570 plus twice N for the proxy, and one above that for the pack. So starting or stopping a lane can't touch the live server, the proxy or the site. They start the first time they're needed, and cost about 5 GB of disk. A lane's test server and proxy stay up between jobs at up to `SHADOW_MEMORY` plus about 1 GB, and its test client adds up to 4 GB during a run. On a 30 GB machine with the live server at `PROD_MEMORY=8G`, that makes 2 lanes with `SHADOW_MEMORY=4G` the most that fits, because a third would leave the live server nothing to grow into. A test server only takes up a new `SHADOW_MEMORY` the next time it starts from cold. Lowering the number of lanes stops the spare ones the next time the broker starts.

To change either number, edit `.env` and run `systemctl restart livingmod-broker`. Don't run `./scripts/stack.sh up -d` for this.

**Test runs on another machine.** Past what fits here, test runs can go to a second machine, which also takes them off the one people are playing on. Rent one that's for nothing else, with Ubuntu 24.04 or later and about 10 GB of memory and 4 fast cores for each lane, that this server can already reach as root over SSH, and run `./scripts/add-test-machine.sh ADDRESS LANES` here as root. It installs what's needed, copies the images and the world across, adds `TEST_MACHINE`, `TEST_MACHINE_HOME` and `FAR_LANES` to `.env`, and restarts the broker between jobs. After that test runs go there first. If it stops answering, each job runs here instead and nobody's told, and it's tried again after 5 minutes. `journalctl -u livingmod-broker | grep 'test machine'` shows when that's happened.

- **What it can reach.** This server has a key for that machine, and that machine has nothing for this one, so unchecked work that gets loose there has no way back. It has its own secrets. It does hold a copy of the world, which is sent at most every 10 minutes, and that includes where players have been.
- **Releases.** A release is always proved here, because a pass from there is never believed, so a release after a test run there runs its own tests. This is the one thing that gets slower: about a third of releases used to reuse a pass.
- **The code.** The same code as this server's is sent with each job, so there's nothing to update. The images aren't, so after `./scripts/stack.sh build` here, run `add-test-machine.sh` again.
- **To stop using it,** set `FAR_LANES=0` in `.env` and restart the broker. Its test servers stay up until you stop or delete the machine.

A bigger job beside others only starts if there's room for it and 4 GB to spare, which leaves the live server room to grow to its limit. `journalctl -u livingmod-broker | grep -E 'waiting [0-9]{2,}'` shows anything that's had to wait long. If memory runs out anyway, the system stops the broker and everything it's running, rather than the live server.

## What the numbers hold it to

Everything the agent builds is checked against limits in `broker/gates/progression.py` and `broker/gates/static.py`: gear and mob strength by stage, automation rates, and how many moving parts a model can have. They're starting values, so tune them after you've played. Real frame rates on your friends' PCs are the thing to watch, because the test client renders in software and can't measure them.

## When something goes wrong

- **A bad release reached players.** The broker rolls back on its own if the server crashes or logs errors within a minute. If it's only bad as content, tell it in chat, or disable the feature by deleting its folder from the agent's repo. Its blocks and items stay in the world as blanks.
- **A feature's mixin crashes the server.** Features can patch the game's own code with mixins, on the server only, when no hook will do. While the broker is running it watches crash reports for as long as any are on the server. If one points to a mixin, that mixin comes out of the live release and the server restarts without it, and the rest of the feature stays. Players hear the same thing they do for a rollback. The same jar stays out until the feature changes it, and the agent treats it as a bug. It's all in `runtime/broker/crashed_mixins.json`, and deleting a feature's entry lets the same jar go out again. Three crashes in ten minutes with mixins on the server and no report pointing to any take them all out, even though they might not be to blame. A mixin can't patch gm.conduit or anything outside the game, whoever approves it. What else it can't patch, like commands and login, is listed in `REFUSED_TARGETS` in `broker/gates/mixins.py`, and you can approve one target for one feature in `broker/gates/bytecode_exceptions.json`, as `{"<feature>": {"mixins": ["target net/minecraft/..."]}}`. Testing a release with mixins leaves out the test server's extra mods, which takes a rebuilt server image. Until then those mods stay in for the test, so a mixin that conflicts with only them would be refused, and one that only fails without them gets as far as a rollback.
- **The agent keeps failing gates.** Five failures in a row pause it for 30 minutes. `docker logs` and `runtime/broker/last.json` say why.
- **It ran out of plan usage.** It stops by itself and resumes when your limits reset. The character goes quiet, and the game isn't affected. `AGENT_DAILY_USAGE_LIMIT` and `AGENT_MAX_BUILDERS` in `.env` control how quickly it spends.
- **The world is damaged.** Stop the server and restore from `runtime/backups`. Chunk data holds which patches each chunk has had, so a restored world is consistent with itself. Only you can do this. The agent can't reach backups.

## Upgrading Minecraft

Don't move until every library supports the new version. Rehearse on a copy of the world, on the shadow server, and regenerate the packet IDs in `scripts/smoketest_join.py` and `scripts/playtest_bot.py`. Friends need a new pack. Minecraft 26.4 snapshots reportedly default to Vulkan, which may break client rendering code, so check that first.
