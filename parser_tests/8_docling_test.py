import os
import sys
import time
from docling.document_converter import DocumentConverter, PdfFormatOption, InputFormat
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.pipeline_options import PdfPipelineOptions

import torch
print(f"MPS Available: {torch.backends.mps.is_available()}")
print(f"MPS Built: {torch.backends.mps.is_built()}")

def parse_with_docling(pdf_path):
    print(f"--- Parsing {pdf_path} with Docling ---")
    start_time = time.time()
    try:
        # 1. Enable Hardware Acceleration (MPS for Apple Silicon)
        accel_options = AcceleratorOptions(device=AcceleratorDevice.MPS, num_threads=8)

        # 2. Use the faster pypdfium2 backend and disable image generation
        pipeline_options = PdfPipelineOptions(
            accelerator_options=accel_options,
            pdf_backend="pypdfium2", # Much faster than default for large PDFs
            generate_page_images=False, # Disable if you don't need thumbnails
            generate_picture_images=False
        )

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
        
        # Convert the document
        result = converter.convert(pdf_path)
        
        # Export to markdown
        md_text = result.document.export_to_markdown()
        
        # Save output
        output_name = f"{os.path.basename(pdf_path)}_docling.md"
        with open(output_name, "w", encoding="utf-8") as f:
            f.write(md_text)
            
        elapsed = time.time() - start_time
        print(f"[Success] Converted to Markdown with Docling in {elapsed:.2f} seconds. Saved to {output_name}\n")
    except Exception as e:
        print(f"[Error] Failed to parse {pdf_path}: {e}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 8_docling_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_docling(path)
    elif os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith('.pdf'):
                parse_with_docling(os.path.join(path, f))
