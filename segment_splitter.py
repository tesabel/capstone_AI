#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
CLOVA Studio 문단 나누기 API를 이용한 텍스트 세그먼트 분리 도구

이 스크립트는 CLOVA Studio의 세그먼테이션 API를 사용해 텍스트 파일을 
의미론적으로 연관된 세그먼트(문단)로 분리합니다.
"""

import os
import json
import requests
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()

class ClovaSegmenter:
    """CLOVA Studio API를 사용하여 텍스트를 세그먼트로 분리하는 클래스"""
    
    def __init__(self, api_key: Optional[str] = None):
        """초기화 함수
        
        Args:
            api_key: CLOVA Studio API 키. None인 경우 환경 변수에서 로드
        """
        self.api_key = api_key or os.getenv('CLOVA_API_KEY')
        if not self.api_key:
            raise ValueError("CLOVA_API_KEY가 제공되지 않았습니다. .env 파일에 설정하거나 인자로 전달해주세요.")
        
        self.api_url = "https://clovastudio.stream.ntruss.com/testapp/v1/api-tools/segmentation"
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
    
    def segment_text(self, 
                    text: str, 
                    alpha: float = -100,
                    seg_cnt: int = -1, 
                    post_process: bool = False,
                    max_size: int = 1000, 
                    min_size: int = 300) -> Dict[str, Any]:
        """텍스트를 세그먼트로 분리합니다.
        
        Args:
            text: 분리할 텍스트
            alpha: 세그먼트 분리 임계값 (-100 또는 -1.5~1.5)
            seg_cnt: 세그먼트 수 (-1 또는 1 이상)
            post_process: 후처리 여부
            max_size: 후처리 시 최대 문단 크기
            min_size: 후처리 시 최소 문단 크기
            
        Returns:
            API 응답 결과 딕셔너리
        """
        payload = {
            "text": text,
            "alpha": alpha,
            "segCnt": seg_cnt,
            "postProcess": post_process,
            "postProcessMaxSize": max_size,
            "postProcessMinSize": min_size
        }
        
        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload)
            response.raise_for_status()
            
            result = response.json()
            
            # API 오류 확인
            if 'status' in result and result['status']['code'] != '20000':
                error_msg = result['status'].get('message', '알 수 없는 오류')
                return {"error": f"API 오류: {error_msg}"}
            
            return result
            
        except requests.exceptions.RequestException as e:
            return {"error": f"API 요청 오류: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "응답을 JSON으로 파싱할 수 없습니다."}
        except Exception as e:
            return {"error": f"알 수 없는 오류: {str(e)}"}

def main(skip_stt: bool = True) -> Dict[str, Any]:
    """메인 함수
    
    Args:
        skip_stt: STT 변환을 건너뛸지 여부
        
    Returns:
        세그먼트 분리 결과
    """
    try:
        text = ""  # text 변수 초기화
        
        # STT 결과 파일 경로
        stt_result_path = "data/STT_result/stt_result.json"
        
        # STT 결과 읽기
        if skip_stt:
            if not os.path.exists(stt_result_path):
                raise FileNotFoundError(f"STT 결과 파일을 찾을 수 없습니다: {stt_result_path}")
            
            with open(stt_result_path, 'r', encoding='utf-8') as f:
                stt_data = json.load(f)
                text = stt_data.get('text', '')  # 'text' 키 사용
        else:
            # STT 함수 호출
            from convert_audio import transcribe_audio  # convert_audio 모듈 import
            stt_result = transcribe_audio()  # STT 함수 호출
            if stt_result:
                text = stt_result.get('text', '')  # 'text' 키 사용
            else:
                raise ValueError("STT 변환 결과를 가져오는데 실패했습니다.")
        
        if not text:
            raise ValueError("처리할 텍스트가 없습니다.")
        
        # CLOVA API 호출
        segmenter = ClovaSegmenter()
        response = segmenter.segment_text(
            text=text,
            alpha=0.5,
            seg_cnt=-1,
            post_process=True,
            max_size=2000,
            min_size=200
        )
        
        # 오류 처리
        if "error" in response:
            raise Exception(response["error"])
        
        # 결과를 새로운 형식으로 변환
        if 'result' in response and 'topicSeg' in response['result']:
            segments = response['result']['topicSeg']
            formatted_result = []
            
            for i, segment in enumerate(segments, 1):
                segment_text = " ".join(segment)  # 세그먼트 내 문장들을 공백으로 연결
                formatted_result.append({
                    "id": i,
                    "text": segment_text
                })
            
            # 결과 저장
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            output_dir = "data/segment_split"
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"segment_split_{timestamp}.json")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(formatted_result, f, ensure_ascii=False, indent=2)
            
            return formatted_result
        else:
            raise ValueError("세그먼테이션 결과를 가져오는데 실패했습니다.")
            
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        return {"error": str(e)}

if __name__ == "__main__":
    main()