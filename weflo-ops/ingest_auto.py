#!/usr/bin/env python3
"""클라우드 라운드용 — 맥 수집기가 푸시한 weflo-ops/data/{auto,contests}.json 을 콘솔 HTML의
`const AUTO=…;` / `const CONTESTS=…;` 한 줄에 주입한다. 라이브 값보다 새 수집(checked/generated)일 때만 교체.

사용:  python3 weflo-ops/ingest_auto.py <console.html> [--raw]
  --raw : 로컬 data/ 대신 GitHub raw(공개 저장소)에서 JSON을 받는다 (클라우드 세션에서 git pull 없이 쓸 때)
출력:  UPDATED <name> <old> -> <new>  /  NO-CHANGE <name> (<checked>)  /  MISSING <name>
"""
import io, json, re, sys, urllib.request, pathlib

RAW = "https://raw.githubusercontent.com/kjoeul-png/mybot/claude/document-app-conversion-ue7rgt/weflo-ops/data/"
HERE = pathlib.Path(__file__).resolve().parent
SPEC = [("AUTO", "auto.json", "checked"), ("CONTESTS", "contests.json", "generated")]

def load(fname, raw):
    if raw:
        with urllib.request.urlopen(RAW + fname, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    p = HERE / "data" / fname
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def main():
    if len(sys.argv) < 2: print(__doc__); sys.exit(2)
    html_path = pathlib.Path(sys.argv[1]); raw = "--raw" in sys.argv
    html = html_path.read_text(encoding="utf-8")
    changed = False
    for name, fname, stamp in SPEC:
        try: new = load(fname, raw)
        except Exception as e: print(f"MISSING {name} ({e})"); continue
        if not new: print(f"MISSING {name}"); continue
        m = re.search(r'^const ' + name + r'=(.*?);\s*$', html, re.M)
        if not m: print(f"MISSING {name} (const not found in html)"); continue
        cur = json.loads(m.group(1))
        old_stamp, new_stamp = str(cur.get(stamp, "")), str(new.get(stamp, ""))
        if new_stamp <= old_stamp:
            print(f"NO-CHANGE {name} ({old_stamp})"); continue
        line = "const " + name + "=" + json.dumps(new, ensure_ascii=False, separators=(", ", ": ")) + ";"
        html = html[:m.start()] + line + html[m.end():]
        changed = True
        print(f"UPDATED {name} {old_stamp} -> {new_stamp}" + (f" (feed {len(new.get('feed', []))}건)" if name == "AUTO" else f" (items {len(new.get('items', []))}건)"))
    if changed: html_path.write_text(html, encoding="utf-8")
    sys.exit(0)

if __name__ == "__main__": main()
