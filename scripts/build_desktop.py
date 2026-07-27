"""Desktop artifact naming, signing gates, checksums and provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

_SIGNING_SECRETS = {
    "windows": ("WINDOWS_SIGN_CERT_BASE64", "WINDOWS_SIGN_CERT_PASSWORD"),
    "macos": (
        "APPLE_CERTIFICATE_BASE64",
        "APPLE_CERTIFICATE_PASSWORD",
        "APPLE_DEVELOPER_ID",
        "APPLE_NOTARY_APPLE_ID",
        "APPLE_NOTARY_TEAM_ID",
        "APPLE_NOTARY_PASSWORD",
    ),
}


def artifact_name(version: str, platform_name: str, *, formal: bool) -> str:
    normalized = version.removeprefix("v")
    suffix = "" if formal else "-UNSIGNED"
    if platform_name == "windows":
        return f"daily-record-ocr-lite-v{normalized}-windows-x64-setup{suffix}.exe"
    if platform_name == "macos":
        return f"daily-record-ocr-lite-v{normalized}-macos-arm64{suffix}.dmg"
    raise ValueError(f"unsupported desktop platform: {platform_name}")


def formal_release_gate(
    platform_name: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = os.environ if environment is None else environment
    required = _SIGNING_SECRETS.get(platform_name)
    if required is None:
        raise ValueError(f"unsupported desktop platform: {platform_name}")
    missing = [name for name in required if not str(env.get(name, "")).strip()]
    return {"platform": platform_name, "ready": not missing, "missing": missing}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_build_metadata(
    artifacts: Sequence[Path],
    *,
    output_dir: Path,
    git_sha: str,
    platform_name: str,
    architecture: str,
) -> tuple[Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    records = [
        {"name": Path(artifact).name, "sha256": sha256_file(Path(artifact))}
        for artifact in sorted(artifacts, key=lambda path: Path(path).name)
    ]
    checksums = output / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{record['sha256']}  {record['name']}\n" for record in records),
        encoding="utf-8",
    )
    provenance = output / "build-provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "schema_version": "desktop-build-v1",
                "git_sha": git_sha,
                "platform": platform_name,
                "architecture": architecture,
                "artifacts": records,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return checksums, provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    gate = subparsers.add_parser("gate")
    gate.add_argument("platform", choices=sorted(_SIGNING_SECRETS))
    gate.add_argument("--formal", action="store_true")
    name = subparsers.add_parser("name")
    name.add_argument("platform", choices=sorted(_SIGNING_SECRETS))
    name.add_argument("version")
    name.add_argument("--formal", action="store_true")
    metadata = subparsers.add_parser("metadata")
    metadata.add_argument("platform", choices=sorted(_SIGNING_SECRETS))
    metadata.add_argument("architecture")
    metadata.add_argument("git_sha")
    metadata.add_argument("output_dir", type=Path)
    metadata.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "name":
        print(artifact_name(args.version, args.platform, formal=args.formal))
        return 0
    if args.command == "metadata":
        write_build_metadata(
            args.artifacts,
            output_dir=args.output_dir,
            git_sha=args.git_sha,
            platform_name=args.platform,
            architecture=args.architecture,
        )
        return 0
    result = formal_release_gate(args.platform)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if (not args.formal or result["ready"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
