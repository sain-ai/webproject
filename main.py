from fastapi import FastAPI, HTTPException, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from contextlib import contextmanager
import sqlite3
import os
import requests
import base64
import json

app = FastAPI(title="AlbaCare Full Stack Gemini Server")

# ==========================================================
# 🌐 CORS 설정
# ==========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = os.path.join(os.getcwd(), "albacare.db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==========================================================
# 💾 SQLite Connection 관리 에이전트
# ==========================================================
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=15.0)
    try:
        yield conn
    finally:
        conn.close()

# ==========================================================
# 💾 데이터베이스 초기화 로직 (summary 칼럼 구조 보완)
# ==========================================================
def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        
        # 💬 요약본을 미리 저장해둘 summary 텍스트 칼럼을 새롭게 추가합니다.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                message TEXT NOT NULL,
                reply TEXT NOT NULL,
                summary TEXT, 
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
# 💬 2. 실시간 1:1 AI 노무사 상담 채팅 엔드포인트 (★요약본 동시 추출 적용★)
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

    # 🛠️ [사용자님 아이디어 전격 반영] 답변과 요약본을 깔끔한 JSON 양식으로 동시에 만들어달라고 강력 규제 유도
    chat_prompt = (
        "너는 대한민국 근로기준법을 완벽하게 숙지한 '알바 전문 AI 노무사'야. "
        "질문자가 처한 상황에 깊이 공감해주며 법적 판단과 대처 행동 지침을 친절하게 설명해줘. "
        "단, 너의 최종 출력은 반드시 아래 명시된 구조의 순수한 JSON 객체 형식이어야만 해. 다른 말은 절대 섞지마:\n\n"
        "{\n"
        '  "reply": "알바생에게 전할 친절하고 상세한 주절주절 답변 원문 전체 내용 (줄바꿈 포함 자유롭게 작성)",\n'
        '  "summary": "위 reply 내용 중 감정적 공감 멘트를 완전히 제외하고, 오직 핵심적인 법적 판단 및 해결책 요령만 골라 딱 온전한 2문장으로 요약한 텍스트 (말줄임표 금지)"\n'
        "}"
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
            
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        
        # 🛡️ 마크다운 백틱(```json ... ```) 제거 안정화 가공
        clean_json_text = raw_text.replace("```json", "").replace("```", "").strip()
        parsed_data = json.loads(clean_json_text)
        
        ai_reply = parsed_data.get("reply", "답변을 불러오지 못했습니다.")
        ai_summary = parsed_data.get("summary", "상담 세부 내용을 확인해 보세요.")

        # 💾 원문 답변과 추출된 2줄 요약본을 각각 테이블에 깔끔하게 나누어 즉시 영구 저장합니다.
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO chat_history (user_email, message, reply, summary) VALUES (?, ?, ?, ?)",
                (user_email, request.message, ai_reply, ai_summary)
            )
            conn.commit()

        # 📱 채팅 화면에는 주절주절 친절한 원본 대답만 내보냅니다!
        return {"reply": ai_reply}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"상담 데이터 가공 처리 장애: {str(e)}")

# ==========================================================
# 📊 3. 유저별 상담 내역 리스트 가져오기 (★초고속 원본 다이렉트 바인딩★)
# ==========================================================
@app.get("/chat/history")
def get_user_chat_history(email: str):
    if not email:
        raise HTTPException(status_code=400, detail="이메일 정보가 빠졌습니다.")
        
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT message, reply, summary, created_at FROM chat_history WHERE user_email = ? ORDER BY id DESC", 
            (email,)
        )
        rows = cursor.fetchall()
    
    history_list = []
    for row in rows:
        summary_title = row[0][:35] + "..." if len(row[0]) > 35 else row[0]
        
        # 🛠️ 복잡하게 자를 필요 없이 저장해둔 2줄짜리 순수 해결 요약본을 다이렉트로 바로 매핑합니다!
        # 혹시 예전에 저장되어 summary 칼럼이 비어있는(None) 데이터라면 기본 예외 문구 처리해 줍니다.
        solution_summary = row[2] if row[2] else "상담 세부 해결 가이드를 확인하세요."
        
        # 날짜 정제 규칙
        raw_date = str(row[3]).strip() if row[3] else "2026-06-11"
        date_part = raw_date.split(" ")[0] if " " in raw_date else raw_date.split("T")[0]
        date_formatted = date_part.replace("-", ".")
        
        history_list.append({
            "title": summary_title,
            "reply": solution_summary,
            "date": date_formatted
        })
        
    return {"history": history_list}
