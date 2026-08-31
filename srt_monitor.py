"""
SRT 빈좌석 모니터링 모듈

- /srt 명령어로 모니터링 시작 → 지정한 시간대에 빈좌석이 나올 때까지 반복 조회
- 빈좌석 발견 시 즉시 예약(좌석 선점)하고 텔레그램으로 "결제할까요?" 버튼 전송
- 결제하기 버튼 → 등록된 카드로 결제 (카드 미등록 시 SRT 앱 결제 안내)
- 예약취소 버튼 → 선점한 좌석 취소

필요한 환경변수:
- SRT_ID: SRT 멤버십 번호 (또는 이메일/전화번호)
- SRT_PW: SRT 비밀번호
- SRT_ALLOWED_USER_ID: (권장) 이 텔레그램 유저 ID만 SRT 기능 사용 가능
- SRT_CHECK_INTERVAL: 조회 간격(초), 기본 10초

카드 자동결제를 쓰려면 (선택):
- SRT_CARD_NUMBER: 카드번호 (숫자만)
- SRT_CARD_PASSWORD: 카드 비밀번호 앞 2자리
- SRT_CARD_BIRTHDAY: 생년월일 6자리 (법인카드는 사업자번호 10자리)
- SRT_CARD_EXPIRE: 유효기간 YYMM
"""

import os
import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

try:
    from SRT import SRT
    from SRT.errors import SRTError
except ImportError:
    SRT = None
    SRTError = Exception

# ===== 환경변수 =====
SRT_ID = os.environ.get('SRT_ID')
SRT_PW = os.environ.get('SRT_PW')
SRT_ALLOWED_USER_ID = os.environ.get('SRT_ALLOWED_USER_ID')  # 미설정 시 모든 유저 허용
CHECK_INTERVAL = int(os.environ.get('SRT_CHECK_INTERVAL', 10))

CARD_NUMBER = os.environ.get('SRT_CARD_NUMBER')
CARD_PASSWORD = os.environ.get('SRT_CARD_PASSWORD')
CARD_BIRTHDAY = os.environ.get('SRT_CARD_BIRTHDAY')
CARD_EXPIRE = os.environ.get('SRT_CARD_EXPIRE')

# SRT 정차역 목록 (SRTrain 라이브러리 지원 역)
STATIONS = [
    "수서", "동탄", "평택지제", "경주", "곡성", "공주", "광주송정", "구례구",
    "김천구미", "나주", "남원", "대전", "동대구", "마산", "목포", "밀양",
    "부산", "서대구", "순천", "여수EXPO", "여천", "오송", "울산(통도사)",
    "익산", "전주", "정읍", "진영", "진주", "창원", "창원중앙", "천안아산", "포항",
]

# ===== 유저별 모니터링 상태 =====
# user_id -> {"task": asyncio.Task, "params": dict, "count": int,
#             "reservation": SRTReservation, "srt": SRT}
monitor_state = {}


def _check_allowed(user_id: str) -> bool:
    if not SRT_ALLOWED_USER_ID:
        return True
    return user_id == SRT_ALLOWED_USER_ID


def _login() -> "SRT":
    """SRT 로그인 (동기 - to_thread로 호출할 것)"""
    return SRT(SRT_ID, SRT_PW, verbose=False)


def _search_available(srt, dep, arr, date, time_start, time_end):
    """시간대 내 예약 가능한 열차 검색 (동기 - to_thread로 호출할 것)"""
    trains = srt.search_train(
        dep, arr, date, time_start + "00",
        available_only=False,
    )
    result = []
    for train in trains:
        # 출발시각이 지정한 시간대를 벗어나면 제외
        if train.dep_time > time_end + "59":
            continue
        if train.seat_available():
            result.append(train)
    return result


def _format_train(train) -> str:
    dep_t = f"{train.dep_time[:2]}:{train.dep_time[2:4]}"
    arr_t = f"{train.arr_time[:2]}:{train.arr_time[2:4]}"
    general = "O" if train.general_seat_available() else "X"
    special = "O" if train.special_seat_available() else "X"
    return (
        f"🚄 {train.train_name} {train.train_number}\n"
        f"🕐 {train.dep_station_name} {dep_t} → {train.arr_station_name} {arr_t}\n"
        f"💺 일반실: {general} / 특실: {special}"
    )


async def _monitor_loop(user_id: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """빈좌석이 나올 때까지 반복 조회 → 발견 시 예약 후 결제 여부 질문"""
    state = monitor_state[user_id]
    p = state["params"]

    try:
        srt = await asyncio.to_thread(_login)
        state["srt"] = srt
    except Exception as e:
        logger.error(f"SRT 로그인 실패: {e}")
        await context.bot.send_message(
            chat_id,
            f"😥 SRT 로그인에 실패했습니다.\nSRT_ID / SRT_PW 환경변수를 확인해주세요.\n\n{e}"
        )
        monitor_state.pop(user_id, None)
        return

    await context.bot.send_message(
        chat_id,
        f"🔍 모니터링을 시작합니다!\n\n"
        f"🚉 구간: {p['dep']} → {p['arr']}\n"
        f"📅 날짜: {p['date'][:4]}-{p['date'][4:6]}-{p['date'][6:]}\n"
        f"⏰ 시간대: {p['start'][:2]}:{p['start'][2:]} ~ {p['end'][:2]}:{p['end'][2:]}\n"
        f"🔄 조회 간격: {CHECK_INTERVAL}초\n\n"
        f"빈좌석이 나오면 바로 선점하고 알려드릴게요!\n"
        f"중단하려면 /srt_stop 을 입력하세요."
    )

    while True:
        try:
            trains = await asyncio.to_thread(
                _search_available, srt,
                p['dep'], p['arr'], p['date'], p['start'], p['end']
            )
        except SRTError as e:
            # 세션 만료 등 → 재로그인 후 재시도
            logger.warning(f"SRT 조회 오류(재로그인 시도): {e}")
            try:
                srt = await asyncio.to_thread(_login)
                state["srt"] = srt
            except Exception as e2:
                logger.error(f"SRT 재로그인 실패: {e2}")
            await asyncio.sleep(CHECK_INTERVAL)
            continue
        except Exception as e:
            logger.error(f"SRT 조회 오류: {e}")
            await asyncio.sleep(CHECK_INTERVAL)
            continue

        state["count"] += 1

        if trains:
            train = trains[0]  # 시간대 내 가장 빠른 열차
            try:
                reservation = await asyncio.to_thread(srt.reserve, train)
            except Exception as e:
                # 조회와 예약 사이에 좌석을 뺏긴 경우 → 계속 모니터링
                logger.warning(f"예약 실패(계속 모니터링): {e}")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            state["reservation"] = reservation

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 결제하기", callback_data="srt_pay"),
                InlineKeyboardButton("❌ 예약취소", callback_data="srt_cancel"),
            ]])
            await context.bot.send_message(
                chat_id,
                f"🎉 빈좌석을 찾아서 예약(선점)했습니다!\n\n"
                f"{_format_train(train)}\n"
                f"💰 요금: {reservation.total_cost:,}원\n\n"
                f"⚠️ 결제하지 않으면 약 10분 후 예약이 자동 취소됩니다.\n\n"
                f"💳 결제할까요?",
                reply_markup=keyboard,
            )
            state["task"] = None
            return  # 모니터링 종료 (예약 성공)

        # 조회 100회마다 생존 신고
        if state["count"] % 100 == 0:
            await context.bot.send_message(
                chat_id,
                f"🔄 아직 빈좌석이 없습니다. (조회 {state['count']}회)\n계속 모니터링 중..."
            )

        await asyncio.sleep(CHECK_INTERVAL)


# ===== /srt 명령어 =====
async def srt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if SRT is None:
        await update.message.reply_text(
            "😥 SRTrain 라이브러리가 설치되지 않았습니다.\n"
            "`pip install SRTrain` 후 다시 시도해주세요."
        )
        return

    if not _check_allowed(user_id):
        await update.message.reply_text("🚫 SRT 기능 사용 권한이 없습니다.")
        return

    if not SRT_ID or not SRT_PW:
        await update.message.reply_text(
            "⚙️ SRT 계정이 설정되지 않았습니다.\n"
            "SRT_ID, SRT_PW 환경변수를 설정해주세요."
        )
        return

    if user_id in monitor_state and monitor_state[user_id].get("task"):
        await update.message.reply_text(
            "⚠️ 이미 모니터링이 실행 중입니다.\n"
            "/srt_status 로 확인하거나 /srt_stop 으로 중단 후 다시 시작해주세요."
        )
        return

    # 인자 파싱: /srt 출발역 도착역 날짜(YYYYMMDD) 시작시각(HHMM) 종료시각(HHMM)
    args = context.args
    if len(args) != 5:
        await update.message.reply_text(
            "📌 사용법:\n"
            "/srt 출발역 도착역 날짜 시작시각 종료시각\n\n"
            "예시:\n"
            "/srt 수서 부산 20260905 1400 1800\n"
            "→ 9월 5일 14:00~18:00 사이 수서→부산 빈좌석 모니터링\n\n"
            f"🚉 지원 역: {', '.join(STATIONS)}"
        )
        return

    dep, arr, date, start, end = args

    # 입력 검증
    errors = []
    if dep not in STATIONS:
        errors.append(f"출발역 '{dep}'을(를) 찾을 수 없습니다.")
    if arr not in STATIONS:
        errors.append(f"도착역 '{arr}'을(를) 찾을 수 없습니다.")
    if not (date.isdigit() and len(date) == 8):
        errors.append("날짜는 YYYYMMDD 형식 8자리로 입력해주세요. 예) 20260905")
    if not (start.isdigit() and len(start) == 4 and start[:2] < "24" and start[2:] < "60"):
        errors.append("시작시각은 HHMM 형식 4자리로 입력해주세요. 예) 1400")
    if not (end.isdigit() and len(end) == 4 and end[:2] < "24" and end[2:] < "60"):
        errors.append("종료시각은 HHMM 형식 4자리로 입력해주세요. 예) 1800")
    if not errors and start >= end:
        errors.append("종료시각은 시작시각보다 늦어야 합니다.")
    if errors:
        await update.message.reply_text("😥 입력 오류:\n" + "\n".join(f"- {e}" for e in errors))
        return

    monitor_state[user_id] = {
        "params": {"dep": dep, "arr": arr, "date": date, "start": start, "end": end},
        "count": 0,
        "reservation": None,
        "srt": None,
        "task": None,
    }
    task = asyncio.create_task(
        _monitor_loop(user_id, update.effective_chat.id, context)
    )
    monitor_state[user_id]["task"] = task


# ===== /srt_stop 명령어 =====
async def srt_stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    state = monitor_state.get(user_id)

    if not state:
        await update.message.reply_text("ℹ️ 실행 중인 모니터링이 없습니다.")
        return

    task = state.get("task")
    if task and not task.done():
        task.cancel()

    if state.get("reservation"):
        await update.message.reply_text(
            "🛑 모니터링을 중단했습니다.\n"
            "⚠️ 선점된 예약이 남아있습니다. 결제하지 않으면 자동 취소됩니다."
        )
    else:
        monitor_state.pop(user_id, None)
        await update.message.reply_text("🛑 모니터링을 중단했습니다.")


# ===== /srt_status 명령어 =====
async def srt_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    state = monitor_state.get(user_id)

    if not state:
        await update.message.reply_text("ℹ️ 실행 중인 모니터링이 없습니다.\n/srt 명령어로 시작하세요!")
        return

    p = state["params"]
    task = state.get("task")
    if task and not task.done():
        status = "🔄 모니터링 중"
    elif state.get("reservation"):
        status = "🎫 예약 완료 (결제 대기)"
    else:
        status = "⏹ 중단됨"

    await update.message.reply_text(
        f"{status}\n\n"
        f"🚉 구간: {p['dep']} → {p['arr']}\n"
        f"📅 날짜: {p['date'][:4]}-{p['date'][4:6]}-{p['date'][6:]}\n"
        f"⏰ 시간대: {p['start'][:2]}:{p['start'][2:]} ~ {p['end'][:2]}:{p['end'][2:]}\n"
        f"🔢 조회 횟수: {state['count']}회"
    )


# ===== 결제/취소 버튼 처리 =====
async def srt_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    await query.answer()

    state = monitor_state.get(user_id)
    if not state or not state.get("reservation"):
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            query.message.chat_id,
            "ℹ️ 처리할 예약이 없습니다. (이미 처리되었거나 만료됨)"
        )
        return

    srt = state["srt"]
    reservation = state["reservation"]

    if query.data == "srt_cancel":
        try:
            await asyncio.to_thread(srt.cancel, reservation)
            state["reservation"] = None
            monitor_state.pop(user_id, None)
            await query.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(query.message.chat_id, "❌ 예약을 취소했습니다.")
        except Exception as e:
            logger.error(f"예약 취소 오류: {e}")
            await context.bot.send_message(
                query.message.chat_id,
                f"😥 예약 취소 중 오류가 발생했습니다.\nSRT 앱에서 직접 확인해주세요.\n\n{e}"
            )
        return

    if query.data == "srt_pay":
        # 카드 정보가 없으면 앱 결제 안내
        if not all([CARD_NUMBER, CARD_PASSWORD, CARD_BIRTHDAY, CARD_EXPIRE]):
            await query.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(
                query.message.chat_id,
                "💳 자동결제용 카드가 등록되어 있지 않습니다.\n\n"
                "📱 SRT 앱 → 승차권 확인 에서 10분 내에 직접 결제해주세요!\n\n"
                "(자동결제를 원하시면 SRT_CARD_NUMBER, SRT_CARD_PASSWORD, "
                "SRT_CARD_BIRTHDAY, SRT_CARD_EXPIRE 환경변수를 설정하세요)"
            )
            return

        try:
            await asyncio.to_thread(
                srt.pay_with_card,
                reservation,
                number=CARD_NUMBER,
                password=CARD_PASSWORD,
                validation_number=CARD_BIRTHDAY,
                expire_date=CARD_EXPIRE,
            )
            state["reservation"] = None
            monitor_state.pop(user_id, None)
            await query.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(
                query.message.chat_id,
                "✅ 결제 완료! 🎫\n즐거운 여행 되세요! 🚄\n"
                "승차권은 SRT 앱에서 확인할 수 있습니다."
            )
        except Exception as e:
            logger.error(f"결제 오류: {e}")
            await context.bot.send_message(
                query.message.chat_id,
                f"😥 결제 중 오류가 발생했습니다.\n"
                f"📱 SRT 앱에서 직접 결제해주세요! (예약은 유지 중)\n\n{e}"
            )
