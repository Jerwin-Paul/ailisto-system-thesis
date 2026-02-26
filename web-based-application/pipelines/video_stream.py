import cv2
import mediapipe as mp
from ultralytics import YOLO
import os
import time
import warnings

STREAM_ACTIVE = True
STREAM_PAUSED = False

# Resolve paths relative to this file's directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)

VIDEO_PATH = os.environ.get(
    "AILISTO_VIDEO_PATH",
    os.path.join(_PROJECT_ROOT, "data", "videos", "sample_vid.mp4"),
)
YOLO_MODEL_PATH = os.path.join(_PROJECT_ROOT, "yolov8n.pt")
POSE_MODEL_PATH = os.path.join(_SCRIPT_DIR, "pose_landmarker_lite.task")

print("Pose model path:", POSE_MODEL_PATH)

# Warn instead of crashing so the app can still start
if not os.path.exists(POSE_MODEL_PATH):
    warnings.warn(f"PoseLandmarker task file not found at {POSE_MODEL_PATH}")

PERSON_CLASS_ID = 0
CROP_PADDING = 20
MIN_CROP_SIZE = 80

# Load models once
yolo = YOLO(YOLO_MODEL_PATH)

BaseOptions = mp.tasks.BaseOptions
PoseLandmarker = mp.tasks.vision.PoseLandmarker
PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

pose_options = PoseLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=POSE_MODEL_PATH),
    running_mode=VisionRunningMode.IMAGE
)

def generate_frames():
    global STREAM_ACTIVE, STREAM_PAUSED

    cap = cv2.VideoCapture(VIDEO_PATH)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_delay = 1.0 / fps

    with PoseLandmarker.create_from_options(pose_options) as pose_landmarker:
        while cap.isOpened() and STREAM_ACTIVE:
            if STREAM_PAUSED:
                time.sleep(0.1)
                continue

            ret, frame = cap.read()
            if not ret:
                
                break

            _, buffer = cv2.imencode(".jpg", frame)
            frame_bytes = buffer.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                frame_bytes + b"\r\n"
            )

            time.sleep(frame_delay)

    cap.release()



