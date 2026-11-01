"""The bytecode gate, on real class files compiled against the real game. Needs no server and no JDK.

Fixtures are prebuilt under fixtures/classes by build_fixtures.sh. Tricks javac won't produce are hand-assembled here.
Usage: python3 -m unittest broker.tests.test_bytecode
"""
import json
import os
import pathlib
import re
import struct
import tempfile
import unittest
import unittest.mock
import zipfile
import zlib

from broker.gates import GateFailed, bytecode

CLASSES = pathlib.Path(__file__).parent / "fixtures" / "classes"
REPO = pathlib.Path(__file__).resolve().parents[2]
GAME_JAR = pathlib.Path(os.environ.get("RUNTIME_DIR", "/srv/livingmod/runtime")) / "cache/gradle/caches/fabric-loom/26.3/minecraft-client.jar"
FABRIC_JARS = GAME_JAR.parents[2] / "modules-2/files-2.1/net.fabricmc.fabric-api/fabric-rendering-v1"


def fixture_entries(feature, entry_class):
    """A module's entries, shaped like Gradle's jar task makes them: directories and a manifest included."""
    folder = CLASSES / "gm" / "feature" / feature
    entries = [("META-INF/", b""), ("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\r\n\r\n"),
               ("gm/", b""), ("gm/feature/", b""), (f"gm/feature/{feature}/", b"")]
    entries += [(f"gm/feature/{feature}/{path.name}", path.read_bytes()) for path in sorted(folder.glob("*.class"))]
    entries.append(("module.properties", f"entry=gm.feature.{feature}.{entry_class}\n".encode()))
    return entries


def local_entry(name, data, descriptor=True):
    """One raw zip entry as the game reads it, with the data descriptor Gradle's jars use."""
    packer = zlib.compressobj(wbits=-15)
    packed = packer.compress(data) + packer.flush()
    crc = zlib.crc32(data)
    encoded = name.encode()
    if descriptor:
        return (struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x0808, 8, 0, 0, 0, 0, 0, len(encoded), 0) + encoded + packed
                + struct.pack("<IIII", 0x08074B50, crc, len(packed), len(data)))
    return struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x0800, 8, 0, 0, crc, len(packed), len(data), len(encoded), 0) + encoded + packed


class ClassMaker:
    """Assembles class files by hand, for the shapes javac will never emit but a hostile build could."""

    def __init__(self, name):
        self.pool = [b""]
        self.slots = 1
        self.fields = []
        self.methods = []
        self.attributes = []
        self.this_class = self.klass(name)
        self.super_class = self.klass("java/lang/Object")

    def add(self, data, slots=1):
        index = self.slots
        self.pool.append(data)
        self.slots += slots
        return index

    def utf8(self, text):
        encoded = text if isinstance(text, bytes) else text.encode()
        return self.add(b"\x01" + struct.pack(">H", len(encoded)) + encoded)

    def klass(self, name):
        return self.add(b"\x07" + struct.pack(">H", self.utf8(name)))

    def name_and_type(self, name, descriptor):
        return self.add(b"\x0c" + struct.pack(">HH", self.utf8(name), self.utf8(descriptor)))

    def method_ref(self, owner, name, descriptor):
        return self.add(b"\x0a" + struct.pack(">HH", self.klass(owner), self.name_and_type(name, descriptor)))

    def long_constant(self):
        return self.add(b"\x05" + b"\0" * 8, slots=2)

    def field(self, name, descriptor):
        self.fields.append(struct.pack(">HHHH", 0, self.utf8(name), self.utf8(descriptor), 0))

    def method(self, name, descriptor, flags=0):
        self.methods.append(struct.pack(">HHHH", flags, self.utf8(name), self.utf8(descriptor), 0))

    def bootstrap(self, owner, name, descriptor):
        handle = self.add(b"\x0f\x06" + struct.pack(">H", self.method_ref(owner, name, descriptor)))
        body = struct.pack(">HHH", 1, handle, 0)
        self.attributes.append(struct.pack(">HI", self.utf8("BootstrapMethods"), len(body)) + body)

    def build(self):
        pool = b"".join(self.pool)
        parts = [b"\xca\xfe\xba\xbe", struct.pack(">HHH", 0, 69, self.slots), pool,
                 struct.pack(">HHHH", 0x0031, self.this_class, self.super_class, 0),
                 struct.pack(">H", len(self.fields)), *self.fields,
                 struct.pack(">H", len(self.methods)), *self.methods,
                 struct.pack(">H", len(self.attributes)), *self.attributes]
        return b"".join(parts)


class JarCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        # No test should see the owner's real approvals.
        self.approvals = self.folder / "exceptions.json"
        patcher = unittest.mock.patch.object(bytecode, "EXCEPTIONS", self.approvals)
        patcher.start()
        self.addCleanup(patcher.stop)

    def jar(self, entries):
        path = self.folder / "module.jar"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return path

    def raw_jar(self, data):
        path = self.folder / "module.jar"
        path.write_bytes(data)
        return path

    def assert_passes(self, jar, side, feature):
        bytecode.check_jar(jar, side, feature)

    def assert_refused(self, jar, side, feature, *mentions):
        with self.assertRaises(GateFailed) as caught:
            bytecode.check_jar(jar, side, feature)
        self.assertEqual(caught.exception.gate, "bytecode")
        for mention in mentions:
            self.assertIn(mention, caught.exception.message)
        return caught.exception.message

    def fixture(self, feature, entry_class="Bad"):
        return self.jar(fixture_entries(feature, entry_class))

    def made_class(self, maker, feature="crafted"):
        """A jar around one hand-assembled class in that feature's package."""
        return self.jar([(f"gm/feature/{feature}/Made.class", maker.build()),
                         ("module.properties", f"entry=gm.feature.{feature}.Made\n".encode())])


class CleanModules(JarCase):
    def test_clean_client_module_passes(self):
        self.assert_passes(self.fixture("clean", "CleanModule"), "client", "clean")

    def test_ember_fixture_passes_on_the_server(self):
        self.assert_passes(self.fixture("ember", "EmberModule"), "server", "ember")

    def test_ember_fixture_would_not_pass_as_a_client_module(self):
        # Allowlist and denylist really are different: it's fine on the server and refused here.
        self.assert_refused(self.fixture("ember", "EmberModule"), "client", "ember", "gm/conduit/api/ServerModule")

    def test_lore_fixture_passes_on_the_server(self):
        self.assert_passes(self.fixture("lore", "LoreModule"), "server", "lore")

    def test_real_server_module_passes(self):
        self.assert_passes(self.fixture("server_clean", "ServerClean"), "server", "server_clean")

    def test_a_clean_module_reports_nothing_on_the_server_either(self):
        self.assert_passes(self.fixture("clean", "CleanModule"), "server", "clean")


class ClientRefusals(JarCase):
    def test_runtime_exec(self):
        self.assert_refused(self.fixture("runtime_exec"), "client", "runtime_exec",
                            "java/lang/Runtime", "gm/feature/runtime_exec/Bad", "calling exec")

    def test_process_builder(self):
        self.assert_refused(self.fixture("process_builder"), "client", "process_builder", "java/lang/ProcessBuilder")

    def test_class_for_name_is_caught_by_its_method(self):
        self.assert_refused(self.fixture("class_forname"), "client", "class_forname", "java/lang/Class.forName")

    def test_get_declared_method(self):
        self.assert_refused(self.fixture("declared_method"), "client", "declared_method",
                            "java/lang/Class.getDeclaredMethod", "java/lang/reflect/Method")

    def test_socket(self):
        self.assert_refused(self.fixture("socket"), "client", "socket", "java/net/Socket", "network")

    def test_session_token(self):
        self.assert_refused(self.fixture("session_token"), "client", "session_token",
                            "net/minecraft/client/User", "session token", "net/minecraft/client/Minecraft.getUser")

    def test_native_method(self):
        self.assert_refused(self.fixture("native_method"), "client", "native_method",
                            "native gm/feature/native_method/Bad.peek")

    def test_files(self):
        self.assert_refused(self.fixture("file_read"), "client", "file_read", "java/nio/file/Files")
        self.assert_refused(self.fixture("file_stream"), "client", "file_stream", "java/io/FileInputStream")

    def test_getting_a_lookup(self):
        self.assert_refused(self.fixture("lookup"), "client", "lookup", "java/lang/invoke/MethodHandles.lookup")

    def test_thread(self):
        self.assert_refused(self.fixture("thread"), "client", "thread", "java/lang/Thread")

    def test_foreign_function_api(self):
        self.assert_refused(self.fixture("foreign"), "client", "foreign", "java/lang/foreign/Linker", "native code")

    def test_minecraft_members_are_a_list(self):
        self.assert_refused(self.fixture("minecraft_stop"), "client", "minecraft_stop", "net/minecraft/client/Minecraft.stop")

    def test_an_inventory_helper_can_use_all_of_its_hooks(self):
        self.assert_passes(self.fixture("inventory_helper", "HelperModule"), "client", "inventory_helper")

    def test_a_stack_in_a_menu_is_only_for_looking_at(self):
        self.assert_refused(self.fixture("stack_changing"), "client", "stack_changing", "net/minecraft/world/item/ItemStack.setCount")

    def test_the_player_is_still_out_of_reach_from_an_inventory_helper(self):
        self.assert_refused(self.fixture("player_reach"), "client", "player_reach", "net/minecraft/client/player/LocalPlayer")

    def test_extending_a_stack_would_inherit_past_the_member_check(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.super_class = maker.klass("net/minecraft/world/item/ItemStack")
        self.assert_refused(self.made_class(maker), "client", "crafted", "extends net/minecraft/world/item/ItemStack")

    def test_anything_unknown_is_refused(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.klass("net/minecraft/client/player/LocalPlayer")
        self.assert_refused(self.made_class(maker), "client", "crafted", "LocalPlayer", "isn't on the list")

    def test_extending_minecraft_would_inherit_past_the_member_check(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.super_class = maker.klass("net/minecraft/client/Minecraft")
        self.assert_refused(self.made_class(maker), "client", "crafted", "extends net/minecraft/client/Minecraft")

    def test_message_says_how_to_ask(self):
        message = self.assert_refused(self.fixture("socket"), "client", "socket")
        self.assertIn("owner can approve", message)


class CompanionScan(JarCase):
    """The companion refuses these on its own, so the broker has to say so before they ship to no effect."""

    def test_runtime_exception_is_fine(self):
        self.assert_passes(self.fixture("runtime_exception"), "client", "runtime_exception")

    def test_a_plain_string(self):
        self.assert_refused(self.fixture("thread_string"), "client", "thread_string", "java/lang/Thread", "companion")

    def test_runtime_exception_is_fine_on_the_server(self):
        self.assert_passes(self.fixture("runtime_exception"), "server", "runtime_exception")

    def test_cant_be_approved_from_here(self):
        self.approvals.write_text(json.dumps({"thread_string": {"client": ["constant 'java/lang/Thread'"]}}))
        self.assert_refused(self.fixture("thread_string"), "client", "thread_string", "can't approve")

    def test_in_step_with_the_companion(self):
        source = REPO / "mods/companion/src/main/java/gm/companion/ModuleVerifier.java"
        if not source.exists():
            self.skipTest("the companion's source isn't here")
        text = source.read_text(encoding="utf-8")
        forbidden = re.search(r"FORBIDDEN = List\.of\((.*?)\);", text, re.DOTALL).group(1)
        names = re.search(r"FORBIDDEN_NAMES = Set\.of\((.*?)\);", text, re.DOTALL).group(1)
        self.assertEqual(set(bytecode.COMPANION_REFUSES), set(re.findall(r'"([^"]+)"', forbidden)))
        self.assertEqual(bytecode.COMPANION_REFUSED_NAMES, set(re.findall(r'"([^"]+)"', names)))
        self.assertEqual(bytecode.COMPANION_IGNORES, re.search(r'HARMLESS = "([^"]+)"', text).group(1))


class ServerRefusals(JarCase):
    def test_processes_network_reflection_threads_native_files(self):
        for feature, mention in (("runtime_exec", "java/lang/Runtime"), ("process_builder", "java/lang/ProcessBuilder"),
                                 ("socket", "java/net/Socket"), ("class_forname", "java/lang/Class.forName"),
                                 ("declared_method", "java/lang/reflect/Method"), ("thread", "java/lang/Thread"),
                                 ("native_method", "native gm/feature/native_method/Bad.peek"),
                                 ("file_read", "java/nio/file/Files"), ("file_stream", "java/io/FileInputStream"),
                                 ("lookup", "java/lang/invoke/MethodHandles.lookup"), ("foreign", "java/lang/foreign/Linker")):
            with self.subTest(feature):
                self.assert_refused(self.fixture(feature), "server", feature, mention)

    def test_a_file_opened_by_name_with_no_file_type_in_sight(self):
        self.assert_refused(self.fixture("print_writer"), "server", "print_writer", "java/io/PrintWriter.<init>")

    def test_parallel_streams_are_threads(self):
        self.assert_refused(self.fixture("parallel_stream"), "server", "parallel_stream", "parallelStream")

    def test_the_module_hosts_own_code(self):
        self.assert_refused(self.fixture("host_internals"), "server", "host_internals", "gm/conduit/modules/ServerModuleHost")

    def test_system_exit_on_an_otherwise_allowed_class(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.method_ref("java/lang/System", "exit", "(I)V")
        self.assert_refused(self.made_class(maker), "server", "crafted", "java/lang/System.exit")

    def test_system_nano_time_is_fine(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.method_ref("java/lang/System", "nanoTime", "()J")
        self.assert_passes(self.made_class(maker), "server", "crafted")

    def test_rejects_unsafe(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.method_ref("sun/misc/Unsafe", "getUnsafe", "()Lsun/misc/Unsafe;")
        self.assert_refused(self.made_class(maker), "server", "crafted", "sun/misc/Unsafe")


class ClassParsing(JarCase):
    """Shapes a hostile build could emit to hide a reference from a careless parser."""

    def setUp(self):
        super().setUp()
        self.maker = ClassMaker("gm/feature/crafted/Made")

    def test_long_constants_take_two_slots(self):
        self.maker.long_constant()
        self.maker.method_ref("java/lang/Runtime", "getRuntime", "()Ljava/lang/Runtime;")
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "java/lang/Runtime")

    def test_array_of_a_banned_type(self):
        self.maker.klass("[Ljava/io/File;")
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "java/io/File")

    def test_array_calls_are_not_a_member_of_anything(self):
        self.maker.method_ref("[I", "clone", "()Ljava/lang/Object;")
        self.assert_passes(self.made_class(self.maker), "client", "crafted")

    def test_field_of_a_banned_type_never_used(self):
        self.maker.field("token", "Lnet/minecraft/client/User;")
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "net/minecraft/client/User")

    def test_method_descriptor_of_a_banned_type(self):
        self.maker.method("open", "()Ljava/net/Socket;")
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "java/net/Socket")

    def test_method_type_constant(self):
        self.maker.add(b"\x10" + struct.pack(">H", self.maker.utf8("(Ljava/net/URL;)V")))
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "java/net/URL")

    def test_overlong_utf8_spelling_of_a_slash(self):
        # Class versions up to 47 may spell "/" as C0 AF, and the JVM reads that as a slash.
        self.maker.klass(b"java\xc0\xaflang\xc0\xafRuntime")
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "java/lang/Runtime")

    def test_native_on_a_declared_method(self):
        self.maker.method("peek", "()V", flags=bytecode.ACC_NATIVE)
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "native gm/feature/crafted/Made.peek")

    def test_custom_bootstrap_method(self):
        self.maker.bootstrap("gm/feature/crafted/Made", "boot", "()V")
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "bootstrap gm/feature/crafted/Made.boot")
        self.assert_refused(self.made_class(self.maker), "server", "crafted", "bootstrap gm/feature/crafted/Made.boot")

    def test_lambda_bootstrap_is_fine(self):
        self.maker.bootstrap("java/lang/invoke/LambdaMetafactory", "metafactory", "()V")
        self.assert_passes(self.made_class(self.maker), "client", "crafted")

    def test_unknown_constant_tag(self):
        self.maker.add(b"\x63")
        self.assert_refused(self.made_class(self.maker), "client", "crafted", "can't be checked")

    def test_truncated_class(self):
        data = self.maker.build()[:-3]
        jar = self.jar([("gm/feature/crafted/Made.class", data), ("module.properties", b"entry=gm.feature.crafted.Made\n")])
        self.assert_refused(jar, "client", "crafted", "can't be checked")

    def test_trailing_bytes(self):
        jar = self.jar([("gm/feature/crafted/Made.class", self.maker.build() + b"\0"), ("module.properties", b"entry=gm.feature.crafted.Made\n")])
        self.assert_refused(jar, "client", "crafted", "can't be checked")

    def test_not_a_class_at_all(self):
        jar = self.jar([("gm/feature/crafted/Made.class", b"hello"), ("module.properties", b"entry=gm.feature.crafted.Made\n")])
        self.assert_refused(jar, "server", "crafted", "can't be checked")

    def test_class_whose_name_disagrees_with_its_path(self):
        maker = ClassMaker("gm/feature/crafted/Other")
        self.assert_refused(self.made_class(maker), "client", "crafted", "doesn't match its path")


class JarShape(JarCase):
    def test_a_stray_file(self):
        entries = fixture_entries("clean", "CleanModule") + [("notes.txt", b"hello")]
        self.assert_refused(self.jar(entries), "client", "clean", "notes.txt")

    def test_a_service_file(self):
        entries = fixture_entries("clean", "CleanModule") + [("META-INF/services/java.lang.Runnable", b"x")]
        self.assert_refused(self.jar(entries), "server", "clean", "META-INF/services")

    def test_shadowing_a_game_class_cant_make_it_your_own(self):
        # Module class loaders ask their parent first, so at runtime this resolves to the real User.
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.method_ref("net/minecraft/client/User", "getAccessToken", "()Ljava/lang/String;")
        jar = self.jar([("gm/feature/crafted/Made.class", maker.build()),
                        ("net/minecraft/client/User.class", ClassMaker("net/minecraft/client/User").build()),
                        ("module.properties", b"entry=gm.feature.crafted.Made\n")])
        self.assert_refused(jar, "client", "crafted", "net/minecraft/client/User.class", "outside this module's package")

    def test_path_tricks_in_a_class_name(self):
        name = "gm/feature/crafted/../../../net/minecraft/client/User.class"
        jar = self.jar([(name, ClassMaker("net/minecraft/client/User").build()), ("module.properties", b"entry=gm.feature.crafted.Made\n")])
        self.assert_refused(jar, "client", "crafted", name)

    def test_entry_point_must_be_its_own_class(self):
        entries = fixture_entries("clean", "CleanModule")[:-1] + [("module.properties", b"entry=net.minecraft.client.Minecraft\n")]
        self.assert_refused(self.jar(entries), "client", "clean", "module.properties", "isn't in this jar")

    def test_properties_tricks(self):
        for text in ("entry=gm.feature.clean.CleanModule\nentry=net.minecraft.client.Minecraft\n",
                     "entr\\u0079=gm.feature.clean.CleanModule\n", "entry=gm.feature.clean.CleanModule\\\n"):
            with self.subTest(text):
                entries = fixture_entries("clean", "CleanModule")[:-1] + [("module.properties", text.encode())]
                self.assert_refused(self.jar(entries), "client", "clean", "module.properties")

    def test_missing_properties(self):
        self.assert_refused(self.jar(fixture_entries("clean", "CleanModule")[:-1]), "client", "clean", "module.properties", "missing")

    def test_duplicate_entries(self):
        entries = fixture_entries("clean", "CleanModule")
        self.assert_refused(self.raw_jar(b"".join(local_entry(*entry) for entry in entries + [entries[-1]])), "client", "clean", "appears twice")

    def test_reads_jars_with_data_descriptors_like_gradles(self):
        data = b"".join(local_entry(*entry) for entry in fixture_entries("clean", "CleanModule"))
        self.assert_passes(self.raw_jar(data), "client", "clean")

    def test_reads_jars_without_data_descriptors(self):
        data = b"".join(local_entry(*entry, descriptor=False) for entry in fixture_entries("clean", "CleanModule"))
        self.assert_passes(self.raw_jar(data), "client", "clean")

    def test_entry_hidden_from_the_central_directory(self):
        """zipfile trusts the central directory, and JarInputStream ignores it. Here they disagree."""
        hidden = local_entry("gm/feature/clean/Hidden.class", (CLASSES / "gm/feature/runtime_exec/Bad.class").read_bytes())
        clean = self.jar(fixture_entries("clean", "CleanModule")).read_bytes()
        crafted = self.raw_jar(hidden + clean)
        # Python's zipfile copes with the prefix and can't see the extra class at all.
        with zipfile.ZipFile(crafted) as archive:
            self.assertNotIn("gm/feature/clean/Hidden.class", archive.namelist())
        self.assert_refused(crafted, "client", "clean", "java/lang/Runtime")

    def test_entry_hidden_inside_another_entrys_compressed_data(self):
        """With a data descriptor, the reader stops where the deflate stream ends, not where the directory says."""
        hidden = local_entry("gm/feature/clean/Hidden.class", (CLASSES / "gm/feature/runtime_exec/Bad.class").read_bytes())
        entries = fixture_entries("clean", "CleanModule")
        self.assert_refused(self.raw_jar(local_entry(*entries[0]) + hidden + b"".join(local_entry(*entry) for entry in entries[1:])),
                            "client", "clean", "java/lang/Runtime")

    def test_junk_before_the_first_entry(self):
        # JarInputStream sees no entries in this at all, so the module could never load.
        self.assert_refused(self.raw_jar(b"junk" + self.jar(fixture_entries("clean", "CleanModule")).read_bytes()), "client", "clean", "no entries")

    def test_encrypted_entry(self):
        data = bytearray(local_entry("module.properties", b"entry=x\n"))
        data[6] |= 1
        self.assert_refused(self.raw_jar(bytes(data)), "client", "clean", "encrypted")

    def test_damaged_entry(self):
        data = local_entry("module.properties", b"entry=x\n")
        self.assert_refused(self.raw_jar(data[:len(data) - 18]), "client", "clean", "can't be checked")


class Exceptions(JarCase):
    def test_real_file_starts_empty(self):
        self.assertEqual(json.loads((REPO / "broker/gates/bytecode_exceptions.json").read_text(encoding="utf-8")), {})

    def approve(self, data):
        self.approvals.write_text(json.dumps(data), encoding="utf-8")

    def test_approving_a_member(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.method_ref("java/lang/System", "nanoTime", "()J")
        jar = self.made_class(maker)
        self.assert_refused(jar, "client", "crafted", "java/lang/System")
        self.approve({"crafted": {"client": ["java/lang/System.nanoTime"]}})
        self.assert_passes(jar, "client", "crafted")

    def test_approving_a_member_doesnt_approve_its_neighbours(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.method_ref("java/lang/System", "nanoTime", "()J")
        maker.method_ref("java/lang/System", "exit", "(I)V")
        self.approve({"crafted": {"client": ["java/lang/System.nanoTime"]}})
        self.assert_refused(self.made_class(maker), "client", "crafted", "java/lang/System.exit")

    def test_approving_a_whole_class(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.method_ref("org/joml/Matrix3x2f", "identity", "()Lorg/joml/Matrix3x2f;")
        self.approve({"crafted": {"client": ["org/joml/Matrix3x2f"]}})
        self.assert_passes(self.made_class(maker), "client", "crafted")

    def test_only_for_that_feature_and_side(self):
        maker = ClassMaker("gm/feature/crafted/Made")
        maker.klass("java/net/Socket")
        jar = self.made_class(maker)
        self.approve({"other": {"client": ["java/net/Socket"]}, "crafted": {"server": ["java/net/Socket"]}})
        self.assert_refused(jar, "client", "crafted", "java/net/Socket")
        self.assert_passes(jar, "server", "crafted")

    def test_native_can_be_approved_by_the_name_in_the_message(self):
        self.approve({"native_method": {"client": ["native gm/feature/native_method/Bad.peek"]}})
        self.assert_passes(self.fixture("native_method"), "client", "native_method")

    def test_broken_file_approves_nothing(self):
        jar = self.fixture("clean", "CleanModule")
        for text in ("{not json", '{"clean": {"client": "java/net/Socket"}}', '["clean"]', '{"clean": []}'):
            with self.subTest(text):
                self.approvals.write_text(text, encoding="utf-8")
                self.assert_refused(jar, "client", "clean", "broken")

    def test_side_must_be_real(self):
        with self.assertRaises(ValueError):
            bytecode.check_jar(self.fixture("clean", "CleanModule"), "both", "clean")


@unittest.skipUnless(GAME_JAR.exists(), "the game's jar isn't here")
class AgainstTheRealGame(unittest.TestCase):
    """Minecraft renames things often, and a name on the list that doesn't exist protects nothing and helps nobody."""

    def test_allowlist_names_real_classes(self):
        with zipfile.ZipFile(GAME_JAR) as game:
            known = set(game.namelist())
        for name in bytecode.CLIENT_CLASSES:
            if name.startswith("net/minecraft/"):
                self.assertIn(f"{name}.class", known)

    def test_refused_game_names_are_real(self):
        with zipfile.ZipFile(GAME_JAR) as game:
            known = set(game.namelist())
        for rule in bytecode.SESSION[1]:
            if not rule.endswith("/"):
                self.assertIn(f"{rule}.class", known)

    def test_hud_element_is_where_the_list_says(self):
        jars = list(FABRIC_JARS.rglob("*.jar"))
        if not jars:
            self.skipTest("Fabric's rendering jar isn't here")
        with zipfile.ZipFile(jars[0]) as fabric:
            self.assertIn("net/fabricmc/fabric/api/client/rendering/v1/hud/HudElement.class", fabric.namelist())

    def test_no_allowed_game_class_goes_near_the_session(self):
        with zipfile.ZipFile(GAME_JAR) as game:
            for name in bytecode.CLIENT_CLASSES:
                if name.startswith("net/minecraft/") and name != "net/minecraft/client/Minecraft":
                    parsed = bytecode.parse_class(game.read(f"{name}.class"))
                    self.assertNotIn("net/minecraft/client/User", parsed.classes, name)

    def test_the_real_jar_parses(self):
        # The parser has to cope with whatever the real compiler emits, so it's run over a good sample of it.
        with zipfile.ZipFile(GAME_JAR) as game:
            names = [name for name in game.namelist() if name.endswith(".class")]
            for name in names[::40]:
                self.assertEqual(f"{bytecode.parse_class(game.read(name)).name}.class", name)

    def test_the_session_really_is_behind_these_members(self):
        with zipfile.ZipFile(GAME_JAR) as game:
            parsed = bytecode.parse_class(game.read("net/minecraft/client/Minecraft.class"))
        self.assertIn("net/minecraft/client/User", parsed.classes)
        self.assertNotIn("getUser", bytecode.CLIENT_MEMBERS["net/minecraft/client/Minecraft"])


if __name__ == "__main__":
    unittest.main()
