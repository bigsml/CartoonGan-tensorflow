import imageio
import os
import glob
import cv2
from common import logger


class FilePath(object):
    def __init__(self, file_path):
        self.file_path = file_path

        self.dir_name = os.path.dirname(self.file_path)
        self.file_name = os.path.basename(self.file_path)

        fs = os.path.splitext(self.file_name)
        self.file_name_no_ext = fs[0]
        self.file_ext = fs[1]


def convert_video_to_png(video_path, output_dir, max_num_frames=0, max_resized_height=0, frame_frequency=1):
    logger.debug(f"`{video_path}` is a video, extracting png images from it...")
    file_path = FilePath(video_path)
    gif_filename = file_path.file_name_no_ext

    png_dir = os.path.join(output_dir, gif_filename)
    if not os.path.exists(png_dir):
        logger.debug(f"Creating temporary folder: {png_dir} for storing intermediate result...")
        os.makedirs(png_dir)

    prev_generated_png_paths = glob.glob(png_dir + '/*.png')
    if prev_generated_png_paths:
        return prev_generated_png_paths

    png_paths = list()
    reader = imageio.get_reader(video_path)
    i = 0
    num_processed_frames = 0
    logger.debug("Generating png images...")
    try:
        for _, extracted_image in enumerate(reader):
            if max_num_frames > 0 and num_processed_frames > max_num_frames:
                break

            if max_resized_height > 0:
                width, height = extracted_image.shape[:2]
                aspect_ratio = width / height
                resized_height = min(height, max_resized_height)
                resized_width = int(resized_height * aspect_ratio)
                if width != resized_width:
                    logger.debug(f"resized ({width}, {height}) to: ({resized_width}, {resized_height})")
                    extracted_image = cv2.resize(extracted_image, (resized_width, resized_height))

            if i % frame_frequency == 0:
                png_filename = f"{i + 1}.png"
                png_path = os.path.join(png_dir, png_filename)

                logger.debug("write ", png_path)
                extracted_image = cv2.cvtColor(extracted_image, cv2.COLOR_RGBA2BGR);
                cv2.imwrite(png_path, extracted_image)
                # imageio.imsave(png_path, extracted_image)
                png_paths.append(png_path)
                num_processed_frames += 1

            i += 1

    except EOFError as e:
        print(e)
        pass  # end of sequence

    logger.debug(f"Number of {len(png_paths)} png images were generated at {png_dir}.")
    return png_paths

def test():
    f = "input_images/test.mp4"
    convert_video_to_png(f, "output_images")

if __name__ == "__main__":
    test()
