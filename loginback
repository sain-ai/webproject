from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import sqlite3
import os

app = FastAPI(title="AlbaCare Auth Server")

# 프론트엔드와 통신하기 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실제 서비스 시에는 프론트엔드 도메인만 지정하는 것이 안전합니다.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "albacare.db"

# 서버 시작 시 데이터베이스 및 테이블 초기화
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

# Pydantic 모델 정의 (데이터 검증용)
class SignUpRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

@app.get("/")
def read_root():
    return {"message": "AlbaCare Auth API is running!"}

# 1. 회원가입 엔드포인트
@app.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user_data: SignUpRequest):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            (user_data.name, user_data.email, user_data.password)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # 이메일 중복 시 예외 처리
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 가입된 이메일입니다."
        )
    finally:
        conn.close()
        
    return {"message": "회원가입이 완료되었습니다."}

# 2. 로그인 엔드포인트
@app.post("/login")
def login(credentials: LoginRequest):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT name, email, password FROM users WHERE email = ?", 
        (credentials.email,)
    )
    user = cursor.fetchone()
    conn.close()
    
    # 사용자가 없거나 비밀번호가 틀린 경우 (보안을 위해 에러 메시지는 동일하게 처리)
    if not user or user[2] != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 일치하지 않습니다."
        )
        
    return {
        "message": "로그인 성공",
        "user": {
            "name": user[0],
            "email": user[1]
        }
    }
