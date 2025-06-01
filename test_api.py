#!/usr/bin/env python3
"""
API 서버 기능 테스트 스크립트
"""

import requests
import json
import time

# 서버 URL
BASE_URL = "http://localhost:8000"

def test_server_connection():
    """서버 연결 테스트"""
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def test_register():
    """회원가입 테스트"""
    data = {
        "email": "test@example.com",
        "password": "test1234",
        "name": "테스트 사용자"
    }
    
    response = requests.post(f"{BASE_URL}/api/auth/register", json=data)
    print(f"회원가입 응답: {response.status_code}")
    print(f"응답 내용: {response.json()}")
    
    return response.status_code in [201, 409]  # 성공 또는 이미 존재

def test_login():
    """로그인 테스트"""
    data = {
        "username": "test@example.com",
        "password": "test1234"
    }
    
    response = requests.post(f"{BASE_URL}/api/auth/login", data=data)
    print(f"로그인 응답: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"로그인 성공: {result}")
        return result.get("access_token")
    else:
        print(f"로그인 실패: {response.json()}")
        return None

def test_history(token):
    """히스토리 조회 테스트"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(f"{BASE_URL}/api/history/my", headers=headers)
    print(f"히스토리 조회 응답: {response.status_code}")
    
    if response.status_code == 200:
        history = response.json()
        print(f"히스토리 개수: {len(history)}")
        return True
    else:
        print(f"히스토리 조회 실패: {response.json()}")
        return False

def test_health_endpoint():
    """헬스 체크 엔드포인트 추가 테스트"""
    try:
        # 기본 루트 경로 테스트
        response = requests.get(f"{BASE_URL}/")
        print(f"루트 경로 응답: {response.status_code}")
        return True
    except Exception as e:
        print(f"헬스 체크 실패: {e}")
        return False

def main():
    """메인 테스트 실행"""
    print("🚀 API 서버 테스트 시작\n")
    
    # 1. 서버 연결 확인
    print("1️⃣ 서버 연결 확인...")
    if not test_health_endpoint():
        print("❌ 서버가 실행되지 않고 있습니다.")
        print("💡 먼저 'python api_server.py'를 실행하세요.")
        return
    print("✅ 서버 연결 성공\n")
    
    # 2. 회원가입 테스트
    print("2️⃣ 회원가입 테스트...")
    if not test_register():
        print("❌ 회원가입 실패")
        return
    print("✅ 회원가입 성공\n")
    
    # 3. 로그인 테스트
    print("3️⃣ 로그인 테스트...")
    token = test_login()
    if not token:
        print("❌ 로그인 실패")
        return
    print("✅ 로그인 성공\n")
    
    # 4. 히스토리 조회 테스트
    print("4️⃣ 히스토리 조회 테스트...")
    if not test_history(token):
        print("❌ 히스토리 조회 실패")
        return
    print("✅ 히스토리 조회 성공\n")
    
    print("🎉 모든 API 테스트 통과!")
    print("\n📝 추가 테스트 방법:")
    print("1. Postman으로 파일 업로드 테스트")
    print("2. 프론트엔드와 연동 테스트")
    print("3. 실시간 변환 WebSocket 테스트")

if __name__ == "__main__":
    main()