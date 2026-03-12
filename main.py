"""
DN-Studio CLI
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from dn_studio import config
from dn_studio.diarization_pipeline import run_pipeline
from dn_studio.generalised_mom_generator import main as mom_main
from dn_studio.generalised_brd_generator import main as brd_main

console = Console()


def cmd_diarize(args: argparse.Namespace) -> None:
    audio = args.audio or str(config.AUDIO_FILE)
    out = args.out or str(config.OUTPUT_DIR)
    console.rule("[bold cyan]DN-Studio · Diarization")
    run_pipeline(audio_path=audio, output_dir=out)


def cmd_mom(args: argparse.Namespace) -> None:
    console.rule("[bold magenta]DN-Studio · MoM Artifacts")
    mom_main([args.input, "--output-dir", args.output_dir, "--formats", args.formats,])


def cmd_brd(args: argparse.Namespace) -> None:
    console.rule("[bold green]DN-Studio · BRD Artifacts")
    brd_main([args.input, "--output", args.output,])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dn-studio", description="Console pipeline for diarization + MoM/BRD generation.",)
    sub = parser.add_subparsers(dest="command", required=True)

    p_diar = sub.add_parser("diarize", help="Run diarization on an audio file")
    p_diar.add_argument("--audio", help="Path to audio file (default from cfg/config.yaml)", default=None,)
    p_diar.add_argument("--out", help="Output directory for diarization artifacts", default=None,)
    p_diar.set_defaults(func=cmd_diarize)

    p_mom = sub.add_parser("mom", help="Generate MoM artifacts from MoM JSON")
    p_mom.add_argument("input", help="Path to MoM JSON")
    p_mom.add_argument("--output-dir", "-o", default="outputs/gcs/mom", help="Output directory",)
    p_mom.add_argument("--formats", default="md,pdf,docx", help="Comma-separated formats: md,pdf,docx",)
    p_mom.set_defaults(func=cmd_mom)

    p_brd = sub.add_parser("brd", help="Generate BRD DOCX from BRD JSON")
    p_brd.add_argument("input", help="Path to BRD JSON")
    p_brd.add_argument("--output", "-o", default="outputs/gcs/brd/BRD.docx", help="Output DOCX path",)
    p_brd.set_defaults(func=cmd_brd)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

