import os
import sys
from dotenv import load_dotenv

# Import Azure Document Intelligence modules
try:
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
except ImportError:
    print("[Error] Azure Document Intelligence SDK not installed. Please run: pip install -r requirements-parsers.txt")
    sys.exit(1)

# Load environment variables from .env file
load_dotenv()

import time

def parse_with_azure_doc_intel(pdf_path):
    print(f"--- Parsing {pdf_path} with Azure Document Intelligence ---")
    start_time = time.time()
    
    # Needs Endpoint and Key environment variables
    endpoint = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    key = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY")
    
    if not endpoint or not key:
        print("[Error] Missing Azure Credentials.")
        print("Please set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY in your .env file.")
        return

    # Initialize the client
    client = DocumentIntelligenceClient(
        endpoint=endpoint, 
        credential=AzureKeyCredential(key)
    )

    try:
        with open(pdf_path, "rb") as f:
            # We use "prebuilt-layout" which provides text, tables, and marks.
            # Using output_content_format="markdown" returns formatted Markdown, great for LLMs!
            poller = client.begin_analyze_document(
                "prebuilt-layout", 
                body=f, 
                output_content_format="markdown",
                content_type="application/octet-stream"
            )
            
            result = poller.result()
            
            # The extracted text/markdown content is available in result.content
            md_text = result.content
            
            output_name = f"{os.path.basename(pdf_path)}_azure.md"
            with open(output_name, "w", encoding="utf-8") as out:
                out.write(md_text if md_text else "")
                
        elapsed = time.time() - start_time
        print(f"[Success] Extracted Markdown in {elapsed:.2f} seconds. Saved to {output_name}\n")
    except Exception as e:
        print(f"[Error] Failed to parse {pdf_path} with Azure: {e}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 6_azure_doc_intel_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_azure_doc_intel(path)
    elif os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith('.pdf'):
                parse_with_azure_doc_intel(os.path.join(path, f))
