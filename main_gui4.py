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

# ===== Configuration =====
# Updated API URL
API_URL = "https://suite-endpoint-api-apne2.superb-ai.com/endpoints/237bfa87-a3a2-4d7f-88a6-db275c671cd1/inference"
ACCESS_KEY = "vpiu1lDi5T7x2rNqaQiIU9sak1MpCDMV8TixTJZt"
USERNAME = "kdt2025_1-33"

# Serial port for sensor and conveyor control
SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 9600

# Directory to save defective images
DEFECTIVE_DIR = "defective_images"
if not os.path.exists(DEFECTIVE_DIR):
    os.makedirs(DEFECTIVE_DIR)

# Expected object counts for normal inspection (unchanged)
EXPECTED_COUNTS = {
    "RASPEBBRY PICO": 1,
    "HOLE": 4,
    "CHIPSET": 1,
    "USB": 1,
    "OSCILATOR": 1,
    "BOOTSEL": 1
}

# Color mapping for original classes (BGR format)
COLOR_MAP = {
    "RASPEBBRY PICO": (255, 0, 0),       # Blue
    "HOLE": (0, 165, 255),               # Orange
    "CHIPSET": (0, 255, 0),              # Green
    "USB": (0, 255, 255),                # Yellow
    "OSCILATOR": (128, 0, 128),          # Purple
    "BOOTSEL": (235, 206, 135)           # Sky blue
}

# New classes (with "X") are drawn in red (BGR)
NEW_CLASS_COLOR = (0, 0, 255)

# ===== ROI Functions =====
def define_roi():
    """
    Define the ROI (Region of Interest) for the conveyor belt.
    Returns:
        dict: {x, y, width, height} defining the ROI.
    """
    return {"x": 200, "y": 100, "width": 400, "height": 200}

def crop_to_roi(img, roi):
    """
    Crop the image to the specified ROI.
    Args:
        img (numpy.array): The original image.
        roi (dict): ROI defined as {x, y, width, height}.
    Returns:
        numpy.array: The cropped ROI image.
    """
    x = roi["x"]
    y = roi["y"]
    w = roi["width"]
    h = roi["height"]
    return img[y:y+h, x:x+w]


class Application:
    def __init__(self, master):
        self.master = master
        master.title("Conveyor Inspection System")
        
        # State flags
        self.emergency_stop = False
        self.waiting_for_go = threading.Event()  # Wait for user confirmation if defective

        # Initialize serial port (with timeout to avoid blocking issues)
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        except Exception as e:
            print("Failed to connect to serial port:", e)
            exit(1)
        
        # Initialize camera for live feed
        self.cam = cv2.VideoCapture(0)
        if not self.cam.isOpened():
            print("Failed to connect to camera")
            exit(1)
        
        # Define ROI (conveyor belt region)
        self.roi = define_roi()
        
        # Build GUI layout
        self.build_gui()
        
        # Start sensor and image processing thread
        self.sensor_thread = threading.Thread(target=self.sensor_loop, daemon=True)
        self.sensor_thread.start()
        
        # Start live feed update
        self.update_live_feed()

    def build_gui(self):
        # Left and right frames
        self.left_frame = tk.Frame(self.master)
        self.left_frame.pack(side=tk.LEFT, padx=5, pady=5)
        self.right_frame = tk.Frame(self.master)
        self.right_frame.pack(side=tk.RIGHT, padx=5, pady=5)
        
        # Live feed (top left)
        self.live_feed_label = tk.Label(self.left_frame)
        self.live_feed_label.pack(padx=5, pady=5)
        
        # Log window (bottom left)
        self.log_text = scrolledtext.ScrolledText(self.left_frame, width=50, height=10, state=tk.DISABLED)
        self.log_text.pack(padx=5, pady=5)
        
        # Result image (top right)
        self.result_img_label = tk.Label(self.right_frame)
        self.result_img_label.pack(padx=5, pady=5)
        
        # Control buttons (GO, STOP) at bottom right
        btn_frame = tk.Frame(self.right_frame)
        btn_frame.pack(padx=5, pady=5)
        self.go_btn = tk.Button(btn_frame, text="GO", width=10, command=self.go_button)
        self.go_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = tk.Button(btn_frame, text="STOP", width=10, command=self.stop_button)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
    def update_live_feed(self):
        # Capture live feed and display ROI region
        ret, frame = self.cam.read()
        if ret:
            roi_frame = crop_to_roi(frame, self.roi)
            frame_rgb = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            imgtk = ImageTk.PhotoImage(image=img)
            self.live_feed_label.imgtk = imgtk
            self.live_feed_label.configure(image=imgtk)
        self.master.after(30, self.update_live_feed)
    
    def log(self, message):
        # Log message with timestamp in English
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_msg = f"[{timestamp}] {message}\n"
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, full_msg)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def sensor_loop(self):
        """Read sensor signal from serial port and process ROI image capture."""
        while True:
            if self.emergency_stop:
                time.sleep(0.1)
                continue
            try:
                data = self.ser.read()
            except Exception as e:
                self.master.after(0, lambda: self.log("Serial read error: " + str(e)))
                continue
            if data == b"0":
                self.master.after(0, lambda: self.log("Sensor detected object: Stopping conveyor"))
                
                # Capture full frame from camera
                ret, captured_img = self.cam.read()
                if not ret:
                    self.master.after(0, lambda: self.log("Image capture failed"))
                    continue

                # Crop to ROI
                roi_img = crop_to_roi(captured_img, self.roi)

                self.master.after(0, lambda: self.log("ROI image captured. Sending to API..."))
                # Send image to API (blocking call)
                result_json = self.send_image_to_api(roi_img)
                if result_json is None:
                    self.master.after(0, lambda: self.log("API request failed"))
                    continue

                # Draw boxes based on API result on ROI image
                boxed_img = self.draw_boxes(roi_img.copy(), result_json)
                self.master.after(0, lambda: self.update_result_image(boxed_img))

                # Evaluate result (normal/defective based on EXPECTED_COUNTS)
                if self.evaluate_result(result_json):
                    self.master.after(0, lambda: self.log("Inspection result: Normal - Resuming conveyor"))
                    try:
                        self.ser.write(b"1")
                    except Exception as e:
                        self.master.after(0, lambda: self.log("Failed to send resume command: " + str(e)))
                else:
                    self.master.after(0, lambda: self.log("Inspection result: Defective - Saving image and awaiting user confirmation"))
                    self.save_defective_image(boxed_img)
                    # Wait for user to press GO before resuming
                    self.waiting_for_go.clear()
                    self.waiting_for_go.wait()
                    self.master.after(0, lambda: self.log("GO button pressed - Resuming conveyor"))
                    try:
                        self.ser.write(b"1")
                    except Exception as e:
                        self.master.after(0, lambda: self.log("Failed to send resume command: " + str(e)))
            else:
                time.sleep(0.1)
    
    def send_image_to_api(self, img):
        """Encode image to JPEG and send to API, then return JSON response."""
        ret, buf = cv2.imencode(".jpg", img)
        if not ret:
            self.master.after(0, lambda: self.log("Image encoding failed"))
            return None
        img_bytes = buf.tobytes()
        try:
            response = requests.post(
                url=API_URL,
                auth=HTTPBasicAuth(USERNAME, ACCESS_KEY),
                headers={"Content-Type": "image/jpeg"},
                data=img_bytes,
            )
            json_response = response.json()
            return json_response
        except Exception as e:
            self.master.after(0, lambda: self.log("API request exception: " + str(e)))
            return None
    
    def draw_boxes(self, img, json_response):
        """Draw bounding boxes, class names, and scores on the image based on API response."""
        objects = json_response.get("objects", [])
        if not objects:
            return img
        for obj in objects:
            class_name = obj.get("class", "Unknown")
            box = obj.get("box", [])
            if not box or len(box) != 4:
                continue
            x1, y1, x2, y2 = box

            # Determine color: new classes (ending with "X") in red, original classes per COLOR_MAP
            if class_name.strip().endswith("X"):
                color = NEW_CLASS_COLOR
            else:
                color = COLOR_MAP.get(class_name.upper(), (0, 255, 0))
            
            # Set smaller font scale
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness = 2
            
            # Include score with two decimal precision if available
            score = obj.get("score", None)
            if score is not None:
                text = f"{class_name} {score:.2f}"
            else:
                text = class_name

            (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
            text_bg_top = max(y1 - text_h - baseline, 0)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            cv2.rectangle(img, (x1, text_bg_top), (x1 + text_w, y1), color, cv2.FILLED)
            cv2.putText(img, text, (x1, y1 - baseline), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
        return img

    def update_result_image(self, img):
        """Update the result image (with bounding boxes) on the GUI."""
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        imgtk = ImageTk.PhotoImage(image=pil_img)
        self.result_img_label.imgtk = imgtk
        self.result_img_label.configure(image=imgtk)
    
    def evaluate_result(self, json_response):
        """
        Evaluate the API result by checking object counts.
        Only the original classes (without "X") are considered.
        Returns True if counts match EXPECTED_COUNTS, else False.
        """
        counts = {}
        expected_set = set([k.upper() for k in EXPECTED_COUNTS.keys()])
        for obj in json_response.get("objects", []):
            cls = obj.get("class", "")
            if cls.strip().endswith("X"):
                continue
            cls_up = cls.upper()
            if cls_up in expected_set:
                counts[cls_up] = counts.get(cls_up, 0) + 1
        for key, expected in EXPECTED_COUNTS.items():
            if counts.get(key.upper(), 0) != expected:
                return False
        return True
    
    def save_defective_image(self, img):
        """Save defective image to a file with a timestamp-based filename."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(DEFECTIVE_DIR, f"defective_{timestamp}.jpg")
        cv2.imwrite(filename, img)
        self.master.after(0, lambda: self.log(f"Defective image saved: {filename}"))
    
    def go_button(self):
        """GO button callback: Clear emergency stop and resume conveyor."""
        self.log("GO button pressed")
        self.emergency_stop = False  # Clear emergency stop flag
        self.waiting_for_go.set()
    
    def stop_button(self):
        """STOP button callback: Set emergency stop and send stop command."""
        self.emergency_stop = True
        self.log("Emergency STOP pressed: Stopping conveyor")
        try:
            self.ser.write(b"0")
        except Exception as e:
            self.log("Failed to send STOP command: " + str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app = Application(root)
    root.mainloop()
