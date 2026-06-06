import cv2
import os
import json
import numpy as np
import threading

class VideoCamera(object):
    def __init__(self):
        self.video = None
        self.face_cascade = None
        self.recognizer = None
        self.user_map = {}
        self.last_id = None
        self.last_name = None
        self.face_roi_size = (200, 200)
        self.lock = threading.Lock()
        
        # Try to open camera at index 0
        self.video = cv2.VideoCapture(0)
        if not self.video.isOpened():
            print("❌ Could not open camera at index 0")
            self.video = None
        else:
            # Set lower resolution for faster processing
            self.video.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.video.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            print("✅ Camera opened at index 0")
        
        # Load face cascade
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        if os.path.exists(cascade_path):
            self.face_cascade = cv2.CascadeClassifier(cascade_path)
            if not self.face_cascade.empty():
                print("✅ Face cascade loaded successfully")
            else:
                self.face_cascade = None
        else:
            print(f"❌ Cascade file not found: {cascade_path}")
            self.face_cascade = None
        
        # Load recognizer
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        trainer_path = 'static/trainer.yml'
        if os.path.exists(trainer_path):
            self.recognizer.read(trainer_path)
            print("✅ Face recognizer loaded")
        else:
            print("⚠️ No trainer.yml found – train faces first")
        
        self.load_user_map()

    def load_user_map(self):
        map_path = 'static/user_map.json'
        if os.path.exists(map_path):
            with open(map_path, 'r') as f:
                self.user_map = json.load(f)
            print(f"✅ Loaded {len(self.user_map)} users")
        else:
            print("⚠️ No user_map.json found")

    def get_name_from_id(self, user_id):
        return self.user_map.get(str(user_id), f"User_{user_id}")

    def stop(self):
        if self.video and self.video.isOpened():
            self.video.release()
            print("Camera released")

    def __del__(self):
        self.stop()

    # ========== CORRECTED METHOD: get_frame_raw ==========
    def get_frame_raw(self):
        with self.lock:
            if self.video is None or not self.video.isOpened():
                return False, None
            ret, frame = self.video.read()
            return ret, frame

    # ========== CORRECTED METHOD: get_face_for_capture ==========
    def get_face_for_capture(self):
        with self.lock:
            if self.video is None or not self.video.isOpened():
                return False, None
            ret, frame = self.video.read()
            if not ret or frame is None:
                return False, None
            
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Apply CLAHE (lighting normalization)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            gray = clahe.apply(gray)
            
            # Detect faces with optimized parameters
            if self.face_cascade is None:
                return False, None
            
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(60,60))
            if len(faces) == 0:
                return False, None
            
            # Take the largest face (first one)
            (x, y, w, h) = faces[0]
            face_roi = gray[y:y+h, x:x+w]
            face_resized = cv2.resize(face_roi, self.face_roi_size)
            return True, face_resized

    # ========== CORRECTED METHOD: generate (for video streaming) ==========
    def generate(self):
        while True:
            with self.lock:
                if self.video is None or not self.video.isOpened():
                    break
                ret, frame = self.video.read()
                if not ret:
                    break
            # Encode frame as JPEG
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n\r\n')