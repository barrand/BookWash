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
import asyncio
import functools
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

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

DEFAULT_MODEL = 'gemini-2.5-flash-lite'
FALLBACK_MODELS = [
    'gemini-2.0-flash-lite',   # Fallback when 2.5 hits rate limit
    'gemini-2.5-flash-lite',   # Retry 2.5 after 2.0 hits limit (ping-pong)
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
        """Check if any rating exceeds the target levels.
        
        DEPRECATED: Use exceeds_target_content() instead. This method is kept for backward compatibility
        but language level checking is no longer used (filtering is checkbox-based).
        """
        return (
            RATING_LEVELS.get(self.sexual, 1) > target_sexual or
            RATING_LEVELS.get(self.violence, 1) > target_violence
        )
    
    def exceeds_target_content(self, target_sexual: int, target_violence: int) -> bool:
        """Check if adult/violence ratings exceed targets (language is no longer level-based)."""
        return (
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
            # Defensive check: ensure line is a string
            if not isinstance(line, str):
                print(f"ERROR: Found non-string in content_lines: {type(line)} = {line}")
                continue
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
    cleaning_prompt: Optional[str] = None  # The Gemini cleaning prompt for analysis
    assets: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    header_lines: list = field(default_factory=list)  # Raw header lines before chapters
    chapters: list = field(default_factory=list)
    
    @property
    def target_language(self) -> int:
        """DEPRECATED: Language filtering is no longer level-based.
        
        Returns the old target_language setting if it exists (for backward compatibility),
        but this is no longer used for filtering. Use language_words instead.
        """
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
        
        offset = 1
        if bw.settings:
            settings_parts = [f'{k}={v}' for k, v in bw.settings.items()]
            lines.insert(insert_idx + offset, f'#SETTINGS: {" ".join(settings_parts)}')
            offset += 1
        
        # Write cleaning prompt if available (for analysis)
        if bw.cleaning_prompt:
            lines.insert(insert_idx + offset, '#CLEANING_PROMPT_START')
            offset += 1
            # Split prompt into lines and add each with # prefix
            prompt_lines = bw.cleaning_prompt.split('\n')
            for prompt_line in prompt_lines:
                lines.insert(insert_idx + offset, f'# {prompt_line}')
                offset += 1
            lines.insert(insert_idx + offset, '#CLEANING_PROMPT_END')
            offset += 1
    
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
    
    # Atomic write: write to temp file, then rename
    temp_path = filepath.with_suffix('.tmp')
    temp_path.write_text('\n'.join(lines), encoding='utf-8')
    temp_path.rename(filepath)


def write_chapter_bookwash(chapter: Chapter, filepath: Path, settings: dict = None):
    """Write a single chapter to a per-chapter .bookwash file."""
    lines = []
    
    # Write minimal settings if provided
    if settings:
        lines.append('#SETTINGS')
        for key, value in settings.items():
            lines.append(f'{key}={value}')
        lines.append('')
    
    # Write chapter
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
    
    # Atomic write
    temp_path = filepath.with_suffix('.tmp')
    temp_path.write_text('\n'.join(lines), encoding='utf-8')
    temp_path.rename(filepath)


def parse_chapter_bookwash(filepath: Path) -> Chapter:
    """Parse a single-chapter .bookwash file."""
    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    chapter = None
    in_settings = False
    
    for line in lines:
        if line.startswith('#SETTINGS'):
            in_settings = True
            continue
        
        if in_settings:
            if line.strip() == '':
                in_settings = False
            continue
        
        if line.startswith('#CHAPTER:'):
            chapter_num = int(line.split(':')[1].strip())
            chapter = Chapter(number=chapter_num)
            continue
        
        if chapter is None:
            continue
        
        if line.startswith('#TITLE:'):
            chapter.title = line.split(':', 1)[1].strip()
        elif line.startswith('#RATING:'):
            rating_str = line.split(':', 1)[1].strip()
            parts = {}
            for part in rating_str.split():
                key, val = part.split('=')
                parts[key] = val
            chapter.rating = ChapterRating(
                language=parts.get('language', 'G'),
                sexual=parts.get('sexual', 'G'),
                violence=parts.get('violence', 'G')
            )
        elif line.startswith('#NEEDS_CLEANING:'):
            val = line.split(':')[1].strip().lower()
            chapter.needs_cleaning = (val == 'true')
        else:
            chapter.content_lines.append(line)
    
    return chapter


def merge_chapter_files(session_dir: Path, master_path: Path, settings: dict):
    """Merge per-chapter .bookwash files back into master file."""
    chapter_files = sorted(session_dir.glob('ch_*.bookwash'))
    
    if not chapter_files:
        return
    
    bw = BookWashFile()
    bw.settings = settings.copy()
    
    for ch_file in chapter_files:
        try:
            chapter = parse_chapter_bookwash(ch_file)
            bw.chapters.append(chapter)
        except Exception as e:
            print(f"⚠️  Error loading {ch_file.name}: {e}")
    
    # Ensure chapters are in order by chapter number (important for multi-worker processing)
    bw.chapters.sort(key=lambda ch: ch.number)
    
    write_bookwash(bw, master_path)


# --- Gemini API ---

class GeminiClient:
    """Simple Gemini API client with model fallback."""
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, language_words: list = None, filter_types: str = 'language,sexual,violence'):
        self.api_key = api_key
        self.primary_model = model
        self.current_model = model
        self.fallback_index = 0
        self.last_request_time = 0
        self.min_request_interval = 1.2  # ~50 requests per minute
        self.consecutive_429s = 0
        self.language_words = language_words or []  # List of specific words to filter
        self.filter_types = filter_types  # Which content types to filter
        # Prompt caching to avoid rebuilding identical prompts
        self._cached_cleaning_prompt = None
        self._cached_cleaning_params = None
    
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
    
    def _log_gemini_instructions(self, prompt: str, text: str, log_type: str = 'unknown') -> None:
        """Minimal logging for Gemini requests.
        
        Verbose logging disabled to keep UI clean and avoid showing offensive content.
        """
        # Logging disabled for cleaner UI
        pass
    
    def _make_request(self, prompt: str, text: str, max_retries: int = 5, log_type: str = 'unknown') -> str:
        """Make a request to Gemini API with model fallback on 429.
        
        Args:
            prompt: System prompt/instructions
            text: Content to process
            max_retries: Maximum retry attempts
            log_type: Type of operation ('rating', 'cleaning', 'unknown') for logging
        """
        
        # Log the instructions being sent (only for cleaning operations)
        self._log_gemini_instructions(prompt, text, log_type)
        
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
                    # Check if the candidate was blocked
                    finish_reason = candidates[0].get('finishReason', '')
                    if finish_reason == 'SAFETY':
                        safety_ratings = candidates[0].get('safetyRatings', [])
                        blocked_categories = [r.get('category', 'UNKNOWN') for r in safety_ratings if r.get('blocked', False)]
                        print(f"  ⚠️  Content blocked by safety filter: {blocked_categories}")
                        # Return a marker so we know it was blocked
                        return '[BLOCKED_BY_SAFETY_FILTER]'
                    
                    content = candidates[0].get('content', {})
                    parts = content.get('parts', [])
                    if parts:
                        return parts[0].get('text', '')
                else:
                    # No candidates at all - check promptFeedback for blocking
                    prompt_feedback = data.get('promptFeedback', {})
                    block_reason = prompt_feedback.get('blockReason', '')
                    if block_reason:
                        print(f"  ⚠️  Prompt blocked: {block_reason}")
                        safety_ratings = prompt_feedback.get('safetyRatings', [])
                        for rating in safety_ratings:
                            if rating.get('probability', '') in ['HIGH', 'MEDIUM']:
                                print(f"      - {rating.get('category', 'UNKNOWN')}: {rating.get('probability', 'UNKNOWN')}")
                        return '[BLOCKED_BY_SAFETY_FILTER]'
                
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
        
        response = self._make_request(prompt, text, log_type='rating')
        
        # If content was blocked by safety filter, assume it's X-rated
        if response == '[BLOCKED_BY_SAFETY_FILTER]':
            print("  ⚠️  Rating blocked - assuming X/X/X (explicit content)")
            return ChapterRating(language='X', sexual='X', violence='X')
        
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

LANGUAGE CONTENT DETECTION:
Rate the overall language content to help the user understand what's in this text.
⚠️ NOTE: This rating is for CONTENT DISCOVERY only. During cleaning, the system will 
remove only the specific words the user selected (not everything at this rating level).

- G: No profanity or crude language
- PG: Only mild exclamations (darn, gosh, gee, jeez, heck)
- PG-13: Moderate profanity (damn, hell, crap, ass, bastard, bitch) - NO f-word or s-word
- R: Strong profanity including f-word (fuck) or s-word (shit, bullshit)
- X: Extreme profanity, c-word, or hate slurs

Common words to watch for:
- Mild: darn, gosh, heck, gee, jeez
- Moderate: damn, hell, crap, ass, bastard, bitch, asshole  
- Strong: shit, fuck, motherfucker, bullshit

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
        
        response = self._make_request(prompt, text, log_type='rating')
        
        # If content was blocked, assume ALL paragraphs need cleaning
        if response == '[BLOCKED_BY_SAFETY_FILTER]':
            print(f"    ⚠️  Chunk rating blocked - flagging all {len(paragraphs)} paragraphs")
            return list(range(len(paragraphs)))
        
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
    
    def clean_paragraph(self, paragraph: str, target_sexual: int, target_violence: int,
                        aggression: int = 1, strategy: str = 'rephrase') -> tuple[str, str]:
        """Clean a single paragraph according to target levels and strategy.
        
        Note: Language filtering is now checkbox-based (via self.language_words), not level-based.
        
        Args:
            paragraph: The paragraph text to clean
            target_sexual: Target sexual content level
            target_violence: Target violence level
            aggression: Cleaning aggression level (1=normal, 2=aggressive, 3=very aggressive)
            strategy: Cleaning strategy ('rephrase', 'summarize', 'fade_to_black')
            
        Returns:
            Tuple of (cleaned paragraph text, prompt used for cleaning)
        """
        # Create cache key for prompt reuse (include strategy)
        cache_key = (target_sexual, target_violence, aggression, tuple(self.language_words), self.filter_types, strategy)
        
        # Check if we can reuse cached prompt
        if self._cached_cleaning_params == cache_key:
            prompt = self._cached_cleaning_prompt
        else:
            # Build new prompt using the comprehensive method that includes all filtering instructions
            prompt = self._build_cleaning_prompt(target_sexual, target_violence, aggression, self.filter_types, strategy)
            
            # Cache the prompt for reuse
            self._cached_cleaning_prompt = prompt
            self._cached_cleaning_params = cache_key
        
        result = self._make_request(prompt, paragraph, log_type='cleaning')
        return result.strip(), prompt
    
    def clean_text(self, text: str, target_sexual: int, target_violence: int,
                   aggression: int = 1) -> str:
        """Clean text according to target levels.
        
        Note: Language filtering is now checkbox-based (via self.language_words), not level-based.
        
        Args:
            text: The text to clean
            target_sexual: Target sexual content level (1-5)
            target_violence: Target violence level (1-5)
            aggression: Cleaning aggression level (1=normal, 2=aggressive, 3=very aggressive)
        """
        prompt = self._build_cleaning_prompt(target_sexual, target_violence, aggression, self.filter_types)
        return self._make_request(prompt, text)
    
    def _build_cleaning_prompt(self, sexual: int, violence: int, aggression: int = 1, filter_types: str = 'sexual,violence', strategy: str = 'rephrase') -> str:
        """Build the filtering prompt based on target levels, aggression, and strategy.
        
        Note: Language filtering is now checkbox-based (via self.language_words), not level-based.
        
        Args:
            filter_types: Comma-separated list of content types being filtered (e.g., 'sexual,violence')
            strategy: Cleaning strategy ('rephrase', 'summarize', 'fade_to_black')
        """
        sexual_name = LEVEL_TO_RATING.get(sexual, 'PG')
        violence_name = LEVEL_TO_RATING.get(violence, 'Unrated')
        
        # Parse filter types
        filters_enabled = {ft.strip() for ft in filter_types.split(',')}
        is_language_only = 'language' in filters_enabled and len(filters_enabled) == 1
        
        # Aggression header based on level - only mention content types being filtered
        aggression_header = ""
        if aggression >= 3:
            # Build a smart aggressive header that only references filtered content types
            if is_language_only:
                aggression_header = """
⚠️ MAXIMUM AGGRESSION MODE (Language Only) ⚠️
Previous cleaning passes FAILED to meet the target language rating. You MUST be EXTREMELY aggressive with language:
- REMOVE entire sentences or phrases if they contain the specified inappropriate words
- Do NOT try to preserve dialogue with profanity - REMOVE or REPLACE it entirely
- Replace with appropriate alternatives from the target language level
- If a paragraph is mostly inappropriate profanity, replace with ONE neutral sentence
- When in doubt, REMOVE rather than rephrase
- The goal is to reach the target language rating

"""
            else:
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
            if is_language_only:
                aggression_header = """
⚠️ AGGRESSIVE MODE (Language Only) ⚠️
The first cleaning pass did not achieve the target language rating. Be MORE aggressive:
- Remove MORE instances of the specified inappropriate words
- Be strict about removing all variations and context uses
- When uncertain about whether a word should be removed, REMOVE it
- Replace removed words with neutral/appropriate alternatives

"""
            else:
                aggression_header = """
⚠️ AGGRESSIVE MODE ⚠️
The first cleaning pass did not achieve the target rating. Be MORE aggressive:
- Remove MORE content than you normally would
- Don't try to preserve suggestive phrasing - cut it entirely
- Summarize intimate scenes with vague phrases ("later that evening")
- Remove body-focused descriptions completely
- When uncertain, remove rather than rephrase

"""
        # Add strategy-specific instructions
        strategy_instructions = ""
        if strategy == 'summarize':
            strategy_instructions = """
📝 STRATEGY: SUMMARIZE
This is a SUMMARIZATION pass. The previous attempt to rephrase did not work.
- Replace detailed scenes with brief, factual summaries
- Example: Instead of detailed intimate interaction → "They became intimate."
- Example: Instead of extended violence → "A fight ensued."
- Keep it SHORT - one sentence is usually enough
- Focus on plot outcomes, not the details of how it happened

"""
        elif strategy == 'fade_to_black':
            strategy_instructions = """
⏭️ STRATEGY: FADE TO BLACK
This is a SCENE SKIP pass. Previous attempts to clean this content failed.
- Use time transitions to skip over problematic scenes entirely
- Example: "Later that evening..." or "The next morning..." or "After some time..."
- Remove the entire problematic section and replace with a brief transition
- Do NOT describe what happened during the skipped time
- Keep the story moving forward without showing inappropriate content

"""
        
        prompt = f"""{aggression_header}{strategy_instructions}You are a content filter for books. Clean the following text by removing or rephrasing inappropriate content.

CRITICAL RULES:
1. Return ONLY the cleaned text - no explanations, no metadata
2. NEVER use [...] or ellipses for removed content
3. Preserve paragraph structure EXACTLY - same number of paragraphs
4. Keep formatting, punctuation, and quotation marks intact
5. CHAPTER TITLES: The first line may be a chapter title. If it contains profanity, CLEAN it but keep it as a short title (not a paragraph). Example: "The S**t Show" → "The Disaster\"
6. DO NOT simplify vocabulary - keep sophisticated words (onerous, nascent, snarled, etc). Only remove inappropriate CONTENT, not complex language.
7. Narrative descriptions of profanity are ALLOWED at all language levels:
   ✅ KEEP: "He snarled a curse" (describes action, doesn't show word)
   ✅ KEEP: "She muttered an oath" (narrative description)
   ✅ KEEP: "A string of profanity" (tells, doesn't show)
   ❌ REMOVE: "He shouted, 'Damn you!'" (shows actual profanity)
   This is storytelling technique, not actual profanity usage.
8. If the paragraph already meets target levels, return it EXACTLY as-is. Do NOT make unnecessary changes to vocabulary, structure, or wording."""
        
        # Adjust rules based on aggression for strict targets (only for the content types being filtered)
        if aggression >= 2:
            if 'sexual' in filters_enabled and sexual <= 2:
                prompt += """
9. For G/PG sexual targets: AGGRESSIVELY remove suggestive content - do not try to preserve it
10. Replace problematic paragraphs with simple neutral summaries
11. Remove all body-focused language, physical descriptions of attraction
12. Cut rather than rephrase when content is borderline"""
            else:
                prompt += """
9. Use minimal replacements - prefer simple phrases over creative elaboration
10. DO NOT add new plot elements or details not in the original
11. Preserve emotional tone and narrative voice"""
        else:
            prompt += """
9. Use minimal replacements - prefer simple phrases over creative elaboration
10. DO NOT add new plot elements or details not in the original
11. Preserve emotional tone and narrative voice"""
        
        prompt += f"""

TARGET LEVELS:
- Sexual: {sexual_name} (Level {sexual})
- Violence: {violence_name} (Level {violence})
- Language: Checked against word list (see below)

LANGUAGE FILTERING:"""
        
        # Only include language filtering section if language is being filtered
        if 'language' in filters_enabled:
            # Use explicit word list for language filtering (checkbox-based)
            if self.language_words:
                prompt += f"""
⚠️ LANGUAGE FILTERING - EXPLICIT WORD REMOVAL ⚠️

TARGET WORDS TO REMOVE: {', '.join(self.language_words)}

CRITICAL INSTRUCTIONS:
1. REMOVE all instances of the target words above, regardless of context
2. REMOVE all variants and forms of these words when used as profanity or insults:
   - Verb forms: "damn" → "damned", "damnation"
   - Adjective forms: "fuck" → "fucking", "fucked"  
   - Compound words: "motherfucker", "goddamn", "bullshit"
   - Censored versions: "f*ck", "sh*t", "d*mn", "a**hole"
3. REMOVE similar profanity at the SAME or HIGHER severity level using this hierarchy:

   SEVERITY LEVELS (lowest to highest):
   
   MILD: darn, gosh, heck, gee, jeez
   ↓
   MODERATE: damn, hell, crap, ass, piss, bummer
   ↓
   STRONG: shit, bitch, bastard, asshole, bullshit
   ↓
   SEVERE: fuck, motherfucker, cunt
   ↓
   BLASPHEMOUS: goddamn, jesus christ (used as expletive), oh my god (used as expletive)
   
   FILTERING RULES BY SEVERITY:
   
   • If ANY MILD words are in target list (darn, gosh, heck):
     → Also remove: All other MILD words at same level
   
   • If ANY MODERATE words are in target list (damn, hell, crap, ass, piss):
     → Also remove: All MODERATE + all MILD words
     → Examples: "damn" triggers removal of "hell", "crap", "ass", "piss", "darn", "heck", "gosh"
   
   • If ANY STRONG words are in target list (shit, bitch, bastard, asshole):
     → Also remove: All STRONG + all MODERATE + all MILD words
     → Examples: "shit" triggers removal of "bitch", "bastard", "asshole", "damn", "hell", "crap", "ass", "darn", "heck"
   
   • If ANY SEVERE words are in target list (fuck, motherfucker, cunt):
     → Also remove: ALL profanity at ALL levels (SEVERE + STRONG + MODERATE + MILD)
     → This is the most aggressive filtering - removes every profane word
   
   • If ANY BLASPHEMOUS words are in target list (goddamn, jesus christ, oh my god):
     → Remove all blasphemous uses of religious terms as expletives
     → Keep genuine religious usage in context (prayer, worship, reverent discussion)
   
4. REPLACE with appropriate alternatives based on context:
   - Mild expletives: → "darn", "heck", "gosh"
   - Moderate cursing: → "blast", "dang", "crud"
   - Strong emotion: → rephrase to show emotion ("he shouted angrily")
   - Descriptive terms: → use neutral equivalents ("jerk" instead of "asshole")

KEEP all other words not in the removal list or similar severity.

CONTEXT-AWARE FILTERING:
- Narrative descriptions like "he cursed" or "snarled a curse" should be KEPT (they describe action without showing the word)
- Only remove when the actual profane word is shown in dialogue or narration
- Consider usage context: emphasis vs. actual cursing
- Religious phrases used genuinely (prayer, worship) may be kept, but blasphemous usage must be removed

EXAMPLES:
❌ "What the hell is going on?" → ✅ "What is going on?"
❌ "This is bullshit!" → ✅ "This is ridiculous!"
❌ "He's a real bastard." → ✅ "He's a real jerk."
❌ "Fuck this!" → ✅ "Forget this!"
❌ "That goddamn idiot..." → ✅ "That foolish person..."""
            else:
                # Fallback if no word list provided (shouldn't happen with new system)
                prompt += """
- Filtering based on provided word list only
- If no word list specified, no language filtering will occur"""
        else:
            prompt += """
- NO LANGUAGE FILTERING (not in filter types)"""
        
        # Only include sexual filtering section if sexual content is being filtered
        if 'sexual' in filters_enabled:
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
        
        # Only include violence filtering section if violence is being filtered
        if 'violence' in filters_enabled:
            prompt += f"""

VIOLENCE FILTERING (Target: {violence_name}):"""
            
            if violence == 1:  # G
                if aggression >= 2:
                    prompt += """
- AGGRESSIVELY remove ALL physical violence, weapons, and conflict descriptions
- Remove even mentions of violent actions or weapons
- Keep only dialogue and emotional content"""
                else:
                    prompt += """
- Remove all physical violence, weapons, injury mentions
- Keep only verbal conflicts"""
            elif violence == 2:  # PG
                if aggression >= 2:
                    prompt += """
- AGGRESSIVELY restrict to absolute minimum action
- ALLOWED ONLY: Very brief, non-graphic scuffles (one-line max)
- REMOVE: Blood, injury descriptions, weapon use, any combat focus
- REMOVE: Consequences of violence (bruises, pain descriptions)"""
                else:
                    prompt += """
- ALLOWED: Mild scuffles, shoving, non-graphic action
- REMOVE: Blood, injury detail, weapon focus"""
            elif violence == 3:  # PG-13
                # At PG-13, there's limited room for escalation
                # Normal and aggressive are similar
                prompt += """
- ALLOWED: Combat, blood mentions, injuries, weapon use
- REMOVE: Graphic gore, visible organs/bones, extreme torture
- (Aggression: may remove more detailed descriptions if needed)"""
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

def _infer_reason(paragraph: str, target_sexual: int, target_violence: int) -> str:
    """Infer why a paragraph needs cleaning based on content.
    
    Note: Language filtering is checkbox-based (language_words list), not level-based,
    so language checking is done by presence of words, not threshold comparison.
    This function only checks sexual and violence content against numeric thresholds.
    """
    para_lower = paragraph.lower()
    
    # Estimate violence level based on keywords present
    violence_level = 1  # Default G
    extreme_violence = ['dismembered', 'eviscerated', 'guts', 'severed', 'torture', 'entrails']
    graphic_violence = ['blood', 'wound', 'stabbed', 'sliced', 'gore', 'bleeding', 'slaughter', 'corpse', 'shot', 'gunshot']
    moderate_violence = ['kill', 'killed', 'fight', 'punch', 'struck', 'blade', 'knife', 'weapon', 'death', 'dead', 'murder']
    
    if any(word in para_lower for word in extreme_violence):
        violence_level = 4  # R
    elif any(word in para_lower for word in graphic_violence):
        violence_level = 3  # PG-13
    elif any(word in para_lower for word in moderate_violence):
        violence_level = 2  # PG
    
    # Only flag if exceeds target
    if violence_level > target_violence:
        return f'violence={LEVEL_TO_RATING[violence_level]} exceeds target={LEVEL_TO_RATING[target_violence]}'
    
    # Estimate sexual content level
    sexual_level = 1  # Default G
    explicit_sexual = ['sex', 'naked', 'nude', 'breast', 'breasts', 'nipple', 'groin', 'aroused', 'orgasm', 'erection']
    moderate_sexual = ['kiss', 'kissed', 'kissing', 'caress', 'caressed', 'intimate', 'curves', 'thigh', 'thighs', 'bare', 'touch', 'touched']
    mild_romantic = ['embrace', 'embraced', 'hug', 'held hands']
    
    if any(word in para_lower for word in explicit_sexual):
        sexual_level = 4  # R
    elif any(word in para_lower for word in moderate_sexual):
        sexual_level = 3  # PG-13
    elif any(word in para_lower for word in mild_romantic):
        sexual_level = 2  # PG
    
    # Only flag if exceeds target
    if sexual_level > target_sexual:
        return f'sexual content={LEVEL_TO_RATING[sexual_level]} exceeds target={LEVEL_TO_RATING[target_sexual]}'
    
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
        elif line in ['#CLEANED', '#PROMPT'] and in_target_change:
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
             target_sexual: int, target_violence: int,
             verbose: bool = False) -> int:
    """Pass A: Rate all chapters, set #RATING and #NEEDS_CLEANING flags.
    
    Note: Language filtering is now checkbox-based (specific words) instead of level-based.
    """
    print(f"=== PASS A: Rating {len(bw.chapters)} chapters ===")
    print(f"Target levels: adult={LEVEL_TO_RATING[target_sexual]}, "
          f"violence={LEVEL_TO_RATING[target_violence]}")
    print()
    
    # Update settings in file (language no longer has a target level)
    bw.settings['target_sexual'] = target_sexual
    bw.settings['target_violence'] = target_violence
    
    # Store the cleaning prompt for analysis (only store once)
    # Use strategy='summarize' and aggression=2 to show more complete instructions
    if not bw.cleaning_prompt and hasattr(client, '_cached_cleaning_prompt'):
        # Trigger prompt generation by calling clean_paragraph with empty string
        # This will populate _cached_cleaning_prompt with strategy instructions
        try:
            _, prompt = client.clean_paragraph('test', target_sexual, target_violence, 2, 'summarize')
            bw.cleaning_prompt = prompt
        except:
            pass  # If it fails, we just won't have the prompt
    
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
            
            # Check if adult or violence exceeds target
            needs_clean = rating.exceeds_target_content(target_sexual, target_violence)
            
            # Also check if there are language words to filter
            if not needs_clean and client.language_words:
                # Check if any of the selected language words are in the chapter
                text_lower = text.lower()
                for word in client.language_words:
                    if word.lower() in text_lower:
                        needs_clean = True
                        break
            
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
                  chunk_size: int = 8) -> int:
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
                reason = _infer_reason(para, target_sexual, target_violence)
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
    """Pass C: Fill in #CLEANED sections for all #CHANGE blocks with empty cleaned content.
    
    Note: Language is now checkbox-based (filtered via client.language_words), not level-based.
    """
    target_sexual = bw.target_sexual
    target_violence = bw.target_violence
    
    print(f"=== PASS C: Filling change blocks ===")
    print(f"Target levels: adult={LEVEL_TO_RATING[target_sexual]}, "
          f"violence={LEVEL_TO_RATING[target_violence]}")
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
                cleaned, _ = client.clean_paragraph(original, target_sexual, target_violence, aggression)
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
               max_iterations: int = 4, verify: bool = True) -> int:
    """Full cleaning pipeline with escalating strategies.
    
    This runs:
    1. Iteration 1: Rephrase/tone down problematic content
    2. Iteration 2: Summarize instead of showing details
    3. Iteration 3: Fade to black / time skip over scenes
    4. Iteration 4: Delete content entirely
    Each iteration re-verifies. Stops when chapter meets target rating.
    """
    # First, clean up any chapters that have change blocks but don't need cleaning
    # (This can happen if a file was partially processed or re-rated)
    cleaned_chapters = 0
    for chapter in bw.chapters:
        if not chapter.needs_cleaning:
            # Check if there are any change blocks
            has_changes = any(line.startswith('#CHANGE:') for line in chapter.content_lines)
            if has_changes:
                # Remove all change blocks and restore original content
                new_content = []
                in_change_block = False
                for line in chapter.content_lines:
                    if line.startswith('#CHANGE:'):
                        in_change_block = True
                    elif line == '#END' and in_change_block:
                        in_change_block = False
                    elif not in_change_block:
                        new_content.append(line)
                chapter.content_lines = new_content
                cleaned_chapters += 1
                if verbose:
                    print(f"Removed change blocks from Chapter {chapter.number} (marked as not needing cleaning)")
    
    if cleaned_chapters > 0:
        print(f"Cleaned up {cleaned_chapters} chapters that don't need cleaning")
        print()
    
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
    
    # Parse which content types are being filtered
    filters_enabled = {ft.strip() for ft in client.filter_types.split(',')}
    
    for i, chapter in enumerate(chapters_to_clean):
        title_str = f" ({chapter.title})" if chapter.title else ""
        print(f"[{i+1}/{len(chapters_to_clean)}] Chapter {chapter.number}{title_str}")
        
        # Double-check: Skip if chapter was marked as not needing cleaning
        # (This can happen if rating changed or chapter was reprocessed)
        if not chapter.needs_cleaning:
            print(f"  ⏭️  Skipping - chapter marked as not needing cleaning")
            continue
        
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            
            # Determine strategy based on iteration number
            # For extreme rating gaps (e.g., X→PG), skip straight to aggressive strategies
            rating_gap = 0
            if chapter.rating:
                if 'sexual' in filters_enabled:
                    sexual_level = RATING_LEVELS.get(chapter.rating.sexual, 1)
                    rating_gap = max(rating_gap, sexual_level - target_sexual)
                if 'violence' in filters_enabled:
                    violence_level = RATING_LEVELS.get(chapter.rating.violence, 1)
                    rating_gap = max(rating_gap, violence_level - target_violence)
            
            # Skip rephrase for large gaps (3+ levels, e.g., X→PG-13 is gap of 2)
            if iteration == 1 and rating_gap >= 2:
                strategy = 'summarize'
                strategy_label = 'Summarize (Large Gap)'
            elif iteration == 1:
                strategy = 'rephrase'
                strategy_label = 'Rephrase/Tone Down'
            elif iteration == 2:
                strategy = 'fade_to_black'
                strategy_label = 'Fade to Black'
            elif iteration == 3:
                strategy = 'delete'
                strategy_label = 'Delete Content'
            else:  # iteration == 4
                strategy = 'delete'
                strategy_label = 'Delete Content (Final)'
            
            # Aggression is always normal since strategy handles escalation
            aggression = 1
            
            print(f"  Pass {iteration} [{strategy_label}]:")
            
            if iteration == 1:
                # First pass: identify problematic paragraphs from ORIGINAL
                paragraphs = chapter.get_paragraphs_for_cleaning()
                if not paragraphs:
                    print("    (empty chapter)")
                    break
                
                # Rate chunks to find problematic paragraphs
                flagged_indices = set()
                chunk_size = 8
                
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
                    print(f"    ✓ No problematic paragraphs found at chunk level")
                    print(f"    ℹ️  Note: Chapter-level rating may still require attention")
                    # Don't set needs_cleaning=False here - trust the chapter-level rating
                    # The chapter may be rated X overall even if individual paragraphs seem okay
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
                        reason = _infer_reason(para, target_sexual, target_violence)
                        new_content.append(f'#REASON: {reason}')
                        new_content.append('#ORIGINAL')
                        new_content.append(para)
                        new_content.append('#CLEANED')
                        
                        # Clean the paragraph immediately with current strategy
                        try:
                            if strategy == 'delete':
                                # Delete strategy: Just remove the content
                                new_content.append('[Content removed to meet target rating]')
                            else:
                                cleaned, _ = client.clean_paragraph(para, target_sexual, target_violence, aggression, strategy)
                                # Check if content was blocked by safety filter
                                if cleaned == '[BLOCKED_BY_SAFETY_FILTER]':
                                    print(f"    ⚠️  Content blocked by safety filter - removing")
                                    new_content.append('[Content removed - blocked by safety filter]')
                                # Detect if Gemini refused to clean (returned original unchanged)
                                elif cleaned.strip() == para.strip():
                                    print(f"    ⚠️  LLM refused to clean paragraph (returned unchanged)")
                                    if strategy != 'delete':
                                        print(f"    → Will escalate to more aggressive strategy in next iteration")
                                    new_content.append(cleaned)
                                elif not cleaned.strip():
                                    # Empty response - treat as blocked
                                    print(f"    ⚠️  LLM returned empty response - removing content")
                                    new_content.append('[Content removed - empty response from LLM]')
                                else:
                                    new_content.append(cleaned)
                        except Exception as e:
                            print(f"    ⚠️  Error cleaning change block: {e}")
                            if verbose:
                                import traceback
                                traceback.print_exc()
                            # Mark as failed instead of leaving empty
                            new_content.append('[Cleaning failed - see logs]')
                        
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
                                if strategy == 'delete':
                                    # Iteration 4: Delete the content
                                    cleaned = '[Content removed to meet target rating]'
                                else:
                                    cleaned, _ = client.clean_paragraph(original, target_sexual, target_violence, aggression, strategy)
                                _set_change_cleaned(chapter, change_id, cleaned)
                                change_count += 1
                            except Exception as e:
                                print(f"    ⚠️  Error re-cleaning {change_id}: {e}")
                                if verbose:
                                    import traceback
                                    traceback.print_exc()
                                # Mark as failed
                                _set_change_cleaned(chapter, change_id, '[Cleaning failed - see logs]')
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
                        chunk_size = 8
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
                                        reason = _infer_reason(para, target_sexual, target_violence)
                                        new_content.append(f'#REASON: {reason}')
                                        new_content.append('#ORIGINAL')
                                        new_content.append(para)
                                        new_content.append('#CLEANED')
                                        try:
                                            if strategy == 'delete':
                                                cleaned = '[Content removed to meet target rating]'
                                            else:
                                                cleaned, _ = client.clean_paragraph(para, target_sexual, target_violence, aggression, strategy)
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


async def worker_clean_chapter(
    worker_id: int,
    chapter: Chapter,
    client: GeminiClient,
    target_lang: int,
    target_sexual: int,
    target_violence: int,
    max_iterations: int,
    verbose: bool,
    log_callback: Optional[Callable[[str], None]] = None
) -> int:
    """
    Async worker to clean a single chapter using Pass B-C with verification.
    Returns number of changes made.
    """
    def log(msg: str):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    
    title_str = f" ({chapter.title})" if chapter.title else ""
    log(f"[Worker {worker_id}] Chapter {chapter.number}{title_str}: Starting...")
    
    start_time = time.time()
    total_changes = 0
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        # Determine strategy based on iteration number (same as cmd_clean)
        if iteration == 1:
            strategy = 'rephrase'
            strategy_label = 'Rephrase/Tone Down'
        elif iteration == 2:
            strategy = 'summarize'
            strategy_label = 'Summarize'
        elif iteration == 3:
            strategy = 'fade_to_black'
            strategy_label = 'Fade to Black'
        else:  # iteration == 4
            strategy = 'delete'
            strategy_label = 'Delete Content'
        
        # Aggression is always normal since strategy handles escalation
        aggression = 1
        
        log(f"[Worker {worker_id}] Chapter {chapter.number}: Pass {iteration} - {strategy_label}")
        
        if iteration == 1:
            # First pass: identify problematic paragraphs from ORIGINAL
            paragraphs = chapter.get_paragraphs_for_cleaning()
            if not paragraphs:
                log(f"[Worker {worker_id}] Chapter {chapter.number}: Empty chapter")
                break
            
            # Rate chunks to find problematic paragraphs
            flagged_indices = set()
            chunk_size = 8
            
            for chunk_idx in range((len(paragraphs) + chunk_size - 1) // chunk_size):
                start = chunk_idx * chunk_size
                end = min(start + chunk_size, len(paragraphs))
                chunk = paragraphs[start:end]
                
                try:
                    # Run synchronously in thread pool to avoid blocking
                    await asyncio.sleep(0)  # Yield control
                    needs_cleaning = client.rate_chunk(chunk, target_lang, target_sexual, target_violence)
                    for idx in needs_cleaning:
                        flagged_indices.add(start + idx)
                except Exception as e:
                    if verbose:
                        log(f"[Worker {worker_id}] Chapter {chapter.number}: Error rating chunk: {e}")
                    continue
            
            if flagged_indices:
                log(f"[Worker {worker_id}] Chapter {chapter.number}: Found {len(flagged_indices)} problematic paragraphs")
                
                # Create change blocks for flagged paragraphs
                new_content = []
                global_change_id = 1
                
                for idx, para in enumerate(paragraphs):
                    if idx in flagged_indices:
                        # Create change block with empty CLEANED
                        change_id = f"c{chapter.number}_{global_change_id:03d}"
                        new_content.append('')
                        new_content.append(f'#CHANGE: {change_id}')
                        new_content.append('#STATUS: pending')
                        reason = _infer_reason(para, target_sexual, target_violence)
                        new_content.append(f'#REASON: {reason}')

                        new_content.append('#ORIGINAL')
                        new_content.append(para)
                        new_content.append('#CLEANED')
                        new_content.append('')  # Empty - to be filled
                        new_content.append('#END')
                        global_change_id += 1
                        total_changes += 1
                    else:
                        # Keep paragraph as-is
                        new_content.append('')
                        new_content.append(para)
                
                chapter.content_lines = new_content
            else:
                log(f"[Worker {worker_id}] Chapter {chapter.number}: No problematic content found")
                break
        
        # Fill in cleaned versions for all unfilled changes
        unfilled = _get_unfilled_changes(chapter)
        if unfilled:
            log(f"[Worker {worker_id}] Chapter {chapter.number}: Cleaning {len(unfilled)} changes...")
            filled_count = 0
            
            for change_id in unfilled:
                original = _get_change_original(chapter, change_id)
                if not original.strip():
                    continue
                
                try:
                    await asyncio.sleep(0)  # Yield control
                    # Use strategy-based cleaning (same as cmd_clean)
                    if strategy == 'delete':
                        cleaned = '[Content removed to meet target rating]'
                    else:
                        cleaned, _ = client.clean_paragraph(original, target_sexual, target_violence, aggression, strategy=strategy)
                    _set_change_cleaned(chapter, change_id, cleaned)
                    filled_count += 1
                    
                    if filled_count % 5 == 0:
                        log(f"[Worker {worker_id}] Chapter {chapter.number}: Cleaned [{filled_count}/{len(unfilled)}]")
                except Exception as e:
                    log(f"[Worker {worker_id}] ⚠️  Chapter {chapter.number}: Error cleaning {change_id}: {e}")
                    if verbose:
                        import traceback
                        traceback.print_exc()
                    # Mark as failed instead of leaving empty
                    _set_change_cleaned(chapter, change_id, '[Cleaning failed - see logs]')
                    filled_count += 1
            
            log(f"[Worker {worker_id}] Chapter {chapter.number}: Filled {filled_count} changes")
        
        # Verify: re-rate with CLEANED substituted
        try:
            await asyncio.sleep(0)  # Yield control
            text = chapter.get_text_with_cleaned()
            if len(text) > 10000:
                text = text[:10000] + "\n\n[truncated for rating]"
            
            rating = client.rate_chapter(text)
            chapter.rating = rating
            
            still_exceeds = rating.exceeds_target(target_lang, target_sexual, target_violence)
            
            if still_exceeds:
                log(f"[Worker {worker_id}] Chapter {chapter.number}: Still exceeds (L={rating.language} A={rating.sexual} V={rating.violence})")
            else:
                log(f"[Worker {worker_id}] Chapter {chapter.number}: ✓ Target met (L={rating.language} A={rating.sexual} V={rating.violence})")
                break
        except Exception as e:
            log(f"[Worker {worker_id}] Chapter {chapter.number}: Error verifying: {e}")
            break
    
    elapsed = time.time() - start_time
    log(f"[Worker {worker_id}] ✅ Chapter {chapter.number} complete ({int(elapsed)}s, {total_changes} changes)")
    
    return total_changes


async def cmd_clean_parallel(
    bw: BookWashFile,
    api_key: str,
    model: str,
    num_workers: int,
    target_lang: int,
    target_sexual: int,
    target_violence: int,
    max_iterations: int,
    verbose: bool,
    session_dir: Optional[Path] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    language_words: list = None
) -> int:
    """
    Parallel cleaning pipeline using async workers with a shared queue.
    Writes per-chapter files during processing for crash resilience.
    """
    def log(msg: str):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    
    chapters_to_clean = [ch for ch in bw.chapters if ch.needs_cleaning]
    
    if not chapters_to_clean:
        log("No chapters need cleaning.")
        return 0
    
    log(f"=== PASS B-C: Cleaning {len(chapters_to_clean)} chapters ({num_workers} workers) ===")
    log(f"Target levels: language={target_lang} ({LEVEL_TO_RATING[target_lang]}), "
        f"adult={target_sexual} ({LEVEL_TO_RATING[target_sexual]}), "
        f"violence={target_violence} ({LEVEL_TO_RATING[target_violence]})")
    log(f"Max iterations per chapter: {max_iterations}")
    log("")
    
    # Create queue and add chapters
    queue = asyncio.Queue()
    for chapter in chapters_to_clean:
        await queue.put(chapter)
    
    # Create clients (one per worker to avoid threading issues)
    clients = [GeminiClient(api_key, model, language_words=language_words or []) for _ in range(num_workers)]
    
    total_changes = 0
    completed = []
    
    async def worker(worker_id: int):
        nonlocal total_changes
        client = clients[worker_id]
        
        while True:
            try:
                chapter = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # Queue is empty
                break
            
            try:
                changes = await worker_clean_chapter(
                    worker_id + 1,
                    chapter,
                    client,
                    target_lang,
                    target_sexual,
                    target_violence,
                    max_iterations,
                    verbose,
                    log_callback
                )
                total_changes += changes
                completed.append(chapter.number)
                
                # Write per-chapter file if session_dir provided
                if session_dir:
                    chapter_file = session_dir / f"ch_{chapter.number:03d}.bookwash"
                    write_chapter_bookwash(chapter, chapter_file, bw.settings)
                
                # Log progress
                log(f"Progress: {len(completed)}/{len(chapters_to_clean)} chapters complete")
                
            except Exception as e:
                log(f"[Worker {worker_id + 1}] ❌ Chapter {chapter.number} failed: {e}")
            finally:
                queue.task_done()
    
    # Start workers
    workers = [asyncio.create_task(worker(i)) for i in range(num_workers)]
    
    # Wait for all work to complete
    await queue.join()
    
    # Cancel workers
    for w in workers:
        w.cancel()
    
    await asyncio.gather(*workers, return_exceptions=True)
    
    log("")
    log(f"Cleaning complete: {total_changes} total changes made across {len(completed)} chapters")
    
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
    parser.add_argument('--language', type=int, default=None, choices=[1,2,3,4,5],
                       help='Target language level: 1=G, 2=PG, 3=PG-13, 4=R, 5=Unrated (DEPRECATED: use --language-words)')
    parser.add_argument('--language-words', type=str, default=None,
                       help='JSON list of specific words to filter (e.g., ["damn", "hell", "shit"])')
    parser.add_argument('--sexual', type=int, default=2, choices=[1,2,3,4,5],
                       help='Target sexual content level (default: 2)')
    parser.add_argument('--violence', type=int, default=5, choices=[1,2,3,4,5],
                       help='Target violence level (default: 5/Unrated)')
    parser.add_argument('--filter-types', type=str, default='language,sexual,violence',
                       help='Comma-separated list of content types to filter (e.g., "language" for language-only)')
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
    parser.add_argument('--workers', type=int, default=1,
                       help='Number of parallel workers for cleaning (default: 1)')
    parser.add_argument('--output-dir', type=str,
                       help='Directory to write per-chapter files during parallel processing')
    
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
    
    # Handle language filtering
    language_words = []
    if args.language_words:
        try:
            language_words = json.loads(args.language_words)
            print(f"Language: Filtering {len(language_words)} specific words")
            # Convert to a pseudo-level based on word severity for backward compatibility
            # This is used for _infer_reason() threshold checks
            if any(w in language_words for w in ['fuck', 'shit', 'motherfucker']):
                target_lang = 4  # R-level words present
            elif any(w in language_words for w in ['damn', 'hell', 'crap', 'ass', 'bitch', 'bastard']):
                target_lang = 3  # PG-13 level words
            elif any(w in language_words for w in ['darn', 'gosh', 'heck']):
                target_lang = 2  # PG level
            else:
                target_lang = 1  # G (filter everything)
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in --language-words: {args.language_words}")
            return 1
    elif args.language is not None:
        target_lang = args.language
        print(f"Language: Using legacy level {target_lang} ({LEVEL_TO_RATING.get(target_lang, 'Unknown')})")
    else:
        target_lang = 2  # Default PG
        print(f"Language: Using default level {target_lang} (PG)")
    
    if args.dry_run:
        print("Dry run mode - no API calls will be made")
        for ch in bw.chapters:
            title = f" ({ch.title})" if ch.title else ""
            rating_str = f" L={ch.rating.language} S={ch.rating.sexual} V={ch.rating.violence}" if ch.rating else ""
            needs = f" NEEDS_CLEANING" if ch.needs_cleaning else ""
            print(f"  Chapter {ch.number}{title}{rating_str}{needs}")
        return 0
    
    # Create client
    # Determine which content types are being filtered
    # If language-words specified, only filter language (unless other flags indicate otherwise)
    filter_types = args.filter_types
    if args.language_words and 'language' not in filter_types:
        # User explicitly provided language words, so ensure language is in filter types
        if 'language' not in filter_types:
            filter_types = 'language,' + filter_types
    
    client = GeminiClient(api_key, args.model, language_words=language_words, filter_types=filter_types)
    
    # Run passes
    if args.rate:
        cmd_rate(bw, client, args.sexual, args.violence, args.verbose)
        print()
    
    if args.identify:
        cmd_identify(bw, client, args.verbose, chunk_size=args.chunk_size)
        print()
    
    if args.fill:
        cmd_fill(bw, client, args.verbose, aggression=args.aggression)
        print()
    
    if args.clean:
        num_workers = args.workers
        
        if num_workers > 1:
            # Parallel processing
            session_dir = None
            if args.output_dir:
                session_dir = Path(args.output_dir)
                session_dir.mkdir(parents=True, exist_ok=True)
            
            asyncio.run(cmd_clean_parallel(
                bw, api_key, args.model,
                num_workers=num_workers,
                target_lang=target_lang,
                target_sexual=args.sexual,
                target_violence=args.violence,
                max_iterations=args.max_iterations,
                verbose=args.verbose,
                session_dir=session_dir,
                language_words=language_words
            ))
            
            # Merge chapter files if they were written
            if session_dir and list(session_dir.glob('ch_*.bookwash')):
                print("Merging per-chapter files...")
                merge_chapter_files(session_dir, input_path, bw.settings)
        else:
            # Serial processing (original)
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
