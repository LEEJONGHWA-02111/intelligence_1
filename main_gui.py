import cv2
import tkinter as tk
from tkinter import scrolledtext
from PIL import Image, ImageTk
import threading
import time
import serial
import requests
from requests.auth import HTTPBasicAuth
import os
from io import BytesIO
from datetime import datetime

# ===== 설정값 =====
# API 설정
API_URL = "https://suite-endpoint-api-apne2.superb-ai.com/endpoints/2e98ddfd-a2ea-494d-b0ec-b4efcdbd9273/inference"
ACCESS_KEY = "vpiu1lDi5T7x2rNqaQiIU9sak1MpCDMV8TixTJZt"
USERNAME = "kdt2025_1-33"

# 시리얼 포트 (센서 및 컨베이어 제어)
SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 9600

# 불량 이미지 저장 경로
DEFECTIVE_DIR = "defective_images"
if not os.path.exists(DEFECTIVE_DIR):
    os.makedirs(DEFECTIVE_DIR)

# 기대되는 객체 갯수 (모두 정확해야 정상)
EXPECTED_COUNTS = {
    "RASPEBBRY PICO": 1,
    "HOLE": 4,
    "CHIPSET": 1,
    "USB": 1,
    "OSCILATOR": 1,
    "BOOTSEL": 1
}

# 클래스별 색상 매핑 (BGR 형식)
COLOR_MAP = {
    "RASPEBBRY PICO": (255, 0, 0),       # 파란색
    "HOLE": (0, 165, 255),               # 주황색
    "CHIPSET": (0, 255, 0),              # 초록색
    "USB": (0, 255, 255),                # 노란색
    "OSCILATOR": (128, 0, 128),          # 보라색
    "BOOTSEL": (235, 206, 135)           # 하늘색
}


class Application:
    def __init__(self, master):
        self.master = master
        master.title("컨베이어 검사 시스템")
        
        # 상태 플래그
        self.emergency_stop = False
        self.waiting_for_go = threading.Event()  # 불량 시 사용자가 GO를 누를 때까지 대기

        # 시리얼 포트 초기화 (timeout을 지정해 blocking 문제 방지)
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        except Exception as e:
            print("시리얼 포트 연결 실패:", e)
            exit(1)
        
        # 카메라 초기화 (실시간 영상용)
        self.cam = cv2.VideoCapture(0)
        if not self.cam.isOpened():
            print("카메라 연결 실패")
            exit(1)
        
        # GUI 레이아웃 구성
        self.build_gui()
        
        # 센서 및 이미지 처리 스레드 시작
        self.sensor_thread = threading.Thread(target=self.sensor_loop, daemon=True)
        self.sensor_thread.start()
        
        # 실시간 영상 업데이트 시작
        self.update_live_feed()

    def build_gui(self):
        # 전체 프레임을 좌/우로 나눔
        self.left_frame = tk.Frame(self.master)
        self.left_frame.pack(side=tk.LEFT, padx=5, pady=5)
        self.right_frame = tk.Frame(self.master)
        self.right_frame.pack(side=tk.RIGHT, padx=5, pady=5)
        
        # 좌측 상단: 실시간 카메라 영상
        self.live_feed_label = tk.Label(self.left_frame)
        self.live_feed_label.pack(padx=5, pady=5)
        
        # 좌측 하단: 로그 창
        self.log_text = scrolledtext.ScrolledText(self.left_frame, width=50, height=10, state=tk.DISABLED)
        self.log_text.pack(padx=5, pady=5)
        
        # 우측 상단: API 결과(박스가 그려진 이미지)
        self.result_img_label = tk.Label(self.right_frame)
        self.result_img_label.pack(padx=5, pady=5)
        
        # 우측 하단: 컨트롤 버튼 (GO, STOP)
        btn_frame = tk.Frame(self.right_frame)
        btn_frame.pack(padx=5, pady=5)
        self.go_btn = tk.Button(btn_frame, text="GO", width=10, command=self.go_button)
        self.go_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = tk.Button(btn_frame, text="STOP", width=10, command=self.stop_button)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
    def update_live_feed(self):
        # 실시간 카메라 영상 읽기 및 Tkinter에 표시
        ret, frame = self.cam.read()
        if ret:
            # OpenCV의 BGR -> RGB 변환
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            imgtk = ImageTk.PhotoImage(image=img)
            self.live_feed_label.imgtk = imgtk  # 참조 유지
            self.live_feed_label.configure(image=imgtk)
        self.master.after(30, self.update_live_feed)
    
    def log(self, message):
        # 로그 메시지를 GUI 텍스트 위젯에 추가 (메인스레드에서 호출)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_msg = f"[{timestamp}] {message}\n"
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, full_msg)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def sensor_loop(self):
        """시리얼 포트에서 센서 신호 읽기 및 이미지 캡처/처리"""
        while True:
            if self.emergency_stop:
                time.sleep(0.1)
                continue
            try:
                data = self.ser.read()
            except Exception as e:
                self.master.after(0, lambda: self.log("시리얼 읽기 오류: " + str(e)))
                continue
            if data == b"0":
                self.master.after(0, lambda: self.log("센서 감지: 물체 인식 → 컨베이어 정지"))
                # 센서 감지 시 컨베이어 정지 상태로 진입
                # (여기서는 센서 신호가 컨베이어 정지를 의미하므로 추가 제어 생략)
                
                # 카메라에서 이미지 캡처 (실시간 영상 프레임 사용)
                ret, captured_img = self.cam.read()
                if not ret:
                    self.master.after(0, lambda: self.log("이미지 캡처 실패"))
                    continue

                # (필요 시 crop 정보 적용 가능; 아래 crop 예시 주석)
                # crop_info = {"x":200, "y":100, "width":400, "height":280}
                # captured_img = captured_img[crop_info["y"]:crop_info["y"]+crop_info["height"],
                #                             crop_info["x"]:crop_info["x"]+crop_info["width"]]

                self.master.after(0, lambda: self.log("이미지 캡처 완료. API 전송 중..."))
                # API 요청 (blocking 호출)
                result_json = self.send_image_to_api(captured_img)
                if result_json is None:
                    self.master.after(0, lambda: self.log("API 요청 실패"))
                    continue

                # 박스 그리기: API 결과 기반
                boxed_img = self.draw_boxes(captured_img.copy(), result_json)
                # GUI에 결과 이미지 업데이트 (메인스레드에서 안전하게 처리)
                self.master.after(0, lambda: self.update_result_image(boxed_img))

                # 결과 평가 (정상/불량)
                if self.evaluate_result(result_json):
                    self.master.after(0, lambda: self.log("검사 결과: 정상 → 컨베이어 재가동"))
                    try:
                        self.ser.write(b"1")
                    except Exception as e:
                        self.master.after(0, lambda: self.log("컨베이어 재가동 명령 전송 실패: " + str(e)))
                else:
                    self.master.after(0, lambda: self.log("검사 결과: 불량 발견! 사진 저장 및 사용자 확인 대기"))
                    # 불량 이미지 저장
                    self.save_defective_image(boxed_img)
                    # 불량이면 GO 버튼 입력을 기다림
                    self.waiting_for_go.clear()
                    self.waiting_for_go.wait()  # GO 버튼 클릭 시 이벤트 set됨
                    self.master.after(0, lambda: self.log("GO 버튼 입력 → 컨베이어 재가동"))
                    try:
                        self.ser.write(b"1")
                    except Exception as e:
                        self.master.after(0, lambda: self.log("컨베이어 재가동 명령 전송 실패: " + str(e)))
            else:
                # 센서가 감지되지 않은 경우
                time.sleep(0.1)
    
    def send_image_to_api(self, img):
        """이미지를 JPEG로 인코딩한 후 API로 전송하여 결과 JSON을 반환"""
        ret, buf = cv2.imencode(".jpg", img)
        if not ret:
            self.master.after(0, lambda: self.log("이미지 인코딩 실패"))
            return None
        img_bytes = buf.tobytes()
        try:
            response = requests.post(
                url=API_URL,
                auth=HTTPBasicAuth(USERNAME, ACCESS_KEY),
                headers={"Content-Type": "image/jpeg"},
                data=img_bytes,
            )
            # 응답이 JSON이 아닐 경우 처리
            json_response = response.json()
            return json_response
        except Exception as e:
            self.master.after(0, lambda: self.log("API 요청 예외: " + str(e)))
            return None
    
    def draw_boxes(self, img, json_response):
        """API 결과에 따라 이미지에 박스 및 클래스명을 그림"""
        objects = json_response.get("objects", [])
        if not objects:
            return img
        for obj in objects:
            class_name = obj.get("class", "Unknown")
            box = obj.get("box", [])
            if not box or len(box) != 4:
                continue
            x1, y1, x2, y2 = box
            # 클래스명이 대/소문자 혼용될 수 있으므로 upper() 사용하여 색상 매핑
            color = COLOR_MAP.get(class_name.upper(), (0, 255, 0))
            # 사각형 박스 그리기
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            # 텍스트 배경 및 텍스트 표시
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6
            thickness = 2
            (text_w, text_h), baseline = cv2.getTextSize(class_name, font, font_scale, thickness)
            text_bg_top = max(y1 - text_h - baseline, 0)
            cv2.rectangle(img, (x1, text_bg_top), (x1 + text_w, y1), color, cv2.FILLED)
            cv2.putText(img, class_name, (x1, y1 - baseline), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
        return img

    def update_result_image(self, img):
        """우측 상단의 결과 이미지(Label)에 업데이트"""
        # OpenCV BGR -> RGB 변환
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        imgtk = ImageTk.PhotoImage(image=pil_img)
        self.result_img_label.imgtk = imgtk
        self.result_img_label.configure(image=imgtk)
    
    def evaluate_result(self, json_response):
        """API 결과의 객체 갯수를 체크하여 정상이면 True, 불량이면 False 반환"""
        counts = {}
        for obj in json_response.get("objects", []):
            cls = obj.get("class", "").upper()
            counts[cls] = counts.get(cls, 0) + 1
        # 모든 기대값이 정확히 일치해야 정상으로 판정
        for key, expected in EXPECTED_COUNTS.items():
            if counts.get(key.upper(), 0) != expected:
                return False
        return True
    
    def save_defective_image(self, img):
        """불량 이미지 저장 (defective_images 폴더에 타임스탬프 기반 파일명)"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(DEFECTIVE_DIR, f"defective_{timestamp}.jpg")
        cv2.imwrite(filename, img)
        self.master.after(0, lambda: self.log(f"불량 이미지 저장: {filename}"))
    
    def go_button(self):
        """불량 시 GO 버튼 클릭 콜백 → 센서 스레드에서 대기 중인 이벤트 set"""
        self.log("GO 버튼 클릭")
        self.waiting_for_go.set()
    
    def stop_button(self):
        """긴급 STOP 버튼 클릭 콜백 → emergency_stop 플래그 설정"""
        self.emergency_stop = True
        self.log("긴급 STOP 버튼 클릭: 컨베이어 정지")
        try:
            self.ser.write(b"0")
        except Exception as e:
            self.log("STOP 명령 전송 실패: " + str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app = Application(root)
    root.mainloop()
