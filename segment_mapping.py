#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
세그먼트와 슬라이드를 매핑하는 도구

이 스크립트는 STT 결과와 이미지 캡셔닝 결과를 기반으로 
세그먼트와 슬라이드를 매핑합니다.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from openai import OpenAI
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()

# OpenAI 클라이언트 초기화
client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url="https://api.openai.com/v1"
)

def load_stt_result(skip_stt: bool = True) -> str:
    """STT 결과를 로드합니다.
    
    Args:
        skip_stt: STT 변환을 건너뛸지 여부
        
    Returns:
        STT 결과 텍스트
    """
    if skip_stt:
        stt_result_path = "data/STT_result/stt_result.json"
        if not os.path.exists(stt_result_path):
            raise FileNotFoundError(f"STT 결과 파일을 찾을 수 없습니다: {stt_result_path}")
        
        with open(stt_result_path, 'r', encoding='utf-8') as f:
            stt_data = json.load(f)
            return stt_data.get('text', '')
    else:
        from segment_splitter import main as segment_splitter_main
        result = segment_splitter_main(skip_stt=False)
        if isinstance(result, dict) and "error" in result:
            raise Exception(result["error"])
        return " ".join(segment["text"] for segment in result)

def load_image_captioning(skip_image_captioning: bool = True) -> List[Dict[str, Any]]:
    """이미지 캡셔닝 결과를 로드합니다.
    
    Args:
        skip_image_captioning: 이미지 캡셔닝을 건너뛸지 여부
        
    Returns:
        이미지 캡셔닝 결과 리스트
    """
    if skip_image_captioning:
        captioning_path = "data/image_captioning/image_captioning.json"
        if not os.path.exists(captioning_path):
            raise FileNotFoundError(f"이미지 캡셔닝 결과 파일을 찾을 수 없습니다: {captioning_path}")
        
        with open(captioning_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        from image_captioning import process_pdf
        return process_pdf(skip_segment_split=True)

def merge_segments(segments: List[Dict[str, Any]], 
                  max_segment_length: int,
                  min_segment_length: int) -> List[str]:
    """세그먼트를 메시지 단위로 병합합니다.
    
    Args:
        segments: 세그먼트 리스트
        max_segment_length: 최대 세그먼트 길이
        min_segment_length: 최소 세그먼트 길이
        
    Returns:
        병합된 메시지 리스트
    """
    merged_messages = []
    current_message = []
    current_length = 0
    
    for segment in segments:
        segment_text = f"Segment ID: {segment['id']}\n{segment['text']}\n"
        segment_length = len(segment_text)
        
        if current_length + segment_length > max_segment_length and current_message:
            merged_messages.append("".join(current_message))
            current_message = []
            current_length = 0
        
        current_message.append(segment_text)
        current_length += segment_length
    
    if current_message:
        if current_length < min_segment_length and merged_messages:
            merged_messages[-1] += "".join(current_message)
        else:
            merged_messages.append("".join(current_message))
    
    return merged_messages

def get_relevant_slides(slides: List[Dict[str, Any]], 
                       center_slide: int,
                       max_slide: int) -> List[Dict[str, Any]]:
    """중심 슬라이드를 기준으로 관련 슬라이드를 가져옵니다.
    
    Args:
        slides: 전체 슬라이드 리스트
        center_slide: 중심 슬라이드 번호
        max_slide: 최대 슬라이드 범위
        
    Returns:
        관련 슬라이드 리스트
    """
    start_idx = max(0, center_slide - max_slide)
    end_idx = min(len(slides), center_slide + max_slide + 1)
    
    relevant_slides = []
    for slide in slides[start_idx:end_idx]:
        if slide["type"] != "meta":
            relevant_slides.append(slide)
    
    return relevant_slides

def map_segments_to_slides(message: str, 
                         slides: List[Dict[str, Any]],
                         message_index: int,
                         total_messages: int,
                         start_slide: int,
                         end_slide: int) -> List[Dict[str, Any]]:
    """세그먼트를 슬라이드에 매핑합니다.
    
    Args:
        message: 병합된 세그먼트 메시지
        slides: 관련 슬라이드 리스트
        message_index: 현재 메시지 인덱스
        total_messages: 전체 메시지 수
        start_slide: 시작 슬라이드 번호
        end_slide: 종료 슬라이드 번호
        
    Returns:
        매핑 결과 리스트
    """
    try:
        # 디버깅 정보 출력
        print(f"\n[디버깅 정보]")
        print(f"메시지 {message_index + 1}/{total_messages}")
        print(f"슬라이드 범위: {start_slide} ~ {end_slide}")
        print(f"메시지 길이: {len(message)} 글자")
        
        messages = [
            {
                "role": "system",
                "content": "You are an assistant that maps lecture segments to their corresponding slides based on content similarity."
            },
            {
                "role": "user",
                "content": f"""Given these lecture segments and slide information, map each segment to its most likely slide.

Available slides:
{json.dumps(slides, indent=2, ensure_ascii=False)}

Segments to map:
{message}

Reply ONLY with a JSON array of mappings in this format:
[
  {{
    "segment_id": <segment number>,
    "slide_id": <slide number>
  }},
  ...
]"""
            }
        ]
        
        # API 요청 메시지 출력
        print("\n[API 요청 메시지]")
        print(json.dumps(messages, indent=2, ensure_ascii=False))
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            functions=[
                {
                    "name": "return_segment_mapping",
                    "description": "Maps lecture segments to their corresponding slides.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mappings": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "segment_id": {
                                            "type": "integer",
                                            "description": "The ID of the segment"
                                        },
                                        "slide_id": {
                                            "type": "integer",
                                            "description": "The ID of the slide this segment corresponds to"
                                        }
                                    },
                                    "required": ["segment_id", "slide_id"]
                                }
                            }
                        },
                        "required": ["mappings"]
                    }
                }
            ],
            function_call={"name": "return_segment_mapping"}
        )
        
        return json.loads(response.choices[0].message.function_call.arguments)["mappings"]
    except Exception as e:
        raise Exception(f"세그먼트 매핑 중 오류 발생: {str(e)}")

def main(skip_stt: bool = True,
         skip_image_captioning: bool = True,
         max_slide: int = 6,
         max_segment_length: int = 2000,
         min_segment_length: int = 500) -> List[Dict[str, Any]]:
    """메인 함수
    
    Args:
        skip_stt: STT 변환을 건너뛸지 여부
        skip_image_captioning: 이미지 캡셔닝을 건너뛸지 여부
        max_slide: 최대 슬라이드 범위
        max_segment_length: 최대 세그먼트 길이
        min_segment_length: 최소 세그먼트 길이
        
    Returns:
        매핑 결과 리스트
    """
    try:
        # STT 결과 로드
        text = load_stt_result(skip_stt)
        
        # 이미지 캡셔닝 결과 로드
        slides = load_image_captioning(skip_image_captioning)
        
        # 세그먼트 분리
        from segment_splitter import main as segment_splitter_main
        segments = segment_splitter_main(skip_stt=True)
        
        # 세그먼트 병합
        merged_messages = merge_segments(segments, max_segment_length, min_segment_length)
        
        # 세그먼트 매핑
        all_mappings = []
        center_slide = 1
        
        for i, message in enumerate(merged_messages):
            relevant_slides = get_relevant_slides(slides, center_slide, max_slide)
            start_slide = max(0, center_slide - max_slide)
            end_slide = min(len(slides), center_slide + max_slide)
            
            mappings = map_segments_to_slides(
                message=message,
                slides=relevant_slides,
                message_index=i,
                total_messages=len(merged_messages),
                start_slide=start_slide,
                end_slide=end_slide
            )
            all_mappings.extend(mappings)
            
            # 다음 중심 슬라이드 업데이트
            if mappings:
                max_slide_id = max(mapping["slide_id"] for mapping in mappings)
                center_slide = max_slide_id - 1
        
        # 결과 정렬
        all_mappings.sort(key=lambda x: x["segment_id"])
        
        # 결과 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_dir = "data/segment_mapping"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"segment_mapping_{timestamp}.json")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_mappings, f, ensure_ascii=False, indent=2)
        
        return all_mappings
        
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        return []

if __name__ == "__main__":
    main() 