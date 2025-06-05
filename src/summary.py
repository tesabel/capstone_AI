import os
import json
import base64
import io
from datetime import datetime
from typing import Dict, List, Any
from dotenv import load_dotenv
from openai import OpenAI
from pdf2image import convert_from_path

# .env 파일에서 환경 변수 로드
load_dotenv()

# OpenAI 클라이언트 초기화
client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url="https://api.openai.com/v1"
)

def convert_pdf_to_images(pdf_path: str) -> List[str]:
    """PDF 파일을 이미지로 변환합니다.
    
    Args:
        pdf_path: PDF 파일 경로
        
    Returns:
        base64로 인코딩된 이미지 리스트
    """
    try:
        # PDF를 이미지로 변환
        images = convert_from_path(pdf_path)
        encoded_images = []
        
        for image in images:
            # 이미지를 JPEG로 변환
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='JPEG', quality=90)
            img_byte_arr = img_byte_arr.getvalue()
            
            # base64로 인코딩
            img_str = base64.b64encode(img_byte_arr).decode()
            encoded_images.append(img_str)
            
        return encoded_images
    except Exception as e:
        raise Exception(f"PDF 변환 중 오류 발생: {str(e)}")

def load_json_file(file_path: str) -> Dict[str, Any]:
    """JSON 파일을 로드합니다."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise Exception(f"JSON 파일 로드 중 오류 발생: {str(e)}")

def generate_summary(slide_data: Dict[str, Any], merged_segments: str) -> Dict[str, Any]:
    """단일 슬라이드에 대한 요약을 생성합니다."""
    prompt = fprompt = f"""
### Slide Analysis
Type: {slide_data['type']}
Title Keywords: {', '.join(slide_data['title_keywords'])}
Secondary Keywords: {', '.join(slide_data['secondary_keywords'])}
Detail: {slide_data['detail']}

### Matched Lecture Segments
{merged_segments}

## Writing Guidelines  ── FOLLOW EXACTLY
1. concise_summary  
   • 7–8 short sentences.  
   • **Bold** each core keyword once. 

2. bullet_points  
   • Use the "∙" bullet symbol.  
   • One sentence or phrase per bullet.  
   • End each bullet entry with (\n).

3. keywords  
   • About 10 entries in the form **Keyword** – (explanation).  
   • End each keyword entry with (\n).

4. chart_summary  
   • Provide a table / step list if meaningful; otherwise write "Omitted".  


## Example
concise_summary
Operating systems manage **resources**, provide **abstraction**, and ensure **security**. They coordinate **processes** and **threads**, ...
bullet_points  
∙ Manages CPU, memory, and I/O devices
∙ Provides process & thread abstraction
∙  ...


keywords  
**Process** – (An executing program instance)
**Thread** – (Lightweight unit of CPU scheduling)
...

chart_summary  
| Component | Role |  
|-----------|-------------------------------|  
| CPU       | Executes instructions         |  
| Memory    | Stores code & data            |  
...

General rules (**FOLLOW EXACTLY**)
- Write in Korean. 
- If a part is impossible, output "Omitted" for that part.
"""

    # 디버깅을 위한 프롬프트 출력
    print("\n[DEBUG] ----- PROMPT BEGIN -----")
    print(f"[DEBUG] 병합된 세그먼트 길이: {len(merged_segments)} 문자")
    print("[DEBUG] ----- PROMPT END -----\n")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "You are an expert in creating structured notes based on lecture content."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        functions=[
            {
                "name": "return_summary",
                "description": "Creates structured notes for a lecture slide.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "concise_summary": {
                            "type": "string",
                            "description": "Concise summary of the content"
                        },
                        "bullet_points": {
                            "type": "string",
                            "description": "Key points in bullet format"
                        },
                        "keywords": {
                            "type": "string",
                            "description": "Important keywords with explanations"
                        },
                        "chart_summary": {
                            "type": "object",
                            "properties": {
                                "주제": {"type": "string"},
                                "부주제": {"type": "string"}
                            },
                            "required": ["주제", "부주제"]
                        }
                    },
                    "required": ["concise_summary", "bullet_points", "keywords", "chart_summary"]
                }
            }
        ],
        function_call={"name": "return_summary"}
    )

    return json.loads(response.choices[0].message.function_call.arguments)

def create_summary(
    image_captioning_data: Dict[str, Any],
    segment_mapping_data: Dict[str, Any],
    progress_callback=None
) -> Dict[str, Any]:
    """모든 슬라이드에 대한 요약을 생성합니다.
    
    Args:
        image_captioning_data: 이미지 캡셔닝 결과 JSON 데이터
        segment_mapping_data: 세그먼트 매핑 결과 JSON 데이터
        progress_callback: 진행률 업데이트를 위한 콜백 함수
        
    Returns:
        생성된 요약 데이터
    """
    # 결과 저장할 딕셔너리
    summaries = {}

    # 처리할 슬라이드 목록 생성
    slides_to_process = []
    for slide_key in segment_mapping_data.keys():
        if slide_key == "slide0":
            continue
            
        slide_number = int(slide_key.replace("slide", ""))
        if slide_number > len(image_captioning_data):
            continue
            
        slides_to_process.append((slide_key, slide_number))

    total_slides = len(slides_to_process)
    
    # 각 슬라이드에 대해 요약 생성
    for i, (slide_key, slide_number) in enumerate(slides_to_process, 1):
        # 진행률 콜백 호출
        if progress_callback:
            progress_callback(i, total_slides)
            
        # 해당 슬라이드의 캡셔닝 데이터
        slide_caption = image_captioning_data[slide_number - 1]

        # 세그먼트 텍스트 병합
        segments = segment_mapping_data[slide_key].get("Segments", {})
        merged_segments = "\n".join(
            f"Segment {seg_id}: {seg_data['text']}"
            for seg_id, seg_data in segments.items()
        )

        # 요약 생성
        summary = generate_summary(slide_caption, merged_segments)
        
        # 결과 저장
        summaries[slide_key] = {
            "Concise Summary Notes": f"🧠Concise Summary Notes\n{summary['concise_summary']}",
            "Bullet Point Notes": f"✅Bullet Point Notes\n{summary['bullet_points']}",
            "Keyword Notes": f"🔑Keyword Notes\n{summary['keywords']}",
            "Chart/Table Summary": f"📊Chart/Table Summary\n{summary['chart_summary']}"
        }

    # 결과 저장
    output_dir = "data/summary"
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = os.path.join(output_dir, f"summary_{timestamp}.json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)
    
    print(f"[INFO] 요약이 {output_path}에 저장되었습니다")
    
    return summaries

if __name__ == "__main__":
    import sys
    
    try:
        # 가장 최근 이미지 캡셔닝 결과 파일 찾기
        captioning_dir = "data/image_captioning"
        captioning_files = [f for f in os.listdir(captioning_dir) if f.startswith("image_captioning")]
        if captioning_files:
            latest_captioning = max(captioning_files)
            with open(os.path.join(captioning_dir, latest_captioning), 'r', encoding='utf-8') as f:
                image_captioning_data = json.load(f)
        else:
            raise Exception("이미지 캡셔닝 결과 파일을 찾을 수 없습니다.")
            
        # 가장 최근 세그먼트 매핑 결과 파일 찾기
        mapping_dir = "data/segment_mapping"
        mapping_files = [f for f in os.listdir(mapping_dir) if f.startswith("segment_mapping")]
        if mapping_files:
            latest_mapping = max(mapping_files)
            with open(os.path.join(mapping_dir, latest_mapping), 'r', encoding='utf-8') as f:
                segment_mapping_data = json.load(f)
        else:
            raise Exception("세그먼트 매핑 결과 파일을 찾을 수 없습니다.")
        
        # JSON 데이터를 직접 전달
        results = create_summary(
            image_captioning_data=image_captioning_data,
            segment_mapping_data=segment_mapping_data
        )
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        sys.exit(1)