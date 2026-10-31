# Running the Living Mod server

Everything here is run on the host from the repo folder unless it says otherwise.

## Moving to a rented server

Aim for about 8 fast cores and 32 GB of RAM, on Ubuntu 24.04. That's an estimate: prod 8 to 10 GB, shadow 6, test client 4, builds 4, agent 4.

1. **Fix your Minecraft login first.** Your client gets "Invalid session" from Mojang, which is why the development proxy has login checks off. The rented server has to keep them on, so you can't join it until this is sorted. Realms' error message points at your account's profile rather than anything on this side.
2. **Install Docker** and create an unprivileged user with uid 1000 for the stack. Don't give the agent's user Docker access.
3. **Copy the repo** to `/srv/livingmod/repo`, then run `./scripts/init-host.sh`.
4. **Edit `.env`:**
   - `PROXY_ONLINE_MODE=true`. Never turn this off on anything reachable from the internet.
   - `WHITE_LIST=true`, then add each friend with `./scripts/mc.sh whitelist add NAME`.
   - `PACK_PUBLIC_URL=http://your.server.address:25567/`.
   - `MINECRAFT_EULA=true`, once you've read and accepted it.
   - `OWNER_UUID=` your Minecraft account's UUID, so `/agentstop` works for you in game.
5. **Set the token** with `./scripts/set-claude-token.sh`. Don't copy it from the dev machine in a chat or a file you keep.
6. **Check the agent's sandbox.** A host with AppArmor may block the namespaces credential scrubbing needs, so rerun both of these and read the results:
   ```bash
   ./scripts/stack.sh --profile agent build
   ./scripts/stack.sh --profile agent run --rm -T agent python3 /spikes/s5_plan_login.py
   ./scripts/stack.sh --profile agent run --rm -T agent python3 /spikes/s6_agent_smoke.py
   ```
7. **Firewall:** allow 25565 for the game and 25567 for the resource pack. Keep 25566, 25568 and 25575 closed.
8. **Set up off-box backups.** World backups land in `runtime/backups`. Copy them somewhere the agent can't reach, and copy `runtime/broker/signing` to somewhere safer still, because losing it means every friend has to reinstall.
9. **Move the signing key** from the dev machine if a pack has already gone out, or make a new one with `python3 -m broker.sign` and rebuild the friend pack.
10. **Start it:**
    ```bash
    ./scripts/stack.sh up -d
    printf 'Name1\nName2\n' > "$RUNTIME_DIR/control/roster.txt"
    ./scripts/agent-up.sh
    ```

**Known gap:** the prod server can reach the internet, because Polymer serves the resource pack from it and that needs a public network. Agent-written server code runs in there, so on the rented server add a firewall rule that blocks new outbound connections from the prod container, or move the pack to a standalone host.

**What the agent can reach:** builders and their shell commands only reach Anthropic, through the `egress` proxy. Research goes through a separate `web` proxy, which can reach any public HTTPS site and refuses this machine and private networks. Only the research role holds its password, and that role has no shell, no files and nothing private in its prompt. The others get its answer as text. A misleading page can still mislead a builder through that text, so every release still goes through all the gates and the review.

## Before friends install anything

Each friend has to agree to two things, knowing what they mean:

- Their chat and private interview answers go to Anthropic. Their ideas can also shape what the agent looks up on the public web. A check keeps player names and long phrases from private answers out of those searches, but it can't catch a paraphrase.
- The companion runs code an AI wrote on their PC. It's signed and checked, and it can't use files, the network or their login, but Java has no true sandbox, so this reduces risk rather than removing it. `/companion off` turns it off on their machine at any time.

Then make the pack with `./scripts/make-friend-pack.sh` and send them the file. They need [Prism Launcher](https://prismlauncher.org/) and their own Minecraft account: *Add Instance → Import → choose the zip*, then add the server address. The first launch takes a few minutes.

Prism's handling of the pack hasn't been tested on a real install yet, so try it on your own PC first.

Once anyone runs a client module, everyone needs the companion. Turn that on with `touch "$RUNTIME_DIR/prod/config/conduit/require_companion"`.

## Day to day

| To do this | Run this |
|---|---|
| See what the agent's doing | `docker logs -f livingmod-agent-1` |
| See what it's released | `tail runtime/timeline.jsonl` and `cat runtime/agent-workspace/state/features.jsonl` |
| See what it's asked the engine to add | `cat runtime/agent-workspace/state/host_requests.jsonl` |
| See how much of your plan it's used | `cat runtime/agent-workspace/state/governor.json` |
| See what it's looked up | `ls runtime/agent-workspace/research`, and `docker logs livingmod-web-1 \| grep CONNECT` for every site |
| Turn its research off, or back on | `touch runtime/control/no_research`, or `rm` the same file |
| Make it decide now, without waiting for everyone | `touch runtime/control/decide_now` |
| Stop the agent, from the host | `touch runtime/control/agent_disabled` |
| Stop the agent, in game (owner only) | `/agentstop`, then `/agentstart` |
| Stop and restart the agent's process | `./scripts/agent-down.sh`, `./scripts/agent-up.sh` |
| Open up land that's already generated to new biomes | Stop the server, then `python3 -m broker.prune runtime/prod/world` (add `--dry-run` first) |

The kill switch stops releases and silences the character. The game keeps running, and everything already shipped keeps working.

## When something goes wrong

- **A bad release reached players.** The broker rolls back on its own if the server crashes or logs errors within a minute. If it's only bad as content, tell it in chat, or disable the feature by deleting its folder from the agent's repo. Its blocks and items stay in the world as blanks.
- **The agent keeps failing gates.** Five failures in a row pause it for 30 minutes. `docker logs` and `runtime/broker/last.json` say why.
- **It ran out of plan usage.** It stops by itself and resumes when your limits reset. The character goes quiet, and the game isn't affected. `AGENT_DAILY_USAGE_LIMIT` and `AGENT_MAX_BUILDERS` in `.env` control how quickly it spends.
- **The world is damaged.** Stop the server and restore from `runtime/backups`. Chunk data holds which patches each chunk has had, so a restored world is consistent with itself. Only you can do this. The agent can't reach backups.

## Upgrading Minecraft

Don't move until every library supports the new version. Rehearse on a copy of the world, on the shadow server, and regenerate the packet IDs in `scripts/smoketest_join.py` and `scripts/playtest_bot.py`. Friends need a new pack. Minecraft 26.4 snapshots reportedly default to Vulkan, which may break client rendering code, so check that first.
