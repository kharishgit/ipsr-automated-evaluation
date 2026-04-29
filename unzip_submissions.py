import argparse
import os
import sys
import zipfile


def _is_within_directory(base_dir: str, target_path: str) -> bool:
    base_dir_abs = os.path.abspath(base_dir)
    target_abs = os.path.abspath(target_path)
    return os.path.commonpath([base_dir_abs, target_abs]) == base_dir_abs


def _should_skip(member_name: str) -> bool:
    name = member_name.replace("\\", "/")
    if name.startswith("__MACOSX/"):
        return True
    if name.endswith("/"):
        return False
    base = os.path.basename(name)
    if base in {".DS_Store", "Thumbs.db"}:
        return True
    return False


def unzip_to_submissions(zip_path: str, submissions_dir: str, *, overwrite: bool) -> int:
    if not os.path.isfile(zip_path):
        print(f"Zip file not found: {zip_path}", file=sys.stderr)
        return 2

    os.makedirs(submissions_dir, exist_ok=True)

    extracted = 0
    skipped = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if _should_skip(name):
                skipped += 1
                continue

            # Normalize to a relative path
            name_norm = name.replace("\\", "/").lstrip("/")
            if not name_norm or name_norm.startswith("../") or "/../" in name_norm:
                skipped += 1
                continue

            dest_path = os.path.join(submissions_dir, name_norm)
            if not _is_within_directory(submissions_dir, dest_path):
                skipped += 1
                continue

            if name.endswith("/"):
                os.makedirs(dest_path, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            if os.path.exists(dest_path) and not overwrite:
                skipped += 1
                continue

            with zf.open(info, "r") as src, open(dest_path, "wb") as dst:
                dst.write(src.read())
            extracted += 1

    print(f"Done. Extracted files: {extracted}. Skipped entries: {skipped}. Output: {submissions_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unzip a Moodle submissions ZIP into the Submissions/ folder."
    )
    parser.add_argument("zip", help="Path to the Moodle ZIP file")
    parser.add_argument(
        "--out",
        default="Submissions",
        help="Destination folder (default: Submissions)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing extracted files",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing contents of destination folder before extracting",
    )
    args = parser.parse_args()
    if args.clean and os.path.isdir(args.out):
        for name in os.listdir(args.out):
            full = os.path.join(args.out, name)
            try:
                if os.path.isdir(full) and not os.path.islink(full):
                    import shutil

                    shutil.rmtree(full)
                else:
                    os.remove(full)
            except OSError:
                pass
    return unzip_to_submissions(args.zip, args.out, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
