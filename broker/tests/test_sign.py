"""Module signing, and how promote and rollback use it. Needs no server, and never touches the real key:
every test here works in a temporary folder.

Usage: python3 -m unittest broker.tests.test_sign
"""
import base64
import json
import pathlib
import shutil
import stat
import tempfile
import threading
import unittest
import unittest.mock
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from broker import deploy, promote, runtime, sign
from broker.gates import GateFailed


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.signing = self.root / "signing"
        patcher = unittest.mock.patch.object(sign, "SIGNING", self.signing)
        patcher.start()
        self.addCleanup(patcher.stop)
        printing = unittest.mock.patch("builtins.print")
        self.printed = printing.start()
        self.addCleanup(printing.stop)

    def make_jar(self, name="feature", folder=None, contents=b"entry=x\n"):
        folder = folder or self.root
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.jar"
        with zipfile.ZipFile(path, "w") as archive:
            # A fixed date, so the same contents always make the same bytes.
            archive.writestr(zipfile.ZipInfo("module.properties", (2026, 1, 1, 0, 0, 0)), contents)
        return path


class Keys(Case):
    def test_creates_a_keypair_with_the_right_permissions(self):
        sign.sign_module(self.make_jar(), "feature")
        self.assertEqual(stat.S_IMODE((self.signing / sign.PRIVATE_KEY).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.signing.stat().st_mode), 0o700)

    def test_prints_the_public_key_once_in_base64(self):
        jar = self.make_jar()
        sign.sign_module(jar, "feature")
        sign.sign_module(jar, "feature")
        pinned = sign.public_key_text()
        printed = [call.args[0] for call in self.printed.call_args_list]
        self.assertEqual(len(printed), 1)
        self.assertIn(pinned, printed[0])
        self.assertEqual(len(base64.b64decode(pinned, validate=True)), 32)

    def test_public_key_loads_in_the_form_the_companion_reads(self):
        sign.sign_module(self.make_jar(), "feature")
        Ed25519PublicKey.from_public_bytes(base64.b64decode(sign.public_key_text()))

    def test_keeps_the_same_key(self):
        jar = self.make_jar()
        sign.sign_module(jar, "feature")
        first = (self.signing / sign.PRIVATE_KEY).read_bytes()
        pinned = sign.public_key_text()
        sign.sign_module(jar, "feature")
        self.assertEqual((self.signing / sign.PRIVATE_KEY).read_bytes(), first)
        self.assertEqual(sign.public_key_text(), pinned)

    def test_restores_a_lost_public_key_from_the_private_one(self):
        jar = self.make_jar()
        sign.sign_module(jar, "feature")
        pinned = sign.public_key_text()
        (self.signing / sign.PUBLIC_KEY).unlink()
        sign.sign_module(jar, "feature")
        self.assertEqual(sign.public_key_text(), pinned)

    def test_refuses_a_key_others_can_read(self):
        jar = self.make_jar()
        sign.sign_module(jar, "feature")
        (self.signing / sign.PRIVATE_KEY).chmod(0o640)
        with self.assertRaisesRegex(sign.SigningError, "read by other users"):
            sign.sign_module(jar, "feature")

    def test_wont_replace_a_lost_private_key_silently(self):
        jar = self.make_jar()
        sign.sign_module(jar, "feature")
        (self.signing / sign.PRIVATE_KEY).unlink()
        with self.assertRaisesRegex(sign.SigningError, "pinned"):
            sign.sign_module(jar, "feature")

    def test_refuses_a_damaged_key(self):
        jar = self.make_jar()
        sign.sign_module(jar, "feature")
        (self.signing / sign.PRIVATE_KEY).write_bytes(b"not a key")
        with self.assertRaisesRegex(sign.SigningError, "readable key"):
            sign.sign_module(jar, "feature")


class Signatures(Case):
    def test_signs_what_the_client_verifies(self):
        jar = self.make_jar()
        record = sign.sign_module(jar, "feature")
        digest = sign.hashlib.sha256(jar.read_bytes()).hexdigest()
        message = f"feature\n{record['generation']}\n{digest}".encode()
        self.assertEqual(sign.signed_message("feature", record["generation"], digest), message)
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(sign.public_key_text()))
        key.verify(base64.b64decode(record["signature"], validate=True), message)

    def test_returns_generation_and_signature(self):
        record = sign.sign_module(self.make_jar(), "feature")
        self.assertEqual(set(record), {"generation", "signature"})
        self.assertIsInstance(record["generation"], int)
        self.assertIsInstance(record["signature"], str)

    def test_writes_it_next_to_the_jar(self):
        jar = self.make_jar()
        record = sign.sign_module(jar, "feature")
        self.assertEqual((self.root / "feature.jar.sig").read_text(encoding="ascii"), record["signature"])

    def test_verifies(self):
        jar = self.make_jar()
        record = sign.sign_module(jar, "feature")
        self.assertTrue(sign.verify_signature(jar, "feature", record["generation"], record["signature"]))

    def test_any_change_breaks_it(self):
        jar = self.make_jar()
        record = sign.sign_module(jar, "feature")
        self.assertFalse(sign.verify_signature(jar, "other", record["generation"], record["signature"]))
        self.assertFalse(sign.verify_signature(jar, "feature", record["generation"] + 1, record["signature"]))
        raw = bytearray(base64.b64decode(record["signature"]))
        raw[0] ^= 1
        self.assertFalse(sign.verify_signature(jar, "feature", record["generation"], base64.b64encode(bytes(raw)).decode()))
        jar.write_bytes(jar.read_bytes() + b"\0")
        self.assertFalse(sign.verify_signature(jar, "feature", record["generation"], record["signature"]))

    def test_rubbish_is_false_not_an_error(self):
        jar = self.make_jar()
        record = sign.sign_module(jar, "feature")
        self.assertFalse(sign.verify_signature(jar, "feature", record["generation"], "not base64!"))
        self.assertFalse(sign.verify_signature(jar, "feature", record["generation"], record["signature"], public_key="bad"))

    def test_another_key_fails(self):
        jar = self.make_jar()
        record = sign.sign_module(jar, "feature")
        other = base64.b64encode(bytes(32)).decode()
        self.assertFalse(sign.verify_signature(jar, "feature", record["generation"], record["signature"], public_key=other))

    def test_module_id_cant_break_out_of_its_line(self):
        for module_id in ("a\n1", "A", "a/b", "", None):
            with self.subTest(module_id):
                with self.assertRaisesRegex(sign.SigningError, "valid module id"):
                    sign.sign_module(self.make_jar(), module_id)

    def test_missing_jar_uses_up_no_generation(self):
        with self.assertRaises(OSError):
            sign.sign_module(self.root / "absent.jar", "feature")
        self.assertEqual(sign.sign_module(self.make_jar(), "feature")["generation"], 1)


class Generations(Case):
    def test_only_ever_increase(self):
        jar = self.make_jar()
        numbers = [sign.sign_module(jar, "feature")["generation"] for _ in range(5)]
        self.assertEqual(numbers, [1, 2, 3, 4, 5])

    def test_per_module(self):
        self.assertEqual(sign.sign_module(self.make_jar("a"), "a")["generation"], 1)
        self.assertEqual(sign.sign_module(self.make_jar("b"), "b")["generation"], 1)
        self.assertEqual(sign.sign_module(self.make_jar("a"), "a")["generation"], 2)

    def test_saved_on_disk(self):
        sign.sign_module(self.make_jar(), "feature")
        self.assertEqual(json.loads((self.signing / sign.GENERATIONS).read_text(encoding="utf-8")), {"feature": 1})

    def test_overlapping_runs_dont_share_a_number(self):
        jar = self.make_jar()
        numbers = []

        def work():
            numbers.append(sign.sign_module(jar, "feature")["generation"])

        threads = [threading.Thread(target=work) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(numbers), list(range(1, 13)))

    def test_lost_generations_stop_it_rather_than_starting_over(self):
        jar = self.make_jar()
        sign.sign_module(jar, "feature")
        (self.signing / sign.GENERATIONS).unlink()
        with self.assertRaisesRegex(sign.SigningError, "backup"):
            sign.sign_module(jar, "feature")

    def test_damaged_generations_stop_it(self):
        jar = self.make_jar()
        sign.sign_module(jar, "feature")
        for text in ("{not json", "[1, 2]", '{"feature": "many"}', '{"feature": -1}', '{"feature": true}'):
            with self.subTest(text):
                (self.signing / sign.GENERATIONS).write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(sign.SigningError, "backup"):
                    sign.sign_module(jar, "feature")


class Release(Case):
    def test_writes_what_the_server_reads(self):
        content = self.root / "content"
        jar = self.make_jar("feature", content / "modules" / "client")
        sign.sign_release(content)
        record = json.loads((jar.parent / "feature.json").read_text(encoding="utf-8"))
        # ModulePush.readFolder reads exactly these two names from this file.
        self.assertEqual(set(record), {"generation", "signature"})
        self.assertTrue(sign.verify_signature(jar, "feature", record["generation"], record["signature"]))
        self.assertTrue((jar.parent / "feature.jar.sig").exists())

    def test_leaves_server_modules_alone(self):
        content = self.root / "content"
        self.make_jar("feature", content / "modules" / "server")
        sign.sign_release(content)
        self.assertFalse((content / "modules" / "server" / "feature.json").exists())
        self.assertFalse(self.signing.exists())

    def signed_pair(self, contents=b"entry=x\n"):
        """An already signed release, and a new one with this jar in it."""
        old, new = self.root / "old", self.root / "new"
        old_jar = self.make_jar("feature", old / "modules" / "client")
        sign.sign_release(old)
        self.make_jar("feature", new / "modules" / "client", contents)
        record = json.loads((old_jar.parent / "feature.json").read_text(encoding="utf-8"))
        return old, new, record

    def record_in(self, content):
        return json.loads((content / "modules" / "client" / "feature.json").read_text(encoding="utf-8"))

    def test_an_unchanged_jar_keeps_its_record(self):
        # Otherwise every release would make every player reload every module for no reason.
        old, new, record = self.signed_pair()
        sign.sign_release(new, old)
        self.assertEqual(self.record_in(new), record)

    def test_a_changed_jar_gets_a_new_generation(self):
        old, new, record = self.signed_pair(b"entry=y\n")
        sign.sign_release(new, old)
        self.assertGreater(self.record_in(new)["generation"], record["generation"])

    def test_with_no_previous_release_it_signs_again(self):
        # What a rollback does: old code has to go out newer than what players have already run.
        _, new, record = self.signed_pair()
        sign.sign_release(new)
        self.assertGreater(self.record_in(new)["generation"], record["generation"])

    def test_marked_for_testing_is_not_a_signature(self):
        content = self.root / "content"
        jar = self.make_jar("feature", content / "modules" / "client")
        sign.mark_for_testing(content)
        record = self.record_in(content)
        self.assertEqual(record["signature"], "")
        self.assertFalse(sign.verify_signature(jar, "feature", record["generation"], record["signature"], base64.b64encode(bytes(32)).decode()))


class Promote(Case):
    def setUp(self):
        super().setUp()
        self.content = self.root / "work" / "content"
        for name, value in (("WORK", self.root / "work"), ("HISTORY", self.root / "history"), ("REPORTS", self.root / "reports"),
                            ("BROKER", self.root / "broker"), ("AGENT_DISABLED", self.root / "disabled")):
            patcher = unittest.mock.patch.object(runtime, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (unittest.mock.patch.object(runtime, "load_state", return_value={"current": "old", "previous": None}),
                        unittest.mock.patch.object(runtime, "record_timeline")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_promote(self, deploy_to_prod=True, check_only=False, tier="T2"):
        """Runs promote with every stage that touches the world replaced, recording the order things happen in."""
        steps = []
        features = {"feature": {"manifest": {"id": "feature"}, "dir": self.root / "src"}}
        (self.root / "src" / "client" / "src").mkdir(parents=True, exist_ok=True)

        def collect(_features, _mods, content):
            steps.append("collect")
            self.make_jar("feature", content / "modules" / "client")

        def store(_release, _jars, content, _ledger):
            steps.append(("store", (content / "modules" / "client" / "feature.json").exists()))
            return self.root / "stored"

        with (unittest.mock.patch.multiple(
                promote,
                prepare_source=lambda source: self.root,
                compile_content=lambda *args: (features, {}, {}, {"blocks": {}, "items": {}}),
                build=lambda mods: steps.append("build"),
                collect_jars=lambda mods: [],
                collect_modules=collect,
                choose_tier=lambda content, jars: tier)), \
             unittest.mock.patch("broker.gates.static.run"), \
             unittest.mock.patch("broker.bundles.save_ledger"), \
             unittest.mock.patch("broker.gates.bytecode.check_jar", side_effect=lambda *args: steps.append(("bytecode", args[1], args[2]))), \
             unittest.mock.patch("broker.gates.shadow.run_gate", side_effect=lambda *args: steps.append("shadow") or {}), \
             unittest.mock.patch("broker.gates.client.run_gate", side_effect=lambda *args: steps.append("client") or []), \
             unittest.mock.patch("broker.deploy.store_release", side_effect=store), \
             unittest.mock.patch("broker.deploy.deploy", side_effect=lambda *args: steps.append("deploy") or {}):
            report = promote.promote(self.root, "r1", deploy_to_prod, False, promote.Stages("r1"), check_only)
        return report, steps

    def test_bytecode_comes_straight_after_collecting(self):
        _, steps = self.run_promote()
        self.assertEqual(steps[steps.index("collect") + 1], ("bytecode", "client", "feature"))

    def test_the_quick_check_gets_the_bytecode_gate_too(self):
        # It's what the agent's check_feature tool runs, so this is where it hears about a refusal.
        report, steps = self.run_promote(check_only=True)
        self.assertIn(("bytecode", "client", "feature"), steps)
        self.assertEqual(report["result"], "passed_gates")

    def test_bytecode_failure_stops_the_release(self):
        with unittest.mock.patch("broker.gates.bytecode.check_jar", side_effect=GateFailed("bytecode", "no")):
            with self.assertRaises(GateFailed):
                promote.check_modules({"feature": {"manifest": {}, "dir": self._feature_dir()}}, self.content)

    def _feature_dir(self):
        folder = self.root / "src"
        (folder / "client" / "src").mkdir(parents=True, exist_ok=True)
        return folder

    def test_signs_just_before_the_release_is_stored(self):
        _, steps = self.run_promote()
        self.assertEqual(steps[-2:], [("store", True), "deploy"])
        self.assertLess(steps.index("client"), steps.index(("store", True)))
        self.assertTrue((self.content / "modules" / "client" / "feature.jar.sig").exists())
        record = json.loads((self.content / "modules" / "client" / "feature.json").read_text(encoding="utf-8"))
        self.assertTrue(sign.verify_signature(self.content / "modules" / "client" / "feature.jar", "feature", record["generation"], record["signature"]))

    def test_a_trial_run_uses_up_no_generation(self):
        self.run_promote(deploy_to_prod=False)
        self.run_promote(check_only=True)
        self.assertFalse(self.signing.exists())

    def test_nothing_to_release_uses_up_no_generation(self):
        report, _ = self.run_promote(tier=None)
        self.assertEqual(report["result"], "nothing_to_release")
        self.assertFalse(self.signing.exists())

    def test_kill_switch_uses_up_no_generation(self):
        runtime.AGENT_DISABLED.touch()
        with self.assertRaises(GateFailed):
            self.run_promote()
        self.assertFalse(self.signing.exists())

    def test_a_release_doesnt_repeat_gates_that_just_passed(self):
        _, first = self.run_promote(deploy_to_prod=False)
        self.assertIn("shadow", first)
        # A real run renders the content afresh each time. compile_content is replaced here, so do what it would.
        shutil.rmtree(self.content)
        _, second = self.run_promote()
        self.assertNotIn("shadow", second)
        self.assertNotIn("client", second)
        self.assertEqual(second[-1], "deploy")

    def test_different_content_runs_the_gates_again(self):
        self.run_promote(deploy_to_prod=False)
        with unittest.mock.patch.object(promote, "fingerprint", return_value="something else"):
            _, steps = self.run_promote(deploy_to_prod=False)
        self.assertIn("shadow", steps)

    def test_signing_failure_is_a_gate_failure(self):
        with unittest.mock.patch.object(sign, "sign_release", side_effect=sign.SigningError("no")):
            with self.assertRaises(GateFailed) as caught:
                promote.sign_modules(self.content, None)
        self.assertEqual(caught.exception.gate, "sign")

    def test_signatures_dont_make_a_release_look_changed(self):
        """A signed old release against a fresh unsigned build of the same jar has to be nothing_to_release."""
        old = runtime.HISTORY / "old" / "content"
        for root in (old, self.content):
            for part in ("pack", "datapack", "config"):
                (root / part).mkdir(parents=True, exist_ok=True)
            self.make_jar("feature", root / "modules" / "client")
        (runtime.HISTORY / "old" / "jars").mkdir(parents=True)
        (old / "modules" / "client" / "feature.jar").write_bytes((self.content / "modules" / "client" / "feature.jar").read_bytes())
        sign.sign_release(old)
        self.assertIsNone(promote.choose_tier(self.content, []))

    def test_a_changed_jar_is_still_a_change(self):
        old = runtime.HISTORY / "old" / "content"
        for root in (old, self.content):
            for part in ("pack", "datapack", "config"):
                (root / part).mkdir(parents=True, exist_ok=True)
        self.make_jar("feature", old / "modules" / "client")
        self.make_jar("feature", self.content / "modules" / "client", contents=b"entry=y\n")
        (runtime.HISTORY / "old" / "jars").mkdir(parents=True)
        self.assertEqual(promote.choose_tier(self.content, []), "T2")


class Rollback(Case):
    def setUp(self):
        super().setUp()
        for name, value in (("RUNTIME", self.root / "runtime"), ("HISTORY", self.root / "history")):
            patcher = unittest.mock.patch.object(runtime, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Nothing here may reach a real server.
        self.applied = []
        for patcher in (unittest.mock.patch.object(deploy, "_install_jars"), unittest.mock.patch.object(deploy, "_restart_prod"),
                        unittest.mock.patch.object(runtime, "apply_content", side_effect=lambda server, content: self.applied.append(content))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.content = runtime.HISTORY / "good" / "content"
        self.jar = self.make_jar("feature", self.content / "modules" / "client")
        sign.sign_release(self.content)

    def record(self):
        return json.loads(self.jar.with_suffix(".json").read_text(encoding="utf-8"))

    def test_old_code_goes_out_under_a_new_generation(self):
        # The failed release used up generation 2, and companions may have run it.
        sign.sign_module(self.make_jar("feature", self.root / "failed"), "feature")
        deploy.rollback({"current": "good"}, "it broke")
        record = self.record()
        self.assertEqual(record["generation"], 3)
        self.assertTrue(sign.verify_signature(self.jar, "feature", record["generation"], record["signature"]))
        self.assertEqual(self.applied, [self.content])

    def test_signing_trouble_cant_stop_a_rollback(self):
        before = self.record()
        with unittest.mock.patch.object(sign, "sign_release", side_effect=sign.SigningError("no key")):
            deploy.rollback({"current": "good"}, "it broke")
        self.assertEqual(self.applied, [self.content])
        self.assertEqual(self.record(), before)
        deploy._restart_prod.assert_called_once()


if __name__ == "__main__":
    unittest.main()
