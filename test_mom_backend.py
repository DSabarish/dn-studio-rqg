import os
import json
from pathlib import Path


def load_google_key_from_env_file(env_path: Path = Path(".env")) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("GOOGLE_API_KEY="):
            os.environ.setdefault("GOOGLE_API_KEY", line.split("=", 1)[1].strip())
            break


def main() -> None:
    from dn_studio.mom_llm import generate_mom

    load_google_key_from_env_file()

    transcript_path = Path("outputs/diarization/transcript.json")
    out_dir = Path("outputs/_mom_test")

    print(f"TRANSCRIPT_EXISTS {transcript_path.exists()} at {transcript_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    res = generate_mom(
        transcript_path=str(transcript_path),
        output_dir=str(out_dir),
        context="Backend MoM test",
    )
    print("RESULT_JSON")
    print(json.dumps(res, indent=2, ensure_ascii=False))

    mom_md_path = out_dir / "minutes" / "MoM.md"
    mom_json_path = out_dir / "minutes" / "MoM.json"
    trace_path = out_dir / "response_mom_trace.json"

    print("MOM_MD_PATH", mom_md_path, "EXISTS", mom_md_path.exists())
    print("MOM_JSON_PATH", mom_json_path, "EXISTS", mom_json_path.exists())
    print("TRACE_PATH", trace_path, "EXISTS", trace_path.exists())

    if mom_json_path.exists():
        print("OK: MoM backend produced JSON suitable for Word/PDF exports.")
    else:
        print("WARN: MoM JSON missing; check LLM response.")


if __name__ == "__main__":
    main()

