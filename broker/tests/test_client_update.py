#!/usr/bin/env python3
"""The updater, run for real against a local web server, from a copy of how a friend's game folder looks. What matters most here is what
it refuses, because anything it accepts runs with no limits on a friend's PC, and that it never stops the game from starting.

Needs Docker, for the JDK. Usage: python3 -m unittest broker.tests.test_client_update
"""
import base64
import functools
import hashlib
import http.server
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from broker import client_release

REPO = pathlib.Path(__file__).resolve().parents[2]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class LaunchCommand(unittest.TestCase):
    """Prism refuses to start the game if this command fails, so a wrong one locks everyone out. It reads instance.cfg with an older parser
    when the file has no ConfigVersion, like the pack's, and with QSettings once it's saved the file itself. Both have to come out right."""

    def line(self):
        script = (REPO / "scripts/make-friend-pack.sh").read_text(encoding="utf-8")
        return next(line for line in script.splitlines() if line.startswith("PreLaunchCommand=")).split("=", 1)[1]

    @staticmethod
    def older_parser(value):
        # unquote(unescape(value)) in Prism's launcher/settings/INIFile.cpp.
        out, previous = "", ""
        for character in value:
            if previous == "\\":
                out += {"n": "\n", "t": "\t"}.get(character, character)
                previous = ""
            elif character == "\\":
                previous = character
            else:
                out += character
        if any(mark in out for mark in ";=,") and out.startswith('"') and out.endswith('"'):
            out = out[1:-1]
        return out

    @staticmethod
    def qsettings(value):
        # Quotes that aren't escaped only group text, and are dropped. Escaped ones are kept.
        out, index = "", 0
        while index < len(value):
            if value[index] == "\\":
                index += 1
                out += value[index]
            elif value[index] != '"':
                out += value[index]
            index += 1
        return out

    def test_both_of_prisms_parsers_get_the_command_right(self):
        wanted = '"$INST_JAVA" -jar livingmod-updater.jar'
        self.assertEqual(self.older_parser(self.line()), wanted)
        self.assertEqual(self.qsettings(self.line()), wanted)


class Updating(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        root = pathlib.Path(cls.folder.name)
        os.chmod(root, 0o777)
        cls.key = Ed25519PrivateKey.generate()
        cls.pinned = root / "pinned.pub"
        cls.pinned.write_text(client_release.public_text(cls.key) + "\n", encoding="ascii")
        cls.jar = root / "updater.jar"
        subprocess.run([str(REPO / "scripts/build-updater.sh"), str(cls.pinned), str(cls.jar)], check=True, capture_output=True)

        cls.site = root / "site"
        cls.site.mkdir()
        handler = functools.partial(Quiet, directory=str(cls.site))
        cls.server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.server.shutdown)

    def setUp(self):
        for path in self.site.iterdir():
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        self.game_folder = tempfile.TemporaryDirectory(dir=self.folder.name)
        self.addCleanup(self.game_folder.cleanup)
        self.game = pathlib.Path(self.game_folder.name)
        os.chmod(self.game, 0o777)
        (self.game / "mods").mkdir()
        os.chmod(self.game / "mods", 0o777)
        shutil.copy(self.jar, self.game / "livingmod-updater.jar")
        self.point_at(f"http://127.0.0.1:{self.port}")

    def point_at(self, url):
        (self.game / "livingmod-updater.properties").write_text(f"url={url}\n", encoding="utf-8")

    def publish(self, files, generation=100, key=None):
        staging = pathlib.Path(tempfile.mkdtemp(dir=self.folder.name))
        for name, data in files.items():
            (staging / name).parent.mkdir(parents=True, exist_ok=True)
            (staging / name).write_bytes(data)
        client_release.release(staging, self.site, generation, key or self.key)

    def update(self):
        result = subprocess.run(
            ["docker", "run", "--rm", "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{self.game}:/game", "-w", "/game",
             "eclipse-temurin:25-jre", "java", "-jar", "livingmod-updater.jar"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False, timeout=120)
        return result.returncode, result.stdout

    def installed(self):
        return {path.name: path.read_bytes() for path in (self.game / "mods").iterdir()}

    def test_it_installs_what_is_signed(self):
        self.publish({"mods/a.jar": b"one", "mods/b+c.jar": b"two"})
        code, output = self.update()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.installed(), {"a.jar": b"one", "b+c.jar": b"two"}, output)

    def test_a_new_version_replaces_the_old_and_leaves_no_download_behind(self):
        self.publish({"mods/a.jar": b"one"}, 100)
        self.update()
        self.publish({"mods/a.jar": b"two"}, 101)
        self.update()
        self.assertEqual(self.installed(), {"a.jar": b"two"})
        self.assertFalse((self.game / "livingmod-updater-download").exists())

    def test_nothing_new_changes_nothing(self):
        self.publish({"mods/a.jar": b"one"})
        self.update()
        before = (self.game / "mods/a.jar").stat().st_mtime_ns
        time.sleep(0.05)
        _, output = self.update()
        self.assertEqual((self.game / "mods/a.jar").stat().st_mtime_ns, before)
        self.assertIn("up to date", output)

    def test_a_file_that_was_deleted_comes_back(self):
        self.publish({"mods/a.jar": b"one"})
        self.update()
        (self.game / "mods/a.jar").unlink()
        self.update()
        self.assertEqual(self.installed(), {"a.jar": b"one"})

    def test_what_it_stops_listing_goes_but_a_players_own_mod_stays(self):
        (self.game / "mods/players_own.jar").write_bytes(b"mine")
        self.publish({"mods/a.jar": b"one", "mods/b.jar": b"two"}, 100)
        self.update()
        self.publish({"mods/a.jar": b"one"}, 101)
        self.update()
        self.assertEqual(self.installed(), {"a.jar": b"one", "players_own.jar": b"mine"})

    def test_another_keys_signature_is_refused(self):
        self.publish({"mods/evil.jar": b"evil"}, key=Ed25519PrivateKey.generate())
        code, output = self.update()
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), {}, output)
        self.assertIn("isn't signed", output)

    def test_a_manifest_changed_after_signing_is_refused(self):
        self.publish({"mods/a.jar": b"one"})
        (self.site / "manifest").write_text((self.site / "manifest").read_text(encoding="utf-8") + "file mods/evil.jar " + "0" * 64 + " 1\n", encoding="utf-8")
        self.assertEqual(self.update()[0], 0)
        self.assertEqual(self.installed(), {})

    def test_a_file_changed_after_signing_is_refused_and_nothing_changes(self):
        self.publish({"mods/a.jar": b"one"}, 100)
        self.update()
        self.publish({"mods/a.jar": b"two", "mods/b.jar": b"bee"}, 101)
        digest = hashlib.sha256(b"bee").hexdigest()
        (self.site / "files" / digest).write_bytes(b"bad")
        code, output = self.update()
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), {"a.jar": b"one"}, output)

    def test_replaying_an_older_update_is_refused(self):
        self.publish({"mods/a.jar": b"new"}, 200)
        self.update()
        self.publish({"mods/a.jar": b"old and flawed"}, 100)
        code, output = self.update()
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), {"a.jar": b"new"}, output)

    def test_paths_outside_the_allowed_folders_are_refused_even_when_signed(self):
        for path in ("../evil.jar", "mods/../../evil.jar", "mods/.hidden", "livingmod-updater.jar", "mods/sub/evil.jar", "/etc/evil"):
            digest = hashlib.sha256(b"evil").hexdigest()
            (self.site / "files").mkdir(exist_ok=True)
            (self.site / "files" / digest).write_bytes(b"evil")
            body = f"livingmod-update 1\ngeneration 100\nfile {path} {digest} 4\n".encode("utf-8")
            (self.site / "manifest").write_bytes(body)
            (self.site / "manifest.sig").write_text(base64.b64encode(self.key.sign(body)).decode("ascii"), encoding="ascii")
            code, _ = self.update()
            self.assertEqual(code, 0)
            self.assertEqual(self.installed(), {}, path)
            self.assertFalse(list(pathlib.Path(self.folder.name).glob("evil*")), path)
            self.assertFalse((self.game / "evil.jar").exists(), path)

    def test_no_server_still_starts_the_game(self):
        (self.game / "mods/a.jar").write_bytes(b"one")
        self.point_at("http://127.0.0.1:9")
        code, output = self.update()
        self.assertEqual(code, 0, output)
        self.assertIn("without updating", output)
        self.assertEqual(self.installed(), {"a.jar": b"one"})

    def test_missing_settings_still_starts_the_game(self):
        (self.game / "livingmod-updater.properties").unlink()
        self.assertEqual(self.update()[0], 0)


if __name__ == "__main__":
    unittest.main()
