import os
import logging
from typing import Tuple, Union, List, Optional
import numpy as np
import cv2
import torch
from .core.predictor import AntiSpoofPredict
from .core.cropper import CropImage
from .core.utility import parse_model_name

logger = logging.getLogger("liveness")

_GLOBAL_LIVENESS_DETECTOR = None


class LivenessDetector:
    def __init__(self, threshold: Optional[float] = None, device_id: Union[int, str, None] = "cpu"):
        if threshold is not None:
            self.threshold = float(threshold)
        else:
            self.threshold = float(os.getenv("LIVENESS_THRESHOLD", "0.60"))

        device = device_id if device_id is not None else ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model = AntiSpoofPredict(device)
        self.cropper = CropImage()
        self.last_details = {}

        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.models_dir = os.path.join(current_dir, "models")
        self.model_path = os.path.join(self.models_dir, "2.7_80x80_MiniFASNetV2.pth")

        # Discover all available .pth models in models/ for ensemble prediction
        self.active_models = []
        if os.path.exists(self.models_dir):
            for fname in sorted(os.listdir(self.models_dir)):
                if fname.endswith(".pth"):
                    fpath = os.path.join(self.models_dir, fname)
                    try:
                        h_in, w_in, mtype, scale = parse_model_name(fname)
                        self.model._load_model(fpath)
                        self.active_models.append({
                            "name": fname,
                            "path": fpath,
                            "h": h_in,
                            "w": w_in,
                            "scale": scale,
                            "type": mtype
                        })
                    except Exception as e:
                        logger.warning(f"[Liveness] Could not preload {fname}: {e}")

        logger.info(f"[Liveness] MiniFASNet initialized with {len(self.active_models)} models, threshold={self.threshold}")

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
            if not self.active_models:
                # Fallback to single model
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
            else:
                # Ensemble prediction over all active models (scale 2.7 + scale 4.0)
                total_prediction = np.zeros((1, 3))
                for m_info in self.active_models:
                    param = {
                        "org_img": frame,
                        "bbox": image_bbox,
                        "scale": m_info["scale"],
                        "out_w": m_info["w"],
                        "out_h": m_info["h"],
                        "crop": True,
                    }
                    cropped = self.cropper.crop(**param)
                    if cropped is None or cropped.size == 0:
                        continue
                    pred = self.model.predict(cropped, m_info["path"])
                    total_prediction += pred

                prediction = total_prediction / max(1, len(self.active_models))

            p_paper = float(prediction[0][0])
            p_real = float(prediction[0][1])
            p_screen = float(prediction[0][2])
            argmax_class = int(np.argmax(prediction))

            real_score = p_real
            is_real = bool(real_score >= self.threshold)

            self.last_details = {
                "score": real_score,
                "threshold": self.threshold,
                "is_real": is_real,
                "paper_prob": p_paper,
                "real_prob": p_real,
                "screen_prob": p_screen,
                "argmax": argmax_class,
            }

            print(
                f"[Liveness Evaluation] Real: {real_score:.3f} | Threshold: {self.threshold:.2f} | "
                f"Paper: {p_paper:.3f} | Screen: {p_screen:.3f} | Argmax: {argmax_class} -> "
                f"{'PASS' if is_real else 'FAIL (SPOOF)'}"
            )
            return is_real, real_score

        except Exception as e:
            logger.error(f"[Liveness] Error during liveness inference: {e}")
            return False, 0.0


def get_liveness_detector(threshold: Optional[float] = None) -> LivenessDetector:
    global _GLOBAL_LIVENESS_DETECTOR
    if _GLOBAL_LIVENESS_DETECTOR is None:
        _GLOBAL_LIVENESS_DETECTOR = LivenessDetector(threshold=threshold)
    elif threshold is not None:
        _GLOBAL_LIVENESS_DETECTOR.threshold = float(threshold)
    return _GLOBAL_LIVENESS_DETECTOR