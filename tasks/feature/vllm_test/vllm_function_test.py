#!/usr/bin/env python3
"""
vLLM Function Calling Test Script (Optimized Version)
- Precise 64k token input with "Needle in a Haystack" logic
- Intent-driven Tool Calls (Implicit triggering)
- JSON serialization for input/output
"""

import json
import requests
import time
import os
from datetime import datetime

try:
    import tiktoken
    TOKENIZER_AVAILABLE = True
except ImportError:
    TOKENIZER_AVAILABLE = False
    print("\n[WARNING] 'tiktoken' is not installed. Token counting will be highly inaccurate (estimated by chars/4).")
    print("[WARNING] For a true 64k context test, please run: pip install tiktoken\n")


class VLLMFunctionTester:
    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api_base = api_base
        self.api_url = f"{api_base}/v1/chat/completions"
        self.models_url = f"{api_base}/v1/models"
        self.input_file = "test_input_optimized.json"
        self.output_file = "test_output_optimized.json"
        
        if TOKENIZER_AVAILABLE:
            print("Use tiktoken to encode")
            self.encoder = tiktoken.get_encoding("cl100k_base")
            print('Fetch cl100k_base done!')
        else:
            self.encoder = None

    def count_tokens(self, text: str) -> int:
        """Count exact tokens using tiktoken or estimate."""
        if self.encoder:
            return len(self.encoder.encode(text))
        return len(text) // 4

    def generate_haystack_with_needles(self, target_tokens: int = 64000) -> str:
        """Generate exactly target_tokens with specific facts injected at 10%, 50%, and 90%."""
        
        # Base repetitive text (The "Haystack")
        base_paragraph = (
            "The development of large language models has revolutionized AI. Modern architectures typically employ "
            "transformer-based designs with attention mechanisms. Training requires significant computational resources "
            "and careful optimization of loss functions. Ensuring helpful, harmless, and honest outputs via RLHF is "
            "crucial. Function calling extends capabilities beyond text generation to actual actions following a structured "
            "format. Comprehensive test suites are essential for reliable performance in enterprise environments. "
        )
        
        # Specific facts to test "Lost in the Middle" and extraction logic (The "Needles")
        needle_1 = " [CRITICAL FACT 1: The NovaLLM project utilized exactly 8192 H100 GPUs for a continuous training period of 4.5 months.] "
        needle_2 = " [CRITICAL FACT 2: A major breakthrough in 2026 was the adoption of Multi-Token Prediction (MTP) combined with 1F1B scheduling.] "
        needle_3 = " [CRITICAL FACT 3: The exact latency target for the new PagedAttention implementation was set to 15.5 milliseconds per request.] "

        print("Generating 64k token context and injecting factual needles...")
        
        if not self.encoder:
            # Fallback naive generation if tiktoken is missing
            full_text = (base_paragraph * 100) + needle_1 + (base_paragraph * 500) + needle_2 + (base_paragraph * 500) + needle_3 + (base_paragraph * 100)
            target_chars = target_tokens * 4
            if len(full_text) > target_chars:
                return full_text[:target_chars]
            return full_text.ljust(target_chars, ' ')

        # Precise generation using tiktoken
        base_tokens = self.encoder.encode(base_paragraph)
        n1_tokens = self.encoder.encode(needle_1)
        n2_tokens = self.encoder.encode(needle_2)
        n3_tokens = self.encoder.encode(needle_3)
        
        total_needle_tokens = len(n1_tokens) + len(n2_tokens) + len(n3_tokens)
        available_space = target_tokens - total_needle_tokens
        
        # Calculate repetitions needed
        repeats = available_space // len(base_tokens)
        remnants = available_space % len(base_tokens)
        
        # Assemble tokens with needles at roughly 10%, 50%, and 90% positions
        pos1 = int(repeats * 0.1)
        pos2 = int(repeats * 0.5)
        pos3 = int(repeats * 0.9)
        
        final_tokens = []
        for i in range(repeats):
            if i == pos1:
                final_tokens.extend(n1_tokens)
            if i == pos2:
                final_tokens.extend(n2_tokens)
            if i == pos3:
                final_tokens.extend(n3_tokens)
            final_tokens.extend(base_tokens)
            
        # Add exact padding to hit exactly target_tokens
        if remnants > 0:
            final_tokens.extend(base_tokens[:remnants])
            
        return self.encoder.decode(final_tokens)

    def get_tool_definitions(self) -> list[dict]:
        """Define tools for function calling test."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for information about recent events, news, or technology trends.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The specific search query string"},
                            "num_results": {"type": "integer", "description": "Number of results to return", "default": 3}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Perform mathematical calculations. Must be used when math or statistical computation is needed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string", "description": "Strictly mathematical expression (e.g., '(4.5 * 30 * 24) / 8192'). Do not use text."},
                        },
                        "required": ["expression"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze_document",
                    "description": "Analyze a document and extract key themes or summarize content.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "document_text": {"type": "string", "description": "The specific text to analyze"},
                            "analysis_type": {"type": "string", "enum": ["summary", "keywords", "sentiment", "entities"]}
                        },
                        "required": ["document_text", "analysis_type"]
                    }
                }
            }
        ]

    def prepare_test_input(self) -> dict:
        """Prepare test input data with precise 64k text and intent-driven prompt."""
        # Note: We generate slightly less than 64k to leave room for prompt & tools to fit inside a strict 64k context window if needed, 
        # but here we follow the original script's logic of 64k text + prompt.
        long_text = self.generate_haystack_with_needles(64000) 
        actual_tokens = self.count_tokens(long_text)
        
        # [OPTIMIZATION] Intent-driven prompt instead of explicit instructions
        user_prompt = (
            "\n\n--- END OF DOCUMENT ---\n\n"
            "Based on the comprehensive technical report above, please perform the following analysis. "
            "You must decide which tools are necessary to complete these tasks:\n\n"
            "Task A: Find the exact number of GPUs and the training duration mentioned in the text, and calculate the total compute hours (assume 1 month = 30 days and 1 day = 24 hours).\n"
            "Task B: Search online for the latest 2026 industry developments regarding 'Multi-Token Prediction' and '1F1B scheduling' to see if they align with the facts in the document.\n"
            "Task C: Extract the core themes from the document and generate a structured summary of the technical challenges.\n\n"
            "Please ensure your final response is highly detailed, spans at least 2000 tokens, and thoroughly covers all tasks."
        )
        
        prompt_tokens = self.count_tokens(user_prompt)
        total_input_tokens = actual_tokens + prompt_tokens
        
        system_prompt = (
            "You are an advanced AI assistant capable of complex reasoning and tool usage. "
            "You must automatically trigger tools when a task requires calculation, external knowledge, or specialized text processing."
        )
        system_tokens = self.count_tokens(system_prompt)
        tools_tokens = self.count_tokens(json.dumps(self.get_tool_definitions()))
        
        test_input = {
            "metadata": {
                "test_name": "vLLM Intent-Driven Function Calling Test (64k context)",
                "created_at": datetime.now().isoformat(),
                "output_constraint": {
                    "min_tokens": 2000,
                    "max_tokens": 2048,
                    "ignore_eos": True,
                },
                "api_endpoint": self.api_url,
                "tokenizer": "cl100k_base" if TOKENIZER_AVAILABLE else "estimated"
            },
            "request": {
                "model": None, # Will be auto-filled
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{long_text}{user_prompt}"}
                ],
                "tools": self.get_tool_definitions(),
                "tool_choice": "auto",
                "max_tokens": 2048,
                "min_tokens": 2000,
                "temperature": 0.3, # Lowered slightly for more deterministic tool extraction
                "top_p": 0.9,
                "ignore_eos": True
            },
            "statistics": {
                "actual_input_tokens": actual_tokens,
                "user_prompt_tokens": prompt_tokens,
                "system_prompt_tokens": system_tokens,
                "tools_tokens": tools_tokens,
                "total_input_tokens": total_input_tokens + system_tokens + tools_tokens,
            }
        }
        return test_input

    def run_test(self, use_existing_input: bool = False):
        """Execute the test and perform deep validation on the output."""
        print("=" * 60)
        print("vLLM Optimized Function Calling Test - Logic & Needle Verification")
        print("=" * 60)
        
        # 1. Server check
        try:
            models_resp = requests.get(self.models_url, timeout=5)
            model_id = models_resp.json()['data'][0]['id'] if models_resp.status_code == 200 else 'default'
        except:
            print("ERROR: vLLM server is not accessible.")
            return

        # 2. Input Prep
        if use_existing_input and os.path.exists(self.input_file):
            with open(self.input_file, 'r') as f:
                test_input = json.load(f)
        else:
            test_input = self.prepare_test_input()
            test_input['request']['model'] = model_id
            with open(self.input_file, 'w') as f:
                json.dump(test_input, f, indent=2)

        print(f"Targeting Model: {model_id}")
        print(f"Total Input Tokens (Approx): {test_input['statistics']['total_input_tokens']}")
        
        # 3. Execution
        print("\nSending request... (This may take a while for 64k context)")
        start_time = time.time()
        try:
            response = requests.post(self.api_url, json=test_input['request'], timeout=300)
            latency = time.time() - start_time
            result = response.json()
        except Exception as e:
            print(f"Request Failed: {e}")
            return
            
        with open(self.output_file, 'w') as f:
            json.dump(result, f, indent=2)

        # 4. Deep Analysis
        print("\n" + "=" * 60)
        print("TEST RESULTS & LOGIC VERIFICATION")
        print("=" * 60)
        print(f"Latency: {latency:.2f} seconds")
        
        choices = result.get('choices', [{}])[0]
        message = choices.get('message', {})
        usage = result.get('usage', {})
        
        # A. Physical Constraints
        print(f"\n[1] Physical Output Constraints:")
        print(f"  - Actual Completion Tokens: {usage.get('completion_tokens', 0)}")
        if usage.get('completion_tokens') >= 2000:
            print("  ✅ Status: PASS (Successfully forced long output)")
        else:
            print("  ❌ Status: FAIL (Did not reach min_tokens)")

        # B. Tool Calling Logic
        tool_calls = message.get('tool_calls', [])
        print(f"\n[2] Intent-Driven Tool Calling:")
        print(f"  - Tools Triggered: {len(tool_calls)}")
        
        calc_passed = False
        search_passed = False
        
        for tc in tool_calls:
            func = tc.get('function', {})
            name = func.get('name')
            args = func.get('arguments', '')
            print(f"  -> Called: {name}")
            print(f"     Args: {args[:150]}...")
            
            # Logic Verification
            if name == "calculator":
                # Check if it successfully extracted 8192 and 4.5 from Needle 1
                if "8192" in args and "4.5" in args:
                    calc_passed = True
            if name == "web_search":
                # Check if it searched for the specific trends from Needle 2
                if "Multi-Token" in args or "1F1B" in args or "2026" in args:
                    search_passed = True

        print(f"\n[3] Needle in a Haystack Verification:")
        if calc_passed:
            print("  ✅ Calculator Logic: PASS (Successfully extracted '8192' and '4.5' from context)")
        else:
            print("  ❌ Calculator Logic: FAIL (Model hallucinated or missed the specific numbers in the 64k text)")
            
        if search_passed:
            print("  ✅ Web Search Logic: PASS (Successfully formulated search query based on context facts)")
        else:
            print("  ❌ Web Search Logic: FAIL (Did not target the specific architecture trends)")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-base', default='http://localhost:8000')
    parser.add_argument('--use-existing', action='store_true')
    args = parser.parse_args()
    
    tester = VLLMFunctionTester(api_base=args.api_base)
    tester.run_test(use_existing_input=args.use_existing)
