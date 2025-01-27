import argparse
import os
import time
from typing import Optional, Tuple, Union

import torch
import torchaudio
from distutils import util
from loguru import logger
from numpy import ndarray
from torch import Tensor, nn
from torch.nn import functional as F

import df
from df import config
from df.checkpoint import load_model
from df.logger import init_logger
from df.model import ModelParams
from df.modules import get_device
from df.utils import as_complex, as_real, get_norm_alpha
from libdf import DF, erb, erb_norm, unit_norm


def main(args):
    if args.model_base_dir is None:
        args.model_base_dir = os.path.join(
            os.path.dirname(df.__file__), os.pardir, "pretrained_models", "DeepFilterNet"
        )
        if args.logging:
            print(f"Using default model at {args.model_base_dir}")
    if not os.path.isdir(args.model_base_dir):
        raise NotADirectoryError("Base directory not found at {}".format(args.model_base_dir))
    init_logger(file=os.path.join(args.model_base_dir, "enhance.log"), enabled=args.logging)
    config.load(
        os.path.join(args.model_base_dir, "config.ini"),
        config_must_exist=True,
        allow_defaults=False,
    )
    if args.pf:
        config.set(ModelParams().section, "mask_pf", True, bool)
    p = ModelParams()
    df_state = DF(
        sr=p.sr,
        fft_size=p.fft_size,
        hop_size=p.hop_size,
        nb_bands=p.nb_erb,
        min_nb_erb_freqs=p.min_nb_freqs,
    )
    checkpoint_dir = os.path.join(args.model_base_dir, "checkpoints")
    model, _ = load_model(checkpoint_dir, df_state)
    model = model.to(get_device())
    logger.info("Model loaded")
    if args.output_dir is None:
        args.output_dir = "."
    elif not os.path.isdir(args.output_dir):
        os.mkdir(args.output_dir)
    # Set suffix to model name
    suffix = os.path.basename(os.path.abspath(args.model_base_dir))
    if args.pf:
        suffix += "_pf"
    for file in args.noisy_audio_files:
        audio = enhance(model, df_state, file, log=True, pad=args.compensate_delay)
        save_audio(file, audio, p.sr, args.output_dir, log=True, suffix=suffix)


def df_features(audio: Tensor, df: DF, device=None) -> Tuple[Tensor, Tensor, Tensor]:
    p = ModelParams()
    spec = df.analysis(audio.numpy())  # [C, Tf] -> [C, Tf, F]
    a = get_norm_alpha(False)
    erb_fb = df.erb_widths()
    erb_feat = torch.as_tensor(erb_norm(erb(spec, erb_fb), a)).unsqueeze(1)
    spec_feat = as_real(torch.as_tensor(unit_norm(spec[..., : p.nb_df], a)).unsqueeze(1))
    spec = as_real(torch.as_tensor(spec).unsqueeze(1))
    if device is not None:
        spec = spec.to(device)
        erb_feat = erb_feat.to(device)
        spec_feat = spec_feat.to(device)
    return spec, erb_feat, spec_feat


def save_audio(
    file: str,
    audio: Union[Tensor, ndarray],
    sr: int,
    output_dir: Optional[str] = None,
    suffix: str = None,
    log: bool = False,
):
    outpath = file
    if suffix is not None:
        file, ext = os.path.splitext(file)
        outpath = file + f"_{suffix}" + ext
    if output_dir is not None:
        outpath = os.path.join(output_dir, os.path.basename(outpath))
    if log:
        logger.info(f"Saving audio file '{outpath}'")
    audio = torch.as_tensor(audio)
    if audio.ndim == 1:
        audio.unsqueeze_(0)
    if audio.dtype != torch.int16:
        audio = (audio * (1 << 15)).to(torch.int16)

    torchaudio.save(outpath, audio, sr)


@torch.no_grad()
def enhance(model: nn.Module, df_state: DF, file: str, log: bool = False, pad=False):
    p = ModelParams()
    model.eval()
    audio, sr = torchaudio.load(file)
    bs = audio.shape[0]
    if hasattr(model, "reset_h0"):
        model.reset_h0(batch_size=bs, device=get_device())
    t_audio = audio.shape[-1] / sr
    if sr != p.sr:
        logger.warning(
            f"Audio sampling rate does not match model sampling rate ({sr}, {p.sr}). Resampling..."
        )
        audio = torchaudio.functional.resample(audio, sr, p.sr)
    orig_len = audio.shape[-1]
    if pad:
        # Pad audio to compensate for the delay due to the real-time STFT implementation
        audio = F.pad(audio, (0, p.fft_size))
    t0 = time.time()
    spec, erb_feat, spec_feat = df_features(audio, df_state, device=get_device())
    spec = model(spec, erb_feat, spec_feat)[0].cpu()
    t1 = time.time()
    audio = df_state.synthesis(as_complex(spec.squeeze(1)).numpy())
    t = t1 - t0
    rtf = t_audio / t
    if log:
        logger.info(
            f"Enhanced noisy audio file '{file}' in {t:.1f}s (RT factor: {rtf:.1f})"
        )
    if pad:
        # Overall, the STFT/ISTFT loop introduces a delay of p.fft_size. Since this python script
        # operates on the full signal and not on a per-frame-basis, the frame size (i.e. p.hop_size)
        # can be neglected.
        d = p.fft_size - p.hop_size
        audio = audio[:, d: orig_len + d]
    return audio


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-base-dir",
        "-m",
        type=str,
        default=None,
        help="Model directory containing checkpoints and config.",
    )
    parser.add_argument(
        "noisy_audio_files",
        type=str,
        nargs="+",
        help="List of noise files to mix with the clean speech file.",
    )
    parser.add_argument(
        "--pf",
        help="Postfilter that slightly overattenuates very noisy sections.",
        action="store_true",
    )
    parser.add_argument("--output-dir", "-o", type=str, default=None)
    parser.add_argument(
        "--compensate-delay",
        "-d",
        action="store_true",
        help="Add some paddig to compensate the delay introduced by the real-time STFT/ISTFT implementation.",
    )
    parser.add_argument(
        "--logging",
        "-l",
        default=True,
        type=util.strtobool,
        help="Add some paddig to compensate the delay introduced by the real-time STFT/ISTFT implementation.",
    )
    args = parser.parse_args()
    main(args)
