"""
데이터베이스 설정 스크립트
SQLAlchemy ORM을 사용해 MySQL 데이터베이스와 테이블을 설정합니다.
"""

import os
import sys
from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

# .env 파일 로드
load_dotenv()

# Flask 앱 생성 및 설정
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-this')

# SQLAlchemy 초기화
db = SQLAlchemy(app)

# === 모델 정의 (server.py와 동일) ===

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime)
    
    # 관계설정
    histories = db.relationship('ConversionHistory', backref='user', lazy=True)

class ConversionHistory(db.Model):
    __tablename__ = 'conversion_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    job_id = db.Column(db.String(100), unique=True, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    notes_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed

def create_database():
    """데이터베이스 테이블 초기화"""
    try:
        with app.app_context():
            # 기존 테이블 삭제 후 재생성
            db.drop_all()
            print("✅ 기존 테이블 삭제 완료")
            
            # 테이블 생성
            db.create_all()
            print("✅ 테이블 생성 완료")
            
            return True
            
    except Exception as e:
        print(f"❌ 데이터베이스 초기화 오류: {e}")
        print("\n💡 해결 방법:")
        print("1. MySQL이 설치되어 있는지 확인하세요")
        print("2. MySQL 서비스가 실행 중인지 확인하세요")
        print("3. .env 파일의 DATABASE_URI가 올바른지 확인하세요")
        print("4. MySQL 사용자의 권한이 충분한지 확인하세요")
        return False

def test_connection():
    """데이터베이스 연결 테스트"""
    try:
        with app.app_context():
            # 사용자 테이블에서 개수 확인
            user_count = db.session.query(User).count()
            history_count = db.session.query(ConversionHistory).count()
            print(f"✅ 연결 테스트 성공")
            print(f"   - 사용자 수: {user_count}")
            print(f"   - 변환 기록 수: {history_count}")
            return True
            
    except Exception as e:
        print(f"❌ 연결 테스트 실패: {e}")
        return False

def main():
    """메인 실행 함수"""
    print("🚀 데이터베이스 설정을 시작합니다...\n")
    
    # 환경변수 확인
    database_uri = os.getenv('DATABASE_URI')
    if not database_uri:
        print("❌ DATABASE_URI 환경변수가 설정되지 않았습니다")
        print("💡 .env 파일에 DATABASE_URI를 설정해주세요")
        sys.exit(1)
    
    print(f"📍 데이터베이스 URI: {database_uri}")
    print()
    
    # 1. 데이터베이스 초기화
    print("1️⃣ 데이터베이스 테이블 초기화 중...")
    if not create_database():
        print("❌ 데이터베이스 초기화 실패")
        sys.exit(1)
    print()
    
    # 2. 연결 테스트
    print("2️⃣ 연결 테스트 중...")
    if not test_connection():
        print("❌ 연결 테스트 실패")
        sys.exit(1)
    print()
    
    print("✅ DB 초기화 완료")
    print("\n📝 다음 단계:")
    print("1. pip install -r requirements.txt 실행")
    print("2. python server.py 실행")
    print("3. 브라우저에서 http://localhost:8000 접속")

if __name__ == "__main__":
    main()