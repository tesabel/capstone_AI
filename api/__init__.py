"""
API 패키지 초기화 모듈
Flask Blueprint들을 등록하고 관리하는 모듈
"""

from flask import Flask
from .process import process_bp
from .history import history_bp  
from .realtime import realtime_bp

def register_blueprints(app: Flask):
    """Flask 앱에 모든 Blueprint를 등록"""
    
    # 비실시간 처리 API
    app.register_blueprint(process_bp, url_prefix='/api/process')
    
    # 히스토리 관리 API
    app.register_blueprint(history_bp, url_prefix='/api/history')
    
    # 실시간 처리 API
    app.register_blueprint(realtime_bp, url_prefix='/api/realtime')
    
    print("모든 API Blueprint가 등록되었습니다:")
    print("- /api/process (비실시간 처리)")
    print("- /api/history (히스토리 관리)")
    print("- /api/realtime (실시간 처리)")