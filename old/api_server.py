"""
통합 Flask API 서버 (리팩토링된 버전)
모듈화된 API Blueprint들을 사용하는 메인 서버
"""

import os
import json
import uuid
import threading
from datetime import datetime, timedelta, timezone
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import jwt
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

# 기존 모듈 import (리팩토링된 API에서 필요한 경우에만)
from src.convert_audio import transcribe_audio
from src.image_captioning import image_captioning
from src.segment_mapping import segment_mapping
from src.segment_splitter import segment_split
from src.summary import create_summary
from src.realtime_convert_audio import transcribe_audio_with_timestamps

# .env 파일 로드
load_dotenv()

# API 모듈들 import
from api import register_blueprints

app = Flask(__name__)
CORS(app)

# 데이터베이스 설정
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
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

# === 헬퍼 함수 ===

def generate_job_id():
    """고유한 job_id 생성"""
    now = datetime.now()
    return now.strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]

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

def update_job_status(job_id, progress, message, status='processing'):
    """작업 상태 업데이트"""
    with job_lock:
        job_status[job_id] = {
            'job_id': job_id,
            'progress': progress,
            'message': message,
            'status': status
        }

def get_job_status(job_id):
    """작업 상태 조회"""
    with job_lock:
        return job_status.get(job_id)

def set_job_result(job_id, result):
    """작업 결과 저장"""
    with job_lock:
        job_results[job_id] = result

def get_job_result(job_id):
    """작업 결과 조회"""
    with job_lock:
        return job_results.get(job_id)

# === 기본 API ===

@app.route('/', methods=['GET'])
def health_check():
    """서버 상태 확인"""
    return jsonify({
        "status": "healthy",
        "message": "Smart Lecture Note API Server",
        "version": "1.0.0"
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
        print("회원가입 요청 시작")
        data = request.get_json()
        print(f"받은 데이터: {data}")
        
        if not data:
            return jsonify({
                "success": False,
                "message": "JSON 데이터가 필요합니다"
            }), 400
        
        email = data.get('email')
        password = data.get('password')
        
        print(f"이메일: {email}")
        
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
        
        try:
            # 사용자 생성
            user = User(email=email, password_hash=password_hash, name=email.split('@')[0])
            db.session.add(user)
            db.session.commit()
            print(f"사용자 생성 성공: {email}")
            
            # JWT 토큰 생성
            access_token = create_jwt_token(user.id)
            
            return jsonify({
                "success": True,
                "message": "회원가입 성공",
                "access_token": access_token
            }), 201
            
        except Exception as db_error:
            print(f"데이터베이스 오류: {str(db_error)}")
            db.session.rollback()
            raise db_error
        
    except IntegrityError as ie:
        print(f"무결성 오류: {str(ie)}")
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": "이미 존재하는 이메일입니다"
        }), 409
    except Exception as e:
        print(f"예상치 못한 오류: {str(e)}")
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

# === 실시간 변환 API ===

@app.route('/api/realTime/start-realtime', methods=['POST'])
@require_auth
def start_realtime(user):
    """실시간 변환 시작"""
    try:
        # job_id 생성
        job_id = generate_job_id()
        
        # 디렉토리 생성
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        # PDF 파일 처리 (선택사항)
        if 'doc_file' in request.files:
            pdf_file = request.files['doc_file']
            if pdf_file.filename:
                filename = secure_filename(pdf_file.filename)
                pdf_path = os.path.join(job_dir, filename)
                pdf_file.save(pdf_path)
                
                # 이미지 캡셔닝 수행
                try:
                    captioning_results = image_captioning(pdf_path)
                    result_path = os.path.join(job_dir, "captioning_results.json")
                    with open(result_path, 'w', encoding='utf-8') as f:
                        json.dump(captioning_results, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"Image captioning error: {e}")
        
        # 변환 이력 생성
        history = ConversionHistory(
            user_id=user.id,
            job_id=job_id,
            filename=filename if 'doc_file' in request.files and request.files['doc_file'].filename else 'realtime_session',
            status='active'
        )
        db.session.add(history)
        db.session.commit()
        
        return jsonify({"job_id": job_id}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/realTime/real-time-process/<job_id>', methods=['POST'])
@require_auth
def real_time_process(user, job_id):
    """실시간 오디오 청크 처리"""
    try:
        # 디렉토리 확인
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        if not os.path.exists(job_dir):
            return jsonify({"error": "Job not found"}), 404
        
        # 권한 확인
        history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user.id).first()
        if not history:
            return jsonify({"error": "Unauthorized access to job"}), 403
        
        # 현재 시간으로 하위 디렉토리 생성
        now = datetime.now()
        sub_dir_name = now.strftime("%Y%m%d_%H%M%S")
        sub_dir = os.path.join(job_dir, sub_dir_name)
        os.makedirs(sub_dir, exist_ok=True)
        
        audio_path = None
        meta_data = None
        
        # 오디오 파일 저장
        if 'audio_file' in request.files:
            audio_file = request.files['audio_file']
            if audio_file.filename:
                audio_path = os.path.join(sub_dir, "audio.wav")
                audio_file.save(audio_path)
        
        # 메타 JSON 저장
        if 'meta_json' in request.form:
            meta_json = request.form['meta_json']
            try:
                meta_data = json.loads(meta_json)
                json_path = os.path.join(sub_dir, "meta.json")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(meta_data, f, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                return jsonify({"error": "Invalid JSON format"}), 400
        
        # STT 처리 (기존 코드와 동일한 로직)
        if audio_path and meta_data:
            # 가장 오래 체류한 슬라이드 찾기
            longest_slide = find_longest_staying_slide(meta_data)
            
            if longest_slide is not None:
                # STT 수행
                stt_result = transcribe_audio_with_timestamps(audio_path)
                
                if stt_result and 'text' in stt_result:
                    # result.json 로드 또는 생성
                    result_data = load_or_create_result_json(job_dir)
                    
                    slide_key = f"slide{longest_slide}"
                    segment_key = f"segment{longest_slide}"
                    
                    # 슬라이드 구조 초기화
                    if slide_key not in result_data:
                        result_data[slide_key] = {
                            "Concise Summary Notes": "",
                            "Bullet Point Notes": "",
                            "Keyword Notes": "",
                            "Segments": {
                                segment_key: {
                                    "text": "",
                                    "isImportant": "false",
                                    "reason": "",
                                    "linkedConcept": "",
                                    "pageNumber": ""
                                }
                            }
                        }
                    
                    # 세그먼트 구조 초기화
                    if "Segments" not in result_data[slide_key]:
                        result_data[slide_key]["Segments"] = {}
                    
                    if segment_key not in result_data[slide_key]["Segments"]:
                        result_data[slide_key]["Segments"][segment_key] = {
                            "text": "",
                            "isImportant": "false",
                            "reason": "",
                            "linkedConcept": "",
                            "pageNumber": ""
                        }
                    
                    # 기존 텍스트에 새 STT 결과 추가 (누적)
                    existing_text = result_data[slide_key]["Segments"][segment_key]["text"]
                    if existing_text:
                        result_data[slide_key]["Segments"][segment_key]["text"] = existing_text + " " + stt_result["text"]
                    else:
                        result_data[slide_key]["Segments"][segment_key]["text"] = stt_result["text"]
                    
                    # result.json 저장
                    save_result_json(job_dir, result_data)
                    
                    return jsonify(result_data), 200
        
        # 오디오나 메타데이터가 없을 경우 기존 결과 반환
        result_data = load_or_create_result_json(job_dir)
        return jsonify(result_data), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === 비실시간 처리 API ===

@app.route('/api/process2/start-process-v2', methods=['POST'])
@require_auth
def start_process_v2(user):
    """비실시간 처리 시작"""
    try:
        # 파일 확인
        if 'audio_file' not in request.files or 'doc_file' not in request.files:
            return jsonify({"error": "Both audio and document files are required"}), 400
        
        audio_file = request.files['audio_file']
        doc_file = request.files['doc_file']
        
        if not audio_file.filename or not doc_file.filename:
            return jsonify({"error": "Both files must have filenames"}), 400
        
        # skip_transcription 플래그 확인
        skip_transcription = request.form.get('skip_transcription') == 'true'
        
        # job_id 생성
        job_id = generate_job_id()
        
        # 디렉토리 생성
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        # 파일 저장
        audio_filename = secure_filename(audio_file.filename)
        doc_filename = secure_filename(doc_file.filename)
        
        audio_path = os.path.join(job_dir, audio_filename)
        doc_path = os.path.join(job_dir, doc_filename)
        
        audio_file.save(audio_path)
        doc_file.save(doc_path)
        
        # 변환 이력 생성
        history = ConversionHistory(
            user_id=user.id,
            job_id=job_id,
            filename=doc_filename,
            status='processing'
        )
        db.session.add(history)
        db.session.commit()
        
        # 백그라운드에서 처리 시작
        threading.Thread(
            target=process_files_background,
            args=(job_id, audio_path, doc_path, user.id, skip_transcription)
        ).start()
        
        return jsonify({"job_id": job_id}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/process2/process-status-v2/<job_id>', methods=['GET'])
@require_auth
def process_status_v2(user, job_id):
    """처리 상태 조회"""
    try:
        # 권한 확인
        history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user.id).first()
        if not history:
            return jsonify({"error": "Job not found"}), 404
        
        # 상태 조회
        status = get_job_status(job_id)
        if not status:
            return jsonify({"error": "Job not found"}), 404
        
        return jsonify(status), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/process2/process-result-v2/<job_id>', methods=['GET'])
@require_auth
def process_result_v2(user, job_id):
    """처리 결과 조회"""
    try:
        # 권한 확인
        history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user.id).first()
        if not history:
            return jsonify({"error": "Job not found"}), 404
        
        # 파일에서 결과 조회
        result_path = os.path.join(UPLOAD_FOLDER, job_id, "result.json")
        if os.path.exists(result_path):
            with open(result_path, 'r', encoding='utf-8') as f:
                result_data = json.load(f)
            return jsonify({"result": result_data}), 200
        else:
            # 파일이 없으면 메모리에서 조회 (하위 호환성)
            result = get_job_result(job_id)
            if not result:
                return jsonify({"error": "Result not ready"}), 404
            return jsonify({"result": result}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === 히스토리 API ===

@app.route('/api/history/my', methods=['GET'])
@require_auth
def get_my_history(user):
    """사용자 변환 이력 조회"""
    try:
        histories = ConversionHistory.query.filter_by(user_id=user.id).order_by(ConversionHistory.created_at.desc()).all()
        
        result = []
        for history in histories:
            result.append({
                "id": history.id,
                "filename": history.filename,
                "created_at": history.created_at.isoformat() + "Z",
                "notes_json": history.notes_json or {},
                "job_id": history.job_id
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/history/download', methods=['GET'])
@require_auth
def download_result_pdf(user):
    """결과 PDF 다운로드"""
    try:
        # 쿼리 파라미터에서 job_id와 filename 가져오기
        job_id = request.args.get('job_id')
        filename = request.args.get('filename')
        
        if not job_id or not filename:
            return jsonify({"error": "job_id and filename are required"}), 400
            
        # 권한 확인
        history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user.id).first()
        if not history:
            return jsonify({"error": "Job not found"}), 404
        
        # PDF 파일 경로
        pdf_path = os.path.join(UPLOAD_FOLDER, job_id, filename)
        
        if not os.path.exists(pdf_path):
            return jsonify({"error": "File not found"}), 404
        
        return send_file(pdf_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === 백그라운드 처리 함수 ===

def process_files_background(job_id, audio_path, doc_path, user_id, skip_transcription=False):
    """백그라운드에서 파일 처리"""
    with app.app_context():
        try:
            update_job_status(job_id, 0, "처리 시작...")
            
            # job 디렉토리 경로
            job_dir = os.path.join(UPLOAD_FOLDER, job_id)
            
            # 1. STT 처리 (0-30%)
            if not skip_transcription:
                update_job_status(job_id, 10, "음성을 텍스트로 변환 중...")
                stt_result = transcribe_audio(audio_path)
                update_job_status(job_id, 20, "텍스트 세그먼트 분리 중...")
                
                # 세그먼트 분리
                segments_data = segment_split(stt_result)
                update_job_status(job_id, 30, "음성 변환 완료, 이미지 분석 시작...")
            else:
                # STT 건너뛰기
                update_job_status(job_id, 30, "STT 건너뛰기, 이미지 분석 시작...")
                # data/stt_result/stt_result.json 파일 사용
                stt_result_path = os.path.join("data", "stt_result", "stt_result.json")
                if os.path.exists(stt_result_path):
                    with open(stt_result_path, 'r', encoding='utf-8') as f:
                        stt_result = json.load(f)
                    segments_data = segment_split(stt_result)
                else:
                    segments_data = []  # 파일이 없으면 빈 세그먼트 데이터
            
            # 2. 이미지 캡셔닝 (30-60%) - 진행률 실시간 업데이트
            update_job_status(job_id, 35, "슬라이드 이미지 분석 시작...")
            
            # image_captioning 함수에 progress callback 전달하여 실시간 업데이트
            def progress_callback(current_slide, total_slides):
                progress = 35 + int((current_slide / total_slides) * 25)
                update_job_status(job_id, progress, f"슬라이드 {current_slide}/{total_slides} 이미지 분석 중...")
            
            image_captions = image_captioning_with_progress(doc_path, progress_callback)
            
            update_job_status(job_id, 60, "이미지 분석 완료, 세그먼트 매핑 시작...")
            
            # 3. 세그먼트 매핑 (60-70%)
            update_job_status(job_id, 65, "음성과 슬라이드 매핑 중...")
            mapped_segments = segment_mapping(image_captions, segments_data)
            update_job_status(job_id, 70, "매핑 완료, 필기 생성 시작...")
            
            # 4. 요약 필기 생성 (70-100%)
            update_job_status(job_id, 80, "필기 요약 생성 중...")
            summary_notes = create_summary(image_captions, mapped_segments)
            
            update_job_status(job_id, 90, "최종 결과 구조화 중...")
            
            # main.py와 동일한 방식으로 최종 결과 생성
            final_result = {}
            for slide_key in mapped_segments.keys():
                if slide_key == "slide0":
                    continue
                    
                slide_number = int(slide_key.replace("slide", ""))
                if slide_number > len(image_captions):
                    continue

                # 세그먼트 데이터
                segments = mapped_segments[slide_key].get("Segments", {})
                
                # 요약 데이터
                summary = summary_notes.get(slide_key, {}) if summary_notes else {}
                
                # 최종 결과 구성
                final_result[slide_key] = {
                    "Concise Summary Notes": summary.get("Concise Summary Notes", ""),
                    "Bullet Point Notes": summary.get("Bullet Point Notes", ""),
                    "Keyword Notes": summary.get("Keyword Notes", ""),
                    "Chart/Table Summary": summary.get("Chart/Table Summary", {}),
                    "Segments": {}
                }
                
                # 세그먼트 추가
                for segment_key, segment_data in segments.items():
                    final_result[slide_key]["Segments"][segment_key] = {
                        "text": segment_data.get("text", ""),
                        "isImportant": "false",
                        "reason": "",
                        "linkedConcept": "",
                        "pageNumber": ""
                    }
            
            update_job_status(job_id, 95, "최종 필기 정리 및 파일 저장 중...")
            
            # 파일 저장 (status 100 전에 실행)
            # 1. image_captioning.json 저장
            image_captioning_path = os.path.join(job_dir, "image_captioning.json")
            with open(image_captioning_path, 'w', encoding='utf-8') as f:
                json.dump(image_captions, f, ensure_ascii=False, indent=2)
            
            # 2. result.json 저장 (main.py와 동일한 구조)
            result_path = os.path.join(job_dir, "result.json")
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(final_result, f, ensure_ascii=False, indent=2)
            
            # 데이터베이스 업데이트 (status 100 전에 실행)
            history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user_id).first()
            if history:
                history.notes_json = final_result
                history.status = 'completed'
                db.session.commit()
            
            # 결과 저장 (메모리에도 저장 - 하위 호환성)
            set_job_result(job_id, final_result)
            
            update_job_status(job_id, 100, "처리 완료!", 'completed')
            
        except Exception as e:
            update_job_status(job_id, 0, f"처리 중 오류 발생: {str(e)}", 'failed')
            
            # 데이터베이스 업데이트
            try:
                history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user_id).first()
                if history:
                    history.status = 'failed'
                    db.session.commit()
            except Exception as db_error:
                print(f"데이터베이스 업데이트 오류: {db_error}")

def image_captioning_with_progress(doc_path, progress_callback=None):
    """진행률 콜백이 포함된 이미지 캡셔닝"""
    try:
        # 기존 image_captioning 함수 사용하되, 진행률 업데이트 추가
        from src.image_captioning import convert_pdf_to_images, analyze_image
        import json
        from datetime import datetime
        
        # PDF를 이미지로 변환
        images = convert_pdf_to_images(doc_path)
        total_slides = len(images)
        
        results = []
        
        for i, image_base64 in enumerate(images):
            slide_number = i + 1
            
            # 진행률 콜백 호출
            if progress_callback:
                progress_callback(slide_number, total_slides)
            
            # 이미지 분석
            analysis_result = analyze_image(image_base64)
            
            result = {
                "slide_number": slide_number,
                "type": analysis_result.get("type", "content"),
                "title_keywords": analysis_result.get("title_keywords", []),
                "secondary_keywords": analysis_result.get("secondary_keywords", []),
                "detail": analysis_result.get("detail", "")
            }
            
            results.append(result)
        
        # 결과 저장
        output_dir = "data/image_captioning"
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = os.path.join(output_dir, f"image_captioning_{timestamp}.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        return results
        
    except Exception as e:
        print(f"이미지 캡셔닝 오류: {e}")
        # 기존 함수로 fallback
        return image_captioning(doc_path)

# === 실시간 변환 헬퍼 함수 (기존 코드에서 이동) ===

def find_longest_staying_slide(meta_data):
    """메타 데이터에서 가장 오래 체류한 슬라이드 찾기"""
    max_duration = 0
    longest_slide = None
    
    # meta_data가 list인 경우와 dict인 경우 모두 처리
    if isinstance(meta_data, list):
        slides_data = meta_data
    else:
        slides_data = meta_data.get('slides', [])
    
    for slide_info in slides_data:
        # start_time과 end_time을 사용해 duration 계산
        if 'start_time' in slide_info and 'end_time' in slide_info:
            start_time = slide_info['start_time']
            end_time = slide_info['end_time']
            
            # "00:05.236" 형식을 초로 변환
            def time_to_seconds(time_str):
                parts = time_str.split(':')
                minutes = int(parts[0])
                seconds = float(parts[1])
                return minutes * 60 + seconds
            
            duration = time_to_seconds(end_time) - time_to_seconds(start_time)
        else:
            duration = slide_info.get('duration', 0)
        
        if duration > max_duration:
            max_duration = duration
            # slide_id 또는 pageNumber 사용
            longest_slide = slide_info.get('slide_id') or slide_info.get('pageNumber')
    
    return longest_slide

def load_or_create_result_json(job_dir):
    """result.json 로드하거나 새로 생성"""
    result_path = os.path.join(job_dir, "result.json")
    
    if os.path.exists(result_path):
        with open(result_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return {}

def save_result_json(job_dir, result_data):
    """result.json 저장"""
    result_path = os.path.join(job_dir, "result.json")
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

# === 데이터베이스 초기화 ===

def create_tables():
    """앱 시작 시 테이블 생성"""
    try:
        with app.app_context():
            db.create_all()
            print("Database tables created successfully")
    except Exception as e:
        print(f"Error creating database tables: {e}")

# === 에러 핸들러 ===

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# === API Blueprint 등록 ===
register_blueprints(app)

# === 메인 실행 ===

if __name__ == '__main__':
    # 테이블 생성
    create_tables()
    
    # .env에서 설정 가져오기
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '8000'))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    print(f"서버 시작: http://{host}:{port}")
    app.run(debug=debug, host=host, port=port)