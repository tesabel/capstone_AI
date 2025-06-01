"""
데이터베이스 설정 스크립트
MySQL 데이터베이스와 테이블을 설정합니다.
"""

import os
import sys
import mysql.connector
from mysql.connector import Error

def create_database():
    """MySQL 데이터베이스 생성"""
    try:
        # MySQL 연결 (데이터베이스 없이)
        connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password=''  # 비밀번호가 있다면 여기에 입력
        )
        
        if connection.is_connected():
            cursor = connection.cursor()
            
            # 데이터베이스 생성
            cursor.execute("CREATE DATABASE IF NOT EXISTS smart_lecture_note CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print("✅ 데이터베이스 'smart_lecture_note' 생성 완료")
            
            # 데이터베이스 선택
            cursor.execute("USE smart_lecture_note")
            print("✅ 데이터베이스 선택 완료")
            
            # 기존 테이블 삭제 (외래 키 제약 조건을 고려한 순서)
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")  # 외래 키 체크 비활성화
            
            # 참조하는 테이블 먼저 삭제
            cursor.execute("DROP TABLE IF EXISTS process_history")
            cursor.execute("DROP TABLE IF EXISTS process_status")
            cursor.execute("DROP TABLE IF EXISTS conversion_history")
            cursor.execute("DROP TABLE IF EXISTS lectures")
            cursor.execute("DROP TABLE IF EXISTS history")
            
            # users 테이블 삭제
            cursor.execute("DROP TABLE IF EXISTS users")
            
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")  # 외래 키 체크 다시 활성화
            print("✅ 기존 테이블 삭제 완료")
            
            # users 테이블 생성
            cursor.execute("""
                CREATE TABLE users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_login DATETIME
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            
            # conversion_history 테이블 생성
            cursor.execute("""
                CREATE TABLE conversion_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    job_id VARCHAR(100) UNIQUE NOT NULL,
                    filename VARCHAR(255) NOT NULL,
                    notes_json JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(50) DEFAULT 'pending',
                    FOREIGN KEY (user_id) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            
            print("✅ 테이블 생성 완료")
            
    except Error as e:
        print(f"❌ MySQL 연결 오류: {e}")
        print("\n💡 해결 방법:")
        print("1. MySQL이 설치되어 있는지 확인하세요")
        print("2. MySQL 서비스가 실행 중인지 확인하세요")
        print("3. root 사용자의 비밀번호가 설정되어 있다면 스크립트를 수정하세요")
        return False
    
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
    
    return True

def test_connection():
    """데이터베이스 연결 테스트"""
    try:
        connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password='',
            database='smart_lecture_note'
        )
        
        if connection.is_connected():
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            print(f"✅ 연결 테스트 성공 - 현재 사용자 수: {user_count}")
            
    except Error as e:
        print(f"❌ 연결 테스트 실패: {e}")
        return False
    
    finally:
        if 'connection' in locals() and connection.is_connected():
            cursor.close()
            connection.close()
    
    return True

def main():
    """메인 실행 함수"""
    print("🚀 데이터베이스 설정을 시작합니다...\n")
    
    # 1. 데이터베이스 생성 및 테이블 설정
    print("1️⃣ 데이터베이스 및 테이블 생성 중...")
    if not create_database():
        print("❌ 데이터베이스 생성 실패")
        sys.exit(1)
    print()
    
    # 2. 연결 테스트
    print("2️⃣ 연결 테스트 중...")
    if not test_connection():
        print("❌ 연결 테스트 실패")
        sys.exit(1)
    print()
    
    print("🎉 데이터베이스 설정이 완료되었습니다!")
    print("\n📝 다음 단계:")
    print("1. pip install -r requirements.txt 실행")
    print("2. python api_server.py 실행")
    print("3. 브라우저에서 http://localhost:8000 접속")

if __name__ == "__main__":
    main()