import time
import serial
import numpy as np
import cv2
import os

# 라즈베리 파이에서 시리얼 포트 경로와 속도를 실제 환경에 맞게 설정
ser = serial.Serial("/dev/ttyACM0", 9600)

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

# 이미지 저장 폴더 설정 (폴더가 없으면 생성)
save_dir = "captured_images"
if not os.path.exists(save_dir):
    os.makedirs(save_dir)
    print("Created directory:", save_dir)

while True:
    data = ser.read()
    print("Serial data:", data)
    if data == b"0":
        img = get_img()
        crop_info = {"x": 200, "y": 100, "width": 300, "height": 300}
        if crop_info is not None:
            img = crop_img(img, crop_info)
        
        # 라즈베리 파이에서 GUI 환경이 있다면 이미지 창에 표시 (헤드리스 환경이면 주석 처리)
        cv2.imshow("Captured Image", img)
        cv2.waitKey(1)
        
        # 타임스탬프를 포함한 파일명으로 이미지 저장
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(save_dir, f"image_{timestamp}.jpg")
        cv2.imwrite(filename, img)
        print("Saved image:", filename)
        
        # 센서가 감지 후 컨베이어 재가동 신호 전송
        ser.write(b"1")
    else:
        pass
