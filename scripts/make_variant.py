"""Rewrite CONFIG values in bot.py without hand-editing.

Only the named keys' values inside the CONFIG dict change; every other byte stays the same.

Examples (variants from EXPERIMENTS.md; start from E, the v2 all-on file with legacy_strategy=False):
    # F: roofs off
    python3 scripts/make_variant.py --set roofs=False
    # G: roofs, hideouts and selective_fire off
    python3 scripts/make_variant.py --set roofs=False --set hideouts=False --set selective_fire=False

Show the current switches:
    python3 scripts/make_variant.py --show
"""
import argparse
import ast
import difflib
import re
import sys

SWITCHES = ("legacy_strategy", "stealth", "hideouts", "roofs", "selective_fire", "evasion",
            "safe_loot", "drops", "upgrades", "endgame", "stuck_recovery", "npc_farm", "react_unseen")


def config_span(text):
    start = re.search(r"^CONFIG = \{", text, re.M)
    if not start:
        sys.exit("error: 'CONFIG = {' not found")
    end = text.find("\n}", start.end())
    if end < 0:
        sys.exit("error: end of CONFIG dict not found")
    return start.end(), end


def value_re(key):
    # "key": value   where value runs to the next comma, closing brace or newline
    return re.compile(r'("%s"\s*:\s*)([^,\n}]+?)(\s*(?:,|\n|$))' % re.escape(key))


def literal(s, what):
    try:
        return ast.literal_eval(s.strip())
    except (ValueError, SyntaxError):
        sys.exit("error: %s is not a Python literal: %r" % (what, s))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--file", default="bot.py", help="input file (default bot.py)")
    ap.add_argument("--out", help="output file (default: overwrite --file)")
    ap.add_argument("--show", action="store_true", help="print current switch values")
    args = ap.parse_args()

    with open(args.file, newline="") as f:
        text = f.read()
    lo, hi = config_span(text)
    cfg = literal(text[lo - 1:hi + 2], "CONFIG")

    if args.show:
        for k in SWITCHES:
            print("%-16s = %s" % (k, cfg.get(k, "(absent)")))
        if not args.set:
            return

    body = text[lo:hi]
    for item in args.set:
        if "=" not in item:
            sys.exit("error: --set needs KEY=VALUE, got %r" % item)
        key, val = item.split("=", 1)
        key, val = key.strip(), val.strip()
        new_val = literal(val, "value for %s" % key)
        matches = list(value_re(key).finditer(body))
        if len(matches) != 1:
            sys.exit("error: key %r found %d times in CONFIG (need exactly 1)" % (key, len(matches)))
        m = matches[0]
        old_val = literal(m.group(2), "current value of %s" % key)
        numeric = (int, float)
        same_kind = (type(old_val) is type(new_val)) or (
            not isinstance(old_val, bool) and not isinstance(new_val, bool)
            and isinstance(old_val, numeric) and isinstance(new_val, numeric))
        if not same_kind:
            sys.exit("error: %s is %r (%s); refusing to set %r (%s)" % (key, old_val, type(old_val).__name__,
                                                                         new_val, type(new_val).__name__))
        body = body[:m.start(2)] + repr(new_val) + body[m.end(2):]

    new_text = text[:lo] + body + text[hi:]
    ast.parse(new_text)  # never write a file that does not parse
    out = args.out or args.file
    diff = list(difflib.unified_diff(text.splitlines(), new_text.splitlines(), args.file, out, n=0, lineterm=""))
    print("\n".join(diff) if diff else "no change")
    with open(out, "w", newline="") as f:
        f.write(new_text)


if __name__ == "__main__":
    main()
