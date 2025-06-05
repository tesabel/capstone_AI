# 🎓 Smart Lecture Note API Server

프론트엔드 요청에 맞춘 Flask 기반 백엔드 API 서버입니다.

## 🚀 시작하기

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. MySQL 데이터베이스 설정

MySQL이 설치되어 있고 실행 중이어야 합니다.

```bash
# 데이터베이스 자동 설정
python setup_database.py
```

또는 수동으로 설정:

```sql
CREATE DATABASE smart_lecture_note CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 3. 환경변수 설정 (선택사항)

`.env` 파일을 생성하여 다음 값들을 설정할 수 있습니다:

```env
SECRET_KEY=your-secret-key-here
GOOGLE_APPLICATION_CREDENTIALS=path/to/your/google/credentials.json
OPENAI_API_KEY=your-openai-api-key
```

### 4. 서버 실행

```bash
# API 서버 실행 (포트 5000)
python api_server.py

# 실시간 변환 서버들도 함께 실행하려면
python start_servers.py
```

## 📡 API 엔드포인트

### 🔐 인증 API

#### 회원가입
```http
POST /api/auth/register
Content-Type: application/json

{
  "email": "test@example.com",
  "password": "1234",
  "name": "우찬"
}
```

#### 로그인
```http
POST /api/auth/login
Content-Type: application/x-www-form-urlencoded

email=test@example.com&password=1234
```

**응답:**
```json
{
  "access_token": "<JWT_TOKEN>"
}
```

### ⚡ 실시간 변환 API

#### 실시간 변환 시작
```http
POST /api/realTime/start-realtime
Authorization: Bearer <JWT_TOKEN>
Content-Type: multipart/form-data

# Form data:
# doc_file: PDF 파일 (선택사항)
```

**응답:**
```json
{
  "job_id": "20250601_141500_abc123"
}
```

#### 실시간 오디오 처리
```http
POST /api/realTime/real-time-process/<job_id>
Authorization: Bearer <JWT_TOKEN>
Content-Type: multipart/form-data

# Form data:
# audio_file: 오디오 청크 파일
# meta_json: 슬라이드 메타 정보 JSON
```

### 🔄 비실시간 처리 API

#### 처리 시작
```http
POST /api/process2/start-process-v2
Authorization: Bearer <JWT_TOKEN>
Content-Type: multipart/form-data

# Form data:
# audioFile: 오디오 파일
# docFile: PDF 문서 파일
```

**응답:**
```json
{
  "job_id": "20250601_142500_def456"
}
```

#### 처리 상태 확인
```http
GET /api/process2/process-status-v2/<job_id>
Authorization: Bearer <JWT_TOKEN>
```

**응답:**
```json
{
  "job_id": "20250601_142500_def456",
  "progress": 70,
  "message": "요약 정리 중"
}
```

#### 처리 결과 조회
```http
GET /api/process2/process-result-v2/<job_id>
Authorization: Bearer <JWT_TOKEN>
```

**응답:**
```json
{
  "result": {
    "slide1": "첫 번째 슬라이드 필기...",
    "slide2": "두 번째 슬라이드 필기..."
  }
}
```

### 📋 히스토리 API

#### 변환 이력 조회
```http
GET /api/history/my
Authorization: Bearer <JWT_TOKEN>
```

**응답:**
```json
[
  {
    "id": 17,
    "filename": "강의노트_1.pdf",
    "created_at": "2025-05-31T13:30:00Z",
    "notes_json": {
      "slide1": "이것은 첫 번째 슬라이드 내용입니다.",
      "slide2": "두 번째 슬라이드입니다."
    },
    "job_id": "20250531_133000"
  }
]
```

#### 결과 PDF 다운로드
```http
GET /api/history/download/<job_id>
Authorization: Bearer <JWT_TOKEN>
```

## 🗄️ 데이터베이스 구조

### users 테이블
- `id`: 기본키
- `email`: 이메일 (유니크)
- `password_hash`: 해시된 비밀번호
- `name`: 사용자 이름
- `created_at`: 가입일시
- `last_login`: 마지막 로그인 시간

### conversion_history 테이블
- `id`: 기본키
- `user_id`: 사용자 ID (외래키)
- `job_id`: 작업 ID (유니크)
- `filename`: 파일명
- `notes_json`: 변환 결과 JSON
- `created_at`: 생성일시
- `status`: 상태 (pending, processing, completed, failed)

## 🔧 진행 상황 단계

비실시간 처리의 진행 상황은 다음과 같이 구분됩니다:

- **0-30%**: STT 처리 + 세그먼트 분리
- **30-60%**: 이미지 캡셔닝 처리
- **60-70%**: 세그먼트 매핑 처리
- **70-100%**: 요약 필기 생성

## 🚨 에러 처리

모든 에러는 HTTP 상태 코드와 함께 JSON 형식으로 반환됩니다:

```json
{
  "error": "에러 메시지"
}
```

주요 에러 코드:
- `400`: 잘못된 요청
- `401`: 인증 실패
- `403`: 권한 없음
- `404`: 리소스를 찾을 수 없음
- `409`: 충돌 (이메일 중복 등)
- `500`: 서버 내부 오류

## 🔒 보안

- JWT 토큰 기반 인증
- 토큰 만료 시간: 30분
- 비밀번호 해시화 저장
- CORS 설정으로 크로스 오리진 요청 허용

## 📁 파일 구조

```
capstone_AI/
├── api_server.py           # 메인 API 서버
├── setup_database.py       # 데이터베이스 설정 스크립트
├── flask_server.py         # 기존 실시간 서버
├── streaming_server.py     # WebSocket 스트리밍 서버
├── start_servers.py        # 서버 시작 스크립트
├── requirements.txt        # 의존성 목록
├── src/                    # 처리 모듈들
│   ├── convert_audio.py
│   ├── image_captioning.py
│   ├── segment_mapping.py
│   ├── summary.py
│   └── realtime_convert_audio.py
└── file/                   # 업로드된 파일 저장소
```

## 🛠️ 개발 및 테스트

API 테스트를 위해 다음 도구들을 사용할 수 있습니다:

- **Postman**: API 엔드포인트 테스트
- **curl**: 커맨드라인에서 API 테스트
- **Python requests**: 스크립트로 API 테스트

### 예시 테스트 스크립트

```python
import requests

# 회원가입
response = requests.post('http://localhost:5000/api/auth/register', json={
    'email': 'test@example.com',
    'password': '1234',
    'name': '테스트'
})

# 로그인
response = requests.post('http://localhost:5000/api/auth/login', data={
    'email': 'test@example.com',
    'password': '1234'
})

token = response.json()['access_token']

# 인증이 필요한 API 호출
headers = {'Authorization': f'Bearer {token}'}
response = requests.get('http://localhost:5000/api/history/my', headers=headers)
```

## 🤝 기여하기

1. 이슈 리포트
2. 기능 제안
3. 코드 개선
4. 문서 개선

---

📞 **문의사항이 있으시면 언제든 연락주세요!**