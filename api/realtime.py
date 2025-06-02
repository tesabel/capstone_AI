"""
실시간 처리 API  
실시간 오디오 스트리밍 및 슬라이드별 음성 인식 결과를 처리하는 API
"""

import os
import json
import uuid
from datetime import datetime
from dotenv import load_dotenv

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

# .env 파일 로드
load_dotenv()

# 기존 모듈 import
from src.image_captioning import image_captioning, convert_pdf_to_images
from src.realtime_convert_audio import transcribe_audio_with_timestamps

# Blueprint 생성
realtime_bp = Blueprint('realtime', __name__)

# 업로드 디렉토리 설정
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'file')
DEFAULT_CAPTIONING_PATH = 'data/image_captioning/image_captioning.json'

def generate_job_id():
    """고유한 job_id 생성"""
    now = datetime.now()
    return now.strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]

@realtime_bp.route('/start-realtime', methods=['POST'])
def start_realtime():
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
                return jsonify({"image_urls": image_urls}), 200
            else:
                raise Exception("No images were successfully saved")
                
        except Exception as convert_error:
            print(f"[ERROR] PDF conversion failed: {convert_error}")
            raise Exception(f"PDF to image conversion failed: {str(convert_error)}")
        
    except Exception as e:
        return jsonify({"error": f"Failed to convert PDF to images: {str(e)}"}), 500