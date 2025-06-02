"""
히스토리 관리 API
사용자의 변환 이력 조회 및 다운로드 기능을 제공하는 API
"""

import os
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from dotenv import load_dotenv

import jwt
from flask import Blueprint, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy

# .env 파일 로드
load_dotenv()

# Blueprint 생성
history_bp = Blueprint('history', __name__)

# 데이터베이스 인스턴스 (app에서 초기화됨)
db = None
app = None

# JWT 설정
JWT_SECRET = os.getenv('SECRET_KEY', 'your-secret-key-change-this')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')

# 데이터베이스 모델들
class User(db.Model if db else object):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True) if db else None
    email = db.Column(db.String(255), unique=True, nullable=False) if db else None
    password_hash = db.Column(db.String(255), nullable=False) if db else None
    name = db.Column(db.String(100), nullable=False) if db else None
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) if db else None
    last_login = db.Column(db.DateTime) if db else None
    
    # 관계설정
    histories = db.relationship('ConversionHistory', backref='user', lazy=True) if db else None

class ConversionHistory(db.Model if db else object):
    __tablename__ = 'conversion_history'
    
    id = db.Column(db.Integer, primary_key=True) if db else None
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) if db else None
    job_id = db.Column(db.String(100), unique=True, nullable=False) if db else None
    filename = db.Column(db.String(255), nullable=False) if db else None
    notes_json = db.Column(db.JSON, nullable=True) if db else None
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) if db else None
    status = db.Column(db.String(50), default='pending') if db else None  # pending, processing, completed, failed

def init_db(app_db, user_model, conversion_history_model, flask_app=None):
    """데이터베이스 초기화"""
    global db, User, ConversionHistory, app
    db = app_db
    User = user_model
    ConversionHistory = conversion_history_model
    app = flask_app

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
    
    return db.session.get(User, user_id) if db else None

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

# 업로드 디렉토리 설정
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'file')

@history_bp.route('/my', methods=['GET'])
@require_auth
def get_my_history(user):
    """사용자 변환 이력 조회"""
    try:
        # 데이터베이스에서 사용자의 이력 조회
        if db:
            histories_db = ConversionHistory.query.filter_by(user_id=user.id).order_by(ConversionHistory.created_at.desc()).all()
            
            result = []
            for history in histories_db:
                result.append({
                    "id": history.id,
                    "job_id": history.job_id,
                    "filename": history.filename,
                    "created_at": history.created_at.isoformat() + "Z",
                    "notes_json": history.notes_json or {},
                    "status": history.status
                })
            
            return jsonify(result), 200
        else:
            # 데이터베이스가 없을 경우 기존 방식으로 폴백
            histories = []
            
            # file 디렉토리에서 모든 job 폴더 조회
            if os.path.exists(UPLOAD_FOLDER):
                for job_dir in os.listdir(UPLOAD_FOLDER):
                    job_path = os.path.join(UPLOAD_FOLDER, job_dir)
                    
                    if os.path.isdir(job_path):
                        # result.json 파일이 있는지 확인
                        result_file = os.path.join(job_path, "result.json")
                        
                        if os.path.exists(result_file):
                            # 폴더의 수정 시간을 생성 시간으로 사용
                            created_at = datetime.fromtimestamp(os.path.getctime(job_path))
                            
                            # PDF 파일 찾기
                            pdf_files = [f for f in os.listdir(job_path) if f.endswith('.pdf')]
                            filename = pdf_files[0] if pdf_files else 'unknown.pdf'
                            
                            # 결과 데이터 로드
                            try:
                                with open(result_file, 'r', encoding='utf-8') as f:
                                    notes_json = json.load(f)
                            except:
                                notes_json = {}
                            
                            histories.append({
                                "id": job_dir,
                                "job_id": job_dir,
                                "filename": filename,
                                "created_at": created_at.isoformat() + "Z",
                                "notes_json": notes_json
                            })
            
            # 생성 시간 역순으로 정렬
            histories.sort(key=lambda x: x['created_at'], reverse=True)
            
            return jsonify(histories), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@history_bp.route('/detail/<job_id>', methods=['GET'])
def get_history_detail(job_id):
    """특정 이력 상세 조회"""
    try:
        job_path = os.path.join(UPLOAD_FOLDER, job_id)
        
        if not os.path.exists(job_path):
            return jsonify({"error": "History not found"}), 404
        
        result_file = os.path.join(job_path, "result.json")
        
        if not os.path.exists(result_file):
            return jsonify({"error": "Result file not found"}), 404
        
        # 결과 데이터 로드
        with open(result_file, 'r', encoding='utf-8') as f:
            result_data = json.load(f)
        
        # 메타 정보 수집
        created_at = datetime.fromtimestamp(os.path.getctime(job_path))
        pdf_files = [f for f in os.listdir(job_path) if f.endswith('.pdf')]
        filename = pdf_files[0] if pdf_files else 'unknown.pdf'
        
        history_detail = {
            "id": job_id,
            "job_id": job_id,
            "filename": filename,
            "created_at": created_at.isoformat() + "Z",
            "notes_json": result_data,
            "files": os.listdir(job_path)
        }
        
        return jsonify(history_detail), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@history_bp.route('/download', methods=['GET'])
def download_file():
    """파일 다운로드"""
    try:
        # 쿼리 파라미터에서 job_id와 filename 가져오기
        job_id = request.args.get('job_id')
        filename = request.args.get('filename')
        
        if not job_id or not filename:
            return jsonify({"error": "job_id and filename are required"}), 400
        
        # 파일 경로
        file_path = os.path.join(UPLOAD_FOLDER, job_id, filename)
        
        if not os.path.exists(file_path):
            return jsonify({"error": "File not found"}), 404
        
        return send_file(file_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@history_bp.route('/delete/<job_id>', methods=['DELETE'])
def delete_history(job_id):
    """이력 삭제"""
    try:
        import shutil
        
        job_path = os.path.join(UPLOAD_FOLDER, job_id)
        
        if not os.path.exists(job_path):
            return jsonify({"error": "History not found"}), 404
        
        # 디렉토리 전체 삭제
        shutil.rmtree(job_path)
        
        return jsonify({"message": "History deleted successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@history_bp.route('/export/<job_id>', methods=['GET'])
def export_result(job_id):
    """결과를 JSON 파일로 내보내기"""
    try:
        job_path = os.path.join(UPLOAD_FOLDER, job_id)
        result_file = os.path.join(job_path, "result.json")
        
        if not os.path.exists(result_file):
            return jsonify({"error": "Result file not found"}), 404
        
        # 파일명에 타임스탬프 추가
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"notes_export_{timestamp}.json"
        
        return send_file(
            result_file, 
            as_attachment=True, 
            download_name=export_filename,
            mimetype='application/json'
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@history_bp.route('/search', methods=['GET'])
def search_history():
    """이력 검색"""
    try:
        query = request.args.get('q', '').lower()
        
        if not query:
            return jsonify({"error": "Search query is required"}), 400
        
        histories = []
        
        if os.path.exists(UPLOAD_FOLDER):
            for job_dir in os.listdir(UPLOAD_FOLDER):
                job_path = os.path.join(UPLOAD_FOLDER, job_dir)
                
                if os.path.isdir(job_path):
                    result_file = os.path.join(job_path, "result.json")
                    
                    if os.path.exists(result_file):
                        # PDF 파일 찾기
                        pdf_files = [f for f in os.listdir(job_path) if f.endswith('.pdf')]
                        filename = pdf_files[0] if pdf_files else 'unknown.pdf'
                        
                        # 파일명 또는 내용에서 검색
                        match_filename = query in filename.lower()
                        match_content = False
                        
                        # 결과 파일 내용에서 검색
                        try:
                            with open(result_file, 'r', encoding='utf-8') as f:
                                content = f.read().lower()
                                match_content = query in content
                        except:
                            pass
                        
                        if match_filename or match_content:
                            created_at = datetime.fromtimestamp(os.path.getctime(job_path))
                            
                            try:
                                with open(result_file, 'r', encoding='utf-8') as f:
                                    notes_json = json.load(f)
                            except:
                                notes_json = {}
                            
                            histories.append({
                                "id": job_dir,
                                "job_id": job_dir,
                                "filename": filename,
                                "created_at": created_at.isoformat() + "Z",
                                "notes_json": notes_json,
                                "match_type": "filename" if match_filename else "content"
                            })
        
        # 생성 시간 역순으로 정렬
        histories.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({
            "query": query,
            "results": histories,
            "total": len(histories)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500