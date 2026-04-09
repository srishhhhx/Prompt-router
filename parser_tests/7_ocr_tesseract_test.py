import os
import sys
import time

try:
    import pytesseract
    from pdf2image import convert_from_path
except ImportError:
    print("[Error] pytesseract or pdf2image not installed.")
    print("Run: pip install -r requirements-parsers.txt")
    sys.exit(1)

def parse_with_ocr(pdf_path):
    print(f"--- Parsing {pdf_path} with Tesseract OCR ---")
    start_time = time.time()
    
    # Note: This requires system dependencies 'tesseract' and 'poppler'.
    # On macOS, install them via: brew install tesseract poppler
    
    try:
        # Convert PDF pages to a list of PIL images
        print("Converting PDF to images (this may take a moment)...")
        pages = convert_from_path(pdf_path, dpi=300)
        
        extracted_text = ""
        
        # Loop through each page image and extract text
        for i, page_img in enumerate(pages):
            print(f"Running OCR on page {i+1}...")
            # We use tesseract to extract text. You can pass config flags to preserve layout if needed.
            page_text = pytesseract.image_to_string(page_img)
            extracted_text += f"\n--- Page {i+1} ---\n\n"
            extracted_text += page_text
            
        output_name = f"{os.path.basename(pdf_path)}_tesseract_ocr.txt"
        with open(output_name, "w", encoding="utf-8") as f:
            f.write(extracted_text)
            
        elapsed = time.time() - start_time
        print(f"[Success] Extracted text using OCR in {elapsed:.2f} seconds. Saved to {output_name}\n")
    except Exception as e:
        print(f"[Error] Failed to parse {pdf_path} with OCR: {e}")
        print("\nNote: Make sure system dependencies are installed: brew install tesseract poppler")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 7_ocr_tesseract_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_ocr(path)
    elif os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith('.pdf'):
                parse_with_ocr(os.path.join(path, f))
