#!/usr/bin/env python3
"""
LLM Analysis Tool - Send large text corpora to high-context LLMs via OpenRouter.
"""
import os
import sys
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# Load .env from project root
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from openai import OpenAI

DEFAULT_PROMPT = """You are a Staff Software Engineer and Security Architect reviewing the overnight run of an autonomous AI coding agent.

The agent attempted to fix issues in a local SOC/SIEM pipeline. Some succeeded, some were rejected by safety gates (AST, Pytest, Truncation), and some were deferred for human review.

### YOUR TASK:
Perform a "Failure Pattern Analysis" on the rejections and deferred items in the data below.

1. **Categorize the Failures:** Group the rejections into 3-5 distinct categories. Provide estimated counts for each.
2. **Identify Architectural Debt:** Based on the deferred items and repeated failures, what underlying technical debt or design patterns in this codebase are making it hostile to AI refactoring?
3. **Recommend 3 "Pre-Refactoring" Tasks:** Before I let the AI loose again, what 3 manual architectural changes should I make to the codebase to increase the AI's success rate from ~45% to 80%?

Output a structured, executive-level report. Be ruthless and analytical.

=== BEGIN DATA ===
{corpus}
=== END DATA ===
"""

def main() -> None:
    parser = argparse.ArgumentParser(description="Send a large text file to a high-context LLM via OpenRouter for analysis.")
    parser.add_argument("--file", dest="input_file", help=argparse.SUPPRESS)
    parser.add_argument("input_file", nargs="?", help="Path to the text file to analyze")
    parser.add_argument("--model", default="nvidia/nemotron-3.5-lightning:free", help="OpenRouter model ID")
    parser.add_argument("--prompt-file", help="Optional: path to a custom prompt file. Use {corpus} as placeholder.")
    parser.add_argument("--output", help="Optional: explicit output file path")
    parser.add_argument("--max-tokens", type=int, default=4000, help="Max tokens for the response")
    parser.add_argument("--temperature", type=float, default=0.2, help="Temperature for the response")
    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        sys.exit(1)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ OPENROUTER_API_KEY not found in .env or environment.")
        sys.exit(1)

    print(f"📖 Reading {input_path}...")
    corpus = input_path.read_text(encoding="utf-8")
    print(f"   Loaded {len(corpus):,} characters ({len(corpus.split()):,} words)")

    # Build prompt
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.exists():
            print(f"❌ Prompt file not found: {prompt_path}")
            sys.exit(1)
        prompt_template = prompt_path.read_text(encoding="utf-8")
        if "{corpus}" not in prompt_template:
            prompt_template += "\n\n=== BEGIN DATA ===\n{corpus}\n=== END DATA ==="
    else:
        prompt_template = DEFAULT_PROMPT

    # Check for backlog task override (Implementation Mode)
    if os.getenv("IS_BACKLOG_TASK") == "true":
        task_desc = os.getenv("BACKLOG_TASK_DESCRIPTION", "Refactor this module.")
        prompt_template = f"""You are a Senior Staff Engineer implementing a critical architectural refactor.

TARGET FILE CONTENT:
{{corpus}}

CRITICAL TASK: {task_desc}

RULES:
- Output ONLY valid Python code or SEARCH/REPLACE blocks.
- Ensure all existing tests pass.
- Do not break existing API contracts unless explicitly required by the task.
- Focus on decoupling, type safety, and testability.
"""

    user_prompt = prompt_template.replace("{corpus}", corpus)

    # Dependency mapping (Ripple effect warning)
    print("🗺️  Mapping cross-file dependencies...")
    try:
        result = subprocess.run(
            ["python3", "tools/dependency_mapper.py", str(input_path)],
            capture_output=True, text=True, timeout=10
        )
        dep_output = result.stdout.strip()
        if dep_output.startswith("DEPENDENTS_FOUND:"):
            dep_list = dep_output.replace("DEPENDENTS_FOUND:", "").strip()
            ripple_warning = f"""

### ⚠️ CRITICAL CROSS-FILE DEPENDENCIES (RIPPLE EFFECT)
The following files IMPORT from this module. If you change function signatures, dataclass fields, or exported variables in this file, you MUST update these dependent files to prevent breaking the build:
{dep_list}
"""
            print(f"   ⚠️  Found dependent files. Injecting ripple warning into prompt.")
        else:
            ripple_warning = "\n### ℹ️ No external files import from this module. Safe to refactor internally.\n"
            print("   ✅ No external dependents found.")
    except Exception as e:
        ripple_warning = ""
        print(f"   ⚠️  Dependency mapping failed: {e}")

    user_prompt += ripple_warning

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    print(f"\n🚀 Sending to OpenRouter model: {args.model}")
    print(f"   Max tokens: {args.max_tokens} | Temperature: {args.temperature}")
    print("   (This may take 30-90 seconds for large files...)\n")

    try:
        response = client.chat.completions.create(
            model=args.model,
            messages=[
                {"role": "system", "content": "You are a Staff Software Engineer and Security Architect. Provide structured, evidence-based analysis."},
                {"role": "user", "content": user_prompt}
            ],
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    except Exception as e:
        print(f"❌ API request failed: {e}")
        sys.exit(1)

    try:
        result = response.choices[0].message.content
        if not result:
            result = "[LLM returned empty response]"
    except Exception:
        result = "[LLM returned empty response]"

    print("\n" + "=" * 70)
    print(f"📊 ANALYSIS REPORT ({args.model})")
    print("=" * 70 + "\n")
    print(result)

    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"overnight/llm_analysis_{timestamp}.md")

    output_path.write_text(str(result), encoding="utf-8")
    print(f"\n✅ Report saved to: {output_path}")

    if hasattr(response, "usage") and response.usage:
        print(f"\n📈 Token usage:")
        print(f"   Prompt:     {response.usage.prompt_tokens:,}")
        print(f"   Completion: {response.usage.completion_tokens:,}")
        print(f"   Total:      {response.usage.total_tokens:,}")

if __name__ == "__main__":
    main()
