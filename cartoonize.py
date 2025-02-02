import os
import PIL
import sys
import glob
import imageio
import argparse
import numpy as np
from tqdm import tqdm
from datetime import datetime
from style_transfer.cartoongan import cartoongan
from common import logger, log_lvl
from transformer import convert_video_to_png, FilePath

STYLES = ["shinkai", "hayao", "hosoda", "paprika"]
VALID_EXTENSIONS = ['jpg', 'png', 'gif', 'JPG', 'mp4']

parser = argparse.ArgumentParser(description="transform real world images to specified cartoon style(s)")
parser.add_argument("--styles", nargs="+", default=[STYLES[0]],
                    help="specify (multiple) cartoon styles which will be used to transform input images.")
parser.add_argument("--all_styles", action="store_true",
                    help="set true if all styled results are desired")
parser.add_argument("--input_dir", type=str, default="input_images",
                    help="directory with images to be transformed")
parser.add_argument("--output_dir", type=str, default="output_images",
                    help="directory where transformed images are saved")
parser.add_argument("--batch_size", type=int, default=1,
                    help="number of images that will be transformed in parallel to speed up processing. "
                         "higher value like 4 is recommended if there are gpus.")
parser.add_argument("--ignore_gif", action="store_true",
                    help="transforming gif images can take long time. enable this when you want to ignore gifs")
parser.add_argument("--overwrite", action="store_true",
                    help="enable this if you want to regenerate outputs regardless of existing results")
parser.add_argument("--skip_comparison", action="store_true",
                    help="enable this if you only want individual style result and to save processing time")
parser.add_argument("--comparison_view", type=str, default="smart",
                    choices=["smart", "horizontal", "vertical", "grid"],
                    help="specify how input images and transformed images are concatenated for easier comparison")
parser.add_argument("--gif_frame_frequency", type=int, default=1,
                    help="how often should a frame in gif be transformed. freq=1 means that every frame "
                         "in the gif will be transformed by default. set higher frequency can save processing "
                         "time while make the transformed gif less smooth")
parser.add_argument("--max_num_frames", type=int, default=100,
                    help="max number of frames that will be extracted from a gif. set higher value if longer gif "
                         "is needed")
parser.add_argument("--keep_original_size", action="store_true",
                    help="by default the input images will be resized to reasonable size to prevent potential large "
                         "computation and to save file sizes. Enable this if you want the original image size.")
parser.add_argument("--max_resized_height", type=int, default=300,
                    help="specify the max height of a image after resizing. the resized image will have the same"
                         "aspect ratio. Set higher value or enable `keep_original_size` if you want larger image.")
parser.add_argument("--convert_gif_to_mp4", action="store_true",
                    help="convert transformed gif to mp4 which is much more smaller and easier to share. "
                         "`ffmpeg` need to be installed at first.")
parser.add_argument("--logging_lvl", type=str, default="info",
                    choices=["debug", "info", "warning", "error", "critical"],
                    help="logging level which decide how verbosely the program will be. set to `debug` if necessary")
parser.add_argument("--debug", action="store_true",
                    help="show the most detailed logging messages for debugging purpose")
parser.add_argument("--show_tf_cpp_log", action="store_true")

args = parser.parse_args()

TEMPORARY_DIR = os.path.join(f"{args.output_dir}", ".tmp")

if not args.debug:
    logger.setLevel(log_lvl[args.logging_lvl])

if not args.show_tf_cpp_log:
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

def pre_processing(image_path, style, expand_dim=True):
    input_image = PIL.Image.open(image_path).convert("RGB")

    if not args.keep_original_size:
        width, height = input_image.size
        aspect_ratio = width / height
        resized_height = min(height, args.max_resized_height)
        resized_width = int(resized_height * aspect_ratio)
        if width != resized_width:
            logger.debug(f"resized ({width}, {height}) to: ({resized_width}, {resized_height})")
            input_image = input_image.resize((resized_width, resized_height))

    input_image = np.asarray(input_image)
    input_image = input_image.astype(np.float32)

    input_image = input_image[:, :, [2, 1, 0]]

    if expand_dim:
        input_image = np.expand_dims(input_image, axis=0)
    return input_image


def post_processing(transformed_image, style):
    if not type(transformed_image) == np.ndarray:
        transformed_image = transformed_image.numpy()
    transformed_image = transformed_image[0]
    transformed_image = transformed_image[:, :, [2, 1, 0]]
    transformed_image = transformed_image * 0.5 + 0.5
    transformed_image = transformed_image * 255
    return transformed_image


def get_output_filename(output_dir, style, img_filename, file_ext=None, create_dir=True):
    save_dir = os.path.join(output_dir, style)
    if file_ext is not None:
        if file_ext[0] != '.':
            file_ext = '.' + file_ext
        img_filename = os.path.splitext(img_filename)[0] + file_ext
    output_filename = os.path.join(save_dir, img_filename)

    if create_dir and not os.path.exists(save_dir):
        os.makedirs(save_dir)

    return output_filename


def save_transformed_image(output_image, transformed_image_path):
    save_dir = os.path.dirname(transformed_image_path)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    if output_image is not None:
        image = PIL.Image.fromarray(output_image.astype("uint8"))
        image.save(transformed_image_path)

    return transformed_image_path


def save_concatenated_image(image_paths, image_folder="comparison", num_columns=2):
    images = [PIL.Image.open(i).convert('RGB') for i in image_paths]
    # pick the image which is the smallest, and resize the others to match it (can be arbitrary image shape here)
    min_shape = sorted([(np.sum(i.size), i.size) for i in images])[0][1]
    array = np.asarray([np.asarray(i.resize(min_shape)) for i in images])

    view = args.comparison_view
    if view == "smart":
        width, height = min_shape[0], min_shape[1]
        aspect_ratio = width / height
        logger.debug(f"(width, height): ({width}, {height}), aspect_ratio: {aspect_ratio}")
        grid_suitable = (len(args.styles) + 1) % num_columns == 0
        is_portrait = aspect_ratio <= 0.75
        if grid_suitable and not is_portrait:
            view = "grid"
        elif is_portrait:
            view = "horizontal"
        else:
            view = "vertical"

    if view == "horizontal":
        images_comb = np.hstack(array)
    elif view == "vertical":
        images_comb = np.vstack(array)
    elif view == "grid":
        rows = np.split(array, num_columns)
        rows = [np.hstack(row) for row in rows]
        images_comb = np.vstack([row for row in rows])
    else:
        logger.debug(f"Wrong `comparison_view`: {args.comparison_view}")

    images_comb = PIL.Image.fromarray(images_comb)
    file_name = image_paths[0].split(os.path.sep)[-1]

    if args.output_dir not in image_folder:
        image_folder = os.path.join(args.output_dir, image_folder)
    if not os.path.exists(image_folder):
        os.makedirs(image_folder)

    image_path = os.path.join(image_folder, file_name)
    images_comb.save(image_path)
    return image_path


def convert_gif_to_png(gif_path):
    logger.debug(f"`{gif_path}` is a gif, extracting png images from it...")
    gif_filename = gif_path.split(os.path.sep)[-1].replace(".gif", "")
    image = PIL.Image.open(gif_path)
    palette = image.getpalette()
    png_paths = list()
    i = 0

    png_dir = os.path.join(TEMPORARY_DIR, gif_filename)
    if not os.path.exists(png_dir):
        logger.debug(f"Creating temporary folder: {png_dir} for storing intermediate result...")
        os.makedirs(png_dir)

    prev_generated_png_paths = glob.glob(png_dir + '/*.png')
    if prev_generated_png_paths:
        return prev_generated_png_paths

    num_processed_frames = 0
    logger.debug("Generating png images...")
    try:
        while num_processed_frames < args.max_num_frames:

            image.putpalette(palette)
            extracted_image = PIL.Image.new("RGB", image.size)
            extracted_image.paste(image)

            if not args.keep_original_size:
                width, height = extracted_image.size
                aspect_ratio = width / height
                resized_height = min(height, args.max_resized_height)
                resized_width = int(resized_height * aspect_ratio)
                if width != resized_width:
                    logger.debug(f"resized ({width}, {height}) to: ({resized_width}, {resized_height})")
                    extracted_image = extracted_image.resize((resized_width, resized_height))

            if i % args.gif_frame_frequency == 0:
                png_filename = f"{i + 1}.png"
                png_path = os.path.join(png_dir, png_filename)
                extracted_image.save(png_path)
                png_paths.append(png_path)
                num_processed_frames += 1

            image.seek(image.tell() + 1)
            i += 1

    except EOFError:
        pass  # end of sequence

    logger.debug(f"Number of {len(png_paths)} png images were generated at {png_dir}.")
    return png_paths


def transform_png_images(image_paths, model, style, return_existing_result=False):
    sep = os.path.sep
    transformed_image_paths = list()
    save_dir = os.path.join(sep.join(image_paths[0].split(sep)[:-1]), style)
    logger.debug(f"Transforming {len(image_paths)} images and saving them to {save_dir}....")

    if return_existing_result:
        return glob.glob(os.path.join(save_dir, "*.png"))

    num_batch = int(np.ceil(len(image_paths) / args.batch_size))
    image_paths = np.array_split(image_paths, num_batch)

    logger.debug(f"Processing {num_batch} batches with batch_size={args.batch_size}...")
    for batch_image_paths in image_paths:
        image_filenames = [path.split(os.path.sep)[-1] for path in batch_image_paths]
        input_images = [pre_processing(path, style=style, expand_dim=False) for path in batch_image_paths]
        input_images = np.stack(input_images, axis=0)
        transformed_images = model(input_images)
        output_images = [post_processing(image, style=style)
                         for image in np.split(transformed_images, transformed_images.shape[0])]

        output_image_files = [os.path.join(save_dir, f) for f in image_filenames]
        paths = [save_transformed_image(img, f)
                 for img, f in zip(output_images, output_image_files)]
        transformed_image_paths.extend(paths)

    return transformed_image_paths


def save_png_images_as_gif(gif_path, image_paths):
    gif_dir = os.path.dirname(gif_path)
    if not os.path.exists(gif_dir):
        os.makedirs(gif_dir)

    with imageio.get_writer(gif_path, mode='I') as writer:
        file_names = sorted(image_paths, key=lambda x: int(x.split(os.path.sep)[-1].replace('.png', '')))
        logger.debug(f"Combining {len(file_names)} png images into {gif_path}...")
        for i, filename in enumerate(file_names):
            image = imageio.imread(filename)
            writer.append_data(image)
    return gif_path


def convert_gif_to_mp4(gif_path, crf=25):
    mp4_dir = os.path.join(os.path.dirname(gif_path), "mp4")
    gif_file = gif_path.split(os.path.sep)[-1]
    if not os.path.exists(mp4_dir):
        os.makedirs(mp4_dir)
    mp4_path = os.path.join(mp4_dir, gif_file.replace(".gif", ".mp4"))
    cmd = "ffmpeg -y -i {} -movflags faststart -pix_fmt yuv420p -vf \"scale=trunc(iw/2)*2:trunc(ih/2)*2\" -crf {} {}"
    cmd = cmd.replace("My Drive", "My\ Drive")
    os.system(cmd.format(gif_path, crf, mp4_path))


def result_exist(image_path, style):
    return os.path.exists(os.path.join(args.output_dir, style, image_path.split(os.path.sep)[-1]))


class ImageTransform(object):
    def __init__(self, image_path, overwrite=True):
        self.image_path = image_path
        self.image_filename = os.path.basename(self.image_path)
        self.related_image_paths = [image_path]
        self.overwrite = overwrite

    def convert(self, model, style):
        transformed_image_path = get_output_filename(args.output_dir, style, self.image_filename)
        return_existing_result = result_exist(self.image_path, style) and not self.overwrite

        if not return_existing_result:
            input_image = pre_processing(self.image_path, style=style)
            transformed_image = model(input_image)
            output_image = post_processing(transformed_image, style=style)
            transformed_image_path = save_transformed_image(output_image, transformed_image_path)

        self.related_image_paths.append(transformed_image_path)

        return transformed_image_path

    def gen_comparison(self):
        save_concatenated_image(self.related_image_paths)


class GifTransform(object):
    def __init__(self, image_path, convert_to_mp4=True, overwrite=True):
        self.image_path = image_path
        self.image_filename = os.path.basename(self.image_path)
        self.overwrite = overwrite
        self.convert_to_mp4 = convert_to_mp4
        self.image_file_path = FilePath(image_path)

        if self.image_path.endswith(".gif"):
            self.png_paths = convert_gif_to_png(self.image_path)
        else:
            self.png_paths = convert_video_to_png(self.image_path, TEMPORARY_DIR, args.max_num_frames, frame_frequency=args.gif_frame_frequency)
        self.png_paths_list = [self.png_paths]

    def convert(self, model, style):
        return_existing_result = result_exist(self.image_path, style) and not self.overwrite

        transformed_png_paths = transform_png_images(self.png_paths, model, style,
                                                     return_existing_result=return_existing_result)

        self.png_paths_list.append(transformed_png_paths)

        if not return_existing_result:
            gif_path = get_output_filename(args.output_dir, style, self.image_filename, ".gif")
            self._output_gif(gif_path, transformed_png_paths)

    def gen_comparison(self):
        num_images = len(self.png_paths)

        rearrange_paths_list = [[l[i] for l in self.png_paths_list] for i in range(num_images)]

        save_dir = os.path.join(TEMPORARY_DIR, self.image_filename.replace(".gif", ""), "comparison")

        combined_image_paths = list()
        for image_paths in rearrange_paths_list:
            path = save_concatenated_image(image_paths, image_folder=save_dir)
            combined_image_paths.append(path)

        gif_path = get_output_filename(args.output_dir, "comparison", self.image_filename, ".gif")
        self._output_gif(gif_path, combined_image_paths)
        return gif_path

    def _output_gif(self, gif_path, image_paths):
        save_png_images_as_gif(gif_path, image_paths)
        if self.convert_to_mp4:
            convert_gif_to_mp4(gif_path)
        return gif_path


def main():
    start = datetime.now()
    logger.info(f"Transformed images will be saved to `{args.output_dir}` folder.")
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    # create temporary folder which will be deleted after transformations
    if not os.path.exists(TEMPORARY_DIR):
        os.makedirs(TEMPORARY_DIR)

    # decide what styles to used in this execution
    styles = STYLES if args.all_styles else args.styles

    models = list()
    for style in styles:
        models.append(cartoongan.load_model(style))

    logger.info(f"Cartoonizing images using {', '.join(styles)} style...")

    image_paths = []
    for ext in VALID_EXTENSIONS:
        image_paths.extend(glob.glob(os.path.join(args.input_dir, f"*.{ext}")))
    logger.info(f"Preparing to transform {len(image_paths)} images from `{args.input_dir}` directory...")

    progress_bar = tqdm(image_paths, desc='Transforming')
    for image_path in progress_bar:
        image_filename = image_path.split(os.path.sep)[-1]
        progress_bar.set_postfix(File=image_filename)

        transform = None
        if image_filename.endswith(".gif") or image_filename.endswith('.mp4'):
            transform = GifTransform(image_path, args.convert_gif_to_mp4, args.overwrite)
        else:
            transform = ImageTransform(image_path, args.overwrite)

        if transform is not None:
            for model, style in zip(models, styles):
                transform.convert(model, style)

            if not args.skip_comparison:
                transform.gen_comparison()

    progress_bar.close()

    time_elapsed = datetime.now() - start
    logger.info(f"Total processing time: {time_elapsed}")


if __name__ == "__main__":
    main()
