"""Finished features going out together, on a real git repository, with a stand-in for the broker that fails anything containing
a feature it's been told is bad. The gates themselves don't change, and they only ever see one commit."""
import asyncio
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import llm, workshop


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.name", "Test", cwd=self.repo)
        git("config", "user.email", "test@localhost", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "Start", cwd=self.repo)
        trees = self.root / "trees"
        for patcher in (mock.patch.object(workshop, "REPO", self.repo), mock.patch.object(workshop, "TREES", trees),
                        mock.patch.object(workshop, "RELEASE_TREE", trees / "_release"),
                        mock.patch.object(workshop._git, "__kwdefaults__", {"cwd": self.repo}),
                        mock.patch.object(workshop.commit_all, "__kwdefaults__", {"cwd": self.repo}) if workshop.commit_all.__kwdefaults__ else mock.patch.object(workshop.commit_all, "__defaults__", (self.repo,)),
                        mock.patch.object(workshop, "request", self.broker)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.shop = workshop.Workshop(mock.Mock(), mock.AsyncMock(), mock.Mock(), lambda: ())
        self.bad = set()
        self.releases = []

    async def broker(self, kind, commit, release_id):
        await asyncio.sleep(0)
        shipped = sorted(path for path in git("ls-tree", "--name-only", commit, "mods/genesis/features/", cwd=self.repo).splitlines())
        names = [path.rsplit("/", 1)[-1] for path in shipped]
        self.releases.append({"kind": kind, "features": names, "id": release_id})
        wrong = self.bad.intersection(names)
        return {"result": "blocked", "gate": "shadow", "reason": f"{sorted(wrong)} broke it"} if wrong else {"result": "released", "tier": "T2", "stages": {}}

    def feature(self, name):
        tree = self.shop._prepare_tree(name)
        folder = tree / "mods/genesis/features" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "feature.json").write_text(json.dumps({"id": name}), encoding="utf-8")
        return tree

    def on_main(self):
        return sorted(path.rsplit("/", 1)[-1] for path in git("ls-tree", "--name-only", "main", "mods/genesis/features/", cwd=self.repo).splitlines())

    async def ship(self, *names):
        return dict(zip(names, await asyncio.gather(*(self.shop._release(name, self.feature(name), "e_one") for name in names))))


class Together(Base):
    async def test_whatever_is_ready_goes_out_in_one_release(self):
        answers = await self.ship("a", "b", "c")
        self.assertEqual(len(self.releases), 1)
        self.assertEqual(self.releases[0]["features"], ["a", "b", "c"])
        self.assertEqual(self.on_main(), ["a", "b", "c"])
        self.assertTrue(all(answer["result"] == "released" for answer in answers.values()))

    async def test_one_alone_goes_under_its_own_name(self):
        await self.ship("solo")
        self.assertTrue(self.releases[0]["id"].startswith("solo-"))

    async def test_what_comes_ready_during_a_release_goes_in_the_next_one(self):
        started, carry_on = asyncio.Event(), asyncio.Event()
        real = self.broker

        async def slow(kind, commit, release_id):
            answer = await real(kind, commit, release_id)
            started.set()
            await carry_on.wait()
            return answer

        with mock.patch.object(workshop, "request", slow):
            first = asyncio.create_task(self.shop._release("a", self.feature("a"), "e_one"))
            await started.wait()
            later = [asyncio.create_task(self.shop._release(name, self.feature(name), "e_one")) for name in ("b", "c")]
            await asyncio.sleep(0)
            carry_on.set()
            await asyncio.gather(first, *later)
        self.assertEqual([release["features"] for release in self.releases], [["a"], ["a", "b", "c"]])

    async def test_there_is_a_limit_and_the_rest_go_straight_after(self):
        names = [f"f{number}" for number in range(workshop.MOST_IN_A_RELEASE + 2)]
        await self.ship(*names)
        self.assertEqual(len(self.releases), 2)
        self.assertEqual(len(self.releases[0]["features"]), workshop.MOST_IN_A_RELEASE)
        self.assertEqual(self.on_main(), sorted(names))

    async def test_a_later_release_keeps_what_went_before(self):
        await self.ship("first")
        await self.ship("second")
        self.assertEqual(self.releases[1]["features"], ["first", "second"])


class OneBad(Base):
    async def test_the_others_ship_and_only_it_hears_about_it(self):
        self.bad = {"c"}
        answers = await self.ship("a", "b", "c", "d")
        self.assertEqual(self.on_main(), ["a", "b", "d"])
        self.assertEqual(answers["c"]["result"], "blocked")
        self.assertIn("broke it", answers["c"]["reason"])
        for name in ("a", "b", "d"):
            self.assertEqual(answers[name]["result"], "released", name)

    async def test_finding_it_doesnt_take_many_tries(self):
        self.bad = {"f5"}
        names = [f"f{number}" for number in range(workshop.MOST_IN_A_RELEASE)]
        await self.ship(*names)
        self.assertLessEqual(len(self.releases), 7)
        self.assertEqual(self.on_main(), sorted(set(names) - {"f5"}))

    async def test_two_bad_ones_are_both_found(self):
        self.bad = {"a", "d"}
        answers = await self.ship("a", "b", "c", "d")
        self.assertEqual(self.on_main(), ["b", "c"])
        self.assertEqual((answers["a"]["result"], answers["d"]["result"]), ("blocked", "blocked"))

    async def test_nothing_bad_ever_reaches_main_even_for_a_moment(self):
        self.bad = {"b"}
        await self.ship("a", "b")
        self.assertNotIn("b", git("log", "--format=%s", "main", cwd=self.repo).replace("Start", "").split("\n")[0].split(", "))
        self.assertEqual(self.on_main(), ["a"])

    async def test_a_feature_alone_that_fails_is_told_straight_away(self):
        self.bad = {"solo"}
        answers = await self.ship("solo")
        self.assertEqual(len(self.releases), 1)
        self.assertEqual(answers["solo"]["gate"], "shadow")


class GoingWrong(Base):
    async def test_two_that_cant_merge_dont_stop_each_other_or_the_rest(self):
        for name in ("a", "b"):
            tree = self.feature(name)
            (tree / "shared.txt").write_text(f"from {name}\n", encoding="utf-8")
            git("add", "-A", cwd=tree)
            git("commit", "-q", "-m", f"{name} touches something shared", cwd=tree)
        answers = dict(zip("abc", await asyncio.gather(self.shop._release("a", self.repo.parent / "trees/a", "e_one"), self.shop._release("b", self.repo.parent / "trees/b", "e_one"),
                                                       self.shop._release("c", self.feature("c"), "e_one"))))
        self.assertEqual(answers["a"]["result"], "released")
        self.assertEqual(answers["b"]["gate"], "merge")
        self.assertEqual(answers["c"]["result"], "released")
        self.assertEqual(self.on_main(), ["a", "c"])

    async def test_everyone_hears_if_the_broker_call_itself_breaks(self):
        async def broken(**fields):
            raise RuntimeError("the disk is full")

        with mock.patch.object(workshop, "request", lambda kind, **fields: broken(**fields)):
            answers = await asyncio.wait_for(self.ship("a", "b", "c"), 20)
        self.assertTrue(all("the disk is full" in answer["reason"] for answer in answers.values()))
        self.assertEqual(self.on_main(), [])

    async def test_it_can_start_again_after_going_idle(self):
        await self.ship("a")
        await asyncio.sleep(0)
        await self.ship("b")
        self.assertEqual(self.on_main(), ["a", "b"])


class TheBuild(Base):
    async def test_a_failed_release_goes_back_to_the_builder_with_the_reason(self):
        self.shop.governor.why_not_build.return_value = None
        self.shop.web_research.server.return_value = None
        answers = [{"result": "blocked", "gate": "shadow", "reason": "It broke."}, {"result": "released", "tier": "T2", "stages": {}}]
        prompts = []

        async def attempt(feature_id, tree, prompt, *rest):
            prompts.append(prompt)
            return llm.Result("", None, "s", 0.0, False, "end_turn", 0.0)

        with mock.patch.object(self.shop, "_attempt", attempt), mock.patch.object(self.shop, "_release", mock.AsyncMock(side_effect=answers)), \
                mock.patch.object(self.shop, "_review", mock.AsyncMock(return_value={"approve": True})), mock.patch.object(self.shop, "_log_timing"), \
                mock.patch.object(workshop, "checked_against_main", mock.AsyncMock(return_value={"result": "passed_gates", "screenshots": []})), \
                mock.patch.object(self.shop, "_prepare_tree", return_value=self.root / "tree"):
            shipped = await self.shop.build("demo", "A spec.", "e_one", "early")
        self.assertTrue(shipped)
        self.assertIn("It broke.", prompts[1])
        self.shop.on_released.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
