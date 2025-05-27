from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# 업로드된 파일을 저장할 기본 디렉토리
DATA_DIR = 'file'

def create_job_directory(job_id):
    """jobId에 해당하는 디렉토리 구조 생성"""
    job_dir = os.path.join(DATA_DIR, job_id)
    audio_dir = os.path.join(job_dir, 'audio')
    
    os.makedirs(job_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)
    
    return job_dir, audio_dir

@app.route('/api/realTime/start-realtime', methods=['POST'])
def start_realtime():
    """실시간 변환 시작 엔드포인트"""
    try:
        # jobId 생성 (현재시간_초)
        now = datetime.now()
        job_id = now.strftime("%Y%m%d_%H%M%S")
        
        # 디렉토리 생성
        job_dir, _ = create_job_directory(job_id)
        
        # PDF 파일 저장
        if 'doc_file' in request.files:
            pdf_file = request.files['doc_file']
            if pdf_file.filename:
                filename = secure_filename(pdf_file.filename)
                pdf_path = os.path.join(job_dir, filename)
                pdf_file.save(pdf_path)
        
        return jsonify({"jobId": job_id}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/realTime/real-time-process/<job_id>', methods=['POST'])
def real_time_process(job_id):
    """실시간 처리 엔드포인트"""
    try:
        # 디렉토리 확인 및 생성
        job_dir = os.path.join(DATA_DIR, job_id)
        audio_dir = os.path.join(job_dir, 'audio')
        
        if not os.path.exists(job_dir):
            return jsonify({"error": "Job ID not found"}), 404
        
        os.makedirs(audio_dir, exist_ok=True)
        
        # 오디오 파일 저장
        if 'audio_file' in request.files:
            audio_file = request.files['audio_file']
            if audio_file.filename:
                # 현재 시간으로 오디오 파일명 생성
                now = datetime.now()
                audio_filename = f"audio_{now.strftime('%Y%m%d_%H%M%S')}.wav"
                audio_path = os.path.join(audio_dir, audio_filename)
                audio_file.save(audio_path)
        
        # 메타 JSON 저장
        if 'meta_json' in request.form:
            meta_json = request.form['meta_json']
            try:
                meta_data = json.loads(meta_json)
                # 현재 시간으로 JSON 파일명 생성
                now = datetime.now()
                json_filename = f"meta_{now.strftime('%Y%m%d_%H%M%S')}.json"
                json_path = os.path.join(job_dir, json_filename)
                
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(meta_data, f, ensure_ascii=False, indent=2)
                    
            except json.JSONDecodeError:
                return jsonify({"error": "Invalid JSON format"}), 400
        
        # 테스트 응답 반환
        test_response = {
            "slide4": {
                "Concise Summary Notes": "",
                "Bullet Point Notes": "",
                "Keyword Notes": "",
                "Chart/Table Summary": {
                    "주제": "Computer System Structure",
                    "부주제": "Hardware"
                },
                "Segments": {
                    "segment6": {
                        "text": "테스트 성공!!!",
                        "isImportant": "false"
                    }
                }
            }
        }
        
        return jsonify(test_response), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # data 디렉토리가 없으면 생성
    os.makedirs(DATA_DIR, exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=8000)