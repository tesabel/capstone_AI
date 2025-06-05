"""
비실시간 처리 API
PDF와 오디오 파일을 받아 STT, 이미지 캡셔닝, 세그먼트 매핑, 요약을 수행하는 API
"""

import os
import json
import uuid
import threading
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dotenv import load_dotenv

import jwt
from flask import Blueprint, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# .env 파일 로드
load_dotenv()

# 기존 모듈 import
from src.convert_audio import transcribe_audio
from src.image_captioning import image_captioning
from src.segment_mapping import segment_mapping
from src.segment_splitter import segment_split
from src.summary import create_summary

# Blueprint 생성
process_bp = Blueprint('process', __name__)

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
DATA_DIR = os.getenv('DATA_DIR', 'data')

# 작업 상태 저장소
job_status = {}
job_results = {}
job_lock = threading.Lock()

def generate_job_id():
    """고유한 job_id 생성"""
    now = datetime.now()
    return now.strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]

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

@process_bp.route('/start-process-v2', methods=['POST'])
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
        
        # 변환 이력 생성 (데이터베이스에 저장)
        if db:
            try:
                history = ConversionHistory(
                    user_id=user.id,
                    job_id=job_id,
                    filename=doc_filename,
                    status='processing'
                )
                db.session.add(history)
                db.session.commit()
            except Exception as db_error:
                print(f"데이터베이스 저장 오류: {db_error}")
                db.session.rollback()
        
        # 백그라운드에서 처리 시작
        threading.Thread(
            target=process_files_background,
            args=(job_id, audio_path, doc_path, user.id if user else None, skip_transcription)
        ).start()
        
        return jsonify({"job_id": job_id}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@process_bp.route('/process-status-v2/<job_id>', methods=['GET'])
@require_auth
def process_status_v2(user, job_id):
    """처리 상태 조회"""
    try:
        # 권한 확인
        if db:
            history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user.id).first()
            if not history:
                return jsonify({"error": "Job not found"}), 404
        
        status = get_job_status(job_id)
        if not status:
            return jsonify({"error": "Job not found"}), 404
        
        return jsonify(status), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@process_bp.route('/process-result-v2/<job_id>', methods=['GET'])
@require_auth
def process_result_v2(user, job_id):
    """처리 결과 조회"""
    try:
        # 권한 확인
        if db:
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
            # 파일이 없으면 메모리에서 조회
            result = get_job_result(job_id)
            if not result:
                return jsonify({"error": "Result not ready"}), 404
            return jsonify({"result": result}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def process_files_background(job_id, audio_path, doc_path, user_id=None, skip_transcription=False):
    """백그라운드에서 파일 처리"""
    # Flask 애플리케이션 컨텍스트 설정
    with app.app_context() if app else nullcontext():
        try:
            update_job_status(job_id, 0, "처리 시작...")
            
            # job 디렉토리 경로
            job_dir = os.path.join(UPLOAD_FOLDER, job_id)
            
            # 1. STT 처리 (0-30%)
            if not skip_transcription:
                update_job_status(job_id, 5, "음성 파일 준비 중...")
                stt_result = transcribe_audio(audio_path)
                update_job_status(job_id, 15, "음성 변환 완료, 텍스트 세그먼트 분리 중...")
                
                # 세그먼트 분리
                segments_data = segment_split(stt_result)
                total_segments = len(segments_data)
                update_job_status(job_id, 30, f"세그먼트 분리 완료 (총 {total_segments}개 세그먼트)")
            else:
                # STT 건너뛰기
                update_job_status(job_id, 30, "STT 건너뛰기, 이미지 분석 시작...")
                # .env에서 기본 STT 결과 경로 가져오기
                stt_result_path = os.getenv('STT_RESULT_PATH', "data/stt_result/stt_result.json")
                if os.path.exists(stt_result_path):
                    with open(stt_result_path, 'r', encoding='utf-8') as f:
                        stt_result = json.load(f)
                    segments_data = segment_split(stt_result)
                    total_segments = len(segments_data)
                else:
                    segments_data = []  # 파일이 없으면 빈 세그먼트 데이터
                    total_segments = 0
            
            # 2. 이미지 캡셔닝 (30-60%) - 진행률 실시간 업데이트
            update_job_status(job_id, 30, "슬라이드 이미지 분석 시작...")
            
            # image_captioning 함수에 progress callback 전달하여 실시간 업데이트
            def image_progress_callback(current_slide, total_slides):
                progress = 30 + int((current_slide / total_slides) * 30)
                update_job_status(job_id, progress, f"슬라이드 {current_slide}/{total_slides} 이미지 분석 중...")
            
            image_captions = image_captioning(doc_path, progress_callback=image_progress_callback)
            total_slides = len(image_captions)
            update_job_status(job_id, 60, f"이미지 분석 완료 (총 {total_slides}개 슬라이드), 세그먼트 매핑 시작...")
            
            # 3. 세그먼트 매핑 (60-70%)
            def mapping_progress_callback(current_batch, total_batches):
                progress = 60 + int((current_batch / total_batches) * 10)
                update_job_status(job_id, progress, f"음성-슬라이드 매핑 {current_batch}/{total_batches} 배치 진행 중...")
            
            mapped_segments = segment_mapping(image_captions, segments_data, progress_callback=mapping_progress_callback)
            mapped_count = sum(len(slide_data.get("Segments", {})) for slide_data in mapped_segments.values())
            update_job_status(job_id, 70, f"매핑 완료 (총 {mapped_count}개 매핑), 필기 생성 시작...")
            
            # 4. 요약 필기 생성 (70-100%)
            update_job_status(job_id, 70, "필기 요약 생성 중...")
            
            # 요약 생성 진행률 업데이트를 위한 콜백 함수
            def summary_progress_callback(current_slide, total_slides):
                progress = 70 + int((current_slide / total_slides) * 20)
                update_job_status(job_id, progress, f"슬라이드 {current_slide}/{total_slides} 요약 생성 중...")
            
            summary_notes = create_summary(image_captions, mapped_segments, progress_callback=summary_progress_callback)
            update_job_status(job_id, 90, "요약 생성 완료, 최종 결과 구조화 중...")
            
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
            
            # 파일 저장
            # 1. image_captioning.json 저장
            image_captioning_path = os.path.join(job_dir, "image_captioning.json")
            with open(image_captioning_path, 'w', encoding='utf-8') as f:
                json.dump(image_captions, f, ensure_ascii=False, indent=2)
            
            # 2. result.json 저장
            result_path = os.path.join(job_dir, "result.json")
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(final_result, f, ensure_ascii=False, indent=2)
            
            # 결과 저장 (메모리에도 저장)
            set_job_result(job_id, final_result)
            
            # 데이터베이스 업데이트 (처리 완료 전에 실행)
            if db and user_id:
                try:
                    history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user_id).first()
                    if history:
                        history.notes_json = final_result
                        history.status = 'completed'
                        db.session.commit()
                except Exception as db_error:
                    print(f"데이터베이스 업데이트 오류: {db_error}")
                    db.session.rollback()
            
            update_job_status(job_id, 100, "처리 완료!", 'completed')
            
        except Exception as e:
            update_job_status(job_id, 0, f"처리 중 오류 발생: {str(e)}", 'failed')
            
            # 데이터베이스 상태 업데이트 (실패)
            if db and user_id:
                try:
                    history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user_id).first()
                    if history:
                        history.status = 'failed'
                        db.session.commit()
                except Exception as db_error:
                    print(f"데이터베이스 업데이트 오류: {db_error}")
                    db.session.rollback()

