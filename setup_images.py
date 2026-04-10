"""
Setup Script — Copy candidate images into static/images/
Run this ONCE: python setup_images.py
After running, you can delete this file.
"""
import shutil
import os
import glob

# Source: where the AI-generated images were saved
SOURCE_DIR = r"C:\Users\NITHIN KATA\.gemini\antigravity\brain\4a456dd8-2c92-437e-ac2e-1684f10397e4"

# Destination: Flask static images folder
DEST_DIR = os.path.join(os.path.dirname(__file__), "static", "images")

# Mapping: source filename pattern → destination filename
IMAGE_MAP = {
    "hemaditya_*": "hemaditya.png",
    "shyam_sunder_*": "shyam_sunder.png",
    "sai_teja_*": "sai_teja.png",
}

def main():
    os.makedirs(DEST_DIR, exist_ok=True)
    print(f"Destination folder: {DEST_DIR}")

    for pattern, dest_name in IMAGE_MAP.items():
        matches = glob.glob(os.path.join(SOURCE_DIR, pattern))
        # Filter to only the latest generated ones (with timestamp suffix)
        png_matches = [m for m in matches if m.endswith(".png")]

        if png_matches:
            # Pick the most recent one
            source = max(png_matches, key=os.path.getmtime)
            dest = os.path.join(DEST_DIR, dest_name)
            shutil.copy2(source, dest)
            print(f"  ✓ Copied {os.path.basename(source)} → {dest_name}")
        else:
            print(f"  ✗ No match found for pattern '{pattern}' in {SOURCE_DIR}")

    print("\nDone! You can now run: python app.py")

if __name__ == "__main__":
    main()
