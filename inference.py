"""
Minimum inference code
"""
import os
import numpy as np
from imageio import imwrite
from PIL import Image
import tensorflow as tf
from logger import get_logger


# NOTE: TF warnings are too noisy without this
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
tf.get_logger().setLevel(40)


def main(m_path, img_path, out_dir):
    cartoon = Cartoonizer(m_path)
    cartoon.init()
    cartoon.cartoon(img_path, out_dir)


model_path = 'exported_models/light_paprika_SavedModel'
model_path = 'exported_models/light_shinkai_SavedModel'

class Cartoonizer(object):
    def __init__(self, model_path):
        self.model_path = model_path
        self.logger = get_logger("inference")
        self.model = None

    def init(self):
        self.logger.info(f"load model " + self.model_path)
        self.model = tf.saved_model.load(self.model_path)
        self.model_f = self.model.signatures["serving_default"]
    
    def cartoon(self, img_path, out_dir):
        self.logger.info(f"generating image from {img_path}")
        
        img = np.array(Image.open(img_path).convert("RGB"))
        img = np.expand_dims(img, 0).astype(np.float32) / 127.5 - 1
        out = self.model_f(tf.constant(img))['output_1']
        out = ((out.numpy().squeeze() + 1) * 127.5).astype(np.uint8)
        if out_dir != "" and not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        if out_dir == "":
            out_dir = "."
        out_path = os.path.join(out_dir, os.path.split(img_path)[1])
        imwrite(out_path, out)
        self.logger.info(f"generated image saved to {out_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--img_path", type=str,
                        default=os.path.join("input_images", "temple.jpg"))
    parser.add_argument("--out_dir", type=str, default='out')
    args = parser.parse_args()
    main(model_path, args.img_path, args.out_dir)
