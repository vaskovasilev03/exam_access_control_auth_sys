import os
import torch
import torch.nn.functional as F
from torchvision import transforms as trans
from .mini_fasnet import MiniFASNetV1, MiniFASNetV2, MiniFASNetV1SE, MiniFASNetV2SE
from .utility import get_kernel, parse_model_name

MODEL_MAPPING = {
    'MiniFASNetV1': MiniFASNetV1,
    'MiniFASNetV2': MiniFASNetV2,
    'MiniFASNetV1SE': MiniFASNetV1SE,
    'MiniFASNetV2SE': MiniFASNetV2SE
}


import numpy as np


class ToTensor:
    def __call__(self, pic):
        if isinstance(pic, np.ndarray):
            if pic.ndim == 2:
                pic = pic.reshape((pic.shape[0], pic.shape[1], 1))
            # MiniFASNet was trained on unnormalized raw [0..255] float inputs (see Minivision Silent-Face-Anti-Spoofing data_io/functional.py)
            img = torch.from_numpy(np.ascontiguousarray(pic.transpose((2, 0, 1))))
            return img.float()
        return pic


class AntiSpoofPredict:
    def __init__(self, device_id=None):
        if device_id is None or device_id == "cpu":
            self.device = torch.device("cpu")
        elif isinstance(device_id, int) or (isinstance(device_id, str) and str(device_id).isdigit()):
            self.device = torch.device(f"cuda:{device_id}" if torch.cuda.is_available() else "cpu")
        elif isinstance(device_id, torch.device):
            self.device = device_id
        else:
            self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

        self._models_cache = {}
        self._transform = trans.Compose([
            ToTensor(),
        ])

    def _load_model(self, model_path):
        if model_path in self._models_cache:
            self.model = self._models_cache[model_path]
            return

        model_name = os.path.basename(model_path)
        h_input, w_input, model_type, _ = parse_model_name(model_name)
        kernel_size = get_kernel(h_input, w_input)
        model = MODEL_MAPPING[model_type](conv6_kernel=kernel_size).to(self.device)

        state_dict = torch.load(model_path, map_location=self.device)
        keys = iter(state_dict)
        first_layer_name = keys.__next__()
        if first_layer_name.find('module.') >= 0:
            from collections import OrderedDict
            new_state_dict = OrderedDict()
            for key, value in state_dict.items():
                name_key = key[7:]
                new_state_dict[name_key] = value
            model.load_state_dict(new_state_dict)
        else:
            model.load_state_dict(state_dict)

        model.eval()
        self._models_cache[model_path] = model
        self.model = model

    def predict(self, img, model_path):
        """
        img: np.ndarray cropped face patch (80x80)
        Returns: softmax probabilities [[spoof_score, real_score]]
        """
        self._load_model(model_path)
        img_tensor = self._transform(img).unsqueeze(0).to(self.device)
        with torch.no_grad():
            result = self.model.forward(img_tensor)
            result = F.softmax(result, dim=1).cpu().numpy()
        return result