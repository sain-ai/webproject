from fastapi import FastAPI, HTTPException, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from contextlib import contextmanager
import sqlite3
import os
import requests
import base64

app = FastAPI(title="AlbaCare Full Stack Gemini Server")

# ==========================================================
# 🌐 CORS 설정 (프론트엔드 정적 사이트 통신 허용)
# ==========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = os.path.join(os.getcwd(), "albacare.db")

# 💡 Google AI Studio에서 발급받은 실제 Gemini API Key를 세팅하는 구역입니다.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==========================================================
# 💾 SQLite Connection 관리 에이전트 (with문 전용)
# ==========================================================
@contextmanager
def get_db():
    """DB가 잠기거나 커넥션이 열려있지 않도록 자동으로 열고 닫아주는 안전장치입니다."""
    conn = sqlite3.connect(DB_FILE, timeout=15.0) # 안전을 위해 대기 타임아웃을 15초로 확장
    try:
        yield conn
    finally:
        conn.close()

# ==========================================================
# 💾 데이터베이스 초기화 로직
# ==========================================================
def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        # 1. 회원 정보 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        # 2. 상담 내역 저장용 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                message TEXT NOT NULL,
                reply TEXT NOT NULL,
                created_at DATETIME DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.commit()

init_db()

# ==========================================================
# 🔑 데이터 모델 규격
# ==========================================================
class SignUpRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ChatMessageRequest(BaseModel):
    message: str

# ==========================================================
# 🚀 기본 라우트 (서버 구동 점검용)
# ==========================================================
@app.get("/")
def read_root():
    return {"status": "running", "message": "AlbaCare Gemini AI API Server is fully operational!"}

# ==========================================================
# 🔐 회원관리 엔드포인트
# ==========================================================
@app.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user_data: SignUpRequest):
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", (user_data.name, user_data.email, user_data.password))
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미 가입된 이메일입니다.")
    return {"message": "회원가입이 완료되었습니다."}

@app.post("/login")
def login(credentials: LoginRequest):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, email, password FROM users WHERE email = ?", (credentials.email,))
        user = cursor.fetchone()
    if not user or user[2] != credentials.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="이메일 또는 비밀번호가 일치하지 않습니다.")
    return {"message": "로그인 성공", "user": {"name": user[0], "email": user[1]}}

# ==========================================================
# 🔍 1. 계약서 이미지 & PDF 분석 API 엔드포인트
# ==========================================================
@app.post("/analyze")
async def analyze_contract(
    file: UploadFile = File(...),
    task_type: str = Form(...)
):
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in ['.jpg', '.jpeg', '.png', '.pdf']:
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. (JPG, PNG, PDF만 가능)")

    if not GEMINI_API_KEY or "여기에_" in GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="서버에 Gemini API Key가 설정되지 않았습니다.")

    file_bytes = await file.read()
    
    validation_rule = (
        "[경고 - 가장 중요한 절대 규칙]\n"
        "제공된 파일이 '근로계약서' 혹은 '고용계약서'와 관련된 공식 문서가 아니거나, "
        "화질이 너무 깨져서 글자를 판독할 수 없는 엉뚱한 사진(치킨 사진, 풍경, 영수증 등)인 경우, "
        "아래 지시 사항들을 모두 전부 전면 무시하고 오직 정확히 다음 한 문장만 답변으로 출력해라:\n"
        "❌ 분석 불가한 파일입니다. 올바른 근로계약서 사진이나 PDF 파일을 업로드해 주세요.\n\n"
        "만약 정상적인 근로계약서 서류가 맞다면, 아래의 조건 유형에 따라 정밀 분석을 진행해줘.\n"
        "-------------------------------------\n"
    )

    if task_type == "photo_detail":
        prompt = validation_rule + (
            "너는 근로기준법을 마스터한 20년 경력의 베테랑 전문 노무사야. "
            "지금 제공하는 알바 근로계약서 파일을 정밀하게 판독해서 아주 상세하고 친절한 리포트를 작성해줘. "
            "반드시 다음 사항들을 꼼꼼하게 짚어내야 해:\n"
            "1. 최저임금(2026년 기준 시급 10,300원) 준수 여부 및 주휴수당 지급 조건 명시 여부\n"
            "2. 소정근로시간, 휴게시간(4시간당 30분) 조건의 법적 타당성\n"
            "3. 알바생에게 일방적으로 불리한 독소 조항(무단 결근 시 임의 벌금, 무리한 위약금 설정 등)\n"
            "4. 이 계약서에 서명해도 안전한지 최종 노무사 총평과 수정이 필요한 문구 가이드"
        )
    elif task_type == "risk_check":
        prompt = validation_rule + (
            "너는 법적 위험 요소를 잡아내는 AI 위험 스캔 검사기야. 이 근로계약서에서 오직 '위법 소지가 있는 위험 조항'들만 "
            "빠르고 보기 좋게 요약 리스트로 뽑아줘. 최저임금 위반, 주휴수당 미지급 조건, 불법 벌금 조항 등이 있다면 "
            "그 항목과 법적 근거(근로기준법 몇 조 위반인지)만 핵심 요약식으로 정리해서 알려줘."
        )
    elif task_type == "summary":
        prompt = validation_rule + (
            "너는 어려운 법률 용어를 쉬운 말로 바꿔주는 친절한 요약 요정이야. 이 근로계약서의 복잡한 내용을 다 제외하고, "
            "알바생이 무조건 인지해야 하는 핵심 요약(시급은 얼마인지, 일주일에 몇 시간 일하는지, 언제 돈 주는지 등)만 "
            "가장 보기 편하게 딱 3~5줄 내외로 아주 쉽게 요약해줘."
        )
    else:
        prompt = validation_rule + "이 근로계약서를 분석하고 주요 근로 조건을 설명해줘."

    mime_type = "image/jpeg"
    if file_extension == ".png": mime_type = "image/png"
    elif file_extension == ".pdf": mime_type = "application/pdf"

    base64_data = base64.b64encode(file_bytes).decode("utf-8")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64_data
                    }
                }
            ]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response_json = response.json()
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Gemini API 에러: {response_json.get('error', {}).get('message', '알 수 없는 오류')}")
            
        ai_result = response_json['candidates'][0]['content']['parts'][0]['text']
        return {"result": ai_result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 내부 문서 분석 에러: {str(e)}")


# ==========================================================
# 💬 2. 실시간 1:1 AI 노무사 상담 채팅 엔드포인트
# ==========================================================
@app.post("/chat")
def chat_with_labor_attorney(
    request: ChatMessageRequest, 
    user_email: str = None
):
    if not GEMINI_API_KEY or "여기에_" in GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="서버에 Gemini API Key가 설정되지 않았습니다.")

    if not user_email:
        raise HTTPException(status_code=422, detail="user_email 파라미터가 누락되었습니다.")

    chat_prompt = (
        "너는 대한민국 근로기준법을 완벽하게 숙지한 친절하고 든든한 '알바 전문 AI 노무사'야. "
        "주로 대학생이나 청소년 아르바이트생들이 억울한 일(임금체불, 부당해고, 갑질 등)을 당해 물어볼 거야. "
        "다음 규칙을 절대적으로 지키며 친근하게 답변해줘:\n"
        "1. 질문자가 처한 힘든 상황에 진심으로 깊이 공감해주고 달래주며 답변을 시작해라.\n"
        "2. 관련된 근로기준법 조항(주휴수당 지급 조건, 해고예고수당 등)을 바탕으로 명확하게 불법 유무를 판단해줘.\n"
        "3. 사장님에게 기죽지 않고 보낼 수 있는 구체적인 대처 대화 예시 문구나 고용노동부 신고 요령 등의 행동 지침을 알려줘.\n"
        "4. 너무 딱딱하고 어려운 전문 법률 용어는 쉽게 풀어서 상냥하고 든든한 어조로 설명해라."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [{
            "parts": [
                {"text": chat_prompt},
                {"text": f"알바생의 질문 내용: {request.message}"}
            ]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response_json = response.json()
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Gemini 대화 API 통신 에러")
            
        ai_reply = response_json['candidates'][0]['content']['parts'][0]['text']

        # 안전하게 DB 저장
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO chat_history (user_email, message, reply) VALUES (?, ?, ?)",
                (user_email, request.message, ai_reply)
            )
            conn.commit()

        return {"reply": ai_reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"상담 서버 채널 장애: {str(e)}")

# ==========================================================
# 📊 3. 유저별 상담 내역 리스트 가져오기 (★초강력 안전 가공 업데이트★)
# ==========================================================
@app.get("/chat/history")
def get_user_chat_history(email: str):
    if not email:
        raise HTTPException(status_code=400, detail="이메일 정보가 빠졌습니다.")
        
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT message, reply, created_at FROM chat_history WHERE user_email = ? ORDER BY id DESC", 
                (email,)
            )
            rows = cursor.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 조회 장애: {str(e)}")
    
    history_list = []
    for row in rows:
        try:
            # 1. 질문 제목 정제 (최대 35자 잘라줌)
            summary_title = row[0][:35] + "..." if len(row[0]) > 35 else row[0]
            
            # 2. 🛡️ 마크다운 및 불필요한 특수문자 제거
            raw_reply = row[1].replace("\n", " ").replace("*", "").replace("#", "").replace("-", "").strip()
            
            # 3. 🛡️ 에러 유발 정규식(re.split) 완전 삭제! 대신 안전한 온점('.') 기준 파싱 설계
            # 문장 부호 뒤에 온점을 기준으로 문장을 정밀하게 나눕니다.
            raw_sentences = [s.strip() for s in raw_reply.split('.') if s.strip()]
            
            solution_summary = ""
            if len(raw_sentences) > 1:
                # 첫 번째 문장(공감 멘트)을 제외한 2번째, 3번째 문장을 조립해 실질적 해결책 구성
                solution_summary = raw_sentences[1]
                if len(raw_sentences) > 2:
                    solution_summary += ". " + raw_sentences[2] + "."
                else:
                    solution_summary += "."
            elif len(raw_sentences) == 1:
                solution_summary = raw_sentences[0] + "."
            else:
                solution_summary = "등록된 상담 내용이 존재합니다."

            # 4. 날짜 형식 가공
            date_formatted = row[2].split(" ")[0].replace("-", ".")
            
            history_list.append({
                "title": summary_title,
                "reply": solution_summary,
                "date": date_formatted
            })
        except Exception:
            # 예외 복구 안전벨트: 특정 행 데이터 가공 중 에러가 나더라도 서버를 터뜨리지 않고 기본값 매핑
            history_list.append({
                "title": row[0][:35] + "..." if len(row[0]) > 35 else row[0],
                "reply": "근로기준법 상담 세부 내용을 확인하세요.",
                "date": "2026.06.11"
            })
        
    return {"history": history_list}
