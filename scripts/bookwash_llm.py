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

def obfuscate_word(word: str) -> str:
    """Obfuscate a profane word by replacing a vowel with *.
    
    Examples: shit -> sh*t, fuck -> f*ck, asshole -> *sshole
    """
    vowels = 'aeiouAEIOU'
    result = list(word)
    for i, char in enumerate(result):
        if char in vowels:
            result[i] = '*'
            break
    return ''.join(result)


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
    needs_cleaning: Optional[bool] = None  # Legacy: true if any cleaning needed
    needs_language_cleaning: Optional[bool] = None  # True if language words need to be cleaned
    needs_adult_cleaning: Optional[bool] = None  # True if sexual content exceeds target
    needs_violence_cleaning: Optional[bool] = None  # True if violence exceeds target
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
            elif line.startswith('#NEEDS_LANGUAGE_CLEANING:'):
                val = line[25:].strip().lower()
                current_chapter.needs_language_cleaning = val == 'true'
            elif line.startswith('#NEEDS_ADULT_CLEANING:'):
                val = line[22:].strip().lower()
                current_chapter.needs_adult_cleaning = val == 'true'
            elif line.startswith('#NEEDS_VIOLENCE_CLEANING:'):
                val = line[25:].strip().lower()
                current_chapter.needs_violence_cleaning = val == 'true'
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
        
        # Write specific cleaning flags (new format)
        if chapter.needs_language_cleaning is not None:
            lines.append(f'#NEEDS_LANGUAGE_CLEANING: {"true" if chapter.needs_language_cleaning else "false"}')
        if chapter.needs_adult_cleaning is not None:
            lines.append(f'#NEEDS_ADULT_CLEANING: {"true" if chapter.needs_adult_cleaning else "false"}')
        if chapter.needs_violence_cleaning is not None:
            lines.append(f'#NEEDS_VIOLENCE_CLEANING: {"true" if chapter.needs_violence_cleaning else "false"}')
        
        # Legacy flag for backward compatibility
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
    
    def _log_blocked_content(self, block_reason: str, text: str, log_type: str) -> None:
        """Log blocked content to a file for analysis.
        
        Creates/appends to 'blocked_content.log' in the current directory.
        """
        from datetime import datetime
        
        log_file = Path('blocked_content.log')
        timestamp = datetime.now().isoformat()
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"TIMESTAMP: {timestamp}\n")
            f.write(f"BLOCK_REASON: {block_reason}\n")
            f.write(f"LOG_TYPE: {log_type}\n")
            f.write(f"MODEL: {self.current_model}\n")
            f.write(f"TEXT_LENGTH: {len(text)} chars\n")
            f.write(f"CONTENT:\n")
            f.write(f"{text}\n")
            f.write(f"{'='*80}\n")
        
        print(f"      (Full blocked content logged to {log_file})")
    
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
                        # Log the blocked content for debugging (first 500 chars of text)
                        text_preview = text[:500] if len(text) > 500 else text
                        text_preview = text_preview.replace('\n', ' ')[:300]  # Compact for display
                        print(f"      BLOCKED TEXT: {text_preview}...")
                        # Also log to file for later analysis
                        self._log_blocked_content(block_reason, text, log_type)
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

KEEP all other words not in the removal list or similar severity.

CONTEXT-AWARE FILTERING:
- Narrative descriptions like "he cursed" or "snarled a curse" should be KEPT (they describe action without showing the word)
- Only remove when the actual profane word is shown in dialogue or narration
- Consider usage context: emphasis vs. actual cursing
- Religious phrases used genuinely (prayer, worship) may be kept, but blasphemous usage must be removed

EXAMPLES:
❌ "What the hell is going on?" → ✅ "What in the worldis going on?"
❌ "This is bullshit!" → ✅ "This is ridiculous!"
❌ "He's a real bastard." → ✅ "He's a real jerk."
❌ "Fuck this!" → ✅ "Forget this!"
❌ "You are an asshole!" → ✅ "You are a real piece of work!!"
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


def _remove_orphaned_cleaning_markers(bw: 'BookWashFile') -> int:
    """Remove #NEEDS_*_CLEANING markers that appear outside of change blocks.
    
    These markers should only exist between #CHANGE: and #ORIGINAL lines.
    If they appear elsewhere (orphaned), they should be removed.
    
    Returns the number of orphaned markers removed.
    """
    removed_count = 0
    cleaning_markers = {
        '#NEEDS_LANGUAGE_CLEANING',
        '#NEEDS_ADULT_CLEANING', 
        '#NEEDS_VIOLENCE_CLEANING'
    }
    
    for chapter in bw.chapters:
        new_content = []
        in_change_block = False
        past_original = False
        
        for line in chapter.content_lines:
            if line.startswith('#CHANGE:'):
                in_change_block = True
                past_original = False
                new_content.append(line)
            elif line == '#ORIGINAL':
                past_original = True
                new_content.append(line)
            elif line == '#END':
                in_change_block = False
                past_original = False
                new_content.append(line)
            elif line in cleaning_markers:
                if in_change_block and not past_original:
                    # Valid location - keep it
                    new_content.append(line)
                else:
                    # Orphaned marker - remove it
                    removed_count += 1
            else:
                new_content.append(line)
        
        chapter.content_lines = new_content
    
    return removed_count


def _remove_identical_change_blocks(bw: 'BookWashFile') -> int:
    """Remove change blocks where ORIGINAL == CLEANED (false positives).
    
    Returns the number of blocks removed.
    """
    removed_count = 0
    
    for chapter in bw.chapters:
        # Parse all change blocks and identify identical ones
        new_content = []
        i = 0
        lines = chapter.content_lines
        
        while i < len(lines):
            line = lines[i]
            
            if line.startswith('#CHANGE:'):
                # Found a change block - parse it completely
                change_start = i
                change_id = line.split(':')[1].strip()
                
                original_lines = []
                cleaned_lines = []
                in_original = False
                in_cleaned = False
                change_end = i
                
                # Scan through the change block
                j = i
                while j < len(lines):
                    block_line = lines[j]
                    if block_line == '#ORIGINAL':
                        in_original = True
                        in_cleaned = False
                    elif block_line == '#CLEANED':
                        in_original = False
                        in_cleaned = True
                    elif block_line == '#END':
                        change_end = j
                        break
                    elif in_original and not block_line.startswith('#'):
                        original_lines.append(block_line)
                    elif in_cleaned and not block_line.startswith('#'):
                        cleaned_lines.append(block_line)
                    j += 1
                
                # Compare original and cleaned
                original_text = '\n'.join(original_lines).strip()
                cleaned_text = '\n'.join(cleaned_lines).strip()
                
                if original_text == cleaned_text and cleaned_text:
                    # Identical! Skip this change block, output just the original text
                    removed_count += 1
                    new_content.append('')  # Empty line before paragraph
                    new_content.append(original_text)
                    i = change_end + 1
                else:
                    # Keep the change block
                    while i <= change_end:
                        new_content.append(lines[i])
                        i += 1
            else:
                new_content.append(line)
                i += 1
        
        chapter.content_lines = new_content
    
    return removed_count


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


# --- Focused Cleaning Prompts (New Simplified System) ---

def build_language_cleaning_prompt(language_words: list) -> str:
    """Build a focused prompt for language-only cleaning.
    
    This is word-list based, not level-based. We categorize the words
    to determine severity and provide context-appropriate replacements.
    """
    if not language_words:
        return ""
    
    # Categorize words by severity to give better replacement guidance
    words_lower = [w.lower() for w in language_words]
    
    mild_words = [w for w in language_words if w.lower() in ['darn', 'gosh', 'heck', 'gee', 'jeez', 'dang']]
    moderate_words = [w for w in language_words if w.lower() in ['damn', 'hell', 'crap', 'ass', 'piss', 'bummer']]
    strong_words = [w for w in language_words if w.lower() in ['shit', 'bitch', 'bastard', 'asshole', 'bullshit']]
    severe_words = [w for w in language_words if w.lower() in ['fuck', 'fucking', 'motherfucker', 'cunt']]
    blasphemous = [w for w in language_words if w.lower() in ['goddamn', 'jesus christ', 'oh my god']]
    
    # Build replacement guidance based on what's in the list
    replacement_rules = []
    
    if severe_words:
        replacement_rules.append("""SEVERE PROFANITY (fuck, motherfucker, cunt):
   - Remove entirely OR rephrase the sentence to convey emotion without the word
   - "What the fuck?" → "What?" or "What is going on?"
   - "Fuck you!" → Remove the line, or "Get away from me!"
   - "fucking idiot" → "complete idiot" or just "idiot"
   - "motherfucker" → Remove entirely""")
    
    if strong_words:
        replacement_rules.append("""STRONG PROFANITY (shit, bitch, bastard, asshole, bullshit):
   - "shit" → "crud" or remove ("Oh shit!" → "Oh no!")
   - "bullshit" → "nonsense" or "ridiculous"
   - "bitch" → "jerk", "idiot", "sissy" or remove
   - "bastard" → "jerk" or "scoundrel"
   - "asshole" → "jerk", "fool", "dork" or remove
   - "son of a bitch" → remove entirely""")
    
    if moderate_words:
        replacement_rules.append("""MODERATE PROFANITY (damn, hell, crap, ass):
   - "damn" → "curses" or remove ("Damn it!" → "Darn it!" or just remove)
   - "hell" → rephrase ("What the hell" → "What on earth")
   - "crap" → "crud" or "junk"
   - "ass" → "butt" or "rear" or remove""")
    
    if mild_words:
        replacement_rules.append("""MILD EXCLAMATIONS (darn, gosh, heck, gee, jeez):
   - Remove or replace with neutral expressions
   - "Darn it!" → "Oh no!" or remove
   - "Gosh" → "Wow" or remove
   - "Jeez" → remove or "Wow" """)
    
    if blasphemous:
        replacement_rules.append("""BLASPHEMOUS EXPRESSIONS (goddamn, jesus christ as expletive, oh my god):
   - "goddamn" → "holy cow" or remove
   - "Jesus Christ!" (as expletive) → "Good grief!" or remove
   - "Oh my god!" (as expletive) → "Oh my!" or "Oh my goodness!"
   - Keep genuine religious usage (prayer, worship) unchanged""")
    
    replacement_section = "\n\n".join(replacement_rules) if replacement_rules else "Replace with appropriate neutral alternatives."
    
    return f"""You are cleaning profanity from a book. Your ONLY task is to replace specific words.

WORDS TO REMOVE: {', '.join(language_words)}

CRITICAL RULES:
1. Return ONLY the cleaned text - no explanations, no commentary
2. Preserve paragraph structure EXACTLY - same line breaks
3. DO NOT change anything else - keep all other content identical
4. Narrative descriptions like "he cursed" or "she swore" are ALLOWED - only remove actual profane words shown

SENTENCE REPAIR (VERY IMPORTANT):
- NEVER leave a sentence starting with just "It," or "This," - that is broken grammar
- If a profane word starts a sentence like "Fuck this" or "Fuck it", you MUST rewrite the ENTIRE sentence
- Examples of BROKEN output to AVOID:
  - "It," he muttered  ← WRONG
  - "This," he screamed ← WRONG
- Correct rewrites:
  - "Fuck it" → "Whatever" or "Forget it" or "I don't care" or remove the sentence
  - "Fuck this" → "I'm done with this" or "This is pointless" or remove
  - "Fuck everything" → "I hate everything" or "Everything is terrible" or remove

REPLACEMENT GUIDANCE:

{replacement_section}

GENERAL PRINCIPLES:
- Preserve the emotional intensity when possible
- If a word is used for emphasis, the replacement should carry similar weight
- When removing a word leaves awkward phrasing, REWRITE the sentence to be grammatically correct
- Don't add new ideas, but DO fix broken grammar caused by word removal

Text to clean:
"""


def build_adult_cleaning_prompt(target_sexual: int) -> str:
    """Build a focused prompt for adult content cleaning.
    
    Each level has very specific, bespoke rules for what's allowed and what must go.
    """
    
    if target_sexual == 1:  # G rating
        return """You are cleaning adult/romantic content from a book to achieve a G (General Audiences) rating.

G RATING REQUIREMENTS - NO romantic or sensual content at all:

MUST REMOVE:
- ALL kissing (even brief pecks)
- ALL romantic embraces or holding
- ANY physical attraction descriptions ("she was beautiful", "his eyes lingered")
- Dancing together romantically
- Hand-holding in romantic context
- Longing looks, racing hearts from attraction
- ANY clothing descriptions that emphasize appearance
- ANY mention of dating, romance, or relationships beyond friendship

ALLOWED:
- Friendly hugs (clearly platonic)
- Family affection (parent-child)
- Handshakes
- Characters described neutrally without attraction focus

REPLACEMENT APPROACH:
- Convert romantic scenes to friendly/platonic interactions
- "They kissed goodbye" → "They said goodbye"
- "She noticed how handsome he was" → Remove entirely
- "They danced together, bodies close" → "They enjoyed the event"
- "His heart raced when she smiled" → "He smiled back"

RULES:
1. Return ONLY the cleaned text - no explanations
2. Preserve paragraph structure EXACTLY
3. When in doubt, REMOVE rather than keep

Text to clean:
"""

    elif target_sexual == 2:  # PG rating
        return """You are cleaning adult/romantic content from a book to achieve a PG (Parental Guidance) rating.

PG RATING REQUIREMENTS - Very mild romance only. Think Disney movies.

ALLOWED (keep these):
- Brief, innocent kiss (peck on lips or cheek)
- Hand-holding
- Friendly/warm hugs (platonic-feeling)
- Simple statements of attraction ("She thought he was handsome")
- Saying "I love you"

MUST REMOVE COMPLETELY (these have NO place in PG content):
- Passionate or lingering kisses (more than a brief moment)
- "Lips parted", "deepened the kiss", "tongues met"
- Body pressed against body
- Hands roaming, caressing, exploring
- ANY arousal cues (racing hearts from desire, flushed with want, breath catching)
- Post-intimacy scenes ("tangled in sheets", "afterward they lay together")
- Implied sex ("the door closed behind them", "they spent the night")
- Revealing clothing descriptions (cleavage, bare skin emphasis, tight clothes on curves)
- Focus on body parts in sensual context (breasts, thighs, hips, curves)
- Lap-sitting, straddling, grinding
- Strip clubs, gentlemen's clubs, or similar adult venues and activities
- Private dances, lap dances, or any performance with sexual undertones
- Suggestive dialogue ("Touch me", "I want you", "You're so hard/wet")
- Characters in underwear/lingerie described sensuously
- ANY physical arousal mentioned or implied
- Escorts, "companions", or transactional intimacy

REPLACEMENT APPROACH:
- Passionate kiss → brief kiss ("He kissed her quickly")
- Extended embrace → simple hug ("They hugged")
- Post-intimacy scene → time skip ("The next morning...")
- Revealing outfit → neutral clothing mention ("She wore a dress")
- Strip club/adult venue scene → REMOVE ENTIRELY or replace with: "They spent time at a lounge."
- Suggestive dialogue → remove or make neutral ("Touch me" → remove)
- Private dance → REMOVE ENTIRELY or: "They talked."
- Physical arousal → REMOVE the sentence

AGGRESSIVE REMOVAL IS OKAY:
- If a paragraph is mostly explicit content, replace it with a single neutral sentence or remove it
- It's better to cut too much than to leave PG-inappropriate content
- Example: A whole explicit paragraph → "They shared a moment together." or just remove it

RULES:
1. Return ONLY the cleaned text - no explanations
2. Preserve paragraph structure where possible, but removal is acceptable
3. When in doubt, REMOVE rather than try to salvage

Text to clean:
"""

    elif target_sexual == 3:  # PG-13 rating
        return """You are cleaning adult/romantic content from a book to achieve a PG-13 rating.

PG-13 RATING REQUIREMENTS - Passionate romance allowed, no explicit content:

ALLOWED (keep these):
- Passionate, extended kissing
- Strong embraces, bodies close
- Implied intimacy with fade-to-black ("Later that night..." then skip)
- Sensual tension and buildup
- Brief mentions of attraction to body ("her curves", "his muscular arms")
- Post-intimacy morning-after scenes (non-explicit)
- Characters in bed together (without explicit activity)
- Racing hearts, flushed skin, desire

MUST REMOVE:
- Explicit sexual activity (any description of the act itself)
- Nudity described in detail
- Anatomical descriptions (genitalia, explicit breast descriptions beyond "cleavage")
- Touching of intimate areas
- Explicit arousal descriptions (erections, wetness)
- Graphic physical sensations during intimacy
- Sexual dialogue/dirty talk

REPLACEMENT APPROACH:
- Explicit scene → fade to black: "They fell into bed together. Later..."
- Detailed nudity → implied: "She undressed" (don't describe what's revealed)
- Explicit touching → passionate embrace: "Their hands explored" → "They held each other close"
- Graphic sensations → emotional: Focus on emotional connection, skip physical details

RULES:
1. Return ONLY the cleaned text - no explanations
2. Preserve paragraph structure EXACTLY
3. Keep the passion and emotion, remove explicit physical details

Text to clean:
"""

    else:  # Level 4 (R) or 5 (Unrated) - no filtering needed
        return """You are reviewing content. The target allows ALL adult content.

NO FILTERING REQUIRED - Return the text exactly as-is.

Text to return unchanged:
"""


def build_violence_cleaning_prompt(target_violence: int) -> str:
    """Build a focused prompt for violence content cleaning.
    
    Each level has very specific, bespoke rules for what's allowed and what must go.
    """
    
    if target_violence == 1:  # G rating
        return """You are cleaning violent content from a book to achieve a G (General Audiences) rating.

G RATING REQUIREMENTS - NO physical violence:

MUST REMOVE:
- ALL physical fighting (punches, kicks, strikes)
- ALL weapons (guns, knives, swords - even mentioned)
- ANY injury descriptions (cuts, bruises, blood)
- Threats of physical harm
- Characters physically hurting each other
- Hunting or killing animals
- Death (even off-screen)
- War or battle scenes

ALLOWED:
- Verbal arguments and disagreements
- Characters being upset or angry (emotions only)
- Non-violent competition (races, games)
- Mild cartoon-style mishaps (slipping, bumping into things - no injury)

REPLACEMENT APPROACH:
- Fight scene → argument: "They fought" → "They argued intensely"
- Weapon → remove: "He drew his sword" → "He stood ready"
- Injury → remove: "Blood ran down his face" → Remove entirely
- Death → euphemism: "He killed the guard" → "He got past the guard"
- Battle → summary: Extended fight scene → "The conflict was resolved"

RULES:
1. Return ONLY the cleaned text - no explanations
2. Preserve paragraph structure EXACTLY
3. Convert physical conflict to verbal/emotional conflict where possible

Text to clean:
"""

    elif target_violence == 2:  # PG rating
        return """You are cleaning violent content from a book to achieve a PG (Parental Guidance) rating.

PG RATING REQUIREMENTS - Mild action only:

ALLOWED (keep these):
- Brief, non-detailed scuffles
- Pushing, shoving (no injury result)
- Characters falling or getting knocked down
- Weapons mentioned (not used graphically)
- Implied danger without showing harm
- Cartoon-style action (chase scenes, slapstick)

MUST REMOVE:
- Blood of any kind
- Visible injuries (cuts, wounds, bruises described)
- Pain descriptions ("agony", "searing pain")
- Weapons making contact with bodies
- Death shown or described (off-screen death can be implied)
- Graphic fight choreography (blow-by-blow)
- Sounds of violence (bones cracking, flesh tearing)

REPLACEMENT APPROACH:
- "Blood dripped from the wound" → "He was hurt"
- "The knife sliced into his arm" → "He dodged the attack"
- Detailed fight → summary: "They fought" or "A scuffle ensued"
- Death description → implication: "He was killed" → "He didn't survive"
- Injury detail → vague: "His broken ribs" → "He was injured"

RULES:
1. Return ONLY the cleaned text - no explanations
2. Preserve paragraph structure EXACTLY
3. Keep the action, remove the graphic consequences

Text to clean:
"""

    elif target_violence == 3:  # PG-13 rating
        return """You are cleaning violent content from a book to achieve a PG-13 rating.

PG-13 RATING REQUIREMENTS - Action violence allowed, no graphic gore:

ALLOWED (keep these):
- Combat and fighting with moderate detail
- Blood mentioned (not dwelt upon)
- Injuries described briefly (broken bones, cuts, gunshot wounds)
- Weapons used in action scenes
- Death (shown or implied, not lingered on)
- War/battle scenes
- Martial arts, sword fights, gun battles
- Pain acknowledged

MUST REMOVE:
- Graphic gore (organs visible, bones protruding)
- Torture scenes with detail
- Prolonged suffering descriptions
- Extremely detailed wound descriptions
- Sadistic violence (enjoying causing pain)
- Dismemberment described graphically
- Blood described in excessive detail (pools, spraying, arterial)
- Bodies described in graphic decay

REPLACEMENT APPROACH:
- Gore detail → simple wound: "intestines spilled out" → "a severe wound"
- Torture → summary: Extended torture → "He was beaten for information"
- Graphic death → quick: Long death scene → "He died from his wounds"
- Excessive blood → brief: "Blood pooled everywhere" → "He was bleeding badly"

RULES:
1. Return ONLY the cleaned text - no explanations
2. Preserve paragraph structure EXACTLY
3. Keep the action and stakes, reduce graphic details

Text to clean:
"""

    else:  # Level 4 (R) or 5 (Unrated) - no filtering needed
        return """You are reviewing content. The target allows ALL violent content.

NO FILTERING REQUIRED - Return the text exactly as-is.

Text to return unchanged:
"""


# Fallback text for when cleaning fails or content is blocked
ADULT_FALLBACK = "The moment passed, and they moved on."
VIOLENCE_FALLBACK = "A violent confrontation ensued."


def _get_change_blocks(chapter) -> list:
    """Get all change block IDs and their cleaning type from a chapter."""
    changes = []
    current_id = None
    cleaning_type = None
    
    for line in chapter.content_lines:
        if line.startswith('#CHANGE:'):
            current_id = line.split(':')[1].strip()
            cleaning_type = 'generic'  # Default
        elif line == '#NEEDS_LANGUAGE_CLEANING':
            cleaning_type = 'language'
        elif line == '#NEEDS_ADULT_CLEANING':
            cleaning_type = 'adult'
        elif line == '#NEEDS_VIOLENCE_CLEANING':
            cleaning_type = 'violence'
        elif line == '#END' and current_id:
            changes.append({'id': current_id, 'type': cleaning_type})
            current_id = None
            cleaning_type = None
    
    return changes


def _create_change_blocks_for_chapter(chapter, paragraphs: list, flagged_indices: set, 
                                       cleaning_type: str) -> int:
    """Create change blocks for flagged paragraphs with specific cleaning type.
    
    Args:
        chapter: The chapter to modify
        paragraphs: List of all paragraphs in the chapter
        flagged_indices: Set of paragraph indices that need cleaning
        cleaning_type: One of 'language', 'adult', 'violence'
        
    Returns:
        Number of change blocks created
    """
    new_content = []
    change_num = 1  # Change number within this chapter
    
    for idx, para in enumerate(paragraphs):
        if idx in flagged_indices:
            new_content.append('')
            new_content.append(f'#CHANGE: {chapter.number}.{change_num}')
            new_content.append('#STATUS: pending')
            # Use specific cleaning type instead of generic reason
            new_content.append(f'#NEEDS_{cleaning_type.upper()}_CLEANING')
            new_content.append('#ORIGINAL')
            new_content.append(para)
            new_content.append('#CLEANED')
            new_content.append('')  # To be filled
            new_content.append('#END')
            change_num += 1
        else:
            new_content.append('')
            new_content.append(para)
    
    chapter.content_lines = new_content
    return change_num - 1  # Return count of changes created


# --- Main Commands ---

def cmd_rate(bw: BookWashFile, client: GeminiClient, 
             target_sexual: int, target_violence: int,
             verbose: bool = False) -> int:
    """Pass A: Rate all chapters, set specific cleaning flags.
    
    Sets three independent flags:
    - needs_language_cleaning: True if any of client.language_words are found in text
    - needs_adult_cleaning: True if sexual rating exceeds target_sexual
    - needs_violence_cleaning: True if violence rating exceeds target_violence
    
    Also sets legacy needs_cleaning = True if ANY of the above are True.
    """
    print(f"=== PASS A: Rating {len(bw.chapters)} chapters ===")
    print(f"Target levels: adult={LEVEL_TO_RATING[target_sexual]}, "
          f"violence={LEVEL_TO_RATING[target_violence]}")
    if client.language_words:
        obfuscated = [obfuscate_word(w) for w in client.language_words[:5]]
        print(f"Language words to filter: {', '.join(obfuscated)}{'...' if len(client.language_words) > 5 else ''}")
    print()
    
    # Update settings in file
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
            chapter.needs_language_cleaning = False
            chapter.needs_adult_cleaning = False
            chapter.needs_violence_cleaning = False
            continue
        
        # Truncate very long chapters for rating (first ~10k chars should be representative)
        if len(text) > 10000:
            text = text[:10000] + "\n\n[truncated for rating]"
        
        try:
            rating = client.rate_chapter(text)
            chapter.rating = rating
            
            # Set specific flags based on what exceeds target
            chapter.needs_adult_cleaning = RATING_LEVELS.get(rating.sexual, 1) > target_sexual
            chapter.needs_violence_cleaning = RATING_LEVELS.get(rating.violence, 1) > target_violence
            
            # Check for language words
            chapter.needs_language_cleaning = False
            if client.language_words:
                text_lower = text.lower()
                for word in client.language_words:
                    if word.lower() in text_lower:
                        chapter.needs_language_cleaning = True
                        break
            
            # Legacy flag: True if ANY cleaning is needed
            chapter.needs_cleaning = (
                chapter.needs_language_cleaning or 
                chapter.needs_adult_cleaning or 
                chapter.needs_violence_cleaning
            )
            
            if chapter.needs_cleaning:
                needs_cleaning_count += 1
            
            # Build status string showing which types need cleaning
            status_parts = []
            if chapter.needs_language_cleaning:
                status_parts.append("LANG")
            if chapter.needs_adult_cleaning:
                status_parts.append("ADULT")
            if chapter.needs_violence_cleaning:
                status_parts.append("VIOLENCE")
            status = f"NEEDS: {'+'.join(status_parts)}" if status_parts else "OK"
            
            print(f"  Rating: L={rating.language} A={rating.sexual} V={rating.violence} -> {status}")
            
        except Exception as e:
            print(f"  Error rating chapter: {e}")
            chapter.rating = ChapterRating()
            chapter.needs_cleaning = False
            chapter.needs_language_cleaning = False
            chapter.needs_adult_cleaning = False
            chapter.needs_violence_cleaning = False
    
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
        change_num = 1  # Change number within this chapter
        
        for idx, para in enumerate(paragraphs):
            if idx in flagged_indices:
                # Create change block with empty CLEANED
                new_content.append('')
                new_content.append(f'#CHANGE: {chapter.number}.{change_num}')
                new_content.append('#STATUS: pending')
                reason = _infer_reason(para, target_sexual, target_violence)
                new_content.append(f'#REASON: {reason}')
                new_content.append('#ORIGINAL')
                new_content.append(para)
                new_content.append('#CLEANED')
                new_content.append('')  # Empty - to be filled in Pass C
                new_content.append('#END')
                change_num += 1
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


def cmd_clean_passes(bw: BookWashFile, client: GeminiClient, filepath: Path,
                      verbose: bool = False) -> int:
    """New simplified cleaning pipeline with separate passes for each content type.
    
    Three passes, each saving to file after completion:
    1. Language pass: Clean blocks with #NEEDS_LANGUAGE_CLEANING
    2. Adult pass: Clean blocks with #NEEDS_ADULT_CLEANING  
    3. Violence pass: Clean blocks with #NEEDS_VIOLENCE_CLEANING
    
    No re-rating or escalation - each pass uses focused prompts.
    """
    target_sexual = bw.target_sexual
    target_violence = bw.target_violence
    
    # Count chapters that need cleaning for progress display
    chapters_needing_cleaning = sum(1 for ch in bw.chapters if ch.needs_cleaning)
    
    print(f"=== CLEANING PIPELINE: {chapters_needing_cleaning} chapters ===")
    print(f"Target levels: adult={LEVEL_TO_RATING[target_sexual]}, "
          f"violence={LEVEL_TO_RATING[target_violence]}")
    if client.language_words:
        print(f"Language words: {', '.join(client.language_words[:5])}{'...' if len(client.language_words) > 5 else ''}")
    print()
    
    total_changes = 0
    
    # First, identify paragraphs that need each type of cleaning
    # and create change blocks with specific flags
    print("=== IDENTIFYING CONTENT TO CLEAN ===")
    
    for i, chapter in enumerate(bw.chapters):
        if not chapter.needs_cleaning:
            continue
            
        title_str = f" ({chapter.title})" if chapter.title else ""
        print(f"[{i+1}/{len(bw.chapters)}] Chapter {chapter.number}{title_str}")
        
        paragraphs = chapter.get_paragraphs_for_cleaning()
        if not paragraphs:
            continue
        
        # Find paragraphs needing each type of cleaning
        lang_indices = set()
        adult_indices = set()
        violence_indices = set()
        
        # Language: word boundary search for banned words (prevents "class" matching "ass")
        if chapter.needs_language_cleaning and client.language_words:
            for idx, para in enumerate(paragraphs):
                para_lower = para.lower()
                for word in client.language_words:
                    # Use word boundary regex to avoid partial matches
                    pattern = r'\b' + re.escape(word.lower()) + r'\b'
                    if re.search(pattern, para_lower):
                        lang_indices.add(idx)
                        break
        
        # Adult/Violence: Use LLM to identify specific paragraphs
        if chapter.needs_adult_cleaning or chapter.needs_violence_cleaning:
            chunk_size = 8
            for chunk_idx in range((len(paragraphs) + chunk_size - 1) // chunk_size):
                start = chunk_idx * chunk_size
                end = min(start + chunk_size, len(paragraphs))
                chunk = paragraphs[start:end]
                
                try:
                    # Rate chunk - this returns paragraph indices that exceed ANY target
                    # We'll use the chapter's rating to determine which type
                    needs_clean_indices = client.rate_chunk(
                        chunk, 
                        bw.target_language if hasattr(bw, 'target_language') else 2,
                        target_sexual, 
                        target_violence
                    )
                    
                    for idx in needs_clean_indices:
                        abs_idx = start + idx
                        # Determine if it's adult or violence based on chapter rating
                        if chapter.needs_adult_cleaning:
                            adult_indices.add(abs_idx)
                        if chapter.needs_violence_cleaning:
                            violence_indices.add(abs_idx)
                            
                except Exception as e:
                    if verbose:
                        print(f"  Error rating chunk: {e}")
        
        # Create change blocks for each identified paragraph
        all_flagged = lang_indices | adult_indices | violence_indices
        if not all_flagged:
            print(f"  No paragraphs flagged for cleaning")
            chapter.needs_cleaning = False
            continue
        
        # Build new content with change blocks
        new_content = []
        change_num = 1  # Change number within this chapter
        
        for idx, para in enumerate(paragraphs):
            if idx in all_flagged:
                new_content.append('')
                new_content.append(f'#CHANGE: {chapter.number}.{change_num}')
                new_content.append('#STATUS: pending')
                
                # Set specific cleaning type flag(s)
                if idx in lang_indices:
                    new_content.append('#NEEDS_LANGUAGE_CLEANING')
                if idx in adult_indices:
                    new_content.append('#NEEDS_ADULT_CLEANING')
                if idx in violence_indices:
                    new_content.append('#NEEDS_VIOLENCE_CLEANING')
                
                new_content.append('#ORIGINAL')
                new_content.append(para)
                new_content.append('#CLEANED')
                new_content.append('')  # Empty - to be filled
                new_content.append('#END')
                change_num += 1
                total_changes += 1
            else:
                new_content.append('')
                new_content.append(para)
        
        chapter.content_lines = new_content
        
        stats = []
        if lang_indices:
            stats.append(f"{len(lang_indices)} lang")
        if adult_indices:
            stats.append(f"{len(adult_indices)} adult")
        if violence_indices:
            stats.append(f"{len(violence_indices)} violence")
        print(f"  Created {change_num - 1} change blocks ({', '.join(stats)})")
    
    # Save after identification
    write_bookwash(bw, filepath)
    print(f"\n✓ Saved after identification ({total_changes} change blocks)")
    print()
    
    # === PASS 1: LANGUAGE CLEANING ===
    print("=== PASS 1: LANGUAGE CLEANING ===")
    lang_prompt = build_language_cleaning_prompt(client.language_words)
    lang_cleaned = 0
    
    if client.language_words and lang_prompt:
        # Save language prompt to file
        bw.cleaning_prompt = f"=== LANGUAGE CLEANING PROMPT ===\n{lang_prompt}"
        
        for chapter in bw.chapters:
            # Find change blocks with #NEEDS_LANGUAGE_CLEANING
            for line_idx, line in enumerate(chapter.content_lines):
                if line.startswith('#CHANGE:'):
                    change_id = line.split(':')[1].strip()
                    
                    # Check if this block needs language cleaning
                    needs_lang = False
                    for check_idx in range(line_idx, min(line_idx + 10, len(chapter.content_lines))):
                        if chapter.content_lines[check_idx] == '#NEEDS_LANGUAGE_CLEANING':
                            needs_lang = True
                            break
                        if chapter.content_lines[check_idx] == '#ORIGINAL':
                            break
                    
                    if needs_lang:
                        original = _get_change_original(chapter, change_id)
                        if original.strip():
                            try:
                                # Use focused language prompt
                                cleaned = client._make_request(lang_prompt, original, log_type='cleaning')
                                if cleaned and cleaned.strip() and cleaned != '[BLOCKED_BY_SAFETY_FILTER]':
                                    _set_change_cleaned(chapter, change_id, cleaned.strip())
                                    lang_cleaned += 1
                                else:
                                    # For language, we can try harder - just remove bad words manually
                                    print(f"  ⚠️  Language cleaning failed for {change_id}, keeping original")
                            except Exception as e:
                                print(f"  Error cleaning {change_id}: {e}")
        
        print(f"  Cleaned {lang_cleaned} language blocks")
        write_bookwash(bw, filepath)
        print(f"  ✓ Saved after language pass")
    else:
        print("  (No language words to filter)")
    print()
    
    # === PASS 2: ADULT CONTENT CLEANING ===
    print("=== PASS 2: ADULT CONTENT CLEANING ===")
    adult_prompt = build_adult_cleaning_prompt(target_sexual)
    adult_cleaned = 0
    adult_fallback_used = 0
    
    # Append adult prompt to saved prompts
    if bw.cleaning_prompt:
        bw.cleaning_prompt += f"\n\n=== ADULT CLEANING PROMPT ===\n{adult_prompt}"
    else:
        bw.cleaning_prompt = f"=== ADULT CLEANING PROMPT ===\n{adult_prompt}"
    
    for chapter in bw.chapters:
        for line_idx, line in enumerate(chapter.content_lines):
            if line.startswith('#CHANGE:'):
                change_id = line.split(':')[1].strip()
                
                # Check if this block needs adult cleaning
                needs_adult = False
                for check_idx in range(line_idx, min(line_idx + 10, len(chapter.content_lines))):
                    if chapter.content_lines[check_idx] == '#NEEDS_ADULT_CLEANING':
                        needs_adult = True
                        break
                    if chapter.content_lines[check_idx] == '#ORIGINAL':
                        break
                
                if needs_adult:
                    # Get current cleaned (may have language cleaning already)
                    current_cleaned = _get_change_cleaned(chapter, change_id)
                    text_to_clean = current_cleaned if current_cleaned.strip() else _get_change_original(chapter, change_id)
                    
                    if text_to_clean.strip():
                        try:
                            cleaned = client._make_request(adult_prompt, text_to_clean, log_type='cleaning')
                            
                            if not cleaned or not cleaned.strip() or cleaned == '[BLOCKED_BY_SAFETY_FILTER]':
                                # Use fallback
                                print(f"  ⚠️  Adult cleaning blocked for {change_id}, using fallback")
                                _set_change_cleaned(chapter, change_id, ADULT_FALLBACK)
                                adult_fallback_used += 1
                            else:
                                _set_change_cleaned(chapter, change_id, cleaned.strip())
                            adult_cleaned += 1
                        except Exception as e:
                            print(f"  Error cleaning {change_id}: {e}")
                            _set_change_cleaned(chapter, change_id, ADULT_FALLBACK)
                            adult_fallback_used += 1
    
    print(f"  Cleaned {adult_cleaned} adult blocks ({adult_fallback_used} used fallback)")
    write_bookwash(bw, filepath)
    print(f"  ✓ Saved after adult pass")
    print()
    
    # === PASS 3: VIOLENCE CLEANING ===
    print("=== PASS 3: VIOLENCE CLEANING ===")
    violence_prompt = build_violence_cleaning_prompt(target_violence)
    violence_cleaned = 0
    violence_fallback_used = 0
    
    # Append violence prompt to saved prompts
    bw.cleaning_prompt += f"\n\n=== VIOLENCE CLEANING PROMPT ===\n{violence_prompt}"
    
    for chapter in bw.chapters:
        for line_idx, line in enumerate(chapter.content_lines):
            if line.startswith('#CHANGE:'):
                change_id = line.split(':')[1].strip()
                
                # Check if this block needs violence cleaning
                needs_violence = False
                for check_idx in range(line_idx, min(line_idx + 10, len(chapter.content_lines))):
                    if chapter.content_lines[check_idx] == '#NEEDS_VIOLENCE_CLEANING':
                        needs_violence = True
                        break
                    if chapter.content_lines[check_idx] == '#ORIGINAL':
                        break
                
                if needs_violence:
                    # Get current cleaned (may have previous cleaning)
                    current_cleaned = _get_change_cleaned(chapter, change_id)
                    text_to_clean = current_cleaned if current_cleaned.strip() else _get_change_original(chapter, change_id)
                    
                    if text_to_clean.strip():
                        try:
                            cleaned = client._make_request(violence_prompt, text_to_clean, log_type='cleaning')
                            
                            if not cleaned or not cleaned.strip() or cleaned == '[BLOCKED_BY_SAFETY_FILTER]':
                                # Use fallback
                                print(f"  ⚠️  Violence cleaning blocked for {change_id}, using fallback")
                                _set_change_cleaned(chapter, change_id, VIOLENCE_FALLBACK)
                                violence_fallback_used += 1
                            else:
                                _set_change_cleaned(chapter, change_id, cleaned.strip())
                            violence_cleaned += 1
                        except Exception as e:
                            print(f"  Error cleaning {change_id}: {e}")
                            _set_change_cleaned(chapter, change_id, VIOLENCE_FALLBACK)
                            violence_fallback_used += 1
    
    print(f"  Cleaned {violence_cleaned} violence blocks ({violence_fallback_used} used fallback)")
    
    # Remove change blocks where ORIGINAL == CLEANED (false positives)
    removed = _remove_identical_change_blocks(bw)
    if removed > 0:
        print(f"  🧹 Removed {removed} identical change blocks (false positives)")
    
    # Remove any orphaned cleaning markers that ended up outside change blocks
    orphaned = _remove_orphaned_cleaning_markers(bw)
    if orphaned > 0:
        print(f"  🧹 Removed {orphaned} orphaned cleaning markers")
    
    write_bookwash(bw, filepath)
    print(f"  ✓ Saved after violence pass")
    print()
    
    # === RE-RATING PASS: Verify cleaning worked ===
    print("=== RE-RATING CLEANED CONTENT ===")
    
    # Re-rate chapters using the CLEANED content
    still_exceeds = []
    for i, chapter in enumerate(bw.chapters):
        # Get chapter text with cleaned content substituted
        cleaned_text = chapter.get_text_with_cleaned()
        if len(cleaned_text) > 12000:
            cleaned_text = cleaned_text[:12000] + "\n\n[truncated for rating]"
        
        if not cleaned_text.strip():
            continue
        
        try:
            rating = client.rate_chapter(cleaned_text)
            old_rating_str = f"{chapter.rating.language}/{chapter.rating.sexual}/{chapter.rating.violence}" if chapter.rating else "none"
            chapter.rating = rating  # Update to post-clean rating
            
            # Check if still exceeds targets
            exceeds_adult = RATING_LEVELS.get(rating.sexual, 1) > target_sexual
            exceeds_violence = RATING_LEVELS.get(rating.violence, 1) > target_violence
            
            if exceeds_adult or exceeds_violence:
                still_exceeds.append((chapter.number, rating))
                chapter.needs_cleaning = True
                chapter.needs_adult_cleaning = exceeds_adult
                chapter.needs_violence_cleaning = exceeds_violence
                print(f"  Chapter {chapter.number}: {old_rating_str} → L={rating.language} A={rating.sexual} V={rating.violence} ⚠️  STILL EXCEEDS")
            else:
                chapter.needs_cleaning = False
                chapter.needs_adult_cleaning = False
                chapter.needs_violence_cleaning = False
                print(f"  Chapter {chapter.number}: {old_rating_str} → L={rating.language} A={rating.sexual} V={rating.violence} ✓")
        except Exception as e:
            print(f"  Chapter {chapter.number}: Error re-rating: {e}")
    
    # Reset language cleaning (word-based, always complete after one pass)
    for chapter in bw.chapters:
        chapter.needs_language_cleaning = False
    
    write_bookwash(bw, filepath)
    
    if still_exceeds:
        print(f"\n⚠️  {len(still_exceeds)} chapters still exceed targets after cleaning.")
        print("  These may need manual review or more aggressive prompts.")
        for ch_num, rating in still_exceeds:
            print(f"    - Chapter {ch_num}: A={rating.sexual} V={rating.violence}")
    else:
        print(f"\n✓ All chapters now meet target ratings!")
    
    print()
    print(f"=== CLEANING COMPLETE ===")
    print(f"Total: {total_changes} change blocks")
    print(f"  Language: {lang_cleaned}")
    print(f"  Adult: {adult_cleaned} ({adult_fallback_used} fallback)")
    print(f"  Violence: {violence_cleaned} ({violence_fallback_used} fallback)")
    
    return total_changes


def _get_change_cleaned(chapter, change_id: str) -> str:
    """Get the #CLEANED content for a specific change ID."""
    in_target_change = False
    in_cleaned = False
    cleaned_lines = []
    
    for line in chapter.content_lines:
        if line.startswith('#CHANGE:'):
            cid = line.split(':')[1].strip()
            in_target_change = (cid == change_id)
            in_cleaned = False
        elif line == '#CLEANED' and in_target_change:
            in_cleaned = True
            cleaned_lines = []
        elif line == '#END':
            if in_target_change:
                break
            in_target_change = False
        elif in_cleaned and not line.startswith('#'):
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)


# Old escalation-based cleaning functions removed - now using cmd_clean_passes


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
    parser.add_argument('--clean-passes', action='store_true', 
                       help='Simplified cleaning with separate passes (language, adult, violence)')
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
    
    if not args.rate and not args.identify and not args.fill and not args.clean_passes:
        print("Error: Must specify at least one of --rate, --identify, --fill, or --clean-passes")
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
    
    if args.clean_passes:
        cmd_clean_passes(bw, client, input_path, verbose=args.verbose)
        print()
    
    # Write updated file
    print(f"Saving: {input_path.name}")
    write_bookwash(bw, input_path)
    print("Done!")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
