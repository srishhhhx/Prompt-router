import os
import pypdf
import sys
import time

def parse_with_pypdf(pdf_path):
    print(f"--- Parsing {pdf_path} with PyPDF ---")
    start_time = time.time()
    try:
        reader = pypdf.PdfReader(pdf_path)
        text = ""
        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            text += page.extract_text() + "\n"
        
        output_name = f"{os.path.basename(pdf_path)}_pypdf.txt"
        with open(output_name, "w", encoding="utf-8") as f:
            f.write(text)
        elapsed = time.time() - start_time
        print(f"[Success] Extracted {len(text)} characters in {elapsed:.2f} seconds. Saved to {output_name}\n")
    except Exception as e:
        print(f"[Error] Failed to parse {pdf_path}: {e}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 1_pypdf_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_pypdf(path)
    elif os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith('.pdf'):
                parse_with_pypdf(os.path.join(path, f))
