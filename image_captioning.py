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
                    "content": "You are a helpful assistant that analyzes lecture slides and extracts keywords and slide type."
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
                            "text": """Analyze this lecture slide and:
1. Extract 1-2 main keywords and 3-5 secondary keywords
2. Determine the slide type from these categories:
   - 'objective': Learning objectives, overview slides
   - 'code': Code or algorithm focused slides
   - 'image': Image, graph, or visual material focused slides
   - 'content': General theory explanation, text-focused slides"""
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
                                "enum": ["objective", "code", "image", "content"],
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
                            }
                        },
                        "required": ["type", "title_keywords", "secondary_keywords"]
                    }
                }
            ],
            function_call={"name": "return_slide_analysis"}
        )
        
        return json.loads(response.choices[0].message.function_call.arguments)
    except Exception as e:
        raise Exception(f"이미지 분석 중 오류 발생: {str(e)}")

def process_pdf(skip_segment_split: bool = True) -> list:
    """PDF 파일을 처리하여 각 페이지의 키워드와 타입을 추출합니다.
    
    Args:
        skip_segment_split: 세그먼트 분리 단계 건너뛰기 여부
        
    Returns:
        각 페이지의 키워드 정보와 타입을 담은 JSON 리스트
    """
    try:
        # PDF 파일 경로
        pdf_path = "assets/os_35.pdf"
        
        # PDF를 이미지로 변환
        encoded_images = convert_pdf_to_images(pdf_path)
        
        # 각 이미지에 대해 키워드 추출
        results = []
        for i, img_str in enumerate(encoded_images, 1):
            # base64 이미지를 URL로 변환
            image_url = f"data:image/jpeg;base64,{img_str}"
            
            # 이미지 분석
            analysis = analyze_image(image_url)
            
            # 결과에 페이지 번호 추가
            result = {
                "slide_number": i,
                "type": analysis["type"],
                "title_keywords": analysis["title_keywords"],
                "secondary_keywords": analysis["secondary_keywords"]
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
        results = process_pdf()
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"오류 발생: {str(e)}") 