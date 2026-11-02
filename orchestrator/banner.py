"""The top of the website's page about this world: a picture, its name and some words, made once it has a theme. Like the server icon, it's a nice
touch rather than a need, so a failure only gets logged and the page goes without.

There's a version of each for someone avoiding spoilers. The page shows them only a blurred mosaic of the picture, which it makes itself, so nothing can
be seen in it however it was drawn, and words a model wrote to give nothing away, which are checked against what's being built in this world.
"""
import json
import pathlib
import re
import shutil

from PIL import Image

from orchestrator import ledger, llm, workshop

FOLDER = pathlib.Path("/workspace/banner")
WORDS = ledger.FOLDER / "world.json"
PICTURE = ledger.FOLDER / "banner.png"
TOOLS = ["Read", "Write", "Edit", "Glob", "Bash"]
TRIES = 2
MOST_BYTES = 4 * 1024 * 1024
WIDEST = 5.0
NARROWEST = 2.0
SMALLEST_WIDTH = 600
LONGEST_NAME = 60
LONGEST_TEASE = 240
LONGEST_TEXT = 1500
SHORTEST_GIVEAWAY = 4  # Words shorter than this are mostly the kind anyone would use.
# In names of things a lot, and meaning nothing by themselves.
COMMON = {"with", "from", "that", "this", "these", "those", "what", "where", "when", "into", "over", "under", "your", "their", "them", "they", "have", "will", "world", "first", "more",
          "some", "than", "then", "only", "here", "there", "like", "make", "made", "keep", "long", "last", "work", "works", "just", "very", "much", "many", "good", "great", "small", "large"}
SCHEMA = {"type": "object", "required": ["name", "text", "safe_name", "tease", "accent"], "properties": {
    "name": {"type": "string"}, "text": {"type": "string"}, "safe_name": {"type": "string"}, "tease": {"type": "string"}, "accent": {"type": "string"}}}


def made():
    return WORDS.exists()


def giveaways(graph):
    """Words that come from what's in this world or planned for it. Someone avoiding spoilers shouldn't read those in a heading."""
    names = [workshop.REPO / "bible" / "persona_name.txt"]
    words = [path.read_text(encoding="utf-8") for path in names if path.exists()]
    words += [graph.get("goal", "")] if graph else []
    for node_id, node in (graph or {}).get("nodes", {}).items():
        words += [node_id.replace("_", " "), node.get("name", "")]
    for manifest in (workshop.REPO / workshop.FEATURES).glob("*/feature.json"):
        words.append(manifest.parent.name.replace("_", " "))
        try:
            found = json.loads(manifest.read_text(encoding="utf-8"))
        except ValueError:
            continue
        words += [str(thing.get("display", "")) for table in ("blocks", "items", "mobs") for thing in (found.get(table) or {}).values() if isinstance(thing, dict)]
    return {word for word in re.findall(r"[a-z']+", " ".join(words).lower()) if len(word) >= SHORTEST_GIVEAWAY} - COMMON


def problem_with_words(answer, graph):
    """Why these words can't be shown to someone avoiding spoilers, or None if they can."""
    if not isinstance(answer, dict) or not all(isinstance(answer.get(name), str) and answer[name].strip() for name in SCHEMA["required"]):
        return "Some of it is missing."
    if len(answer["safe_name"]) > LONGEST_NAME or len(answer["name"]) > LONGEST_NAME:
        return f"A name has to fit in {LONGEST_NAME} characters."
    if len(answer["tease"]) > LONGEST_TEASE:
        return f"`tease` has to fit in {LONGEST_TEASE} characters."
    safe_words = set(re.findall(r"[a-z']+", f"{answer['safe_name']} {answer['tease']}".lower()))
    real_name = set(re.findall(r"[a-z']+", answer["name"].lower())) - COMMON
    named = {word for word in safe_words & (giveaways(graph) | real_name) if len(word) >= SHORTEST_GIVEAWAY}
    if named:
        return f"`safe_name` and `tease` mustn't use any word from what's in this world or from its real name, and these do: {', '.join(sorted(named))}."
    return None


def problem_with_picture(path):
    if not path.exists() or path.stat().st_size > MOST_BYTES:
        return "banner.png isn't there, or it's bigger than 4 MB."
    try:
        with Image.open(path, formats=["PNG"]) as image:
            width, height = image.size
            image.verify()
    except Exception as error:  # noqa: BLE001 - whatever's wrong with it, it can't be used
        return f"banner.png can't be read as a PNG: {error}"
    if width < SMALLEST_WIDTH or not NARROWEST <= width / height <= WIDEST:
        return f"banner.png is {width}x{height}, and it should be at least {SMALLEST_WIDTH} wide and between {NARROWEST:g} and {WIDEST:g} times as wide as it is high."
    return None


async def make(governor, graph):
    FOLDER.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(workshop.REPO / "bible" / "theme.md", FOLDER / "theme.md")
    prompt = "Make the banner and write the words."
    session = None
    for _ in range(TRIES):
        result = await llm.ask(governor, "banner", prompt, schema=SCHEMA, tools=TOOLS, allowed_tools=TOOLS, disallowed_tools=workshop.BUILDER_DENIED, cwd=str(FOLDER), budget=3.0, resume=session)
        session = result.session_id or session
        answer = result.structured
        problem = "It didn't finish." if result.is_error else problem_with_picture(FOLDER / "banner.png") or problem_with_words(answer, graph)
        if not problem:
            clean = ledger.scrubber()
            accent = answer["accent"].strip().lower()
            ledger.FOLDER.mkdir(parents=True, exist_ok=True)
            ledger._write(PICTURE, (FOLDER / "banner.png").read_bytes())
            ledger._write_json(WORDS, {"name": clean(answer["name"], LONGEST_NAME), "text": clean(answer["text"], LONGEST_TEXT), "safe_name": clean(answer["safe_name"], LONGEST_NAME),
                                       "tease": clean(answer["tease"], LONGEST_TEASE), "accent": accent if re.fullmatch(r"#[0-9a-f]{6}", accent) else None})
            print("the page's banner is made", flush=True)
            return True
        print(f"the page's banner wasn't accepted: {problem}", flush=True)
        prompt = f"That can't be used: {problem} Fix it, and give all the words again."
    return False
