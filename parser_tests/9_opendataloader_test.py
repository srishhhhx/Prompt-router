import os
import sys
import time
import opendataloader_pdf

def parse_with_opendataloader(path):
    print(f"--- Parsing {path} with opendataloader-pdf ---")
    start_time = time.time()
    try:
        # Convert the document
        opendataloader_pdf.convert(
            input_path=[path],
            output_dir=os.path.dirname(os.path.abspath(path)),
            format="markdown"
        )
        
        elapsed = time.time() - start_time
        print(f"[Success] Converted with opendataloader-pdf in {elapsed:.2f} seconds.\n")
    except Exception as e:
        print(f"[Error] Failed to parse {path}: {e}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 9_opendataloader_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_opendataloader(path)
    elif os.path.isdir(path):
        # opendataloader can handle directories directly, so we can just pass the path
        parse_with_opendataloader(path)
