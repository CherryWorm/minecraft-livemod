"""One feature changing another, on a real git repository, with a stand-in for the broker that sees exactly what the real one would be given."""
import asyncio
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from PIL import Image

from broker import bundles
from broker.gates import GateFailed, progression, static
from broker.tests.test_batched_release import Base, git
from orchestrator import llm, others, worker_hub, workshop, world_index

PLACE = "mods/genesis/features"
REASON = "Its bronze recipe was on the wrong machine, so nobody ever found it"


def manifest_of(name, **fields):
    return {"id": name, "node": "e_one", **fields}


class Repo(Base):
    def setUp(self):
        super().setUp()
        self.seen = []
        self.prompts = []
        self.shop.governor.why_not_build.return_value = None
        self.shop.web_research.server.return_value = None
        self.out("kiln", {"bronze": {"machine": "forge"}, "iron": {"machine": "kiln"}})
        patcher = mock.patch.object(llm, "ask", self.review)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def broker(self, kind, commit, release_id=None, why="", **fields):
        await asyncio.sleep(0)
        self.seen.append({"kind": kind, "commit": commit, "kiln": git("show", f"{commit}:{PLACE}/kiln/feature.json", cwd=self.repo)})
        names = [path.rsplit("/", 1)[-1] for path in git("ls-tree", "--name-only", commit, f"{PLACE}/", cwd=self.repo).splitlines()]
        self.releases.append({"kind": kind, "features": names, "id": release_id, "why": why})
        wrong = self.bad.intersection(names)
        if wrong:
            return {"result": "blocked", "gate": "shadow", "reason": f"{sorted(wrong)} broke it"}
        return {"result": {"lint": "passed_lint", "check": "passed_gates", "gates": "passed_gates"}.get(kind, "released"), "screenshots": [], "tier": "T2", "stages": {}}

    async def review(self, governor, role, prompt, **options):
        self.prompts.append(prompt)
        return llm.Result("", {"approve": True, "serious": False, "problems": []}, "s", 0.0, False, "end_turn", 0.0)

    def write(self, root, name, recipes=None, **fields):
        folder = root / PLACE / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "feature.json").write_text(json.dumps(manifest_of(name, recipes=recipes or {}, **fields), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return folder

    def out(self, name, recipes=None, **fields):
        self.write(self.repo, name, recipes, **fields)
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", f"{name} is out", cwd=self.repo)

    def builder(self, name, **fields):
        """A builder's tree, with its own feature in it."""
        tree = self.shop._prepare_tree(name)
        self.write(tree, name, **fields)
        return tree

    def change(self, tree, feature, **recipes):
        """Edits another feature in place, the way a builder would, a line or two at a time."""
        path = tree / PLACE / feature / "feature.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["recipes"].update(recipes)
        path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def on_main(self, feature):
        return json.loads(git("show", f"main:{PLACE}/{feature}/feature.json", cwd=self.repo))

    def lint(self, name, tree):
        return asyncio.create_task(workshop.checked_against_main("lint", f"{name}: work in progress", tree, name, "e_one"))

    def builds(self, name, *steps):
        """Stands in for a builder, doing one of these for each attempt and keeping what it's told."""
        told = []
        steps = iter(steps)

        async def attempt(feature_id, tree, prompt, *rest):
            told.append(prompt)
            step = next(steps)
            if step:
                step(tree)
            return llm.Result("", None, "s", 0.0, False, "end_turn", 0.0)

        return told, mock.patch.object(self.shop, "_attempt", attempt), mock.patch.object(self.shop, "_log_timing")


class WithinALine(Repo):
    async def test_a_change_across_two_features_goes_out_whole(self):
        def work(tree):
            self.write(tree, "fix_it", changes_features={"kiln": REASON})
            self.change(tree, "kiln", bronze={"machine": "kiln"})

        told, attempt, timing = self.builds("fix_it", work)
        with attempt, timing:
            shipped = await self.shop.build("fix_it", "Move the bronze recipe.", "e_one", "early")
        self.assertTrue(shipped)
        self.assertEqual(self.on_main("kiln")["recipes"], {"bronze": {"machine": "kiln"}, "iron": {"machine": "kiln"}})
        self.assertIn("fix_it", git("ls-tree", "--name-only", "main", f"{PLACE}/", cwd=self.repo))
        # The gates and the release were both given the whole of it, and the reviewer was shown why and what.
        self.assertEqual([entry["kind"] for entry in self.seen], ["gates", "release"])
        for seen in self.seen:
            self.assertEqual(json.loads(seen["kiln"])["recipes"]["bronze"], {"machine": "kiln"})
        self.assertIn(REASON, self.prompts[0])
        self.assertIn('-   "machine": "forge"', self.prompts[0])
        self.assertIn('+   "machine": "kiln"', self.prompts[0])

    async def test_the_reviewer_is_told_nothing_when_it_stays_in_its_folder(self):
        told, attempt, timing = self.builds("fix_it", None)
        self.builder("fix_it")
        with attempt, timing:
            await self.shop.build("fix_it", "Own thing.", "e_one", "early")
        self.assertNotIn("changes_to_other_features", self.prompts[0])

    async def test_changing_one_without_saying_so_is_refused_and_nothing_is_lost(self):
        tree = self.builder("fix_it")
        self.change(tree, "kiln", bronze={"machine": "kiln"})
        answer = await self.lint("fix_it", tree)
        self.assertEqual((answer["result"], answer["gate"]), ("blocked", "scope"))
        self.assertIn("kiln", answer["reason"])
        self.assertIn("changes_features", answer["reason"])
        self.assertEqual(json.loads((tree / PLACE / "kiln/feature.json").read_text(encoding="utf-8"))["recipes"]["bronze"], {"machine": "kiln"})
        self.assertEqual(self.seen, [])

    async def test_saying_so_lets_it_through(self):
        tree = self.builder("fix_it")
        self.change(tree, "kiln", bronze={"machine": "kiln"})
        await self.lint("fix_it", tree)
        self.write(tree, "fix_it", changes_features={"kiln": REASON})
        answer = await self.lint("fix_it", tree)
        self.assertEqual(answer["result"], "passed_lint")
        self.assertIn('"machine": "kiln"', self.seen[-1]["kiln"].split('"iron"')[0])

    async def test_putting_it_back_lets_it_through_with_nothing_changed(self):
        tree = self.builder("fix_it")
        self.change(tree, "kiln", bronze={"machine": "kiln"})
        await self.lint("fix_it", tree)
        self.change(tree, "kiln", bronze={"machine": "forge"})
        self.assertEqual((await self.lint("fix_it", tree))["result"], "passed_lint")
        self.assertEqual(self.seen[-1]["kiln"], json.dumps(self.on_main("kiln"), indent=1, sort_keys=True))

    async def test_changing_its_mind_after_a_commit_undoes_it(self):
        tree = self.builder("fix_it", changes_features={"kiln": REASON})
        self.change(tree, "kiln", bronze={"machine": "kiln"})
        self.assertEqual((await self.lint("fix_it", tree))["result"], "passed_lint")
        self.write(tree, "fix_it")
        self.change(tree, "kiln", bronze={"machine": "forge"})
        self.assertEqual((await self.lint("fix_it", tree))["result"], "passed_lint")
        await self.shop._release("fix_it", tree, "e_one")
        self.assertEqual(self.on_main("kiln")["recipes"]["bronze"], {"machine": "forge"})

    async def test_a_new_folder_cant_be_declared_into_being(self):
        tree = self.builder("fix_it", changes_features={"brand_new": REASON})
        self.write(tree, "brand_new")
        answer = await self.lint("fix_it", tree)
        self.assertEqual(answer["gate"], "scope")
        self.assertIn("anything new goes in your own folder", answer["reason"])

    async def test_a_name_from_a_model_cant_reach_out_of_the_features(self):
        tree = self.builder("fix_it", changes_features={"../../../bible": REASON, "..": REASON, "kiln/../../..": REASON})
        (tree / "bible").mkdir(exist_ok=True)
        (tree / "bible/theme.md").write_text("Something else altogether.\n", encoding="utf-8")
        (tree / "stray.txt").write_text("Left behind.\n", encoding="utf-8")
        self.assertEqual((await self.lint("fix_it", tree))["result"], "passed_lint")
        changed = git("diff", "--name-only", "main", "HEAD", cwd=tree).splitlines()
        self.assertEqual(changed, [f"{PLACE}/fix_it/feature.json"])

    async def test_anything_else_it_left_lying_around_still_goes_nowhere(self):
        (self.repo / "bible").mkdir()
        (self.repo / "bible/theme.md").write_text("The theme.\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "A theme", cwd=self.repo)
        tree = self.builder("fix_it")
        (tree / "bible/theme.md").write_text("Another theme.\n", encoding="utf-8")
        self.assertEqual((await self.lint("fix_it", tree))["result"], "passed_lint")
        self.assertEqual((tree / "bible/theme.md").read_text(encoding="utf-8"), "The theme.\n")

    async def test_it_can_change_several(self):
        self.out("mill", {"flour": {"machine": "mill"}})
        tree = self.builder("fix_it", changes_features={"kiln": REASON, "mill": REASON})
        self.change(tree, "kiln", bronze={"machine": "kiln"})
        self.change(tree, "mill", flour={"machine": "quern"})
        await self.shop._release("fix_it", tree, "e_one")
        self.assertEqual(self.on_main("kiln")["recipes"]["bronze"], {"machine": "kiln"})
        self.assertEqual(self.on_main("mill")["recipes"]["flour"], {"machine": "quern"})

    async def test_a_broken_manifest_throws_nothing_away(self):
        tree = self.builder("fix_it", changes_features={"kiln": REASON})
        self.change(tree, "kiln", bronze={"machine": "kiln"})
        (tree / PLACE / "fix_it/feature.json").write_text("{ this isn't JSON", encoding="utf-8")
        await self.lint("fix_it", tree)
        self.assertIn('"machine": "kiln"', (tree / PLACE / "kiln/feature.json").read_text(encoding="utf-8").split('"iron"')[0])
        self.write(tree, "fix_it", changes_features={"kiln": REASON})
        self.assertEqual((await self.lint("fix_it", tree))["result"], "passed_lint")
        self.assertIn('"machine": "kiln"', self.seen[-1]["kiln"].split('"iron"')[0])


class TwoAtOnce(Repo):
    def two_on_one_line(self):
        first = self.builder("first", changes_features={"kiln": REASON})
        second = self.builder("second", changes_features={"kiln": REASON})
        self.change(first, "kiln", bronze={"machine": "first"})
        self.change(second, "kiln", bronze={"machine": "second"})
        return first, second

    async def test_different_lines_just_come_together(self):
        first = self.builder("first", changes_features={"kiln": REASON})
        second = self.builder("second", changes_features={"kiln": REASON})
        self.change(first, "kiln", bronze={"machine": "first"})
        self.change(second, "kiln", iron={"machine": "second"})
        answers = await asyncio.gather(self.shop._release("first", first, "e_one"), self.shop._release("second", second, "e_one"))
        self.assertEqual([answer["result"] for answer in answers], ["released", "released"])
        self.assertEqual(self.on_main("kiln")["recipes"], {"bronze": {"machine": "first"}, "iron": {"machine": "second"}})

    async def test_the_same_line_is_refused_and_shows_both_versions(self):
        first, second = self.two_on_one_line()
        await self.shop._release("first", first, "e_one")
        answer = await self.lint("second", second)
        self.assertEqual((answer["result"], answer["gate"]), ("blocked", "merge"))
        self.assertIn(f"{PLACE}/kiln/feature.json", answer["reason"])
        text = (second / PLACE / "kiln/feature.json").read_text(encoding="utf-8")
        for marker in ('"machine": "first"', '"machine": "second"', "<<<<<<< ", ">>>>>>> "):
            self.assertIn(marker, text)
        # Nothing of the second has reached anything, and what went out is still out.
        self.assertEqual(self.on_main("kiln")["recipes"]["bronze"], {"machine": "first"})
        self.assertEqual(len(self.seen), 1)

    async def test_it_goes_nowhere_until_its_settled_and_then_keeps_both(self):
        first, second = self.two_on_one_line()
        await self.shop._release("first", first, "e_one")
        await self.lint("second", second)
        again = await self.lint("second", second)
        self.assertEqual(again["gate"], "merge")
        self.assertIn("marker lines", again["reason"])
        released = await self.shop._release("second", second, "e_one")
        self.assertEqual(released["gate"], "merge")
        self.write(second, "kiln", {"bronze": {"machine": "first", "also": "second"}, "iron": {"machine": "kiln"}})
        self.assertEqual((await self.lint("second", second))["result"], "passed_lint")
        self.assertEqual((await self.shop._release("second", second, "e_one"))["result"], "released")
        self.assertEqual(self.on_main("kiln")["recipes"]["bronze"], {"machine": "first", "also": "second"})
        self.assertNotIn("<<<<<<<", json.dumps(self.on_main("kiln")))

    async def test_going_out_together_the_second_waits_and_hears_what_really_happened(self):
        first, second = self.two_on_one_line()
        answers = await asyncio.gather(self.shop._release("first", first, "e_one"), self.shop._release("second", second, "e_one"))
        self.assertEqual(answers[0]["result"], "released")
        self.assertEqual(answers[1]["gate"], "merge")
        self.assertIn(f"{PLACE}/kiln/feature.json", answers[1]["reason"])
        self.assertIn("<<<<<<<", (second / PLACE / "kiln/feature.json").read_text(encoding="utf-8"))
        self.assertEqual(self.on_main("kiln")["recipes"]["bronze"], {"machine": "first"})

    async def test_if_the_one_ahead_doesnt_go_out_after_all_the_second_is_fine(self):
        first, second = self.two_on_one_line()
        self.bad = {"first"}
        answers = await asyncio.gather(self.shop._release("first", first, "e_one"), self.shop._release("second", second, "e_one"))
        self.assertEqual(answers[0]["gate"], "shadow")
        self.assertEqual(answers[1]["result"], "released")
        self.assertEqual(self.on_main("kiln")["recipes"]["bronze"], {"machine": "second"})

    async def test_the_others_in_the_release_arent_held_up(self):
        first, second = self.two_on_one_line()
        third = self.builder("third")
        answers = await asyncio.gather(self.shop._release("first", first, "e_one"), self.shop._release("second", second, "e_one"), self.shop._release("third", third, "e_one"))
        self.assertEqual([answer.get("result") for answer in answers], ["released", "blocked", "released"])
        self.assertEqual(self.releases[0]["features"], ["first", "kiln", "third"])

    async def test_a_builder_hears_when_its_own_feature_was_changed_under_it(self):
        own = self.shop._prepare_tree("kiln")
        reach = self.builder("fix_it", changes_features={"kiln": REASON})
        self.change(reach, "kiln", bronze={"machine": "reached"})
        await self.shop._release("fix_it", reach, "e_one")
        self.change(own, "kiln", bronze={"machine": "own"})
        answer = await self.lint("kiln", own)
        self.assertEqual(answer["gate"], "merge")
        self.assertEqual(self.on_main("kiln")["recipes"]["bronze"], {"machine": "reached"})

    async def test_art_cant_show_both_so_whats_out_stays_and_yours_can_be_found(self):
        def paint(tree, colour):
            folder = tree / PLACE / "kiln/assets/textures"
            folder.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (16, 16), colour).save(folder / "kiln.png")

        paint(self.repo, "black")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "Art", cwd=self.repo)
        first = self.builder("first", changes_features={"kiln": REASON})
        second = self.builder("second", changes_features={"kiln": REASON})
        paint(first, "red")
        paint(second, "blue")
        await self.shop._release("first", first, "e_one")
        answer = await self.lint("second", second)
        self.assertEqual(answer["gate"], "merge")
        self.assertIn("kiln.png", answer["reason"])
        self.assertIn("git show", answer["reason"])
        with Image.open(second / PLACE / "kiln/assets/textures/kiln.png") as image:
            self.assertEqual(image.convert("RGB").getpixel((0, 0)), (255, 0, 0))
        commit = answer["reason"].split("git show ")[1].split(":")[0]
        self.assertTrue(git("cat-file", "-e", f"{commit}:{PLACE}/kiln/assets/textures/kiln.png", cwd=second) == "")
        # Nothing's left to settle, so it can go ahead.
        self.assertEqual((await self.lint("second", second))["result"], "passed_lint")

    async def test_something_changed_here_and_removed_there(self):
        (self.repo / PLACE / "kiln/notes.txt").write_text("One.\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "Notes", cwd=self.repo)
        tree = self.builder("second", changes_features={"kiln": REASON})
        (tree / PLACE / "kiln/notes.txt").write_text("Two.\n", encoding="utf-8")
        git("rm", "-q", f"{PLACE}/kiln/notes.txt", cwd=self.repo)
        git("commit", "-q", "-m", "No notes", cwd=self.repo)
        answer = await self.lint("second", tree)
        self.assertEqual(answer["gate"], "merge")
        self.assertFalse((tree / PLACE / "kiln/notes.txt").exists())

    async def test_a_conflict_doesnt_use_up_a_try(self):
        tries = iter([*[{"result": "blocked", "gate": "merge", "reason": "Lines."}] * 3, {"result": "passed_gates", "screenshots": []}])
        told, attempt, timing = self.builds("demo", None, None, None, None)
        with attempt, timing, mock.patch.object(self.shop, "_review", mock.AsyncMock(return_value={"approve": True})), \
                mock.patch.object(workshop, "checked_against_main", mock.AsyncMock(side_effect=lambda *args, **fields: next(tries))), \
                mock.patch.object(self.shop, "_release", mock.AsyncMock(return_value={"result": "released", "tier": "T2", "stages": {}})):
            self.assertTrue(await self.shop.build("demo", "A spec.", "e_one", "early", small=True))
        self.assertEqual(len(told), 4)

    async def test_but_it_cant_go_on_forever(self):
        told, attempt, timing = self.builds("demo", *[None] * 20)
        with attempt, timing, mock.patch.object(workshop, "checked_against_main", mock.AsyncMock(return_value={"result": "blocked", "gate": "merge", "reason": "Lines."})):
            self.assertFalse(await self.shop.build("demo", "A spec.", "e_one", "early", small=True, fix="bug_1"))
        self.assertEqual(len(told), workshop.FIX_LIMITS[2] + workshop.MOST_CONFLICTS)

    async def test_the_whole_way_with_a_conflict_on_the_way(self):
        def first_go(tree):
            self.write(tree, "fix_it", changes_features={"kiln": REASON})
            self.change(tree, "kiln", bronze={"machine": "mine"})
            # Someone else's change goes out while this one's being built.
            self.out("kiln", {"bronze": {"machine": "theirs"}, "iron": {"machine": "kiln"}})

        def second_go(tree):
            path = tree / PLACE / "kiln/feature.json"
            self.assertIn("<<<<<<<", path.read_text(encoding="utf-8"))
            self.write(tree, "kiln", {"bronze": {"machine": "theirs", "also": "mine"}, "iron": {"machine": "kiln"}})

        told, attempt, timing = self.builds("fix_it", first_go, second_go)
        with attempt, timing:
            self.assertTrue(await self.shop.build("fix_it", "Move the bronze recipe.", "e_one", "early", small=True))
        self.assertIn("at merge", told[1])
        self.assertIn(f"{PLACE}/kiln/feature.json", told[1])
        self.assertEqual(self.on_main("kiln")["recipes"]["bronze"], {"machine": "theirs", "also": "mine"})

    async def test_a_balance_change_that_clashes_says_so(self):
        tree = workshop.TREES / "tune-test"
        workshop.TREES.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-q", "-b", "tune-test", str(tree), "main", cwd=self.repo)
        (tree / PLACE / "kiln/feature.json").write_text("{}\n", encoding="utf-8")
        self.out("kiln", {"bronze": {"machine": "moved"}})
        with self.assertRaises(workshop.Refused) as caught:
            workshop.ready_commit("A tune", tree)
        self.assertEqual(caught.exception.gate, "merge")
        self.assertFalse((tree / ".git").is_dir() and (tree / "MERGE_HEAD").exists())
        self.assertEqual(git("status", "--porcelain", cwd=tree), "")


class AnotherMachine(Repo):
    def job(self, name, tree):
        return worker_hub.Job("job1", name, tree, {}, mock.Mock())

    def machine_commit(self, tree, feature_manifest, touched):
        """A commit like one a machine would upload, with the changes it made, and the server's tree put back as it was."""
        for name, recipes in touched.items():
            self.write(tree, name, recipes)
        (tree / PLACE / "fix_it/feature.json").write_text(feature_manifest, encoding="utf-8")
        git("add", "-A", cwd=tree)
        git("commit", "-q", "-m", "On the machine", cwd=tree)
        commit = git("rev-parse", "HEAD", cwd=tree)
        git("reset", "-q", "--hard", "HEAD~1", cwd=tree)
        git("update-ref", "refs/workers/job1", commit, cwd=self.repo)
        return commit

    def hub(self):
        return worker_hub.WorkerHub(self.repo, mock.AsyncMock(), mock.Mock(), lambda: ())

    def on_server(self):
        self.out("mill", {"flour": {"machine": "mill"}})
        tree = self.builder("fix_it")
        workshop.ready_commit("First", tree, "fix_it", "e_one")
        return tree

    def recipes(self, tree, name):
        return json.loads((tree / PLACE / name / "feature.json").read_text(encoding="utf-8"))["recipes"]

    async def test_it_brings_what_it_declared_and_nothing_else(self):
        tree = self.on_server()
        declared = json.dumps(manifest_of("fix_it", recipes={}, changes_features={"kiln": REASON}), indent=1)
        commit = self.machine_commit(tree, declared, {"kiln": {"bronze": {"machine": "kiln"}}, "mill": {"flour": {"machine": "quern"}}})
        self.assertIsNone(self.hub()._take_feature(self.job("fix_it", tree), commit))
        self.assertEqual(self.recipes(tree, "kiln"), {"bronze": {"machine": "kiln"}})
        self.assertEqual(self.recipes(tree, "mill"), {"flour": {"machine": "mill"}})
        self.assertEqual((await self.lint("fix_it", tree))["result"], "passed_lint")

    async def test_it_still_reads_a_manifest_thats_waiting_on_a_merge(self):
        tree = self.on_server()
        conflicted = ('{\n<<<<<<< HEAD\n "changes_features": {"kiln": "' + REASON + '"},\n=======\n "changes_features": {"mill": "theirs"},\n>>>>>>> main\n "id": "fix_it"\n}\n')
        commit = self.machine_commit(tree, conflicted, {"kiln": {"bronze": {"machine": "kiln"}}, "mill": {"flour": {"machine": "quern"}}})
        self.hub()._take_feature(self.job("fix_it", tree), commit)
        self.assertEqual(self.recipes(tree, "kiln"), {"bronze": {"machine": "kiln"}})
        self.assertEqual(self.recipes(tree, "mill"), {"flour": {"machine": "mill"}})

    async def test_a_name_from_a_model_cant_reach_out_of_the_features(self):
        tree = self.on_server()
        declared = json.dumps(manifest_of("fix_it", changes_features={"../../..": REASON}))
        commit = self.machine_commit(tree, declared, {})
        self.assertIsNone(self.hub()._take_feature(self.job("fix_it", tree), commit))
        self.assertTrue((tree / ".git").exists())


class Additions(unittest.TestCase):
    def adding(self, target, **places):
        return {"owner": manifest_of("owner", **target), "adder": manifest_of("adder", adds_to={"owner": {"why": REASON, **{key.replace("__", "."): value for key, value in places.items()}}})}

    def test_a_route_goes_on_the_entrys_list_and_names_the_adders_own(self):
        manifests = self.adding({"knowledge": {"gems": {"routes": [{"type": "obtain", "id": "$item:dust"}]}}},
                                knowledge__gems__routes=[{"type": "read", "id": "$item:tablet"}, {"type": "kill", "id": "$mob:owner/crab"}])
        self.assertEqual(others.apply_additions(manifests), [])
        self.assertEqual(manifests["owner"]["knowledge"]["gems"]["routes"], [{"type": "obtain", "id": "$item:dust"}, {"type": "read", "id": "$item:adder/tablet"}, {"type": "kill", "id": "$mob:owner/crab"}])

    def test_a_page_grows_a_paragraph(self):
        manifests = self.adding({"knowledge": {"gems": {"text": "One."}}}, knowledge__gems__text="Two, with $item:dust.")
        self.assertEqual(others.apply_additions(manifests), [])
        self.assertEqual(manifests["owner"]["knowledge"]["gems"]["text"], "One.\nTwo, with $item:adder/dust.")

    def test_a_place_in_a_list_can_be_named(self):
        manifests = self.adding({"ruins": {"shrine": {"loot": {"pools": [{"entries": [{"name": "a"}]}]}}}}, ruins__shrine__loot__pools__0__entries=[{"name": "$item:b"}])
        self.assertEqual(others.apply_additions(manifests), [])
        self.assertEqual(manifests["owner"]["ruins"]["shrine"]["loot"]["pools"][0]["entries"], [{"name": "a"}, {"name": "$item:adder/b"}])

    def test_a_list_that_isnt_there_yet_is_started(self):
        manifests = self.adding({"blocks": {"cable": {}}}, blocks__cable__connects=["$block:battery"])
        self.assertEqual(others.apply_additions(manifests), [])
        self.assertEqual(manifests["owner"]["blocks"]["cable"]["connects"], ["$block:adder/battery"])

    def test_it_can_give_the_reason_for_changing_what_players_have(self):
        manifests = self.adding({"blocks": {"cable": {}}}, changes_reached={"cable": REASON})
        self.assertEqual(others.apply_additions(manifests), [])
        self.assertEqual(manifests["owner"]["changes_reached"], {"cable": REASON})

    def test_it_can_only_ever_add(self):
        for target, places, words in (
                ({"knowledge": {"gems": {"title": "Name"}}}, {"knowledge__gems__title": "More"}, "only a list"),
                ({"mobs": {"crab": {"mind": {"teaches": {"gems": 1}}}}}, {"mobs__crab__mind__teaches": {"gems": 9}}, "can't replace"),
                ({"blocks": {"cable": {"hardness": 1}}}, {"blocks__cable__hardness": 5}, "only a list"),
                ({"blocks": {"cable": {"connects": []}}}, {"blocks__cable__connects": "$block:battery"}, "only a list")):
            manifests = self.adding(target, **places)
            before = json.loads(json.dumps(manifests["owner"]))
            problems = others.apply_additions(manifests)
            self.assertEqual(len(problems), 1, target)
            self.assertIn(words, problems[0])
            self.assertEqual(manifests["owner"], before)

    def test_it_has_to_be_somewhere_that_can_be_added_to_and_is_there(self):
        for places, words in (({"node": "e_two"}, "can only add"), ({"automation": []}, "can only add"), ({"knowledge": {"new": {}}}, "can only add"),
                              ({"knowledge__missing__routes": []}, "no missing"), ({"ruins__shrine__loot__pools__9__entries": []}, "no shrine")):
            self.assertTrue(others.apply_additions(self.adding({"knowledge": {}}, **places)), places)

    def test_it_has_to_be_a_feature_thats_out_and_not_itself(self):
        self.assertIn("isn't a feature that's out", others.apply_additions({"a_one": manifest_of("a_one", adds_to={"nobody": {}})})[0])
        self.assertIn("is itself", others.apply_additions({"a_one": manifest_of("a_one", adds_to={"a_one": {}})})[0])

    def test_nothing_is_needed_of_a_feature_that_adds_nothing(self):
        self.assertEqual(others.apply_additions({"a_one": manifest_of("a_one")}), [])


class Compiled(unittest.TestCase):
    """All the way through the bundle, as the gates and the game see it."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.features = self.root / "features"

    def feature(self, name, **fields):
        folder = self.features / name
        (folder / "assets/textures").mkdir(parents=True)
        for item in fields.get("items", {}):
            Image.new("RGB", (16, 16), "gray").save(folder / "assets/textures" / f"{item}.png")
        (folder / "feature.json").write_text(json.dumps(manifest_of(name, **fields)), encoding="utf-8")

    def compile(self):
        features = bundles.load_features(self.features)
        pool = {"families": {}, "item_count": 100, "mobs": {"monster": 10, "creature": 10}}
        ledger = bundles.assign_slots(features, bundles.empty_ledger(), pool)
        bundles.render(features, ledger, self.root / "out", 61)
        return features, json.loads((self.root / "out/config/knowledge.json").read_text(encoding="utf-8"))

    def test_what_one_adds_is_in_the_others_entry_when_the_game_reads_it(self):
        self.feature("alloys", items={"dust": {"display": "Dust"}}, knowledge={"alloying": {"title": "Alloying", "text": "One.", "routes": [{"type": "obtain", "id": "$item:dust"}]},
                                                                               "basics": {"title": "Basics", "text": "Hm.", "routes": [{"type": "obtain", "id": "$item:dust"}]}})
        self.feature("ruins", items={"tablet": {"display": "Tablet"}}, knowledge={"reading": {"title": "Reading", "text": "Hm.", "routes": [{"type": "read", "id": "$item:tablet"}]}},
                     adds_to={"alloys": {"why": REASON, "knowledge.alloying.routes": [{"type": "read", "id": "$item:tablet", "requires": ["basics", "ruins/reading"]}], "knowledge.alloying.text": "Two."}})
        features, plan = self.compile()
        entry = plan["entries"]["alloys/alloying"]
        self.assertEqual(len(entry["routes"]), 2)
        tablet = plan["entries"]["ruins/reading"]["routes"][0]["id"]
        self.assertEqual(entry["routes"][1], {"type": "read", "id": tablet, "requires": ["alloys/basics", "ruins/reading"]})
        self.assertEqual(entry["text"], "One.\nTwo.")
        static.check_knowledge(features)
        static.check_changes_to_others(features)

    def test_a_problem_with_it_stops_the_release_in_words_a_builder_can_use(self):
        self.feature("alloys")
        self.feature("ruins", adds_to={"alloys": {"why": REASON, "knowledge.nothing.routes": []}})
        with self.assertRaises(bundles.BundleError) as caught:
            self.compile()
        self.assertIn("no knowledge", str(caught.exception))

    def test_requires_has_to_be_a_list(self):
        self.feature("alloys", items={"dust": {"display": "Dust"}}, knowledge={"a": {"title": "A", "text": "A.", "routes": [{"type": "obtain", "id": "$item:dust", "requires": 3}]}})
        with self.assertRaises(bundles.BundleError) as caught:
            self.compile()
        self.assertIn("requires", str(caught.exception))

    def test_a_route_without_requires_is_as_it_was(self):
        self.feature("alloys", items={"dust": {"display": "Dust"}}, knowledge={"a": {"title": "A", "text": "A.", "routes": [{"type": "obtain", "id": "$item:dust"}]}})
        _, plan = self.compile()
        self.assertNotIn("requires", plan["entries"]["alloys/a"]["routes"][0])


class Checks(unittest.TestCase):
    def features(self, **manifests):
        return {name: {"manifest": manifest_of(name, **fields), "dir": pathlib.Path("/nowhere")} for name, fields in manifests.items()}

    def refused(self, check, features, words):
        with self.assertRaises(GateFailed) as caught:
            check(features)
        self.assertIn(words, caught.exception.message)

    def test_a_clear_reason_is_all_it_takes(self):
        static.check_changes_to_others(self.features(a_one={"changes_features": {"b_two": REASON}}, b_two={}))

    def test_it_has_to_say_why(self):
        self.refused(static.check_changes_to_others, self.features(a_one={"changes_features": {"b_two": "fix"}}, b_two={}), "clear reason")
        self.refused(static.check_changes_to_others, self.features(a_one={"adds_to": {"b_two": {"knowledge.x.routes": []}}}, b_two={}), "clear reason")

    def test_it_has_to_be_a_feature_thats_out(self):
        self.refused(static.check_changes_to_others, self.features(a_one={"changes_features": {"nobody": REASON}}), "isn't a feature that's out")

    def test_it_cant_list_itself(self):
        self.refused(static.check_changes_to_others, self.features(a_one={"changes_features": {"a_one": REASON}}), "lists itself")

    def test_it_has_to_be_the_right_shape(self):
        self.refused(static.check_changes_to_others, self.features(a_one={"changes_features": ["b_two"]}, b_two={}), "other features and why")

    def entry(self, *routes):
        return {"title": "T", "text": "T", "routes": [{"type": "obtain", "id": "minecraft:apple", **route} for route in routes]}

    def test_a_route_can_require_another_entry(self):
        static.check_knowledge(self.features(a_one={"knowledge": {"first": self.entry({}), "second": self.entry({"requires": ["first"]}), "third": self.entry({"requires": ["b_two/other", "second"]})}},
                                             b_two={"knowledge": {"other": self.entry({})}}))

    def test_what_it_requires_has_to_exist(self):
        self.refused(static.check_knowledge, self.features(a_one={"knowledge": {"second": self.entry({"requires": ["nothing"]})}}), "which no feature declares")

    def test_a_circle_is_refused_because_nobody_could_start_on_it(self):
        self.refused(static.check_knowledge, self.features(a_one={"knowledge": {"one": self.entry({"requires": ["two"]}), "two": self.entry({"requires": ["one"]})}}), "Nobody could ever learn a_one/one, a_one/two")
        self.refused(static.check_knowledge, self.features(a_one={"knowledge": {"one": self.entry({"requires": ["one"]})}}), "Nobody could ever learn")

    def test_a_circle_with_a_way_in_is_fine(self):
        static.check_knowledge(self.features(a_one={"knowledge": {"one": self.entry({"requires": ["two"]}, {}), "two": self.entry({"requires": ["one"]})}}))

    GRAPH = {"nodes": {"e_one": {"stage": "early", "requires": []}, "e_two": {"stage": "early", "requires": ["e_one"]}}}

    def graph_check(self, node, needs_node, *routes):
        features = {"a_one": {"manifest": {"id": "a_one", "node": node, "knowledge": {"entry": self.entry(*routes)}}},
                    "b_two": {"manifest": {"id": "b_two", "node": needs_node, "knowledge": {"need": self.entry({})}}}}
        return progression._check_knowledge_follows_graph(features, self.GRAPH)

    def test_a_requirement_from_earlier_in_the_graph_is_fine(self):
        self.assertEqual(self.graph_check("e_two", "e_one", {"requires": ["b_two/need"]}), [])

    def test_every_route_needing_something_later_is_a_lie(self):
        self.assertIn("doesn't come before", self.graph_check("e_one", "e_two", {"requires": ["b_two/need"]})[0])

    def test_a_late_second_way_of_learning_something_early_is_fine(self):
        self.assertEqual(self.graph_check("e_one", "e_two", {}, {"requires": ["b_two/need"]}), [])


class WhatBuildersSee(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.features = pathlib.Path(folder.name) / "mods/genesis/features"
        for name, fields in {"alloys": {"knowledge": {"alloying": {"title": "Alloying", "text": "One.", "routes": [{"type": "obtain", "id": "minecraft:copper_ingot"}]}}},
                             "ruins": {"adds_to": {"alloys": {"why": REASON, "knowledge.alloying.routes": [{"type": "kill", "id": "minecraft:husk", "requires": ["ruins/reading"]}]}}}}.items():
            (self.features / name).mkdir(parents=True)
            (self.features / name / "feature.json").write_text(json.dumps(manifest_of(name, **fields)), encoding="utf-8")

    def test_the_index_shows_the_entry_with_what_was_added_and_who_adds_what(self):
        text = world_index.build(self.features)
        self.assertIn("'kill after ruins/reading'", text)
        self.assertIn("- adds to alloys: knowledge.alloying.routes", text)

    def test_the_voices_that_help_players_hear_it_too(self):
        text = world_index.player_entry(self.features, "alloys")
        self.assertIn("kill husk, once reading has been learned", text)


class ThePrompts(unittest.TestCase):
    def test_builders_are_told_how_and_the_old_rule_has_gone(self):
        text = llm.prompt_text("builder")
        self.assertNotIn("Change nothing outside it", text)
        self.assertIn("changes_features", text)
        self.assertIn("adds_to", text)

    def test_the_quick_pass_knows_a_small_job_can_span_features(self):
        self.assertIn("a small fix that spans two is still a small fix", llm.prompt_text("director_quick"))

    def test_the_reviewer_knows_to_judge_it(self):
        self.assertIn("changes_to_other_features", llm.prompt_text("reviewer"))

    def test_a_small_job_and_a_fix_are_told_they_can(self):
        for note in (workshop.SMALL_NOTE, workshop.FIX_NOTE):
            self.assertIn("changes_features", note)


if __name__ == "__main__":
    unittest.main()
