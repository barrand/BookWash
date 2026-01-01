#!/usr/bin/env python3
"""
BookWash LLM Integration

Three-pass architecture for content moderation:
  Pass A (--rate):     Rate whole chapters, set #RATING and #PENDING_CLEANING
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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable
from zoneinfo import ZoneInfo

# Import language prefilter for regex-based profanity replacement
from language_prefilter import prefilter_language, get_replacement_count

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
# Model to use when PROHIBITED_CONTENT is detected (copyright detection bypass)
PROHIBITED_CONTENT_FALLBACK_MODEL = 'gemini-2.0-flash'
API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'

# Parallel processing configuration
NUM_WORKERS = 5  # Number of parallel workers for rating/cleaning
print_lock = threading.Lock()  # Thread-safe printing
worker_id_lock = threading.Lock()  # Lock for assigning worker IDs
worker_id_counter = 0  # Counter for assigning unique worker IDs
thread_worker_ids = {}  # Map thread ID to worker ID (1-based)

# Common racial slurs for detection (used when "racial slurs" checkbox is enabled)
# This list is used for automated detection - the LLM handles replacement
RACIAL_SLURS_DETECTION = [
    'nigger', 'nigga', 'negro', 'colored',  # Anti-Black
    'chink', 'gook', 'jap', 'zipperhead',    # Anti-Asian
    'wetback', 'spic', 'beaner', 'greaser',  # Anti-Latino
    'kike', 'heeb',                           # Anti-Jewish
    'towelhead', 'raghead', 'camel jockey',  # Anti-Middle Eastern
    'redskin', 'injun', 'squaw',             # Anti-Native American
    'cracker', 'honky',                       # Anti-White
    'wop', 'dago', 'polack', 'mick',         # Anti-European ethnic
]

def thread_safe_print(*args, **kwargs):
    """Thread-safe print function for parallel workers."""
    with print_lock:
        print(*args, **kwargs)

def get_worker_id() -> int:
    """Get or assign a worker ID (1-based) for the current thread."""
    global worker_id_counter
    thread_id = threading.current_thread().ident
    
    with worker_id_lock:
        if thread_id not in thread_worker_ids:
            worker_id_counter += 1
            thread_worker_ids[thread_id] = worker_id_counter
        return thread_worker_ids[thread_id]

def reset_worker_ids():
    """Reset worker ID tracking for a new parallel operation."""
    global worker_id_counter, thread_worker_ids
    with worker_id_lock:
        worker_id_counter = 0
        thread_worker_ids.clear()

def _get_mountain_timestamp() -> str:
    """Get current timestamp in Mountain Time with readable format.
    
    Returns format like: 12/20/24 09:45pm MT
    """
    mt = ZoneInfo('America/Denver')
    now = datetime.now(mt)
    # Format: MM/DD/YY HH:MMam/pm MT
    formatted = now.strftime('%m/%d/%y %I:%M%p MT').lower()
    # Capitalize MT back
    return formatted[:-2] + 'MT'

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
    language: str = 'G'  # Legacy field for display (derived from language_detected)
    language_detected: bool = False  # True if LLM detected target language words
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
    section_label: Optional[str] = None  # Label from TOC (e.g., "Chapter 1", "Copyright")
    title: Optional[str] = None
    rating: Optional[ChapterRating] = None
    # Cleaning state: None = not evaluated, True = has change blocks needing work, False = cleaning complete
    pending_cleaning: Optional[bool] = None
    # Internal tracking for what types of content to clean (set during rating)
    needs_language_cleaning: bool = False
    needs_adult_cleaning: bool = False
    needs_violence_cleaning: bool = False
    content_lines: list = field(default_factory=list)  # Raw lines including any existing changes
    
    @property
    def display_name(self) -> str:
        """Get a human-readable name for the chapter for display in logs."""
        if self.section_label:
            return self.section_label
        elif self.title:
            return self.title
        else:
            return f"Chapter {self.number}"
    
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
    chapter_rating_prompt: Optional[str] = None  # The Gemini chapter rating prompt (Pass A)
    paragraph_identification_prompt: Optional[str] = None  # The Gemini paragraph identification prompt for analysis
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
    chapter_count = 0  # Track chapter count for #SECTION: format
    
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
            elif line.startswith('#SECTION:'):
                in_header = False
                # Fall through to chapter parsing
            else:
                bw.header_lines.append(line)
                i += 1
                continue
        
        # Chapter parsing
        if line.startswith('#SECTION:'):
            if current_chapter is not None:
                bw.chapters.append(current_chapter)
            
            chapter_count += 1
            section_label = line[9:].strip()
            current_chapter = Chapter(number=chapter_count, section_label=section_label)
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
            elif line.startswith('#PENDING_CLEANING:'):
                val = line[18:].strip().lower()
                current_chapter.pending_cleaning = val == 'true'
            # Legacy support for old format
            elif line.startswith('#NEEDS_CLEANING:'):
                val = line[16:].strip().lower()
                current_chapter.pending_cleaning = val == 'true'
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
    
    # Apply language prefilter to all chapters - regex replacement for unambiguous profanity
    # This runs ONCE at load time, before any LLM processing
    total_replacements = 0
    for chapter in bw.chapters:
        new_lines = []
        for line in chapter.content_lines:
            # Only prefilter content lines, not metadata/markup lines
            if line.startswith('#'):
                new_lines.append(line)
            else:
                filtered = prefilter_language(line)
                if filtered != line:
                    total_replacements += 1
                new_lines.append(filtered)
        chapter.content_lines = new_lines
    
    if total_replacements > 0:
        print(f"✅ Prefilter: {total_replacements} auto-replacements (sh*t→crud, f*ck→screw, etc.)", file=sys.stderr)
    
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
        now = _get_mountain_timestamp()
        lines.insert(insert_idx, f'#MODIFIED: {now}')
        
        offset = 1
        if bw.settings:
            settings_parts = [f'{k}={v}' for k, v in bw.settings.items()]
            lines.insert(insert_idx + offset, f'#SETTINGS: {" ".join(settings_parts)}')
            offset += 1
        
        # Write chapter rating prompt if available (for analysis - Pass A)
        if bw.chapter_rating_prompt:
            lines.insert(insert_idx + offset, '#CHAPTER_RATING_PROMPT_START')
            offset += 1
            # Split prompt into lines and add each with # prefix
            prompt_lines = bw.chapter_rating_prompt.split('\n')
            for prompt_line in prompt_lines:
                lines.insert(insert_idx + offset, f'# {prompt_line}')
                offset += 1
            lines.insert(insert_idx + offset, '#CHAPTER_RATING_PROMPT_END')
            offset += 1
        
        # Write paragraph identification prompt if available (for analysis)
        if bw.paragraph_identification_prompt:
            lines.insert(insert_idx + offset, '#PARAGRAPH_IDENTIFICATION_PROMPT_START')
            offset += 1
            # Split prompt into lines and add each with # prefix
            prompt_lines = bw.paragraph_identification_prompt.split('\n')
            for prompt_line in prompt_lines:
                lines.insert(insert_idx + offset, f'# {prompt_line}')
                offset += 1
            lines.insert(insert_idx + offset, '#PARAGRAPH_IDENTIFICATION_PROMPT_END')
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
        # Use section_label if available (new format), otherwise fall back to number
        if chapter.section_label:
            lines.append(f'#SECTION: {chapter.section_label}')
        else:
            lines.append(f'#SECTION: Chapter {chapter.number}')
        
        if chapter.title and chapter.title != chapter.section_label:
            lines.append(f'#TITLE: {chapter.title}')
        
        if chapter.rating:
            lines.append(f'#RATING: language={chapter.rating.language} sexual={chapter.rating.sexual} violence={chapter.rating.violence}')
        
        # Only write PENDING_CLEANING if the chapter has change blocks
        # None = never evaluated, True = has unfilled changes, False = cleaning complete
        if chapter.pending_cleaning is not None:
            lines.append(f'#PENDING_CLEANING: {"true" if chapter.pending_cleaning else "false"}')
        
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
    if chapter.section_label:
        lines.append(f'#SECTION: {chapter.section_label}')
    else:
        lines.append(f'#SECTION: Chapter {chapter.number}')
    
    if chapter.title and chapter.title != chapter.section_label:
        lines.append(f'#TITLE: {chapter.title}')
    
    if chapter.rating:
        lines.append(f'#RATING: language={chapter.rating.language} sexual={chapter.rating.sexual} violence={chapter.rating.violence}')
    
    # Only write PENDING_CLEANING if the chapter has change blocks
    if chapter.pending_cleaning is not None:
        lines.append(f'#PENDING_CLEANING: {"true" if chapter.pending_cleaning else "false"}')
    
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
        
        if line.startswith('#SECTION:'):
            section_label = line.split(':', 1)[1].strip()
            chapter = Chapter(number=1, section_label=section_label)
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
            # Legacy format support - convert to pending_cleaning
            val = line.split(':')[1].strip().lower()
            chapter.pending_cleaning = (val == 'true')
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
    
    def clone(self):
        """Create a thread-safe copy of this client for parallel processing."""
        return GeminiClient(
            api_key=self.api_key,
            model=self.primary_model,
            language_words=self.language_words.copy() if self.language_words else None,
            filter_types=self.filter_types
        )
    
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
                        # Check if it's PROHIBITED_CONTENT (copyright detection)
                        if block_reason == 'PROHIBITED_CONTENT' and self.current_model != PROHIBITED_CONTENT_FALLBACK_MODEL:
                            print(f"  ⚠️  {block_reason} detected, retrying with {PROHIBITED_CONTENT_FALLBACK_MODEL}...")
                            # Temporarily switch to fallback model and retry
                            original_model = self.current_model
                            self.current_model = PROHIBITED_CONTENT_FALLBACK_MODEL
                            try:
                                result = self._make_request(prompt, text, max_retries=3, log_type=log_type)
                                return result
                            finally:
                                self.current_model = original_model
                        
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
    
    def rate_chapter(self, text: str, language_words: list = None) -> ChapterRating:
        """Rate a chapter for content levels.
        
        Args:
            text: Chapter text to rate
            language_words: Optional list of words for fuzzy language detection
        """
        prompt = build_chapter_rating_prompt(language_words)
        
        response = self._make_request(prompt, text, log_type='rating')
        
        # If content was blocked by safety filter, assume worst case
        if response == '[BLOCKED_BY_SAFETY_FILTER]':
            print("  ⚠️  Rating blocked - assuming worst case")
            return ChapterRating(language='X', language_detected=True, sexual='X', violence='X')
        
        rating = ChapterRating()
        for line in response.strip().split('\n'):
            line = line.strip()
            if line.startswith('LANGUAGE:'):
                val = line.replace('LANGUAGE:', '').strip().upper()
                # New format: YES/NO for language detection
                if val in ['YES', 'Y']:
                    rating.language_detected = True
                    rating.language = 'DETECTED'  # For display in file
                elif val in ['NO', 'N']:
                    rating.language_detected = False
                    rating.language = 'CLEAN'
                elif val in RATING_LEVELS:
                    # Legacy format fallback (G/PG/etc) - treat PG-13+ as detected
                    rating.language = val
                    rating.language_detected = RATING_LEVELS.get(val, 1) >= 3
            elif line.startswith('SEXUAL:'):
                val = line.replace('SEXUAL:', '').strip().upper()
                if val in RATING_LEVELS:
                    rating.sexual = val
            elif line.startswith('VIOLENCE:'):
                val = line.replace('VIOLENCE:', '').strip().upper()
                if val in RATING_LEVELS:
                    rating.violence = val
        
        return rating
    
    def identify_paragraphs_to_clean(self, paragraphs: list, target_sexual: int, target_violence: int,
                    language_words: list = None) -> list:
        """Identify which paragraphs in a chunk need cleaning.
        
        Args:
            paragraphs: List of paragraph strings (typically 2-3)
            target_sexual: Target sexual content level  
            target_violence: Target violence level
            language_words: Optional list of specific words to filter (from checkboxes)
            
        Returns:
            List of paragraph indices (0-based) that exceed target ratings
        """
        sexual_name = LEVEL_TO_RATING.get(target_sexual, 'PG')
        violence_name = LEVEL_TO_RATING.get(target_violence, 'X')
        
        # Build dynamic language section based on user's word list
        if language_words:
            words_str = ', '.join(language_words)
            language_section = f"""LANGUAGE CONTENT DETECTION:
The user wants to filter these specific words: {words_str}
Flag any paragraph containing these words OR any similarly offensive profanity/slurs.

Include variations, misspellings, and words of similar offensiveness level.
For example, if 'shit' is listed, also flag 'sh*t', 'shite', 'shitty', 'shitshow' etc."""
        else:
            # No language checkboxes selected - skip language detection entirely
            language_section = """LANGUAGE CONTENT: No language filtering requested - do not flag paragraphs for language."""
        
        # Number each paragraph for reference
        numbered = []
        for i, p in enumerate(paragraphs):
            numbered.append(f"[{i+1}] {p}")
        text = '\n\n'.join(numbered)
        
        prompt = f"""Analyze each numbered paragraph and identify which ones contain content that exceeds the target ratings.

⚠️ CRITICAL: When in doubt, FLAG IT. It is much better to flag a paragraph that might be fine than to miss one that needs cleaning. False positives are acceptable; false negatives are not.

RATING SCALE DEFINITIONS:

{language_section}

SEXUAL CONTENT - Use MPAA film rating standards:
- G: No romance. Content suitable for young children.
- PG: Light romance (hand-holding, quick innocent kiss). Nothing that would make a parent uncomfortable.
- PG-13: Passionate kissing, implied intimacy, fade-to-black. The camera cuts away before anything explicit.
- R: Sexual content that would get a film an R rating. Descriptive intimate scenes, even if poetic/metaphorical.
- NC-17/X: Explicit, graphic sexual content.

CRITICAL: Authors often describe sex through metaphor, poetry, or fragmented prose rather than explicit terms. 
If you're reading a scene and thinking "this is clearly describing sex, just artistically" → rate it R.
Poetic language does not reduce the rating. A sex scene written beautifully is still a sex scene.

VIOLENCE:
- G: No physical violence (arguments only)
- PG: Mild action, non-detailed scuffles, no blood
- PG-13: Combat, injuries, some blood, weapon use without gore detail
- R: Graphic injury detail, notable gore, intense sustained violence
- X: Extreme gore/torture, sadistic detail

TARGET RATINGS (content must be at or BELOW these levels):
- Language: (based on word list above)
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
        
        # DEBUG: Log what we're sending
        if os.environ.get('BOOKWASH_DEBUG_IDENTIFY'):
            print(f"\n{'='*60}")
            print(f"DEBUG IDENTIFY: Sending {len(paragraphs)} paragraphs:")
            print(f"{'='*60}")
            print(text)
            print(f"{'='*60}")
        
        response = self._make_request(prompt, text, log_type='rating')
        
        # DEBUG: Log what the LLM responded
        if os.environ.get('BOOKWASH_DEBUG_IDENTIFY'):
            print(f"DEBUG IDENTIFY: LLM response: '{response}'")
            print(f"{'='*60}\n")
        
        # If content was blocked, assume ALL paragraphs need cleaning
        if response == '[BLOCKED_BY_SAFETY_FILTER]':
            print(f"    ⚠️  Chunk rating blocked - flagging all {len(paragraphs)} paragraphs")
            return list(range(len(paragraphs)))
        
        # Parse response for paragraph numbers
        flagged_indices = []
        for line in response.strip().split('\n'):
            line = line.strip()
            if line.upper() == 'NONE':
                return []
            # Extract number from line (handle formats like "1", "[1]", "1.", "Paragraph 1", etc.)
            match = re.search(r'\b(\d+)\b', line)
            if match:
                idx = int(match.group(1)) - 1  # Convert to 0-based
                if 0 <= idx < len(paragraphs):
                    flagged_indices.append(idx)
        
        return flagged_indices
    
    def rate_paragraphs(self, paragraphs: list, target_sexual: int, target_violence: int,
                        language_words: list = None) -> list:
        """Rate each paragraph and return MPAA ratings for diagnostic purposes.
        
        Args:
            paragraphs: List of paragraph strings
            target_sexual: Target sexual content level  
            target_violence: Target violence level
            language_words: Optional list of specific words to filter (from checkboxes)
            
        Returns:
            List of dicts, one per paragraph:
            {
                'sexual': 'G'|'PG'|'PG-13'|'R'|'X',
                'violence': 'G'|'PG'|'PG-13'|'R'|'X',
                'language': True|False,  # Whether language words detected
                'exceeds_sexual': bool,
                'exceeds_violence': bool,
                'exceeds_language': bool
            }
        """
        sexual_name = LEVEL_TO_RATING.get(target_sexual, 'PG')
        violence_name = LEVEL_TO_RATING.get(target_violence, 'X')
        
        # Build dynamic language section based on user's word list
        if language_words:
            words_str = ', '.join(language_words)
            language_section = f"""LANGUAGE CONTENT DETECTION:
The user wants to filter these specific words: {words_str}
Flag YES for any paragraph containing these words OR any similarly offensive profanity/slurs.
Include variations, misspellings, and words of similar offensiveness level."""
        else:
            language_section = """LANGUAGE CONTENT: No language filtering requested - always report NO."""
        
        # Number each paragraph for reference
        numbered = []
        for i, p in enumerate(paragraphs):
            numbered.append(f"[{i+1}] {p}")
        text = '\n\n'.join(numbered)
        
        prompt = f"""Rate each numbered paragraph for content. Provide MPAA-style ratings.

{language_section}

SEXUAL CONTENT - Use MPAA film rating standards:
- G: No romance. Content suitable for young children.
- PG: Light romance (hand-holding, quick innocent kiss).
- PG-13: Passionate kissing, implied intimacy, fade-to-black.
- R: Sexual content that would get a film an R rating. Descriptive intimate scenes, even if poetic/metaphorical.
- X: Explicit, graphic sexual content.

CRITICAL: Authors often describe sex through metaphor, poetry, or fragmented prose.
If it's clearly describing sex artistically → rate it R.
Poetic language does not reduce the rating.

VIOLENCE:
- G: No physical violence (arguments only)
- PG: Mild action, non-detailed scuffles, no blood
- PG-13: Combat, injuries, some blood, weapon use
- R: Graphic injury detail, notable gore, intense sustained violence
- X: Extreme gore/torture, sadistic detail

TARGET RATINGS (for reference - still rate honestly):
- Language: {('filter words: ' + ', '.join(language_words)) if language_words else 'none'}
- Sexual: {sexual_name}
- Violence: {violence_name}

For EACH paragraph, respond with its number and ratings on ONE line.
Format: [number] LANG=[YES/NO] SEXUAL=[rating] VIOLENCE=[rating]

Example response:
1 LANG=NO SEXUAL=G VIOLENCE=G
2 LANG=YES SEXUAL=PG-13 VIOLENCE=G
3 LANG=NO SEXUAL=R VIOLENCE=PG

Text to analyze:
"""
        
        response = self._make_request(prompt, text, log_type='rating')
        
        # Initialize results with defaults
        results = []
        for _ in paragraphs:
            results.append({
                'sexual': 'G',
                'violence': 'G', 
                'language': False,
                'exceeds_sexual': False,
                'exceeds_violence': False,
                'exceeds_language': False
            })
        
        # If content was blocked, assume worst case
        if response == '[BLOCKED_BY_SAFETY_FILTER]':
            print(f"    ⚠️  Chunk rating blocked - assuming X for all")
            for r in results:
                r['sexual'] = 'X'
                r['violence'] = 'X'
                r['language'] = True
                r['exceeds_sexual'] = True
                r['exceeds_violence'] = True
                r['exceeds_language'] = bool(language_words)
            return results
        
        # Parse response
        for line in response.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Extract paragraph number
            num_match = re.match(r'\[?(\d+)\]?', line)
            if not num_match:
                continue
            idx = int(num_match.group(1)) - 1  # Convert to 0-based
            if idx < 0 or idx >= len(paragraphs):
                continue
            
            # Extract ratings
            lang_match = re.search(r'LANG(?:UAGE)?=\s*(YES|NO)', line, re.IGNORECASE)
            sexual_match = re.search(r'SEXUAL=\s*(G|PG-13|PG|R|X)', line, re.IGNORECASE)
            violence_match = re.search(r'VIOLENCE=\s*(G|PG-13|PG|R|X)', line, re.IGNORECASE)
            
            if lang_match:
                results[idx]['language'] = lang_match.group(1).upper() == 'YES'
            if sexual_match:
                rating = sexual_match.group(1).upper()
                results[idx]['sexual'] = rating
                results[idx]['exceeds_sexual'] = RATING_LEVELS.get(rating, 1) > target_sexual
            if violence_match:
                rating = violence_match.group(1).upper()
                results[idx]['violence'] = rating
                results[idx]['exceeds_violence'] = RATING_LEVELS.get(rating, 1) > target_violence
            
            # Language exceeds if detected and we have words to filter
            results[idx]['exceeds_language'] = results[idx]['language'] and bool(language_words)
        
        return results
    
    def clean_change_block(self, paragraph: str, target_sexual: int, target_violence: int,
                        aggression: int = 1, strategy: str = 'rephrase') -> tuple[str, str]:
        """Clean a change block's content according to target levels and strategy.
        
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
3. NEVER use [REDACTED], [REMOVED], [CENSORED], or any bracketed placeholder - ALWAYS replace with actual substitute words or remove the content entirely
4. Preserve ALL whitespace EXACTLY - same line breaks, same paragraph breaks. If the original has a line break mid-sentence, keep it there.
5. Keep formatting, punctuation, and quotation marks intact

⚠️ FORMATTING TAGS - CRITICAL ⚠️
6. DO NOT ADD [B], [I], or any formatting tags that are not in the original text!
   - If the original word has NO tags around it, the replacement must have NO tags
   - WRONG: "hell" → "[B]heck[/B]" (added tags that weren't there!)
   - CORRECT: "hell" → "heck" (no tags added)
   - Only PRESERVE existing tags: "[I]damn[/I]" → "[I]darn[/I]" (kept existing tags)

7. CHAPTER TITLES: The first line may be a chapter title. If it contains profanity, CLEAN it but keep it as a short title (not a paragraph). Example: "The Sh*t Show" → "The Disaster"
8. DO NOT simplify vocabulary - keep sophisticated words (onerous, nascent, snarled, etc). Only remove inappropriate CONTENT, not complex language.
9. Narrative descriptions of profanity are ALLOWED at all language levels:
   ✅ KEEP: "He snarled a curse" (describes action, doesn't show word)
   ✅ KEEP: "She muttered an oath" (narrative description)
   ✅ KEEP: "A string of profanity" (tells, doesn't show)
   ❌ REMOVE: "He shouted, 'Damn you!'" (shows actual profanity)
   This is storytelling technique, not actual profanity usage.
10. If the paragraph already meets target levels, return it EXACTLY as-is. Do NOT make unnecessary changes to vocabulary, structure, wording, OR LINE BREAKS."""
        
        # Adjust rules based on aggression for strict targets (only for the content types being filtered)
        if aggression >= 2:
            if 'sexual' in filters_enabled and sexual <= 2:
                prompt += """
10. For G/PG sexual targets: AGGRESSIVELY remove suggestive content - do not try to preserve it
11. Replace problematic paragraphs with simple neutral summaries
12. Remove all body-focused language, physical descriptions of attraction
13. Cut rather than rephrase when content is borderline"""
            else:
                prompt += """
10. Use minimal replacements - prefer simple phrases over creative elaboration
11. DO NOT add new plot elements or details not in the original
12. Preserve emotional tone and narrative voice"""
        else:
            prompt += """
10. Use minimal replacements - prefer simple phrases over creative elaboration
11. DO NOT add new plot elements or details not in the original
12. Preserve emotional tone and narrative voice"""
        
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
1. REMOVE all instances of the target words when used as PROFANITY or INSULTS
2. KEEP words used in their LITERAL/PROPER meaning (see exceptions below)
3. REMOVE all variants and forms of these words when used as profanity or insults:
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

⚠️ EXCEPTION - LEGITIMATE/PROPER USES (do NOT remove these):
- "bastard" meaning illegitimate child → NEVER REPLACE when referring to illegitimate birth status:
  • "born a bastard", "the king's bastard", "his bastard", "[name]'s bastard", "fathered a bastard"
  • "I'm a bastard", "I'm his bastard", "You're a bastard" (when discussing parentage)
  • "the bastard son", "a bastard child", "Gavin's bastard", "Kip was Gavin's bastard"
  • Context clue: if discussing parentage, lineage, birth status, or social shame of illegitimacy → KEEP
- "bitch" meaning female dog → KEEP "the bitch and her puppies", "a hunting bitch"
- "ass" meaning donkey → KEEP "rode an ass", "stubborn as an ass"
- "damn" meaning to condemn → KEEP "damn his soul", "damned to hell" (religious condemnation) or as a physical construction for blocking water
- "hell" as a place → KEEP "descended into hell", "the fires of hell"
- "prick" meaning to pierce → KEEP "pricked her finger", "prick of a needle"
- "cock" meaning rooster → KEEP "the cock crowed", "cockfight", "cockcrow"

CONTEXT-AWARE FILTERING:
- Narrative descriptions like "he cursed" or "snarled a curse" should be KEPT (they describe action without showing the word)
- Only remove when the actual profane word is shown in dialogue or narration
- Consider usage context: emphasis vs. actual cursing
- Religious phrases used genuinely (prayer, worship) may be kept, but blasphemous usage must be removed
- When a word has BOTH a profane and literal meaning, use context to determine which is intended

EXAMPLES:
❌ "What the hell is going on?" → ✅ "What in the world is going on?"
❌ "This is bullshit!" → ✅ "This is ridiculous!"
❌ "Fuck this!" → ✅ "Forget this!"
❌ "You are an asshole!" → ✅ "You are a jerk!"
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

SEXUAL CONTENT FILTERING (Target: {sexual_name}):

Think like an MPAA rating board. Edit content so it would fit in a {sexual_name}-rated film.
If content would get a higher rating than {sexual_name} → REMOVE or REWRITE it.
Poetic/metaphorical sex is still sex - clean it the same way."""
            
            if sexual >= 4:  # R or Unrated
                prompt += """
- Almost everything acceptable. Only remove NC-17/explicit pornographic content."""
            elif aggression >= 2:
                prompt += """
- BE AGGRESSIVE: When in doubt, remove it. Replace with brief neutral summaries if needed."""
        
        # Only include violence filtering section if violence is being filtered
        if 'violence' in filters_enabled:
            prompt += f"""

VIOLENCE FILTERING (Target: {violence_name}):

Think like an MPAA rating board. Edit content so it would fit in a {violence_name}-rated film.
If content would get a higher rating than {violence_name} → REMOVE or REWRITE it."""
            
            if violence >= 4:  # R or Unrated
                prompt += """
- Almost everything acceptable. Only remove extreme torture-porn or sadistic content."""
            elif aggression >= 2:
                prompt += """
- BE AGGRESSIVE: When in doubt, remove it. Summarize violent events briefly if needed."""
        
        prompt += """

FINAL REMINDER: Do NOT add [B], [I], or any formatting tags. Only keep tags that already exist in the original.

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
    """Get list of change IDs that have status 'pending' and empty #CLEANED sections.
    
    Change blocks with status 'ok' are skipped (they don't need cleaning).
    """
    unfilled = []
    current_change_id = None
    current_status = None
    in_cleaned = False
    cleaned_content = []
    
    for line in chapter.content_lines:
        if line.startswith('#CHANGE:'):
            # Save previous change if it was pending with empty cleaned
            if current_change_id and current_status == 'pending' and in_cleaned and not any(c.strip() for c in cleaned_content):
                unfilled.append(current_change_id)
            # Start new change
            current_change_id = line.split(':')[1].strip()
            current_status = None
            in_cleaned = False
            cleaned_content = []
        elif line.startswith('#STATUS:'):
            current_status = line.split(':')[1].strip().lower()
        elif line == '#CLEANED':
            in_cleaned = True
            cleaned_content = []
        elif line == '#END':
            # Check if this change was pending with empty cleaned
            if current_change_id and current_status == 'pending' and in_cleaned and not any(c.strip() for c in cleaned_content):
                unfilled.append(current_change_id)
            current_change_id = None
            current_status = None
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

def build_chapter_rating_prompt(language_words: list = None) -> str:
    """Build the prompt used to rate chapters for content levels (Pass A).
    
    Args:
        language_words: List of specific words to detect (from user checkboxes).
                       If provided, language detection uses fuzzy matching.
                       If None/empty, language detection is skipped.
    """
    # Build dynamic language section based on user's word list
    if language_words:
        words_str = ', '.join(language_words)
        language_section = f"""1. LANGUAGE (profanity, offensive words)
   The user wants to detect these specific words: {words_str}
   
   Look for these words OR any similarly offensive profanity/slurs:
   - Include variations: shit → sh*t, shite, shitty
   - Include misspellings: fuck → fuk, fuuck
   - Include compounds: bullshit, motherfucker, goddamn
   - Include similar severity: if 'bitch' is listed, also detect 'slut', 'son of a bitch'
   
   ⚠️ EXCEPTION - LEGITIMATE/PROPER USES (do NOT flag these):
   - "bastard" meaning illegitimate child - NEVER FLAG when referring to illegitimate birth:
     • "born a bastard", "the king's bastard", "his bastard", "[name]'s bastard", "fathered a bastard"
     • "I'm a bastard", "I'm his bastard", "You're a bastard" (when discussing parentage)
     • "the bastard son", "a bastard child", "Gavin's bastard", "Kip was Gavin's bastard"
     • Context clue: if discussing parentage, lineage, birth status, or social shame of illegitimacy → DO NOT FLAG
   - "bitch" meaning female dog (e.g., "the bitch and her puppies", "a hunting bitch")
   - "ass" meaning donkey (e.g., "rode an ass", "stubborn as an ass")
   - "damn" meaning to condemn (e.g., "damn his soul", "damned to hell" in religious context), or physical construction for retaining water (e.g., "the damn held back the river")
   - "hell" as a place (e.g., "descended into hell", "the fires of hell")
   - "prick" meaning to pierce (e.g., "pricked her finger", "prick of a needle")
   - "cock" meaning rooster (e.g., "the cock crowed", "cockfight")
   
   Only flag words used as profanity, insults, or crude slang - NOT their literal meanings.
   
   Respond with YES if ANY profane uses are found, NO if the text is clean."""
        language_response = "LANGUAGE: [YES or NO]"
    else:
        language_section = """1. LANGUAGE
   No language filtering requested - respond with NO."""
        language_response = "LANGUAGE: NO"
    
    return f"""Analyze the following text and rate it for content.

Categories:

{language_section}

2. SEXUAL CONTENT - Use MPAA film rating standards:
   - G: No romance. Content suitable for young children.
   - PG: Light romance (hand-holding, quick innocent kiss). Nothing that would make a parent uncomfortable.
   - PG-13: Passionate kissing, implied intimacy, fade-to-black. The camera cuts away before anything explicit.
   - R: Sexual content that would get a film an R rating. Descriptive intimate scenes, even if poetic/metaphorical.
   - X: Explicit, graphic sexual content.

   CRITICAL: Authors often describe sex through metaphor, poetry, or fragmented prose.
   If it's clearly describing sex artistically → rate it R.
   Poetic language does not reduce the rating.

3. VIOLENCE - Use MPAA film rating standards:
   - G: No physical violence (arguments only)
   - PG: Mild action, brief scuffles, no blood
   - PG-13: Combat, injuries, some blood, weapon use
   - R: Graphic injury detail, notable gore, intense violence
   - X: Extreme gore/torture, sadistic detail

Respond in EXACTLY this format (one rating per line):
{language_response}
SEXUAL: [G, PG, PG-13, R, or X]
VIOLENCE: [G, PG, PG-13, R, or X]

Text to analyze:"""


def build_paragraph_identification_prompt(language_words: list, target_sexual: int, target_violence: int) -> str:
    """Build the prompt used to identify paragraphs needing cleaning.
    
    This is a template showing what the LLM sees when identifying paragraphs.
    """
    sexual_name = LEVEL_TO_RATING.get(target_sexual, 'PG')
    violence_name = LEVEL_TO_RATING.get(target_violence, 'X')
    
    # Build dynamic language section based on user's word list
    if language_words:
        words_str = ', '.join(language_words)
        language_section = f"""LANGUAGE CONTENT DETECTION:
The user wants to filter these specific words: {words_str}
Flag any paragraph containing these words OR any similarly offensive profanity/slurs.

Include variations, misspellings, and words of similar offensiveness level.
For example, if 'shit' is listed, also flag 'sh*t', 'shite', 'crap', etc."""
    else:
        # No language checkboxes selected - skip language detection entirely
        language_section = """LANGUAGE CONTENT: No language filtering requested - do not flag paragraphs for language."""

    prompt = f"""Analyze each numbered paragraph and identify which ones contain content that exceeds the target ratings.

⚠️ CRITICAL: When in doubt, FLAG IT. It is much better to flag a paragraph that might be fine than to miss one that needs cleaning. False positives are acceptable; false negatives are not.

RATING SCALE DEFINITIONS:

{language_section}

SEXUAL CONTENT - Use MPAA film rating standards:
- G: No romance. Content suitable for young children.
- PG: Light romance (hand-holding, quick innocent kiss). Nothing that would make a parent uncomfortable.
- PG-13: Passionate kissing, implied intimacy, fade-to-black. The camera cuts away before anything explicit.
- R: Sexual content that would get a film an R rating. Descriptive intimate scenes, even if poetic/metaphorical.
- NC-17/X: Explicit, graphic sexual content.

CRITICAL: Authors often describe sex through metaphor, poetry, or fragmented prose rather than explicit terms. 
If you're reading a scene and thinking "this is clearly describing sex, just artistically" → rate it R.
Poetic language does not reduce the rating. A sex scene written beautifully is still a sex scene.

VIOLENCE:
- G: No physical violence (arguments only)
- PG: Mild action, non-detailed scuffles, no blood
- PG-13: Combat, injuries, some blood, weapon use without gore detail
- R: Graphic injury detail, notable gore, intense sustained violence
- X: Extreme gore/torture, sadistic detail

TARGET RATINGS (content must be at or BELOW these levels):
- Language: (based on word list above)
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
[Paragraphs are numbered [1], [2], etc. and sent in chunks of 8]"""
    
    return prompt


def build_language_cleaning_prompt(language_words: list) -> str:
    """Build a focused prompt for language-only cleaning.
    
    This is word-list based, not level-based. We categorize the words
    to determine severity and provide context-appropriate replacements.
    
    Special handling for "racial slurs" - this is a meta-option that instructs
    the LLM to identify and replace all racial slurs, not just specific words.
    """
    if not language_words:
        return ""
    
    # Check for racial slurs meta-option
    include_racial_slurs = 'racial slurs' in [w.lower() for w in language_words]
    
    # Filter out the meta-option from the regular word list
    regular_words = [w for w in language_words if w.lower() != 'racial slurs']
    
    # Categorize words by severity to give better replacement guidance
    words_lower = [w.lower() for w in regular_words]
    
    mild_words = [w for w in regular_words if w.lower() in ['darn', 'gosh', 'heck', 'gee', 'jeez', 'dang']]
    moderate_words = [w for w in regular_words if w.lower() in ['damn', 'hell', 'crap', 'ass', 'piss', 'bummer']]
    strong_words = [w for w in regular_words if w.lower() in ['shit', 'bitch', 'bastard', 'asshole', 'bullshit']]
    severe_words = [w for w in regular_words if w.lower() in ['fuck', 'fucking', 'motherfucker', 'cunt']]
    blasphemous = [w for w in regular_words if w.lower() in ['goddamn', 'jesus christ', 'oh my god']]
    
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
   - "goddamn" → "goodness" or remove
   - "Jesus Christ!" (as expletive) → "Good grief!" or remove
   - "Oh my god!" (as expletive) → "Oh my!" or "Oh my goodness!"
   - Keep genuine religious usage (prayer, worship) unchanged""")
    
    if include_racial_slurs:
        replacement_rules.append("""RACIAL SLURS AND EPITHETS:
   - Identify and replace ALL racial slurs, ethnic slurs, and derogatory terms for any racial/ethnic group
   - This includes the n-word and all its variations, as well as slurs for any ethnicity
   - Replace with contextually appropriate alternatives:
     - For the n-word referring to a person: use "man", "person", "friend", or the character's name
     - For the n-word as a derogatory term: remove the sentence or rephrase without the slur
     - "n****r Jim" → "Jim" (just use the name)
     - Preserve the character's identity and the story's meaning while removing the slur
   - Historical/literary context does NOT justify keeping slurs - replace them all
   - Keep the narrative intact - only remove the slurs themselves, not plot-relevant content""")
    
    replacement_section = "\n\n".join(replacement_rules) if replacement_rules else "Replace with appropriate neutral alternatives."
    
    # Build the words section
    words_section = ""
    if regular_words:
        words_section = f"SPECIFIC WORDS TO REMOVE: {', '.join(regular_words)}\n\n"
    if include_racial_slurs:
        words_section += "ALSO REMOVE: All racial slurs, ethnic slurs, and derogatory terms for any race/ethnicity\n\n"
    
    if not words_section:
        return ""  # Nothing to clean
    
    return f"""You are cleaning offensive language from a book. Your task is to replace specific words and slurs.

{words_section}CRITICAL RULES:
1. Return ONLY the cleaned sentence - no explanations, no commentary
2. Preserve ALL whitespace EXACTLY - same line breaks in the same positions. If a line break occurs mid-sentence, keep it there.
3. DO NOT change anything else - keep all other content identical
4. Narrative descriptions like "he cursed" or "she swore" are ALLOWED - only remove actual offensive words

⚠️ FORMATTING TAGS - CRITICAL ⚠️
5. DO NOT ADD [B], [I], or any formatting tags that are not in the original text!
   - If the original word has NO tags around it, the replacement must have NO tags
   - WRONG: "hell" → "[B]heck[/B]" (added tags that weren't there!)
   - CORRECT: "hell" → "heck" (no tags added)
   - WRONG: "son of a bitch" → "[B]scoundrel[/B]" (added tags!)
   - CORRECT: "son of a bitch" → "scoundrel" (no tags)
   - Only PRESERVE existing tags: "[I]damn[/I]" → "[I]darn[/I]" (kept existing tags)

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
    
    Uses MPAA rating standards - trusts LLM knowledge rather than prescriptive lists.
    """
    rating_name = LEVEL_TO_RATING.get(target_sexual, 'PG')
    
    if target_sexual >= 4:  # R or Unrated - no filtering needed
        return """You are reviewing content. The target allows ALL adult content.

NO FILTERING REQUIRED - Return the text exactly as-is.

Text to return unchanged:
"""
    
    return f"""You are cleaning romantic/sensual content to achieve a {rating_name} rating.

Think like an MPAA movie rating board. Your job is to edit this text so it would fit in a {rating_name}-rated film.

THE QUESTION: If this scene were in a movie, would it get a {rating_name} rating or higher?
- If it would get {rating_name} or lower → KEEP IT
- If it would get a higher rating → REMOVE or REWRITE IT

CLEANING APPROACH:
- Remove content that exceeds the {rating_name} threshold
- You may replace explicit scenes with brief neutral summaries ("They spent time together.")
- You may use "fade to black" transitions ("Later that evening...")
- When in doubt about whether something is {rating_name}-appropriate, remove it

REMEMBER: Poetic or metaphorical descriptions of sex are still descriptions of sex. 
A beautifully written sex scene is still a sex scene - clean it accordingly.

RULES:
1. Return ONLY the cleaned text - no explanations
2. Preserve ALL whitespace EXACTLY - same line breaks in the same positions
3. DO NOT ADD [B], [I], or any formatting tags that are not in the original text!
4. When uncertain, remove it

Text to clean:
"""


def build_violence_cleaning_prompt(target_violence: int) -> str:
    """Build a focused prompt for violence content cleaning.
    
    Uses MPAA rating standards - trusts LLM knowledge rather than prescriptive lists.
    """
    rating_name = LEVEL_TO_RATING.get(target_violence, 'R')
    
    if target_violence >= 4:  # R or Unrated - no filtering needed
        return """You are reviewing content. The target allows ALL violent content.

NO FILTERING REQUIRED - Return the text exactly as-is.

Text to return unchanged:
"""
    
    return f"""You are cleaning violent content to achieve a {rating_name} rating.

Think like an MPAA movie rating board. Your job is to edit this text so it would fit in a {rating_name}-rated film.

THE QUESTION: If this scene were in a movie, would it get a {rating_name} rating or higher?
- If it would get {rating_name} or lower → KEEP IT
- If it would get a higher rating → REMOVE or REWRITE IT

CLEANING APPROACH:
- Remove graphic details that exceed the {rating_name} threshold
- You may summarize violent events briefly ("A fight broke out.")
- Keep tension and stakes, reduce graphic detail
- When in doubt about whether something is {rating_name}-appropriate, remove it

RULES:
1. Return ONLY the cleaned text - no explanations
2. Preserve ALL whitespace EXACTLY - same line breaks in the same positions
3. DO NOT ADD [B], [I], or any formatting tags that are not in the original text!
4. When uncertain, remove it

Text to clean:
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

# Size threshold for chunk-based rating (chars)
CHUNK_RATING_THRESHOLD = 4000  # Chapters larger than this get rated in chunks
CHUNK_RATING_SIZE = 3000  # Size of each rating chunk


def _rate_single_chapter(args: tuple) -> tuple:
    """Worker function to rate a single chapter. Returns (index, flagged_for_cleaning, error).
    
    For large chapters (> CHUNK_RATING_THRESHOLD chars), rates in chunks and takes
    the MAX rating across all chunks. This prevents long G-rated sections from
    diluting short problematic sections (e.g., a seduction scene at the end of
    a long travelogue chapter).
    """
    i, chapter, client, target_sexual, target_violence, total = args
    
    # Clone client for thread safety - each worker gets its own copy
    worker_client = client.clone()
    
    # Get worker ID for this thread
    wid = get_worker_id()
    
    title_str = f" ({chapter.title})" if chapter.title and chapter.title != chapter.section_label else ""
    thread_safe_print(f"[W{wid}] [{i+1}/{total}] {chapter.display_name}{title_str}...")
    
    # Get text for rating
    text = chapter.get_text_for_rating()
    if not text.strip():
        thread_safe_print(f"[W{wid}]   (empty chapter, skipping)")
        chapter.rating = ChapterRating()
        chapter.pending_cleaning = None
        chapter.needs_language_cleaning = False
        chapter.needs_adult_cleaning = False
        chapter.needs_violence_cleaning = False
        return (i, False, None)
    
    try:
        # For large chapters, rate in chunks and take MAX rating
        if len(text) > CHUNK_RATING_THRESHOLD:
            # Split into chunks, trying to break at paragraph boundaries
            chunks = []
            paragraphs = text.split('\n\n')
            current_chunk = ""
            
            for para in paragraphs:
                if len(current_chunk) + len(para) > CHUNK_RATING_SIZE and current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = para
                else:
                    current_chunk += "\n\n" + para if current_chunk else para
            
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            
            # Rate each chunk and track max ratings
            max_lang_detected = False
            max_sexual = "G"  
            max_violence = "G"
            chunk_count = len(chunks)
            
            for chunk_idx, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                chunk_rating = worker_client.rate_chapter(chunk, worker_client.language_words)
                
                # Update max ratings
                if chunk_rating.language_detected:
                    max_lang_detected = True
                if RATING_LEVELS.get(chunk_rating.sexual, 1) > RATING_LEVELS.get(max_sexual, 1):
                    max_sexual = chunk_rating.sexual
                if RATING_LEVELS.get(chunk_rating.violence, 1) > RATING_LEVELS.get(max_violence, 1):
                    max_violence = chunk_rating.violence
            
            # Create combined rating from max of all chunks
            rating = ChapterRating(
                language='DETECTED' if max_lang_detected else 'CLEAN',
                language_detected=max_lang_detected,
                sexual=max_sexual, 
                violence=max_violence
            )
            thread_safe_print(f"[W{wid}]   (rated in {chunk_count} chunks)")
        else:
            # Small chapter - rate directly
            rating = worker_client.rate_chapter(text, worker_client.language_words)
        
        chapter.rating = rating
        
        # Set specific flags based on what exceeds target
        chapter.needs_adult_cleaning = RATING_LEVELS.get(rating.sexual, 1) > target_sexual
        chapter.needs_violence_cleaning = RATING_LEVELS.get(rating.violence, 1) > target_violence
        
        # Use LLM's fuzzy language detection (replaces string matching)
        chapter.needs_language_cleaning = rating.language_detected
        
        # Set pending_cleaning: True means chapter has content to clean
        any_cleaning_needed = (
            chapter.needs_language_cleaning or 
            chapter.needs_adult_cleaning or 
            chapter.needs_violence_cleaning
        )
        chapter.pending_cleaning = True if any_cleaning_needed else None
        
        # Build status string showing which types need cleaning
        status_parts = []
        if chapter.needs_language_cleaning:
            status_parts.append("LANG")
        if chapter.needs_adult_cleaning:
            status_parts.append("ADULT")
        if chapter.needs_violence_cleaning:
            status_parts.append("VIOLENCE")
        status = f"NEEDS: {'+'.join(status_parts)}" if status_parts else "OK"
        
        thread_safe_print(f"[W{wid}]   Rating: L={rating.language} A={rating.sexual} V={rating.violence} -> {status}")
        
        return (i, any_cleaning_needed, None)
        
    except Exception as e:
        thread_safe_print(f"[W{wid}]   Error rating chapter: {e}")
        chapter.rating = ChapterRating()
        chapter.pending_cleaning = None
        chapter.needs_language_cleaning = False
        chapter.needs_adult_cleaning = False
        chapter.needs_violence_cleaning = False
        return (i, False, str(e))


def _verify_single_chapter(args: tuple) -> tuple:
    """Worker function to re-rate a single chapter after cleaning.
    
    Returns (chapter_number, old_rating_str, new_rating, still_exceeds, error)
    """
    chapter, client, target_sexual, target_violence, total, processed_idx = args
    
    # Clone client for thread safety
    worker_client = client.clone()
    
    # Get worker ID for this thread
    wid = get_worker_id()
    
    # Get chapter text with cleaned content substituted
    cleaned_text = chapter.get_text_with_cleaned()
    if len(cleaned_text) > 12000:
        cleaned_text = cleaned_text[:12000] + "\n\n[truncated for rating]"
    
    if not cleaned_text.strip():
        return (chapter.number, None, None, False, None)
    
    try:
        rating = worker_client.rate_chapter(cleaned_text)
        old_rating_str = f"{chapter.rating.language}/{chapter.rating.sexual}/{chapter.rating.violence}" if chapter.rating else "none"
        
        # Check if still exceeds targets
        exceeds_adult = RATING_LEVELS.get(rating.sexual, 1) > target_sexual
        exceeds_violence = RATING_LEVELS.get(rating.violence, 1) > target_violence
        still_exceeds = exceeds_adult or exceeds_violence
        
        status = "⚠️  STILL EXCEEDS" if still_exceeds else "✓"
        thread_safe_print(f"[W{wid}] [{processed_idx}/{total}] {chapter.display_name}: {old_rating_str} → L={rating.language} A={rating.sexual} V={rating.violence} {status}")
        
        return (chapter.number, old_rating_str, rating, still_exceeds, None)
        
    except Exception as e:
        thread_safe_print(f"[W{wid}] [{processed_idx}/{total}] {chapter.display_name}: Error re-rating: {e}")
        return (chapter.number, None, None, False, str(e))


def _create_chapter_change_blocks(args: tuple) -> tuple:
    """Worker function to create change blocks for ALL paragraphs in a chapter.
    
    Creates change blocks for every paragraph with LLM ratings stored.
    Paragraphs that exceed targets are marked as 'pending', others as 'ok'.
    
    Used by cmd_clean_passes for the new cleaning pipeline.
    
    Args: (worker_id, chapter_idx, chapter, client, target_sexual, target_violence, 
           language_words, total, verbose)
    Returns: (chapter_idx, lang_indices, adult_indices, violence_indices, new_content, error)
    """
    (worker_id, chapter_idx, chapter, client, target_sexual, target_violence,
     language_words, total, verbose) = args
    
    # Clone client for thread safety
    worker_client = client.clone()
    
    title_str = f" ({chapter.title})" if chapter.title and chapter.title != chapter.section_label else ""
    thread_safe_print(f"[W{worker_id}] [{chapter_idx+1}/{total}] {chapter.display_name}{title_str}")
    
    paragraphs = chapter.get_paragraphs_for_cleaning()
    if not paragraphs:
        return (chapter_idx, set(), set(), set(), None, None)
    
    lang_indices = set()
    adult_indices = set()
    violence_indices = set()
    
    # Store ratings for each paragraph (index -> rating dict)
    paragraph_ratings = {}
    
    # Rate ALL paragraphs to get MPAA ratings for each
    chunk_size = 8
    for chunk_idx in range((len(paragraphs) + chunk_size - 1) // chunk_size):
        start = chunk_idx * chunk_size
        end = min(start + chunk_size, len(paragraphs))
        chunk = paragraphs[start:end]
        
        try:
            # Get full ratings for each paragraph
            chunk_ratings = worker_client.rate_paragraphs(
                chunk, 
                target_sexual, 
                target_violence,
                language_words=language_words
            )
            
            for idx, rating in enumerate(chunk_ratings):
                abs_idx = start + idx
                paragraph_ratings[abs_idx] = rating
                
                # Track which paragraphs exceed targets
                if rating['exceeds_language']:
                    lang_indices.add(abs_idx)
                if rating['exceeds_sexual']:
                    adult_indices.add(abs_idx)
                if rating['exceeds_violence']:
                    violence_indices.add(abs_idx)
                    
        except Exception as e:
            if verbose:
                thread_safe_print(f"[W{worker_id}]   Error rating chunk: {e}")
            # If rating fails, use defaults (G/G/NO) for this chunk
            for idx in range(len(chunk)):
                abs_idx = start + idx
                paragraph_ratings[abs_idx] = {
                    'sexual': 'G', 'violence': 'G', 'language': False,
                    'exceeds_sexual': False, 'exceeds_violence': False, 'exceeds_language': False
                }
    
    # Build new content with change blocks for ALL paragraphs
    new_content = []
    change_num = 1
    all_flagged = lang_indices | adult_indices | violence_indices
    
    for idx, para in enumerate(paragraphs):
        rating = paragraph_ratings.get(idx, {
            'sexual': 'G', 'violence': 'G', 'language': False,
            'exceeds_sexual': False, 'exceeds_violence': False, 'exceeds_language': False
        })
        
        needs_cleaning = idx in all_flagged
        
        new_content.append('')
        new_content.append(f'#CHANGE: {chapter.number}.{change_num}')
        
        # Store the LLM's rating
        lang_str = 'YES' if rating['language'] else 'NO'
        new_content.append(f"#LLM_RATING: LANG={lang_str} SEXUAL={rating['sexual']} VIOLENCE={rating['violence']}")
        
        if needs_cleaning:
            new_content.append('#STATUS: pending')
            
            if idx in lang_indices:
                new_content.append('#NEEDS_LANGUAGE_CLEANING')
            if idx in adult_indices:
                new_content.append('#NEEDS_ADULT_CLEANING')
            if idx in violence_indices:
                new_content.append('#NEEDS_VIOLENCE_CLEANING')
            
            new_content.append('#ORIGINAL')
            new_content.append(para)
            new_content.append('#CLEANED')
            new_content.append('')
            new_content.append('#END')
        else:
            new_content.append('#STATUS: ok')
            new_content.append('#ORIGINAL')
            new_content.append(para)
            new_content.append('#END')
        
        change_num += 1
    
    stats = []
    stats.append(f"{len(paragraphs)} total")
    if lang_indices:
        stats.append(f"{len(lang_indices)} lang")
    if adult_indices:
        stats.append(f"{len(adult_indices)} adult")
    if violence_indices:
        stats.append(f"{len(violence_indices)} violence")
    thread_safe_print(f"[W{worker_id}]   Created {change_num - 1} change blocks ({', '.join(stats)})")
    
    return (chapter_idx, lang_indices, adult_indices, violence_indices, new_content, None)


def _clean_single_block(args: tuple) -> tuple:
    """Worker function to clean a single change block.
    
    Args: (worker_id, change_id, text_to_clean, prompt, fallback_text, client, total, processed_idx)
    Returns: (change_id, cleaned_text, used_fallback, error)
    """
    worker_id, change_id, text_to_clean, prompt, fallback_text, client, total, processed_idx = args
    
    # Clone client for thread safety
    worker_client = client.clone()
    
    thread_safe_print(f"  [W{worker_id}] [{processed_idx}/{total}] Cleaning {change_id}...")
    
    if not text_to_clean.strip():
        return (change_id, None, False, "Empty text")
    
    try:
        cleaned = worker_client._make_request(prompt, text_to_clean, log_type='cleaning')
        
        if not cleaned or not cleaned.strip() or cleaned == '[BLOCKED_BY_SAFETY_FILTER]':
            if fallback_text:
                thread_safe_print(f"  [W{worker_id}]   ⚠️  Blocked, using fallback")
                return (change_id, fallback_text, True, None)
            else:
                thread_safe_print(f"  [W{worker_id}]   ⚠️  Cleaning failed, keeping original")
                return (change_id, None, False, "Blocked")
        else:
            return (change_id, cleaned.strip(), False, None)
            
    except Exception as e:
        thread_safe_print(f"  [W{worker_id}]   Error: {e}")
        if fallback_text:
            return (change_id, fallback_text, True, str(e))
        return (change_id, None, False, str(e))


def cmd_rate(bw: BookWashFile, client: GeminiClient, 
             target_sexual: int, target_violence: int,
             verbose: bool = False) -> int:
    """Pass A: Rate all chapters in parallel, set specific cleaning flags.
    
    Uses NUM_WORKERS parallel threads to rate chapters faster.
    Each worker updates its chapter object in memory, then file is written once at the end.
    
    Sets three independent flags:
    - needs_language_cleaning: True if any of client.language_words are found in text
    - needs_adult_cleaning: True if sexual rating exceeds target_sexual
    - needs_violence_cleaning: True if violence rating exceeds target_violence
    
    Also sets pending_cleaning = True if ANY of the above are True.
    """
    rate_start = time.time()
    print(f"=== PASS A: Rating {len(bw.chapters)} chapters ({NUM_WORKERS} workers) ===")
    print(f"Target levels: adult={LEVEL_TO_RATING[target_sexual]}, "
          f"violence={LEVEL_TO_RATING[target_violence]}")
    if client.language_words:
        obfuscated = [obfuscate_word(w) for w in client.language_words[:5]]
        print(f"Language words to filter: {', '.join(obfuscated)}{'...' if len(client.language_words) > 5 else ''}")
    print()
    
    # Reset worker IDs for fresh tracking
    reset_worker_ids()
    
    # Update settings in file
    bw.settings['target_sexual'] = target_sexual
    bw.settings['target_violence'] = target_violence
    
    # Save the rating prompt for debugging/analysis
    bw.chapter_rating_prompt = build_chapter_rating_prompt(client.language_words)
    
    # Prepare work items for parallel processing
    total = len(bw.chapters)
    work_items = [
        (i, chapter, client, target_sexual, target_violence, total)
        for i, chapter in enumerate(bw.chapters)
    ]
    
    flagged_count = 0
    
    # Process chapters in parallel with NUM_WORKERS threads
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        # Submit all work
        futures = {executor.submit(_rate_single_chapter, item): item[0] for item in work_items}
        
        # Collect results as they complete
        for future in as_completed(futures):
            try:
                idx, flagged_for_cleaning, error = future.result()
                if flagged_for_cleaning:
                    flagged_count += 1
            except Exception as e:
                idx = futures[future]
                thread_safe_print(f"  [{idx+1}] Worker exception: {e}")
    
    print()
    rate_elapsed = time.time() - rate_start
    print(f"Rating complete: {flagged_count}/{len(bw.chapters)} chapters flagged for cleaning")
    print(f"⏱️  Rating time: {rate_elapsed:.1f}s ({rate_elapsed/60:.1f} min)", file=sys.stderr)
    
    return flagged_count


def _identify_paragraphs_worker(args: tuple) -> tuple:
    """Worker function to identify paragraphs needing cleaning in a single chunk.
    
    Returns (chunk_idx, start_idx, flagged_indices, error).
    """
    chunk_idx, start_idx, chunk, client, target_sexual, target_violence, language_words = args
    
    # Clone client for thread safety
    worker_client = client.clone()
    
    try:
        flagged_in_chunk = worker_client.identify_paragraphs_to_clean(chunk, target_sexual, target_violence, language_words=language_words)
        # Convert chunk-relative indices to absolute indices
        flagged = {start_idx + idx for idx in flagged_in_chunk}
        return (chunk_idx, start_idx, flagged, None)
    except Exception as e:
        return (chunk_idx, start_idx, set(), str(e))


def cmd_clean_passes(bw: BookWashFile, client: GeminiClient, filepath: Path,
                      verbose: bool = False) -> int:
    """New simplified cleaning pipeline with separate passes for each content type.
    
    Three passes, each saving to file after completion:
    1. Language pass: Clean blocks with #NEEDS_LANGUAGE_CLEANING
    2. Adult pass: Clean blocks with #NEEDS_ADULT_CLEANING  
    3. Violence pass: Clean blocks with #NEEDS_VIOLENCE_CLEANING
    
    No re-rating or escalation - each pass uses focused prompts.
    """
    pipeline_start = time.time()
    phase_times = {}  # Track timing for each phase
    
    target_sexual = bw.target_sexual
    target_violence = bw.target_violence
    
    # Count chapters that need cleaning for progress display
    chapters_needing_cleaning = sum(1 for ch in bw.chapters if ch.pending_cleaning)
    
    print(f"=== CLEANING PIPELINE: {chapters_needing_cleaning} chapters ===")
    print(f"Target levels: adult={LEVEL_TO_RATING[target_sexual]}, "
          f"violence={LEVEL_TO_RATING[target_violence]}")
    if client.language_words:
        print(f"Language words: {len(client.language_words)} configured")
    print()
    
    total_changes = 0
    
    # First, identify paragraphs that need each type of cleaning
    # and create change blocks with specific flags
    print(f"=== IDENTIFYING CONTENT TO CLEAN ({NUM_WORKERS} workers) ===")
    identify_start = time.time()
    
    # Build and save paragraph identification prompt template for debugging
    id_prompt = build_paragraph_identification_prompt(client.language_words, target_sexual, target_violence)
    bw.paragraph_identification_prompt = id_prompt
    
    # Reset worker IDs for fresh tracking
    reset_worker_ids()
    
    # Build work items for chapters needing cleaning
    chapters_to_identify = [(i, ch) for i, ch in enumerate(bw.chapters) if ch.pending_cleaning]
    total_to_identify = len(chapters_to_identify)
    
    if chapters_to_identify:
        work_args = [
            ((idx % NUM_WORKERS) + 1, chapter_idx, chapter, client, target_sexual, target_violence,
             client.language_words, total_to_identify, verbose)
            for idx, (chapter_idx, chapter) in enumerate(chapters_to_identify)
        ]
        
        # Process in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = {executor.submit(_create_chapter_change_blocks, args): args[1] for args in work_args}
            for future in as_completed(futures):
                try:
                    chapter_idx, lang_indices, adult_indices, violence_indices, new_content, error = future.result()
                    results[chapter_idx] = (lang_indices, adult_indices, violence_indices, new_content)
                except Exception as e:
                    chapter_idx = futures[future]
                    thread_safe_print(f"  Worker exception for chapter {chapter_idx}: {e}")
        
        # Apply results to chapters (sequential for thread safety)
        total_pending = 0
        for chapter_idx, (lang_indices, adult_indices, violence_indices, new_content) in results.items():
            chapter = bw.chapters[chapter_idx]
            if new_content:
                chapter.content_lines = new_content
                pending_count = len(lang_indices | adult_indices | violence_indices)
                total_changes += len([l for l in new_content if l.startswith('#CHANGE:')])
                total_pending += pending_count
                # Set pending_cleaning based on whether any blocks need cleaning
                chapter.pending_cleaning = True if pending_count > 0 else False
            else:
                # No content generated (empty chapter)
                chapter.pending_cleaning = None
    
    # Save after identification
    write_bookwash(bw, filepath)
    phase_times['identify'] = time.time() - identify_start
    print(f"\n✓ Saved after identification ({total_changes} change blocks, {total_pending} need cleaning) [{phase_times['identify']:.1f}s]")
    print()
    
    # === PASS 1: LANGUAGE CLEANING (Parallel) ===
    print(f"=== PASS 1: LANGUAGE CLEANING ({NUM_WORKERS} workers) ===")
    lang_start = time.time()
    lang_prompt = build_language_cleaning_prompt(client.language_words)
    lang_cleaned = 0
    
    if client.language_words and lang_prompt:
        # Collect all blocks needing language cleaning
        lang_work_items = []
        for chapter in bw.chapters:
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
                        lang_work_items.append((chapter, change_id, original))
        
        print(f"  {len(lang_work_items)} blocks need language cleaning")
        
        # Save language prompt to file
        bw.cleaning_prompt = f"=== LANGUAGE CLEANING PROMPT ===\n{lang_prompt}"
        
        if lang_work_items:
            # Build work items with worker IDs (round-robin assignment)
            total = len(lang_work_items)
            work_args = [
                ((i % NUM_WORKERS) + 1, change_id, text, lang_prompt, None, client, total, i + 1)
                for i, (chapter, change_id, text) in enumerate(lang_work_items)
            ]
            
            # Process in parallel
            results = {}
            with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
                futures = {executor.submit(_clean_single_block, args): args[1] for args in work_args}
                for future in as_completed(futures):
                    change_id, cleaned_text, used_fallback, error = future.result()
                    if cleaned_text:
                        results[change_id] = cleaned_text
                        lang_cleaned += 1
            
            # Apply results to chapters (sequential for thread safety)
            for chapter, change_id, _ in lang_work_items:
                if change_id in results:
                    _set_change_cleaned(chapter, change_id, results[change_id])
        
        phase_times['language'] = time.time() - lang_start
        print(f"  Cleaned {lang_cleaned} language blocks [{phase_times['language']:.1f}s]")
        write_bookwash(bw, filepath)
        print(f"  ✓ Saved after language pass")
    else:
        phase_times['language'] = time.time() - lang_start
        print(f"  (No language words to filter) [{phase_times['language']:.1f}s]")
    print()
    
    # === PASS 2: ADULT CONTENT CLEANING (Parallel) ===
    print(f"=== PASS 2: ADULT CONTENT CLEANING ({NUM_WORKERS} workers) ===")
    adult_start = time.time()
    adult_prompt = build_adult_cleaning_prompt(target_sexual)
    adult_cleaned = 0
    adult_fallback_used = 0
    
    # Collect all blocks needing adult cleaning
    adult_work_items = []
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
                    adult_work_items.append((chapter, change_id, text_to_clean))
    
    print(f"  {len(adult_work_items)} blocks need adult cleaning")
    
    # Append adult prompt to saved prompts
    if bw.cleaning_prompt:
        bw.cleaning_prompt += f"\n\n=== ADULT CLEANING PROMPT ===\n{adult_prompt}"
    else:
        bw.cleaning_prompt = f"=== ADULT CLEANING PROMPT ===\n{adult_prompt}"
    
    if adult_work_items:
        # Build work items with worker IDs
        total = len(adult_work_items)
        work_args = [
            ((i % NUM_WORKERS) + 1, change_id, text, adult_prompt, ADULT_FALLBACK, client, total, i + 1)
            for i, (chapter, change_id, text) in enumerate(adult_work_items)
        ]
        
        # Process in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = {executor.submit(_clean_single_block, args): args[1] for args in work_args}
            for future in as_completed(futures):
                change_id, cleaned_text, used_fallback, error = future.result()
                if cleaned_text:
                    results[change_id] = cleaned_text
                    adult_cleaned += 1
                    if used_fallback:
                        adult_fallback_used += 1
        
        # Apply results to chapters (sequential for thread safety)
        for chapter, change_id, _ in adult_work_items:
            if change_id in results:
                _set_change_cleaned(chapter, change_id, results[change_id])
    
    phase_times['adult'] = time.time() - adult_start
    print(f"  Cleaned {adult_cleaned} adult blocks ({adult_fallback_used} used fallback) [{phase_times['adult']:.1f}s]")
    write_bookwash(bw, filepath)
    print(f"  ✓ Saved after adult pass")
    print()
    
    # === PASS 3: VIOLENCE CLEANING (Parallel) ===
    print(f"=== PASS 3: VIOLENCE CLEANING ({NUM_WORKERS} workers) ===")
    violence_start = time.time()
    violence_prompt = build_violence_cleaning_prompt(target_violence)
    violence_cleaned = 0
    violence_fallback_used = 0
    
    # Collect all blocks needing violence cleaning
    violence_work_items = []
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
                    violence_work_items.append((chapter, change_id, text_to_clean))
    
    print(f"  {len(violence_work_items)} blocks need violence cleaning")
    
    # Append violence prompt to saved prompts
    bw.cleaning_prompt += f"\n\n=== VIOLENCE CLEANING PROMPT ===\n{violence_prompt}"
    
    if violence_work_items:
        # Build work items with worker IDs
        total = len(violence_work_items)
        work_args = [
            ((i % NUM_WORKERS) + 1, change_id, text, violence_prompt, VIOLENCE_FALLBACK, client, total, i + 1)
            for i, (chapter, change_id, text) in enumerate(violence_work_items)
        ]
        
        # Process in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = {executor.submit(_clean_single_block, args): args[1] for args in work_args}
            for future in as_completed(futures):
                change_id, cleaned_text, used_fallback, error = future.result()
                if cleaned_text:
                    results[change_id] = cleaned_text
                    violence_cleaned += 1
                    if used_fallback:
                        violence_fallback_used += 1
        
        # Apply results to chapters (sequential for thread safety)
        for chapter, change_id, _ in violence_work_items:
            if change_id in results:
                _set_change_cleaned(chapter, change_id, results[change_id])
    
    phase_times['violence'] = time.time() - violence_start
    print(f"  Cleaned {violence_cleaned} violence blocks ({violence_fallback_used} used fallback) [{phase_times['violence']:.1f}s]")
    
    # Remove any orphaned cleaning markers that ended up outside change blocks
    orphaned = _remove_orphaned_cleaning_markers(bw)
    if orphaned > 0:
        print(f"  🧹 Removed {orphaned} orphaned cleaning markers")
    
    write_bookwash(bw, filepath)
    print(f"  ✓ Saved after violence pass")
    print()
    
    # === RE-RATING PASS: Verify cleaning worked (parallel) ===
    verify_start = time.time()
    # Find chapters that have change blocks (i.e., were modified)
    chapters_with_changes = []
    for chapter in bw.chapters:
        has_changes = any(line.startswith('#CHANGE:') for line in chapter.content_lines)
        if has_changes:
            chapters_with_changes.append(chapter)
    
    if not chapters_with_changes:
        print("=== VERIFYING CLEANED CONTENT ===")
        print("  No chapters were modified, skipping verification")
        phase_times['verify'] = time.time() - verify_start
    else:
        total_to_verify = len(chapters_with_changes)
        print(f"=== VERIFYING CLEANED CONTENT ({total_to_verify} chapters, {NUM_WORKERS} workers) ===")
        
        # Build work items for parallel processing
        verify_items = [
            (chapter, client, target_sexual, target_violence, total_to_verify, idx + 1)
            for idx, chapter in enumerate(chapters_with_changes)
        ]
        
        # Process in parallel
        still_exceeds = []
        results = {}  # chapter_number -> (rating, still_exceeds)
        
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = {executor.submit(_verify_single_chapter, item): item[0].number for item in verify_items}
            
            for future in as_completed(futures):
                try:
                    ch_num, old_rating_str, new_rating, exceeds, error = future.result()
                    if new_rating:
                        results[ch_num] = (new_rating, exceeds)
                        if exceeds:
                            still_exceeds.append((ch_num, new_rating))
                except Exception as e:
                    ch_num = futures[future]
                    thread_safe_print(f"  Chapter {ch_num}: Worker exception: {e}")
        
        # Apply results to chapters
        for chapter in chapters_with_changes:
            if chapter.number in results:
                new_rating, exceeds = results[chapter.number]
                chapter.rating = new_rating
                
                if exceeds:
                    chapter.pending_cleaning = True  # Still has content to clean
                    chapter.needs_adult_cleaning = RATING_LEVELS.get(new_rating.sexual, 1) > target_sexual
                    chapter.needs_violence_cleaning = RATING_LEVELS.get(new_rating.violence, 1) > target_violence
                else:
                    chapter.pending_cleaning = False  # Cleaning complete
                    chapter.needs_adult_cleaning = False
                    chapter.needs_violence_cleaning = False
        
        # Reset language cleaning (word-based, always complete after one pass)
        for chapter in bw.chapters:
            chapter.needs_language_cleaning = False
        
        write_bookwash(bw, filepath)
        phase_times['verify'] = time.time() - verify_start
        
        if still_exceeds:
            print(f"\n⚠️  {len(still_exceeds)} chapters still exceed targets after cleaning. [{phase_times['verify']:.1f}s]")
            print("  These may need manual review or more aggressive prompts.")
            for ch_num, rating in still_exceeds:
                print(f"    - Chapter {ch_num}: A={rating.sexual} V={rating.violence}")
        else:
            print(f"\n✓ All chapters now meet target ratings! [{phase_times['verify']:.1f}s]")
    
    # Calculate total pipeline time
    total_time = time.time() - pipeline_start
    
    print()
    print(f"=== CLEANING COMPLETE ===")
    print(f"Total: {total_changes} change blocks")
    print(f"  Language: {lang_cleaned}")
    print(f"  Adult: {adult_cleaned} ({adult_fallback_used} fallback)")
    print(f"  Violence: {violence_cleaned} ({violence_fallback_used} fallback)")
    
    # Print timing to stderr so it's always visible
    print(f"\n⏱️  TIMING BREAKDOWN:", file=sys.stderr)
    print(f"  Identify:   {phase_times.get('identify', 0):6.1f}s", file=sys.stderr)
    print(f"  Language:   {phase_times.get('language', 0):6.1f}s", file=sys.stderr)
    print(f"  Adult:      {phase_times.get('adult', 0):6.1f}s", file=sys.stderr)
    print(f"  Violence:   {phase_times.get('violence', 0):6.1f}s", file=sys.stderr)
    print(f"  Verify:     {phase_times.get('verify', 0):6.1f}s", file=sys.stderr)
    print(f"  ─────────────────", file=sys.stderr)
    print(f"  TOTAL:      {total_time:6.1f}s ({total_time/60:.1f} min)", file=sys.stderr)
    
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
        description='BookWash LLM Integration - Content moderation with parallel processing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Rate and clean all chapters (recommended)
    python bookwash_llm.py --rate --clean-passes book.bookwash --api-key YOUR_KEY
    
    # Rate only (Pass A)
    python bookwash_llm.py --rate book.bookwash --api-key YOUR_KEY
    
    # Custom target levels
    python bookwash_llm.py --rate --clean-passes book.bookwash --sexual 2 --violence 3
        """
    )
    
    parser.add_argument('input', help='Input .bookwash file')
    parser.add_argument('--rate', action='store_true', help='Pass A: Rate all chapters')
    parser.add_argument('--clean-passes', action='store_true', 
                       help='Run cleaning pipeline (language, adult, violence passes)')
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
    
    args = parser.parse_args()
    
    # Validate input
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return 1
    
    if not args.rate and not args.clean_passes:
        print("Error: Must specify --rate, --clean-passes, or both")
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
    
    # Handle language filtering (word-based, not level-based)
    language_words = []
    if args.language_words:
        try:
            language_words = json.loads(args.language_words)
            print(f"Language: Filtering {len(language_words)} specific words")
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in --language-words: {args.language_words}")
            return 1
    elif args.language is not None:
        # Legacy --language flag is deprecated but still accepted
        print(f"Language: --language flag is deprecated, use --language-words instead")
    else:
        print(f"Language: No specific words configured (use --language-words)")
    
    if args.dry_run:
        print("Dry run mode - no API calls will be made")
        for ch in bw.chapters:
            title = f" ({ch.title})" if ch.title else ""
            rating_str = f" L={ch.rating.language} S={ch.rating.sexual} V={ch.rating.violence}" if ch.rating else ""
            status = ""
            if ch.pending_cleaning is True:
                status = " PENDING_CLEANING"
            elif ch.pending_cleaning is False:
                status = " CLEANING_COMPLETE"
            print(f"  Chapter {ch.number}{title}{rating_str}{status}")
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
