import os
import sys
from llama_parse import LlamaParse
from dotenv import load_dotenv
import nest_asyncio
import time



# Apply nest_asyncio if running in environments with existing event loops (like Jupyter)
nest_asyncio.apply()

# Load environment variables from a .env file if present
load_dotenv()

def parse_with_llamaparse(pdf_path):
    print(f"--- Parsing {pdf_path} with LlamaParse ---")
    start_time = time.time()
    
    # Needs LLAMA_CLOUD_API_KEY environment variable. 
    # You can get one for free at https://cloud.llamaindex.ai/
    api_key = os.environ.get("LLAMA_CLOUD_API_KEY")
    if not api_key:
        print("[Error] LLAMA_CLOUD_API_KEY environment variable is not set.")
        print("Please set it in your terminal or create a .env file with LLAMA_CLOUD_API_KEY=your_key")
        return

    try:
        # Initialize LlamaParse
        # Result type can be "text" or "markdown" (default)
        parser = LlamaParse(
            api_key=api_key,
            result_type="markdown",
            verbose=False,
            language="en",
            num_workers=4
        )
        
        # Load data (this communicates with the LlamaCloud API)
        documents = parser.load_data(pdf_path)
        
        # Combine all parsed document chunks
        md_text = "\n\n".join([doc.text for doc in documents])
        
        output_name = f"{os.path.basename(pdf_path)}_llamaparse.md"
        with open(output_name, "w", encoding="utf-8") as f:
            f.write(md_text)
        elapsed = time.time() - start_time
        print(f"[Success] Converted to Markdown with LlamaParse in {elapsed:.2f} seconds. Saved to {output_name}\n")
    except Exception as e:
        print(f"[Error] Failed to parse {pdf_path}: {e}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 5_llamaparse_test.py <pdf_file_or_directory>")
        sys.exit(1)
        
    path = sys.argv[1]
    if os.path.isfile(path):
        parse_with_llamaparse(path)
    elif os.path.isdir(path):
        for f in os.listdir(path):
            if f.lower().endswith('.pdf'):
                parse_with_llamaparse(os.path.join(path, f))
