import os
import logging
from typing import Tuple, Union, List
import numpy as np
import cv2
import torch
from .core.predictor import AntiSpoofPredict
from .core.cropper import CropImage

logger = logging.getLogger("liveness")

_GLOBAL_LIVENESS_DETECTOR = None


class LivenessDetector:
    def __init__(self, threshold: float = 0.85, device_id: Union[int, str, None] = "cpu"):
        self.threshold = threshold
        device = device_id if device_id is not None else ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model = AntiSpoofPredict(device)
        self.cropper = CropImage()

        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.model_path = os.path.join(current_dir, "models", "2.7_80x80_MiniFASNetV2.pth")

        if not os.path.exists(self.model_path):
            logger.error(f"[Liveness] Model file not found at: {self.model_path}")
        else:
            # Warm up / pre-load model into memory
            try:
                self.model._load_model(self.model_path)
                logger.info(f"[Liveness] MiniFASNetV2 loaded successfully (threshold={self.threshold})")
            except Exception as e:
                logger.error(f"[Liveness] Failed to preload model: {e}")

    def check(self, frame: np.ndarray, face_box: Union[Tuple[int, int, int, int], List[int]]) -> Tuple[bool, float]:
        """
        Evaluate whether the face bounding box in frame is a live human or a spoof (flat photo, replay screen).
        
        face_box format:
          - Can be (top, right, bottom, left) from face_recognition
          - Or (x, y, w, h)
        
        Returns:
          (is_real: bool, real_score: float)
        """
        if frame is None or frame.size == 0:
            return False, 0.0

        # Disambiguate box format
        if len(face_box) == 4:
            v0, v1, v2, v3 = face_box
            # If top, right, bottom, left format (typical face_recognition box):
            if v2 > v0 and v1 > v3:
                top, right, bottom, left = v0, v1, v2, v3
                x = left
                y = top
                w = right - left
                h = bottom - top
            else:
                x, y, w, h = v0, v1, v2, v3
        else:
            return False, 0.0

        if w <= 0 or h <= 0:
            return False, 0.0

        image_bbox = [int(x), int(y), int(w), int(h)]

        try:
            param = {
                "org_img": frame,
                "bbox": image_bbox,
                "scale": 2.7,
                "out_w": 80,
                "out_h": 80,
                "crop": True,
            }
            cropped_img = self.cropper.crop(**param)
            if cropped_img is None or cropped_img.size == 0:
                return False, 0.0

            prediction = self.model.predict(cropped_img, self.model_path)
            real_score = float(prediction[0][1])
            is_real = bool(real_score >= self.threshold)
            return is_real, real_score

        except Exception as e:
            logger.error(f"[Liveness] Error during liveness inference: {e}")
            return False, 0.0


def get_liveness_detector(threshold: float = 0.85) -> LivenessDetector:
    global _GLOBAL_LIVENESS_DETECTOR
    if _GLOBAL_LIVENESS_DETECTOR is None:
        _GLOBAL_LIVENESS_DETECTOR = LivenessDetector(threshold=threshold)
    return _GLOBAL_LIVENESS_DETECTOR