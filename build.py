#!/usr/bin/env python3
"""Build `reveille` (the single installable file) from the layered fragments in src/.

  python3 build.py            write ./reveille
  python3 build.py --check    change nothing; fail if ./reveille is not exactly what src/ builds
  python3 build.py -o PATH    write somewhere else

The fragments src/NN_name.py are joined in file-name order, byte for byte. Leading lines that start
with "#:" are notes for the reader of the fragment and are left out of the output.

Layer rule: a fragment may use module-level names defined in its own layer or in a lower one (a smaller
NN), never in a higher one. Imports and constants are layer 00 and 01. The build refuses to write when
the rule is broken, when a name is defined in two fragments, or when the result does not compile.
Only the standard library is used, and nothing in src/ is run: it is parsed.
"""
import argparse, os, re, symtable, sys, tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAGMENT = re.compile(r"\d\d_[a-z0-9_]+\.py")


def fragments(src_dir):
    """[(file name, text)] in layer order, notes removed. The numbers must be 00, 01, 02... with no gap."""
    names = sorted(n for n in os.listdir(src_dir) if FRAGMENT.fullmatch(n))
    if [int(n[:2]) for n in names] != list(range(len(names))):
        raise ValueError(f"fragments must be numbered 00, 01, ... without gaps, found: {names}")
    out = []
    for n in names:
        with open(os.path.join(src_dir, n), newline="") as f: lines = f.read().splitlines(keepends=True)
        i = 0
        while i < len(lines) and lines[i].startswith("#:"): i += 1
        out.append((n, "".join(lines[i:])))
    return out


def scopes(name, text):
    """(names bound at module level, module-level names the fragment looks up). Resolved by symtable, so a
    local variable that happens to share a name with a module-level one is not counted as a use of it."""
    top = symtable.symtable(text, name, "exec")
    bound = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    used, todo = set(), [top]
    while todo:
        t = todo.pop()
        todo += t.get_children()
        for s in t.get_symbols():
            if (t is top and s.is_referenced()) or (t is not top and s.is_global() and (s.is_referenced() or s.is_assigned())):
                used.add(s.get_name())
    return bound, used


def problems(frags):
    """Everything that is wrong with the fragments, as readable lines (empty if all is well)."""
    out, home, info = [], {}, []
    for layer, (name, text) in enumerate(frags):
        try: bound, used = scopes(name, text)
        except SyntaxError as e:
            out.append(f"{name}: does not parse on its own: {e.msg} (line {e.lineno})"); continue
        info.append((layer, name, bound, used))
        for n in bound:
            if n in home and home[n][1] != layer:
                out.append(f"{n} is defined in both {frags[home[n][1]][0]} and {name}")
            home.setdefault(n, (name, layer))
    for layer, name, bound, used in info:
        for n in sorted(used - bound):
            if n in home and home[n][1] > layer:
                out.append(f"{name} (layer {layer:02d}) uses {n}, which is defined in {home[n][0]} (layer {home[n][1]:02d})")
    return out


def build(src_dir):
    """(text of the built file, list of problems). The text is None if the fragments can't be joined."""
    frags = fragments(src_dir)
    bad = problems(frags)
    text = "".join(t for _, t in frags)
    try: compile(text, "reveille", "exec")
    except SyntaxError as e: bad.append(f"the joined file does not compile: {e.msg} (line {e.lineno})")
    return text, bad


def write_atomic(path, text, mode):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".build-")
    try:
        with os.fdopen(fd, "w", newline="") as f: f.write(text)
        os.chmod(tmp, mode); os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build reveille from src/.")
    ap.add_argument("--check", action="store_true", help="write nothing; fail if the built file is out of date")
    ap.add_argument("-o", "--output", default=os.path.join(ROOT, "reveille"), help="where to write (default: ./reveille)")
    args = ap.parse_args(argv)
    try: text, bad = build(os.path.join(ROOT, "src"))
    except (OSError, ValueError) as e:
        print(f"build: {e}", file=sys.stderr); return 1
    for line in bad: print(f"build: {line}", file=sys.stderr)
    if bad: return 1
    try:
        with open(args.output, newline="") as f: current = f.read()
    except OSError: current = None
    if args.check:
        if current == text: print(f"{args.output} is up to date"); return 0
        print(f"build: {args.output} is not what src/ builds. Run: python3 build.py", file=sys.stderr); return 1
    mode = os.stat(args.output).st_mode & 0o7777 if current is not None else 0o755
    if current != text: write_atomic(args.output, text, mode)
    print(f"{args.output}: {'written' if current != text else 'already up to date'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
