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

def load_segment_mapping(skip_segment_split: bool = True) -> Dict[str, Any]:
    """세그먼트 매핑 결과를 로드합니다."""
    if skip_segment_split:
        # 가장 최근의 매핑 결과 파일 찾기
        mapping_dir = "data/segment_mapping"
        if not os.path.exists(mapping_dir):
            raise FileNotFoundError(f"매핑 결과 디렉토리를 찾을 수 없습니다: {mapping_dir}")
        
        mapping_files = [f for f in os.listdir(mapping_dir) if f.startswith("segment_mapping_")]
        if not mapping_files:
            raise FileNotFoundError("매핑 결과 파일을 찾을 수 없습니다.")
        
        latest_file = max(mapping_files)
        path = os.path.join(mapping_dir, latest_file)
        
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        # 실제 세그먼트 매핑 실행
        from segment_mapping import segment_mapping
        return segment_mapping()

def generate_summary(slide_image: str, merged_segments: str) -> Dict[str, Any]:
    """단일 슬라이드에 대한 요약을 생성합니다."""
    prompt = f"""
You are an expert in creating structured notes based on long user inputs.

The user's input consists of:
- A **slide image** that shows the lecture content, and
- A set of **matching lecture segments** explaining details related to that slide.

Matched Lecture Segments:
\"\"\"
{merged_segments}
\"\"\"

# Important Writing Rules:

**ABSOLUTELY MUST** use the exact following titles, numbered exactly as shown:
   - "1. Concise Summary Notes"
   - "2. Bullet Point Notes"
   - "3. Keyword Notes"
   - "4. Chart/Table Summary"

1. **Concise Summary Notes**  
- Summarize the combined content into natural sentences within 7–8 lines.

2. **Bullet Point Notes**  
- List the key points clearly and briefly in bullet points.  
- Each point should be one sentence or a short phrase.

3. **Keyword Notes**  
- Extract and list around 10 major keywords, concepts, or important terms.  
- Provide a brief explanation for each keyword.

4. **Chart/Table Summary**  
- Try your best to summarize the content in a **chart or table format** if possible.
- A table is especially helpful when listing concepts, comparing items, or explaining step-by-step processes.  
- Only write "Omitted" if it is clearly impossible to express the content in a structured chart or table.

Important writing guidelines you must follow:
- Respond in English if the user input is in English; respond in Korean if the input is in Korean.
- Make the notes concise and clear so that users can understand quickly.
- Eliminate redundant expressions and maintain a logical flow.
- Clearly separate each style of note-taking in the output.
- If a style is not applicable, do not leave it blank; explicitly write Omitted.
- If there are no matching lecture segments for a slide, generate the notes based as much as possible on the slide image alone.
- Each style must be written only once. Do not repeat or duplicate the same style multiple times.

# Output Format Example:

1. 🧠Concise Summary Notes
(Your concise summary here)

2. ✅Bullet Point Notes
(Your bullet points here)
∙ This is Bullet Point example
∙ using This point "∙"

3. 🔑Keyword Notes
(Your keywords here)
**Continuity** : Maintaining ongoing operations without disruption.  
**Independence** : Layers functioning without affecting each other.

4. 📊Chart/Table Summary
(Your table here or "Omitted")

Now, generate the notes accordingly.
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
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{slide_image}",
                            "detail": "low"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
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

def create_summary(pdf_path: str = "assets/os_35.pdf", skip_segment_split: bool = True) -> Dict[str, Any]:
    """모든 슬라이드에 대한 요약을 생성합니다."""
    # PDF를 이미지로 변환
    slide_images = convert_pdf_to_images(pdf_path)
    
    # 세그먼트 매핑 데이터 로드
    mapping_data = load_segment_mapping(skip_segment_split)

    # 결과 저장할 딕셔너리
    summaries = {}

    # 각 슬라이드에 대해 요약 생성
    for slide_key, slide_data in mapping_data.items():
        if slide_key == "slide0":
            continue  # 매핑되지 않은 세그먼트는 요약하지 않음
            
        slide_number = int(slide_key.replace("slide", ""))
        
        # 슬라이드 번호가 이미지 범위를 벗어나면 건너뛰기
        if slide_number > len(slide_images):
            continue

        # 해당 슬라이드의 이미지
        slide_image = slide_images[slide_number - 1]

        # 세그먼트 텍스트 병합
        segments = slide_data.get("Segments", {})
        merged_segments = "\n".join(
            f"Segment {seg_id}: {seg_data['text']}"
            for seg_id, seg_data in segments.items()
        )

        # 요약 생성
        summary = generate_summary(slide_image, merged_segments)
        
        # 결과 저장
        summaries[slide_key] = {
            "Concise Summary Notes": summary["concise_summary"],
            "Bullet Point Notes": summary["bullet_points"],
            "Keyword Notes": summary["keywords"],
            "Chart/Table Summary": summary["chart_summary"]
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
    create_summary(skip_segment_split=True) 