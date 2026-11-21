#!/bin/sh
# Pre-submission gate for the Mech Royale bot. Run from anywhere: sh scripts/gate.sh
# Exits non-zero if any required step fails. Kit location: $MECHFIGHT_KIT,
# else ./sim/kit, else ./mechfight-kit.

cd "$(dirname "$0")/.." || exit 2
FAILED=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILED=1; }

echo "== 1. Syntax =="
if python3 -c "import ast;ast.parse(open('bot.py').read())" && \
   python3 -m py_compile bot_v1.py mechfight.py; then
    pass "bot.py parses; bot_v1.py and mechfight.py compile"
else
    fail "syntax check"
fi
# py_compile leaves bytecode behind; it is ignored by git, but keep the tree tidy.
rm -rf __pycache__

echo "== 2. CONFIG =="
if grep -q '^CONFIG = {' bot.py; then
    pass "CONFIG present in bot.py"
    python3 - <<'EOF'
import ast
tree = ast.parse(open("bot.py").read())
cfg = None
for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "CONFIG" for t in node.targets):
        cfg = ast.literal_eval(node.value)
for k in ("legacy_strategy", "roofs", "hideouts", "stealth", "selective_fire", "react_unseen"):
    print("  %-16s = %s" % (k, cfg.get(k, "(absent)") if cfg is not None else "(CONFIG not a literal)"))
EOF
else
    fail "CONFIG not found in bot.py"
fi

echo "== 3. Kit conformance check =="
KIT="${MECHFIGHT_KIT:-}"
if [ -z "$KIT" ]; then
    if [ -d ./sim/kit ]; then KIT=./sim/kit; elif [ -d ./mechfight-kit ]; then KIT=./mechfight-kit; fi
fi
if [ -z "$KIT" ] || [ ! -f "$KIT/check/check.py" ] || [ ! -d "$KIT/arena" ]; then
    fail "kit not found (need check/check.py and arena/). Set MECHFIGHT_KIT=/path/to/mechfight-kit, or put it at ./sim/kit or ./mechfight-kit"
else
    if python3 "$KIT/check/check.py" --map-dir "$KIT/arena" -- python3 -u bot.py; then
        pass "check.py (local python)"
    else
        fail "check.py (local python)"
    fi
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        ARENA_ABS=$(cd "$KIT/arena" && pwd)
        if docker build -q -t mechroyale-gate . >/dev/null && \
           python3 "$KIT/check/check.py" --map-dir "$KIT/arena" -- \
               docker run -i --rm --network none --cpus 1 --memory 512m --read-only \
               --tmpfs /tmp:rw,size=64m --user 65534:65534 \
               -v "$ARENA_ABS":/arena:ro mechroyale-gate; then
            pass "check.py (sandboxed docker)"
        else
            fail "check.py (sandboxed docker)"
        fi
    else
        echo "SKIPPED: docker daemon unavailable"
    fi
fi

echo "== 4. Repo hygiene =="
SIZE=$(git ls-files -z | xargs -0 cat 2>/dev/null | wc -c | tr -d ' ')
if [ "$SIZE" -gt 20971520 ]; then
    fail "tracked files are $SIZE bytes (> 20 MB)"
else
    pass "tracked files are $SIZE bytes (<= 20 MB)"
fi
if [ -f bot_v1.py ]; then pass "bot_v1.py present"; else fail "bot_v1.py missing (bot.py imports it)"; fi
BAD=$(git ls-files | grep -E '(^|/)sim/out/|(^|/)__pycache__/' || true)
if [ -n "$BAD" ]; then
    fail "forbidden tracked files:"; echo "$BAD" | sed 's/^/  /'
else
    pass "no sim/out/ or __pycache__ files tracked"
fi

echo "== 5. Commit =="
echo "HEAD: $(git rev-parse HEAD)"
if [ -n "$(git status --porcelain)" ]; then
    echo "WARNING: working tree is dirty; commit and push before submitting, or the hash above is NOT what will be scored"
    git status --short | sed 's/^/  /'
else
    echo "Working tree clean."
fi

echo
if [ "$FAILED" -ne 0 ]; then echo "GATE: FAIL"; exit 1; fi
echo "GATE: PASS"
