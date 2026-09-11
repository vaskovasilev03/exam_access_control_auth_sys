import os
import cv2
import math
import torch
import numpy as np
import torch.nn.functional as F
from src.model_lib.MiniFASNet import MiniFASNetV1, MiniFASNetV2,MiniFASNetV1SE,MiniFASNetV2SE
from src.data_io import transform as trans
from src.utility import get_kernel, parse_model_name

MODEL_MAPPING = {
    'MiniFASNetV1': MiniFASNetV1,
    'MiniFASNetV2': MiniFASNetV2,
    'MiniFASNetV1SE': MiniFASNetV1SE,
    'MiniFASNetV2SE': MiniFASNetV2SE
}

class Detection:
    def __init__(self):
        caffemodel = "./resources/detection_model/Widerface-RetinaFace.caffemodel"
        deploy = "./resources/detection_model/deploy.prototxt"
        self.detector = cv2.dnn.readNetFromCaffe(deploy, caffemodel)
        self.detector_confidence = 0.6

    def get_bbox(self, img):
        height, width = img.shape[0], img.shape[1]
        aspect_ratio = width / height
        if img.shape[1] * img.shape[0] >= 192 * 192:
            img = cv2.resize(img,
                             (int(192 * math.sqrt(aspect_ratio)),
                              int(192 / math.sqrt(aspect_ratio))), interpolation=cv2.INTER_LINEAR)

        blob = cv2.dnn.blobFromImage(img, 1, mean=(104, 117, 123))
        self.detector.setInput(blob)
        detections = self.detector.forward()

        bs, Cls, y, x = detections.shape
        max_conf = 0
        bbox = []
        for i in range(y):
            # conf = detections[0, 0, i, 2]
            if detections[0, 0, i, 2] > 0.1: # self.detector_confidence:
                # get the bounding box
                box = detections[0, 0, i, 3:7] * np.array([width, height, width, height])
                # (x, y, w, h)
                # bbox.append([box[0], box[1], box[2], box[3]])
                if detections[0, 0, i, 2] > max_conf:
                    max_conf = detections[0, 0, i, 2]
                    bbox = [box[0], box[1], box[2], box[3]]
        return bbox


class AntiSpoofPredict(Detection):
    def __init__(self, device_id):
        
        self.device = torch.device("cuda:{}".format(device_id)
                                   if torch.cuda.is_available() else "cpu")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(script_dir, ".."))
        
        caffemodel = os.path.join(root_dir, "resources/detection_model/Widerface-RetinaFace.caffemodel")
        deploy = os.path.join(root_dir, "resources/detection_model/deploy.prototxt")
      
        print(f"[DEBUG] Loading Caffe Model from: {deploy}")
        
        if not os.path.exists(deploy):
            print(f"[ERROR] Deploy file missing at: {deploy}")
        if not os.path.exists(caffemodel):
             print(f"[ERROR] Caffemodel file missing at: {caffemodel}")

        self.detector = cv2.dnn.readNetFromCaffe(deploy, caffemodel)
        self.detector_confidence = 0.6


    def _load_model(self, model_path):
        # define model
        model_name = os.path.basename(model_path)
        h_input, w_input, model_type, _ = parse_model_name(model_name)
        self.kernel_size = get_kernel(h_input, w_input,)
        self.model = MODEL_MAPPING[model_type](conv6_kernel=self.kernel_size).to(self.device)

        # load model weight
        state_dict = torch.load(model_path, map_location=self.device)
        keys = iter(state_dict)
        first_layer_name = keys.__next__()
        if first_layer_name.find('module.') >= 0:
            from collections import OrderedDict
            new_state_dict = OrderedDict()
            for key, value in state_dict.items():
                name_key = key[7:]
                new_state_dict[name_key] = value
            self.model.load_state_dict(new_state_dict)
        else:
            self.model.load_state_dict(state_dict)
        return None

    def predict(self, img, model_path):
        test_transform = trans.Compose([
            trans.ToTensor(),
        ])
        img = test_transform(img)
        img = img.unsqueeze(0).to(self.device)
        self._load_model(model_path)
        self.model.eval()
        with torch.no_grad():
            result = self.model.forward(img)
            result = F.softmax(result, dim=1).cpu().numpy()
        return result