import os
import logging
import anthropic
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# ===== 로깅 설정 =====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== 환경변수 =====
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')  # Render.com에서 제공하는 URL
PORT = int(os.environ.get('PORT', 8443))

# ===== Claude 클라이언트 =====
claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# ===== 대화 기록 (유저별 저장) =====
conversation_history = {}

# ===== 시스템 프롬프트 =====
SYSTEM_PROMPT = """당신은 유능하고 친절한 AI 어시스턴트입니다.
- 한국어로 대답해주세요
- 텔레그램에서 읽기 좋게 간결하고 명확하게 작성해주세요
- 파일 분석, 정보 검색, 번역, 요약 등 다양한 업무를 도와주세요
- 이모지를 적절히 사용해서 가독성을 높여주세요"""


# ===== /start 명령어 =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "안녕하세요! Claude AI 봇입니다 🤖\n\n"
        "📌 사용 가능한 기능:\n"
        "💬 메시지 입력 → Claude와 자유 대화\n"
        "📄 파일 전송 → 파일 내용 분석/요약\n"
        "🖼 사진 전송 → 이미지 설명 요청 가능\n"
        "🔍 /search [검색어] → 정보 검색 및 요약\n"
        "🗑 /clear → 대화 기록 초기화\n"
        "❓ /help → 도움말 보기\n\n"
        "무엇이든 물어보세요! 😊"
    )


# ===== /help 명령어 =====
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 도움말\n\n"
        "✅ 자유 대화: 메시지를 보내면 Claude가 답변\n"
        "✅ 파일 분석: 텍스트 파일(.txt, .csv, .py 등) 전송 시 내용 분석\n"
        "✅ 검색 요약: /search 날씨 또는 최신 뉴스 등\n"
        "✅ 번역: '다음을 영어로 번역해줘: ...' 형식으로 요청\n"
        "✅ 대화 초기화: /clear 입력\n\n"
        "💡 팁: 파일을 보낼 때 캡션으로 지시사항을 함께 적어주세요!\n"
        "예) '이 파일을 요약해줘', '오류를 찾아줘'"
    )


# ===== 일반 텍스트 메시지 처리 =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_text = update.message.text

    # 대화 기록 초기화
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    # 유저 메시지 추가
    conversation_history[user_id].append({
        "role": "user",
        "content": user_text
    })

    # 타이핑 표시
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        response = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=conversation_history[user_id]
        )

        reply = response.content[0].text

        # 어시스턴트 응답 기록 추가
        conversation_history[user_id].append({
            "role": "assistant",
            "content": reply
        })

        # 대화 기록 최대 20개로 제한 (메모리 관리)
        if len(conversation_history[user_id]) > 20:
            conversation_history[user_id] = conversation_history[user_id][-20:]

        # 텔레그램 메시지 길이 제한(4096자) 처리
        if len(reply) > 4000:
            chunks = [reply[i:i+4000] for i in range(0, len(reply), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"메시지 처리 오류: {e}")
        await update.message.reply_text(f"😥 오류가 발생했습니다.\n{str(e)}")


# ===== 파일(문서) 처리 =====
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    document = update.message.document
    caption = update.message.caption or "이 파일을 분석하고 주요 내용을 요약해주세요."

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        # 파일 다운로드
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()

        # 텍스트 파일 시도
        try:
            text_content = file_bytes.decode('utf-8')
            # 너무 길면 앞부분만
            if len(text_content) > 4000:
                text_content = text_content[:4000] + "\n\n[파일이 길어 앞부분만 표시됩니다]"
            file_info = f"📄 파일명: {document.file_name}\n\n내용:\n{text_content}"
        except UnicodeDecodeError:
            file_info = f"📄 파일명: {document.file_name}\n(바이너리 파일 - 텍스트 추출 불가)"

        if user_id not in conversation_history:
            conversation_history[user_id] = []

        conversation_history[user_id].append({
            "role": "user",
            "content": f"{caption}\n\n[첨부 파일]\n{file_info}"
        })

        response = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=conversation_history[user_id]
        )

        reply = response.content[0].text

        conversation_history[user_id].append({
            "role": "assistant",
            "content": reply
        })

        await update.message.reply_text(f"📄 파일 분석 결과:\n\n{reply}")

    except Exception as e:
        logger.error(f"파일 처리 오류: {e}")
        await update.message.reply_text(f"😥 파일 처리 중 오류가 발생했습니다.\n{str(e)}")


# ===== 사진 처리 =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.caption or ""
    await update.message.reply_text(
        "📸 사진을 받았습니다!\n\n"
        "현재 버전에서는 이미지 직접 분석이 제한됩니다.\n"
        "사진에 대해 궁금한 점을 텍스트로 설명해주시면 도와드릴게요! 😊"
    )


# ===== /search 명령어 =====
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🔍 검색어를 입력해주세요!\n예시: /search 파이썬 비동기 프로그래밍"
        )
        return

    query = ' '.join(context.args)
    user_id = str(update.effective_user.id)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({
        "role": "user",
        "content": f"다음 주제에 대해 자세히 설명하고 핵심 정보를 정리해주세요: {query}"
    })

    try:
        response = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=conversation_history[user_id]
        )

        reply = response.content[0].text

        conversation_history[user_id].append({
            "role": "assistant",
            "content": reply
        })

        await update.message.reply_text(f"🔍 '{query}' 검색 결과:\n\n{reply}")

    except Exception as e:
        logger.error(f"검색 오류: {e}")
        await update.message.reply_text(f"😥 검색 중 오류가 발생했습니다.\n{str(e)}")


# ===== /clear 명령어 =====
async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    conversation_history[user_id] = []
    await update.message.reply_text("🗑 대화 기록이 초기화되었습니다!")


# ===== 메인 실행 =====
def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN 환경변수가 설정되지 않았습니다!")
    if not CLAUDE_API_KEY:
        raise ValueError("CLAUDE_API_KEY 환경변수가 설정되지 않았습니다!")

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Render.com 배포 시 Webhook 모드 / 로컬 테스트 시 Polling 모드
    if WEBHOOK_URL:
        logger.info(f"Webhook 모드로 실행 중... PORT: {PORT}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}"
        )
    else:
        logger.info("Polling 모드로 실행 중...")
        application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
