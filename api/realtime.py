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
from src.summary import create_summary

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
                    # skip_image_captioning = os.getenv('SKIP_IMAGECAPTIONING', 'false').lower() == 'true'
                    skip_image_captioning = filename == 'cry_demo.pdf'
                    print(f"skip_image_captioning: {skip_image_captioning}")    
                    if skip_image_captioning:
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
        
        # 세그먼트가 없는 슬라이드 필터링
        valid_sleep_slides = []
        for slide_num in sleep_slides:
            slide_key = f"slide{slide_num}"
            
            # 슬라이드가 result_data에 없거나 Segments가 없는 경우 건너뛰기
            if slide_key not in result_data or "Segments" not in result_data[slide_key]:
                print(f"슬라이드 {slide_num}에 세그먼트가 없어 처리에서 제외됩니다.")
                continue
                
            # 해당 슬라이드의 텍스트 추출
            slide_text = ""
            if "Segments" in result_data[slide_key]:
                for segment_data in result_data[slide_key]["Segments"].values():
                    slide_text += segment_data.get("text", "") + " "
            
            # 텍스트가 비어있는 경우 건너뛰기
            if not slide_text.strip():
                print(f"슬라이드 {slide_num}의 텍스트가 비어있어 처리에서 제외됩니다.")
                continue
                
            valid_sleep_slides.append(slide_num)
        
        # 유효한 슬라이드가 없는 경우
        if not valid_sleep_slides:
            return jsonify({
                "message": "No valid slides to process",
                "processed_slides": [],
                "result": result_data
            }), 200
            
        print(f"처리할 유효한 슬라이드: {valid_sleep_slides}")
        
        # 각 sleep slide에 대해 후처리 수행
        for slide_num in valid_sleep_slides:
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
            segments = segment_split(
                stt_data,
                alpha = -100,
                seg_cnt = -1,
                post_process = False)
            
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
                
                # 2. 이동할 세그먼트들을 대상 슬라이드별로 그룹화
                segments_by_target = {}
                for move_info in segments_to_move:
                    target_slide_num = move_info["target_slide"]
                    if target_slide_num not in segments_by_target:
                        segments_by_target[target_slide_num] = []
                    segments_by_target[target_slide_num].append(move_info)
                
                # 3. 각 대상 슬라이드별로 세그먼트들을 올바른 순서로 추가
                for target_slide_num, target_segments in segments_by_target.items():
                    target_slide_key = f"slide{target_slide_num}"
                    target_main_segment_key = f"segment{target_slide_num}"
                    
                    print(f"slide{target_slide_num}로 이동할 세그먼트 {len(target_segments)}개 처리")
                    
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
                    
                    # 이동할 세그먼트들의 텍스트를 순서대로 결합
                    segments_texts = [seg["text"] for seg in target_segments]
                    combined_segments_text = " ".join(segments_texts)
                    
                    # 텍스트 추가 위치 결정
                    if target_slide_num < slide_num:
                        # 앞 슬라이드: 뒷부분에 추가 (순서 유지)
                        new_text = existing_text + " " + combined_segments_text if existing_text else combined_segments_text
                        print(f"앞 슬라이드 slide{target_slide_num}에 순서 유지하여 추가")
                    elif target_slide_num > slide_num:
                        # 뒷 슬라이드: 앞부분에 추가 (순서 유지)
                        new_text = combined_segments_text + " " + existing_text if existing_text else combined_segments_text
                        print(f"뒷 슬라이드 slide{target_slide_num}에 순서 유지하여 추가")
                    else:
                        # 같은 슬라이드 (이미 위에서 처리됨)
                        continue
                    
                    # 텍스트 업데이트
                    result_data[target_slide_key]["Segments"][target_main_segment_key]["text"] = new_text.strip()
                    print(f"slide{target_slide_num} 업데이트 완료, 추가된 세그먼트: {len(target_segments)}개, 최종 텍스트 길이: {len(new_text)}")
                
                print(f"slide {slide_num} 전체 처리 완료")
                
            except Exception as e:
                print(f"후처리 오류 (slide {slide_num}): {str(e)}")
                continue
        
        print("후처리 완료, 요약 생성 시작...")
        
        # 매핑된 세그먼트들을 segment_mapping 형식으로 변환 (meta 타입 제외)
        mapped_segments_for_summary = {}
        for slide_key, slide_data in result_data.items():
            if slide_key == "slide0" or "Segments" not in slide_data:
                continue
            
            # 해당 슬라이드의 type 확인
            slide_number = int(slide_key.replace("slide", ""))
            if slide_number <= len(captioning_data):
                slide_caption = captioning_data[slide_number - 1]
                slide_type = slide_caption.get("type", "")
                
                # meta 타입 슬라이드는 요약 생성에서 제외
                if slide_type == "meta":
                    print(f"{slide_key}는 meta 타입이므로 요약 생성 대상에서 제외합니다")
                    continue
                
            mapped_segments_for_summary[slide_key] = {
                "Segments": slide_data["Segments"]
            }
        
        # 요약 생성
        try:
            def summary_progress_callback(current_slide, total_slides):
                print(f"요약 생성 중: {current_slide}/{total_slides}")
            
            print(f"요약 생성 대상 슬라이드: {list(mapped_segments_for_summary.keys())}")
            summary_notes = create_summary(
                captioning_data, 
                mapped_segments_for_summary, 
                progress_callback=summary_progress_callback
            )
            print("요약 생성 완료")
            
            # 최종 결과 구성 (process.py 패턴 참고)
            final_result = {}
            for slide_key in mapped_segments_for_summary.keys():
                if slide_key == "slide0":
                    continue
                    
                slide_number = int(slide_key.replace("slide", ""))
                if slide_number > len(captioning_data):
                    continue

                # 해당 슬라이드의 캡셔닝 데이터에서 type 확인
                slide_caption = captioning_data[slide_number - 1]
                slide_type = slide_caption.get("type", "")
                
                # meta 타입 슬라이드는 요약 생성 건너뛰기
                if slide_type == "meta":
                    print(f"{slide_key}는 meta 타입이므로 요약 생성을 건너뜁니다")
                    # 세그먼트만 포함하고 요약은 빈 값으로 설정
                    segments = mapped_segments_for_summary[slide_key].get("Segments", {})
                    final_result[slide_key] = {
                        "Concise Summary Notes": "",
                        "Bullet Point Notes": "",
                        "Keyword Notes": "",
                        "Chart/Table Summary": "",
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
                    continue

                # 일반 슬라이드의 경우 요약 생성
                # 세그먼트 데이터
                segments = mapped_segments_for_summary[slide_key].get("Segments", {})
                
                # 요약 데이터
                summary = summary_notes.get(slide_key, {}) if summary_notes else {}
                
                # 최종 결과 구성
                final_result[slide_key] = {
                    "Concise Summary Notes": summary.get("Concise Summary Notes", ""),
                    "Bullet Point Notes": summary.get("Bullet Point Notes", ""),
                    "Keyword Notes": summary.get("Keyword Notes", ""),
                    "Chart/Table Summary": summary.get("Chart/Table Summary", ""),
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
            
            # 기존 result_data에서 요약이 없는 슬라이드들도 유지 (meta 타입 포함)
            for slide_key, slide_data in result_data.items():
                if slide_key not in final_result:
                    # meta 타입이거나 기타 슬라이드들은 그대로 유지
                    final_result[slide_key] = slide_data
            
            # final_result로 교체
            result_data = final_result
            print(f"최종 result 구성 완료, 슬라이드 수: {len(result_data)}")
            
        except Exception as e:
            print(f"요약 생성 오류: {str(e)}")
            print("요약 없이 세그먼트 매핑 결과만 저장합니다")
        
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
            "processed_slides": valid_sleep_slides,
            "result": result_data
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Post-processing failed: {str(e)}"}), 500

@realtime_bp.route('/move-segment', methods=['POST', 'OPTIONS'])
def move_segment_endpoint():
    """
    특정 텍스트 세그먼트를 다른 슬라이드로 이동하거나 삭제하는 API
    
    동작 설명:
    - 슬라이드 간 세그먼트를 '이동'하는 기능
    - 세그먼트를 새로 추가하지 않고, 기존 세그먼트의 텍스트 내부에 덧붙이는 방식으로 처리
    - 슬라이드당 세그먼트가 하나라는 구조를 가정하고 있음 (segmentN)
    
    유의사항:
    - 이동 대상 슬라이드가 현재보다 앞이면 → 타겟 슬라이드의 가장 마지막 세그먼트의 맨 뒤에 텍스트를 추가
    - 이동 대상 슬라이드가 현재보다 뒤이면 → 타겟 슬라이드의 가장 첫 세그먼트의 맨 앞에 텍스트를 삽입
    - 삭제 요청(targetSlide == 0)일 경우 → 단순히 시작 슬라이드에서 해당 텍스트만 제거하고 종료
    """
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
        start_slide = request.json.get('startSlide')
        target_slide = request.json.get('targetSlide')
        text_to_move = request.json.get('text')
        
        print(f"move-segment 요청: jobId={job_id}, startSlide={start_slide}, targetSlide={target_slide}")
        print(f"이동할 텍스트: '{text_to_move[:50]}...' (길이: {len(text_to_move)})")
        
        # 필수 파라미터 확인
        if not all([job_id, start_slide is not None, target_slide is not None, text_to_move]):
            return jsonify({"error": "jobId, startSlide, targetSlide, text are required"}), 400
        
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
        
        # 기존 result.json 로드
        with open(result_path, 'r', encoding='utf-8') as f:
            result_data = json.load(f)
        
        # 시작 슬라이드 키와 세그먼트 키 생성
        start_slide_key = f"slide{start_slide}"
        start_segment_key = f"segment{start_slide}"
        
        # 시작 슬라이드 확인
        if start_slide_key not in result_data:
            return jsonify({"error": f"Start slide {start_slide} not found"}), 404
        
        if "Segments" not in result_data[start_slide_key] or start_segment_key not in result_data[start_slide_key]["Segments"]:
            return jsonify({"error": f"Segment not found in slide {start_slide}"}), 404
        
        # 시작 슬라이드의 현재 텍스트
        current_text = result_data[start_slide_key]["Segments"][start_segment_key]["text"]
        
        # 이동할 텍스트가 실제로 포함되어 있는지 확인
        if text_to_move not in current_text:
            return jsonify({"error": "Text to move not found in the source segment"}), 404
        
        # 시작 슬라이드에서 해당 텍스트 제거
        updated_start_text = current_text.replace(text_to_move, "").strip()
        # 연속된 공백 제거
        updated_start_text = " ".join(updated_start_text.split())
        
        result_data[start_slide_key]["Segments"][start_segment_key]["text"] = updated_start_text
        print(f"시작 슬라이드 {start_slide}에서 텍스트 제거 완료")
        
        # 삭제 요청인 경우 (targetSlide == 0)
        if target_slide == 0:
            print("삭제 요청 - 텍스트만 제거하고 종료")
        else:
            # 이동 요청인 경우
            target_slide_key = f"slide{target_slide}"
            target_segment_key = f"segment{target_slide}"
            
            # 타겟 슬라이드가 없으면 생성
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
            
            # 타겟 세그먼트가 없으면 생성
            if target_segment_key not in result_data[target_slide_key]["Segments"]:
                result_data[target_slide_key]["Segments"][target_segment_key] = {
                    "text": "",
                    "isImportant": "false",
                    "reason": "",
                    "linkedConcept": "",
                    "pageNumber": ""
                }
            
            # 타겟 슬라이드의 현재 텍스트
            target_current_text = result_data[target_slide_key]["Segments"][target_segment_key]["text"]
            
            # 텍스트 추가 위치 결정
            if target_slide < start_slide:
                # 앞 슬라이드: 맨 뒤에 추가
                new_text = target_current_text + " " + text_to_move if target_current_text else text_to_move
                print(f"앞 슬라이드 {target_slide}의 뒤에 텍스트 추가")
            else:
                # 뒷 슬라이드: 맨 앞에 추가
                new_text = text_to_move + " " + target_current_text if target_current_text else text_to_move
                print(f"뒷 슬라이드 {target_slide}의 앞에 텍스트 추가")
            
            # 타겟 슬라이드 업데이트
            result_data[target_slide_key]["Segments"][target_segment_key]["text"] = new_text.strip()
            print(f"타겟 슬라이드 {target_slide} 업데이트 완료")
        
        # 수정된 result.json 저장
        print(f"result.json 저장 중: {result_path}")
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        
        # 저장 확인
        if os.path.exists(result_path):
            file_size = os.path.getsize(result_path)
            print(f"result.json 저장 완료, 파일 크기: {file_size} bytes")
        
        # 히스토리에 저장
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
        
        action = "deleted" if target_slide == 0 else "moved"
        return jsonify({
            "message": f"Segment {action} successfully",
            "startSlide": start_slide,
            "targetSlide": target_slide,
            "action": action,
            "result": result_data
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Move segment failed: {str(e)}"}), 500