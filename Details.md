1. Objective
Develop a system that accepts user prompts and documents as input, identifies the intent from the prompt, and
routes the request to the appropriate processing module. The system should use the prompt to determine the
required operation and apply it to the provided document.
2. Scope
• Accept user prompts and documents (PDF, image, or text) as input.
• Analyze prompts to identify primary intent (e.g., extraction, classification, summarization).
• Route the request to the appropriate processing module based on the detected intent.
• Generate output including detected intent and processed result.
• Handle multiple inputs and basic error handling.
3. Guidelines
3.1 Reference Tools: Feel free to explore State Of The Art (SOTA) Open-Source Libraries/Tools to achieve accuracy.
• LLM Integration
a. LLM APIs or open-source models (e.g., OpenAI, Anthropic, Gemini, or LLaMA, Qwen, TinyLlama): A single
model may be used for all tasks, or different models can be selected for specific tasks based on suitability.
• Backend Development
a. FastAPI (Python): Build APIs for prompt handling, routing, and execution logic.
• Frontend Development
a. React.js: Build UI for prompt input, document upload, and result display.
3.2 Leverage AI Code Generation Tools: Feel free to explore any tool, below is for reference only.
• Cursor: Generate boilerplate code and debug using GPT-4/Claude and OCR integration.
• GitHub Copilot: Auto-generate functions and unit tests.
3.3 Security Requirements
• Exclude PII (API keys, emails) from code.
• Use environment variables for credentials.
• Add a `.gitignore` file to exclude sensitive configs.
3.4 Acceptance Criteria
1. Code Submission:
a. Working modular code uploaded to your GitHub repository with Apache 2.0 license.
b. `requirements.txt` with pinned dependency versions.
c. No hardcoded credentials or PII in the codebase.
2. Readme File: A comprehensive document covering below sections at the minimum
a. High-Level Design: Architecture diagram showing prompt ingestion, intent detection, routing, and
processing modules.
b. Implementation Details: Tools and Libraries used with rationale for tool choices.
c. Steps to build and test the project
4. Sample Document(s)
Refer to the sample documents provided for testing.