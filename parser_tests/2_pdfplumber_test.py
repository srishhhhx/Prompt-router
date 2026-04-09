import os
import pdfplumber
import sys
import time

def parse_with_pdfplumber(pdf_path):
    print(f"--- Parsing {pdf_path} with pdfplumber ---")
    start_time = time.time()
    try:
        text = ""
        # pdfplumber is excellent for extracting tables as well.
        # Here we extract text layout, line by line.
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # Extract text preserving visual layout
                page_text = page.extract_text(layout=True)
                if page_text:
                    text += page_text + "\n"
                
                # Test table extraction
                tables = page.extract_tables()
                if tables:
                    text += "\n[Extracted Tables Found]\n"
                    for table in tables:
                        for row in table:
                            text += " | ".join(str(cell) if cell is not None else "" for cell in row) + "\n"
                        text += "-" * 40 + "\n"
        
        output_name = f"{os.path.basename(pdf_path)}_pdfplumber.txt"
        with open(output_name, "w", encoding="utf-8") as f:
            f.write(text)
        elapsed = time.time() - start_time
        print(f"[Success] Extracted text & tables in {elapsed:.2f} seconds. Saved to {output_name}\n")
    except Exception as e:
        print(f"[Error] Failed to parse {pdf_path}: {e}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 2_pdfplumber_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_pdfplumber(path)
    elif os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith('.pdf'):
                parse_with_pdfplumber(os.path.join(path, f))
