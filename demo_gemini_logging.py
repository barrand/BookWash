#!/usr/bin/env python3
"""
Simple demonstration script to show Gemini instruction logging.

This script demonstrates what logging output you'll see when the BookWash
system processes text through Gemini with different configurations.
"""

import sys
sys.path.insert(0, '.')
from scripts.bookwash_llm import GeminiClient, LEVEL_TO_RATING

def demo_logging():
    """Demonstrate the logging output."""
    
    print("\n" + "="*80)
    print("GEMINI INSTRUCTION LOGGING DEMONSTRATION")
    print("="*80 + "\n")
    
    # Example 1: Language-only filtering
    print("EXAMPLE 1: Language-Only Filtering")
    print("-" * 80)
    client = GeminiClient('fake_key', language_words=['damn', 'hell', 'shit', 'fuck'])
    
    paragraph = "What the hell? This is damn nonsense! She wanted to shit or get off the pot."
    print(f"\n🧹 CLEANING PARAGRAPH - Parameters:")
    print(f"   Target Sexual: G (level 1)")
    print(f"   Target Violence: G (level 1)")
    print(f"   Language Words: {client.language_words}")
    print(f"   Aggression: 1")
    print(f"   Paragraph: {paragraph[:100]}...")
    
    # Build and show the prompt that would be sent
    prompt = client._build_cleaning_prompt(sexual=1, violence=1, aggression=1, 
                                           filter_types='language')
    print(f"\n📋 GEMINI REQUEST LOG - Full Instructions Being Sent")
    print("="*80)
    print("\n--- SYSTEM PROMPT (Instructions to AI) ---\n")
    print(prompt[:1500] + "\n... (truncated for demo)")
    print("\n--- INPUT TEXT (Content to Process) ---\n")
    print(paragraph)
    print("\n" + "="*80)
    
    # Example 2: Mixed filtering
    print("\n\nEXAMPLE 2: Mixed Filtering (Language + Sexual + Violence)")
    print("-" * 80)
    client = GeminiClient('fake_key', language_words=['fuck', 'shit'])
    
    paragraph = "He fucked up the deal. She was angry and wanted to hit him, nearly naked with rage."
    print(f"\n🧹 CLEANING PARAGRAPH - Parameters:")
    print(f"   Target Sexual: PG (level 2)")
    print(f"   Target Violence: PG-13 (level 3)")
    print(f"   Language Words: {client.language_words}")
    print(f"   Aggression: 2 (AGGRESSIVE MODE)")
    print(f"   Paragraph: {paragraph[:100]}...")
    
    prompt = client._build_cleaning_prompt(sexual=2, violence=3, aggression=2,
                                          filter_types='language,sexual,violence')
    print(f"\n📋 GEMINI REQUEST LOG - Full Instructions Being Sent")
    print("="*80)
    print("\n--- SYSTEM PROMPT (Instructions to AI) ---\n")
    print(prompt[:2000] + "\n... (truncated for demo)")
    print("\n--- INPUT TEXT (Content to Process) ---\n")
    print(paragraph)
    print("\n" + "="*80)
    
    # Example 3: No language filtering
    print("\n\nEXAMPLE 3: Sexual and Violence Only (No Language Filtering)")
    print("-" * 80)
    client = GeminiClient('fake_key', language_words=[])
    
    paragraph = "They kissed passionately. Blood dripped from his wound."
    print(f"\n🧹 CLEANING PARAGRAPH - Parameters:")
    print(f"   Target Sexual: PG (level 2)")
    print(f"   Target Violence: PG-13 (level 3)")
    print(f"   Language Words: (none selected)")
    print(f"   Aggression: 1")
    print(f"   Paragraph: {paragraph[:100]}...")
    
    prompt = client._build_cleaning_prompt(sexual=2, violence=3, aggression=1,
                                          filter_types='sexual,violence')
    print(f"\n📋 GEMINI REQUEST LOG - Full Instructions Being Sent")
    print("="*80)
    print("\n--- SYSTEM PROMPT (Instructions to AI) ---\n")
    print(prompt[:2000] + "\n... (truncated for demo)")
    print("\n--- INPUT TEXT (Content to Process) ---\n")
    print(paragraph)
    print("\n" + "="*80)
    
    print("\n\n✅ LOGGING DEMONSTRATION COMPLETE")
    print("\nKey observations from the above examples:")
    print("1. Cleaning parameters show EXACTLY what's being filtered")
    print("2. SYSTEM PROMPT shows the instructions sent to Gemini")
    print("3. Only relevant sections appear (language only if language filtering)")
    print("4. INPUT TEXT shows the paragraph being processed")
    print("\nSee GEMINI_LOGGING_GUIDE.md for full documentation on auditing logs.")

if __name__ == '__main__':
    demo_logging()
