"""
실시간 처리 API  
실시간 오디오 스트리밍 및 슬라이드별 음성 인식 결과를 처리하는 API
"""

import os
import json
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

# .env 파일 로드
load_dotenv()

# 기존 모듈 import
from src.image_captioning import image_captioning, convert_pdf_to_images
from src.realtime_convert_audio import transcribe_audio_with_timestamps
from src.segment_splitter import segment_split
from src.post_process import post_process

# Blueprint 생성
realtime_bp = Blueprint('realtime', __name__)

# 업로드 디렉토리 설정
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'file')
DEFAULT_CAPTIONING_PATH = 'data/image_captioning/image_captioning.json'

# 데이터베이스 관련 변수 (process.py에서 초기화됨)
db = None
User = None
ConversionHistory = None

# JWT 설정
JWT_SECRET = os.getenv('SECRET_KEY', 'your-secret-key-change-this')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')

def init_realtime_db(app_db, user_model, conversion_history_model):
    """데이터베이스 초기화"""
    global db, User, ConversionHistory
    db = app_db
    User = user_model
    ConversionHistory = conversion_history_model

def verify_jwt_token(token):
    """JWT 토큰 검증"""
    try:
        import jwt
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

def generate_job_id():
    """고유한 job_id 생성"""
    now = datetime.now()
    return now.strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]

@realtime_bp.route('/start-realtime', methods=['POST'])
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
        filename = "realtime_session.pdf"  # 기본값
        if 'doc_file' in request.files:
            pdf_file = request.files['doc_file']
            if pdf_file.filename:
                filename = secure_filename(pdf_file.filename)
                pdf_path = os.path.join(job_dir, filename)
                pdf_file.save(pdf_path)
                
                # 이미지 캡셔닝 수행
                try:
                    if os.getenv('SKIP_IMAGECAPTIONING', 'false').lower() == 'true':
                        # 기본 캡셔닝 결과 파일 사용
                        with open(DEFAULT_CAPTIONING_PATH, 'r', encoding='utf-8') as f:
                            captioning_results = json.load(f)
                    else:
                        # 실제 이미지 캡셔닝 수행
                        captioning_results = image_captioning(pdf_path)
                    
                    result_path = os.path.join(job_dir, "captioning_results.json")
                    with open(result_path, 'w', encoding='utf-8') as f:
                        json.dump(captioning_results, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"Image captioning error: {e}")
        
        # 변환 이력 생성 (데이터베이스에 저장)
        if db:
            try:
                history = ConversionHistory(
                    user_id=user.id,
                    job_id=job_id,
                    filename=filename,
                    status='processing'
                )
                db.session.add(history)
                db.session.commit()
            except Exception as db_error:
                print(f"데이터베이스 저장 오류: {db_error}")
                db.session.rollback()
        
        return jsonify({"jobId": job_id}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@realtime_bp.route('/stop-realtime', methods=['POST'])
def stop_realtime():
    """실시간 변환 종료 및 PDF를 이미지로 변환"""
    try:
        # jobId 가져오기 (query parameter, request body, form data에서)
        job_id = None
        
        # 1. Query parameter에서 확인
        job_id = request.args.get('jobId')
        
        # 2. JSON body에서 확인
        if not job_id and request.json:
            job_id = request.json.get('jobId')
        
        # 3. Form data에서 확인
        if not job_id and request.form:
            job_id = request.form.get('jobId')
        
        print(f"[DEBUG] Query args: {dict(request.args)}")
        print(f"[DEBUG] Request JSON: {request.json}")
        print(f"[DEBUG] Request form: {dict(request.form) if request.form else None}")
        print(f"[DEBUG] Final jobId: {job_id}")
        
        if not job_id:
            return jsonify({"error": "jobId is required"}), 400
        
        # PDF 파일 경로 확인
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        if not os.path.exists(job_dir):
            return jsonify({"error": f"Job directory not found: {job_id}"}), 404
        
        # PDF 파일 찾기
        pdf_files = [f for f in os.listdir(job_dir) if f.lower().endswith('.pdf')]
        if not pdf_files:
            return jsonify({"error": "No PDF file found in job directory"}), 404
        
        pdf_path = os.path.join(job_dir, pdf_files[0])  # 첫 번째 PDF 파일 사용
        
        # 이미지 저장 디렉토리 생성
        image_dir = os.path.join(job_dir, 'image')
        os.makedirs(image_dir, exist_ok=True)
        print(f"[DEBUG] Image directory created: {image_dir}")
        
        # PDF를 이미지로 변환
        try:
            from pdf2image import convert_from_path
            print(f"[DEBUG] Converting PDF: {pdf_path}")
            
            # PDF를 이미지로 변환
            images = convert_from_path(pdf_path, dpi=200, fmt='PNG')
            print(f"[DEBUG] Converted {len(images)} pages from PDF")
            
            image_urls = []
            successful_saves = 0
            
            # 모든 이미지를 저장하고 확인
            for i, image in enumerate(images, 1):
                # 이미지 파일명 생성 (1.png, 2.png, ...)
                image_filename = f"{i}.png"
                image_path = os.path.join(image_dir, image_filename)
                
                try:
                    # 이미지를 PNG로 저장
                    image.save(image_path, 'PNG', quality=95, optimize=True)
                    print(f"[DEBUG] Saved image: {image_path}")
                    
                    # 파일이 실제로 생성되고 크기가 0이 아닌지 확인
                    if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
                        file_size = os.path.getsize(image_path)
                        print(f"[DEBUG] Image file verified, size: {file_size} bytes")
                        
                        # 이미지 URL 생성 (성공한 경우만)
                        image_url = f"/file/{job_id}/image/{image_filename}"
                        image_urls.append(image_url)
                        successful_saves += 1
                    else:
                        print(f"[ERROR] Image file not created or empty: {image_path}")
                        
                except Exception as save_error:
                    print(f"[ERROR] Failed to save image {i}: {save_error}")
            
            print(f"[DEBUG] Successfully saved {successful_saves}/{len(images)} images")
            
            # 최소 하나 이상의 이미지가 성공적으로 저장된 경우에만 성공 응답
            if successful_saves > 0:
                print(f"[DEBUG] Returning {len(image_urls)} image URLs")
                
                # JSON 결과 파일 읽기
                result_json = None
                result_path = os.path.join(UPLOAD_FOLDER, job_id, "result.json")
                if os.path.exists(result_path):
                    with open(result_path, 'r', encoding='utf-8') as f:
                        result_json = json.load(f)
                
                return jsonify({
                    "image_urls": image_urls,
                    "result_json": result_json
                }), 200
            else:
                raise Exception("No images were successfully saved")
                
        except Exception as convert_error:
            print(f"[ERROR] PDF conversion failed: {convert_error}")
            raise Exception(f"PDF to image conversion failed: {str(convert_error)}")
        
    except Exception as e:
        return jsonify({"error": f"Failed to convert PDF to images: {str(e)}"}), 500

@realtime_bp.route('/post-process', methods=['POST', 'OPTIONS'])
def post_process_endpoint():
    """졸았던 슬라이드들에 대한 후처리 수행"""
    # OPTIONS 요청 처리 (CORS preflight)
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200
    
    # POST 요청의 경우 인증 확인
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        # 요청 데이터 확인
        if not request.json:
            return jsonify({"error": "JSON data is required"}), 400
        
        job_id = request.json.get('jobId')
        sleep_slides = request.json.get('sleepSlides')
        print(f"sleep_slides: {sleep_slides}")
        
        if not job_id:
            return jsonify({"error": "jobId is required"}), 400
        
        if not sleep_slides or not isinstance(sleep_slides, list):
            return jsonify({"error": "sleepSlides must be a non-empty array"}), 400
        
        # 권한 확인 - 해당 job이 현재 사용자의 것인지 확인
        if db:
            history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user.id).first()
            if not history:
                return jsonify({"error": "Job not found or access denied"}), 404
        
        # job 디렉토리 확인
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        if not os.path.exists(job_dir):
            return jsonify({"error": f"Job directory not found: {job_id}"}), 404
        
        # result.json 파일 확인
        result_path = os.path.join(job_dir, "result.json")
        if not os.path.exists(result_path):
            return jsonify({"error": "result.json not found"}), 404
        
        # captioning_results.json 또는 image_captioning.json 확인
        captioning_path = os.path.join(job_dir, "captioning_results.json")
        if not os.path.exists(captioning_path):
            captioning_path = os.path.join(job_dir, "image_captioning.json")
            if not os.path.exists(captioning_path):
                return jsonify({"error": "captioning results not found"}), 404
        
        # 기존 result.json 로드
        with open(result_path, 'r', encoding='utf-8') as f:
            result_data = json.load(f)
        
        # captioning 데이터 로드
        with open(captioning_path, 'r', encoding='utf-8') as f:
            captioning_data = json.load(f)
        
        # 각 sleep slide에 대해 후처리 수행
        for slide_num in sleep_slides:
            slide_key = f"slide{slide_num}"
            
            if slide_key not in result_data:
                continue
            
            # 해당 슬라이드의 텍스트 추출
            slide_text = ""
            if "Segments" in result_data[slide_key]:
                for segment_data in result_data[slide_key]["Segments"].values():
                    slide_text += segment_data.get("text", "") + " "
            
            if not slide_text.strip():
                continue
            
            # STT 형식으로 변환하여 세그먼트 분할
            stt_data = {"text": slide_text.strip()}
            segments = segment_split(stt_data)
            
            if isinstance(segments, dict) and "error" in segments:
                print(f"세그먼트 분할 오류 (slide {slide_num}): {segments['error']}")
                continue
            
            # 후처리로 세그먼트 재매핑
            try:
                mapped_data = post_process(
                    image_captioning_data=captioning_data,
                    segment_split_data=segments,
                    centre_slide=slide_num
                )
                
                print(f"매핑 결과: {mapped_data}")
                
                # 원본 슬라이드에 남을 세그먼트들을 수집
                segments_to_keep_in_original = []
                segments_to_move = []
                
                # 매핑 결과를 분석하여 어떤 세그먼트가 어디로 갈지 분류
                for mapped_slide_key, mapped_slide_data in mapped_data.items():
                    if mapped_slide_key == "slide0" or "Segments" not in mapped_slide_data:
                        continue
                    
                    mapped_slide_num = int(mapped_slide_key.replace("slide", ""))
                    
                    for segment_key, segment_data in mapped_slide_data["Segments"].items():
                        segment_text = segment_data.get("text", "")
                        if not segment_text.strip():
                            continue
                            
                        if mapped_slide_num == slide_num:
                            # 같은 슬라이드에 남을 세그먼트
                            segments_to_keep_in_original.append(segment_text)
                        else:
                            # 다른 슬라이드로 이동할 세그먼트
                            segments_to_move.append({
                                "text": segment_text,
                                "target_slide": mapped_slide_num,
                                "target_slide_key": mapped_slide_key
                            })
                
                print(f"원본에 남을 세그먼트: {len(segments_to_keep_in_original)}개")
                print(f"이동할 세그먼트: {len(segments_to_move)}개")
                
                # 1. 원본 슬라이드 업데이트 (남을 세그먼트들만)
                original_slide_key = f"slide{slide_num}"
                main_segment_key = f"segment{slide_num}"
                
                if original_slide_key in result_data and "Segments" in result_data[original_slide_key]:
                    if main_segment_key in result_data[original_slide_key]["Segments"]:
                        # 원본 슬라이드에는 남을 세그먼트들만 결합
                        new_original_text = " ".join(segments_to_keep_in_original).strip()
                        result_data[original_slide_key]["Segments"][main_segment_key]["text"] = new_original_text
                        print(f"원본 슬라이드 {slide_num} 업데이트: '{new_original_text[:50]}...'")
                
                # 2. 이동할 세그먼트들을 대상 슬라이드에 추가
                for move_info in segments_to_move:
                    target_slide_key = move_info["target_slide_key"]
                    target_slide_num = move_info["target_slide"]
                    segment_text = move_info["text"]
                    
                    print(f"세그먼트를 slide{target_slide_num}로 이동: '{segment_text[:50]}...'")
                    
                    # 대상 슬라이드가 없으면 생성
                    if target_slide_key not in result_data:
                        result_data[target_slide_key] = {
                            "Concise Summary Notes": "",
                            "Bullet Point Notes": "",
                            "Keyword Notes": "",
                            "Chart/Table Summary": {},
                            "Segments": {}
                        }
                    
                    # Segments가 없으면 생성
                    if "Segments" not in result_data[target_slide_key]:
                        result_data[target_slide_key]["Segments"] = {}
                    
                    # 대상 슬라이드의 메인 세그먼트 키
                    target_main_segment_key = f"segment{target_slide_num}"
                    
                    # 메인 세그먼트가 없으면 생성
                    if target_main_segment_key not in result_data[target_slide_key]["Segments"]:
                        result_data[target_slide_key]["Segments"][target_main_segment_key] = {
                            "text": "",
                            "isImportant": "false",
                            "reason": "",
                            "linkedConcept": "",
                            "pageNumber": ""
                        }
                    
                    # 기존 텍스트 가져오기
                    existing_text = result_data[target_slide_key]["Segments"][target_main_segment_key]["text"]
                    
                    # 텍스트 추가 위치 결정
                    if target_slide_num < slide_num:
                        # 앞 슬라이드: 뒷부분에 추가
                        new_text = existing_text + " " + segment_text if existing_text else segment_text
                        print(f"앞 슬라이드에 추가: slide{target_slide_num}")
                    elif target_slide_num > slide_num:
                        # 뒷 슬라이드: 앞부분에 추가
                        new_text = segment_text + " " + existing_text if existing_text else segment_text
                        print(f"뒷 슬라이드에 추가: slide{target_slide_num}")
                    else:
                        # 같은 슬라이드 (이미 위에서 처리됨)
                        continue
                    
                    # 텍스트 업데이트
                    result_data[target_slide_key]["Segments"][target_main_segment_key]["text"] = new_text.strip()
                    print(f"slide{target_slide_num} 업데이트 완료, 텍스트 길이: {len(new_text)}")
                
                print(f"slide {slide_num} 전체 처리 완료")
                
            except Exception as e:
                print(f"후처리 오류 (slide {slide_num}): {str(e)}")
                continue
        
        # 수정된 result.json 저장
        print(f"result.json 저장 중: {result_path}")
        print(f"저장할 데이터 슬라이드 수: {len(result_data)}")
        
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        
        # 저장 확인
        if os.path.exists(result_path):
            file_size = os.path.getsize(result_path)
            print(f"result.json 저장 완료, 파일 크기: {file_size} bytes")
        else:
            print("result.json 저장 실패!")
        
        # 저장된 내용 확인
        try:
            with open(result_path, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            print(f"저장된 데이터 슬라이드 수: {len(saved_data)}")
        except Exception as e:
            print(f"저장된 파일 읽기 오류: {e}")
        
        # 히스토리에 저장 (process.py 로직 참고)
        if db:
            try:
                # 현재 사용자의 히스토리 업데이트
                history = ConversionHistory.query.filter_by(job_id=job_id, user_id=user.id).first()
                if history:
                    history.notes_json = result_data
                    history.status = 'completed'
                    db.session.commit()
                    print(f"히스토리 업데이트 완료: job_id={job_id}, user_id={user.id}")
                else:
                    print(f"히스토리를 찾을 수 없음: job_id={job_id}, user_id={user.id}")
            except Exception as db_error:
                print(f"데이터베이스 업데이트 오류: {db_error}")
                db.session.rollback()
        
        return jsonify({
            "message": "Post-processing completed successfully",
            "processed_slides": sleep_slides,
            "result": result_data
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Post-processing failed: {str(e)}"}), 500