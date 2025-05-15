import os
from pptx import Presentation
from dotenv import load_dotenv
from openai import OpenAI
import base64
from PIL import Image, ImageDraw, ImageFont
import io
import tempfile
from pdf2image import convert_from_path
import subprocess
import platform

# .env 파일에서 환경 변수 로드
load_dotenv()

# 운영체제에 따른 LibreOffice 경로 설정
def get_libreoffice_path():
    system = platform.system()
    if system == "Windows":
        return r"C:\Program Files\LibreOffice\program\soffice.exe"
    elif system == "Darwin":  # macOS
        return "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    else:
        return "soffice"  # Linux에서는 PATH에 있는 경우

# LibreOffice 실행 파일 경로
LIBREOFFICE_PATH = get_libreoffice_path()

# OpenAI 클라이언트 초기화
client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url="https://api.openai.com/v1"
)

# 토큰 비용 설정 (1M 토큰당)
TOKEN_COSTS = {
    "gpt-4o": {
        "input": 2.50,
        "output": 10.00
    }
}

# 환율 설정
EXCHANGE_RATE = 1468.30

def calculate_cost(usage, model="gpt-4o"):
    """토큰 사용량에 따른 비용을 계산합니다."""
    input_cost = (usage.prompt_tokens / 1_000_000) * TOKEN_COSTS[model]["input"]
    output_cost = (usage.completion_tokens / 1_000_000) * TOKEN_COSTS[model]["output"]
    return input_cost + output_cost

def analyze_image(image_url):
    try:
        # API 호출
        response = client.chat.completions.create(
            model="gpt-4o",
messages=[
    {
        "role": "system",
        "content": """Explain slide content following these guidelines:
1. Present as a professor would during class.
2. Focus on key points, avoid unnecessary details not too long.
3. Use narrative prose.
4. Be concise yet informative."""
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
            }
        ]
    }
],
        max_tokens=2000
        )
        
        # 비용 계산
        cost = calculate_cost(response.usage)
        
        # 응답과 비용 정보 반환
        return response.choices[0].message.content, cost
    except Exception as e:
        return f"오류가 발생했습니다: {str(e)}", 0.0

def convert_slide_to_image(ppt_path, slide_number):
    """PowerPoint 슬라이드를 이미지로 변환합니다."""
    try:
        # data 디렉토리 경로
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        # 임시 디렉토리 생성
        temp_dir = tempfile.mkdtemp()
        print(f"임시 파일 저장 위치: {temp_dir}")
        
        # PowerPoint를 PDF로 변환
        pdf_path = os.path.join(temp_dir, "temp.pdf")
        
        # 운영체제에 따른 명령어 실행
        if platform.system() == "Windows":
            subprocess.run([LIBREOFFICE_PATH, "--headless", "--convert-to", "pdf", "--outdir", temp_dir, ppt_path], check=True)
        else:
            subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", temp_dir, ppt_path], check=True)
        
        # 변환된 PDF 파일 경로 확인
        ppt_filename = os.path.basename(ppt_path)
        pdf_filename = os.path.splitext(ppt_filename)[0] + ".pdf"
        actual_pdf_path = os.path.join(temp_dir, pdf_filename)
        
        if not os.path.exists(actual_pdf_path):
            print(f"PDF 변환 실패: {actual_pdf_path} 파일이 존재하지 않습니다.")
            return None
        
        print(f"PDF 파일 저장 위치: {actual_pdf_path}")
        
        # PDF를 이미지로 변환 (pdf2image 사용)
        images = convert_from_path(actual_pdf_path, first_page=slide_number, last_page=slide_number)
        if not images:
            print(f"슬라이드 {slide_number}를 이미지로 변환하는데 실패했습니다.")
            return None
            
        # 이미지 저장
        output_path = os.path.join(data_dir, f"slide_{slide_number}.jpg")
        images[0].save(output_path, 'JPEG', quality=90)
        
        # JPEG 파일을 base64로 인코딩
        with open(output_path, "rb") as image_file:
            img_str = base64.b64encode(image_file.read()).decode()
        
        # 임시 파일 삭제
        os.remove(actual_pdf_path)
        os.rmdir(temp_dir)
        print("임시 파일이 삭제되었습니다.")
        
        return img_str
    except Exception as e:
        print(f"변환 중 오류 발생: {str(e)}")
        return None

def get_ppt_files():
    """assets 디렉토리에서 PPT 파일 목록을 가져옵니다."""
    assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')
    ppt_files = [f for f in os.listdir(assets_dir) if f.endswith(('.ppt', '.pptx'))]
    return ppt_files, assets_dir

def main():
    # assets 디렉토리에서 PPT 파일 목록 가져오기
    ppt_files, assets_dir = get_ppt_files()
    
    if not ppt_files:
        print("assets 디렉토리에 PPT 파일이 없습니다.")
        return
    
    # PPT 파일 목록 출력 및 선택
    print("\n사용 가능한 PPT 파일:")
    for i, file in enumerate(ppt_files, 1):
        print(f"{i}. {file}")
    
    while True:
        try:
            choice = int(input("\n캡셔닝할 PPT 파일 번호를 입력하세요: "))
            if 1 <= choice <= len(ppt_files):
                break
            print(f"1부터 {len(ppt_files)} 사이의 숫자를 입력하세요.")
        except ValueError:
            print("올바른 숫자를 입력하세요.")
    
    # 선택한 PPT 파일 경로
    ppt_path = os.path.join(assets_dir, ppt_files[choice-1])
    
    # PPT 파일의 총 페이지 수 확인
    pr = Presentation(ppt_path)
    total_slides = len(pr.slides)
    print(f"\n총 페이지 수: {total_slides}")
    
    # 사용자로부터 페이지 번호 입력 받기
    while True:
        try:
            page_number = int(input("캡셔닝을 원하는 페이지 번호를 입력하세요 (종료하려면 0 입력): "))
            if page_number == 0:
                break
            if page_number < 1 or page_number > total_slides:
                print(f"잘못된 페이지 번호입니다. 1부터 {total_slides} 사이의 숫자를 입력하세요.")
                continue
            
            # 슬라이드를 이미지로 변환
            image_data = convert_slide_to_image(ppt_path, page_number)
            
            if not image_data:
                print(f"{page_number}페이지를 이미지로 변환하는데 실패했습니다.")
                continue
            
            # base64 이미지를 URL로 변환
            image_url = f"data:image/jpeg;base64,{image_data}"
            
            # base64 이미지를 PIL Image로 변환하여 표시
            image = Image.open(io.BytesIO(base64.b64decode(image_data)))
            image.show()
            
            # 이미지 분석 수행
            response, cost = analyze_image(image_url)
            print(f"\n페이지 {page_number}의 설명:")
            print(response)
            print(f"\nAPI 사용 비용: ${cost:.4f} (약 {int(cost * EXCHANGE_RATE)}원)")
            
        except ValueError:
            print("올바른 숫자를 입력하세요.")
        except Exception as e:
            print(f"오류가 발생했습니다: {str(e)}")

if __name__ == "__main__":
    main() 