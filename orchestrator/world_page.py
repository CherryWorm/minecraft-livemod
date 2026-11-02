"""Writes the website's /world pages: this world's theme, and what's been built, what's being built and what's planned.

It runs in a container of its own with no network, no secrets and read-only access to only what the agent has already cleaned up for it, in
orchestrator/ledger.py, plus builders' pictures. So nothing private can reach a page through this, because it can't be read from here at all.

The pages are plain files written ahead of time, in two trees: /world/ is spoiler-free, and /world/spoilers/ is the same pages with everything in them.
A page takes no work to serve, and there's no script on any of them. A spoiler-free page is written from a copy of a record with only a few fields left
in it (see reduced), and all of those are fixed words, numbers, or a line that's been checked as safe for players, so there's nothing else it could show.
Its address says nothing either, because each page's address comes from a salted hash.

A builder has a shell, and it could have written anything in those records or left a link in place of a picture. So all of it is checked as it's read,
everything shown is escaped, and pictures are read without following links and written out again from their pixels.
"""
import hashlib
import html
import io
import json
import math
import os
import pathlib
import re
import stat
import time

from PIL import Image

from orchestrator import scrub
from orchestrator.feedback import CATEGORIES, STAGE_WORDS

IN = pathlib.Path(os.environ.get("WORLD_IN", "/in"))
OUT = pathlib.Path(os.environ.get("WORLD_OUT", "/out"))
PASS_SECONDS = 20
AGENT_QUIET_SECONDS = 3 * 60
TRANSCRIPT_PAGE = 150
TRANSCRIPT_LATEST = 25
TRANSCRIPTS_KEPT = 200  # Finished ones. The agent's record of older ones stays, so this can go up.
TRANSCRIPT_BYTES_PER_PASS = 20 * 1024 * 1024  # Only matters just after a restart. What doesn't fit is left for the next pass.
MOST_SHOTS = 12
MOST_ASSETS = 40
MOST_PICTURE_BYTES = 20 * 1024 * 1024
MOST_SOUND_BYTES = 5 * 1024 * 1024
MOST_RECORD_BYTES = 32 * 1024 * 1024
PICTURES_PER_PASS = 30  # So that the first time through, with every old build to do, this doesn't take the machine's time all at once.
SHOT_WIDTH = 1280
MOSAIC_SIZE = (32, 8)  # Small enough that the colours are all that's left of the banner.
BASE = "/world/"
SPOILERS = "spoilers/"
TABS = (("", "Implemented"), ("building/", "Being built"), ("planned/", "Planned"))
FEATURE, SMALL, FIX = "feature", "small", "fix"
RELEASED, FAILED = "released", "failed"
KIND_WORDS = {FEATURE: "Feature", SMALL: "Small change", FIX: "Bug fix"}
STAGE_NOW = {"building": "Being written", "art": "Having its art finished", "translating": "Being translated", "testing": "In the automated tests",
             "reviewing": "Being reviewed", "releasing": "Waiting to go out", "waiting": "Waiting to carry on"}
PHASES = {"planning", "writing code", "making art", "checking its work", "fixing problems", "finishing up"}  # The same as ledger.PHASES. This doesn't import that, to stay small.
STEP_WORDS = {"build": "Writing it", "art": "Finishing art", "translate": "Translating", "gates": "Automated tests", "review": "Review", "release": "Waiting for and going through release"}
FAILURE_WORDS = {"gate": "It didn't get through the automated tests.", "review": "A reviewer wouldn't pass it.", "release": "It couldn't be released.",
                 "builder": "Its builder stopped before it was done.", "crashed": "Something went wrong while it was being built.", "refused": "It was turned down before a builder started on it."}
ROLE_WORDS = {"builder": "Builder", "small_builder": "Builder", "bug_fixer": "Builder", "reviewer": "Reviewer", "artist": "Artist", "modeller": "Modeller", "translator": "Translator", "researcher": "Researcher"}
# All that's left of a build on a spoiler-free page. Anything added here has to be a fixed word, a number or a line that's already safe for players.
SAFE_FIELDS = ("page", "kind", "stage", "category", "outcome", "safe_name", "started_at", "finished_at", "queued_at", "seconds", "failure_kind", "tokens_total", "steps", "attempts_made", "stage_now", "phase", "attempt", "active_at", "old")
PAGE_ID = re.compile(r"[0-9a-f]{20}")
RUN_NAME = re.compile(r"[a-z0-9_]{1,60}-\d{1,12}")
IDENTIFIER = re.compile(r"[a-z0-9_]{1,60}")
REPORT_DIR = re.compile(r"(.+)-(\d+)")
SHOT_PATH = re.compile(r"/workspace/reports/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,160}\.png)")

Image.MAX_IMAGE_PIXELS = 40_000_000
e = html.escape


def _text(value, limit=None):
    if not isinstance(value, str):
        return ""
    return value[:limit] if limit else value


def _line(value, limit=200):
    return " ".join(_text(value, limit * 2).split())[:limit]


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _one_of(value, allowed):
    return value if isinstance(value, str) and value in allowed else None


def _identifier(value):
    return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) else ""


def _read_json(path):
    try:
        if os.stat(path).st_size > MOST_RECORD_BYTES:
            return None
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return None


def _accent(world):
    """A colour's the only thing this takes from a model that goes straight into the style of a page, so it has to look exactly like one."""
    colour = world.get("accent") if isinstance(world, dict) else None
    return colour if isinstance(colour, str) and re.fullmatch(r"#[0-9a-f]{6}", colour) else None


def _pages_building(board):
    return {page for page in board.get("building") or [] if isinstance(page, str)} if isinstance(board.get("building"), list) else set()


def _steps(phases):
    """Seconds spent on each step, whichever way it came."""
    steps = {}
    for name, seconds in (phases if isinstance(phases, dict) else {}).items():
        step = str(name).split("_")[0]
        if step in STEP_WORDS and _number(seconds) is not None and seconds > 0:
            steps[step] = steps.get(step, 0.0) + seconds
    return steps


def _tokens(tokens):
    clean = {}
    for role, used in (tokens if isinstance(tokens, dict) else {}).items():
        if isinstance(used, dict):
            clean[_line(role, 40)] = {name: int(_number(used.get(name)) or 0) for name in ("input", "output", "cache_read", "cache_write")}
    return clean


def normal(raw, now):
    """A record as it's safe to work with, or None if there's nothing to be done with it."""
    if not isinstance(raw, dict) or not PAGE_ID.fullmatch(str(raw.get("page"))):
        return None
    old = raw.get("old") is True
    tokens = _tokens(raw.get("tokens"))
    failure = raw.get("failure") if isinstance(raw.get("failure"), dict) else {}
    status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
    attempts = [{"attempt": _number(item.get("attempt")), "reason": scrub.secrets(_text(item.get("reason"), 6000)), "kind": _one_of(item.get("kind"), FAILURE_WORDS)}
                for item in raw.get("attempts") or [] if isinstance(item, dict)] if isinstance(raw.get("attempts"), list) else []
    timings = raw.get("timings") if isinstance(raw.get("timings"), dict) else {}
    seconds = _number(raw.get("seconds"))
    resumed = _number(raw.get("resumed_at"))
    if resumed:
        seconds = (seconds or 0.0) + max(0.0, now - resumed)
    return {
        "page": raw["page"], "run": raw["run"] if isinstance(raw.get("run"), str) and RUN_NAME.fullmatch(raw["run"]) else "", "key": _identifier(raw.get("key")), "feature": _identifier(raw.get("feature")),
        "kind": _one_of(raw.get("kind"), KIND_WORDS) or FEATURE, "stage": _one_of(raw.get("stage"), STAGE_WORDS), "category": _one_of(raw.get("category"), CATEGORIES), "node": _identifier(raw.get("node")),
        "outcome": _one_of(raw.get("outcome"), (RELEASED, FAILED)), "old": old, "safe_name": _line(raw.get("safe_name"), 120), "title": _line(raw.get("title"), 200),
        "started_at": _number(raw.get("started_at")), "finished_at": _number(raw.get("finished_at")), "queued_at": _number(raw.get("queued_at")), "active_at": _number(raw.get("active_at")),
        "seconds": seconds, "failure_kind": _one_of(failure.get("kind"), FAILURE_WORDS), "failure_reason": scrub.secrets(_text(failure.get("reason"), 6000)),
        "tokens": tokens, "tokens_total": sum(sum(used.values()) for used in tokens.values()), "estimate": _number(raw.get("estimate")),
        "steps": _steps(raw.get("phases") or timings), "attempts_made": int(_number(raw.get("attempt")) or sum(1 for name in timings if str(name).startswith("build_")) or 0) or None,
        "attempt": int(_number(raw.get("attempt")) or 0) or None, "attempts": attempts, "stage_now": _one_of(raw.get("stage_now"), STAGE_NOW), "phase": _one_of(status.get("phase"), PHASES),
        "doing": scrub.secrets(_line(status.get("doing"), 240)), "doing_at": _number(status.get("at")), "spec": scrub.secrets(_text(raw.get("spec"), 24000)),
        "summary": scrub.secrets(_text(raw.get("summary"), 2400)), "shown": scrub.secrets(_text(raw.get("shown"), 1200)),
        "prompts": [scrub.secrets(_text(item.get("text"), 24000)) for item in raw.get("prompts") or [] if isinstance(item, dict)] if isinstance(raw.get("prompts"), list) else [],
        "screenshots": [path for path in raw.get("screenshots") or [] if isinstance(path, str)] if isinstance(raw.get("screenshots"), list) else [], "entries": int(_number(raw.get("entries")) or 0),
    }


def reduced(view):
    """All a spoiler-free page ever gets to see of a build. See SAFE_FIELDS."""
    return {name: view.get(name) for name in SAFE_FIELDS}


def safe_name(view):
    words = " ".join(part for part in (STAGE_WORDS.get(view.get("stage")), view.get("category")) if part)
    name = view.get("safe_name") or words or "something new"
    return name[0].upper() + name[1:]


def concrete_name(view):
    named = (view.get("feature") or view.get("key") or "something").replace("_", " ").capitalize()
    if view.get("kind") == FIX:
        return f"Fix to {named}: {view['title']}" if view.get("title") else f"Fix to {named}"
    title = view.get("title")
    return title[0].upper() + title[1:] if title else named


# How things read ------------------------------------------------------------------------------------------------------------------------

def _when(moment):
    return time.strftime("%-d %b, %H:%M UTC", time.gmtime(moment)) if moment else "—"


def _time_tag(moment):
    return f'<time datetime="{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))}">{e(_when(moment))}</time>' if moment else "—"


def _took(seconds):
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60} s" if seconds < 600 else f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def _ago(moment, now):
    return f"{_took(max(0, now - moment))} ago" if moment else "—"


def _count(number):
    if not number:
        return "—"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.0f}k"
    return str(number)


def _paragraphs(text):
    return "".join(f"<p>{e(part.strip())}</p>" for part in re.split(r"\n\s*\n", text) if part.strip())


STYLE = """
:root {
  color-scheme: dark light;
  --ground: #15130f; --panel: #1f1c16; --line: #38332a; --text: #ece6d8; --quiet: #a8a08f;
  --moss: #8ccf6e; --dirt: #8a5a3a; --warn: #e0a94f; --bad: #e8826f; --good: #8ccf6e; --row: #1a1813;
}
@media (prefers-color-scheme: light) {
  :root {
    --ground: #f6f2e8; --panel: #fffdf7; --line: #ddd5c3; --text: #24201a; --quiet: #625a4c;
    --moss: #3f7d2c; --warn: #96640f; --bad: #b23a22; --good: #2f6b1f; --row: #fbf8f0;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--ground); color: var(--text); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; overflow-wrap: anywhere; }
a { color: inherit; text-underline-offset: .18em; }
a:focus-visible { outline: 2px solid var(--moss); outline-offset: 2px; }
.mono, h2, .tabs a, .toggle, .eyebrow { font-family: ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace; }
.strata { height: 24px; background: repeating-linear-gradient(90deg, transparent 0 24px, rgba(0,0,0,.14) 24px 48px, transparent 48px 96px, rgba(255,255,255,.05) 96px 120px), linear-gradient(var(--moss) 0 10px, var(--dirt) 10px 24px); }
.spoiler-strip { background: var(--warn); color: #1a1408; padding: .3rem 1rem; font-size: .88rem; font-weight: 650; text-align: center; }
.hero { position: relative; color: #fff; background: #26221a; min-height: clamp(180px, 24vw, 300px); display: flex; align-items: flex-end; overflow: hidden; }
.hero img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; image-rendering: pixelated; }
.hero .scrim { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(10,8,5,.82), rgba(10,8,5,.5) 55%, rgba(10,8,5,.12)); }
.hero .words { position: relative; max-width: 44rem; padding: 3.25rem 1rem 1.25rem; margin-left: max(0px, calc((100vw - 68rem) / 2)); }
.hero h1 { margin: 0; font: 700 clamp(1.8rem, 5vw, 2.8rem)/1.08 ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace; letter-spacing: -.02em; }
.hero p { margin: .6rem 0 0; color: #efe9dc; font-size: 1.04rem; line-height: 1.45; }
.intro { max-width: 68rem; margin: 0 auto; padding: 1.1rem 1rem 0; color: var(--quiet); }
.intro p { max-width: 46rem; }
.toggle { position: absolute; top: .75rem; right: .75rem; z-index: 1; display: inline-flex; align-items: center; gap: .55rem; min-height: 2.5rem; padding: .35rem .8rem; background: rgba(10,8,5,.78); color: #fff; border: 1px solid rgba(255,255,255,.4); border-radius: 2rem; font-size: .84rem; text-decoration: none; }
.toggle:hover { background: rgba(10,8,5,.92); }
.bar { display: flex; justify-content: flex-end; padding: .75rem 1rem 0; max-width: 68rem; margin: 0 auto; }
.bar .toggle { position: static; }
.switch { width: 2rem; height: 1.1rem; border-radius: 1rem; background: #6d675a; position: relative; flex: none; }
.switch::after { content: ""; position: absolute; top: .15rem; left: .15rem; width: .8rem; height: .8rem; border-radius: 50%; background: #fff; }
.toggle.safe .switch { background: var(--accent, #6fae56); }
.toggle.safe .switch::after { left: 1.05rem; }
.tabs { display: flex; flex-wrap: wrap; gap: .25rem 1.25rem; padding: 0 1rem; border-bottom: 1px solid var(--line); max-width: 68rem; margin: 0 auto; }
.tabs a { padding: .9rem .1rem .7rem; font-size: .92rem; font-weight: 650; text-decoration: none; color: var(--quiet); border-bottom: 3px solid transparent; }
.tabs a:hover { color: var(--text); }
.tabs a[aria-current] { color: var(--text); border-bottom-color: var(--accent, var(--moss)); }
.tabs .n { font-weight: 400; opacity: .8; margin-left: .25rem; }
main { max-width: 68rem; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
.back { display: inline-block; margin: 0 0 1rem; color: var(--quiet); font-size: .94rem; }
h1.title { margin: 0 0 .35rem; font: 700 clamp(1.45rem, 4vw, 2rem)/1.15 ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace; letter-spacing: -.02em; }
h2 { margin: 2.25rem 0 .7rem; font-size: .84rem; font-weight: 700; line-height: 1.3; letter-spacing: .08em; text-transform: uppercase; color: var(--moss); }
h3 { margin: 1.1rem 0 .3rem; font-size: 1rem; }
p { margin: 0 0 .85rem; }
.lead { color: var(--quiet); }
.note { color: var(--quiet); font-size: .94rem; }
.warn { padding: .7rem .9rem; background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--warn); margin: 0 0 1rem; }
.rows { border: 1px solid var(--line); background: var(--panel); }
.row { display: grid; gap: .1rem 1rem; align-items: baseline; padding: .6rem .85rem; border-top: 1px solid var(--line); text-decoration: none; }
.row:first-child { border-top: 0; }
a.row:hover, a.row:focus-visible { background: var(--row); }
.row.head { color: var(--quiet); font-size: .8rem; }
.done { grid-template-columns: minmax(0, 1fr) 7rem 6.5rem 9rem; }
.now { grid-template-columns: minmax(0, 1fr) 9rem 6.5rem minmax(0, 15rem); }
.next { grid-template-columns: 2.5rem minmax(0, 1fr) 9rem; }
.name { font-weight: 600; }
.tag { color: var(--quiet); font-size: .84rem; font-weight: 400; }
.cell-label { display: none; color: var(--quiet); font-size: .8rem; margin-right: .35rem; }
.ok { color: var(--good); font-weight: 650; }
.no { color: var(--bad); font-weight: 650; }
.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: .25rem 1.25rem; margin: 1rem 0; padding: .9rem 1rem; background: var(--panel); border: 1px solid var(--line); }
.facts dt { color: var(--quiet); }
.facts dd { margin: 0; }
table { border-collapse: collapse; width: 100%; font-size: .94rem; }
th, td { padding: .3rem .8rem .3rem 0; text-align: left; border-bottom: 1px solid var(--line); }
th { color: var(--quiet); font-weight: 500; }
td.n, th.n { text-align: right; }
pre { margin: .3rem 0 0; padding: .7rem .85rem; background: var(--panel); border: 1px solid var(--line); font: .84rem/1.5 ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 34rem; overflow-y: auto; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr)); gap: .7rem; }
.gallery figure { margin: 0; background: var(--panel); border: 1px solid var(--line); }
.gallery img { display: block; width: 100%; height: auto; }
.gallery figcaption { padding: .3rem .55rem; font-size: .8rem; color: var(--quiet); }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(5.5rem, 1fr)); gap: .55rem; }
.tiles figure { margin: 0; padding: .4rem; background: var(--panel); border: 1px solid var(--line); text-align: center; }
.tiles img { display: block; width: 64px; height: 64px; margin: 0 auto; object-fit: contain; image-rendering: pixelated; }
.tiles figcaption { margin-top: .25rem; font-size: .72rem; color: var(--quiet); }
audio { width: 100%; max-width: 24rem; display: block; margin: .3rem 0; }
.say { margin: .55rem 0; }
.who { color: var(--quiet); font-size: .78rem; font-family: ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace; }
details { margin: .35rem 0; }
summary { cursor: pointer; color: var(--quiet); font-size: .88rem; font-family: ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace; }
.sub { margin-left: 1rem; padding-left: .7rem; border-left: 2px solid var(--line); }
.bad { color: var(--bad); }
.pager { display: flex; flex-wrap: wrap; gap: .4rem .9rem; margin: 1rem 0; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: .6rem; margin: 0 0 1rem; }
.stat { padding: .7rem .85rem; background: var(--panel); border: 1px solid var(--line); }
.stat b { display: block; font-size: 1.35rem; line-height: 1.2; }
.stat span { color: var(--quiet); font-size: .84rem; }
footer { max-width: 68rem; margin: 0 auto; padding: 1rem 1rem 2rem; border-top: 1px solid var(--line); color: var(--quiet); font-size: .88rem; }
@media (max-width: 660px) {
  .row { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: .15rem .75rem; }
  .row > span:first-child { grid-column: 1 / -1; }
  .next > .tag:first-child { display: none; }
  .next > span:nth-child(2) { grid-column: 1 / -1; }
  .now > span:last-child { grid-column: 1 / -1; }
  .row.head { display: none; }
  .cell-label { display: inline; }
  .toggle { position: static; margin: .6rem .75rem 0; align-self: flex-start; }
  .hero { flex-direction: column; align-items: stretch; justify-content: space-between; }
  .hero .words { padding-top: 1.5rem; margin-left: 0; }
  .facts { grid-template-columns: minmax(0, 1fr); gap: .05rem; }
  .facts dd { margin-bottom: .5rem; }
}
"""

ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8' shape-rendering='crispEdges'%3E%3Crect width='8' height='8' fill='%238a5a3a'/%3E%3Crect width='8' height='3' fill='%235fa04e'/%3E"
        "%3Crect x='1' y='3' width='1' height='1' fill='%235fa04e'/%3E%3Crect x='4' y='3' width='2' height='1' fill='%235fa04e'/%3E%3Crect x='6' y='5' width='1' height='1' fill='%23704626'/%3E%3Crect x='2' y='6' width='1' height='1' fill='%23704626'/%3E%3C/svg%3E")


class Mode:
    """One of the two trees of pages."""

    def __init__(self, spoilers):
        self.spoilers = spoilers
        self.root = SPOILERS if spoilers else ""
        self.base = BASE + self.root

    def other(self, path):
        return BASE + ("" if self.spoilers else SPOILERS) + path


SAFE, FULL = Mode(False), Mode(True)


def _document(mode, path, accent, body, now=None, refresh=False):
    """Only pages that can change say when they were written, so that one that's finished isn't written again every minute for nothing."""
    colour = f' style="--accent:{accent}"' if accent else ""
    updated = f"Updated {e(_when(now))}. " if now else ""
    label = ('<span>Spoilers are on</span><span class="switch"></span>' if mode.spoilers else '<span>Spoiler-free</span><span class="switch"></span>')
    toggle = f'<a class="toggle {"full" if mode.spoilers else "safe"}" href="{e(mode.other(path))}" aria-label="{"Go back to spoiler-free" if mode.spoilers else "Show spoilers"}">{label}</a>'
    strip = '<div class="spoiler-strip">Spoilers are showing, for this page and everything you open from it.</div>' if mode.spoilers else ""
    meta = '<meta http-equiv="refresh" content="30">' if refresh else ""
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">{meta}'
            f'<title>Living Mod: this world</title><link rel="icon" href="{ICON}"><style>{STYLE}</style></head><body{colour}><div class="strata" aria-hidden="true"></div>{strip}'
            f'{body.replace("<!--toggle-->", toggle)}<footer>{updated}<a href="/">Back to the main page</a>.</footer></body></html>\n').encode("utf-8")


BAR = '<header class="bar"><!--toggle--></header>'


def _hero(world):
    """A line fits over the picture, and anything longer goes under it, where it can be read."""
    over = world["text"] if world.get("short") else ""
    under = f'<div class="intro">{world["text"]}</div>' if not world.get("short") else ""
    return f'<header class="hero">{world["picture"]}<div class="scrim"></div><!--toggle--><div class="words"><h1>{e(world["name"])}</h1>{over}</div></header>{under}'


def _world_words(mode, world, board, has_banner):
    """The heading of the page. For someone avoiding spoilers the words are ones written to give nothing away, and the picture's reduced to a few blocks of colour."""
    world = world if isinstance(world, dict) else {}
    if not mode.spoilers:
        picture = f'<img src="{BASE}banner-mosaic.png" alt="" width="{MOSAIC_SIZE[0]}" height="{MOSAIC_SIZE[1]}">' if has_banner else ""
        return {"name": _line(world.get("safe_name"), 60) or "This world", "picture": picture, "short": True,
                "text": f'<p>{e(_line(world.get("tease"), 240) or "The agent has chosen a direction for this world, and it is building it now.")}</p>'}
    picture = f'<img src="{BASE}{SPOILERS}banner.png" alt="" width="1920" height="480">' if has_banner else ""
    theme = _text(board.get("theme"), 3000)
    heading = next((line.lstrip("# ").strip() for line in theme.splitlines() if line.strip()), "")
    return {"name": _line(world.get("name"), 60) or _line(heading, 60) or "This world", "picture": picture,
            "text": _paragraphs(_text(world.get("text"), 2000) or "\n".join(theme.splitlines()[1:])[:900])}


def _tabs(mode, current, counts):
    links = []
    for (path, label), count in zip(TABS, counts):
        marked = ' aria-current="page"' if path == current else ""
        links.append(f'<a href="{e(mode.base + path)}"{marked}>{e(label)}<span class="n">{count}</span></a>')
    return f'<nav class="tabs" aria-label="Sections">{"".join(links)}</nav>'


def _outcome(view):
    return '<span class="ok">Released</span>' if view.get("outcome") == RELEASED else '<span class="no">Given up</span>'


def _tags(view, name=""):
    """What kind of thing it is, unless its name has already said."""
    parts = [KIND_WORDS.get(view.get("kind")) if view.get("kind") != FEATURE else None, STAGE_WORDS.get(view.get("stage")), view.get("category")]
    return " · ".join(part for part in parts if part and part.lower() not in name.lower())


def _name_cell(view, name):
    tags = _tags(view, name)
    return f'<span><span class="name">{e(name)}</span>' + (f' <span class="tag">{e(tags)}</span>' if tags else "") + "</span>"


def _cell(label, content):
    return f'<span><span class="cell-label">{e(label)}</span>{content}</span>'


def _implemented(mode, views, world, counts, now, accent):
    rows = "".join(f'<a class="row done" href="{mode.base}f/{view["page"]}/">{_name_cell(view, view["shown_name"])}{_cell("Result", _outcome(view))}{_cell("Ran for", e(_took(view.get("seconds"))))}'
                   f'{_cell("Finished", _time_tag(view.get("finished_at")))}</a>' for view in views)
    table = (f'<div class="rows"><div class="row done head" aria-hidden="true"><span>Name</span><span>Result</span><span>Ran for</span><span>Finished</span></div>{rows}</div>'
             if views else '<p class="lead">Nothing has finished yet.</p>')
    body = f'{_hero(world)}{_tabs(mode, "", counts)}<main><h2>What has finished</h2>{table}</main>'
    return _document(mode, "", accent, body, now)


def _status_words(view):
    words = STAGE_NOW.get(view.get("stage_now")) or "Starting"
    if view.get("stage_now") == "building" and view.get("phase"):
        words = f"Builder is {view['phase']}"
    if view.get("attempt") and view["attempt"] > 1:
        words += f" (try {view['attempt']})"
    return words


def _building(mode, views, world, counts, now, accent, board):
    rows = []
    for view in views:
        status = e(_status_words(view))
        if mode.spoilers and view.get("doing"):
            status += f'<br><span class="tag">{e(view["doing"])} ({e(_ago(view.get("doing_at"), now))})</span>'
        rows.append(f'<a class="row now" href="{mode.base}f/{view["page"]}/">{_name_cell(view, view["shown_name"])}{_cell("Queued", _time_tag(view.get("queued_at")))}{_cell("Running for", e(_took(view.get("seconds"))))}{_cell("Status", status)}</a>')
    table = (f'<div class="rows"><div class="row now head" aria-hidden="true"><span>Name</span><span>Added to the queue</span><span>Running for</span><span>Status</span></div>{"".join(rows)}</div>'
             if rows else '<p class="lead">Nothing is being built right now.</p>')
    body = f'{_hero(world)}{_tabs(mode, "building/", counts)}<main>{_quiet_note(board, now)}<h2>Being built right now</h2>{table}<p class="note" style="margin-top:.8rem">This page refreshes itself every 30 seconds.</p></main>'
    return _document(mode, "building/", accent, body, now, refresh=True)


def _quiet_note(board, now):
    heard = _number(board.get("at"))
    if heard and now - heard > AGENT_QUIET_SECONDS:
        return f'<p class="warn">The agent was last heard from {e(_ago(heard, now))}, so this may be out of date. It may just be restarting.</p>'
    return ""


def _planned(mode, board, world, counts, now, accent, released_nodes):
    queue = board["queue"]
    roadmap = board["roadmap"]
    rows = []
    for number, item in enumerate(queue, 1):
        cells = f'<span class="tag">{number}</span>{_name_cell(item, item["shown_name"])}{_cell("Waiting since", _time_tag(item.get("queued_at")))}'
        rows.append(f'<a class="row next" href="{mode.base}f/{item["run_page"] or item["page"]}/">{cells}</a>' if mode.spoilers else f'<div class="row next">{cells}</div>')
    planning = '<p class="note">More is being planned right now.</p>' if board.get("planning") else ""
    waiting = (f'<div class="rows"><div class="row next head" aria-hidden="true"><span>#</span><span>Name</span><span>Waiting since</span></div>{"".join(rows)}</div>'
               if rows else '<p class="lead">Nothing is waiting right now, because everything planned so far is being built.</p>')
    stages = {stage: [node for node in roadmap["nodes"] if node["stage"] == stage] for stage in STAGE_WORDS}
    if mode.spoilers:
        goal = f'<p>{e(roadmap["goal"])}</p>' if roadmap["goal"] else ""
        sections = "".join(
            f'<h3>{e(STAGE_WORDS[stage].capitalize())}</h3><table><thead><tr><th>Part</th><th>What it holds</th><th>Opens with</th><th>Started</th></tr></thead><tbody>'
            + "".join(f'<tr><td>{e(node["name"] or node["id"])}</td><td>{e(node["holds"])}</td><td>{e(node["opens_with"])}</td><td>{"Yes" if node["id"] in released_nodes else "Not yet"}</td></tr>' for node in nodes)
            + "</tbody></table>" for stage, nodes in stages.items() if nodes)
        plan = f'<h2>The world\'s plan</h2>{goal}{sections}'
    else:
        reached = sum(node["id"] in released_nodes for node in roadmap["nodes"])
        stats = "".join(f'<div class="stat"><b>{len(nodes)}</b><span>{e(STAGE_WORDS[stage])} parts</span></div>' for stage, nodes in stages.items())
        plan = f'<h2>The world\'s plan</h2><div class="stats">{stats}<div class="stat"><b>{reached}</b><span>parts with something out</span></div></div>'
    body = f'{_hero(world)}{_tabs(mode, "planned/", counts)}<main>{_quiet_note(board, now)}<h2>Up next, in order</h2>{planning}{waiting}{plan}</main>'
    return _document(mode, "planned/", accent, body, now)


def _back(mode, view):
    target, label = ("building/", "Being built") if view.get("outcome") is None and not view.get("queued_only") else ("", "Implemented")
    if view.get("queued_only"):
        target, label = "planned/", "Planned"
    return f'<a class="back" href="{e(mode.base + target)}">← {e(label)}</a>'


def _facts(view, now, running):
    facts = []
    if running:
        facts += [("Status", e(_status_words(view))), ("Added to the queue", _time_tag(view.get("queued_at"))), ("Started", _time_tag(view.get("started_at"))), ("Running for", e(_took(view.get("seconds"))))]
    else:
        facts += [("Result", _outcome(view)), ("Finished", _time_tag(view.get("finished_at"))), ("Ran for", e(_took(view.get("seconds"))))]
        if view.get("outcome") == FAILED:
            facts.append(("Why", e(FAILURE_WORDS.get(view.get("failure_kind")) or "It couldn't be finished.")))
    if view.get("attempts_made"):
        facts.append(("Tries", str(view["attempts_made"])))
    label = "Tokens so far" if running else "Tokens"
    facts.append((label, e(_count(view.get("tokens_total"))) if not view.get("old") else "Not recorded for this one"))
    if view.get("steps"):
        facts += [(STEP_WORDS[step], e(_took(seconds))) for step, seconds in view["steps"].items()]
    return '<dl class="facts">' + "".join(f"<dt>{e(label)}</dt><dd>{content}</dd>" for label, content in facts) + "</dl>"


def _detail_safe(view, now, accent):
    running = view.get("outcome") is None
    tags = _tags(view)
    body = (f'<main>{_back(SAFE, view)}<h1 class="title">{e(safe_name(view))}</h1>' + (f'<p class="lead">{e(tags)}</p>' if tags else "") + _facts(view, now, running)
            + '<p class="note">The prompt, the transcript, what was made and why anything went wrong are all hidden while you\'re spoiler-free.</p></main>')
    return _document(SAFE, f"f/{view['page']}/", accent, BAR + body, now if running else None)


def _pictures(media):
    parts = []
    if media.get("shots"):
        more = f' <span class="note">(the first {len(media["shots"])} of {media["shots_total"]})</span>' if media.get("shots_total", 0) > len(media["shots"]) else ""
        figures = "".join(f'<figure><a href="{e(url)}"><img src="{e(url)}" alt="{e(label)}" loading="lazy"></a><figcaption>{e(label)}</figcaption></figure>' for url, label in media["shots"])
        parts.append(f'<h2>Screenshots the reviewer saw{more}</h2><div class="gallery">{figures}</div>')
    if media.get("preview"):
        url, label = media["preview"]
        parts.append(f'<h2>The builder\'s preview</h2><div class="gallery"><figure><a href="{e(url)}"><img src="{e(url)}" alt="{e(label)}" loading="lazy"></a></figure></div>')
    if media.get("assets"):
        figures = "".join(f'<figure><img src="{e(url)}" alt="" loading="lazy"><figcaption>{e(label)}</figcaption></figure>' for url, label in media["assets"])
        parts.append(f'<h2>What it has made</h2><div class="tiles">{figures}</div>')
    if media.get("sounds"):
        parts.append("<h2>Sounds</h2>" + "".join(f'<div class="note">{e(label)}<audio controls preload="none" src="{e(url)}"></audio></div>' for url, label in media["sounds"]))
    return "".join(parts)


def _token_table(view):
    if not view.get("tokens"):
        return ""
    rows = "".join(f'<tr><td>{e(ROLE_WORDS.get(role, role))}</td><td class="n">{used["input"]:,}</td><td class="n">{used["cache_read"] + used["cache_write"]:,}</td><td class="n">{used["output"]:,}</td></tr>' for role, used in view["tokens"].items())
    return ('<h2>Tokens</h2><table><thead><tr><th>Who</th><th class="n">Read</th><th class="n">From cache</th><th class="n">Written</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _detail_full(view, media, transcript, now, accent):
    running = view.get("outcome") is None
    parts = [_back(FULL, view), f'<h1 class="title">{e(view["shown_name"])}</h1>']
    tags = _tags(view)
    if tags:
        parts.append(f'<p class="lead">{e(tags)}</p>')
    parts.append(_facts(view, now, running))
    if view.get("doing"):
        parts.append(f'<h2>What its builder last said</h2><p>{e(view["doing"])} <span class="note">({e(_ago(view.get("doing_at"), now))})</span></p>')
    if view.get("failure_reason"):
        parts.append(f'<h2>Why it was given up on</h2><pre>{e(view["failure_reason"])}</pre>')
    if view.get("old"):
        parts.append('<p class="note">This was built before prompts, tokens and transcripts were being kept, so there\'s only what follows.</p>')
        if view.get("summary"):
            parts.append(f'<h2>What it says about itself</h2><p>{e(view["summary"])}</p>')
        if view.get("shown"):
            parts.append(f'<h2>What it adds</h2><p>{e(view["shown"])}</p>')
    prompts = view.get("prompts") or []
    if prompts:
        parts.append(f'<h2>The prompt</h2><pre>{e(prompts[0])}</pre>')
        parts.extend(f'<details><summary>What it was told on try {number}</summary><pre>{e(text)}</pre></details>' for number, text in enumerate(prompts[1:], 2))
    elif view.get("spec"):
        parts.append(f'<h2>The spec</h2><pre>{e(view["spec"])}</pre>')
    if view.get("attempts"):
        parts.append("<h2>What sent it back</h2>" + "".join(f'<details><summary>Try {int(item["attempt"] or 0)}: {e(FAILURE_WORDS.get(item["kind"]) or "It went back to its builder.")}</summary><pre>{e(item["reason"])}</pre></details>' for item in view["attempts"]))
    parts.append(_token_table(view))
    parts.append(_pictures(media))
    if transcript:
        parts.append(transcript)
    return _document(FULL, f"f/{view['page']}/", accent, f'{BAR}<main>{"".join(parts)}</main>', now if running else None)


def _detail_queued(item, now, accent):
    tags = _tags(item)
    parts = [f'<a class="back" href="{BASE}{SPOILERS}planned/">← Planned</a><h1 class="title">{e(item["shown_name"])}</h1>']
    if tags:
        parts.append(f'<p class="lead">{e(tags)}</p>')
    parts.append(f'<dl class="facts"><dt>Status</dt><dd>Waiting to be started</dd><dt>Added to the queue</dt><dd>{_time_tag(item.get("queued_at"))}</dd>' + (f'<dt>Part of the plan</dt><dd>{e(item["node"])}</dd>' if item.get("node") else "") + "</dl>")
    if item.get("spec"):
        parts.append(f'<h2>The spec</h2><pre>{e(item["spec"])}</pre>')
    return _document(FULL, f"f/{item['page']}/", accent, f'{BAR}<main>{"".join(parts)}</main>')


def _queued_safe_page(item, now, accent):
    """The other side of the toggle from a planned feature's page. It only has to say there's nothing to see here."""
    return _document(SAFE, f"f/{item['page']}/", accent, f'{BAR}<main><a class="back" href="{BASE}planned/">← Planned</a>'
                     f'<h1 class="title">{e(safe_name(item))}</h1><p class="note">What this will be is hidden while you\'re spoiler-free.</p></main>', now)


def _waiting_page(now):
    """The same on both sides, because there's nothing to hide yet and no reason to say so."""
    return _document(SAFE, "", None, '<main><h1 class="title">Nothing here yet</h1><p class="lead">This world doesn\'t have a theme yet. Once it does, this is where you can follow how it\'s coming along.</p></main>', now)


def _normal_queue(board, now):
    items = []
    for raw in board.get("queue") if isinstance(board.get("queue"), list) else []:
        if not isinstance(raw, dict) or not PAGE_ID.fullmatch(str(raw.get("page"))):
            continue
        items.append({"page": raw["page"], "run_page": raw["run_page"] if PAGE_ID.fullmatch(str(raw.get("run_page"))) else None, "key": _identifier(raw.get("key")), "feature": _identifier(raw.get("key")), "kind": _one_of(raw.get("kind"), KIND_WORDS) or FEATURE,
                      "stage": _one_of(raw.get("stage"), STAGE_WORDS), "category": _one_of(raw.get("category"), CATEGORIES), "safe_name": _line(raw.get("safe_name"), 120), "title": _line(raw.get("title"), 200),
                      "node": _line(raw.get("node"), 200), "spec": scrub.secrets(_text(raw.get("spec"), 24000)), "queued_at": _number(raw.get("queued_at")), "queued_only": True})
    return items


def _normal_roadmap(board):
    raw = board.get("roadmap") if isinstance(board.get("roadmap"), dict) else {}
    nodes = []
    for node in raw.get("nodes") if isinstance(raw.get("nodes"), list) else []:
        if isinstance(node, dict) and _one_of(node.get("stage"), STAGE_WORDS):
            nodes.append({"id": _identifier(node.get("id")), "stage": node["stage"], "name": _line(node.get("name"), 200), "holds": scrub.secrets(_text(node.get("holds"), 1200)), "opens_with": scrub.secrets(_text(node.get("opens_with"), 600))})
    return {"goal": scrub.secrets(_text(raw.get("goal"), 2400)), "nodes": nodes}


def render(board, world, runs, media, transcripts, now, has_banner=True):
    """Every page there should be, by path. It's given everything it needs, so that it does nothing else. Only ever reads a build through reduced for the spoiler-free tree."""
    files = {}
    if not (isinstance(board, dict) and board.get("chosen") is True):
        files["index.html"] = files[f"{SPOILERS}index.html"] = _waiting_page(now)
        return files
    accent = _accent(world)
    building_pages = _pages_building(board)
    finished = sorted((run for run in runs if run.get("outcome")), key=lambda run: run.get("finished_at") or 0, reverse=True)
    building = sorted((run for run in runs if run["page"] in building_pages and not run.get("outcome")), key=lambda run: run.get("started_at") or 0)
    queue = _normal_queue(board, now)
    board = {**board, "queue": queue, "roadmap": _normal_roadmap(board)}
    released_nodes = {run["node"] for run in finished if run.get("outcome") == RELEASED and run.get("node")}
    counts = (len(finished), len(building), len(queue))
    for mode in (SAFE, FULL):
        words = _world_words(mode, world, board, has_banner)
        view_of = (lambda run: {**run, "shown_name": concrete_name(run)}) if mode.spoilers else (lambda run: {**reduced(run), "shown_name": safe_name(run)})
        files[f"{mode.root}index.html"] = _implemented(mode, [view_of(run) for run in finished], words, counts, now, accent)
        files[f"{mode.root}building/index.html"] = _building(mode, [view_of(run) for run in building], words, counts, now, accent, board)
        items = [{**item, "shown_name": concrete_name(item)} if mode.spoilers else {**{name: item.get(name) for name in ("page", "kind", "stage", "category", "queued_at", "safe_name")}, "shown_name": safe_name(item)} for item in queue]
        files[f"{mode.root}planned/index.html"] = _planned(mode, {**board, "queue": items}, words, counts, now, accent, released_nodes)
    for run in runs:
        files[f"f/{run['page']}/index.html"] = _detail_safe(reduced(run), now, accent)
        files[f"{SPOILERS}f/{run['page']}/index.html"] = _detail_full({**run, "shown_name": concrete_name(run)}, media.get(run["page"], {}), transcripts.get(run["page"]), now, accent)
    for item in queue:
        if not item.get("run_page"):
            files[f"f/{item['page']}/index.html"] = _queued_safe_page({name: item.get(name) for name in ("page", "stage", "category", "safe_name")}, now, accent)
            files[f"{SPOILERS}f/{item['page']}/index.html"] = _detail_queued({**item, "shown_name": concrete_name(item)}, now, accent)
    return files


# Writing it all out ---------------------------------------------------------------------------------------------------------------------

class Publisher:
    """Only touches a page if it's changed, each change is one atomic step, and anything that's no longer wanted goes."""

    def __init__(self, out):
        self.out = pathlib.Path(out)
        self.wanted = set()
        self.wanted_folders = set()

    def write(self, relative, data):
        self.wanted.add(relative)
        path = self.out / relative
        try:
            if path.read_bytes() == data:
                return
        except OSError:
            path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def keep(self, relative):
        self.wanted.add(relative)

    def keep_folder(self, relative):
        self.wanted_folders.add(relative)

    def sweep(self):
        for folder, names, files in os.walk(self.out, topdown=False):
            base = pathlib.Path(folder)
            for name in files:
                relative = (base / name).relative_to(self.out).as_posix()
                if relative not in self.wanted and not any(relative.startswith(prefix) for prefix in self.wanted_folders):
                    (base / name).unlink(missing_ok=True)
            if base != self.out and not any(base.iterdir()):
                base.rmdir()
        self.wanted, self.wanted_folders = set(), set()


def _usable_file(path, root, limit):
    """What's there if it's an ordinary file under where it should be, and not too big. A builder could have left a link pointing anywhere, or anything else that isn't what it says."""
    path = os.path.abspath(path)
    real = os.path.realpath(path)
    if real != path or not real.startswith(os.path.join(os.path.abspath(root), "")):
        return None
    try:
        info = os.lstat(real)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit else None


class Media:
    """Pictures and sounds, copied out once each, as their pixels only, so nothing else that's in the file can come along."""

    def __init__(self, publisher, reports, trees):
        self.publisher = publisher
        self.reports = pathlib.Path(reports)
        self.trees = pathlib.Path(trees)
        self.budget = PICTURES_PER_PASS
        self.report_folders = {}
        self.finished = {}  # What's been sorted out for a build that won't change, so that there's no looking for it again on every pass.
        self.used = []
        self.bad = set()  # Whatever couldn't be read as what it says it is, so that it isn't tried again every time.

    def start_pass(self):
        self.budget = PICTURES_PER_PASS
        self.report_folders = {}
        try:
            for entry in os.scandir(self.reports):
                found = REPORT_DIR.fullmatch(entry.name)
                if found and entry.is_dir(follow_symlinks=False):
                    self.report_folders.setdefault(found.group(1), []).append((entry.stat(follow_symlinks=False).st_mtime, entry.name))
        except OSError:
            pass

    def _target(self, source, info, page, extension):
        digest = hashlib.sha256(f"{source}|{info.st_size}|{info.st_mtime_ns}".encode()).hexdigest()[:24]
        return f"{SPOILERS}img/{page}/{digest}.{extension}"

    def picture(self, source, root, page, shot=False):
        """Where it can be found on the site, or None if it can't be used or it's waiting its turn."""
        info = _usable_file(source, root, MOST_PICTURE_BYTES)
        if info is None:
            return None
        relative = self._target(source, info, page, "jpg" if shot else "png")
        if (self.publisher.out / relative).exists():
            self.publisher.keep(relative)
            self.used.append(relative)
            return BASE + relative
        if self.budget <= 0 or relative in self.bad:
            return None
        self.budget -= 1
        try:
            self.publisher.write(relative, _picture_bytes(source, shot))
        except Exception as error:  # noqa: BLE001 - a bad picture just doesn't get shown
            print(f"couldn't use a picture: {type(error).__name__}", flush=True)
            self.bad.add(relative)
            return None
        self.used.append(relative)
        return BASE + relative

    def sound(self, source, root, page):
        info = _usable_file(source, root, MOST_SOUND_BYTES)
        if info is None:
            return None
        with open(source, "rb") as stream:
            data = stream.read()
        if not data.startswith(b"OggS"):
            return None
        relative = self._target(source, info, page, "ogg")
        self.publisher.write(relative, data)
        self.used.append(relative)
        return BASE + relative

    def _shots(self, view):
        listed = [found.groups() for found in (SHOT_PATH.fullmatch(path) for path in view.get("screenshots") or []) if found]
        if not listed and view.get("old") and view.get("feature"):
            # Nothing recorded which ones the reviewer saw back then, so these are the ones from the last test before it finished.
            folders = [item for item in self.report_folders.get(view["feature"], []) if item[0] <= (view.get("finished_at") or 0) + 120]
            if folders:
                folder = max(folders)[1]
                try:
                    listed = [(folder, name) for name in sorted(os.listdir(self.reports / folder)) if name.endswith(".png")]
                except OSError:
                    listed = []
        feature = view.get("feature") or "\0"
        listed.sort(key=lambda item: (feature not in item[1], "scene_" not in item[1]))
        return listed

    def _assets(self, view):
        folder = self.trees / (view.get("feature") if view.get("kind") == FIX else view.get("key") or "") / "mods/genesis/features" / (view.get("feature") or "") / "assets"
        pictures, sounds = [], []
        for base, names, files in os.walk(folder, followlinks=False):
            names[:] = [name for name in sorted(names) if not name.startswith(".")]
            for name in sorted(files):
                if name.endswith(".png") and len(pictures) < MOST_ASSETS:
                    pictures.append(os.path.join(base, name))
                elif name.endswith(".ogg") and len(sounds) < 6:
                    sounds.append(os.path.join(base, name))
        return pictures, sounds

    def for_run(self, view):
        page = view["page"]
        done = self.finished.get(page)
        if done:
            for relative in done[1]:
                self.publisher.keep(relative)
            return done[0]
        media = {}
        self.used = []
        listed = self._shots(view)
        if listed:
            media["shots_total"] = len(listed)
            shots = ((self.picture(self.reports / folder / name, self.reports, page, shot=True), re.sub(r"^\d+_", "", name[:-4]).replace("_", " ")) for folder, name in listed[:MOST_SHOTS])
            media["shots"] = [shot for shot in shots if shot[0]]
        if view.get("feature"):
            preview = self.picture(self.reports / f"preview-{view['feature']}.png", self.reports, page)
            if preview:
                media["preview"] = (preview, "What the builder looked at while working")
            pictures, sounds = self._assets(view)
            assets = ((self.picture(path, self.trees, page), pathlib.Path(path).stem.replace("_", " ")) for path in pictures)
            media["assets"] = [asset for asset in assets if asset[0]]
            noises = ((self.sound(path, self.trees, page), pathlib.Path(path).stem.replace("_", " ")) for path in sounds)
            media["sounds"] = [noise for noise in noises if noise[0]]
        if view.get("outcome") and self.budget > 0:
            self.finished[page] = (media, self.used)
        return media


def _picture_bytes(source, shot):
    """The file's pixels and nothing else from it, and a screenshot smaller, because there are a lot of them."""
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream, Image.open(stream, formats=["PNG"]) as image:
        image.load()
        out = io.BytesIO()
        if shot:
            picture = image.convert("RGB")
            picture.thumbnail((SHOT_WIDTH, SHOT_WIDTH))
            picture.save(out, "JPEG", quality=82, optimize=True)
        else:
            picture = image.convert("RGBA")
            picture.save(out, "PNG")
        return out.getvalue()


def mosaic_bytes(source):
    """A few blocks of the banner's colours, which is all someone avoiding spoilers sees of it. It's made here, so it can't depend on how the banner was drawn."""
    with Image.open(source, formats=["PNG"]) as image:
        small = image.convert("RGB").resize(MOSAIC_SIZE, Image.Resampling.BOX)
        out = io.BytesIO()
        small.save(out, "PNG")
        return out.getvalue()


class Transcripts:
    """Written a page at a time as they grow, because a long one would be a lot to go over every few seconds."""

    def __init__(self, publisher, runs_folder):
        self.publisher = publisher
        self.folder = pathlib.Path(runs_folder)
        self.seen = {}
        self.budget = TRANSCRIPT_BYTES_PER_PASS

    def start_pass(self):
        self.budget = TRANSCRIPT_BYTES_PER_PASS

    def update(self, view, now, accent):
        """Returns what goes on the build's own page: the latest of it, and links to the rest."""
        page, run = view["page"], view.get("run")
        if not run:
            return None
        path = self.folder / f"{run}.transcript.jsonl"
        info = _usable_file(path, self.folder, 1024 * 1024 * 1024)
        if info is None:
            return None
        seen = self.seen.setdefault(page, {"offset": 0, "tail": [], "pages": 0, "latest": []})
        if info.st_size > seen["offset"] and self.budget > 0:
            with open(path, "rb") as stream:
                stream.seek(seen["offset"])
                data = stream.read(min(self.budget, info.st_size - seen["offset"]))
            self.budget -= len(data)
            complete = data[:data.rfind(b"\n") + 1]
            seen["offset"] += len(complete)
            self._add_lines(seen, complete.decode("utf-8", "replace").splitlines())
            while len(seen["tail"]) >= TRANSCRIPT_PAGE:
                self._write_page(view, seen["pages"] + 1, seen["tail"][:TRANSCRIPT_PAGE], True, now, accent)
                seen["pages"] += 1
                del seen["tail"][:TRANSCRIPT_PAGE]
        self.publisher.keep_folder(f"{SPOILERS}f/{page}/transcript/")
        if seen["tail"]:
            self._write_page(view, seen["pages"] + 1, seen["tail"], False, now, accent)
        total = seen["pages"] + bool(seen["tail"])
        if not total:
            return None
        links = "".join(f'<a href="{BASE}{SPOILERS}f/{page}/transcript/{number}/">Page {number}</a>' for number in range(1, total + 1))
        kept = "Up to the latest it's done" if view.get("outcome") is None else "All of it"
        return f'<h2>Transcript</h2><p class="note">{kept}, as recorded. Here\'s the end of it, and the rest is by page.</p><div class="pager">{links}</div>{"".join(seen["latest"])}'

    def _add_lines(self, seen, lines):
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            try:
                piece = transcript_entry(entry)
            except (TypeError, ValueError):
                continue
            if piece:
                seen["tail"].append(piece)
                seen["latest"].append(piece)
        del seen["latest"][:-TRANSCRIPT_LATEST]

    def _write_page(self, view, number, pieces, finished, now, accent):
        page = view["page"]
        back = f'<a href="{BASE}{SPOILERS}f/{page}/transcript/{number - 1}/">← Earlier</a>' if number > 1 else ""
        forward = f'<a href="{BASE}{SPOILERS}f/{page}/transcript/{number + 1}/">Later →</a>' if finished else ""
        pager = f'<div class="pager">{back}{forward}</div>'
        body = (f'<main><a class="back" href="{BASE}{SPOILERS}f/{page}/">← Back to this build</a>'
                f'<h1 class="title">Transcript, page {number}</h1>{pager}{"".join(pieces)}{pager}</main>')
        self.publisher.write(f"{SPOILERS}f/{page}/transcript/{number}/index.html", _document(FULL, "", accent, body))


def _gist(said):
    """The part of what a tool was asked that says which it was, for the line you click on to see it all."""
    try:
        said = json.loads(said)
    except ValueError:
        return _line(said, 90)
    if isinstance(said, dict):
        for name in ("command", "file_path", "path", "pattern", "doing", "description", "class_name"):
            if isinstance(said.get(name), str):
                return _line(said[name], 90)
    return ""


def transcript_entry(entry):
    """One thing said or done, for the spoiler pages. The agent's already scrubbed it, and it's looked over again here for anything shaped like a secret, in case something else wrote it."""
    if not isinstance(entry, dict):
        return ""
    kind = entry.get("kind")
    text = scrub.secrets(_text(entry.get("text"), 24000))
    role = _line(entry.get("role"), 40)
    who = ROLE_WORDS.get(role, role or "Agent")
    who = e(who + (" (helper)" if entry.get("sub") else ""))
    wrap = (lambda piece: f'<div class="sub">{piece}</div>') if entry.get("sub") else (lambda piece: piece)
    if kind == "say":
        return wrap(f'<div class="say"><div class="who">{who}</div>{_paragraphs(text)}</div>')
    if kind == "think":
        return wrap(f'<details><summary>{who} thought</summary><pre>{e(text)}</pre></details>')
    if kind == "use":
        name = _line(entry.get("name"), 80).removeprefix("mcp__broker__").removeprefix("mcp__world__").removeprefix("mcp__art__")
        gist = _gist(text)
        return wrap(f'<details><summary>{who} used {e(name)}{": " + e(gist) if gist else ""}</summary><pre>{e(text)}</pre></details>')
    if kind == "got":
        return wrap(f'<details><summary class="{"bad" if entry.get("error") else ""}">{"It failed:" if entry.get("error") else "It got back"}</summary><pre>{e(text)}</pre></details>')
    if kind == "prompt":
        return wrap(f'<details><summary>What {who} was told</summary><pre>{e(text)}</pre></details>')
    if kind in ("end", "note"):
        return wrap(f'<p class="note">{who}: {e(_line(text, 300))}</p>')
    return ""


class Pages:
    def __init__(self, folder_in=IN, out=OUT):
        self.ledger = pathlib.Path(folder_in) / "ledger"
        self.publisher = Publisher(out)
        self.media = Media(self.publisher, pathlib.Path(folder_in) / "reports", pathlib.Path(folder_in) / "trees")
        self.transcripts = Transcripts(self.publisher, self.ledger / "runs")
        self.records = {}  # What's been read, by file and when it last changed.

    def _records(self):
        found = []
        try:
            entries = list(os.scandir(self.ledger / "runs"))
        except OSError:
            return found
        for entry in entries:
            if not entry.name.endswith(".json") or not entry.is_file(follow_symlinks=False) or entry.name.startswith("."):
                continue
            mark = entry.stat(follow_symlinks=False).st_mtime_ns
            saved = self.records.get(entry.name)
            if not saved or saved[0] != mark:
                saved = (mark, _read_json(entry.path))
                self.records[entry.name] = saved
            found.append(saved[1])
        return found

    def _banner(self):
        source = self.ledger / "banner.png"
        if _usable_file(source, self.ledger, MOST_PICTURE_BYTES) is None:
            return False
        try:
            mark = source.stat().st_mtime_ns
            if getattr(self, "banner_mark", None) != mark:
                self.banner_files = (_picture_bytes(source, False), mosaic_bytes(source))
                self.banner_mark = mark
            self.publisher.write(f"{SPOILERS}banner.png", self.banner_files[0])
            self.publisher.write("banner-mosaic.png", self.banner_files[1])
            return True
        except Exception as error:  # noqa: BLE001 - the page does without
            print(f"couldn't use the banner: {type(error).__name__}", flush=True)
            return False

    def one_pass(self, now=None):
        now = now or time.time()
        board = _read_json(self.ledger / "board.json")
        chosen = isinstance(board, dict) and board.get("chosen") is True
        runs, media, transcripts, has_banner = [], {}, {}, False
        world = None
        if chosen:
            old = _read_json(self.ledger / "old_builds.json")
            raw = [*(old if isinstance(old, list) else []), *self._records()]
            runs = [view for view in (normal(item, now) for item in raw) if view]
            world = _read_json(self.ledger / "world.json")
            accent = _accent(world)
            has_banner = self._banner()
            self.media.start_pass()
            self.transcripts.start_pass()
            building = _pages_building(board)
            newest_first = sorted(runs, key=lambda run: run.get("finished_at") or now, reverse=True)
            for position, view in enumerate(newest_first):
                media[view["page"]] = self.media.for_run(view)
                if position < TRANSCRIPTS_KEPT or view["page"] in building:
                    transcript = self.transcripts.update(view, now, accent)
                    if transcript:
                        transcripts[view["page"]] = transcript
        for relative, data in render(board, world, runs, media, transcripts, now, has_banner).items():
            self.publisher.write(relative, data)
        self.publisher.sweep()

    def run(self):
        print("writing the world pages", flush=True)
        while True:
            try:
                self.one_pass()
            except Exception as error:  # noqa: BLE001 - try again, and what's there already stays up
                print(f"couldn't write the world pages: {type(error).__name__}: {error}", flush=True)
            time.sleep(PASS_SECONDS)


if __name__ == "__main__":
    Pages().run()
