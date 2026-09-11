import sys
import os
import numpy as np
import cv2

current_dir = os.path.dirname(os.path.abspath(__file__)) # .../server
liveness_path = os.path.join(current_dir, 'liveness')    # .../server/liveness

if liveness_path not in sys.path:
    sys.path.append(liveness_path)

try:
    from src.anti_spoof_predict import AntiSpoofPredict
    from src.generate_patches import CropImage
except ImportError as e:
    print("ERROR: Could not import liveness modules.")
    raise e

class LivenessDetector:
    def __init__(self, threshold=0.85):
        self.threshold = threshold
        device = 0 if cv2.cuda.getCudaEnabledDeviceCount() > 0 else "cpu"
        self.model = AntiSpoofPredict(device)
        self.cropper = CropImage()
        
        # Absolute path to the model file
        self.model_path = os.path.join(liveness_path, "resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth")
        
        if not os.path.exists(self.model_path):
            print(f"[ERROR] Model file not found at: {self.model_path}")
            
        print(f"[Liveness] Model loaded. Threshold: {self.threshold}")

    def check(self, frame, face_box):
        """
        Returns: (is_real, score)
        """
        # Convert (top, right, bottom, left) -> (x, y, w, h)
        top, right, bottom, left = face_box
        x = left
        y = top
        w = right - left
        h = bottom - top
        image_bbox = [x, y, w, h]
        
        try:
            # 1. CROP THE FACE
            # The model requires the image to be cropped to the face and resized to 80x80
            # We use the 'cropper' tool from the repo to do this scaling correctly
            param = {
                "org_img": frame,
                "bbox": image_bbox,
                "scale": 2.7,      # The model expects a 2.7x scale crop
                "out_w": 80,       # Model input width
                "out_h": 80,       # Model input height
                "crop": True,
            }
            cropped_img = self.cropper.crop(**param)
            
            # 2. PREDICT
            # We pass the CROPPED image and the MODEL PATH
            prediction = self.model.predict(cropped_img, self.model_path)
            
            # 3. ANALYZE SCORE
            # prediction output is [[Spoof_Score, Real_Score]]
            real_score = prediction[0][1]
            
            is_real = real_score > self.threshold
            return is_real, real_score

        except Exception as e:
            print(f"Liveness Check Error: {e}")
            return False, 0.0