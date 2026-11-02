"""The website's page about the world. Friends can read whatever their browser receives, so what matters most here is what a spoiler-free page can't contain.
Needs Pillow, so it runs in the agent's image."""
import io
import json
import os
import pathlib
import tempfile
import time
import unittest

from PIL import Image

from orchestrator import world_page

NOW = 1_800_000_000.0
# Each of these is somewhere a spoiler or something private could be, so none of them can turn up anywhere in the spoiler-free tree, including in an address.
SPOILERS = ("brass", "kiln", "SPECWORD", "PROMPTWORD", "REASONWORD", "DOINGWORD", "SUMMARYWORD", "SHOWNWORD", "TITLEWORD", "GOALWORD", "NODEWORD", "HOLDSWORD", "THEMEWORD", "REALNAME", "TEXTWORD", "TRANSCRIPTWORD")


def page(number):
    return f"{number:020x}"


def png(size=(32, 32), colour=(200, 40, 40, 255)):
    out = io.BytesIO()
    Image.new("RGBA", size, colour).save(out, "PNG")
    return out.getvalue()


def released(number=1, **extra):
    return {"page": page(number), "run": f"brass_kiln-{1000 + number}", "key": "brass_kiln", "feature": "brass_kiln", "kind": "feature", "stage": "mid", "category": "machine", "node": "n_NODEWORD".lower(),
            "safe_name": "a furnace for mixing metals", "title": "TITLEWORD", "spec": "SPECWORD", "outcome": "released", "started_at": NOW - 900, "finished_at": NOW - 300, "seconds": 600.0,
            "tokens": {"builder": {"input": 1000, "output": 500, "cache_read": 0, "cache_write": 0}}, "phases": {"build": 200.0, "gates": 100.0}, "attempt": 2, "prompts": [{"text": "PROMPTWORD"}],
            "attempts": [{"attempt": 1, "kind": "review", "reason": "REASONWORD"}], "summary": "SUMMARYWORD", "shown": "SHOWNWORD", "entries": 2, **extra}


def building(number=2, **extra):
    return {**released(number), "outcome": None, "finished_at": None, "resumed_at": NOW - 120, "seconds": 10.0, "stage_now": "building", "queued_at": NOW - 500, "status": {"phase": "writing code", "doing": "DOINGWORD", "at": NOW - 5}, **extra}


def failed(number=3):
    return {**released(number), "outcome": "failed", "failure": {"kind": "gate", "reason": "REASONWORD"}}


def board(**extra):
    return {"at": NOW - 5, "chosen": True, "planning": True, "building": [page(2)], "theme": "# THEMEWORD\nTHEMEWORD",
            "queue": [{"key": "brass_kiln", "page": page(9), "kind": "feature", "safe_name": "early game mob", "title": "TITLEWORD", "category": "mob", "stage": "early", "node": "NODEWORD", "spec": "SPECWORD", "queued_at": NOW - 50}],
            "roadmap": {"goal": "GOALWORD", "nodes": [{"id": "n_nodeword", "stage": "mid", "name": "NODEWORD", "holds": "HOLDSWORD", "opens_with": "HOLDSWORD", "requires": []}]}, **extra}


WORLD = {"name": "REALNAME", "text": "TEXTWORD", "safe_name": "A place to explore", "tease": "Something is waiting.", "accent": "#336699"}


def rendered(records=None, the_board=None, world=WORLD):
    runs = [world_page.normal(record, NOW) for record in (records if records is not None else [released(), building(), failed()])]
    media = {view["page"]: {"shots": [("/world/spoilers/img/x/brass.jpg", "brass shot")], "assets": [("/world/spoilers/img/x/kiln.png", "kiln")]} for view in runs}
    transcripts = {view["page"]: "<h2>Transcript</h2>TRANSCRIPTWORD" for view in runs}
    return world_page.render(the_board if the_board is not None else board(), world, runs, media, transcripts, NOW)


def spoiler_free(files):
    return {path: data for path, data in files.items() if not path.startswith(world_page.SPOILERS)}


class SpoilerFree(unittest.TestCase):
    def test_nothing_about_what_anything_is_reaches_a_spoiler_free_page(self):
        files = spoiler_free(rendered())
        self.assertGreater(len(files), 6)
        for path, data in files.items():
            text = (path + data.decode("utf-8")).lower()
            for word in SPOILERS:
                self.assertNotIn(word.lower(), text, f"{word} in {path}")

    def test_it_doesnt_link_to_any_picture_of_the_real_thing(self):
        for path, data in spoiler_free(rendered()).items():
            self.assertNotIn(b"/img/", data, path)
            self.assertNotIn(b"banner.png", data, path)

    def test_what_a_spoiler_free_page_says(self):
        files = rendered()
        text = files["index.html"].decode()
        self.assertIn("A place to explore", text)
        self.assertIn("Something is waiting.", text)
        self.assertIn("A furnace for mixing metals", text)
        self.assertIn("Released", text)
        self.assertIn("Given up", text)
        self.assertIn("banner-mosaic.png", text)
        building_tab = files["building/index.html"].decode()
        self.assertIn("Builder is writing code", building_tab)
        self.assertIn('http-equiv="refresh"', building_tab)
        planned = files["planned/index.html"].decode()
        self.assertIn("Early game mob", planned)
        self.assertIn("More is being planned", planned)
        self.assertNotIn(f"f/{page(9)}", planned)

    def test_a_failure_only_says_what_kind_it_was(self):
        text = rendered()[f"f/{page(3)}/index.html"].decode()
        self.assertIn(world_page.e(world_page.FAILURE_WORDS["gate"]), text)
        self.assertNotIn("REASONWORD", text)

    def test_a_field_nobody_has_said_is_safe_never_gets_through(self):
        self.assertEqual(set(world_page.reduced(world_page.normal(released(), NOW))), set(world_page.SAFE_FIELDS))
        for field in ("title", "spec", "prompts", "attempts", "failure_reason", "doing", "summary", "shown", "feature", "key", "run", "node", "tokens", "screenshots"):
            self.assertNotIn(field, world_page.SAFE_FIELDS)

    def test_its_toggle_leads_to_the_same_page_with_spoilers(self):
        for path, data in spoiler_free(rendered()).items():
            if path.startswith("f/"):
                self.assertIn(f'href="/world/spoilers/{path[:-len("index.html")]}"'.encode(), data, path)

    def test_a_word_slipped_into_a_fixed_field_is_thrown_away(self):
        files = spoiler_free(rendered([released(stage="SPECWORD", category="SPECWORD", kind="SPECWORD", stage_now="SPECWORD", failure={"kind": "SPECWORD"}, status={"phase": "SPECWORD", "doing": "x"})]))
        for path, data in files.items():
            self.assertNotIn(b"SPECWORD", data, path)


class WithSpoilers(unittest.TestCase):
    def test_turning_them_on_shows_what_was_asked_for(self):
        files = rendered()
        run = files[f"spoilers/f/{page(1)}/index.html"].decode()
        for word in ("TITLEWORD", "PROMPTWORD", "REASONWORD", "TRANSCRIPTWORD", "1,000", "/world/spoilers/img/x/brass.jpg"):
            self.assertIn(word, run)
        self.assertIn("REASONWORD", files[f"spoilers/f/{page(3)}/index.html"].decode())
        now = files[f"spoilers/f/{page(2)}/index.html"].decode()
        self.assertIn("DOINGWORD", now)
        self.assertIn("Tokens so far", now)
        planned = files["spoilers/planned/index.html"].decode()
        for word in ("GOALWORD", "NODEWORD", "HOLDSWORD", "TITLEWORD"):
            self.assertIn(word, planned)
        self.assertIn("SPECWORD", files[f"spoilers/f/{page(9)}/index.html"].decode())
        top = files["spoilers/index.html"].decode()
        self.assertIn("REALNAME", top)
        self.assertIn("TEXTWORD", top)
        self.assertIn("Spoilers are showing", top)

    def test_a_builder_cant_put_anything_on_a_page_but_text(self):
        attack = '<script>alert(1)</script><img src=x onerror=alert(1)>"\'><a href="javascript:x">'
        files = rendered([released(title=attack, spec=attack, prompts=[{"text": attack}], attempts=[{"attempt": 1, "kind": "gate", "reason": attack}], summary=attack, shown=attack),
                          building(status={"phase": "planning", "doing": attack, "at": NOW}), failed()], world={**WORLD, "name": attack, "text": attack, "safe_name": attack, "tease": attack, "accent": "red;}</style><script>"})
        for path, data in files.items():
            self.assertNotIn(b"<script", data, path)
            self.assertNotIn(b"<img src=x", data, path)
            self.assertNotIn(b'href="javascript:', data, path)

    def test_something_shaped_like_a_secret_comes_out_here_too(self):
        run = rendered([released(prompts=[{"text": "sk-abcdefghijklmnopqrstuvwx and 10.1.2.3"}])])[f"spoilers/f/{page(1)}/index.html"]
        self.assertNotIn(b"sk-abcdefghijklmnopqrstuvwx", run)
        self.assertNotIn(b"10.1.2.3", run)


class BeforeTheTheme(unittest.TestCase):
    def test_neither_tree_shows_anything(self):
        for the_board in ({"chosen": False, "theme": "THEMEWORD"}, {}, None):
            files = world_page.render(the_board, WORLD, [], {}, {}, NOW)
            self.assertEqual(set(files), {"index.html", "spoilers/index.html"})
            for data in files.values():
                self.assertIn(b"Nothing here yet", data)
                self.assertNotIn(b"REALNAME", data)
                self.assertNotIn(b"toggle", data.split(b"</style>")[1])


class Reading(unittest.TestCase):
    def test_a_broken_record_is_left_out_or_cleaned_up(self):
        self.assertIsNone(world_page.normal("nonsense", NOW))
        self.assertIsNone(world_page.normal({"page": "../../etc"}, NOW))
        view = world_page.normal({"page": page(1), "tokens": [1], "phases": "x", "attempts": "x", "prompts": 3, "seconds": "lots", "screenshots": 7, "started_at": float("inf")}, NOW)
        self.assertEqual((view["tokens"], view["steps"], view["attempts"], view["prompts"], view["seconds"], view["screenshots"], view["started_at"]), ({}, {}, [], [], None, [], None))

    def test_a_run_that_stopped_counts_only_the_time_it_was_going(self):
        self.assertEqual(world_page.normal(building(), NOW)["seconds"], 130.0)


class Files(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = pathlib.Path(self.folder.name)
        self.into = self.root / "in"
        self.out = self.root / "out"
        for name in ("ledger/runs", "reports", "trees"):
            (self.into / name).mkdir(parents=True)
        self.out.mkdir()
        self.secret = self.root / "secret.png"
        self.secret.write_bytes(png())

    def write_board(self, **extra):
        (self.into / "ledger" / "board.json").write_text(json.dumps({"at": NOW, "chosen": True, "building": [], "queue": [], "roadmap": {"nodes": []}, **extra}), encoding="utf-8")

    def write_run(self, record):
        (self.into / "ledger" / "runs" / f"{record['run']}.json").write_text(json.dumps(record), encoding="utf-8")

    def test_a_link_left_by_a_builder_isnt_followed(self):
        assets = self.into / "trees" / "brass_kiln" / "mods/genesis/features/brass_kiln/assets/textures"
        assets.mkdir(parents=True)
        (assets / "good.png").write_bytes(png())
        os.symlink(self.secret, assets / "stolen.png")
        (assets / "fake.png").write_bytes(b"not a picture at all")
        self.write_board()
        self.write_run(released())
        world_page.Pages(self.into, self.out).one_pass(NOW)
        made = list(self.out.rglob("*.png"))
        self.assertEqual(len(made), 1, made)

    def test_pictures_come_out_with_only_their_pixels(self):
        from PIL import PngImagePlugin
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "PRIVATEWORD")
        source = self.into / "reports" / "shot.png"
        Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(source, "PNG", pnginfo=info)
        self.assertIn(b"PRIVATEWORD", source.read_bytes())
        self.assertNotIn(b"PRIVATEWORD", world_page._picture_bytes(source, False))
        self.assertNotIn(b"PRIVATEWORD", world_page._picture_bytes(source, True))

    def test_the_mosaic_is_only_a_few_blocks(self):
        source = self.into / "ledger" / "banner.png"
        source.write_bytes(png((1920, 480)))
        with Image.open(io.BytesIO(world_page.mosaic_bytes(source))) as image:
            self.assertEqual(image.size, world_page.MOSAIC_SIZE)

    def test_a_whole_pass_writes_both_trees_and_takes_down_what_has_gone(self):
        self.write_board()
        self.write_run(released())
        (self.into / "ledger" / "runs" / "brass_kiln-1001.transcript.jsonl").write_text(
            json.dumps({"kind": "say", "role": "builder", "text": "TRANSCRIPTWORD"}) + "\n" + "{not json\n" + json.dumps({"kind": "got", "role": "builder", "text": "<script>"}) + "\n", encoding="utf-8")
        pages = world_page.Pages(self.into, self.out)
        pages.one_pass(NOW)
        self.assertTrue((self.out / "index.html").exists())
        self.assertTrue((self.out / f"spoilers/f/{page(1)}/transcript/1/index.html").exists())
        transcript = (self.out / f"spoilers/f/{page(1)}/transcript/1/index.html").read_bytes()
        self.assertIn(b"TRANSCRIPTWORD", transcript)
        self.assertNotIn(b"<script>", transcript)
        self.assertIn(b"TRANSCRIPTWORD", (self.out / f"spoilers/f/{page(1)}/index.html").read_bytes())
        self.assertNotIn(b"TRANSCRIPTWORD", (self.out / f"f/{page(1)}/index.html").read_bytes())
        self.write_board(chosen=False)
        pages.one_pass(NOW)
        self.assertEqual(sorted(path.relative_to(self.out).as_posix() for path in self.out.rglob("*") if path.is_file()), ["index.html", "spoilers/index.html"])

    def test_a_long_transcript_goes_over_several_pages(self):
        self.write_board()
        self.write_run(released())
        path = self.into / "ledger" / "runs" / "brass_kiln-1001.transcript.jsonl"
        path.write_text("".join(json.dumps({"kind": "say", "role": "builder", "text": f"line {number}"}) + "\n" for number in range(world_page.TRANSCRIPT_PAGE + 5)), encoding="utf-8")
        pages = world_page.Pages(self.into, self.out)
        pages.one_pass(NOW)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": "say", "role": "builder", "text": "the very latest"}) + "\n")
        pages.one_pass(NOW)
        self.assertIn(b"line 0", (self.out / f"spoilers/f/{page(1)}/transcript/1/index.html").read_bytes())
        self.assertIn(b"the very latest", (self.out / f"spoilers/f/{page(1)}/transcript/2/index.html").read_bytes())
        self.assertIn(b"the very latest", (self.out / f"spoilers/f/{page(1)}/index.html").read_bytes())

    def test_the_first_pass_only_takes_so_many_pictures_at_a_time(self):
        folder = self.into / "reports" / "brass_kiln-1"
        folder.mkdir()
        for number in range(world_page.MOST_SHOTS):
            (folder / f"{number:04}_scene.png").write_bytes(png())
        for number in range(world_page.PICTURES_PER_PASS):
            self.write_run(released(number + 10, old=True, screenshots=[]))
        os.utime(folder, (NOW - 1000, NOW - 1000))
        self.write_board()
        pages = world_page.Pages(self.into, self.out)
        pages.one_pass(NOW)
        self.assertEqual(len(list(self.out.rglob("*.jpg"))), world_page.PICTURES_PER_PASS)


if __name__ == "__main__":
    unittest.main()
