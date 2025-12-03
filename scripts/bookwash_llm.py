#!/usr/bin/env python3
"""
BookWash LLM Integration

Three-pass architecture for content moderation:
  Pass A (--rate):     Rate whole chapters, set #RATING and #NEEDS_CLEANING
  Pass B (--identify): For flagged chapters, rate small chunks (2-3 paragraphs),
                       create #CHANGE blocks with empty #CLEANED for problematic content
  Pass C (--fill):     Fill in #CLEANED section for each #CHANGE block

Usage:
    # Rate all chapters (Pass A)
    python bookwash_llm.py --rate book.bookwash --api-key YOUR_KEY
    
    # Identify problematic paragraphs (Pass B)
    python bookwash_llm.py --identify book.bookwash --api-key YOUR_KEY
    
    # Fill in cleaned versions (Pass C)
    python bookwash_llm.py --fill book.bookwash --api-key YOUR_KEY
    
    # Full pipeline (all three passes with verification loop)
    python bookwash_llm.py --rate --identify --fill book.bookwash --api-key YOUR_KEY
    
    # Set target levels (default: language=2, sexual=2, violence=5)
    python bookwash_llm.py --rate book.bookwash --language 2 --sexual 2 --violence 3

Environment:
    GEMINI_API_KEY - API key (or use --api-key)
    GEMINI_MODEL - Model name (default: gemini-2.0-flash)
"""

import argparse
import functools
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Force unbuffered output for real-time logging
print = functools.partial(print, flush=True)

# Try to import requests, fall back to urllib
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False


# --- Constants ---

RATING_LEVELS = {
    'G': 1,
    'PG': 2,
    'PG-13': 3,
    'R': 4,
    'X': 5,
}

LEVEL_TO_RATING = {
    1: 'G',
    2: 'PG',
    3: 'PG-13',
    4: 'R',
    5: 'X',
}

DEFAULT_MODEL = 'gemini-2.0-flash'
FALLBACK_MODELS = [
    'gemini-1.5-flash',   # Fallback when 2.0 hits rate limit
    'gemini-2.0-flash',   # Retry 2.0 after 1.5 hits limit (ping-pong)
]
API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'


# --- Data Classes ---

@dataclass
class ChapterRating:
    """Content ratings for a chapter."""
    language: str = 'G'
    sexual: str = 'G'
    violence: str = 'G'
    
    def exceeds_target(self, target_language: int, target_sexual: int, target_violence: int) -> bool:
        """Check if any rating exceeds the target levels."""
        return (
            RATING_LEVELS.get(self.language, 1) > target_language or
            RATING_LEVELS.get(self.sexual, 1) > target_sexual or
            RATING_LEVELS.get(self.violence, 1) > target_violence
        )


@dataclass
class Chapter:
    """Represents a chapter in the bookwash file."""
    number: int
    title: Optional[str] = None
    rating: Optional[ChapterRating] = None
    needs_cleaning: Optional[bool] = None
    content_lines: list = field(default_factory=list)  # Raw lines including any existing changes
    
    def get_text_for_rating(self) -> str:
        """Get plain text content for rating (excludes change blocks, uses original text)."""
        lines = []
        in_change = False
        in_original = False
        in_cleaned = False
        
        for line in self.content_lines:
            if line.startswith('#CHANGE:'):
                in_change = True
                continue
            if line == '#END' and in_change:
                in_change = False
                in_original = False
                in_cleaned = False
                continue
            if in_change:
                if line == '#ORIGINAL':
                    in_original = True
                    in_cleaned = False
                    continue
                if line == '#CLEANED':
                    in_original = False
                    in_cleaned = True
                    continue
                if line.startswith('#STATUS:') or line.startswith('#REASON:'):
                    continue
                # Use original text for rating
                if in_original:
                    lines.append(line)
            else:
                # Regular content
                lines.append(line)
        
        return '\n'.join(lines)
    
    def get_text_with_cleaned(self) -> str:
        """Get text content with CLEANED versions substituted where available.
        
        For change blocks: uses CLEANED if non-empty, otherwise uses ORIGINAL.
        """
        lines = []
        in_change = False
        in_original = False
        in_cleaned = False
        original_lines = []
        cleaned_lines = []
        
        for line in self.content_lines:
            if line.startswith('#CHANGE:'):
                in_change = True
                original_lines = []
                cleaned_lines = []
                continue
            if line == '#END' and in_change:
                # Use cleaned content if available, otherwise use original
                has_cleaned = any(cl.strip() for cl in cleaned_lines)
                if has_cleaned:
                    lines.extend(cleaned_lines)
                else:
                    lines.extend(original_lines)
                in_change = False
                in_original = False
                in_cleaned = False
                continue
            if in_change:
                if line == '#ORIGINAL':
                    in_original = True
                    in_cleaned = False
                    continue
                if line == '#CLEANED':
                    in_original = False
                    in_cleaned = True
                    continue
                if line.startswith('#STATUS:') or line.startswith('#REASON:'):
                    continue
                if in_original:
                    original_lines.append(line)
                elif in_cleaned:
                    cleaned_lines.append(line)
            else:
                # Regular content
                lines.append(line)
        
        return '\n'.join(lines)
    
    def get_paragraphs_for_cleaning(self) -> list:
        """Get paragraphs that need cleaning (original text, no existing changes)."""
        text = self.get_text_for_rating()
        # Split on double newlines to get paragraphs
        paragraphs = re.split(r'\n\n+', text.strip())
        return [p.strip() for p in paragraphs if p.strip()]
    
    def get_paragraphs_with_cleaned(self) -> list:
        """Get paragraphs with CLEANED content substituted where available."""
        text = self.get_text_with_cleaned()
        paragraphs = re.split(r'\n\n+', text.strip())
        return [p.strip() for p in paragraphs if p.strip()]


@dataclass  
class BookWashFile:
    """Represents a parsed .bookwash file."""
    version: str = '1.0'
    source: str = ''
    created: str = ''
    modified: Optional[str] = None
    settings: dict = field(default_factory=dict)
    assets: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    header_lines: list = field(default_factory=list)  # Raw header lines before chapters
    chapters: list = field(default_factory=list)
    
    @property
    def target_language(self) -> int:
        return self.settings.get('target_language', 2)
    
    @property
    def target_sexual(self) -> int:
        return self.settings.get('target_sexual', 2)
    
    @property
    def target_violence(self) -> int:
        return self.settings.get('target_violence', 5)


# --- Parser ---

def parse_bookwash(filepath: Path) -> BookWashFile:
    """Parse a .bookwash file."""
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    bw = BookWashFile()
    current_chapter = None
    in_header = True
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Header parsing
        if in_header:
            if line.startswith('#BOOKWASH'):
                bw.version = line.split()[1] if len(line.split()) > 1 else '1.0'
                bw.header_lines.append(line)
            elif line.startswith('#SOURCE:'):
                bw.source = line[8:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#CREATED:'):
                bw.created = line[9:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#MODIFIED:'):
                bw.modified = line[10:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#SETTINGS:'):
                settings_str = line[10:].strip()
                for pair in settings_str.split():
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        try:
                            bw.settings[k] = int(v)
                        except ValueError:
                            bw.settings[k] = v
                bw.header_lines.append(line)
            elif line.startswith('#ASSETS:'):
                bw.assets = line[8:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#AUTHOR:'):
                bw.metadata['author'] = line[8:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#PUBLISHER:'):
                bw.metadata['publisher'] = line[11:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#PUBLISHED:'):
                bw.metadata['published'] = line[11:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#LANGUAGE:'):
                bw.metadata['language'] = line[10:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#IDENTIFIER:'):
                bw.metadata['identifier'] = line[12:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#DESCRIPTION:'):
                bw.metadata['description'] = line[13:].strip()
                bw.header_lines.append(line)
            elif line.startswith('#IMAGE:'):
                bw.header_lines.append(line)
            elif line.startswith('#CHAPTER:'):
                in_header = False
                # Fall through to chapter parsing
            else:
                bw.header_lines.append(line)
                i += 1
                continue
        
        # Chapter parsing
        if line.startswith('#CHAPTER:'):
            if current_chapter is not None:
                bw.chapters.append(current_chapter)
            
            num_str = line[9:].strip()
            current_chapter = Chapter(number=int(num_str))
        elif current_chapter is not None:
            if line.startswith('#TITLE:'):
                current_chapter.title = line[7:].strip()
            elif line.startswith('#RATING:'):
                # Parse: #RATING: language=PG sexual=G violence=PG-13
                rating = ChapterRating()
                rating_str = line[8:].strip()
                for pair in rating_str.split():
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        if k == 'language':
                            rating.language = v
                        elif k == 'sexual':
                            rating.sexual = v
                        elif k == 'violence':
                            rating.violence = v
                current_chapter.rating = rating
            elif line.startswith('#NEEDS_CLEANING:'):
                val = line[16:].strip().lower()
                current_chapter.needs_cleaning = val == 'true'
            else:
                current_chapter.content_lines.append(line)
        
        i += 1
    
    # Add last chapter
    if current_chapter is not None:
        bw.chapters.append(current_chapter)
    
    return bw


def write_bookwash(bw: BookWashFile, filepath: Path):
    """Write a .bookwash file."""
    lines = []
    
    # Write header
    for line in bw.header_lines:
        # Update MODIFIED timestamp
        if line.startswith('#MODIFIED:'):
            continue  # Skip old modified line
        # Update SETTINGS if present
        if line.startswith('#SETTINGS:'):
            continue  # We'll rewrite it
        lines.append(line)
    
    # Insert/update MODIFIED and SETTINGS after CREATED
    insert_idx = None
    for i, line in enumerate(lines):
        if line.startswith('#CREATED:'):
            insert_idx = i + 1
            break
    
    if insert_idx is not None:
        now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        lines.insert(insert_idx, f'#MODIFIED: {now}')
        
        if bw.settings:
            settings_parts = [f'{k}={v}' for k, v in bw.settings.items()]
            lines.insert(insert_idx + 1, f'#SETTINGS: {" ".join(settings_parts)}')
    
    # Ensure blank line before chapters
    while lines and lines[-1] == '':
        lines.pop()
    lines.append('')
    
    # Write chapters
    for chapter in bw.chapters:
        lines.append(f'#CHAPTER: {chapter.number}')
        
        if chapter.title:
            lines.append(f'#TITLE: {chapter.title}')
        
        if chapter.rating:
            lines.append(f'#RATING: language={chapter.rating.language} sexual={chapter.rating.sexual} violence={chapter.rating.violence}')
        
        if chapter.needs_cleaning is not None:
            lines.append(f'#NEEDS_CLEANING: {"true" if chapter.needs_cleaning else "false"}')
        
        # Write content
        for content_line in chapter.content_lines:
            lines.append(content_line)
    
    filepath.write_text('\n'.join(lines), encoding='utf-8')


# --- Gemini API ---

class GeminiClient:
    """Simple Gemini API client with model fallback."""
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.primary_model = model
        self.current_model = model
        self.fallback_index = 0
        self.last_request_time = 0
        self.min_request_interval = 1.2  # ~50 requests per minute
        self.consecutive_429s = 0
    
    def _switch_to_fallback(self):
        """Switch to next fallback model after rate limiting (cycles through list)."""
        if self.fallback_index < len(FALLBACK_MODELS):
            old_model = self.current_model
            self.current_model = FALLBACK_MODELS[self.fallback_index]
            self.fallback_index += 1
            print(f"  ⚡ Switching model: {old_model} → {self.current_model}")
            return True
        else:
            # Wrap around to start cycling again
            self.fallback_index = 0
            old_model = self.current_model
            self.current_model = FALLBACK_MODELS[0]
            self.fallback_index = 1
            print(f"  ⚡ Cycling model: {old_model} → {self.current_model}")
            return True
    
    def _reset_to_primary(self):
        """Reset to primary model."""
        if self.current_model != self.primary_model:
            self.current_model = self.primary_model
            self.fallback_index = 0
            self.consecutive_429s = 0
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _make_request(self, prompt: str, text: str, max_retries: int = 5) -> str:
        """Make a request to Gemini API with model fallback on 429."""
        
        for attempt in range(max_retries):
            url = API_URL.format(model=self.current_model) + f'?key={self.api_key}'
            
            payload = {
                'contents': [{
                    'parts': [{'text': f'{prompt}\n\n{text}'}]
                }],
                'generationConfig': {
                    'temperature': 0.1,
                    'topP': 0.9,
                    'maxOutputTokens': 8192,
                },
                'safetySettings': [
                    {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_NONE'},
                    {'category': 'HARM_CATEGORY_HATE_SPEECH', 'threshold': 'BLOCK_NONE'},
                    {'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT', 'threshold': 'BLOCK_NONE'},
                    {'category': 'HARM_CATEGORY_DANGEROUS_CONTENT', 'threshold': 'BLOCK_NONE'},
                ]
            }
            
            self._rate_limit()
            
            try:
                if HAS_REQUESTS:
                    response = requests.post(
                        url,
                        json=payload,
                        headers={'Content-Type': 'application/json'},
                        timeout=75
                    )
                    
                    if response.status_code == 429:
                        self.consecutive_429s += 1
                        # Try switching model after 2 consecutive 429s
                        if self.consecutive_429s >= 2:
                            if self._switch_to_fallback():
                                self.consecutive_429s = 0
                                continue
                        wait_time = min(2 ** (attempt + 1), 30)
                        print(f"  Rate limited, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    
                    self.consecutive_429s = 0  # Reset on success
                    response.raise_for_status()
                    data = response.json()
                else:
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode('utf-8'),
                        headers={'Content-Type': 'application/json'},
                        method='POST'
                    )
                    
                    try:
                        with urllib.request.urlopen(req, timeout=75) as resp:
                            data = json.loads(resp.read().decode('utf-8'))
                        self.consecutive_429s = 0
                    except urllib.error.HTTPError as e:
                        if e.code == 429:
                            self.consecutive_429s += 1
                            if self.consecutive_429s >= 2:
                                if self._switch_to_fallback():
                                    self.consecutive_429s = 0
                                    continue
                            wait_time = min(2 ** (attempt + 1), 30)
                            print(f"  Rate limited, waiting {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        elif e.code == 404:
                            # Model not found - try next fallback immediately
                            if self._switch_to_fallback():
                                continue
                            raise  # No more fallbacks
                        raise
                
                # Extract response text
                candidates = data.get('candidates', [])
                if candidates:
                    content = candidates[0].get('content', {})
                    parts = content.get('parts', [])
                    if parts:
                        return parts[0].get('text', '')
                
                return ''
                
            except Exception as e:
                # Check if it's a 404 wrapped in another exception
                err_str = str(e)
                if '404' in err_str:
                    if self._switch_to_fallback():
                        continue
                if attempt == max_retries - 1:
                    raise
                wait_time = min(2 ** (attempt + 1), 16)
                print(f"  Error: {e}, retrying in {wait_time}s...")
                time.sleep(wait_time)
        
        return ''
    
    def rate_chapter(self, text: str) -> ChapterRating:
        """Rate a chapter for content levels."""
        prompt = """Analyze the following text and rate it for content in three categories.
For each category, respond with ONLY one of: G, PG, PG-13, R, or X

Categories:
1. LANGUAGE (profanity, cursing)
   - G: No profanity or insults at all
   - PG: Only very mild exclamations (darn, gosh, gee, jeez, heck)
   - PG-13: Moderate profanity (damn, hell, crap, ass, bastard) but NO f-word or s-word
   - R: Strong profanity including f-word (fuck) or s-word (shit, bullshit)
   - X: Extreme sexual profanity or hate slurs

2. SEXUAL CONTENT (romantic, sexual, suggestive, revealing descriptions)
   - G: No romantic/sexual content, no body-focused descriptions
   - PG: Light romance (hand-holding, brief kiss), no suggestive body descriptions
   - PG-13: Passionate kissing, implied intimacy (fade-to-black), OR suggestive clothing/body descriptions (cleavage, tight/revealing clothes, bare skin emphasis, physical attractiveness focus)
   - R: Descriptive sexual scenes, sustained intimate detail, OR explicit body descriptions focusing on breasts, thighs, buttocks, or other sensual areas
   - X: Explicit sexual activity described graphically

   IMPORTANT: Rate as PG-13 or higher if the text:
   - Describes revealing or sexualized clothing (low-cut, tight, minimal coverage)
   - Focuses on body curves, skin, or physical attractiveness in a sensual way
   - Emphasizes breasts, cleavage, thighs, or other typically sexualized body parts
   - Uses words like "curve", "smooth skin", "bare", "exposed", "tight", "revealing"

3. VIOLENCE (fighting, gore, harm)
   - G: No physical violence (arguments only)
   - PG: Mild action, non-detailed scuffles, no blood
   - PG-13: Combat, injuries, some blood, weapon use without gore detail
   - R: Graphic injury detail, notable gore, intense sustained violence
   - X: Extreme gore/torture, sadistic detail

Respond in EXACTLY this format (one rating per line):
LANGUAGE: [rating]
SEXUAL: [rating]
VIOLENCE: [rating]

Text to analyze:"""
        
        response = self._make_request(prompt, text)
        
        rating = ChapterRating()
        for line in response.strip().split('\n'):
            line = line.strip()
            if line.startswith('LANGUAGE:'):
                val = line.replace('LANGUAGE:', '').strip().upper()
                if val in RATING_LEVELS:
                    rating.language = val
            elif line.startswith('SEXUAL:'):
                val = line.replace('SEXUAL:', '').strip().upper()
                if val in RATING_LEVELS:
                    rating.sexual = val
            elif line.startswith('VIOLENCE:'):
                val = line.replace('VIOLENCE:', '').strip().upper()
                if val in RATING_LEVELS:
                    rating.violence = val
        
        return rating
    
    def rate_chunk(self, paragraphs: list, target_lang: int, target_sexual: int, target_violence: int) -> list:
        """Rate a small chunk of paragraphs and identify which ones need cleaning.
        
        Args:
            paragraphs: List of paragraph strings (typically 2-3)
            target_lang: Target language level
            target_sexual: Target sexual content level  
            target_violence: Target violence level
            
        Returns:
            List of paragraph indices (0-based) that exceed target ratings
        """
        lang_name = LEVEL_TO_RATING.get(target_lang, 'PG')
        sexual_name = LEVEL_TO_RATING.get(target_sexual, 'PG')
        violence_name = LEVEL_TO_RATING.get(target_violence, 'X')
        
        # Number each paragraph for reference
        numbered = []
        for i, p in enumerate(paragraphs):
            numbered.append(f"[{i+1}] {p}")
        text = '\n\n'.join(numbered)
        
        prompt = f"""Analyze each numbered paragraph and identify which ones contain content that exceeds the target ratings.

RATING SCALE DEFINITIONS:

LANGUAGE (profanity, cursing):
- G: No profanity or insults at all
- PG: Only very mild exclamations (darn, gosh, gee, jeez, heck)
- PG-13: Moderate profanity (damn, hell, crap, ass, bastard) but NO f-word or s-word
- R: Strong profanity including f-word (fuck) or s-word (shit, bullshit, shitshow)
- X: Extreme sexual profanity or hate slurs

SEXUAL CONTENT:
- G: No romantic/sexual content, no body-focused descriptions
- PG: Light romance only: hand-holding, brief innocent kiss goodbye, friendly hug
- PG-13: ANY of the following makes it PG-13:
  * Passionate or sustained kissing
  * Implied intimacy (fade-to-black, "the door closed", "they spent the night")
  * Post-intimacy scenes ("tangled in sheets", "afterward they lay together", morning-after)
  * Physical arousal cues (racing hearts from attraction, flushed from desire)
  * Suggestive body descriptions (curves, cleavage, bare skin in romantic context)
- R: Descriptive sexual scenes, explicit body touching, nudity in intimate context
- X: Explicit sexual activity described graphically

⚠️ KEY PG-13 TRIGGERS (these are NOT PG):
- "tangled in sheets" or similar post-sex imagery → PG-13
- "hearts racing" in romantic context → PG-13
- "pulling closer" in bed → PG-13  
- Any implication that characters just had or will have sex → PG-13

VIOLENCE:
- G: No physical violence (arguments only)
- PG: Mild action, non-detailed scuffles, no blood
- PG-13: Combat, injuries, some blood, weapon use without gore detail
- R: Graphic injury detail, notable gore, intense sustained violence
- X: Extreme gore/torture, sadistic detail

TARGET RATINGS (content must be at or BELOW these levels):
- Language: {lang_name}
- Sexual: {sexual_name}
- Violence: {violence_name}

IMPORTANT: Words like "shit", "bullshit", "fuck", "fucking" are R-level!

For each paragraph that EXCEEDS any target rating, list its number.
If a paragraph is acceptable, do NOT list it.

Respond with ONLY the paragraph numbers that need cleaning (one per line), or "NONE" if all paragraphs are acceptable.

Example response:
1
3

Text to analyze:
"""
        
        response = self._make_request(prompt, text)
        
        # Parse response for paragraph numbers
        needs_cleaning = []
        for line in response.strip().split('\n'):
            line = line.strip()
            if line.upper() == 'NONE':
                return []
            # Extract number from line (handle formats like "1", "[1]", "1.", "Paragraph 1", etc.)
            match = re.search(r'\b(\d+)\b', line)
            if match:
                idx = int(match.group(1)) - 1  # Convert to 0-based
                if 0 <= idx < len(paragraphs):
                    needs_cleaning.append(idx)
        
        return needs_cleaning
    
    def clean_paragraph(self, paragraph: str, target_lang: int, target_sexual: int, target_violence: int,
                        aggression: int = 1) -> str:
        """Clean a single paragraph according to target levels.
        
        Args:
            paragraph: The paragraph text to clean
            target_lang: Target language level
            target_sexual: Target sexual content level
            target_violence: Target violence level
            aggression: Cleaning aggression level (1=normal, 2=aggressive, 3=very aggressive)
            
        Returns:
            The cleaned paragraph text
        """
        lang_name = LEVEL_TO_RATING.get(target_lang, 'PG')
        sexual_name = LEVEL_TO_RATING.get(target_sexual, 'PG')
        violence_name = LEVEL_TO_RATING.get(target_violence, 'X')
        
        # Detect if this is an R→PG drop (the hard case)
        # We'll add special creative strategies for this
        is_strict_adult = target_sexual <= 2  # G or PG
        is_strict_violence = target_violence <= 2  # G or PG
        
        # Build base instructions based on aggression
        if aggression >= 3:
            base_instructions = """MAXIMUM AGGRESSION: Be extremely aggressive. Remove entire sentences if needed.
Replace problematic content with minimal neutral text. When in doubt, DELETE rather than rephrase."""
        elif aggression >= 2:
            base_instructions = """AGGRESSIVE: Remove more content than usual. Don't try to preserve suggestive phrasing.
Summarize rather than rephrase problematic content."""
        else:
            base_instructions = """Clean minimally while preserving the narrative voice and emotional tone.
Rephrase or replace only what's necessary to meet target ratings."""
        
        # Add creative strategies for R→PG adult content
        adult_strategies = ""
        if is_strict_adult:
            adult_strategies = """
⚠️ ADULT CONTENT → PG RATING REQUIRED ⚠️

CRITICAL: PG is NOT the same as PG-13!
- PG-13 allows: passionate kissing, implied intimacy (fade-to-black), suggestive tension
- PG allows ONLY: hand-holding, brief innocent kiss, hugs - NO implication of anything more

WHAT MAKES PG-13 (which is TOO MUCH for PG):
❌ "They spent the night together" - implies sex
❌ "The door closed behind them" - implies what happens next
❌ "The next morning..." after a romantic scene - implies overnight intimacy
❌ Any mention of undressing, beds in romantic context, or physical urgency
❌ "Hearts racing" or physical reactions to attraction

WHAT IS ACTUALLY PG:
✅ "He kissed her goodnight and left"
✅ "They embraced warmly before parting"
✅ "She squeezed his hand, smiling"
✅ Scene ends with a simple kiss, then CUT to next day in a neutral context

STRATEGIES FOR EXPLICIT CONTENT → PG:
• COMPLETE REMOVAL: If a paragraph describes intimate activity, replace with:
  "They shared a tender moment together." (ONE SENTENCE - nothing more)
• NO IMPLICATION: Don't hint at what happened - just skip it entirely
• SKIP TO NEUTRAL: Jump to a completely non-romantic next scene
  "The next day, they met for coffee." (no reference to night before)
• REMOVE BODY LANGUAGE: Cut all physical attraction cues (racing hearts, flushed cheeks, etc.)

Example transformation:
BEFORE (R): "Clothing fell away piece by piece. His hands explored her curves. She gasped as..."
AFTER (PG): "They talked late into the evening, reluctant to say goodnight."
"""

        # Add creative strategies for R→PG violence
        violence_strategies = ""
        if is_strict_violence:
            violence_strategies = """
VIOLENCE → PG STRATEGIES (use these creative approaches):
• "OFF-SCREEN": Move graphic action off the page, show reactions.
  - Instead of gore: "He looked away, unable to watch." 
  - "The sounds told her everything she needed to know."
• "QUICK CUT": Summarize violence in one sanitized line.
  - "The fight was over in seconds. He stood alone."
  - "She defended herself. The attacker fled."
• "AFTERMATH FOCUS": Skip the violence, show the result.
  - "He nursed a bruised jaw afterward."
  - "The scuffle left them both breathing hard."
• Remove ALL: blood descriptions, injury details, gore, pain descriptions
• Replace: "blood sprayed" → "he fell"
• Replace: detailed combat → "they fought briefly"
• If the paragraph is mostly violent, compress to outcome without graphic detail.
"""

        prompt = f"""Clean this paragraph to meet the target content ratings.

TARGET RATINGS:
- Language: {lang_name} (max profanity level)
- Sexual: {sexual_name} (max suggestive content level)  
- Violence: {violence_name} (max violence level)

INSTRUCTIONS:
{base_instructions}
{adult_strategies}{violence_strategies}
RULES:
1. Return ONLY the cleaned paragraph - no explanations
2. Never use [...] or ellipses to indicate removed content
3. Keep the paragraph readable and coherent
4. The cleaned version should flow naturally - readers shouldn't notice edits
5. Preserve character names and basic plot points

Paragraph to clean:
"""
        
        result = self._make_request(prompt, paragraph)
        return result.strip()
    
    def clean_text(self, text: str, target_language: int, target_sexual: int, target_violence: int,
                   aggression: int = 1) -> str:
        """Clean text according to target levels.
        
        Args:
            text: The text to clean
            target_language: Target language level (1-5)
            target_sexual: Target sexual content level (1-5)
            target_violence: Target violence level (1-5)
            aggression: Cleaning aggression level (1=normal, 2=aggressive, 3=very aggressive)
        """
        prompt = self._build_cleaning_prompt(target_language, target_sexual, target_violence, aggression)
        return self._make_request(prompt, text)
    
    def _build_cleaning_prompt(self, lang: int, sexual: int, violence: int, aggression: int = 1) -> str:
        """Build the filtering prompt based on target levels and aggression."""
        lang_name = LEVEL_TO_RATING.get(lang, 'PG')
        sexual_name = LEVEL_TO_RATING.get(sexual, 'PG')
        violence_name = LEVEL_TO_RATING.get(violence, 'Unrated')
        
        # Aggression header based on level
        if aggression >= 3:
            aggression_header = """
⚠️ MAXIMUM AGGRESSION MODE ⚠️
Previous cleaning passes FAILED to meet the target rating. You MUST be EXTREMELY aggressive:
- REMOVE entire sentences or paragraphs if they contain ANY inappropriate content
- Do NOT try to preserve suggestive scenes - DELETE them entirely
- Replace romantic/sexual scenes with simple summary: "They spent time together."
- If a paragraph is mostly inappropriate, replace with ONE neutral sentence
- When in doubt, REMOVE rather than rephrase
- The goal is a CLEAN rating, not preserving the story details

"""
        elif aggression >= 2:
            aggression_header = """
⚠️ AGGRESSIVE MODE ⚠️
The first cleaning pass did not achieve the target rating. Be MORE aggressive:
- Remove MORE content than you normally would
- Don't try to preserve suggestive phrasing - cut it entirely
- Summarize intimate scenes with vague phrases ("later that evening")
- Remove body-focused descriptions completely
- When uncertain, remove rather than rephrase

"""
        else:
            aggression_header = ""
        
        prompt = f"""{aggression_header}You are a content filter for books. Clean the following text by removing or rephrasing inappropriate content.

CRITICAL RULES:
1. Return ONLY the cleaned text - no explanations, no metadata
2. NEVER use [...] or ellipses for removed content
3. Preserve paragraph structure EXACTLY - same number of paragraphs
4. Keep formatting, punctuation, and quotation marks intact
5. CHAPTER TITLES: The first line may be a chapter title. If it contains profanity, CLEAN it but keep it as a short title (not a paragraph). Example: "The S**t Show" → "The Disaster\""""
        
        # Adjust rules based on aggression for strict targets (G/PG)
        if aggression >= 2 and (lang <= 2 or sexual <= 2):
            prompt += """
6. For G/PG targets: AGGRESSIVELY remove suggestive content - do not try to preserve it
7. Replace problematic paragraphs with simple neutral summaries
8. Remove all body-focused language, physical descriptions of attraction
9. Cut rather than rephrase when content is borderline"""
        else:
            prompt += """
6. Use minimal replacements - prefer simple phrases over creative elaboration
7. DO NOT add new plot elements or details not in the original
8. Preserve emotional tone and narrative voice"""
        
        prompt += f"""

TARGET LEVELS:
- Language: {lang_name} (Level {lang})
- Sexual: {sexual_name} (Level {sexual})
- Violence: {violence_name} (Level {violence})

LANGUAGE FILTERING (Target: {lang_name}):"""
        
        if lang == 1:  # G
            prompt += """
- Remove ALL profanity and insults
- Replace with neutral emotional descriptors ("upset", "frustrated")"""
        elif lang == 2:  # PG
            prompt += """
- ALLOWED: darn, gosh, gee, jeez, heck, shoot
- REMOVE: damn, hell, crap, shit, ass, bitch, bastard, fuck, and all stronger"""
        elif lang == 3:  # PG-13
            prompt += """
- ALLOWED: damn, hell, crap, ass, bastard, bitch (moderate profanity)
- REMOVE: fuck, fucking, shit (f-word variants and strongest profanity)"""
        elif lang == 4:  # R
            prompt += """
- KEEP almost everything - only remove extreme NC-17 content"""
        else:  # Unrated
            prompt += """
- NO FILTERING - keep all language as-is"""
        
        prompt += f"""

SEXUAL CONTENT FILTERING (Target: {sexual_name}):"""
        
        if sexual == 1:  # G
            if aggression >= 2:
                prompt += """
- AGGRESSIVELY remove ALL romantic content - even hints of attraction
- Replace entire romantic scenes with: "They talked for a while."
- Remove: dancing together, body contact, longing looks, attraction descriptions
- No physical descriptions of characters that could be seen as attractive
- Remove ALL descriptions of revealing clothing, body curves, exposed skin
- Convert intimate settings to neutral: "They met at the venue." """
            else:
                prompt += """
- Remove all romantic/suggestive content
- Remove all descriptions of revealing clothing or body-focused descriptions
- Keep only platonic relationships"""
        elif sexual == 2:  # PG
            if aggression >= 2:
                prompt += """
- AGGRESSIVELY cut sensual content - be strict about what stays
- ALLOWED ONLY: Quick peck on cheek, holding hands briefly, friendly hug
- REMOVE ENTIRELY: lap dances, grinding, straddling, pressing bodies together
- REMOVE: "breath hot", "lips close to ear", "body pressed against", "hips moving"
- REMOVE: descriptions of arousal, desire, physical attraction to body parts
- REMOVE: intimate whispers, seductive behavior, lingering touches
- REMOVE: revealing clothing descriptions (cleavage, bare skin, tight clothes focusing on body)
- REMOVE: emphasis on breasts, thighs, buttocks, curves, smooth skin in sensual context
- Replace removed content with simple neutral summary: "They spent time together."
- When in doubt about whether something is PG, REMOVE IT"""
            else:
                prompt += """
- ALLOWED: Hand-holding, brief kiss, hugs, warm affection
- REMOVE: Passionate kissing, body focus, arousal, implied intimacy
- REMOVE: Suggestive clothing descriptions (revealing outfits, emphasis on exposed skin)
- REMOVE: Body-focused descriptions emphasizing curves, breasts, thighs, or physical attractiveness in a sensual way
- Rewrite clothing descriptions to be neutral (just mention the type of clothing without sensual focus)"""
        elif sexual == 3:  # PG-13
            prompt += """
- ALLOWED: Passionate kissing, implied intimacy (fade-to-black), sensual tension
- ALLOWED: Brief mentions of attractive appearance or clothing
- REMOVE: Explicit acts, anatomical detail, graphic descriptions
- REMOVE: Extended focus on revealing clothing or body parts in a sexual context"""
        elif sexual == 4:  # R
            prompt += """
- KEEP almost everything - only remove NC-17/pornographic content"""
        else:  # Unrated
            prompt += """
- NO FILTERING - keep all sexual content as-is"""
        
        prompt += f"""

VIOLENCE FILTERING (Target: {violence_name}):"""
        
        if violence == 1:  # G
            prompt += """
- Remove all physical violence, weapons, injury mentions
- Keep only verbal conflicts"""
        elif violence == 2:  # PG
            prompt += """
- ALLOWED: Mild scuffles, shoving, non-graphic action
- REMOVE: Blood, injury detail, weapon focus"""
        elif violence == 3:  # PG-13
            prompt += """
- ALLOWED: Combat, blood mentions, injuries, weapon use
- REMOVE: Graphic gore, visible organs/bones, extreme torture"""
        elif violence == 4:  # R
            prompt += """
- KEEP almost everything - only remove torture-porn or extreme snuff"""
        else:  # Unrated
            prompt += """
- NO FILTERING - keep all violence as-is"""
        
        prompt += """

Now filter the following text according to these rules. Return ONLY the cleaned text:

"""
        return prompt


# --- Helper Functions ---

def _infer_reason(paragraph: str, target_lang: int, target_sexual: int, target_violence: int) -> str:
    """Infer why a paragraph needs cleaning based on content."""
    para_lower = paragraph.lower()
    
    # Check for profanity
    strong_profanity = ['fuck', 'fucking', 'fucked', 'shit', 'bullshit', 'shitty']
    moderate_profanity = ['damn', 'hell', 'crap', 'ass', 'bitch', 'bastard', 'asshole']
    
    for word in strong_profanity:
        if word in para_lower:
            return f'language=R exceeds target={LEVEL_TO_RATING[target_lang]}'
    
    for word in moderate_profanity:
        if word in para_lower:
            return f'language=PG-13 exceeds target={LEVEL_TO_RATING[target_lang]}'
    
    # Check for violence indicators FIRST (before sexual, to avoid "bodies" false positive)
    violence_words = ['blood', 'wound', 'kill', 'killed', 'stab', 'stabbed', 'slash', 
                      'gore', 'death', 'dead', 'corpse', 'bodies', 'body bag', 'murder',
                      'shot', 'shooting', 'bullet', 'gunshot', 'knife', 'blade']
    for word in violence_words:
        if word in para_lower:
            return f'violence exceeds target={LEVEL_TO_RATING[target_violence]}'
    
    # Check for sexual content indicators (but NOT "body" alone - too many false positives)
    sexual_words = ['kiss', 'kissed', 'kissing', 'touch', 'touched', 'caress', 'caressed',
                    'embrace', 'embraced', 'passion', 'passionate', 'desire', 
                    'chest', 'breast', 'breasts', 'thigh', 'thighs', 'curves', 
                    'lips', 'sensual', 'naked', 'nude', 'undress', 'intimate']
    for word in sexual_words:
        if word in para_lower:
            return f'sexual content exceeds target={LEVEL_TO_RATING[target_sexual]}'
    
    return 'content exceeds target rating'


def _get_unfilled_changes(chapter) -> list:
    """Get list of change IDs that have empty #CLEANED sections."""
    unfilled = []
    current_change_id = None
    in_cleaned = False
    cleaned_content = []
    
    for line in chapter.content_lines:
        if line.startswith('#CHANGE:'):
            # Save previous change if it had empty cleaned
            if current_change_id and in_cleaned and not any(c.strip() for c in cleaned_content):
                unfilled.append(current_change_id)
            # Start new change
            current_change_id = line.split(':')[1].strip()
            in_cleaned = False
            cleaned_content = []
        elif line == '#CLEANED':
            in_cleaned = True
            cleaned_content = []
        elif line == '#END':
            # Check if this change had empty cleaned
            if current_change_id and in_cleaned and not any(c.strip() for c in cleaned_content):
                unfilled.append(current_change_id)
            current_change_id = None
            in_cleaned = False
            cleaned_content = []
        elif in_cleaned:
            cleaned_content.append(line)
    
    return unfilled


def _get_change_original(chapter, change_id: str) -> str:
    """Get the #ORIGINAL content for a specific change ID."""
    in_target_change = False
    in_original = False
    original_lines = []
    
    for line in chapter.content_lines:
        if line.startswith('#CHANGE:'):
            cid = line.split(':')[1].strip()
            in_target_change = (cid == change_id)
            in_original = False
        elif line == '#ORIGINAL' and in_target_change:
            in_original = True
            original_lines = []
        elif line == '#CLEANED' and in_target_change:
            in_original = False
        elif line == '#END':
            if in_target_change:
                break
            in_target_change = False
        elif in_original:
            original_lines.append(line)
    
    return '\n'.join(original_lines)


def _set_change_cleaned(chapter, change_id: str, cleaned_text: str):
    """Set the #CLEANED content for a specific change ID."""
    new_lines = []
    in_target_change = False
    in_cleaned = False
    skip_until_end = False
    
    for line in chapter.content_lines:
        if line.startswith('#CHANGE:'):
            cid = line.split(':')[1].strip()
            in_target_change = (cid == change_id)
            new_lines.append(line)
        elif line == '#CLEANED' and in_target_change:
            new_lines.append(line)
            # Add the cleaned content
            new_lines.append(cleaned_text)
            in_cleaned = True
            skip_until_end = True
        elif line == '#END':
            new_lines.append(line)
            in_target_change = False
            in_cleaned = False
            skip_until_end = False
        elif skip_until_end and in_cleaned:
            # Skip old cleaned content
            continue
        else:
            new_lines.append(line)
    
    chapter.content_lines = new_lines


# --- Main Commands ---

def cmd_rate(bw: BookWashFile, client: GeminiClient, 
             target_lang: int, target_sexual: int, target_violence: int,
             verbose: bool = False) -> int:
    """Pass A: Rate all chapters, set #RATING and #NEEDS_CLEANING flags."""
    print(f"=== PASS A: Rating {len(bw.chapters)} chapters ===")
    print(f"Target levels: language={target_lang} ({LEVEL_TO_RATING[target_lang]}), "
          f"adult={target_sexual} ({LEVEL_TO_RATING[target_sexual]}), "
          f"violence={target_violence} ({LEVEL_TO_RATING[target_violence]})")
    print()
    
    # Update settings in file
    bw.settings['target_language'] = target_lang
    bw.settings['target_sexual'] = target_sexual
    bw.settings['target_violence'] = target_violence
    
    needs_cleaning_count = 0
    
    for i, chapter in enumerate(bw.chapters):
        title_str = f" ({chapter.title})" if chapter.title else ""
        print(f"[{i+1}/{len(bw.chapters)}] Chapter {chapter.number}{title_str}...")
        
        # Get text for rating
        text = chapter.get_text_for_rating()
        if not text.strip():
            print("  (empty chapter, skipping)")
            chapter.rating = ChapterRating()
            chapter.needs_cleaning = False
            continue
        
        # Truncate very long chapters for rating (first ~10k chars should be representative)
        if len(text) > 10000:
            text = text[:10000] + "\n\n[truncated for rating]"
        
        try:
            rating = client.rate_chapter(text)
            chapter.rating = rating
            
            needs_clean = rating.exceeds_target(target_lang, target_sexual, target_violence)
            chapter.needs_cleaning = needs_clean
            
            if needs_clean:
                needs_cleaning_count += 1
            
            status = "NEEDS CLEANING" if needs_clean else "OK"
            print(f"  Rating: L={rating.language} A={rating.sexual} V={rating.violence} -> {status}")
            
        except Exception as e:
            print(f"  Error rating chapter: {e}")
            chapter.rating = ChapterRating()
            chapter.needs_cleaning = False
    
    print()
    print(f"Rating complete: {needs_cleaning_count}/{len(bw.chapters)} chapters need cleaning")
    
    return needs_cleaning_count


def cmd_identify(bw: BookWashFile, client: GeminiClient, verbose: bool = False,
                  chunk_size: int = 3) -> int:
    """Pass B: For flagged chapters, identify problematic paragraphs and create #CHANGE blocks."""
    chapters_to_process = [ch for ch in bw.chapters if ch.needs_cleaning]
    
    if not chapters_to_process:
        print("=== PASS B: No chapters need identification ===")
        return 0
    
    print(f"=== PASS B: Identifying content in {len(chapters_to_process)} chapters ===")
    target_lang = bw.target_language
    target_sexual = bw.target_sexual
    target_violence = bw.target_violence
    print(f"Target levels: language={target_lang} ({LEVEL_TO_RATING[target_lang]}), "
          f"adult={target_sexual} ({LEVEL_TO_RATING[target_sexual]}), "
          f"violence={target_violence} ({LEVEL_TO_RATING[target_violence]})")
    print(f"Chunk size: {chunk_size} paragraphs")
    print()
    
    total_changes = 0
    global_change_id = 1
    
    for i, chapter in enumerate(chapters_to_process):
        title_str = f" ({chapter.title})" if chapter.title else ""
        print(f"[{i+1}/{len(chapters_to_process)}] Chapter {chapter.number}{title_str}...")
        
        # Get paragraphs for analysis
        paragraphs = chapter.get_paragraphs_for_cleaning()
        if not paragraphs:
            print("  (empty chapter, skipping)")
            continue
        
        # Process in chunks
        flagged_indices = set()
        chunk_count = (len(paragraphs) + chunk_size - 1) // chunk_size
        
        for chunk_idx in range(chunk_count):
            start = chunk_idx * chunk_size
            end = min(start + chunk_size, len(paragraphs))
            chunk = paragraphs[start:end]
            
            if verbose:
                print(f"  Checking paragraphs {start+1}-{end}...")
            
            try:
                needs_cleaning = client.rate_chunk(chunk, target_lang, target_sexual, target_violence)
                # Convert chunk-relative indices to absolute indices
                for idx in needs_cleaning:
                    flagged_indices.add(start + idx)
            except Exception as e:
                print(f"  Error rating chunk: {e}")
                continue
        
        if not flagged_indices:
            print(f"  No problematic paragraphs found")
            chapter.needs_cleaning = False
            continue
        
        print(f"  Found {len(flagged_indices)} paragraphs needing cleaning")
        
        # Build new content with #CHANGE blocks
        new_content = []
        chapter_changes = 0
        
        for idx, para in enumerate(paragraphs):
            if idx in flagged_indices:
                # Create change block with empty CLEANED
                new_content.append('')
                new_content.append(f'#CHANGE: c{global_change_id:03d}')
                new_content.append('#STATUS: pending')
                reason = _infer_reason(para, target_lang, target_sexual, target_violence)
                new_content.append(f'#REASON: {reason}')
                new_content.append('#ORIGINAL')
                new_content.append(para)
                new_content.append('#CLEANED')
                new_content.append('')  # Empty - to be filled in Pass C
                new_content.append('#END')
                global_change_id += 1
                chapter_changes += 1
            else:
                # Keep paragraph as-is
                new_content.append('')
                new_content.append(para)
        
        chapter.content_lines = new_content
        total_changes += chapter_changes
        print(f"  Created {chapter_changes} change blocks")
    
    print()
    print(f"Identification complete: {total_changes} change blocks created")
    
    return total_changes


def cmd_fill(bw: BookWashFile, client: GeminiClient, verbose: bool = False,
             aggression: int = 1) -> int:
    """Pass C: Fill in #CLEANED sections for all #CHANGE blocks with empty cleaned content."""
    target_lang = bw.target_language
    target_sexual = bw.target_sexual
    target_violence = bw.target_violence
    
    print(f"=== PASS C: Filling change blocks ===")
    print(f"Target levels: language={target_lang} ({LEVEL_TO_RATING[target_lang]}), "
          f"adult={target_sexual} ({LEVEL_TO_RATING[target_sexual]}), "
          f"violence={target_violence} ({LEVEL_TO_RATING[target_violence]})")
    agg_str = {1: "normal", 2: "aggressive", 3: "VERY aggressive"}.get(aggression, "normal")
    print(f"Aggression: {agg_str}")
    print()
    
    total_filled = 0
    
    for i, chapter in enumerate(bw.chapters):
        unfilled = _get_unfilled_changes(chapter)
        if not unfilled:
            continue
        
        title_str = f" ({chapter.title})" if chapter.title else ""
        print(f"[Chapter {chapter.number}{title_str}] Filling {len(unfilled)} changes...")
        
        for change_id in unfilled:
            original = _get_change_original(chapter, change_id)
            if not original.strip():
                continue
            
            if verbose:
                print(f"  {change_id}: cleaning {len(original)} chars...")
            
            try:
                cleaned = client.clean_paragraph(original, target_lang, target_sexual, target_violence, aggression)
                _set_change_cleaned(chapter, change_id, cleaned)
                total_filled += 1
            except Exception as e:
                print(f"  Error cleaning {change_id}: {e}")
                continue
        
        print(f"  Filled {len(unfilled)} change blocks")
    
    print()
    print(f"Fill complete: {total_filled} changes filled")
    
    return total_filled


def cmd_clean(bw: BookWashFile, client: GeminiClient, verbose: bool = False,
               max_iterations: int = 3, verify: bool = True) -> int:
    """Full cleaning pipeline: identify + fill + verify loop.
    
    This runs:
    1. Pass B (identify) - create change blocks for problematic paragraphs
    2. Pass C (fill) - fill in cleaned versions
    3. Re-rate chapter, repeat with increased aggression if still exceeds target
    """
    chapters_to_clean = [ch for ch in bw.chapters if ch.needs_cleaning]
    
    if not chapters_to_clean:
        print("No chapters need cleaning.")
        return 0
    
    target_lang = bw.target_language
    target_sexual = bw.target_sexual
    target_violence = bw.target_violence
    
    print(f"=== CLEANING PIPELINE: {len(chapters_to_clean)} chapters ===")
    print(f"Target levels: language={target_lang} ({LEVEL_TO_RATING[target_lang]}), "
          f"adult={target_sexual} ({LEVEL_TO_RATING[target_sexual]}), "
          f"violence={target_violence} ({LEVEL_TO_RATING[target_violence]})")
    if verify:
        print(f"Verification enabled (max {max_iterations} iterations)")
    print()
    
    total_changes = 0
    verified_count = 0
    
    for i, chapter in enumerate(chapters_to_clean):
        title_str = f" ({chapter.title})" if chapter.title else ""
        print(f"[{i+1}/{len(chapters_to_clean)}] Chapter {chapter.number}{title_str}")
        
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            
            # Calculate aggression based on iteration
            is_strict_target = target_lang <= 2 or target_sexual <= 2
            if iteration == 1:
                aggression = 1
            elif iteration == 2:
                aggression = 2 if is_strict_target else 1
            else:
                aggression = 3 if is_strict_target else 2
            
            agg_str = {1: "", 2: " [aggressive]", 3: " [VERY aggressive]"}.get(aggression, "")
            print(f"  Pass {iteration}{agg_str}:")
            
            if iteration == 1:
                # First pass: identify problematic paragraphs from ORIGINAL
                paragraphs = chapter.get_paragraphs_for_cleaning()
                if not paragraphs:
                    print("    (empty chapter)")
                    break
                
                # Rate chunks to find problematic paragraphs
                flagged_indices = set()
                chunk_size = 3
                
                for chunk_idx in range((len(paragraphs) + chunk_size - 1) // chunk_size):
                    start = chunk_idx * chunk_size
                    end = min(start + chunk_size, len(paragraphs))
                    chunk = paragraphs[start:end]
                    
                    try:
                        needs_cleaning = client.rate_chunk(chunk, target_lang, target_sexual, target_violence)
                        for idx in needs_cleaning:
                            flagged_indices.add(start + idx)
                    except Exception as e:
                        if verbose:
                            print(f"    Error rating chunk: {e}")
                        continue
                
                if not flagged_indices:
                    print(f"    ✓ No problematic paragraphs found")
                    chapter.needs_cleaning = False
                    verified_count += 1
                    break
                
                print(f"    Found {len(flagged_indices)} paragraphs to clean")
                
                # First pass: create new change blocks
                new_content = []
                global_change_id = total_changes + 1
                
                for idx, para in enumerate(paragraphs):
                    if idx in flagged_indices:
                        new_content.append('')
                        new_content.append(f'#CHANGE: c{global_change_id:03d}')
                        new_content.append('#STATUS: pending')
                        reason = _infer_reason(para, target_lang, target_sexual, target_violence)
                        new_content.append(f'#REASON: {reason}')
                        new_content.append('#ORIGINAL')
                        new_content.append(para)
                        new_content.append('#CLEANED')
                        
                        # Clean the paragraph immediately
                        try:
                            cleaned = client.clean_paragraph(para, target_lang, target_sexual, target_violence, aggression)
                            new_content.append(cleaned)
                        except Exception as e:
                            print(f"    Error cleaning: {e}")
                            new_content.append('')
                        
                        new_content.append('#END')
                        global_change_id += 1
                        total_changes += 1
                    else:
                        new_content.append('')
                        new_content.append(para)
                
                chapter.content_lines = new_content
            else:
                # Subsequent passes: 
                # 1. Re-clean existing change blocks more aggressively
                # 2. ALSO check for NEW paragraphs that now exceed target
                
                print(f"    Re-cleaning existing change blocks...")
                change_count = 0
                for line in chapter.content_lines:
                    if line.startswith('#CHANGE:'):
                        change_id = line.split(':')[1].strip()
                        original = _get_change_original(chapter, change_id)
                        if original.strip():
                            try:
                                cleaned = client.clean_paragraph(original, target_lang, target_sexual, target_violence, aggression)
                                _set_change_cleaned(chapter, change_id, cleaned)
                                change_count += 1
                            except Exception as e:
                                if verbose:
                                    print(f"    Error re-cleaning {change_id}: {e}")
                print(f"    Re-cleaned {change_count} change blocks")
                
                # ALSO: Check for paragraphs that weren't flagged initially but still exceed target
                # This catches cases where paragraph 4 is PG-13 but target is PG
                paragraphs = chapter.get_paragraphs_with_cleaned()  # Get current state with cleaned versions
                if paragraphs:
                    # Find which paragraphs are NOT already in change blocks
                    existing_originals = set()
                    in_change = False
                    in_original = False
                    current_original = []
                    for line in chapter.content_lines:
                        if line.startswith('#CHANGE:'):
                            in_change = True
                            current_original = []
                        elif line == '#END' and in_change:
                            if current_original:
                                existing_originals.add('\n'.join(current_original).strip())
                            in_change = False
                            in_original = False
                        elif line == '#ORIGINAL' and in_change:
                            in_original = True
                        elif line == '#CLEANED' and in_change:
                            in_original = False
                        elif in_original:
                            current_original.append(line)
                    
                    # Rate any paragraphs not in change blocks
                    uncleaned_paragraphs = []
                    uncleaned_indices = []
                    for idx, para in enumerate(paragraphs):
                        # Check if this paragraph text matches any original in a change block
                        if para.strip() not in existing_originals:
                            uncleaned_paragraphs.append(para)
                            uncleaned_indices.append(idx)
                    
                    if uncleaned_paragraphs:
                        # Rate these to see if any exceed target
                        new_flagged = []
                        chunk_size = 3
                        for chunk_idx in range((len(uncleaned_paragraphs) + chunk_size - 1) // chunk_size):
                            start = chunk_idx * chunk_size
                            end = min(start + chunk_size, len(uncleaned_paragraphs))
                            chunk = uncleaned_paragraphs[start:end]
                            
                            try:
                                needs_cleaning = client.rate_chunk(chunk, target_lang, target_sexual, target_violence)
                                for idx in needs_cleaning:
                                    new_flagged.append(uncleaned_indices[start + idx])
                            except Exception as e:
                                if verbose:
                                    print(f"    Error rating additional chunk: {e}")
                        
                        if new_flagged:
                            print(f"    Found {len(new_flagged)} additional paragraphs to clean")
                            # Create new change blocks for these
                            global_change_id = total_changes + 1
                            new_content = []
                            para_idx = 0
                            i = 0
                            while i < len(chapter.content_lines):
                                line = chapter.content_lines[i]
                                if line.startswith('#CHANGE:'):
                                    # Copy entire change block
                                    while i < len(chapter.content_lines):
                                        new_content.append(chapter.content_lines[i])
                                        if chapter.content_lines[i] == '#END':
                                            i += 1
                                            break
                                        i += 1
                                    para_idx += 1
                                elif line.strip() and not line.startswith('#'):
                                    # Regular paragraph
                                    if para_idx in new_flagged:
                                        para = line
                                        new_content.append('')
                                        new_content.append(f'#CHANGE: c{global_change_id:03d}')
                                        new_content.append('#STATUS: pending')
                                        reason = _infer_reason(para, target_lang, target_sexual, target_violence)
                                        new_content.append(f'#REASON: {reason}')
                                        new_content.append('#ORIGINAL')
                                        new_content.append(para)
                                        new_content.append('#CLEANED')
                                        try:
                                            cleaned = client.clean_paragraph(para, target_lang, target_sexual, target_violence, aggression)
                                            new_content.append(cleaned)
                                        except Exception as e:
                                            print(f"    Error cleaning new para: {e}")
                                            new_content.append('')
                                        new_content.append('#END')
                                        global_change_id += 1
                                        total_changes += 1
                                    else:
                                        new_content.append(line)
                                    para_idx += 1
                                    i += 1
                                else:
                                    new_content.append(line)
                                    i += 1
                            chapter.content_lines = new_content
                print(f"    Re-cleaned {change_count} change blocks")
            
            if not verify:
                break
            
            # Verify: re-rate the chapter using cleaned content
            print(f"    Verifying...")
            
            # Get text with cleaned versions applied (not original)
            text = chapter.get_text_with_cleaned()
            if len(text) > 10000:
                text = text[:10000]
            
            try:
                rating = client.rate_chapter(text)
                still_exceeds = rating.exceeds_target(target_lang, target_sexual, target_violence)
                
                print(f"    Post-clean rating: L={rating.language} A={rating.sexual} V={rating.violence}")
                
                if not still_exceeds:
                    print(f"    ✓ Meets target after {iteration} pass(es)")
                    chapter.needs_cleaning = False
                    chapter.rating = rating
                    verified_count += 1
                    break
                else:
                    if iteration < max_iterations:
                        print(f"    ✗ Still exceeds target, trying again...")
                    else:
                        print(f"    ✗ Max iterations reached")
                        chapter.needs_cleaning = False  # Avoid infinite loops
            except Exception as e:
                print(f"    Error verifying: {e}")
                break
        
        print()
    
    print(f"Cleaning complete: {total_changes} total changes made")
    if verify:
        print(f"Verification: {verified_count}/{len(chapters_to_clean)} chapters meet target rating")
    
    return total_changes


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description='BookWash LLM Integration - Three-pass content moderation with verification',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Rate all chapters (Pass A)
    python bookwash_llm.py --rate book.bookwash --api-key YOUR_KEY
    
    # Identify problematic paragraphs (Pass B)
    python bookwash_llm.py --identify book.bookwash --api-key YOUR_KEY
    
    # Fill cleaned versions (Pass C)
    python bookwash_llm.py --fill book.bookwash --api-key YOUR_KEY
    
    # Full pipeline with verification (all passes)
    python bookwash_llm.py --rate --clean book.bookwash --api-key YOUR_KEY
    
    # Run passes separately
    python bookwash_llm.py --rate --identify --fill book.bookwash --api-key YOUR_KEY
    
    # Custom target levels
    python bookwash_llm.py --rate --clean book.bookwash --language 2 --sexual 2 --violence 3
        """
    )
    
    parser.add_argument('input', help='Input .bookwash file')
    parser.add_argument('--rate', action='store_true', help='Pass A: Rate all chapters')
    parser.add_argument('--identify', action='store_true', help='Pass B: Identify problematic paragraphs, create #CHANGE blocks')
    parser.add_argument('--fill', action='store_true', help='Pass C: Fill in #CLEANED sections for change blocks')
    parser.add_argument('--clean', action='store_true', help='Full cleaning pipeline (identify + fill + verify loop)')
    parser.add_argument('--api-key', help='Gemini API key (or set GEMINI_API_KEY)')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'Gemini model (default: {DEFAULT_MODEL})')
    parser.add_argument('--language', type=int, default=2, choices=[1,2,3,4,5],
                       help='Target language level: 1=G, 2=PG, 3=PG-13, 4=R, 5=Unrated (default: 2)')
    parser.add_argument('--sexual', type=int, default=2, choices=[1,2,3,4,5],
                       help='Target sexual content level (default: 2)')
    parser.add_argument('--violence', type=int, default=5, choices=[1,2,3,4,5],
                       help='Target violence level (default: 5/Unrated)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--dry-run', action='store_true', help='Parse and validate without API calls')
    parser.add_argument('--no-verify', action='store_true', 
                       help='Skip verification (do not re-rate after cleaning)')
    parser.add_argument('--max-iterations', type=int, default=3,
                       help='Max cleaning iterations per chapter (default: 3)')
    parser.add_argument('--chunk-size', type=int, default=3,
                       help='Paragraphs per chunk for identification (default: 3)')
    parser.add_argument('--aggression', type=int, default=1, choices=[1,2,3],
                       help='Cleaning aggression level: 1=normal, 2=aggressive, 3=very aggressive')
    
    args = parser.parse_args()
    
    # Validate input
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return 1
    
    if not args.rate and not args.identify and not args.fill and not args.clean:
        print("Error: Must specify at least one of --rate, --identify, --fill, or --clean")
        return 1
    
    # Get API key
    api_key = args.api_key or os.environ.get('GEMINI_API_KEY', '')
    if not api_key and not args.dry_run:
        print("Error: API key required. Set GEMINI_API_KEY or use --api-key")
        return 1
    
    # Parse bookwash file
    print(f"Loading: {input_path.name}")
    bw = parse_bookwash(input_path)
    print(f"  Source: {bw.source}")
    print(f"  Chapters: {len(bw.chapters)}")
    print()
    
    if args.dry_run:
        print("Dry run mode - no API calls will be made")
        for ch in bw.chapters:
            title = f" ({ch.title})" if ch.title else ""
            rating_str = f" L={ch.rating.language} S={ch.rating.sexual} V={ch.rating.violence}" if ch.rating else ""
            needs = f" NEEDS_CLEANING" if ch.needs_cleaning else ""
            print(f"  Chapter {ch.number}{title}{rating_str}{needs}")
        return 0
    
    # Create client
    client = GeminiClient(api_key, args.model)
    
    # Run passes
    if args.rate:
        cmd_rate(bw, client, args.language, args.sexual, args.violence, args.verbose)
        print()
    
    if args.identify:
        cmd_identify(bw, client, args.verbose, chunk_size=args.chunk_size)
        print()
    
    if args.fill:
        cmd_fill(bw, client, args.verbose, aggression=args.aggression)
        print()
    
    if args.clean:
        cmd_clean(bw, client, args.verbose, 
                  max_iterations=args.max_iterations,
                  verify=not args.no_verify)
        print()
    
    # Write updated file
    print(f"Saving: {input_path.name}")
    write_bookwash(bw, input_path)
    print("Done!")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
