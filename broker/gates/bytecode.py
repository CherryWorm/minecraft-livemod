"""What can a module's code touch? Reads the class files themselves, because Java 25 has no in-process
sandbox, so what's in the jar is what runs.

Client modules run on friends' PCs, so they get an allowlist: what isn't named here is refused, and a new
Minecraft version can't quietly widen what they reach. Server modules need much of Minecraft and already run
in a locked-down container, so they get a denylist. A method on an allowed class can still be the dangerous
part (Class.forName, Minecraft.getUser), so members are checked as well as classes, and classes are also
collected from every descriptor: calling a method that returns a File holds a File, even if it's never named.

Exceptions are read from beside this file, in the trusted checkout. The agent's repository only supplies
features (see broker/daemon.py), so it can't approve its own.
"""
import collections
import json
import pathlib
import re
import struct
import zlib

from broker.gates import GateFailed

GATE = "bytecode"
EXCEPTIONS = pathlib.Path(__file__).with_name("bytecode_exceptions.json")
ACC_NATIVE = 0x0100
MAX_JAR_BYTES = 64 * 1024 * 1024
MAX_REPORTED = 25

# Rules: a name ending in / is a package, one ending in * is a prefix, and anything else is that class and its
# nested classes. Exact on purpose: a plain prefix for java/lang/Runtime would also refuse RuntimeException.
FILES = ("touches files, and modules must keep state in the game's own storage",
         ("java/io/File*", "java/io/RandomAccessFile", "java/nio/file/", "java/nio/channels/",
          "java/util/logging/FileHandler", "java/util/zip/ZipFile", "java/util/jar/JarFile"))
# Only these parts of Netty: Minecraft's own packet code passes ByteBuf around, and that's harmless by itself.
NETWORK = ("opens network connections",
           ("java/net/", "javax/net/", "jdk/net/", "java/rmi/", "javax/naming/", "io/netty/bootstrap/", "io/netty/channel/",
            "com/sun/net/"))
PROCESSES = ("starts or controls processes",
             ("java/lang/Runtime", "java/lang/ProcessBuilder", "java/lang/Process", "java/lang/ProcessHandle"))
REFLECTION = ("uses reflection, which could reach everything else on this list",
              ("java/lang/reflect/", "java/lang/StackWalker"))
CLASS_LOADING = ("loads code at runtime",
                 ("java/lang/ClassLoader", "java/security/SecureClassLoader", "java/lang/Module", "java/lang/ModuleLayer",
                  "java/util/ServiceLoader", "java/lang/instrument/", "javax/script/", "javax/tools/"))
INTERNALS = ("reaches JVM internals such as Unsafe", ("sun/", "jdk/", "com/sun/"))
# Java 22 and later can call native code with java.lang.foreign, with no native method anywhere to spot.
NATIVE = ("runs native code", ("java/lang/foreign/", "org/lwjgl/", "com/sun/jna/"))
THREADS = ("starts threads, and module code should run in its tick or render callback",
           ("java/lang/Thread", "java/lang/ThreadGroup", "java/util/Timer", "java/util/TimerTask",
            "java/util/concurrent/Executor*", "java/util/concurrent/ScheduledExecutorService",
            "java/util/concurrent/ScheduledThreadPoolExecutor", "java/util/concurrent/ThreadPoolExecutor",
            "java/util/concurrent/ThreadFactory", "java/util/concurrent/ForkJoin*", "java/util/concurrent/CompletableFuture"))
# From searching the 26.3 client jar for classes naming User or its token getters. The rest of what names User, like
# the splash text and the win screen, is off the client list anyway, and of all of them only Minecraft is on it.
SESSION = ("can reach the player's session token",
           ("net/minecraft/client/User", "net/minecraft/client/main/", "net/minecraft/server/Services",
            "net/minecraft/client/multiplayer/ClientHandshakePacketListenerImpl",
            "net/minecraft/client/multiplayer/ProfileKeyPairManager", "net/minecraft/client/multiplayer/AccountProfileKeyPairManager",
            "com/mojang/authlib/", "com/mojang/realmsclient/"))
# The patcher and the loader's insides. Asking for one more mixin config at runtime, or for the class bytes of anything, gets
# around everything else on this list. A mixin can use the few parts of it that it's handed: see MIXIN_USABLE.
PATCHER = ("reaches the code patcher or the mod loader's insides, which run before anything here can check them",
           ("org/spongepowered/", "org/objectweb/", "com/llamalad7/", "net/fabricmc/loader/impl/"))
# These do the refused things above on a caller's behalf, from plain strings, so nothing in a descriptor gives them away. The
# game's own libraries are all on the server's classpath. oshi runs commands, and Expression calls any method by name.
WRAPPERS = ("does files, processes or reflection for you, from plain text, so it counts as those",
            ("oshi/", "org/apache/commons/io/", "org/apache/commons/lang3/reflect/", "org/apache/commons/lang3/ClassUtils",
             "org/apache/commons/lang3/SerializationUtils", "com/google/common/io/", "com/google/common/reflect/",
             "org/apache/logging/log4j/core/", "org/apache/logging/log4j/util/LoaderUtil", "io/netty/util/internal/",
             "it/unimi/dsi/fastutil/io/", "java/beans/", "javax/management/", "java/lang/management/", "java/sql/", "javax/sql/",
             "java/util/prefs/", "java/util/ResourceBundle", "java/io/ObjectInputStream", "java/awt/", "javax/swing/", "javax/imageio/",
             "javax/xml/", "org/xml/", "org/w3c/"))
# The player's own game fetches or connects to whatever these name, which shows their address to whoever's there.
SENDS_AWAY = ("sends players' games to an address of its own choosing",
              ("net/minecraft/network/protocol/common/ClientboundResourcePackPushPacket", "net/minecraft/network/protocol/common/ClientboundTransferPacket"))
SERVER_REFUSED = (FILES, NETWORK, PROCESSES, REFLECTION, CLASS_LOADING, INTERNALS, NATIVE, THREADS, PATCHER, WRAPPERS, SENDS_AWAY)
CLIENT_REFUSED = (*SERVER_REFUSED, SESSION)

# What a mixin's own code is handed. Its annotations are checked apart from this, in gates/mixins.py. @At and @Constant
# are here for their nested enums, which javac names as classes.
MIXIN_USABLE = ("org/spongepowered/asm/mixin/injection/callback/", "org/spongepowered/asm/mixin/injection/invoke/arg/Args",
                "org/spongepowered/asm/mixin/injection/At", "org/spongepowered/asm/mixin/injection/Constant",
                "com/llamalad7/mixinextras/injector/wrapoperation/Operation", "com/llamalad7/mixinextras/sugar/ref/")
# A mixin gets a list rather than the module's denylist, because it sits on the game's own loader with every library there is, and
# a denylist can't know them all. The refusals below and the module's rules still apply inside these.
MIXIN_LIBRARIES = ("java/lang/", "java/util/", "java/math/", "java/time/", "java/text/", "java/io/", "java/nio/", "javax/annotation/",
                   "net/minecraft/", "gm/", "com/mojang/serialization/", "com/mojang/datafixers/util/", "com/mojang/datafixers/kinds/",
                   "com/mojang/math/", "com/mojang/logging/", "com/mojang/authlib/GameProfile", "com/google/common/collect/",
                   "com/google/common/base/", "com/google/gson/", "it/unimi/dsi/fastutil/", "org/joml/", "org/slf4j/", "org/jspecify/",
                   "org/jetbrains/annotations/", "io/netty/buffer/", "net/fabricmc/fabric/api/", "eu/pb4/polymer/")
# Registries are still open while the game starts, which is when a mixin can run and a module can't. Anything registered
# there ends up in the world's data under a name that's gone when the mixin is. Slots are how features add things.
REGISTERS = ("registers something the world can't load without. Blocks, items and mobs go through slots in feature.json, and "
             "attachments are saved into chunks, so removing the mixin would leave data the game throws away",
             ("net/minecraft/core/MappedRegistry", "net/minecraft/core/DefaultedMappedRegistry", "net/minecraft/core/RegistrationInfo",
              "net/minecraft/world/level/block/state/StateDefinition", "net/fabricmc/fabric/api/attachment/",
              "net/fabricmc/fabric/api/event/registry/", "net/fabricmc/fabric/api/object/builder/"))
# A command run from code counts as the console, which includes the ones that start the agent again after its owner has stopped it.
COMMANDS = ("runs server commands, which a mixin has no need to and which could undo the kill switch",
            ("net/minecraft/commands/Commands", "net/minecraft/commands/execution/", "net/minecraft/server/commands/",
             "net/minecraft/server/dedicated/", "net/minecraft/server/rcon/", "net/minecraft/server/ServerFunctionManager", "com/mojang/brigadier/"))
UNRECORDED = ("changes blocks without leaving the record that protects players' builds, so use the level's own setBlock",
              ("net/minecraft/world/level/chunk/LevelChunkSection", "net/minecraft/world/level/chunk/PalettedContainer"))
HIDES_CRASHES = ("is how a crash gets noticed, and rollback depends on that", ("net/minecraft/CrashReport", "net/minecraft/ReportedException"))
MIXIN_REFUSED = (REGISTERS, COMMANDS, UNRECORDED, HIDES_CRASHES)
REGISTERING_OWNERS = ("net/minecraft/core/Registry", "net/minecraft/core/WritableRegistry", "net/minecraft/world/level/block/Blocks",
                      "net/minecraft/world/item/Items", "net/minecraft/world/entity/EntityType",
                      "net/minecraft/world/level/block/entity/BlockEntityType")
MIXIN_REFUSED_MEMBERS = {
    # A server that stops itself on purpose writes no crash report, and these can also take a world down without saving it.
    "net/minecraft/server/MinecraftServer": ({"halt", "stopServer", "close", "getCommands", "getFunctions", "createCommandSourceStack"},
                                             "stops the server or runs commands, and nothing a mixin does needs that"),
    "java/lang/Throwable": ({"setStackTrace"}, "takes away what says where a crash came from"),
}

# Client modules draw HUDs and effects and help on inventory screens, so this is what those need and nothing else. It stays
# narrow because widening it later only costs a release, and something unsafe that shipped can't be recalled from friends' PCs.
# Worth knowing what isn't here: LocalPlayer and ClientLevel, because they can act as the player and send packets,
# org/joml, which GuiGraphicsExtractor.pose() needs, and java/lang/System. A feature that wants one can ask.
CLIENT_CLASSES = {
    *(f"java/lang/{name}" for name in (
        "Object String StringBuilder CharSequence Comparable Iterable Runnable Math Number Record Enum Class Void "
        "Boolean Byte Character Short Integer Long Float Double "
        "Throwable Exception RuntimeException Error AssertionError ArithmeticException ClassCastException "
        "IllegalArgumentException IllegalStateException IndexOutOfBoundsException ArrayIndexOutOfBoundsException "
        "StringIndexOutOfBoundsException NegativeArraySizeException NullPointerException NumberFormatException "
        "UnsupportedOperationException "
        # javac adds these two on its own, for switches over enums and sealed types.
        "MatchException NoSuchFieldError").split()),
    # Named one by one, because java/util also holds Timer, ServiceLoader, Scanner and Formatter, which can
    # open a file from a plain String. java/util/stream is out too, for its parallel streams.
    *(f"java/util/{name}" for name in (
        "Collection List ArrayList LinkedList Map Map$Entry HashMap LinkedHashMap TreeMap SortedMap NavigableMap "
        "Set HashSet LinkedHashSet TreeSet SortedSet NavigableSet Queue Deque ArrayDeque PriorityQueue "
        "Iterator ListIterator Collections Arrays Objects Comparator Optional OptionalInt OptionalLong OptionalDouble "
        "EnumMap EnumSet BitSet StringJoiner NoSuchElementException ConcurrentModificationException").split()),
    # Rendering and GUI. Checked against the real 26.3 client jar by test_bytecode.
    "net/minecraft/client/DeltaTracker", "net/minecraft/client/gui/GuiGraphicsExtractor", "net/minecraft/client/gui/Font",
    "net/fabricmc/fabric/api/client/rendering/v1/hud/HudElement",
    # Text.
    "net/minecraft/network/chat/Component", "net/minecraft/network/chat/MutableComponent",
    "net/minecraft/network/chat/FormattedText", "net/minecraft/network/chat/Style", "net/minecraft/network/chat/TextColor",
    "net/minecraft/util/FormattedCharSequence", "net/minecraft/ChatFormatting", "net/minecraft/resources/Identifier",
    # Math.
    "net/minecraft/util/Mth", "net/minecraft/util/ARGB", "net/minecraft/util/CommonColors",
    "net/minecraft/world/phys/Vec2", "net/minecraft/world/phys/Vec3",
    # A tick callback is handed a Minecraft, so the class must be nameable, but see CLIENT_MEMBERS.
    "net/minecraft/client/Minecraft",
    # An inventory view hands these out, and drawing can take them, but see CLIENT_MEMBERS.
    "net/minecraft/world/item/ItemStack",
}
CLIENT_PREFIXES = ("gm/companion/api/", "java/util/function/")

# Every lambda and string concatenation names these in its bootstrap, whether or not it uses them directly.
# A lookup or a method handle is reflection by another name, so they may appear but nothing may be called on them.
_NAMEABLE_ONLY = ("java/lang/invoke/MethodHandles", "java/lang/invoke/MethodHandles$Lookup", "java/lang/invoke/MethodHandle",
                  "java/lang/invoke/MethodType", "java/lang/invoke/CallSite", "java/lang/invoke/TypeDescriptor")
# What javac's own bootstraps call: lambdas, string concatenation, record methods and pattern switches.
BOOTSTRAPS = {"java/lang/invoke/LambdaMetafactory.metafactory", "java/lang/invoke/LambdaMetafactory.altMetafactory",
              "java/lang/invoke/StringConcatFactory.makeConcat", "java/lang/invoke/StringConcatFactory.makeConcatWithConstants",
              "java/lang/runtime/ObjectMethods.bootstrap", "java/lang/runtime/SwitchBootstraps.typeSwitch",
              "java/lang/runtime/SwitchBootstraps.enumSwitch"}
# Classes where only the listed members may be used, on both sides.
LIMITED_MEMBERS = {
    # Class is in every enum and class literal, but nearly everything else on it is reflection or class loading.
    "java/lang/Class": {"getName", "getSimpleName", "getTypeName", "isInstance", "isAssignableFrom", "cast",
                        "isEnum", "isRecord", "isArray", "isInterface", "desiredAssertionStatus",
                        "getClass", "hashCode", "equals", "toString"},
    **{name: set() for name in _NAMEABLE_ONLY},
}
for _bootstrap in BOOTSTRAPS:
    _owner, _name = _bootstrap.split(".")
    LIMITED_MEMBERS.setdefault(_owner, set()).add(_name)
# Minecraft is the door to everything: getUser() is the session token, stop() closes the game, gameDirectory is a
# File and getConnection() sends packets. A list of what's allowed can't miss one the way a list of what isn't could.
CLIENT_MEMBERS = {**LIMITED_MEMBERS, "net/minecraft/client/Minecraft": {"getInstance", "font", "getFps", "getDeltaTracker"},
                  # Only for looking. A stack in a menu is the game's own, and changing it would show what the server hasn't said.
                  "net/minecraft/world/item/ItemStack": {"EMPTY", "isEmpty", "getCount", "getMaxStackSize", "isStackable", "getHoverName",
                                                         "isSameItem", "isSameItemSameComponents", "isDamageableItem", "isDamaged",
                                                         "getDamageValue", "getMaxDamage"}}
# Members refused on classes that are otherwise fine.
REFUSED_MEMBERS = {
    "java/lang/System": ({"exit", "load", "loadLibrary", "getenv", "setProperty", "setProperties", "clearProperty",
                          "setIn", "setOut", "setErr", "setSecurityManager"},
                         "reaches the process, its environment or native code"),
    # These three read system properties, which is surprising for number parsing.
    "java/lang/Boolean": ({"getBoolean"}, "reads system properties"),
    "java/lang/Integer": ({"getInteger"}, "reads system properties"),
    "java/lang/Long": ({"getLong"}, "reads system properties"),
}
# These open a file when constructed from a String, with nothing in the descriptor to show it.
_FILE_NAME_CONSTRUCTORS = {"java/io/PrintWriter", "java/io/PrintStream", "java/util/Formatter"}

# The companion repeats a cruder check of its own. ModuleVerifier refuses a jar if any constant in any class contains
# one of these, including plain strings and method names, and the owner can't approve past that from here. Mirrored
# so the agent hears about it now, not from a module that silently fails on every PC. test_bytecode keeps this in step.
COMPANION_REFUSES = ("java/io/File", "java/io/RandomAccessFile", "java/nio/file/", "java/net/", "java/lang/Runtime",
                     "java/lang/ProcessBuilder", "java/lang/reflect/", "java/lang/ClassLoader",
                     "sun/", "jdk/internal/", "org/lwjgl/", "net/minecraft/client/User", "java/lang/Thread")
COMPANION_REFUSED_NAMES = {"forName", "getDeclaredMethod", "loadLibrary", "lookup", "publicLookup", "privateLookupIn"}
COMPANION_IGNORES = "java/lang/RuntimeException"

ANNOTATIONS = {"RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"}
PARAMETER_ANNOTATIONS = {"RuntimeVisibleParameterAnnotations", "RuntimeInvisibleParameterAnnotations"}

_CLASS_PATH = re.compile(r"[A-Za-z_$][\w$]*(/[A-Za-z_$][\w$]*)*\.class", re.ASCII)
_IN_DESCRIPTOR = re.compile(r"L([^;]+);")
_ENTRY_LINE = re.compile(r"entry\s*[=:]\s*([\w.$]+)", re.ASCII)


class BadClass(Exception):
    """A class file this parser can't read. It's refused, because nobody has checked what it says."""


class BadJar(Exception):
    """A jar the game wouldn't read the way this does, or at all."""


ClassValue = collections.namedtuple("ClassValue", "descriptor")
EnumValue = collections.namedtuple("EnumValue", "descriptor name")


class Annotation:
    """One annotation. Its values are text, numbers, a ClassValue, an EnumValue, another Annotation, or a list of those."""

    def __init__(self, descriptor, values):
        self.descriptor = descriptor
        self.values = values

    def and_nested(self):
        """This one and all those inside it, because @At and @Slice sit inside @Inject."""
        found = [self]

        def walk(value):
            if isinstance(value, Annotation):
                found.extend(value.and_nested())
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        for value in self.values.values():
            walk(value)
        return found


class ClassFile:
    """What one class file refers to."""

    def __init__(self):
        self.name = None
        self.parents = []
        self.classes = set()
        self.members = set()
        self.natives = []
        self.bootstraps = []
        self.texts = []
        self.annotations = []
        self.own_annotations = []
        self.methods = []


def _decode(raw):
    """Decodes modified UTF-8 by hand, because bytes.decode refuses what the JVM accepts. Old class versions may
    spell "/" as an overlong two-byte form, so a name must be read as the JVM reads it or it could hide."""
    if raw.isascii():
        return raw.decode("ascii")
    chars, at = [], 0
    while at < len(raw):
        byte = raw[at]
        if byte < 0x80:
            chars.append(byte)
            at += 1
        elif byte >> 5 == 0b110 and raw[at + 1] >> 6 == 0b10:
            chars.append((byte & 0x1F) << 6 | raw[at + 1] & 0x3F)
            at += 2
        elif byte >> 4 == 0b1110 and raw[at + 1] >> 6 == 0b10 and raw[at + 2] >> 6 == 0b10:
            chars.append((byte & 0x0F) << 12 | (raw[at + 1] & 0x3F) << 6 | raw[at + 2] & 0x3F)
            at += 3
        else:
            raise BadClass("a constant isn't valid modified UTF-8")
    return "".join(map(chr, chars))


def _read_pool(data):
    """Returns the constant pool and where it ends. Longs and doubles take two slots, a quirk from the first JVM."""
    count = struct.unpack_from(">H", data, 8)[0]
    pool, index, at = {}, 1, 10
    while index < count:
        tag = data[at]
        at += 1
        if tag == 1:
            length = struct.unpack_from(">H", data, at)[0]
            if at + 2 + length > len(data):
                raise BadClass("a constant runs past the end of the file")
            pool[index] = (tag, _decode(data[at + 2:at + 2 + length]))
            at += 2 + length
        elif tag == 3:
            # Annotations keep their numbers here, and a mixin's require is one of them.
            pool[index] = (tag, struct.unpack_from(">i", data, at)[0])
            at += 4
        elif tag == 4:
            at += 4
        elif tag in (5, 6):
            at += 8
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            pool[index] = (tag, struct.unpack_from(">H", data, at)[0])
            at += 2
        elif tag in (9, 10, 11, 12, 17, 18):
            pool[index] = (tag, *struct.unpack_from(">HH", data, at))
            at += 4
        elif tag == 15:
            pool[index] = (tag, data[at], struct.unpack_from(">H", data, at + 1)[0])
            at += 3
        else:
            raise BadClass(f"unknown constant tag {tag}")
        index += 1
    return pool, at


def _parse(data):
    if data[:4] != b"\xca\xfe\xba\xbe":
        raise BadClass("it doesn't start like a class file")
    pool, at = _read_pool(data)
    parsed = ClassFile()

    def utf8(index):
        tag, text = pool[index]
        if tag != 1:
            raise BadClass("a constant points at the wrong kind of entry")
        return text

    def class_name(index):
        tag, name_index = pool[index]
        if tag != 7:
            raise BadClass("a constant points at the wrong kind of entry")
        return utf8(name_index)

    def member(entry):
        _, owner, name_and_type = entry
        _, name, descriptor = pool[name_and_type]
        return class_name(owner), utf8(name), utf8(descriptor)

    for entry in pool.values():
        tag = entry[0]
        if tag == 1:
            parsed.texts.append(entry[1])
        elif tag == 7:
            # An array type is its own class entry, so [Ljava/io/File; has to count as java/io/File.
            name = utf8(entry[1])
            parsed.classes.update(_IN_DESCRIPTOR.findall(name) if name.startswith("[") else [name])
        elif tag == 12:
            parsed.classes.update(_IN_DESCRIPTOR.findall(utf8(entry[2])))
        elif tag == 16:
            parsed.classes.update(_IN_DESCRIPTOR.findall(utf8(entry[1])))
        elif tag in (9, 10, 11):
            found = member(entry)
            # An owner starting with [ is an array's clone(). Its element type is a class entry already.
            if not found[0].startswith("["):
                parsed.members.add(found)

    this_class, super_class, interfaces = struct.unpack_from(">HHH", data, at + 2)
    parsed.name = class_name(this_class)
    parsed.parents = [class_name(super_class)] if super_class else []
    at += 8
    for _ in range(interfaces):
        parsed.parents.append(class_name(struct.unpack_from(">H", data, at)[0]))
        at += 2

    def annotation(position):
        descriptor, pairs = struct.unpack_from(">HH", data, position)
        position += 4
        values = {}
        for _ in range(pairs):
            name = utf8(struct.unpack_from(">H", data, position)[0])
            # The patcher reads the first of these and a dict keeps the last, so a second could say something else to each of them.
            if name in values:
                raise BadClass(f"an annotation says what {name} is twice")
            values[name], position = element(position + 2)
        return Annotation(utf8(descriptor), values), position

    def element(position):
        tag = chr(data[position])
        position += 1
        if tag == "@":
            return annotation(position)
        if tag == "[":
            items = []
            count = struct.unpack_from(">H", data, position)[0]
            position += 2
            for _ in range(count):
                item, position = element(position)
                items.append(item)
            return items, position
        if tag == "e":
            descriptor, name = struct.unpack_from(">HH", data, position)
            return EnumValue(utf8(descriptor), utf8(name)), position + 4
        index = struct.unpack_from(">H", data, position)[0]
        if tag == "c":
            return ClassValue(utf8(index)), position + 2
        if tag == "s":
            return utf8(index), position + 2
        if tag not in "BCDFIJSZ":
            raise BadClass(f"an annotation has a value of an unknown kind, {tag!r}")
        # Longs, floats and doubles aren't kept, and none of the checks need one.
        return (pool[index][1] if tag in "BCISZ" else None), position + 2

    def read_annotations(name, position, into):
        count = 1
        if name in PARAMETER_ANNOTATIONS:
            count = data[position]
            position += 1
        for _ in range(count):
            total = struct.unpack_from(">H", data, position)[0]
            position += 2
            for _ in range(total):
                found, position = annotation(position)
                into.append(found)

    def read_attributes(position, into):
        """Every copy of an attribute counts. Class readers differ over which one wins, so a second one mustn't hide anything."""
        total = struct.unpack_from(">H", data, position)[0]
        position += 2
        for _ in range(total):
            name = utf8(struct.unpack_from(">H", data, position)[0])
            if name in ANNOTATIONS or name in PARAMETER_ANNOTATIONS:
                read_annotations(name, position + 6, into)
            position += 6 + struct.unpack_from(">I", data, position + 2)[0]
        return position

    # Declared fields and methods aren't in the constant pool's NameAndType entries, so a field of a banned type
    # or a native method would be invisible to a scan of the pool alone.
    for is_method in (False, True):
        total = struct.unpack_from(">H", data, at)[0]
        at += 2
        for _ in range(total):
            flags, name_index, descriptor_index = struct.unpack_from(">HHH", data, at)
            parsed.classes.update(_IN_DESCRIPTOR.findall(utf8(descriptor_index)))
            if is_method:
                parsed.methods.append(utf8(name_index))
            if is_method and flags & ACC_NATIVE:
                parsed.natives.append(utf8(name_index))
            at = read_attributes(at + 6, parsed.annotations)

    total = struct.unpack_from(">H", data, at)[0]
    at += 2
    for _ in range(total):
        name_index, length = struct.unpack_from(">HI", data, at)
        if utf8(name_index) == "BootstrapMethods":
            methods = struct.unpack_from(">H", data, at + 6)[0]
            position = at + 8
            for _ in range(methods):
                handle, arguments = struct.unpack_from(">HH", data, position)
                owner, name, _ = member(pool[pool[handle][2]])
                parsed.bootstraps.append(f"{owner}.{name}")
                position += 4 + 2 * arguments
        elif utf8(name_index) in ANNOTATIONS:
            read_annotations(utf8(name_index), at + 6, parsed.own_annotations)
        at += 6 + length
    if at != len(data):
        raise BadClass("its length doesn't add up")
    return parsed


def parse_class(data):
    """Reads one class file. Raises BadClass for anything not understood, rather than guessing."""
    try:
        return _parse(data)
    except (struct.error, IndexError, KeyError, TypeError, ValueError, RecursionError) as error:
        raise BadClass(f"it's malformed: {error}") from error


def read_jar(path):
    """Returns each entry as (name, bytes), read the way the game reads a jar.

    The module hosts and ModuleVerifier use JarInputStream, which walks entries in file order and never looks at
    the central directory that zipfile trusts. A crafted jar can show those two different sets of entries, so
    reading it any other way would mean checking one set of classes and running another.
    """
    raw = pathlib.Path(path).read_bytes()
    entries, at, total = [], 0, 0
    try:
        while raw[at:at + 4] == b"PK\x03\x04":
            flags, method, _, _, _, packed, size, name_length, extra_length = struct.unpack_from("<HHHHIIIHH", raw, at + 6)
            name = raw[at + 30:at + 30 + name_length].decode("utf-8")
            start = at + 30 + name_length + extra_length
            if flags & 1:
                raise BadJar(f"{name} is encrypted")
            if method == 8:
                inflater = zlib.decompressobj(-15)
                data = inflater.decompress(raw[start:], max(1, MAX_JAR_BYTES - total))
                if not inflater.eof:
                    raise BadJar(f"{name} is damaged, or too big to unpack")
                at = len(raw) - len(inflater.unused_data)
                if flags & 8:
                    at += 16 if raw[at:at + 4] == b"PK\x07\x08" else 12
                elif at - start != packed:
                    raise BadJar(f"{name}'s header gives the wrong compressed size")
            elif method == 0 and not flags & 8 and packed == size:
                data = raw[start:start + size]
                at = start + size
            else:
                raise BadJar(f"{name} uses a storage method the game can't read")
            total += len(data)
            if total > MAX_JAR_BYTES:
                raise BadJar("it's too big to unpack")
            entries.append((name, data))
    except (struct.error, UnicodeDecodeError, zlib.error) as error:
        raise BadJar(f"it's damaged: {error}") from error
    if not entries:
        raise BadJar("the game would find no entries in it")
    return entries


def _matches(name, rule):
    if rule.endswith("/"):
        return name.startswith(rule)
    if rule.endswith("*"):
        return name.startswith(rule[:-1])
    return name == rule or name.startswith(rule + "$")


def _refusal(name, groups):
    for reason, rules in groups:
        if any(_matches(name, rule) for rule in rules):
            return reason
    return None


def _class_problem(name, side):
    """Why this module may not refer to this class, or None. Own classes are handled before this."""
    if name.startswith(("java/lang/invoke/", "java/lang/runtime/")) and name not in LIMITED_MEMBERS:
        return "is more of java/lang/invoke than lambdas and string concatenation need"
    if side == "client":
        reason = _refusal(name, CLIENT_REFUSED)
        if reason:
            return reason
        if name in CLIENT_CLASSES or name in LIMITED_MEMBERS or name.startswith(CLIENT_PREFIXES):
            return None
        return "isn't on the list client modules may use"
    if side in ("mixins", "mixin_text"):
        if name.startswith(MIXIN_USABLE):
            return None
        reason = _refusal(name, MIXIN_REFUSED)
        if reason:
            return reason
        # Text might be anything, like a file name in a constant, so it only has to stay off the lists. A class has to be on this one.
        if side == "mixins" and not name.startswith(MIXIN_LIBRARIES):
            return "isn't one of the libraries a mixin may use, which are listed in docs/feature-format.md"
    # A machine's tick and a mob's behaviour are handed these, so using them is what the API asks for.
    if name.startswith("gm/conduit/") and not name.startswith("gm/conduit/api/") and name not in ("gm/conduit/slots/SlotBlockEntity", "gm/conduit/mobs/SlotMob"):
        return "is the module host's own code, and modules may only use gm/conduit/api"
    return _refusal(name, SERVER_REFUSED)


def _member_problem(owner, name, descriptor, side):
    limited = (CLIENT_MEMBERS if side == "client" else LIMITED_MEMBERS).get(owner)
    if limited is not None and name not in limited:
        allowed = ", ".join(sorted(limited)) or "nothing"
        return f"isn't allowed: on this class, modules may only use {allowed}"
    names, reason = REFUSED_MEMBERS.get(owner, ((), None))
    if name in names:
        return reason
    if side == "mixins":
        if owner in REGISTERING_OWNERS and name.startswith("register"):
            return REGISTERS[0]
        names, reason = MIXIN_REFUSED_MEMBERS.get(owner, ((), None))
        if name in names:
            return reason
    if owner.startswith("java/util/") and name.startswith("parallel"):
        return THREADS[0]
    if name == "<init>" and owner in _FILE_NAME_CONSTRUCTORS and descriptor.startswith("(Ljava/lang/String;"):
        return FILES[0]
    return None


def _approved(feature_id, side):
    """What the owner has approved for this feature on this side. A broken file approves nothing, and says so."""
    try:
        data = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
        approved = data.get(feature_id, {}).get(side, [])
        if not isinstance(approved, list) or not all(isinstance(item, str) for item in approved):
            raise ValueError(f"{feature_id}.{side} must be a list of names")
    except FileNotFoundError:
        return set()
    except (AttributeError, ValueError) as error:
        raise GateFailed(GATE, f"{EXCEPTIONS.name} is broken, so no exception can be trusted. "
                               f"The owner needs to fix it: {error}") from error
    return set(approved)


def _read_properties(data, classes, feature_id, found):
    """The host instantiates whatever module.properties names, so it must name one of the jar's own classes.
    Java's properties format has escapes, so only the plainest form is accepted, leaving nothing to read differently."""
    lines = [line.strip() for line in data.decode("utf-8", "replace").splitlines()]
    lines = [line for line in lines if line and not line.startswith(("#", "!"))]
    match = _ENTRY_LINE.fullmatch(lines[0]) if len(lines) == 1 else None
    if not match:
        found("module.properties", "must hold exactly one line, entry=<your class>")
    elif match.group(1).replace(".", "/") not in classes:
        found("module.properties", f"names {match.group(1)}, which isn't in this jar. "
                                   f"It should be a class in package gm.feature.{feature_id}")


def _scan(entries, side, feature_id, approved):
    own = f"gm/feature/{feature_id}/"
    problems = {}

    def found(reference, why, where=None):
        if reference not in approved:
            wheres = problems.setdefault(reference, (why, set()))[1]
            if where:
                wheres.add(where)

    parsed_classes, seen, properties = [], set(), None
    for name, data in entries:
        if name in seen:
            found(name, "appears twice in the jar, so which one runs depends on the reader")
        seen.add(name)
        if name.endswith("/"):
            if data:
                found(name, "is a directory entry holding data")
        elif name == "module.properties":
            properties = data
        elif name.endswith(".class"):
            # Module class loaders ask their parent first, so a jar's own net/minecraft/client/User would resolve
            # to the real one. Only a package nothing else uses can honestly be called its own.
            if not (name.startswith(own) and _CLASS_PATH.fullmatch(name)):
                found(name, f"is outside this module's package. Its classes must all be under {own}")
            elif side == "server" and name.startswith((f"{own}mixin/", f"{own}shared/")):
                # The game's own loader is asked first and it has the feature's mixins, so this copy would never run.
                found(name, "is in a package that belongs to the feature's mixins folder, so a module's own class can't be there")
            try:
                parsed = parse_class(data)
            except BadClass as error:
                found(name, f"can't be checked: {error}")
                continue
            if f"{parsed.name}.class" != name:
                found(name, f"holds class {parsed.name}, which doesn't match its path")
            parsed_classes.append(parsed)
        elif name != "META-INF/MANIFEST.MF":
            # The manifest is allowed because Gradle always adds one, and the game ignores it. Nothing else can stay.
            found(name, "isn't a class or module.properties, and a module's jar may hold nothing else. "
                        "Art and data belong in the feature's assets")

    if properties is None:
        found("module.properties", "is missing, so the module could never load. Add src/main/resources/module.properties")
    else:
        _read_properties(properties, {parsed.name for parsed in parsed_classes}, feature_id, found)

    check_references(parsed_classes, side, own, approved, found)

    # Last, because anything already reported would mostly be reported again here in a less useful way.
    if side == "client" and not problems:
        for parsed in parsed_classes:
            for text in parsed.texts:
                scanned = text.replace(COMPANION_IGNORES, "")
                banned = next((item for item in COMPANION_REFUSES if item in scanned), None)
                if banned or scanned in COMPANION_REFUSED_NAMES:
                    why = (f"would make every companion refuse this module, because it refuses any class with a constant "
                           f"{'containing ' + banned if banned else 'with that name'}. That includes plain strings and your "
                           "own method names, so rename it. The owner can't "
                           "approve this one, since the companion decides it")
                    problems.setdefault(f"constant {text!r}", (why, set()))[1].add(parsed.name)
    return problems


def check_references(parsed_classes, side, own, approved, found):
    """Reports what these classes refer to that this side may not, member by member."""
    # A member approval also lets its class be named. The class's other members still get checked.
    owners = {item.split(".", 1)[0] for item in approved}
    limited = CLIENT_MEMBERS if side == "client" else LIMITED_MEMBERS
    for parsed in parsed_classes:
        where = parsed.name
        for name in parsed.classes:
            if not name.startswith(own) and name not in owners:
                why = _class_problem(name, side)
                if why:
                    found(name, why, where)
        for owner, name, descriptor in parsed.members:
            reference = f"{owner}.{name}"
            if reference in approved or owner in approved or owner.startswith(own):
                continue
            # A refused class is reported once, with the members used so the agent can see what it was reaching
            # for. If a sibling member was approved the class itself wasn't reported, so this member answers for it.
            class_problem = _class_problem(owner, side)
            if class_problem and owner not in owners:
                found(owner, class_problem, f"{where}, calling {name}")
            else:
                why = class_problem or _member_problem(owner, name, descriptor, side)
                if why:
                    found(reference, why, where)
        for parent in parsed.parents:
            # A subclass inherits every member under its own name, which would walk straight past the member check.
            if parent in limited:
                found(f"extends {parent}", "isn't allowed, because a subclass would inherit members modules may not use", where)
        for name in parsed.natives:
            found(f"native {parsed.name}.{name}", "declares native code, which nothing here can inspect", where)
        for bootstrap in parsed.bootstraps:
            # A class's own bootstrap method is handed a full-privilege Lookup by the JVM.
            if bootstrap not in BOOTSTRAPS:
                found(f"bootstrap {bootstrap}", "is a custom bootstrap, which can do whatever reflection can", where)


def report_problems(label, problems):
    """Raises GateFailed for what's been found, in the words the agent acts on."""
    lines = [f"{label} can't ship:"]
    for reference, (why, wheres) in sorted(problems.items())[:MAX_REPORTED]:
        users = f" (used by {', '.join(sorted(wheres))})" if wheres else ""
        lines.append(f"- {reference}{users}: {why}.")
    if len(problems) > MAX_REPORTED:
        lines.append(f"...and {len(problems) - MAX_REPORTED} more.")
    lines.append("Remove these or do it another way. If the feature really needs one, say so in your report and quote the "
                 "name after the dash exactly: the owner can approve it for this feature.")
    raise GateFailed(GATE, "\n".join(lines))


def check_jar(path, side, feature_id):
    """Raises GateFailed if a module's jar holds anything but its own code, or that code reaches what it shouldn't."""
    if side not in ("client", "server"):
        raise ValueError(f"side must be client or server, not {side!r}")
    label = f"{feature_id}'s {side} module"
    try:
        entries = read_jar(path)
    except (BadJar, OSError) as error:
        raise GateFailed(GATE, f"{label} has a jar that can't be checked: {error}. Build it with the normal Gradle jar task.") from error
    problems = _scan(entries, side, feature_id, _approved(feature_id, side))
    if problems:
        report_problems(label, problems)
