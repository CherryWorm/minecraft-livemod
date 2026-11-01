"""Mixins: a feature's patches to the game's own code, on the server only.

A mixin isn't a module. It can't be hot-loaded, because it only applies to a class as that class first loads, so it's a mod in
its own right that the server loads as it starts. Nothing can switch one off once it's in, because its code becomes part of the
game's, and it can reach private things no module can. So the jar is made here rather than by the build, and everything it
says about itself comes from this file: a mod's metadata can run code as the game starts, through an entrypoint, a mixin
plugin or a nested jar, and none of that can come from the agent's side.

Everything in bytecode.py applies as well, but that reads a class's code, and a mixin says most of what it does in annotations,
as text. Its target isn't a reference to a class at all, so nothing there would notice one naming gm.conduit.KillSwitch. These
are the rules for what's in the annotations, and each refusal is there because of what would otherwise go unseen:
- What can be patched: what protects the world, players' builds and the way back from a bad release.
- Failures that stay quiet: @Pseudo, require = 0, a soft local capture, @Group. The rule is that a mixin either applies or stops the release.
- Things that can quietly undo other patches: @Overwrite and priorities.
- Text that names something the code never does: a @Redirect's target, or a selector written as a pattern that hides a name.
- Code that runs inside the patcher: a custom @At, or a static initialiser.
"""
import json
import re
import zipfile

from broker.gates import GateFailed, bytecode

GATE = bytecode.GATE
MOD_PREFIX = "mixin_"
JAR_PREFIX = "mixin-"
METADATA_KEY = "livingmod:mixins"
# Starting values. Hooks are what's meant to grow, so needing more than this says something's missing from the engine.
MOST_MIXINS_A_FEATURE = 4
MOST_FEATURES_WITH_MIXINS = 12
LEAST_WHY_CHARACTERS = 40
FABRIC_ID = re.compile(r"[a-z][a-z0-9_-]{1,63}", re.ASCII)
MIXIN = "org/spongepowered/asm/mixin/"
INJECTION = f"{MIXIN}injection/"
EXTRAS = "com/llamalad7/mixinextras/"
# The only thing a mixin may patch is the game. Everything else here is what's meant to watch over what mixins do, like gm.conduit.
PATCHABLE = "net/minecraft/"

RECORDS = ("is where the records that protect players' builds get written, and a patch could change a block without leaving one",
           ("net/minecraft/world/level/chunk/LevelChunk", "net/minecraft/world/level/chunk/LevelChunkSection", "net/minecraft/world/level/chunk/ChunkAccess",
            "net/minecraft/world/level/chunk/ProtoChunk", "net/minecraft/world/level/chunk/ImposterProtoChunk", "net/minecraft/world/level/chunk/PalettedContainer",
            "net/minecraft/world/level/chunk/status/", "net/minecraft/server/level/ChunkMap", "net/minecraft/server/level/ServerChunkCache"))
# Rules as in bytecode.py. Each is something a mod might well patch somewhere else. The owner can approve one for one feature.
REFUSED_TARGETS = (
    ("is how the kill switch, the broker and the checks on a release reach the server, and a patch here could quietly answer for it",
     ("net/minecraft/commands/", "net/minecraft/server/commands/", "net/minecraft/server/permissions/", "net/minecraft/server/rcon/",
      "net/minecraft/server/dedicated/", "net/minecraft/server/MinecraftServer", "net/minecraft/server/ServerFunctionManager",
      "net/minecraft/server/Main", "net/minecraft/server/Bootstrap", "net/minecraft/server/WorldStem", "net/minecraft/server/Eula")),
    ("is how a crash gets noticed, and rollback depends on that",
     ("net/minecraft/CrashReport", "net/minecraft/CrashReportCategory", "net/minecraft/CrashReportDetail", "net/minecraft/ReportedException",
      "net/minecraft/ReportType", "net/minecraft/SystemReport", "net/minecraft/server/gui/", "net/minecraft/util/thread/")),
    ("is how players are let in, which includes the password and the whitelist, and every command a player types passes through it",
     ("net/minecraft/network/", "net/minecraft/server/network/", "net/minecraft/server/players/", "net/minecraft/server/Services")),
    RECORDS,
    ("decides the format of the world's saved data, and a world has to keep loading after this mixin is gone",
     ("net/minecraft/world/level/storage/", "net/minecraft/world/level/chunk/storage/", "net/minecraft/nbt/", "net/minecraft/util/datafix/",
      "net/minecraft/util/worldupdate/", "net/minecraft/core/registries/", "net/minecraft/core/Registry", "net/minecraft/core/WritableRegistry",
      "net/minecraft/core/MappedRegistry", "net/minecraft/core/DefaultedMappedRegistry", "net/minecraft/core/RegistryAccess", "net/minecraft/core/LayeredRegistryAccess",
      "net/minecraft/core/component/DataComponents", "net/minecraft/resources/RegistryDataLoader", "net/minecraft/server/RegistryLayer",
      "net/minecraft/SharedConstants", "net/minecraft/DetectedVersion", "net/minecraft/WorldVersion", "net/minecraft/world/level/block/Blocks",
      "net/minecraft/world/item/Items", "net/minecraft/world/entity/EntityType", "net/minecraft/world/level/block/entity/BlockEntityType",
      "net/minecraft/world/level/block/state/StateDefinition")),
)

# Only these, because any other annotation from either library might be one nobody here has thought about yet.
ALLOWED_ANNOTATIONS = {
    *(f"{MIXIN}{name}" for name in ("Mixin", "Shadow", "Unique", "Final", "Mutable", "Intrinsic", "Dynamic", "SoftOverride", "gen/Accessor", "gen/Invoker")),
    *(f"{INJECTION}{name}" for name in ("Inject", "At", "Slice", "Desc", "Descriptors", "Next", "Redirect", "ModifyArg", "ModifyArgs",
                                        "ModifyVariable", "ModifyConstant", "Constant", "Coerce", "Surrogate")),
    *(f"{EXTRAS}{name}" for name in ("injector/ModifyExpressionValue", "injector/ModifyReceiver", "injector/ModifyReturnValue", "injector/WrapWithCondition",
                                     "injector/v2/WrapWithCondition", "injector/wrapoperation/WrapOperation", "injector/wrapmethod/WrapMethod",
                                     "sugar/Local", "sugar/Share", "sugar/Cancellable", "expression/Expression", "expression/Expressions",
                                     "expression/Definition", "expression/Definitions")),
}
REFUSED_ANNOTATIONS = {
    f"{MIXIN}Overwrite": "replaces a whole method, which silently undoes every other patch to it, conduit's and Fabric's included. Use "
                         "@Inject at HEAD with cancellable = true, or @WrapMethod, which do the same while leaving those in place",
    f"{MIXIN}Pseudo": "lets a mixin whose target doesn't exist pass without a word, and a mixin here either applies or stops the release",
    f"{MIXIN}Debug": "writes class files to disk",
    f"{INJECTION}Group": "lets an injection find nothing, by counting it together with others",
}
# Any other value would load a class of the mixin's choosing and run it inside the patcher.
INJECTION_POINTS = {"HEAD", "RETURN", "TAIL", "INVOKE", "INVOKE_ASSIGN", "INVOKE_STRING", "FIELD", "NEW", "JUMP", "LOAD", "STORE", "CONSTANT", "MIXINEXTRAS:EXPRESSION"}
LOUD_CAPTURES = {"NO_CAPTURE", "CAPTURE_FAILHARD"}
# These need to say what they mean, or they'd match whatever comes first.
NEEDS_TARGET = {"INVOKE", "INVOKE_ASSIGN", "INVOKE_STRING", "FIELD", "NEW"}
# These run once, as the game starts, and vanilla sets up what's in its registries and saves there. A new block state goes straight into saves.
REFUSED_METHODS = {"<clinit>": "is a static initialiser, which runs once as the game starts, before anything can tell what it did",
                   "createBlockStateDefinition": "adds to what a block's state can be, and that goes into the world's saves and to every client"}
# The patcher takes much more than this: patterns, wildcards, spaces it ignores, a name with no owner. All of those can match a
# name without containing it, and then there's nothing here to check, so only the plain forms are allowed.
_TYPE = r"\[*(?:[BCDFIJSZV]|L[\w$/]+;)"
_SIGNATURE = rf"\((?:{_TYPE})*\){_TYPE}"
_MEMBER = r"[\w$]+|<init>|<clinit>"
_OWNER = r"L[\w$/]+;"
_METHOD_SELECTOR = re.compile(rf"(?:{_OWNER})?(?:{_MEMBER})(?:{_SIGNATURE})?", re.ASCII)
_FULL_TARGET = re.compile(rf"{_OWNER}(?:{_MEMBER})(?:{_SIGNATURE}|:{_TYPE})?", re.ASCII)
_NEW_TARGET = re.compile(rf"{_OWNER}|[\w$]+(/[\w$]+)+", re.ASCII)
_IN_DESCRIPTORS = re.compile(r"L([\w$/]+);", re.ASCII)
_SLASHED = re.compile(r"[\w$]+(?:/[\w$]+)+", re.ASCII)
_DOTTED = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+", re.ASCII)
_CLASS_NAME = re.compile(r"[A-Za-z_$][\w$]*(/[A-Za-z_$][\w$]*)*", re.ASCII)
# Reached by a @Shadow or @Invoker, whose owner is the mixin itself, so the check on what code calls wouldn't see it. Unique names have a $ in them.
_REGISTERING_NAME = re.compile(r"(?:invoke|call)?register", re.ASCII | re.IGNORECASE)


def jar_name(feature_id):
    return f"{JAR_PREFIX}{feature_id}.jar"


def feature_of(jar_path):
    """Which feature a jar's mixins belong to, or None if it isn't a mixin jar. Conduit's jar sits in the same folder."""
    name = jar_path.name
    return name[len(JAR_PREFIX):-len(".jar")] if name.startswith(JAR_PREFIX) and name.endswith(".jar") else None


def mod_id(feature_id):
    return f"{MOD_PREFIX}{feature_id}"


def mixin_package(feature_id):
    return f"gm/feature/{feature_id}/mixin/"


def shared_package(feature_id):
    return f"gm/feature/{feature_id}/shared/"


def crash_marks(feature_id):
    """What a crash report says if it was this feature's mixin. Its handlers are named after the mod, and every crash report
    lists all the mods anyway, so it's the name with what's around it that counts."""
    return (f"gm.feature.{feature_id}.mixin", f"gm.feature.{feature_id}.shared", f"${mod_id(feature_id)}$")


def target_problem(name):
    """Why a mixin may not patch this class, or None. Takes slashes or dots. Everything else may be approved by the owner, but not this."""
    name = name.replace(".", "/")
    if not name.startswith(PATCHABLE):
        return (f"isn't part of the game. A mixin may only patch {PATCHABLE}, because everything else, gm.conduit above all, is "
                "what's watching over what features do, and the owner can't approve this one")
    return None


def protected_target(name):
    return bytecode._refusal(name.replace(".", "/"), REFUSED_TARGETS)


def _is_mixin(parsed):
    return any(annotation.descriptor == f"L{MIXIN}Mixin;" for annotation in parsed.own_annotations)


def mixin_targets(parsed):
    """The classes a @Mixin says it patches, with slashes. A name that isn't a class name is returned too, for the check to refuse."""
    found = []
    for annotation in parsed.own_annotations:
        if annotation.descriptor == f"L{MIXIN}Mixin;":
            for value in annotation.values.get("value", []):
                found.append(value.descriptor[1:-1] if isinstance(value, bytecode.ClassValue) and value.descriptor.startswith("L") else str(value))
            for value in annotation.values.get("targets", []):
                found.append(str(value).replace(".", "/"))
    return found


def describe(feature_id, targets):
    """A mixin jar's own description, as (fabric.mod.json, its mixin config). Here's where the required, defaultRequire and server-only
    are set, and where there's nothing else: no entrypoints, no mixin plugin, no access wideners and no nested jars."""
    package = mixin_package(feature_id)
    names = sorted(name.removeprefix(package).replace("/", ".") for name in targets)
    config = f"{mod_id(feature_id)}.mixins.json"
    # Naming the loader matters: with no version to go by, the patcher falls back on old behaviour, which is looser about what it accepts.
    mod = {"schemaVersion": 1, "id": mod_id(feature_id), "version": "1", "name": f"Mixins of {feature_id}", "environment": "server",
           "mixins": [config], "depends": {"fabricloader": ">=0.20.1", "minecraft": "~26.3", "conduit": "*"},
           "custom": {METADATA_KEY: {name.replace("/", "."): sorted(target.replace("/", ".") for target in found) for name, found in sorted(targets.items())}}}
    settings = {"required": True, "package": package.rstrip("/").replace("/", "."), "compatibilityLevel": "JAVA_25", "mixins": names,
                "injectors": {"defaultRequire": 1}, "overwrites": {"requireAnnotations": True}}
    return (config, (json.dumps(mod, indent=1, sort_keys=True) + "\n").encode(), (json.dumps(settings, indent=1, sort_keys=True) + "\n").encode())


def assemble(built, feature_id, target):
    """Makes the jar that ships from what was compiled: only its classes, with the rest written here. The same classes always make
    the same bytes, because a jar that changes is a restart for everyone on the server."""
    try:
        entries = bytecode.read_jar(built)
    except (bytecode.BadJar, OSError) as error:
        raise GateFailed(GATE, f"{feature_id}'s mixins have a jar that can't be checked: {error}") from error
    classes = []
    for name, data in entries:
        if name.endswith(".class"):
            classes.append((name, data))
        elif not name.endswith("/") and name != "META-INF/MANIFEST.MF":
            raise GateFailed(GATE, f"{feature_id}'s mixins can't ship {name}. The mixins folder holds only Java classes, and what the "
                                   "game needs to know about them is written for you, so take out src/main/resources")
    targets = {}
    for name, data in classes:
        try:
            parsed = bytecode.parse_class(data)
        except bytecode.BadClass:
            continue  # The check that comes next says why.
        if _is_mixin(parsed) and name.startswith(mixin_package(feature_id)):
            targets[name.removesuffix(".class")] = mixin_targets(parsed)
    config, mod, settings = describe(feature_id, targets)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = [*classes, ("fabric.mod.json", mod), (config, settings)]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(written, key=lambda entry: entry[0]):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return target


def _names_in(text):
    yield from _SLASHED.findall(text)
    for match in _DOTTED.finditer(text):
        # Any leading part of a dotted name could be the class, with the rest being a member of it.
        parts = match.group(0).split(".")
        for end in range(2, len(parts) + 1):
            yield "/".join(parts[:end])


def _check_text(text, found, where):
    """Text in a mixin's annotations names things the code around it doesn't have to, so it answers to the same lists as the code does.
    Written as a descriptor it's certainly a class. Anything else might just be text that looks like one."""
    for name in _IN_DESCRIPTORS.findall(text):
        why = bytecode._class_problem(name, "mixins")
        if why:
            found(name, why, where)
    for name in _names_in(text):
        why = bytecode._class_problem(name, "mixin_text")
        if why:
            found(name, why, where)


def _check_target(text, found, where):
    """Where an injection goes. Going round a call to a chunk is as good as patching the chunk, so it can't be used to change a block unrecorded."""
    for name in _IN_DESCRIPTORS.findall(text.split("(", 1)[0]):
        why = bytecode._refusal(name, (RECORDS,))
        if why:
            found(f"@At target {text!r}", why, where)


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)


def _classes(value):
    if isinstance(value, bytecode.ClassValue):
        yield value.descriptor
    elif isinstance(value, list):
        for item in value:
            yield from _classes(item)


def _check_annotation(annotation, found, where):
    kind = annotation.descriptor[1:-1] if annotation.descriptor.startswith("L") else annotation.descriptor
    short = "@" + kind.rsplit("/", 1)[-1]
    in_library = kind.startswith((MIXIN, EXTRAS))
    if kind in REFUSED_ANNOTATIONS:
        found(short, REFUSED_ANNOTATIONS[kind], where)
    elif in_library and kind not in ALLOWED_ANNOTATIONS:
        found(short, "isn't one of the annotations mixins here may use, which are in docs/feature-format.md", where)
    # Whatever a class value in any annotation names, it's named in a class that's going to run.
    for value in annotation.values.values():
        for descriptor in _classes(value):
            for name in bytecode._IN_DESCRIPTOR.findall(descriptor):
                why = bytecode._class_problem(name, "mixins")
                if why:
                    found(name, why, where)
    if not in_library:
        return

    values = annotation.values
    for value in values.values():
        for text in _texts(value):
            _check_text(text, found, where)
    if isinstance(values.get("require"), int) and values["require"] < 1:
        found(f"{short} require = {values['require']}", "lets the injection find nothing and say nothing. It has to find what it's patching, or the release stops", where)
    if values.get("constraints"):
        found(f"{short} constraints", "can quietly skip the injection", where)
    if kind == f"{MIXIN}Mixin" and "priority" in values:
        found("@Mixin priority", "orders this mixin against the others on the server, conduit's included, and nothing here should depend on that", where)
    if "order" in values:
        found(f"{short} order", "orders this injection against the others on the server, conduit's included, and nothing here should depend on that", where)
    locals_captured = values.get("locals")
    if isinstance(locals_captured, bytecode.EnumValue) and locals_captured.name not in LOUD_CAPTURES:
        found(f"{short} locals = {locals_captured.name}", "can skip the injection, or fail only once it runs. Use @Local, or CAPTURE_FAILHARD", where)
    if kind == f"{EXTRAS}expression/Definition":
        # Here, method and field say what's being matched, the same as an @At's target.
        for target in [*_texts(values.get("method")), *_texts(values.get("field"))]:
            if not _FULL_TARGET.fullmatch(target):
                found(f"@Definition {target!r}", "has to say in full what it means, as Lowner;name(arguments)result, so what it reaches can be checked", where)
            _check_target(target, found, where)
        return
    if kind == f"{MIXIN}Shadow" and (values.get("prefix") or values.get("aliases")):
        found("@Shadow prefix or aliases", "makes a shadow's name something other than what it's reaching, so what it reaches can't be checked", where)
    # @Inject(target = @Desc("<clinit>")) is another way to write method = "<clinit>".
    for method in [*_texts(values.get("method")), *(_texts(values.get("value")) if kind == f"{INJECTION}Desc" else ())]:
        if not _METHOD_SELECTOR.fullmatch(method):
            found(f"method {method!r}", "has to be written out as a plain name, or a full Lowner;name(arguments)result. A pattern or a wildcard can match a name without containing it", where)
        for name, why in REFUSED_METHODS.items():
            if name in method:
                found(f"method {method!r}", why, where)
    if kind == f"{MIXIN}gen/Invoker" and _REGISTERING_NAME.match(next(_texts(values.get("value")), "")):
        found(f"@Invoker {values['value']!r}", bytecode.REGISTERS[0], where)
    if kind == f"{INJECTION}At":
        point = values.get("value")
        if point not in INJECTION_POINTS:
            found(f"@At({point!r})", f"isn't an injection point this game has, and any other name loads a class to run it in the patcher. They are: {', '.join(sorted(INJECTION_POINTS))}", where)
        if values.get("unsafe"):
            found("@At unsafe", "injects before a constructor has set the object up, which the game can't recover from", where)
        target = values.get("target", "")
        if target and not (_FULL_TARGET.fullmatch(target) or (point == "NEW" and _NEW_TARGET.fullmatch(target))):
            found(f"@At target {target!r}", "has to say in full what it means, as Lowner;name(arguments)result, so what it reaches can be checked", where)
        _check_target(target, found, where)
        described = values.get("desc")
        if point in NEEDS_TARGET and not target and not (isinstance(described, bytecode.Annotation) and "owner" in described.values):
            found(f"@At({point!r}) with no target", "would match the first thing of that kind it finds, whatever that is, so say which one you mean, owner included", where)


def scan(entries, feature_id, approved):
    """What's wrong with a mixin jar, as bytecode.py reports it."""
    problems = {}
    own = f"gm/feature/{feature_id}/"
    package, shared = mixin_package(feature_id), shared_package(feature_id)

    def found(reference, why, where=None):
        if reference not in approved:
            wheres = problems.setdefault(reference, (why, set()))[1]
            if where:
                wheres.add(where)

    def refused(reference, why, where=None):
        """For what the owner's approvals don't get to decide."""
        problems.setdefault(reference, (why, set()))[1].update([where] if where else [])

    parsed_classes, texts, seen, targets = [], {}, set(), {}
    for name, data in entries:
        if name in seen:
            found(name, "appears twice in the jar, so which one runs depends on the reader")
        seen.add(name)
        if name.endswith("/"):
            if data:
                found(name, "is a directory entry holding data")
        elif name.endswith(".class"):
            if not (name.startswith((package, shared)) and bytecode._CLASS_PATH.fullmatch(name)):
                found(name, f"is outside the mixins' packages. Mixins go under {package} and classes they share with the feature's server module under {shared}")
            try:
                parsed = bytecode.parse_class(data)
            except bytecode.BadClass as error:
                found(name, f"can't be checked: {error}")
                continue
            if f"{parsed.name}.class" != name:
                found(name, f"holds class {parsed.name}, which doesn't match its path")
            parsed_classes.append(parsed)
        else:
            texts[name] = data

    for parsed in parsed_classes:
        where = parsed.name
        if _is_mixin(parsed):
            targets[parsed.name] = mixin_targets(parsed)
            if not parsed.name.startswith(package):
                found(parsed.name, f"is a mixin outside {package}, so the game wouldn't apply it", where)
            if not targets[parsed.name]:
                found(parsed.name, "is a mixin with no target", where)
            for target in targets[parsed.name]:
                if not _CLASS_NAME.fullmatch(target):
                    refused(f"target {target}", "isn't the name of a class", where)
                elif target_problem(target):
                    refused(f"target {target}", target_problem(target), where)
                elif protected_target(target):
                    found(f"target {target}", protected_target(target), where)
        elif parsed.name.startswith(package) and "$" not in parsed.name:
            # The patcher refuses to let the game load anything in its package, so it would fail the moment something reached for it.
            found(parsed.name, f"is in the mixins' package without being a mixin. Put it in {shared}", where)
        for method in parsed.methods:
            if _REGISTERING_NAME.match(method):
                found(f"{parsed.name}.{method}", bytecode.REGISTERS[0], where)
        for annotation in [*parsed.own_annotations, *parsed.annotations]:
            for each in annotation.and_nested():
                _check_annotation(each, found, where)

    if len(targets) > MOST_MIXINS_A_FEATURE:
        refused(f"{len(targets)} mixins", f"is more than the {MOST_MIXINS_A_FEATURE} one feature can have. If that's what it takes, a hook is missing, so ask for it in host_requests")
    if not targets:
        found("mixins", f"there are no classes with @Mixin under {package}, so this folder has nothing to do")

    # The agent's build only supplies classes, so these can only differ if something's got in another way. Still, they're what runs first.
    config, mod, settings = describe(feature_id, {name: found_targets for name, found_targets in targets.items() if name.startswith(package)})
    expected = {"fabric.mod.json": mod, config: settings, "META-INF/MANIFEST.MF": None}
    for name, data in texts.items():
        if name not in expected:
            refused(name, "isn't a class, and nothing else may be in a mixin jar")
        elif expected[name] is not None and data != expected[name]:
            refused(name, "isn't what the broker wrote")
    for name in ("fabric.mod.json", config):
        if name not in texts:
            refused(name, "is missing")

    bytecode.check_references(parsed_classes, "mixins", own, approved, found)
    return problems


def check_jar(path, feature_id):
    """Raises GateFailed if a mixin jar holds anything but mixins this world can take."""
    label = f"{feature_id}'s mixins"
    if not FABRIC_ID.fullmatch(mod_id(feature_id)):
        raise GateFailed(GATE, f"{label} can't ship, because {mod_id(feature_id)} is too long to be a mod's id. Use a shorter feature id")
    try:
        entries = bytecode.read_jar(path)
    except (bytecode.BadJar, OSError) as error:
        raise GateFailed(GATE, f"{label} have a jar that can't be checked: {error}") from error
    problems = scan(entries, feature_id, bytecode._approved(feature_id, "mixins"))
    if problems:
        bytecode.report_problems(label, problems)
