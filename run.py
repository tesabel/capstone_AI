"""
통합 서버 실행 스크립트
Flask API 서버와 WebSocket 스트리밍 서버를 동시에 실행합니다.
"""

import os
import time
from multiprocessing import Process
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

def run_flask_process():
    """Flask 서버를 별도 프로세스로 실행"""
    os.system("python server.py")

def run_websocket_process():
    """WebSocket 서버를 별도 프로세스로 실행"""
    os.system("python streaming_server.py")

def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("🎓 Smart Lecture Note 서버 시작")
    print("=" * 60)
    
    # 환경 설정 확인
    flask_host = os.getenv('FLASK_HOST', '0.0.0.0')
    flask_port = os.getenv('FLASK_PORT', '8000')
    
    print(f"📡 Flask API 서버: http://{flask_host}:{flask_port}")
    print(f"🔗 WebSocket 서버: ws://0.0.0.0:8001")
    print("=" * 60)
    
    try:
        # Flask 서버 프로세스 시작
        flask_process = Process(target=run_flask_process)
        flask_process.start()
        
        # 잠시 대기 후 WebSocket 서버 시작
        time.sleep(2)
        websocket_process = Process(target=run_websocket_process)
        websocket_process.start()
        
        print("모든 서버가 시작되었습니다.")
        print("\n종료하려면 Ctrl+C를 누르세요...")
        
        # 프로세스 대기
        flask_process.join()
        websocket_process.join()
        
    except KeyboardInterrupt:
        print("\n 서버 종료 중...")
        
        # 프로세스 종료
        if 'flask_process' in locals():
            flask_process.terminate()
            flask_process.join()
        
        if 'websocket_process' in locals():
            websocket_process.terminate()
            websocket_process.join()
        
        print("✅\ 모든 서버가 종료되었습니다.")
    
    except Exception as e:
        print(f" 오류 발생: {e}")

if __name__ == "__main__":
    main()