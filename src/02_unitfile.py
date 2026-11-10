#: layer 02: unit-file text: escaping, reading, merge-rewrite, atomic write
# ---------------------------------------------------------------- unit files
def esc(s):                       # "%" is special in unit files
    return s.replace("%", "%%")

def unesc(s):
    return s.replace("%%", "%")

def xesc(s):                      # in ExecStart "$" is special too
    return esc(s).replace("$", "$$")

def xunesc(s):
    return unesc(s.replace("$$", "$"))

def unit_path(unit):
    return os.path.realpath(f"{UNITS}/{unit}")

def read_text(path):
    try:
        with open(path) as f: return f.read()
    except OSError:
        return ""

def groups(text):
    """Split a unit file into logical lines: a line ending in a backslash continues on the next one."""
    out, cur = [], []
    for l in text.splitlines():
        cur.append(l)
        if not l.rstrip().endswith("\\"):
            out.append(cur); cur = []
    if cur: out.append(cur)
    return out

def joined(g):
    return " ".join((x.rstrip()[:-1] if i < len(g) - 1 else x).strip() for i, x in enumerate(g))

def read_unit(path):
    """{section: {key: [values]}} or None if the file can't be read."""
    try:
        with open(path) as f: text = f.read()
    except OSError:
        return None
    out, sect = {}, None
    for g in groups(text):
        st = joined(g).strip()
        if not st or st[0] in "#;": continue
        if st.startswith("["): sect = st.strip("[]"); out.setdefault(sect, {}); continue
        if sect is not None and "=" in st:
            k, v = st.split("=", 1); out[sect].setdefault(k.strip(), []).append(v.strip())
    return out

def merge_unit(text, spec):
    """Rewrite only the lines the editor manages and keep every other line, comment and section as it was.
    spec = {section: (managed keys, new lines, keep)}: lines of a managed key are dropped unless keep(key, value)
    says to keep that one, and the new lines go where the first dropped line was (or at the end of the section)."""
    out, sect, slot, end, seen = [], None, {}, {}, set()
    def close():
        if sect is not None:
            j = len(out)
            while j > 0 and not out[j - 1].strip(): j -= 1
            end[sect] = j
    for g in groups(text):
        st = joined(g).strip()
        if st.startswith("[") and "]" in st:
            close(); sect = st[1:st.index("]")]; seen.add(sect); out += g; continue
        if sect in spec and "=" in st and st[0] not in "#;":
            k, v = (x.strip() for x in st.split("=", 1))
            managed, _, keep = spec[sect]
            if k in managed and not keep(k, v):
                slot.setdefault(sect, len(out)); continue
        out += g
    close()
    ins = [(slot.get(s, end.get(s)), new) for s, (_, new, _) in spec.items() if new and s in seen]
    for i, lines in sorted(ins, key=lambda x: -x[0]): out[i:i] = lines
    for s, (_, new, _) in spec.items():
        if new and s not in seen: out += ([""] if out else []) + [f"[{s}]"] + new
    return "\n".join(out) + "\n"

def write_atomic(path, text):
    """Write a file so a crash or full disk never leaves a half-written unit. A symlink is followed: the file
    it points to is replaced, the link stays."""
    path = os.path.realpath(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".reveille-")
    try:
        with os.fdopen(fd, "w") as f: f.write(text)
        try: os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except OSError: os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

