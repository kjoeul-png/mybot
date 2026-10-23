# 맥북 자동수집 → 클라우드 콘솔 연결 (설치 3단계)

왜 필요한가: 수집기(collect_*.py, run_all.sh, update_console.py)는 맥북 ~/Weflo 에만 있고, 클라우드 세션은 나라장터·D2B·기업마당 등 수집 호스트가 네트워크 정책으로 차단돼 있다.
그래서 **맥은 수집한 결과(JSON)만 GitHub에 올리고**, 콘솔 발행은 클라우드 06:50·13:10 라운드가 `weflo-ops/ingest_auto.py`로 받아서 한다. 맥에서 콘솔을 직접 발행하던 경로(Weflo bid watch 세션)는 더 이상 쓰지 않는다.

## 1) 저장소를 맥에 받기 (최초 1회)
```bash
git clone -b claude/document-app-conversion-ue7rgt https://github.com/kjoeul-png/mybot ~/Weflo/mybot
```
(푸시 권한: 터미널에서 한 번 `git push`가 되는 상태여야 한다 — 안 되면 `gh auth login` 또는 GitHub 토큰으로 credential helper 설정)

## 2) 한 번 손으로 돌려보기
```bash
bash ~/Weflo/mybot/weflo-ops/mac/collect_and_push.sh
tail -20 ~/Weflo/logs/collect.log
```
`PUSHED auto.json checked=2026-..` 가 찍히면 성공. 다음 클라우드 라운드(06:50/13:10)가 콘솔에 반영한다.

## 3) 자동 실행 등록 (06:20·12:40)
```bash
sed "s#REPLACE_ME#$USER#g" ~/Weflo/mybot/weflo-ops/mac/com.kjoeul.weflo.collect.plist > ~/Library/LaunchAgents/com.kjoeul.weflo.collect.plist
launchctl unload ~/Library/LaunchAgents/com.kjoeul.weflo.collect.plist 2>/dev/null; launchctl load ~/Library/LaunchAgents/com.kjoeul.weflo.collect.plist
launchctl list | grep weflo
```
맥북이 잠들어 있으면 launchd는 그 시각에 실행하지 못한다 → 시스템 설정 > 배터리/에너지에서 "전원 연결 시 잠자기 방지" 또는 뚜껑 닫힘 잠자기 해제, 혹은 `sudo pmset repeat wakeorpoweron MTWRFSU 06:15:00` 로 깨우기 예약.

## 점검
- 수집기 자체 실패: `tail -50 ~/Weflo/logs/collect.log` (run_all.sh 오류 메시지가 그대로 남는다)
- 콘솔 반영 여부: 콘솔 00 탭 "마지막 수집" 시각
