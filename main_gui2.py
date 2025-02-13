import time
import serial
import numpy as np
import cv2
import os
import requests
from io import BytesIO

# 라즈베리 파이 환경에 맞게 시리얼 포트 설정 (예: /dev/ttyACM0)
ser = serial.Serial("/dev/ttyACM0", 9600)

# 업데이트된 API URL
api_url = 'https://suite-endpoint-api-apne2.superb-ai.com/endpoints/237bfa87-a3a2-4d7f-88a6-db275c671cd1/inference'

# 새롭게 추가된 클래스 리스트 (이 클래스들은 모두 빨간색으로 표시)
new_classes = ["RASPEBBRY PICO X", "HOLE X", "CHIPSET X", "USB X", "OSCILATOR X", "BOOTSEL X"]

def get_img():
    """USB 카메라로부터 이미지 획득"""
    cam = cv2.VideoCapture(0)
    if not cam.isOpened():
        print("Camera Error")
        exit(-1)
    ret, img = cam.read()
    cam.release()
    return img

def crop_img(img, size_dict):
    """이미지에서 지정된 영역을 잘라냄"""
    x = size_dict["x"]
    y = size_dict["y"]
    w = size_dict["width"]
    h = size_dict["height"]
    return img[y:y+h, x:x+w]

def inference_request(img: np.array, api_url: str):
    """이미지를 API로 전송하여 추론 결과 JSON을 반환"""
    _, img_encoded = cv2.imencode(".jpg", img)
    img_bytes = BytesIO(img_encoded.tobytes())
    files = {"file": ("image.jpg", img_bytes, "image/jpeg")}
    try:
        response = requests.post(api_url, files=files)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to send image. Status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error sending request: {e}")
        return None

def draw_boxes(img, inference_result):
    """추론 결과를 기반으로 이미지에 바운딩 박스와 라벨을 그린다."""
    if inference_result is None:
        return img
    objects = inference_result.get("objects", [])
    for obj in objects:
        label = obj.get("class", "")
        score = obj.get("score", 0)
        box = obj.get("box", [])
        if len(box) != 4:
            continue
        # box: [x1, y1, x2, y2]
        x1, y1, x2, y2 = box
        # 새로 추가된 클래스는 빨간색, 나머지는 초록색으로 지정
        if label in new_classes:
            color = (0, 0, 255)  # 빨간색
        else:
            color = (0, 255, 0)  # 초록색
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        text = f"{label}: {score:.2f}"
        cv2.putText(img, text, (x1, max(y1 - 10, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    return img

# 캡처된 이미지 저장 폴더 설정 (폴더가 없으면 생성)
save_dir = "captured_images"
if not os.path.exists(save_dir):
    os.makedirs(save_dir)
    print("Created directory:", save_dir)

while True:
    data = ser.read()
    print("Serial data:", data)
    if data == b"0":
        # 이미지 캡처 및 크롭
        img = get_img()
        crop_info = {"x": 200, "y": 100, "width": 300, "height": 300}
        img = crop_img(img, crop_info)
        
        # API로 추론 요청 후 결과 받기
        result = inference_request(img, api_url)
        
        # 추론 결과에 따라 바운딩 박스 그리기
        img_with_boxes = draw_boxes(img, result)
        
        # 이미지 출력 (라즈베리 파이에서 GUI 환경이 있다면)
        cv2.imshow("Captured Image", img_with_boxes)
        cv2.waitKey(1)
        
        # 타임스탬프 포함 파일명으로 이미지 저장
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(save_dir, f"image_{timestamp}.jpg")
        cv2.imwrite(filename, img_with_boxes)
        print("Saved image:", filename)
        
        # 불량 판정 기준은 기존과 동일하게 처리 (추가 로직 필요 시 이곳에 구현)
        
        # 컨베이어 재가동 신호 전송
        ser.write(b"1")
    else:
        pass
