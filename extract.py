import argparse
import os
import shutil


def extract_student_files(source_folder: str = "Submissions", destination_folder: str = "final_files") -> int:
    os.makedirs(destination_folder, exist_ok=True)

    if not os.path.isdir(source_folder):
        print(f"Source folder not found: {source_folder}")
        return 2

    extracted = 0

    for folder_name in os.listdir(source_folder):
        folder_path = os.path.join(source_folder, folder_name)
        if not os.path.isdir(folder_path):
            continue

        student_name = folder_name.split("college")[0].strip()

        for file in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file)
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file)[1]
            clean_name = student_name.replace(" ", "_")

            new_filename = f"{clean_name}{file_ext}"
            dest_path = os.path.join(destination_folder, new_filename)

            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(destination_folder, f"{clean_name}_{counter}{file_ext}")
                counter += 1

            shutil.copy2(file_path, dest_path)
            extracted += 1

    print(f"All files extracted and renamed successfully! Extracted: {extracted}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract/rename Moodle submission files into final_files/")
    parser.add_argument("--src", default="Submissions", help="Source folder (default: Submissions)")
    parser.add_argument("--dst", default="final_files", help="Destination folder (default: final_files)")
    parser.add_argument("--clean", action="store_true", help="Delete existing contents of destination folder first")
    args = parser.parse_args()

    if args.clean and os.path.isdir(args.dst):
        for name in os.listdir(args.dst):
            full = os.path.join(args.dst, name)
            try:
                if os.path.isdir(full) and not os.path.islink(full):
                    shutil.rmtree(full)
                else:
                    os.remove(full)
            except OSError:
                pass

    raise SystemExit(extract_student_files(source_folder=args.src, destination_folder=args.dst))
