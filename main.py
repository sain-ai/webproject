from fastapi import FastAPI, HTTPException, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import sqlite3
import os
import requests
import base64

app = FastAPI(title="AlbaCare Full Stack Server")

# CORS 설정 (프론트엔드 통신 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = os.path.join(os.getcwd(), "albacare.db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCyimAmgFnZ1P5Um48PhIRGq36BdDSAnso")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

class SignUpRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

@app.get("/")
def read_root():
    return {"status": "running", "message": "AlbaCare Gemini API Server is fully operational!"}

@app.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user_data: SignUpRequest):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", (user_data.name, user_data.email, user_data.password))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미 가입된 이메일입니다.")
    finally:
        conn.close()
    return {"message": "회원가입이 완료되었습니다."}

@app.post("/login")
def login(credentials: LoginRequest):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, email, password FROM users WHERE email = ?", (credentials.email,))
    user = cursor.fetchone()
    conn.close()
    if not user or user[2] != credentials.password:
        raise HTTPException(status_code=status.HTTP_41_UNAUTHORIZED, detail="이메일 또는 비밀번호가 일치하지 않습니다.")
    return {"message": "로그인 성공", "user": {"name": user[0], "email": user[1]}}


# ==========================================================
# 🔥 [예외 처리 강화] 계약서 이미지 & PDF 분석 API
# ==========================================================
@app.post("/analyze")
async def analyze_contract(
    file: UploadFile = File(...),
    task_type: str = Form(...) # 'photo_detail', 'risk_check', 'summary'
):
    # 1. 파일 확장자 검사
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in ['.jpg', '.jpeg', '.png', '.pdf']:
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. (JPG, PNG, PDF만 가능)")

    if not GEMINI_API_KEY or "여기에_" in GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="서버에 Gemini API Key가 설정되지 않았습니다.")

    # 2. 파일 바이트 읽기
    file_bytes = await file.read()
    
    # 🛑 [공통 핵심 지시사항] 계약서가 아닌 파일 필터링 규칙 정의
    validation_rule = (
        "[경고 - 가장 중요한 규칙]\n"
        "제공된 파일이 '근로계약서' 혹은 '고용계약서' 관련 문서가 아니거나, "
        "화질이 너무 깨져서 글자를 전혀 판독할 수 없는 이상한 문서/사진인 경우, "
        "아래 분석 내용을 모두 무시하고 오직 정확히 다음 한 문장만 답변으로 출력해라:\n"
        "❌ 분석 불가한 파일입니다. 올바른 근로계약서 사진이나 PDF 파일을 업로드해 주세요.\n\n"
        "만약 올바른 근로계약서가 맞다면, 아래 요청 조건에 맞추어 정상적인 분석을 진행해줘.\n"
        "-------------------------------------\n"
    )

    # 3. 요청 목적(task_type)에 따른 프롬프트 세팅
    if task_type == "photo_detail":
        prompt = validation_rule + (
            "너는 대한민국 근로기준법을 완벽하게 마스터한 20년 경력의 전문 노무사야. "
            "지금 제공하는 알바 근로계약서 첨부파일을 정밀 판독해서 아주 상세한 분석 리포트를 작성해줘. "
            "반드시 다음 사항들을 꼼꼼하게 짚어내야 해:\n"
            "1. 최저임금(2026년 기준 시급 10,300원) 준수 여부 및 주휴수당 지급 조건 명시 여부\n"
            "2. 소정근로시간, 휴게시간(4시간당 30분) 조건의 법적 타당성\n"
            "3. 알바생에게 일방적으로 불리한 독소 조항(무단 결근 시 벌금, 수습기간 감액 남용, 무리한 위약금 설정 등)\n"
            "4. 이 계약서에 서명해도 안전한지 최종 노무사 총평과 수정이 필요한 문구 가이드"
        )
    elif task_type == "risk_check":
        prompt = validation_rule + (
            "너는 법적 위험 요소를 잡아내는 AI 검사기야. 이 근로계약서에서 오직 '위법 소지가 있는 위험 조항'들만 "
            "빠르고 명확하게 리스트로 뽑아줘. 최저임금 위반, 주휴수당 미지급 조건, 불법 벌금 조항 등이 있다면 "
            "그 항목과 법적 근거(근로기준법 몇 조 위반인지)만 핵심 요약식으로 정리해서 알려줘."
        )
    elif task_type == "summary":
        prompt = validation_rule + (
            "너는 어려운 법률 용어를 쉬운 말로 바꿔주는 친절한 요약 요정이야. 이 근로계약서의 복잡한 내용을 다 제외하고, "
            "알바생이 꼭 알아야 하는 핵심 요약(시급은 얼마인지, 일주일에 몇 시간 일하는지, 언제 돈 주는지 등)만 "
            "가장 보기 편하게 딱 3~5줄 내외로 아주 쉽게 요약해줘."
        )
    else:
        prompt = validation_rule + "이 근로계약서를 분석하고 주요 근로 조건을 설명해줘."

    # 4. 마임타입 지정 및 Base64 인코딩
    mime_type = "image/jpeg"
    if file_extension == ".png": mime_type = "image/png"
    elif file_extension == ".pdf": mime_type = "application/pdf"

    base64_data = base64.b64encode(file_bytes).decode("utf-8")

    # 5. Gemini API 호출
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
        raise HTTPException(status_code=500, detail=f"서버 내부 분석 에러: {str(e)}")
