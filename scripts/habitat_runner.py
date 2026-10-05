"""Run HABITAT's full_pipeline.py for one scene with paths from our config.

HABITAT reads all of its settings from `operational_config.py` (and, through
dataloader.py, `final_model_config.py`), both of which hardcode paths on the
original cluster. Rather than edit the HABITAT checkout, this script registers
replacement modules under those names in sys.modules before full_pipeline.py
runs, so every `from operational_config import *` inside HABITAT picks up the
values passed here.

It also covers the parts of HABITAT that assume a CUDA GPU, so the same code
runs on a laptop CPU (--device cpu) or Apple GPU (--device mps).

Usage:
    python scripts/habitat_runner.py --habitat-dir HABITAT --scene-dir ... \
        --output-dir ... --weights ... --image SCENE.tif [--footprint ...]
"""

import argparse
import os
import runpy
import sys
import types


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--habitat-dir", required=True, help="HABITAT checkout")
    p.add_argument("--scene-dir", required=True, help="directory holding the input scenes")
    p.add_argument("--output-dir", required=True, help="where HABITAT writes its outputs")
    p.add_argument("--weights", required=True, help="trained model (.pth, a pickled torch model)")
    p.add_argument("--image", required=True, help="scene file name inside --scene-dir")
    p.add_argument("--footprint", default=None,
                   help="footprint shapefile used to clip the scene (S_FILENAME column)")
    p.add_argument("--clean-data-dir", default="", help="HABITAT CLEAN_DATA_DIR (currently unused)")
    p.add_argument("--no-data-value", type=float, default=0,
                   help="scene NoData value, used only when no footprint is given")
    p.add_argument("--device", default="cuda", help="cuda, cpu or mps")
    p.add_argument("--size", type=int, default=512, help="tile size in pixels")
    p.add_argument("--overlap", type=float, default=0.5, help="tile overlap factor")
    p.add_argument("--channels", type=int, default=3)
    p.add_argument("--classes", type=int, default=3)
    p.add_argument("--encoder", default="resnet50")
    p.add_argument("--encoder-weights", default="imagenet")
    return p.parse_args()


def make_config_modules(args):
    """Build stand-ins for operational_config and final_model_config."""
    import albumentations as albu
    import segmentation_models_pytorch as smp
    import torch
    import torch.nn as nn
    from segmentation_models_pytorch import utils

    # The names HABITAT's modules get from `from operational_config import *`.
    shared = {"smp": smp, "torch": torch, "nn": nn, "albu": albu, "utils": utils}

    class Operational_Config(object):
        NAME = os.path.splitext(os.path.basename(args.weights))[0]
        INPUT_SCENE_DIR = args.scene_dir
        OUTPUT_DIR = args.output_dir
        WEIGHT_DIR = args.weights
        CLEAN_DATA_DIR = args.clean_data_dir
        FOOTPRINT_DIR = args.footprint
        SIZE = args.size
        OVERLAP_FACTOR = args.overlap
        CHANNELS = args.channels
        CLASSES = args.classes
        ENCODER = args.encoder
        ENCODER_WEIGHTS = args.encoder_weights
        PREPROCESS = smp.encoders.get_preprocessing_fn(args.encoder, args.encoder_weights)
        DEVICE = args.device

    # dataloader.py only reads these at import time; the training settings
    # (and the ImageNet download that building Final_Config.MODEL triggers)
    # aren't needed for inference.
    class Final_Config(object):
        SIZE = args.size
        CHANNELS = args.channels
        CLASSES = args.classes

    op = types.ModuleType("operational_config")
    op.__dict__.update(shared, Operational_Config=Operational_Config)
    fm = types.ModuleType("final_model_config")
    fm.__dict__.update(shared, Final_Config=Final_Config)
    return op, fm


def make_tensorflow_stub():
    """dataloader.py imports tensorflow only for one-hot masks during training."""
    tf = types.ModuleType("tensorflow")

    def unavailable(name):
        raise ImportError("tensorflow is not installed; HABITAT only needs it for training "
                          "(tf.%s was requested)" % name)

    tf.__getattr__ = unavailable
    return tf


def redirect_cuda(device):
    """HABITAT hardcodes .to('cuda'); send it to `device` instead."""
    import torch

    def fix(arg):
        if isinstance(arg, str) and arg.startswith("cuda"):
            return device
        if isinstance(arg, torch.device) and arg.type == "cuda":
            return torch.device(device)
        return arg

    module_to = torch.nn.Module.to
    tensor_to = torch.Tensor.to

    def module_to_fixed(self, *a, **kw):
        return module_to(self, *[fix(x) for x in a], **{k: fix(v) for k, v in kw.items()})

    def tensor_to_fixed(self, *a, **kw):
        return tensor_to(self, *[fix(x) for x in a], **{k: fix(v) for k, v in kw.items()})

    torch.nn.Module.to = module_to_fixed
    torch.Tensor.to = tensor_to_fixed


def patch_torch_load(device):
    """The weights are a whole pickled model, possibly saved from a GPU."""
    import torch

    load = torch.load

    def load_model(f, *a, **kw):
        kw.setdefault("map_location", device)
        kw.setdefault("weights_only", False)
        return load(f, *a, **kw)

    torch.load = load_model


def main():
    args = parse_args()
    habitat_dir = os.path.abspath(args.habitat_dir)
    pipeline = os.path.join(habitat_dir, "full_pipeline.py")
    if not os.path.isfile(pipeline):
        sys.exit("No full_pipeline.py in %s (run `git submodule update --init`?)" % habitat_dir)

    # postprocess.py creates OUTPUT_DIR with os.mkdir, so its parent must exist.
    os.makedirs(args.output_dir, exist_ok=True)

    op, fm = make_config_modules(args)
    sys.modules["operational_config"] = op
    sys.modules["final_model_config"] = fm
    try:
        import tensorflow  # noqa: F401
    except ImportError:
        sys.modules["tensorflow"] = make_tensorflow_stub()

    if args.device != "cuda":
        redirect_cuda(args.device)
    patch_torch_load(args.device)

    sys.path.insert(0, habitat_dir)
    sys.argv = [pipeline, "--image=%s" % args.image]

    # full_pipeline.py only sets no_data_value when it clips to a footprint,
    # but uses it either way; supply it for the no-footprint case.
    init_globals = {}
    if args.footprint is None:
        init_globals["no_data_value"] = args.no_data_value

    runpy.run_path(pipeline, init_globals=init_globals, run_name="__main__")


if __name__ == "__main__":
    main()
