import os
import sys
import time
import pymupdf4llm

def parse_with_pymupdf4llm(pdf_path):
    print(f"--- Parsing {pdf_path} with pymupdf4llm ---")
    start_time = time.time()
    try:
        # Converts the PDF directly into Markdown formatted text
        # This is ideal for passing to LLMs for intent classification and extraction
        md_text = pymupdf4llm.to_markdown(pdf_path)
        
        output_name = f"{os.path.basename(pdf_path)}_pymupdf4llm.md"
        with open(output_name, "w", encoding="utf-8") as f:
            f.write(md_text)
        elapsed = time.time() - start_time
        print(f"[Success] Converted to Markdown in {elapsed:.2f} seconds. Saved to {output_name}\n")
    except Exception as e:
        print(f"[Error] Failed to parse {pdf_path}: {e}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 4_pymupdf4llm_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_pymupdf4llm(path)
    elif os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith('.pdf'):
                parse_with_pymupdf4llm(os.path.join(path, f))
