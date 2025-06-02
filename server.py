"""
새로운 Flask API 서버
리팩토링된 API 모듈들을 사용하는 메인 서버
"""

import os
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import jwt
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

# .env 파일 로드
load_dotenv()

# API 모듈들 import
from api import register_blueprints

app = Flask(__name__)
CORS(app)

# 데이터베이스 설정
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'mysql+pymysql://root:@localhost:3306/smart_lecture_note')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-this')

db = SQLAlchemy(app)

# 업로드 디렉토리 설정
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'file')
DATA_DIR = os.getenv('DATA_DIR', 'data')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# JWT 설정
JWT_SECRET = app.config['SECRET_KEY']
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXPIRATION_DELTA = timedelta(minutes=int(os.getenv('JWT_EXPIRATION_MINUTES', '30')))

# === 데이터베이스 모델 ===

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

# === JWT 헬퍼 함수 ===

def create_jwt_token(user_id):
    """JWT 토큰 생성"""
    payload = {
        'user_id': user_id,
        'exp': datetime.now(timezone.utc) + JWT_EXPIRATION_DELTA
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token):
    """JWT 토큰 검증"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload['user_id']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_current_user():
    """현재 사용자 정보 가져오기"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    
    token = auth_header.split(' ')[1]
    user_id = verify_jwt_token(token)
    if not user_id:
        return None
    
    return db.session.get(User, user_id)

def require_auth(f):
    """인증 데코레이터"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        return f(user, *args, **kwargs)
    return decorated_function

# === 기본 API ===

@app.route('/', methods=['GET'])
def health_check():
    """서버 상태 확인"""
    return jsonify({
        "status": "healthy",
        "message": "Smart Lecture Note API Server",
        "version": "2.0.0"
    }), 200

@app.route('/api/health', methods=['GET'])
def api_health():
    """API 헬스 체크"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "connected"
    }), 200

# === 인증 API ===

@app.route('/api/auth/register', methods=['POST'])
def register():
    """사용자 회원가입"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "success": False,
                "message": "JSON 데이터가 필요합니다"
            }), 400
        
        email = data.get('email')
        password = data.get('password')
        
        if not all([email, password]):
            return jsonify({
                "success": False,
                "message": "이메일과 비밀번호는 필수입니다"
            }), 400
        
        # 이메일 중복 체크
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return jsonify({
                "success": False,
                "message": "이미 존재하는 이메일입니다"
            }), 409
        
        # 비밀번호 해시화
        password_hash = generate_password_hash(password)
        
        # 사용자 생성
        user = User(email=email, password_hash=password_hash, name=email.split('@')[0])
        db.session.add(user)
        db.session.commit()
        
        # JWT 토큰 생성
        access_token = create_jwt_token(user.id)
        
        return jsonify({
            "success": True,
            "message": "회원가입 성공",
            "access_token": access_token
        }), 201
        
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": "이미 존재하는 이메일입니다"
        }), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": f"서버 오류가 발생했습니다: {str(e)}"
        }), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """사용자 로그인"""
    try:
        # application/x-www-form-urlencoded 형식 처리
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not all([username, password]):
            return jsonify({
                "success": False,
                "message": "이메일/아이디와 비밀번호는 필수입니다"
            }), 400
        
        # 사용자 조회 (이메일 기준)
        user = User.query.filter_by(email=username).first()
        if not user:
            return jsonify({
                "success": False,
                "message": "사용자를 찾을 수 없습니다"
            }), 404
        
        # 비밀번호 검증
        if not check_password_hash(user.password_hash, password):
            return jsonify({
                "success": False,
                "message": "비밀번호가 틀렸습니다"
            }), 401
        
        # 마지막 로그인 시간 업데이트
        user.last_login = datetime.now(timezone.utc)
        db.session.commit()
        
        # JWT 토큰 생성
        access_token = create_jwt_token(user.id)
        
        return jsonify({
            "success": True,
            "message": "로그인 성공",
            "access_token": access_token
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": f"서버 오류가 발생했습니다: {str(e)}"
        }), 500

# === 데이터베이스 초기화 ===

def create_tables():
    """앱 시작 시 테이블 생성"""
    try:
        with app.app_context():
            db.create_all()
            print("✅ 데이터베이스 테이블이 생성되었습니다")
    except Exception as e:
        print(f"❌ 데이터베이스 테이블 생성 오류: {e}")

# === 에러 핸들러 ===

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# === 파일 서빙 API ===
@app.route('/file/<path:filepath>')
def serve_file(filepath):
    """파일 서빙 (이미지, PDF 등)"""
    try:
        # file 디렉토리에서 파일 제공
        file_path = os.path.join(UPLOAD_FOLDER, filepath)
        
        if not os.path.exists(file_path):
            return jsonify({"error": "File not found"}), 404
        
        # 파일의 디렉토리와 파일명 분리
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        
        return send_from_directory(directory, filename)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === API Blueprint 등록 ===
from api.process import process_bp
from api.history import history_bp  
from api.realtime import realtime_bp

# 기존 API 경로로 등록
app.register_blueprint(process_bp, url_prefix='/api/process2')
app.register_blueprint(history_bp, url_prefix='/api/history')
app.register_blueprint(realtime_bp, url_prefix='/api/realTime')

# === 메인 실행 ===

if __name__ == '__main__':
    # 테이블 생성
    create_tables()
    
    # .env에서 설정 가져오기
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '8000'))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    print("=" * 60)
    print("🎓 Smart Lecture Note API 서버")
    print("=" * 60)
    print(f"📡 서버 주소: http://{host}:{port}")
    print("📋 사용 가능한 API:")
    print("├── 📁 비실시간 처리: /api/process/")
    print("├── 📚 히스토리 관리: /api/history/")
    print("├── ⚡ 실시간 처리: /api/realtime/")
    print("└── 🔐 인증: /api/auth/")
    print("=" * 60)
    
    app.run(debug=debug, host=host, port=port)