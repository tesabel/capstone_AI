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
from src.image_captioning import image_captioning
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

@realtime_bp.route('/real-time-process/<job_id>', methods=['POST'])
def real_time_process(job_id):
    """실시간 오디오 청크 처리"""
    try:
        # 디렉토리 확인
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        if not os.path.exists(job_dir):
            return jsonify({"error": "Job not found"}), 404
        
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
        
        # STT 처리
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

@realtime_bp.route('/result/<job_id>', methods=['GET'])
def get_realtime_result(job_id):
    """실시간 처리 결과 조회"""
    try:
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        if not os.path.exists(job_dir):
            return jsonify({"error": "Job not found"}), 404
        
        result_data = load_or_create_result_json(job_dir)
        return jsonify(result_data), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@realtime_bp.route('/stop/<job_id>', methods=['POST'])
def stop_realtime(job_id):
    """실시간 처리 종료"""
    try:
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        if not os.path.exists(job_dir):
            return jsonify({"error": "Job not found"}), 404
        
        # 최종 결과 정리 및 저장
        result_data = load_or_create_result_json(job_dir)
        
        # 종료 시점 정보 추가
        result_data["_metadata"] = {
            "ended_at": datetime.now().isoformat(),
            "status": "stopped"
        }
        
        save_result_json(job_dir, result_data)
        
        return jsonify({
            "message": "Realtime processing stopped",
            "result": result_data
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@realtime_bp.route('/reset/<job_id>', methods=['POST'])
def reset_realtime(job_id):
    """실시간 처리 초기화"""
    try:
        job_dir = os.path.join(UPLOAD_FOLDER, job_id)
        if not os.path.exists(job_dir):
            return jsonify({"error": "Job not found"}), 404
        
        # 빈 결과로 초기화
        empty_result = {}
        save_result_json(job_dir, empty_result)
        
        return jsonify({
            "message": "Realtime processing reset",
            "result": empty_result
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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