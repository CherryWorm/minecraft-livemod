"""What every proof script does at the end: time each stage, then write the file and the two preview sheets."""
import json
import sys
import time

from assetkit import bbmodel, sculpt

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sc/out"


def report(m, name, start, machine=False):
    drawn = time.time()
    doc = m.build()
    built = time.time()
    problems = sculpt.check(m, machine)
    checked = time.time()
    bbmodel.save(doc, f"{OUT}/{name}.bbmodel")
    m.preview(f"{OUT}/{name}.png", machine=machine)
    previewed = time.time()
    numbers = sculpt.stats(m)
    numbers.update(script_ms=round((drawn - start) * 1000), build_ms=round((built - drawn) * 1000), check_ms=round((checked - built) * 1000),
                   preview_ms=round((previewed - checked) * 1000))
    print(name, json.dumps(numbers))
    for problem in problems:
        print("PROBLEM:", problem)
    json.dump(numbers, open(f"{OUT}/{name}.json", "w"))
