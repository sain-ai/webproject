from fastapi import FastAPI, HTTPException, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from contextlib import contextmanager
import sqlite3
import os
import requests
import base64
import json

app = FastAPI(title="성북굿잡 AI 맞춤 일자리 매칭 & 취업 컨설팅 서버")

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

DB_FILE = os.path.join(os.getcwd(), "seongbuk_goodjob.db")
# 🔑 환경변수가 없더라도 기본 발급받으신 Gemini API 키로 즉시 구동되도록 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6LD61hlzoiankwMkVJ-rC0KS-BOWGohX_UIyGB_A5j3kg")

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
# 💾 데이터베이스 초기화 로직
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
    return {"status": "running", "message": "성북굿잡(Seongbuk GoodJob) AI 일자리 매칭 서버가 정상 가동 중입니다!"}

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
    return {"message": "성북굿잡 회원가입이 완료되었습니다."}

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
# 🔍 1. 자기소개서 & 이력서 & 채용공고 AI 정밀 분석 API
# ==========================================================
@app.post("/analyze")
async def analyze_document(
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
        "제공된 파일이 '자기소개서', '이력서/포트폴리오', '채용공고문', '구인구직 서류'와 관련된 문서가 아니거나, "
        "화질이 깨져 글자를 판독할 수 없는 엉뚱한 사진(음식 사진, 풍경, 영수증 등)인 경우, "
        "아래 지시 사항들을 모두 무시하고 오직 정확히 다음 한 문장만 답변으로 출력해라:\n"
        "❌ 분석 불가한 파일입니다. 올바른 자기소개서 또는 이력서 사진/PDF 파일을 업로드해 주세요.\n\n"
        "만약 정상적인 구인구직 서류가 맞다면, 아래의 요청 유형에 맞춰 정밀 분석을 진행해줘.\n"
        "-------------------------------------\n"
    )

    # 1) 자기소개서 사진 분석 & 일자리 추천
    if task_type == "photo_detail":
        prompt = validation_rule + (
            "너는 성북구 취업지원센터의 20년 경력 수석 취업 컨설턴트야. "
            "지금 제공하는 자기소개서(또는 초안 사진)를 꼼꼼하게 읽고 지원자의 강점을 도출하여 성북구 맞춤 일자리를 추천해줘:\n"
            "1. 자소서 핵심 역량(전공 지식, 프로젝트 경험, 문제 해결력 등) 3가지 추출\n"
            "2. 지원자에게 가장 잘 어울리는 성북구 관내 추천 직무 및 기업 유형 (IT/벤처, 문화기획, 공공기관, 패션/제조 등)\n"
            "3. 서류 합격률을 높이기 위한 자기소개서 문장 첨삭 및 보완 가이드\n"
            "4. 지원자가 활용할 수 있는 성북구 일자리 지원센터(대학 일자리카페 등) 연계 조언"
        )
    # 2) 이력서 PDF 정밀 분석
    elif task_type == "resume_analyze":
        prompt = validation_rule + (
            "너는 인사담당자 관점에서 서류를 평가하는 취업 전문 헤드헌터야. "
            "업로드된 이력서 및 경력기술서 문서를 정밀 분석해서 합격 진단서를 작성해줘:\n"
            "1. 목표 직무 부합도 평가 및 핵심 경쟁력 분석\n"
            "2. 수치화된 성과 표현 부족 등 이력서 서술 방식 개선점 피드백\n"
            "3. 추가하면 서류 합격률이 급상승하는 필수 직무 키워드 제안\n"
            "4. 이력서 기반 추천 채용 포지션 및 면접 대비 질문 2가지"
        )
    # 3) 블랙기업 & 위험 채용공고 스캔
    elif task_type == "risk_check":
        prompt = validation_rule + (
            "너는 구인구직 사기 및 불량 채용공고를 잡아내는 AI 안전 스캐너야. 이 공고문에서 '지원자가 주의해야 할 위험 요소'만 "
            "핵심 요약 리스트로 뽑아줘. 허위 과장 공고, 2026년 최저임금(시급 10,300원) 미달, 불명확한 수습 감액, 다단계/영업 강요 의심 조항이 있다면 "
            "그 항목과 법적·실무적 주의사항만 명확히 정리해줘."
        )
    # 4) 공고 핵심 3줄 요약
    elif task_type == "summary":
        prompt = validation_rule + (
            "너는 복잡한 채용공고를 핵심만 쏙 뽑아주는 스마트 취업 요약 요정이야. 공고문의 복잡한 내용을 제외하고 "
            "구직자가 무조건 알아야 할 핵심 5가지(담당업무, 급여, 근무지/시간, 필수자격, 마감일)만 보기 편하게 3~5줄로 쉽게 요약해줘."
        )
    else:
        prompt = validation_rule + "이 일자리 및 채용 관련 서류를 정밀 분석하고 핵심 가이드를 제공해줘."

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
# 💬 2. 실시간 1:1 AI 취업 컨설턴트 상담 채팅 엔드포인트
# ==========================================================
@app.post("/chat")
def chat_with_job_advisor(
    request: ChatMessageRequest, 
    user_email: str = None
):
    if not GEMINI_API_KEY or "여기에_" in GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="서버에 Gemini API Key가 설정되지 않았습니다.")

    if not user_email:
        raise HTTPException(status_code=422, detail="user_email 파라미터가 누락되었습니다.")

    chat_prompt = (
        "너는 성북구 청년 및 구직자를 위한 '성북굿잡 전담 AI 취업 컨설턴트'야. "
        "성북구 내 일자리 정보, 공공 일자리, 이력서/자소서 첨삭, 면접 코칭, 청년 취업 지원 정책(성북구 청년수당, 면접정장 대여, 일자리카페 특강)을 친절하게 안내해줘. "
        "단, 너의 최종 출력은 반드시 아래 명시된 구조의 순수한 JSON 객체 형식이어야만 해. 다른 말은 절대 섞지마:\n\n"
        "{\n"
        '  "reply": "구직자에게 전할 친절하고 전문적인 상세 답변 원문 전체 내용 (줄바꿈 포함)",\n'
        '  "summary": "위 reply 내용 중 감정적 인사를 제외하고, 오직 핵심적인 일자리 추천 및 취업 해결책만 골라 딱 온전한 2문장으로 요약한 텍스트 (말줄임표 금지)"\n'
        "}"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [{
            "parts": [
                {"text": chat_prompt},
                {"text": f"구직자의 질문 내용: {request.message}"}
            ]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response_json = response.json()
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Gemini 대화 API 통신 에러")
            
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        clean_json_text = raw_text.replace("```json", "").replace("```", "").strip()
        parsed_data = json.loads(clean_json_text)
        
        ai_reply = parsed_data.get("reply", "답변을 불러오지 못했습니다.")
        ai_summary = parsed_data.get("summary", "상담 세부 내용을 확인해 보세요.")

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO chat_history (user_email, message, reply, summary) VALUES (?, ?, ?, ?)",
                (user_email, request.message, ai_reply, ai_summary)
            )
            conn.commit()

        return {"reply": ai_reply}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"상담 데이터 가공 처리 장애: {str(e)}")

# ==========================================================
# 📊 3. 유저별 취업 상담 내역 리스트 가져오기
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
        solution_summary = row[2] if row[2] else "상담 세부 해결 가이드를 확인하세요."
        raw_date = str(row[3]).strip() if row[3] else "2026-08-24"
        date_part = raw_date.split(" ")[0] if " " in raw_date else raw_date.split("T")[0]
        date_formatted = date_part.replace("-", ".")
        
        history_list.append({
            "title": summary_title,
            "reply": solution_summary,
            "date": date_formatted
        })
        
    return {"history": history_list}
