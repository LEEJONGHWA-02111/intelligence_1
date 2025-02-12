import time
import serial
import requests
import numpy as np
from io import BytesIO
from pprint import pprint
import cv2
import os

ser = serial.Serial("/dev/ttyACM0", 9600)

# API endpoint (필요 시 URL 입력)
api_url = ""

def get_img():
    """USB 카메라로부터 이미지 획득

    Returns:
        numpy.array: 캡처된 이미지
    """
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
    """이미지를 API로 전송하여 추론 요청

    Args:
        img (numpy.array): 이미지 데이터
        api_url (str): API 엔드포인트 URL
    """
    _, img_encoded = cv2.imencode(".jpg", img)
    img_bytes = BytesIO(img_encoded.tobytes())
    files = {"file": ("image.jpg", img_bytes, "image/jpeg")}
    try:
        response = requests.post(api_url, files=files)
        if response.status_code == 200:
            pprint(response.json())
            return response.json()
        else:
            print(f"Failed to send image. Status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending request: {e}")

# 이미지 저장 폴더 설정 (폴더가 없으면 생성)
save_dir = "captured_images"
if not os.path.exists(save_dir):
    os.makedirs(save_dir)

while True:
    data = ser.read()
    print(data)
    if data == b"0":
        img = get_img()
        # 원하는 영역으로 이미지 크롭 (필요 시 crop_info 수정)
        crop_info = {"x": 200, "y": 100, "width": 300, "height": 300}
        if crop_info is not None:
            img = crop_img(img, crop_info)
        
        # 이미지 화면에 표시
        cv2.imshow("Captured Image", img)
        cv2.waitKey(1)
        
        # 타임스탬프를 포함한 파일명으로 이미지 저장
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(save_dir, f"image_{timestamp}.jpg")
        cv2.imwrite(filename, img)
        print("Saved image:", filename)
        
        # API로 이미지 전송 (필요 시 사용)
        result = inference_request(img, api_url)
        
        # 컨베이어 재가동 신호 전송
        ser.write(b"1")
    else:
        pass
