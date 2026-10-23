#!/usr/bin/env python3
"""맥 수집기용 — update_console.py 가 만든 로컬 콘솔 HTML에서 `const AUTO=…;` / `const CONTESTS=…;` 를 뽑아
이 저장소의 weflo-ops/data/auto.json, contests.json 으로 저장한다. (콘솔 발행은 클라우드 라운드가 맡는다)

사용:  python3 export_auto.py [소스 HTML 경로]
  경로 생략 시 ~/Weflo 아래에서 'const AUTO=' 를 포함한 가장 최근 수정 HTML을 자동 선택한다.
"""
import io, json, re, sys, pathlib, time

HOME = pathlib.Path.home()
OUT = pathlib.Path(__file__).resolve().parent.parent / "data"

def find_source():
    cands = []
    for p in (HOME / "Weflo").rglob("*.html"):
        try:
            if p.stat().st_size > 50_000 and "const AUTO=" in p.read_text(encoding="utf-8", errors="ignore"):
                cands.append(p)
        except Exception: pass
    if not cands: sys.exit("ERROR: ~/Weflo 아래에 'const AUTO='를 가진 HTML이 없습니다 — run_all.sh 가 먼저 성공해야 합니다")
    return max(cands, key=lambda p: p.stat().st_mtime)

def main():
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else find_source()
    html = src.read_text(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fname in (("AUTO", "auto.json"), ("CONTESTS", "contests.json")):
        m = re.search(r'^const ' + name + r'=(.*?);\s*$', html, re.M)
        if not m: print(f"SKIP {name} (not found in {src})"); continue
        obj = json.loads(m.group(1))
        (OUT / fname).write_text(json.dumps(obj, ensure_ascii=False, indent=None), encoding="utf-8")
        stamp = obj.get("checked") or obj.get("generated")
        print(f"EXPORT {name} <- {src.name} ({stamp}) -> {OUT / fname}")

if __name__ == "__main__": main()
