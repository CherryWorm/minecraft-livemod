# Patchouli for Minecraft 26.3

[Patchouli](https://github.com/VazkiiMods/Patchouli) is by Vazkii, williewillus and its other contributors, and is licensed under CC BY-NC-SA 3.0, in `LICENSE`. This port is under the same licence. It's what players read the Codex in.

Upstream's newest build is for 26.1, and nothing offers one for 26.3, so this is upstream at `4f94b07` with `port.patch` on top:

- Minecraft's renames between 26.1 and 26.3.
- Only the Fabric mod is built, by `build.gradle` here, because upstream's shared project compiles against NeoForm, which has nothing for 26.3.
- No multiblock pages or previews, because they draw through renderer classes 26.3 removed. A book asking for one gets nothing.
- No book-opened advancement trigger, because advancement predicates were rebuilt in 26.3 and nothing here uses it.
- It only loads on clients, so a server can't end up with a registry its players don't share.

`scripts/build-patchouli.sh` rebuilds `mods/companion/libs/patchouli-fabric-*.jar` from all of this. When upstream publishes a build for this Minecraft, use that and delete this folder.
