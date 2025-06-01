import os
from dotenv import load_dotenv
from openai import OpenAI
import base64
from pdf2image import convert_from_path
import json
import io
from datetime import datetime

# .env 파일에서 환경 변수 로드
load_dotenv()

# OpenAI 클라이언트 초기화
client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url="https://api.openai.com/v1"
)

def convert_pdf_to_images(pdf_path: str) -> list:
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

def analyze_image(image_url: str) -> dict:
    """이미지를 분석하여 키워드와 슬라이드 타입을 추출합니다.
    
    Args:
        image_url: base64로 인코딩된 이미지 URL
        
    Returns:
        추출된 키워드 정보와 슬라이드 타입
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
    {
        "role": "system",
        "content": "You are an assistant that analyzes each lecture slide, extracts concise English keywords, and classifies the slide into a single type so audio segments can later be mapped accurately."
    },
    {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {
                    "url": image_url,
                    "detail": "low"
                }
            },
            {
                "type": "text",
                "text": """Analyze this slide and reply ONLY with a JSON object in the form:
{
  "type": "<meta|code|image|content>",
  "title_keywords": ["<1-2 core keywords>"],
  "secondary_keywords": ["<3-5 additional terms>"],
  "detail": "<detailed description based on type>"
}

Field meanings:
- "title_keywords": 1-2 core terms that best summarize the slide's main idea.
- "secondary_keywords": 1–5 specific technical or domain terms that actually appear on the slide; avoid broad or generic words.
- "detail": Detailed description of the slide content:
  * For type="image": Provide a comprehensive description of the visual elements, their arrangement, and significance.
  * For type="code": Explain the code's purpose, key functions, and implementation details.
  * For other types: Provide a brief 1-2 sentence summary of the main content.

Type definitions (choose exactly one):
- meta   : cover, agenda, learning-objective, summary, or closing slides that must never be mapped to audio segments.
- code   : slides dominated by source code, pseudocode, or algorithms.
- image  : slides whose main content is an image, diagram, chart, or other visual.
- content: all other explanatory or theory-focused slides.

Rules:
1. Keep every keyword short (≤ 3 words), English nouns where possible.
2. If the type is meta, BOTH keyword arrays must be empty lists.
3. For secondary_keywords, include only concrete terms present on the slide; skip vague catch-all words.
4. Do not add any text outside the JSON object.
5. If a slide fits multiple categories, pick the most specific (code > image > content).
"""
            }
        ]
    }
],
            functions=[
                {
                    "name": "return_slide_analysis",
                    "description": "Analyzes lecture slides and returns keywords and slide type.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["meta", "code", "image", "content"],
                                "description": "The type of the slide based on its content"
                            },
                            "title_keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Top 1-2 keywords summarizing the slide"
                            },
                            "secondary_keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Additional 3-5 technical or related terms"
                            },
                            "detail": {
                                "type": "string",
                                "description": "Detailed description of the slide content"
                            }
                        },
                        "required": ["type", "title_keywords", "secondary_keywords", "detail"]
                    }
                }
            ],
            function_call={"name": "return_slide_analysis"}
        )
        
        return json.loads(response.choices[0].message.function_call.arguments)
    except Exception as e:
        raise Exception(f"이미지 분석 중 오류 발생: {str(e)}")

def image_captioning(pdf_path: str = "assets/os_35.pdf", progress_callback=None) -> list:
    """PDF 파일을 처리하여 각 페이지의 키워드와 타입을 추출합니다.
    
    Args:
        pdf_path: PDF 파일 경로
        progress_callback: 진행률 업데이트 콜백 함수 (current_page, total_pages)
        
    Returns:
        각 페이지의 키워드 정보와 타입을 담은 JSON 리스트
    """
    try:
        # PDF를 이미지로 변환
        encoded_images = convert_pdf_to_images(pdf_path)
        total_pages = len(encoded_images)
        
        # 각 이미지에 대해 키워드 추출
        results = []
        for i, img_str in enumerate(encoded_images, 1):
            # 진행률 콜백 호출
            if progress_callback:
                progress_callback(i, total_pages)
            
            print(f"[INFO] 슬라이드 {i}/{total_pages} 분석 중...")
            # base64 이미지를 URL로 변환
            image_url = f"data:image/jpeg;base64,{img_str}"
            
            # 이미지 분석
            analysis = analyze_image(image_url)
            
            # 결과에 페이지 번호 추가
            result = {
                "slide_number": i,
                "type": analysis["type"],
                "title_keywords": analysis["title_keywords"],
                "secondary_keywords": analysis["secondary_keywords"],
                "detail": analysis["detail"]
            }
            results.append(result)
        
        # 결과 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_dir = "data/image_captioning"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"image_captioning_{timestamp}.json")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        return results
        
    except Exception as e:
        raise Exception(f"PDF 처리 중 오류 발생: {str(e)}")

if __name__ == "__main__":
    try:
        pdf_path = "assets/os_35.pdf"
        results = image_captioning(pdf_path=pdf_path)
    except Exception as e:
        print(f"오류 발생: {str(e)}") 