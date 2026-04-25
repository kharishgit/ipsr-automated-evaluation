import os
import shutil
source_folder = "Submissions"
destination_folder = "final_files"
os.makedirs(destination_folder, exist_ok=True)
for folder_name in os.listdir(source_folder):
    folder_path = os.path.join(source_folder, folder_name)
    if os.path.isdir(folder_path):
        
        student_name = folder_name.split("college")[0].strip()

        for file in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file)

            if os.path.isfile(file_path):
                file_ext = os.path.splitext(file)[1]

                clean_name = student_name.replace(" ", "_")

                new_filename = f"{clean_name}{file_ext}"
                dest_path = os.path.join(destination_folder, new_filename)

                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(
                        destination_folder,
                        f"{clean_name}_{counter}{file_ext}"
                    )
                    counter += 1

                shutil.copy2(file_path, dest_path)

print("All files extracted and renamed successfully!")