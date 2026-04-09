import os
import fitz # PyMuPDF
import sys
import time

def parse_with_pymupdf(pdf_path):
    print(f"--- Parsing {pdf_path} with PyMuPDF ---")
    start_time = time.time()
    try:
        doc = fitz.open(pdf_path)
        text = ""
        # PyMuPDF is extremely fast and can extract text blocks
        for page in doc:
            # "blocks" parameter gives layout info (x0, y0, x1, y1, text, block_type, block_no)
            blocks = page.get_text("blocks")
            for b in blocks:
                # b[4] is the text content
                if b[6] == 0: # 0 means text block, 1 means image block
                    text += b[4]
            text += "\n--- Page Break ---\n"
            
        output_name = f"{os.path.basename(pdf_path)}_pymupdf.txt"
        with open(output_name, "w", encoding="utf-8") as f:
            f.write(text)
        elapsed = time.time() - start_time
        print(f"[Success] Extracted {len(text)} characters in {elapsed:.2f} seconds. Saved to {output_name}\n")
    except Exception as e:
        print(f"[Error] Failed to parse {pdf_path}: {e}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 3_pymupdf_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_pymupdf(path)
    elif os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith('.pdf'):
                parse_with_pymupdf(os.path.join(path, f))
