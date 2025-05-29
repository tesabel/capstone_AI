from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from datetime import datetime
from werkzeug.utils import secure_filename
from src.image_captioning import image_captioning
from src.realtime_convert_audio import transcribe_audio_with_timestamps
import shutil

class Config:
    """설정 클래스"""
    SKIP_IMAGE_CAPTIONING = True
    DEFAULT_CAPTIONING_PATH = 'data/image_captioning/image_captioning.json'

app = Flask(__name__)
CORS(app)

# 업로드된 파일을 저장할 기본 디렉토리
DATA_DIR = 'file'

def create_job_directory(job_id):
    """jobId에 해당하는 디렉토리 구조 생성"""
    job_dir = os.path.join(DATA_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return job_dir

@app.route('/api/realTime/start-realtime', methods=['POST'])
def start_realtime():
    """실시간 변환 시작 엔드포인트"""
    try:
        # jobId 생성 (현재시간_초)
        now = datetime.now()
        job_id = now.strftime("%Y%m%d_%H%M%S")
        
        # 디렉토리 생성
        job_dir = create_job_directory(job_id)
        
        # PDF 파일 저장
        if 'doc_file' not in request.files:
            return jsonify({"error": "No PDF file provided"}), 400
            
        pdf_file = request.files['doc_file']
        if not pdf_file.filename:
            return jsonify({"error": "No selected file"}), 400
            
        filename = secure_filename(pdf_file.filename)
        pdf_path = os.path.join(job_dir, filename)
        pdf_file.save(pdf_path)
        
        if Config.SKIP_IMAGE_CAPTIONING:
            # 기존 캡셔닝 결과 파일 복사
            result_path = os.path.join(job_dir, "captioning_results.json")
            shutil.copy2(Config.DEFAULT_CAPTIONING_PATH, result_path)
            
            return jsonify({
                "jobId": job_id,
                "message": "PDF processing completed and default captioning results copied"
            }), 200
        else:
            # 이미지 캡셔닝 수행
            try:
                captioning_results = image_captioning(pdf_path)
                
                # 결과를 JSON 파일로 저장
                result_path = os.path.join(job_dir, "captioning_results.json")
                with open(result_path, 'w', encoding='utf-8') as f:
                    json.dump(captioning_results, f, ensure_ascii=False, indent=2)
                    
                return jsonify({
                    "jobId": job_id,
                    "message": "PDF processing and image captioning completed successfully"
                }), 200
                
            except Exception as e:
                return jsonify({"error": f"Image captioning failed: {str(e)}"}), 500
        
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

@app.route('/api/realTime/real-time-process/<job_id>', methods=['POST'])
def real_time_process(job_id):
    """실시간 처리 엔드포인트"""
    try:
        # 디렉토리 확인 및 생성
        job_dir = os.path.join(DATA_DIR, job_id)
        
        if not os.path.exists(job_dir):
            return jsonify({"error": "Job ID not found"}), 404
        
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
                    
                    # 누적된 결과 반환
                    return jsonify(result_data), 200
        
        # 오디오나 메타데이터가 없을 경우 기존 결과 반환
        result_data = load_or_create_result_json(job_dir)
        return jsonify(result_data), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # data 디렉토리가 없으면 생성
    os.makedirs(DATA_DIR, exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=8000)