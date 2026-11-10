#!/usr/bin/env python3
"""Show that the built `reveille` is the same program as an older single-file copy.

  git show HEAD:reveille > /tmp/reveille.old        # the version from before the split
  python3 tools/prove_split.py /tmp/reveille.old    # compares it with ./reveille and with src/

Checks, each reported as ok / FAIL:
  1. the files are identical byte for byte (sha256)
  2. the two parse to the same syntax tree, with and without line numbers
  3. every line of the old file is in the new one and the other way round (counted, not just present)
  4. src/ holds every old line exactly once and in order, so nothing was dropped, copied or reordered
  5. test_reveille.py run against each file gives the same result for every single test
Exit status 0 only if all five pass. Nothing is written outside a temporary folder."""
import ast, collections, hashlib, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path, newline="") as f: return f.read()


def fragment_lines():
    """All lines of src/ in layer order, without the "#:" notes at the top of each fragment."""
    out = []
    for n in sorted(x for x in os.listdir(f"{ROOT}/src") if re.fullmatch(r"\d\d_[a-z0-9_]+\.py", x)):
        lines = read(f"{ROOT}/src/{n}").splitlines(keepends=True)
        i = 0
        while i < len(lines) and lines[i].startswith("#:"): i += 1
        out += lines[i:]
    return out


def run_tests(reveille):
    """{test name: ok / FAIL / ERROR / skipped} and the summary line, from running test_reveille.py on `reveille`."""
    d = tempfile.mkdtemp()
    try:
        shutil.copy(reveille, f"{d}/reveille"); shutil.copy(f"{ROOT}/test_reveille.py", d)
        r = subprocess.run([sys.executable, "test_reveille.py", "-v"], cwd=d, capture_output=True, text=True,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    finally:
        shutil.rmtree(d, ignore_errors=True)
    results = {}
    for line in r.stderr.splitlines():
        m = re.match(r"(\S+) \((\S+)\) \.\.\. (ok|FAIL|ERROR|skipped.*)$", line)
        if m: results[f"{m[2]}"] = m[3].split()[0] if m[3].startswith("skipped") else m[3]
    return results, next((l for l in r.stderr.splitlines() if l.startswith(("OK", "FAILED"))), "no summary")


def main(argv):
    if len(argv) != 2: print(__doc__); return 2
    old_path, new_path = argv[1], f"{ROOT}/reveille"
    old, new = read(old_path), read(new_path)
    ok = True
    def report(passed, what):
        nonlocal ok; ok &= passed; print(f"{'ok  ' if passed else 'FAIL'}  {what}")

    ho, hn = hashlib.sha256(old.encode()).hexdigest(), hashlib.sha256(new.encode()).hexdigest()
    report(ho == hn, f"1. byte for byte: old {ho[:12]}  new {hn[:12]}  ({len(old.splitlines())} and {len(new.splitlines())} lines)")

    to, tn = ast.parse(old), ast.parse(new)
    report(ast.dump(to) == ast.dump(tn) and ast.dump(to, include_attributes=True) == ast.dump(tn, include_attributes=True),
           f"2. same syntax tree, with line numbers too ({sum(1 for _ in ast.walk(to))} nodes)")

    co, cn = collections.Counter(old.splitlines()), collections.Counter(new.splitlines())
    lost, extra = co - cn, cn - co
    report(not lost and not extra, f"3. line counts match both ways (missing from new: {sum(lost.values())}, only in new: {sum(extra.values())})")

    frag = fragment_lines()
    report(frag == old.splitlines(keepends=True), f"4. src/ holds all {len(frag)} old lines exactly once, in order")

    ro, so = run_tests(old_path); rn, sn = run_tests(new_path)
    diff = sorted(k for k in set(ro) | set(rn) if ro.get(k) != rn.get(k))
    report(ro == rn and len(ro) > 0, f"5. tests, old: {len(ro)} [{so}]  new: {len(rn)} [{sn}]  differing results: {len(diff)}")
    for k in diff[:10]: print(f"        {k}: old={ro.get(k)} new={rn.get(k)}")
    bad = sorted(k for k, v in rn.items() if v in ("FAIL", "ERROR"))
    if bad: print("      failing in both (pre-existing):" if ro == rn else "      failing in new:", *bad, sep="\n        ")
    print("\nPROVEN: same program" if ok else "\nNOT PROVEN")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
