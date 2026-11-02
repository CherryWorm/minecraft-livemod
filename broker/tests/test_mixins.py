"""The mixin gate, on real class files compiled against the real game, and what happens to one that crashes. Needs no server and no JDK.

Fixtures are prebuilt under fixtures/classes by build_fixtures.sh, as in test_bytecode.
Usage: python3 -m unittest broker.tests.test_mixins
"""
import hashlib
import json
import os
import pathlib
import struct
import tempfile
import unittest
import unittest.mock
import zipfile

from broker import bundles, daemon, deploy, promote, runtime
from broker.gates import GateFailed, bytecode, mixins, shadow, static
from broker.tests.test_bytecode import ClassMaker

CLASSES = pathlib.Path(__file__).parent / "fixtures" / "classes"
GAME_JAR = pathlib.Path(os.environ.get("RUNTIME_DIR", "/srv/livingmod/runtime")) / "cache/gradle/caches/fabric-loom/26.3/minecraft-merged.jar"


def annotation_bytes(maker, descriptor, **values):
    """One annotation of text and class values, for the shapes javac won't write."""
    data = struct.pack(">HH", maker.utf8(descriptor), len(values))
    for name, value in values.items():
        data += struct.pack(">H", maker.utf8(name))
        if isinstance(value, list):
            data += b"[" + struct.pack(">H", len(value)) + b"".join(b"s" + struct.pack(">H", maker.utf8(item)) for item in value)
        else:
            data += b"s" + struct.pack(">H", maker.utf8(value))
    return data


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        approvals = unittest.mock.patch.object(bytecode, "EXCEPTIONS", self.folder / "exceptions.json")
        approvals.start()
        self.addCleanup(approvals.stop)

    def built_jar(self, feature_id, extra=()):
        """What Gradle would make of a fixture's classes."""
        path = self.folder / f"built-{feature_id}.jar"
        root = CLASSES / "gm" / "feature" / feature_id
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("META-INF/", b"")
            archive.writestr("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\r\n\r\n")
            for file in sorted(root.rglob("*.class")):
                archive.writestr(str(file.relative_to(CLASSES)).replace("\\", "/"), file.read_bytes())
            for name, data in extra:
                archive.writestr(name, data)
        return path

    def assembled(self, feature_id):
        return mixins.assemble(self.built_jar(feature_id), feature_id, self.folder / mixins.jar_name(feature_id))

    def refusal(self, feature_id):
        with self.assertRaises(GateFailed) as caught:
            mixins.check_jar(self.assembled(feature_id), feature_id)
        return caught.exception.message


class GoodMixin(Case):
    def test_passes(self):
        mixins.check_jar(self.assembled("good_mixin"), "good_mixin")

    def test_annotations_are_read(self):
        parsed = bytecode.parse_class((CLASSES / "gm/feature/good_mixin/mixin/AbstractBoatMixin.class").read_bytes())
        self.assertEqual(mixins.mixin_targets(parsed), ["net/minecraft/world/entity/vehicle/boat/AbstractBoat"])
        kinds = {each.descriptor for annotation in parsed.annotations for each in annotation.and_nested()}
        self.assertIn(f"L{mixins.INJECTION}ModifyConstant;", kinds)
        self.assertIn(f"L{mixins.INJECTION}Constant;", kinds)
        inject = next(annotation for annotation in parsed.annotations if annotation.descriptor == f"L{mixins.INJECTION}Inject;")
        self.assertEqual(inject.values["method"], ["tick"])
        self.assertEqual(inject.values["at"][0].values["value"], "INVOKE")

    def test_what_it_says_about_itself(self):
        """Fabric reads this before anything else, and it's what could run code as the game starts, so it's written here and has nothing of that."""
        with zipfile.ZipFile(self.assembled("good_mixin")) as archive:
            mod = json.loads(archive.read("fabric.mod.json"))
            config = json.loads(archive.read("mixin_good_mixin.mixins.json"))
            names = archive.namelist()
        self.assertEqual(mod["environment"], "server")
        self.assertEqual(sorted(mod), ["custom", "depends", "environment", "id", "mixins", "name", "schemaVersion", "version"])
        self.assertIn("fabricloader", mod["depends"])
        self.assertEqual(sorted(mod["custom"][mixins.METADATA_KEY]), ["gm.feature.good_mixin.mixin.AbstractBoatMixin", "gm.feature.good_mixin.mixin.BoatAccessor"])
        self.assertTrue(config["required"])
        self.assertEqual(config["injectors"]["defaultRequire"], 1)
        self.assertEqual(config["mixins"], ["AbstractBoatMixin", "BoatAccessor"])
        self.assertEqual(config["package"], "gm.feature.good_mixin.mixin")
        self.assertNotIn("plugin", config)
        self.assertIn("gm/feature/good_mixin/shared/Rules.class", names)

    def test_same_classes_make_the_same_jar(self):
        """Any change to a jar means a restart for everyone, so nothing but the classes can be allowed to change it."""
        first = self.assembled("good_mixin").read_bytes()
        second = self.assembled("good_mixin").read_bytes()
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())


class Targets(Case):
    def test_kill_switch(self):
        message = self.refusal("kill_switch_mixin")
        self.assertIn("target gm/conduit/KillSwitch", message)
        self.assertIn("isn't part of the game", message)

    def test_conduit_named_in_text(self):
        """Not a class reference at all, so nothing that only reads the code would see it."""
        message = self.refusal("named_conduit_mixin")
        self.assertIn("target gm/conduit/provenance/Provenance", message)

    def test_owner_cant_approve_conduit(self):
        bytecode.EXCEPTIONS.write_text(json.dumps({"named_conduit_mixin": {"mixins": ["target gm/conduit/provenance/Provenance", "gm/conduit/provenance/Provenance"]}}), encoding="utf-8")
        self.assertIn("target gm/conduit/provenance/Provenance", self.refusal("named_conduit_mixin"))

    def test_what_protects_the_world(self):
        message = self.refusal("protected_mixin")
        self.assertIn("target net/minecraft/server/MinecraftServer", message)
        self.assertIn("target net/minecraft/world/level/chunk/LevelChunk", message)
        self.assertIn("players' builds", message)

    def test_owner_can_approve_a_protected_target(self):
        bytecode.EXCEPTIONS.write_text(json.dumps({"protected_mixin": {"mixins": ["target net/minecraft/server/MinecraftServer", "target net/minecraft/world/level/chunk/LevelChunk"]}}), encoding="utf-8")
        mixins.check_jar(self.assembled("protected_mixin"), "protected_mixin")

    def test_rule_examples(self):
        for name in ("net.minecraft.commands.Commands", "net/minecraft/commands/Commands$1", "net/minecraft/commands/execution/ExecutionContext", "net/minecraft/server/rcon/thread/RconClient",
                     "net/minecraft/server/network/ServerGamePacketListenerImpl", "net/minecraft/server/players/UserWhiteList", "net/minecraft/CrashReport",
                     "net/minecraft/nbt/NbtIo", "net/minecraft/world/level/block/Blocks", "net/minecraft/core/Registry", "net/minecraft/server/permissions/LevelBasedPermissionSet"):
            self.assertTrue(mixins.protected_target(name), name)
        for name in ("net/minecraft/world/entity/vehicle/boat/AbstractBoat", "net/minecraft/world/entity/Entity", "net/minecraft/server/level/ServerPlayer",
                     "net/minecraft/world/level/block/Block", "net/minecraft/world/item/ItemStack"):
            self.assertFalse(mixins.protected_target(name), name)
        for name in ("gm/conduit/KillSwitch", "gm/companion/ModuleVerifier", "net/fabricmc/fabric/impl/Anything", "eu/pb4/polymer/Anything", "java/lang/String",
                     "org/spongepowered/asm/mixin/Mixins", "gm/feature/other/mixin/Thing"):
            self.assertTrue(mixins.target_problem(name), name)

    @unittest.skipUnless(GAME_JAR.exists(), "needs the game's jar")
    def test_every_rule_is_about_something_real(self):
        """If the game renames one of these, the rule would go on looking fine while protecting nothing."""
        with zipfile.ZipFile(GAME_JAR) as archive:
            classes = [name.removesuffix(".class") for name in archive.namelist() if name.endswith(".class")]
        for _, rules in mixins.REFUSED_TARGETS:
            for rule in rules:
                self.assertTrue(any(bytecode._matches(name, rule) for name in classes), f"nothing in the game matches {rule}")
        for owner in bytecode.REGISTERING_OWNERS:
            self.assertIn(owner, classes)


class WhatsInTheAnnotations(Case):
    def test_overwrite_and_priority(self):
        message = self.refusal("overwrite_mixin")
        self.assertIn("@Overwrite", message)
        self.assertIn("@Mixin priority", message)

    def test_failures_cant_be_made_quiet(self):
        message = self.refusal("quiet_mixin")
        self.assertIn("@Pseudo", message)
        self.assertIn("@Inject require = 0", message)
        self.assertIn("CAPTURE_FAILSOFT", message)

    def test_redirecting_files_shows_nothing_in_the_code(self):
        """What the denylist alone would miss: the handler takes an Object, so no file class appears in anything but text."""
        parsed = bytecode.parse_class((CLASSES / "gm/feature/redirect_files_mixin/mixin/SomewhereMixin.class").read_bytes())
        self.assertFalse([name for name in parsed.classes if name.startswith("java/nio")])
        message = self.refusal("redirect_files_mixin")
        self.assertIn("java/nio/file/Files", message)
        self.assertIn("method '/ti.k/'", message)
        self.assertIn("@At target 'owner=/^java.nio/", message)
        self.assertIn("@At target 'delete'", message)

    def annotation_problems(self, kind, **values):
        problems = {}
        mixins._check_annotation(bytecode.Annotation(f"L{kind};", values), lambda reference, why, where=None: problems.setdefault(reference, why), "somewhere")
        return problems

    def test_selectors_can_only_be_plain(self):
        """The patcher takes much more than this, and each of these can match a name without containing it."""
        inject = f"{mixins.INJECTION}Inject"
        for method in (" <clinit>", "<cli nit>", "name = /^.clinit.$/", "/ti.k/", "*", "t*", "tick ", "Lx/Y;tick(I)V "):
            self.assertIn(f"method {method!r}", self.annotation_problems(inject, method=[method]), method)
        for method in ("tick", "<init>", "tick(I)V", "Lnet/minecraft/world/entity/Entity;tick()V", "getGroundFriction()F", "a$b", "move(Lnet/minecraft/world/entity/MoverType;Lnet/minecraft/world/phys/Vec3;)V"):
            self.assertEqual(self.annotation_problems(inject, method=[method]), {}, method)

    def test_targets_can_only_be_plain(self):
        at = f"{mixins.INJECTION}At"
        for target in ("La;()/.*Files.*/", "delete", "java/nio/file/Files.delete", "owner=/^java.nio/", "La/B;c()V ", "La/B;c(I)", "La/B;"):
            self.assertIn(f"@At target {target!r}", self.annotation_problems(at, value="INVOKE", target=target), target)
        self.assertEqual(self.annotation_problems(at, value="INVOKE", target="Lnet/minecraft/world/entity/Entity;tick()V"), {})
        self.assertEqual(self.annotation_problems(at, value="FIELD", target="Lnet/minecraft/world/entity/Entity;level:Lnet/minecraft/world/level/Level;"), {})
        self.assertEqual(self.annotation_problems(at, value="NEW", target="net/minecraft/world/entity/Entity"), {})

    def test_a_point_that_could_match_anything_needs_to_say_what(self):
        """With @Coerce, a handler can go round a call to something refused without naming it anywhere."""
        at = f"{mixins.INJECTION}At"
        self.assertTrue(self.annotation_problems(at, value="INVOKE", ordinal=3))
        self.assertTrue(self.annotation_problems(at, value="FIELD"))
        self.assertTrue(self.annotation_problems(at, value="INVOKE", desc=bytecode.Annotation(f"L{mixins.INJECTION}Desc;", {"value": "delete"})))
        owned = bytecode.Annotation(f"L{mixins.INJECTION}Desc;", {"value": "tick", "owner": bytecode.ClassValue("Lnet/minecraft/world/entity/Entity;")})
        self.assertEqual(self.annotation_problems(at, value="INVOKE", desc=owned), {})
        self.assertEqual(self.annotation_problems(at, value="HEAD"), {})
        self.assertEqual(self.annotation_problems(at, value="RETURN"), {})

    def test_going_round_a_chunk_is_as_good_as_patching_it(self):
        at = f"{mixins.INJECTION}At"
        target = "Lnet/minecraft/world/level/chunk/LevelChunk;setBlockState(Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/level/block/state/BlockState;I)Lnet/minecraft/world/level/block/state/BlockState;"
        self.assertIn(f"@At target {target!r}", self.annotation_problems(at, value="INVOKE", target=target))

    def test_expressions_are_held_to_the_same_rules(self):
        definition = f"{mixins.EXTRAS}expression/Definition"
        for name in ("/.*Files.*/", "Lgm/conduit/Kill Switch;set", "delete"):
            self.assertIn(f"@Definition {name!r}", self.annotation_problems(definition, id="x", field=[name]))
            self.assertIn(f"@Definition {name!r}", self.annotation_problems(definition, id="x", method=[name]))
        self.assertIn("java/nio/file/Files", self.annotation_problems(definition, id="x", method=["Ljava/nio/file/Files;delete(Ljava/nio/file/Path;)V"]))
        self.assertIn("gm/conduit/KillSwitch", self.annotation_problems(definition, id="x", method=["Lgm/conduit/KillSwitch;set(Z)V"]))
        self.assertEqual(self.annotation_problems(definition, id="x", method=["Lnet/minecraft/world/entity/Entity;tick()V"]), {})

    def test_a_library_that_does_it_for_you_counts(self):
        """Their descriptors name nothing refused, and what they're told to do is a plain string."""
        for name in ("oshi/util/ExecutingCommand", "oshi/util/FileUtil", "org/apache/commons/lang3/ClassUtils", "org/apache/commons/lang3/reflect/MethodUtils",
                     "org/apache/commons/io/FileUtils", "com/google/common/reflect/ClassPath", "com/google/common/io/Files", "java/beans/Expression",
                     "org/apache/logging/log4j/core/config/Configurator", "io/netty/util/internal/PlatformDependent", "it/unimi/dsi/fastutil/io/BinIO"):
            for side in ("server", "mixins", "mixin_text"):
                self.assertTrue(bytecode._class_problem(name, side), f"{name} on {side}")

    def test_a_mixin_only_gets_listed_libraries(self):
        self.assertTrue(bytecode._class_problem("org/lz4/LZ4Factory", "mixins"))
        self.assertFalse(bytecode._class_problem("org/lz4/LZ4Factory", "mixin_text"))
        for name in ("java/lang/String", "net/minecraft/world/entity/Entity", "gm/conduit/api/ServerModule", "org/joml/Vector3f", "com/google/common/collect/ImmutableList",
                     "org/spongepowered/asm/mixin/injection/callback/CallbackInfo", "org/spongepowered/asm/mixin/injection/At$Shift", "com/llamalad7/mixinextras/sugar/ref/LocalRef"):
            self.assertFalse(bytecode._class_problem(name, "mixins"), name)
        for name in ("net/minecraft/server/dedicated/DedicatedServer", "net/minecraft/commands/Commands", "net/minecraft/CrashReport", "net/minecraft/world/level/chunk/LevelChunkSection",
                     "net/minecraft/world/level/block/state/StateDefinition$Builder", "net/fabricmc/loader/api/FabricLoader", "gm/conduit/KillSwitch"):
            self.assertTrue(bytecode._class_problem(name, "mixins"), name)

    def test_what_stops_a_server_or_hides_a_crash(self):
        for owner, member in (("net/minecraft/server/MinecraftServer", "halt"), ("net/minecraft/server/MinecraftServer", "createCommandSourceStack"), ("java/lang/Throwable", "setStackTrace")):
            self.assertTrue(bytecode._member_problem(owner, member, "()V", "mixins"), member)
        self.assertFalse(bytecode._member_problem("net/minecraft/server/MinecraftServer", "getPlayerList", "()V", "mixins"))

    def test_sending_a_players_game_away(self):
        for name in ("net/minecraft/network/protocol/common/ClientboundResourcePackPushPacket", "net/minecraft/network/protocol/common/ClientboundTransferPacket"):
            for side in ("server", "mixins"):
                self.assertTrue(bytecode._class_problem(name, side), f"{name} on {side}")

    def test_registering_through_a_shadow_or_an_invoker(self):
        invoker = f"{mixins.MIXIN}gen/Invoker"
        for value in ("register", "registerThing", "invokeRegister"):
            self.assertTrue(self.annotation_problems(invoker, value=value), value)
        self.assertEqual(self.annotation_problems(invoker, value="getName"), {})
        self.assertTrue(self.annotation_problems(f"{mixins.MIXIN}Shadow", prefix="x$"))
        self.assertTrue(self.annotation_problems(f"{mixins.MIXIN}Shadow", aliases=["register"]))
        maker = ClassMaker("gm/feature/lots/mixin/Sneaky")
        data = struct.pack(">H", 1) + annotation_bytes(maker, f"L{mixins.MIXIN}Mixin;", targets=["net.minecraft.world.effect.MobEffects"])
        maker.attributes.append(struct.pack(">HI", maker.utf8("RuntimeInvisibleAnnotations"), len(data)) + data)
        maker.method("register", "()V")
        path = self.folder / "built.jar"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("gm/feature/lots/mixin/Sneaky.class", maker.build())
        with self.assertRaises(GateFailed) as caught:
            mixins.check_jar(mixins.assemble(path, "lots", self.folder / mixins.jar_name("lots")), "lots")
        self.assertIn("Sneaky.register", caught.exception.message)

    def test_an_annotation_cant_say_a_thing_twice(self):
        """The patcher reads the first and a dict keeps the last, so a second could tell each of them something else."""
        maker = ClassMaker("gm/feature/twice/mixin/Hidden")
        data = struct.pack(">H", 1) + struct.pack(">HH", maker.utf8(f"L{mixins.MIXIN}Mixin;"), 2)
        for target in ("gm.conduit.KillSwitch", "net.minecraft.world.entity.vehicle.boat.AbstractBoat"):
            data += struct.pack(">H", maker.utf8("targets")) + b"[" + struct.pack(">H", 1) + b"s" + struct.pack(">H", maker.utf8(target))
        maker.attributes.append(struct.pack(">HI", maker.utf8("RuntimeInvisibleAnnotations"), len(data)) + data)
        with self.assertRaises(bytecode.BadClass):
            bytecode.parse_class(maker.build())

    def test_custom_injection_point(self):
        self.assertIn("isn't an injection point", self.refusal("custom_point_mixin"))

    def test_what_runs_at_startup(self):
        message = self.refusal("clinit_mixin")
        self.assertIn("method '<clinit>'", message)
        self.assertIn("method 'createBlockStateDefinition'", message)

    def test_registering_is_refused(self):
        self.assertIn("net/minecraft/core/Registry.register", self.refusal("registers_mixin"))

    def test_running_commands_is_refused(self):
        """Run from code, a command counts as the console, and that's enough to undo the owner's /agentstop."""
        maker = ClassMaker("gm/feature/x/shared/Sneaky")
        maker.method_ref("net/minecraft/server/MinecraftServer", "getCommands", "()Lnet/minecraft/commands/Commands;")
        parsed = bytecode.parse_class(maker.build())
        problems = {}
        bytecode.check_references([parsed], "mixins", "gm/feature/x/", set(), lambda reference, why, where=None: problems.setdefault(reference, why))
        self.assertIn("net/minecraft/commands/Commands", problems)

    def test_the_patcher_itself(self):
        self.assertIn("org/spongepowered/asm/mixin/Mixins", self.refusal("patcher_mixin"))

    def test_a_second_attribute_cant_hide_a_target(self):
        """Class readers differ over which copy of an attribute wins, so every one counts."""
        maker = ClassMaker("gm/feature/twice/mixin/Hidden")
        good = annotation_bytes(maker, f"L{mixins.MIXIN}Mixin;", targets=["net.minecraft.world.entity.vehicle.boat.AbstractBoat"])
        bad = annotation_bytes(maker, f"L{mixins.MIXIN}Mixin;", targets=["gm.conduit.KillSwitch"])
        for body in (good, bad):
            data = struct.pack(">H", 1) + body
            maker.attributes.append(struct.pack(">HI", maker.utf8("RuntimeInvisibleAnnotations"), len(data)) + data)
        path = self.folder / "built.jar"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("gm/feature/twice/mixin/Hidden.class", maker.build())
        jar = mixins.assemble(path, "twice", self.folder / mixins.jar_name("twice"))
        with self.assertRaises(GateFailed) as caught:
            mixins.check_jar(jar, "twice")
        self.assertIn("target gm/conduit/KillSwitch", caught.exception.message)

    def test_visible_annotation_counts_too(self):
        maker = ClassMaker("gm/feature/twice/mixin/Hidden")
        body = annotation_bytes(maker, f"L{mixins.MIXIN}Mixin;", targets=["gm.conduit.KillSwitch"])
        data = struct.pack(">H", 1) + body
        maker.attributes.append(struct.pack(">HI", maker.utf8("RuntimeVisibleAnnotations"), len(data)) + data)
        parsed = bytecode.parse_class(maker.build())
        self.assertEqual(mixins.mixin_targets(parsed), ["gm/conduit/KillSwitch"])

    def test_a_bad_annotation_is_refused_not_skipped(self):
        maker = ClassMaker("gm/feature/twice/mixin/Hidden")
        data = struct.pack(">HHH", 1, maker.utf8("LFoo;"), 1) + struct.pack(">H", maker.utf8("value")) + b"?\0\0"
        maker.attributes.append(struct.pack(">HI", maker.utf8("RuntimeInvisibleAnnotations"), len(data)) + data)
        with self.assertRaises(bytecode.BadClass):
            bytecode.parse_class(maker.build())


class TheJar(Case):
    def test_resources_are_refused_when_built(self):
        path = self.built_jar("good_mixin", extra=[("mixin.accesswidener", b"accessWidener v2 named\n")])
        with self.assertRaises(GateFailed) as caught:
            mixins.assemble(path, "good_mixin", self.folder / "out.jar")
        self.assertIn("mixin.accesswidener", caught.exception.message)

    def rewritten(self, change):
        """A finished jar with something changed, as if it had got past being assembled."""
        source = self.assembled("good_mixin")
        path = self.folder / "changed.jar"
        with zipfile.ZipFile(source) as old, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as new:
            for name in old.namelist():
                data = change(name, old.read(name))
                if data is not None:
                    new.writestr(name, data)
        return path

    def test_entrypoint_is_refused(self):
        def change(name, data):
            if name != "fabric.mod.json":
                return data
            return json.dumps({**json.loads(data), "entrypoints": {"preLaunch": ["gm.feature.good_mixin.shared.Rules"]}}).encode()
        with self.assertRaises(GateFailed) as caught:
            mixins.check_jar(self.rewritten(change), "good_mixin")
        self.assertIn("isn't what the broker wrote", caught.exception.message)

    def test_mixin_plugin_is_refused(self):
        def change(name, data):
            if name != "mixin_good_mixin.mixins.json":
                return data
            return json.dumps({**json.loads(data), "plugin": "gm.feature.good_mixin.shared.Rules", "required": False}).encode()
        with self.assertRaises(GateFailed) as caught:
            mixins.check_jar(self.rewritten(change), "good_mixin")
        self.assertIn("isn't what the broker wrote", caught.exception.message)

    def test_nested_jar_is_refused(self):
        source = self.assembled("good_mixin")
        with zipfile.ZipFile(source, "a") as archive:
            archive.writestr("META-INF/jars/other.jar", b"")
        with self.assertRaises(GateFailed) as caught:
            mixins.check_jar(source, "good_mixin")
        self.assertIn("META-INF/jars/other.jar", caught.exception.message)

    def test_too_many(self):
        def mixin(number):
            maker = ClassMaker(f"gm/feature/lots/mixin/M{number}")
            data = struct.pack(">H", 1) + annotation_bytes(maker, f"L{mixins.MIXIN}Mixin;", targets=["net.minecraft.world.entity.vehicle.boat.AbstractBoat"])
            maker.attributes.append(struct.pack(">HI", maker.utf8("RuntimeInvisibleAnnotations"), len(data)) + data)
            return maker.build()
        path = self.folder / "built.jar"
        with zipfile.ZipFile(path, "w") as archive:
            for number in range(mixins.MOST_MIXINS_A_FEATURE + 1):
                archive.writestr(f"gm/feature/lots/mixin/M{number}.class", mixin(number))
        with self.assertRaises(GateFailed) as caught:
            mixins.check_jar(mixins.assemble(path, "lots", self.folder / mixins.jar_name("lots")), "lots")
        self.assertIn("5 mixins", caught.exception.message)

    def test_shared_class_cant_be_a_mixin_and_mixin_package_cant_hold_others(self):
        maker = ClassMaker("gm/feature/mixed/mixin/NotOne")
        other = ClassMaker("gm/feature/mixed/shared/Secretly")
        data = struct.pack(">H", 1) + annotation_bytes(other, f"L{mixins.MIXIN}Mixin;", targets=["net.minecraft.world.entity.vehicle.boat.AbstractBoat"])
        other.attributes.append(struct.pack(">HI", other.utf8("RuntimeInvisibleAnnotations"), len(data)) + data)
        path = self.folder / "built.jar"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("gm/feature/mixed/mixin/NotOne.class", maker.build())
            archive.writestr("gm/feature/mixed/shared/Secretly.class", other.build())
        with self.assertRaises(GateFailed) as caught:
            mixins.check_jar(mixins.assemble(path, "mixed", self.folder / mixins.jar_name("mixed")), "mixed")
        self.assertIn("without being a mixin", caught.exception.message)
        self.assertIn("is a mixin outside", caught.exception.message)


class Modules(Case):
    def module_problems(self, class_name, reference):
        maker = ClassMaker(class_name)
        maker.klass(reference)
        entry = class_name.replace("/", ".")
        return bytecode._scan([(f"{class_name}.class", maker.build()), ("module.properties", f"entry={entry}\n".encode())], "server", "plain", set())

    def test_a_module_cant_reach_the_patcher_either(self):
        for reference in ("org/spongepowered/asm/mixin/Mixins", "org/objectweb/asm/ClassWriter", "net/fabricmc/loader/impl/FabricLoaderImpl", "com/llamalad7/mixinextras/MixinExtrasBootstrap"):
            self.assertIn(reference, self.module_problems("gm/feature/plain/Thing", reference))

    def test_a_module_cant_have_classes_where_mixins_go(self):
        """The game's own loader is asked first, so that class would be the mixins' copy, not this one."""
        self.assertIn("gm/feature/plain/shared/Thing.class", self.module_problems("gm/feature/plain/shared/Thing", "java/lang/String"))


class StaticChecks(Case):
    def feature(self, feature_id, mixins_entry, sources=None, resources=False):
        folder = self.folder / feature_id
        package = folder / "mixins" / "src" / "main" / "java" / "gm" / "feature" / feature_id / "mixin"
        package.mkdir(parents=True, exist_ok=True)
        for name, text in (sources or {}).items():
            (package / name).write_text(text, encoding="utf-8")
        if resources:
            (folder / "mixins" / "src" / "main" / "resources").mkdir(parents=True)
        return {feature_id: {"manifest": {"id": feature_id, **({"mixins": mixins_entry} if mixins_entry else {})}, "dir": folder}}

    GOOD_WHY = {"why": "WorldEvents has nothing for how a boat moves, and no behaviour runs for it."}
    GOOD = {"A.java": "import net.minecraft.world.entity.vehicle.boat.AbstractBoat;\n@Mixin(AbstractBoat.class)\nabstract class A {}\n"}

    def refused(self, features, words):
        with self.assertRaises(GateFailed) as caught:
            static.check_mixins(features)
        self.assertIn(words, caught.exception.message)

    def test_good(self):
        static.check_mixins(self.feature("boats", self.GOOD_WHY, self.GOOD))

    def test_needs_a_reason(self):
        self.refused(self.feature("boats", None, self.GOOD), "saying which hook you looked for")
        self.refused(self.feature("boats", {"why": "faster"}, self.GOOD), "more of a reason")

    def test_declared_but_missing(self):
        self.refused({"boats": {"manifest": {"id": "boats", "mixins": self.GOOD_WHY}, "dir": self.folder / "nothing"}}, "there's no mixins/src folder")

    def test_no_resources(self):
        self.refused(self.feature("boats", self.GOOD_WHY, self.GOOD, resources=True), "src/main/resources")

    def test_cap_on_a_feature(self):
        sources = {f"M{number}.java": self.GOOD["A.java"] for number in range(mixins.MOST_MIXINS_A_FEATURE + 1)}
        self.refused(self.feature("boats", self.GOOD_WHY, sources), "host_requests")

    def test_cap_on_a_world(self):
        features = {}
        for number in range(mixins.MOST_FEATURES_WITH_MIXINS + 1):
            features.update(self.feature(f"boats{number}", self.GOOD_WHY, self.GOOD))
        self.refused(features, "over the limit")

    def test_targets_are_seen_in_the_source(self):
        for text, words in (
                ("import gm.conduit.KillSwitch;\n@Mixin(KillSwitch.class)\nabstract class A {}\n", "gm.conduit.KillSwitch"),
                ('@Mixin(targets = "gm.conduit.provenance.Provenance")\nabstract class A {}\n', "gm.conduit.provenance.Provenance"),
                ("import net.minecraft.server.MinecraftServer;\n@Mixin(value = {MinecraftServer.class})\nabstract class A {}\n", "net.minecraft.server.MinecraftServer")):
            self.refused(self.feature("boats", self.GOOD_WHY, {"A.java": text}), words)

    def test_a_feature_cant_bring_its_own_build(self):
        """Gradle would run it in the builder, which can write to the engine's own jar, and then nothing after that could be trusted."""
        for side in ("server", "client", "mixins"):
            for name in ("build.gradle", "build.gradle.kts"):
                features = self.feature("boats", self.GOOD_WHY, self.GOOD)
                script = self.folder / "boats" / side / name
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text("// anything at all", encoding="utf-8")
                with self.assertRaises(GateFailed) as caught:
                    static.check_no_build_scripts(features)
                self.assertIn(f"{side}/{name}", caught.exception.message)
                script.unlink()
        static.check_no_build_scripts(self.feature("boats", self.GOOD_WHY, self.GOOD))

    def test_refused_annotations_are_seen_in_the_source(self):
        text = self.GOOD["A.java"] + "class B { @Overwrite void a() {} }\n"
        self.refused(self.feature("boats", self.GOOD_WHY, {"A.java": text}), "@Overwrite")
        text = self.GOOD["A.java"] + "class B { @Inject(require = 0) void a() {} }\n"
        self.refused(self.feature("boats", self.GOOD_WHY, {"A.java": text}), "require")


class WhenOneCrashes(Case):
    """What the watch does, with crash reports and a release on disk but nothing running."""

    REPORT = ("---- Minecraft Crash Report ----\nDescription: Ticking entity\n\njava.lang.IllegalStateException: no\n"
              "\tat net.minecraft.world.entity.vehicle.boat.AbstractBoat.handler$zzz000$mixin_boats$boom(AbstractBoat.java:1024)\n"
              "\tat net.minecraft.world.entity.vehicle.boat.AbstractBoat.tick(AbstractBoat.java)\n\n"
              "-- System Details --\n\tFabric Mods:\n\t\tmixin_boats: Mixins of boats 1\n\t\tmixin_ships: Mixins of ships 1\n")
    OTHER = "---- Minecraft Crash Report ----\nDescription: Exception ticking world\n\tFabric Mods:\n\t\tmixin_boats: Mixins of boats 1\n\t\tmixin_ships: Mixins of ships 1\n"

    def setUp(self):
        super().setUp()
        for target, value in ((runtime, {"RUNTIME": self.folder, "BROKER": self.folder / "broker", "RELEASES": self.folder / "releases", "HISTORY": self.folder / "releases" / "history",
                                         "STATE_FILE": self.folder / "broker" / "state.json", "TIMELINE": self.folder / "timeline.jsonl"}),
                              (deploy, {"CRASHED_MIXINS": self.folder / "broker" / "crashed_mixins.json", "MIXIN_WATCH": self.folder / "broker" / "mixin_watch.json",
                        "CRASHED_MIXINS_FOR_AGENT": self.folder / "agent-workspace" / "reports" / "crashed_mixins.json"})):
            for name, path in value.items():
                patcher = unittest.mock.patch.object(target, name, path)
                patcher.start()
                self.addCleanup(patcher.stop)
        self.rollbacks = []
        rollback = unittest.mock.patch.object(deploy, "rollback", lambda state, reason: self.rollbacks.append((state["current"], reason)))
        rollback.start()
        self.addCleanup(rollback.stop)
        self.docker = {"RestartCount": 0}
        inspect = unittest.mock.patch.object(runtime, "inspect_state", lambda server: self.docker)
        inspect.start()
        self.addCleanup(inspect.stop)
        self.reports = self.folder / "prod" / "crash-reports"
        self.reports.mkdir(parents=True)
        runtime.save_state({"current": "r1", "previous": "r0"})
        self.jars = runtime.HISTORY / "r1" / "jars"
        self.jars.mkdir(parents=True)
        for name in ("conduit-0.0.1.jar", "mixin-boats.jar", "mixin-ships.jar"):
            (self.jars / name).write_bytes(name.encode())

    def crash(self, number, text):
        (self.reports / f"crash-{number}-server.txt").write_text(text, encoding="utf-8")

    def test_old_reports_arent_blamed_on_anything(self):
        self.crash(1, self.REPORT)
        self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.assertTrue((self.jars / "mixin-boats.jar").exists())
        self.assertEqual(self.rollbacks, [])

    def test_a_crash_takes_out_only_the_mixin_it_points_to(self):
        deploy.check_for_mixin_crashes()
        self.crash(2, self.REPORT)
        self.assertEqual(deploy.check_for_mixin_crashes(), ["boats"])
        self.assertFalse((self.jars / "mixin-boats.jar").exists())
        self.assertTrue((self.jars / "mixin-ships.jar").exists())
        self.assertTrue((self.jars / "conduit-0.0.1.jar").exists())
        self.assertEqual(len(self.rollbacks), 1)
        self.assertEqual(deploy.crashed_mixins()["boats"]["sha256"], hashlib.sha256(b"mixin-boats.jar").hexdigest())
        told = json.loads(deploy.CRASHED_MIXINS_FOR_AGENT.read_text(encoding="utf-8"))["boats"]
        self.assertIn("AbstractBoat.tick", told["crash"])
        self.assertNotIn("Fabric Mods", told["crash"].split("-- System Details")[0])
        # And it's only dealt with once.
        self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.assertEqual(len(self.rollbacks), 1)

    def test_being_listed_in_a_report_isnt_being_blamed(self):
        deploy.check_for_mixin_crashes()
        self.crash(2, self.OTHER)
        self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.assertEqual(self.rollbacks, [])

    def test_a_crash_that_keeps_happening_takes_them_all_out(self):
        deploy.check_for_mixin_crashes()
        for number in range(deploy.CRASHES_BEFORE_ALL_MIXINS_GO):
            self.crash(number + 2, self.OTHER)
            removed = deploy.check_for_mixin_crashes()
        self.assertEqual(removed, ["boats", "ships"])
        self.assertEqual(len(self.rollbacks), 1)

    def test_a_message_cant_put_the_blame_on_someone_else(self):
        deploy.check_for_mixin_crashes()
        self.crash(2, self.OTHER.replace("Description: Exception ticking world", "Description: Exception ticking world\njava.lang.IllegalStateException: gm.feature.ships.mixin $mixin_ships$"))
        self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.assertEqual(self.rollbacks, [])

    def test_a_server_that_keeps_stopping_with_no_report(self):
        """It can fail before there's any game to write one, or be told to stop."""
        self.docker["RestartCount"] = 4
        deploy.check_for_mixin_crashes()
        self.assertEqual(self.rollbacks, [], "what happened before the first look isn't counted")
        self.docker["RestartCount"] = 6
        self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.docker["RestartCount"] = 7
        self.assertEqual(deploy.check_for_mixin_crashes(), ["boats", "ships"])
        self.assertIn("3 times", self.rollbacks[0][1])

    def test_a_report_and_a_restart_are_one_crash(self):
        deploy.check_for_mixin_crashes()
        self.docker["RestartCount"] = 1
        self.crash(2, self.OTHER)
        self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.docker["RestartCount"] = 2
        self.crash(3, self.OTHER)
        self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.assertEqual(self.rollbacks, [])

    def test_a_restart_by_hand_starts_the_count_again(self):
        deploy.check_for_mixin_crashes()
        self.docker["RestartCount"] = 2
        deploy.check_for_mixin_crashes()
        self.docker["RestartCount"] = 0
        self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.docker["RestartCount"] = 1
        self.assertEqual(deploy.check_for_mixin_crashes(), ["boats", "ships"], "three stops in the window, whatever the count did in between")

    def test_nothing_happens_with_no_mixins(self):
        (self.jars / "mixin-boats.jar").unlink()
        (self.jars / "mixin-ships.jar").unlink()
        deploy.check_for_mixin_crashes()
        for number in range(deploy.CRASHES_BEFORE_ALL_MIXINS_GO + 1):
            self.crash(number + 2, self.OTHER)
            self.assertEqual(deploy.check_for_mixin_crashes(), [])
        self.assertEqual(self.rollbacks, [])

    def test_the_same_jar_is_left_out_of_the_next_release(self):
        built = self.built_jar("good_mixin")
        mods = self.folder / "mods"
        libs = mods / "genesis" / "features" / "good_mixin" / "mixins" / "build" / "libs"
        libs.mkdir(parents=True)
        (libs / "feature-good_mixin-mixins.jar").write_bytes(built.read_bytes())
        features = {"good_mixin": {"manifest": {}, "dir": mods / "genesis" / "features" / "good_mixin"}}
        (features["good_mixin"]["dir"] / "mixins" / "src").mkdir(parents=True)
        work = unittest.mock.patch.object(runtime, "WORK", self.folder / "work")
        work.start()
        self.addCleanup(work.stop)
        report = {}
        jars = promote.collect_mixins(features, mods, report)
        self.assertEqual([jar.name for jar in jars], ["mixin-good_mixin.jar"])
        self.assertEqual(report, {})
        digest = hashlib.sha256(jars[0].read_bytes()).hexdigest()

        deploy.CRASHED_MIXINS.parent.mkdir(parents=True, exist_ok=True)
        deploy.CRASHED_MIXINS.write_text(json.dumps({"good_mixin": {"sha256": digest, "reason": "it crashed"}}), encoding="utf-8")
        self.assertEqual(promote.collect_mixins(features, mods, report), [])
        self.assertEqual(report["withheld_mixins"], {"good_mixin": "it crashed"})

        deploy.CRASHED_MIXINS.write_text(json.dumps({"good_mixin": {"sha256": "something older", "reason": "it crashed"}}), encoding="utf-8")
        self.assertEqual(len(promote.collect_mixins(features, mods, {})), 1)


class Rollback(Case):
    def test_with_nothing_to_go_back_to_the_mixin_still_goes(self):
        current = self.folder / "releases" / "current"
        current.mkdir(parents=True)
        (current / "conduit.jar").write_bytes(b"x")
        (current / "mixin-boats.jar").write_bytes(b"x")
        with unittest.mock.patch.object(runtime, "RELEASES", self.folder / "releases"), \
                unittest.mock.patch.object(runtime, "HISTORY", self.folder / "releases" / "history"), \
                unittest.mock.patch.object(runtime, "RUNTIME", self.folder), \
                unittest.mock.patch.object(deploy, "tell_players"), \
                unittest.mock.patch.object(deploy, "_restart_prod") as restart:
            deploy.rollback({"current": None}, "testing")
        restart.assert_called_once()
        self.assertEqual(sorted(path.name for path in current.iterdir()), ["conduit.jar"])

    def test_install_jars_leaves_no_old_mixin_behind(self):
        """Rollback is this, so going back to a release from before a mixin has to remove the mixin."""
        current = self.folder / "releases" / "current"
        current.mkdir(parents=True)
        (current / "mixin-boats.jar").write_bytes(b"x")
        release = self.folder / "releases" / "history" / "r0"
        (release / "jars").mkdir(parents=True)
        (release / "jars" / "conduit.jar").write_bytes(b"y")
        with unittest.mock.patch.object(runtime, "RELEASES", self.folder / "releases"):
            deploy._install_jars(release)
        self.assertEqual(sorted(path.name for path in current.iterdir()), ["conduit.jar"])


class WithoutMixins(Case):
    def boot(self, logs):
        candidate = self.folder / "candidate"
        candidate.mkdir(exist_ok=True)
        jars = [candidate / "mixin-boats.jar", candidate / "conduit.jar"]
        for jar in jars:
            jar.write_bytes(b"x")
        with unittest.mock.patch.object(shadow, "runtime") as stack, unittest.mock.patch.object(shadow, "start") as start, \
                unittest.mock.patch.object(shadow.time, "sleep"):
            stack.candidate_folder.return_value = candidate
            stack.logs_since.return_value = logs
            try:
                shadow.boot_without_mixins(jars)
            finally:
                stack.stack.assert_called_with("stop", "shadow", check=False)
            start.assert_called_once()
            self.assertEqual(start.call_args.kwargs, {"test_mods": False})
        self.assertEqual(sorted(path.name for path in candidate.iterdir()), ["conduit.jar"])

    def test_a_clean_boot_passes(self):
        self.boot("[Server thread/INFO] Done")

    def test_a_world_that_loses_something_is_refused(self):
        with self.assertRaises(GateFailed) as caught:
            self.boot("[Server thread/ERROR] Recoverable errors when loading section [3, 1, 2]")
        self.assertIn("A rollback must work without them", caught.exception.message)
        self.assertIn("Recoverable errors when loading section", caught.exception.message)


class TheBuild(Case):
    def test_a_link_in_a_feature_is_refused(self):
        """It could point at anything on the machine reading it, like what a build leaves for the gates, or the broker's own files."""
        folder = self.folder / "features" / "boats"
        (folder / "mixins").mkdir(parents=True)
        (folder / "feature.json").write_text(json.dumps({"id": "boats"}), encoding="utf-8")
        self.assertEqual(list(bundles.load_features(self.folder / "features")), ["boats"])
        (folder / "mixins" / "build").symlink_to(self.folder)
        with self.assertRaises(bundles.BundleError) as caught:
            bundles.load_features(self.folder / "features")
        self.assertIn("is a link", str(caught.exception))

    def test_nothing_from_a_feature_gets_expanded(self):
        """Expanding a file runs what's in it as Groovy, so it can only be for our own mods."""
        build = (pathlib.Path(__file__).resolve().parents[2] / "mods" / "build.gradle").read_text(encoding="utf-8")
        guarded = build[build.index("if (!project.name.startsWith('feature-'))"):]
        self.assertLess(guarded.index("processResources"), guarded.index("expand "))
        self.assertEqual(build.count("expand "), 1)


class TheRest(Case):
    def test_showing_one_method(self):
        lines = ["public class net.minecraft.Boat {", "  private float speed;", "", "  public net.minecraft.Boat(int);", "    Code:", "       0: return", "",
                 "  private void floatBoat();", "    Code:", "       0: ldc  #1  // float 0.9f", "", "  static {};", "    Code:", "       0: return", "}"]
        self.assertEqual(daemon._one_method(lines, "floatBoat", "net.minecraft.Boat"), ["  private void floatBoat();", "    Code:", "       0: ldc  #1  // float 0.9f", ""])
        self.assertIn("  public net.minecraft.Boat(int);", daemon._one_method(lines, "<init>", "net.minecraft.Boat"))
        self.assertIn("  static {};", daemon._one_method(lines, "<clinit>", "net.minecraft.Boat"))
        self.assertIn("no method", daemon._one_method(lines, "nothing", "net.minecraft.Boat")[0])

    def test_finding_features(self):
        folder = self.folder / "boats"
        (folder / "mixins" / "src").mkdir(parents=True)
        self.assertEqual(bundles.find_mixins({"boats": {"dir": folder}, "ores": {"dir": self.folder / "ores"}}), ["boats"])
        self.assertEqual(bundles.find_modules({"boats": {"dir": folder}}), [])

    def test_only_changed_mixins_are_new(self):
        current = self.folder / "history" / "r1"
        (current / "jars").mkdir(parents=True)
        (current / "jars" / "mixin-same.jar").write_bytes(b"same")
        (current / "jars" / "mixin-changed.jar").write_bytes(b"old")
        (current / "jars" / "conduit.jar").write_bytes(b"old")
        for name, data in (("mixin-same.jar", b"same"), ("mixin-changed.jar", b"new"), ("mixin-added.jar", b"new"), ("conduit.jar", b"new")):
            (self.folder / name).write_bytes(data)
        jars = [self.folder / name for name in ("mixin-same.jar", "mixin-changed.jar", "mixin-added.jar", "conduit.jar")]
        self.assertEqual(sorted(promote.new_mixins(jars, current)), ["added", "changed"])
        self.assertEqual(sorted(promote.new_mixins(jars, self.folder / "never")), ["added", "changed", "same"])

    def test_applied_count_has_to_match(self):
        jars = [pathlib.Path("mixin-boats.jar"), pathlib.Path("conduit.jar")]
        shadow.check_mixins_applied(jars, "[Server thread/INFO] (Conduit) feature mixins in place: 2 from 1 features")
        shadow.check_mixins_applied([pathlib.Path("conduit.jar")], "nothing about them at all")
        with self.assertRaises(GateFailed):
            shadow.check_mixins_applied(jars, "[Server thread/INFO] (Conduit) feature mixins in place: 0 from 0 features")
        with self.assertRaises(GateFailed):
            shadow.check_mixins_applied(jars, "nothing about them at all")

    def test_failures_show_in_the_log_scan(self):
        for line in ("[Server thread/ERROR] (Conduit) feature mixin gm.feature.boats.mixin.A didn't apply to net.minecraft.Thing",
                     "[main/ERROR] (mixin) Mixin apply for mod mixin_boats failed mixin_boats.mixins.json:A from mod mixin_boats -> net.minecraft.Thing: org.spongepowered.asm.mixin.injection.throwables.InvalidInjectionException",
                     "[main/WARN] (mixin) @Mixin target net.minecraft.NotAThing was not found mixin_boats.mixins.json:A from mod mixin_boats"):
            self.assertTrue(shadow.scan_logs(line), line)
        self.assertFalse(shadow.scan_logs("[Server thread/INFO] (Conduit) feature mixins in place: 2 from 1 features"))


if __name__ == "__main__":
    unittest.main()
