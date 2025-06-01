"""
Flask + WebSocket 서버 동시 실행 스크립트

기존 Flask 서버와 새로운 WebSocket 스트리밍 서버를 동시에 실행합니다.
"""

import subprocess
import sys
import os
import signal
import time
from multiprocessing import Process

def run_flask_server():
    """Flask 서버 실행"""
    print("[Flask] 서버 시작 중... (포트: 8000)")
    try:
        subprocess.run([sys.executable, "flask_server.py"], cwd=os.getcwd())
    except KeyboardInterrupt:
        print("[Flask] 서버 종료")
    except Exception as e:
        print(f"[Flask] 서버 오류: {e}")

def run_websocket_server():
    """WebSocket 서버 실행"""
    print("[WebSocket] 스트리밍 서버 시작 중... (포트: 8001)")
    try:
        subprocess.run([sys.executable, "streaming_server.py"], cwd=os.getcwd())
    except KeyboardInterrupt:
        print("[WebSocket] 서버 종료")
    except Exception as e:
        print(f"[WebSocket] 서버 오류: {e}")

def signal_handler(signum, frame):
    """시그널 핸들러 (Ctrl+C 처리)"""
    print("\n\n서버들을 종료하는 중...")
    sys.exit(0)

def main():
    """메인 실행 함수"""
    print("=== Capstone AI 서버 시작 ===")
    print("Flask 서버: http://localhost:8000")
    print("WebSocket 서버: ws://localhost:8001")
    print("종료하려면 Ctrl+C를 누르세요.\n")
    
    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 각 서버를 별도 프로세스로 실행
    flask_process = Process(target=run_flask_server)
    websocket_process = Process(target=run_websocket_server)
    
    try:
        # 서버 시작
        flask_process.start()
        time.sleep(2)  # Flask 서버가 먼저 시작되도록 잠시 대기
        websocket_process.start()
        
        print("두 서버가 모두 시작되었습니다!\n")
        
        # 프로세스 종료 대기
        flask_process.join()
        websocket_process.join()
        
    except KeyboardInterrupt:
        print("\n서버 종료 중...")
    finally:
        # 프로세스 정리
        if flask_process.is_alive():
            flask_process.terminate()
            flask_process.join(timeout=5)
            if flask_process.is_alive():
                flask_process.kill()
        
        if websocket_process.is_alive():
            websocket_process.terminate()
            websocket_process.join(timeout=5)
            if websocket_process.is_alive():
                websocket_process.kill()
        
        print("모든 서버가 종료되었습니다.")

if __name__ == "__main__":
    main()