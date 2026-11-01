#!/bin/bash
# The part of publish-client.sh that runs in the dev distro, where the key is. Builds from a fresh copy of what's on main, so what's
# signed is what's public, and writes the signed result to stdout as a tar. Everything else goes to stderr.
# Usage: publish-client-build.sh <repository url> <commit> <module public key>
set -euo pipefail
url=$1
commit=$2
module_key=$3
runtime_dir=/srv/livingmod/runtime

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git clone -q "$url" "$work/repo" </dev/null >&2
cd "$work/repo"
git checkout -q "$commit"
printf 'RUNTIME_DIR=%s\n' "$runtime_dir" >.env
printf '%s\n' "$module_key" >mods/companion/src/main/resources/module_key.pub
chmod +x mods/gradlew

# A Gradle home of its own, because Loom holds a lock on one for as long as anything's using it, and tests here can run for a long time.
# Started from a copy of the shared one, so the first build needn't download everything again.
[[ -d "$runtime_dir/cache/gradle-publish" ]] || rsync -a --exclude "*.lock" "$runtime_dir/cache/gradle/" "$runtime_dir/cache/gradle-publish/" >&2
docker run --rm --user "$(id -u):$(id -g)" -e GRADLE_USER_HOME=/cache/gradle-publish -e HOME=/cache/home \
  -v "$work/repo/mods":/work -v "$runtime_dir/cache":/cache -w /work eclipse-temurin:25-jdk \
  ./gradlew --no-daemon --console=plain :companion:build </dev/null >&2

staging="$work/staging"
mkdir -p "$staging/mods"
find mods/companion/build/libs -maxdepth 1 -name 'companion-*.jar' ! -name '*-sources.jar' -exec cp {} "$staging/mods/" \;
cp mods/companion/libs/patchouli-fabric-*.jar "$staging/mods/"
line=$(grep -P '^server\tfabric-api-' infra/mods.lock)
file=$(cut -f2 <<<"$line"); jar_url=$(cut -f3 <<<"$line"); sha=$(cut -f4 <<<"$line")
curl -fsSL --retry 3 -o "$staging/mods/$file" "$jar_url" </dev/null >&2
echo "$sha  $staging/mods/$file" | sha512sum -c --quiet - >&2
bash infra/fetch-mods.sh infra/mods.lock client "$staging/mods" </dev/null >&2

python3 -m broker.client_release sign "$staging" "$work/out" "$(date +%s)" </dev/null >&2
sed -n 2p "$work/out/manifest" >&2
tar -C "$work/out" -cf - files manifest manifest.sig
