#!/bin/bash
# 맥북용 — 수집(run_all.sh) → JSON 추출 → GitHub 푸시. 콘솔 발행은 하지 않는다(클라우드 06:50/13:10 라운드가 받아서 발행).
# launchd(com.kjoeul.weflo.collect)가 06:20·12:40 에 실행. 수동 실행: bash ~/Weflo/mybot/weflo-ops/mac/collect_and_push.sh
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
REPO="${WEFLO_REPO:-$HOME/Weflo/mybot}"
BRANCH="claude/document-app-conversion-ue7rgt"
LOG="$HOME/Weflo/logs/collect.log"; mkdir -p "$(dirname "$LOG")"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

wait_net(){ for i in $(seq 1 30); do curl -s -m 5 -o /dev/null https://www.g2b.go.kr && return 0; sleep 10; done; return 1; }

log "=== collect start ==="
wait_net || { log "ABORT: 네트워크 없음(g2b 접속 실패 5분)"; exit 1; }

# 1) 수집 — 기존 파이프라인 그대로
if [ -x "$HOME/Weflo/run_all.sh" ]; then
  caffeinate -i bash "$HOME/Weflo/run_all.sh" >>"$LOG" 2>&1 && log "run_all.sh OK" || { log "run_all.sh FAILED (exit $?) — 로그 위 참조"; }
else
  log "WARN: ~/Weflo/run_all.sh 없음 또는 실행권한 없음 (chmod +x ~/Weflo/run_all.sh)"
fi

# 2) JSON 추출 → 저장소
cd "$REPO" || { log "ABORT: 저장소 없음 $REPO — git clone -b $BRANCH https://github.com/kjoeul-png/mybot $REPO"; exit 1; }
git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --rebase origin "$BRANCH" || log "WARN: git pull 실패(계속 진행)"
python3 weflo-ops/mac/export_auto.py >>"$LOG" 2>&1 || { log "ABORT: export 실패"; exit 1; }

# 3) 변경 있으면 커밋·푸시
if git diff --quiet -- weflo-ops/data; then log "변경 없음 — 푸시 생략"; exit 0; fi
STAMP=$(python3 -c "import json;print(json.load(open('weflo-ops/data/auto.json'))['checked'])" 2>/dev/null || echo "?")
git add weflo-ops/data && git commit -q -m "자동수집 데이터 $STAMP (맥 collect_and_push)" && git push -q origin "$BRANCH" \
  && log "PUSHED auto.json checked=$STAMP" || log "ABORT: push 실패 — 맥의 GitHub 인증(gh auth login 또는 credential helper) 확인"
log "=== collect end ==="
