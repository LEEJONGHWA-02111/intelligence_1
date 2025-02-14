import cv2
import tkinter as tk
from tkinter import scrolledtext, ttk
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
API_URL = "https://suite-endpoint-api-apne2.superb-ai.com/endpoints/c0ee04fd-a40e-4a62-8b06-6244aecb2ae1/inference"
ACCESS_KEY = "vpiu1lDi5T7x2rNqaQiIU9sak1MpCDMV8TixTJZt"
USERNAME = "kdt2025_1-33"

SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 9600

DEFECTIVE_DIR = "defective_images"
if not os.path.exists(DEFECTIVE_DIR):
    os.makedirs(DEFECTIVE_DIR)

# Expected object counts for normal inspection
EXPECTED_COUNTS = {
    "RASPEBBRY PICO": 1,
    "HOLE": 4,
    "CHIPSET": 1,
    "USB": 1,
    "OSCILATOR": 1,
    "BOOTSEL": 1
}

# Original class colors in BGR
COLOR_MAP_BGR = {
    "RASPEBBRY PICO": (255, 0, 0),       # Blue box
    "HOLE": (0, 165, 255),               # Orange
    "CHIPSET": (0, 255, 0),              # Green
    "USB": (0, 255, 255),                # Yellow
    "OSCILATOR": (128, 0, 128),          # Purple
    "BOOTSEL": (235, 206, 135)           # Sky-blue
}
# New classes (with "X") in red (BGR)
NEW_CLASS_COLOR_BGR = (0, 0, 255)       # Red

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

def bgr_to_hex(bgr_tuple):
    """
    Convert a BGR tuple to #RRGGBB hex format for Tkinter usage.
    Args:
        bgr_tuple (tuple): (B, G, R)
    Returns:
        str: Hex color string (e.g. "#FF0000").
    """
    b, g, r = bgr_tuple
    return f"#{r:02x}{g:02x}{b:02x}"

# Precompute color mapping for classes (in hex) to use in the GUI table
CLASS_COLOR_HEX = {}
for cls_name, bgr in COLOR_MAP_BGR.items():
    CLASS_COLOR_HEX[cls_name.upper()] = bgr_to_hex(bgr_tuple=bgr)

# "X" classes use red
X_CLASS_HEX = bgr_to_hex(NEW_CLASS_COLOR_BGR)

class Application:
    def __init__(self, master):
        self.master = master
        master.title("Conveyor Inspection System")
        
        # State flags
        self.emergency_stop = False
        self.waiting_for_go = threading.Event()

        # Initialize serial port
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        except Exception as e:
            print("Failed to connect to serial port:", e)
            exit(1)
        
        # Initialize camera
        self.cam = cv2.VideoCapture(0)
        if not self.cam.isOpened():
            print("Failed to connect to camera")
            exit(1)
        
        # Define ROI
        self.roi = define_roi()
        
        # Build GUI
        self.build_gui()
        
        # Start sensor thread
        self.sensor_thread = threading.Thread(target=self.sensor_loop, daemon=True)
        self.sensor_thread.start()
        
        # Start live feed update
        self.update_live_feed()

    def build_gui(self):
        # Left frame (camera feed + log)
        self.left_frame = tk.Frame(self.master)
        self.left_frame.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.BOTH, expand=True)

        # Camera feed
        self.live_feed_label = tk.Label(self.left_frame)
        self.live_feed_label.pack(padx=5, pady=5)

        # Log window
        self.log_text = scrolledtext.ScrolledText(self.left_frame, width=50, height=10, state=tk.DISABLED)
        self.log_text.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)

        # Right frame (top: bounding box image, bottom: control + info panel)
        self.right_frame = tk.Frame(self.master)
        self.right_frame.pack(side=tk.RIGHT, padx=5, pady=5, fill=tk.BOTH, expand=True)

        # Top: bounding box image (without text)
        self.result_img_label = tk.Label(self.right_frame)
        self.result_img_label.pack(padx=5, pady=5)

        # Bottom: control + info
        self.bottom_frame = tk.Frame(self.right_frame)
        self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)

        # Control buttons
        self.btn_frame = tk.Frame(self.bottom_frame)
        self.btn_frame.pack(side=tk.BOTTOM, padx=5, pady=5)
        self.go_btn = tk.Button(self.btn_frame, text="GO", width=10, command=self.go_button)
        self.go_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = tk.Button(self.btn_frame, text="STOP", width=10, command=self.stop_button)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # Info panel (large rectangle on the right, above the buttons)
        self.info_frame = tk.Frame(self.bottom_frame, bd=2, relief=tk.SUNKEN)
        self.info_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 1) Status label (Success/Fail)
        self.status_label = tk.Label(self.info_frame, text="Waiting...", font=("Arial", 20, "bold"))
        self.status_label.pack(pady=5)

        # 2) Count label (total objects, normal objects)
        self.count_label = tk.Label(self.info_frame, text="0 objects, 0 normal", font=("Arial", 12))
        self.count_label.pack(pady=5)

        # 3) Table (class name, score) with scrollbar
        self.tree_frame = tk.Frame(self.info_frame)
        self.tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree_scrollbar = tk.Scrollbar(self.tree_frame, orient=tk.VERTICAL)
        self.tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(self.tree_frame, columns=("Class", "Score"), show="headings",
                                 yscrollcommand=self.tree_scrollbar.set, selectmode="none")
        self.tree.heading("Class", text="Class")
        self.tree.heading("Score", text="Score")
        self.tree.column("Class", width=120)
        self.tree.column("Score", width=60, anchor=tk.E)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_scrollbar.config(command=self.tree.yview)

        # Configure color tags for known classes + X
        # We'll do uppercase keys for matching
        for cls_name, hex_color in CLASS_COLOR_HEX.items():
            self.tree.tag_configure(cls_name, foreground=hex_color)
        self.tree.tag_configure("X_CLASS", foreground=X_CLASS_HEX)
        self.tree.tag_configure("UNKNOWN", foreground="#000000")  # black

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
                
                # Capture full frame
                ret, captured_img = self.cam.read()
                if not ret:
                    self.master.after(0, lambda: self.log("Image capture failed"))
                    continue

                # Crop to ROI
                roi_img = crop_to_roi(captured_img, self.roi)

                self.master.after(0, lambda: self.log("ROI image captured. Sending to API..."))
                result_json = self.send_image_to_api(roi_img)
                if result_json is None:
                    self.master.after(0, lambda: self.log("API request failed"))
                    continue

                # Draw bounding boxes on ROI (no text)
                boxed_img = self.draw_boxes(roi_img.copy(), result_json)
                self.master.after(0, lambda: self.update_result_image(boxed_img))

                # Evaluate result
                is_normal = self.evaluate_result(result_json)
                # Update detailed info panel (Success/Fail, counts, table)
                self.master.after(0, lambda: self.update_detailed_info(result_json, is_normal))

                if is_normal:
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
        """
        Draw bounding boxes only (no text) based on API response.
        """
        objects = json_response.get("objects", [])
        for obj in objects:
            box = obj.get("box", [])
            class_name = obj.get("class", "Unknown")
            if not box or len(box) != 4:
                continue
            x1, y1, x2, y2 = box

            # Determine color: new classes (ending with "X") in red, original classes per COLOR_MAP_BGR
            if class_name.strip().endswith("X"):
                color_bgr = NEW_CLASS_COLOR_BGR
            else:
                color_bgr = COLOR_MAP_BGR.get(class_name.upper(), (0, 255, 0))
            
            cv2.rectangle(img, (x1, y1), (x2, y2), color_bgr, 2)
        return img

    def update_result_image(self, img):
        """
        Update the result image (with bounding boxes only) on the GUI.
        """
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        imgtk = ImageTk.PhotoImage(image=pil_img)
        self.result_img_label.imgtk = imgtk
        self.result_img_label.configure(image=imgtk)

    def update_detailed_info(self, result_json, is_normal):
        """
        Update the Info Panel on the right:
          - Success or Fail (big text)
          - Total object count, total normal count
          - A table (TreeView) listing each class and score with proper colors
        """
        # 1) Success/Fail label
        if is_normal:
            self.status_label.config(text="SUCCESS", fg="blue")
        else:
            self.status_label.config(text="FAIL", fg="red")

        objects = result_json.get("objects", [])
        # 2) Count total objects and total normal
        total_objects = len(objects)
        normal_objects = sum(1 for obj in objects if not obj.get("class", "").strip().endswith("X"))
        self.count_label.config(text=f"{total_objects} objects, {normal_objects} normal")

        # 3) Update the table
        # Clear existing rows
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Insert new rows
        for obj in objects:
            class_name = obj.get("class", "Unknown")
            score = obj.get("score", 0.0)
            # Format score to 2 decimals
            score_text = f"{score:.2f}"

            # Decide which tag (color) to use
            if class_name.strip().endswith("X"):
                row_tag = "X_CLASS"
            else:
                cls_up = class_name.upper()
                if cls_up in CLASS_COLOR_HEX:
                    row_tag = cls_up
                else:
                    row_tag = "UNKNOWN"

            self.tree.insert("", "end", values=(class_name, score_text), tags=(row_tag,))
    
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
                # "X" class is not counted as normal
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
        self.emergency_stop = False
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
