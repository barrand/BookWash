#!/usr/bin/env python3
"""
BookWash LLM Integration

Two-pass architecture for content moderation:
  Pass A (--rate):  Rate all chapters, set #RATING and #NEEDS_CLEANING
  Pass B (--clean): Clean chapters where #NEEDS_CLEANING: true, insert #CHANGE blocks

Usage:
    # Rate all chapters (Pass A)
    python bookwash_llm.py --rate book.bookwash --api-key YOUR_KEY
    
    # Clean flagged chapters (Pass B)
    python bookwash_llm.py --clean book.bookwash --api-key YOUR_KEY
    
    # Full pipeline (both passes)
    python bookwash_llm.py --rate --clean book.bookwash --api-key YOUR_KEY
    
    # Set target levels (default: language=2, sexual=2, violence=5)
    python bookwash_llm.py --rate book.bookwash --language 2 --sexual 2 --violence 3

Environment:
    GEMINI_API_KEY - API key (or use --api-key)
    GEMINI_MODEL - Model name (default: gemini-2.0-flash-exp)
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

DEFAULT_MODEL = 'gemini-1.5-flash'
FALLBACK_MODELS = [
    'gemini-2.0-flash-exp',    # Experimental flash
    'gemini-2.0-flash',        # Stable flash - fast  
    'gemini-2.0-flash-lite',   # Lite version - fastest
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
    
    def get_paragraphs_for_cleaning(self) -> list:
        """Get paragraphs that need cleaning (original text, no existing changes)."""
        text = self.get_text_for_rating()
        # Split on double newlines to get paragraphs
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
        """Switch to next fallback model after rate limiting."""
        if self.fallback_index < len(FALLBACK_MODELS):
            old_model = self.current_model
            self.current_model = FALLBACK_MODELS[self.fallback_index]
            self.fallback_index += 1
            print(f"  ⚡ Switching model: {old_model} → {self.current_model}")
            return True
        return False
    
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
   - PG-13: Moderate profanity (damn, hell, crap, ass, bastard) but NO f-word
   - R: Strong profanity including f-word usage
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


# --- Change Detection ---

def find_changes(original_paragraphs: list, cleaned_paragraphs: list, 
                 chapter_num: int, start_change_id: int,
                 target_lang: int, target_sexual: int, target_violence: int) -> tuple:
    """
    Compare original and cleaned paragraphs, generate #CHANGE blocks.
    Uses fuzzy matching to align paragraphs correctly even if counts differ.
    Returns (new_content_lines, next_change_id).
    """
    from difflib import SequenceMatcher
    
    lines = []
    change_id = start_change_id
    
    # If counts match, do simple 1:1 comparison
    if len(original_paragraphs) == len(cleaned_paragraphs):
        for i, (orig, cleaned) in enumerate(zip(original_paragraphs, cleaned_paragraphs)):
            orig = orig.strip()
            cleaned = cleaned.strip()
            
            if orig == cleaned or not orig:
                # No change
                if orig:
                    lines.append('')  # Blank line separator
                    lines.append(orig)
            else:
                # Change detected
                lines.append('')  # Blank line separator
                lines.append(f'#CHANGE: c{change_id:03d}')
                lines.append('#STATUS: pending')
                
                reason = _infer_reason(orig, cleaned, target_lang, target_sexual, target_violence)
                lines.append(f'#REASON: {reason}')
                
                lines.append('#ORIGINAL')
                lines.append(orig)
                lines.append('#CLEANED')
                lines.append(cleaned)
                lines.append('#END')
                
                change_id += 1
        return lines, change_id
    
    # Paragraph count mismatch - use fuzzy matching
    print(f"  Note: Paragraph count differs ({len(original_paragraphs)} orig vs {len(cleaned_paragraphs)} cleaned), using alignment...")
    
    # Build a mapping from original paragraphs to their best matching cleaned paragraphs
    # using sequence similarity
    orig_to_cleaned = {}
    used_cleaned = set()
    
    for i, orig in enumerate(original_paragraphs):
        orig = orig.strip()
        if not orig:
            continue
            
        best_match = -1
        best_ratio = 0.0
        
        for j, cleaned in enumerate(cleaned_paragraphs):
            if j in used_cleaned:
                continue
            cleaned = cleaned.strip()
            if not cleaned:
                continue
            
            # Calculate similarity
            ratio = SequenceMatcher(None, orig, cleaned).ratio()
            
            # If orig is short (like a title) and cleaned contains it, boost score
            if len(orig) < 100 and orig.lower() in cleaned.lower():
                ratio = max(ratio, 0.3)  # Ensure it gets considered
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = j
        
        # Only match if similarity is reasonable (>30%) or if cleaned contains original
        if best_match >= 0 and best_ratio > 0.3:
            orig_to_cleaned[i] = best_match
            used_cleaned.add(best_match)
    
    # Now process each original paragraph
    for i, orig in enumerate(original_paragraphs):
        orig = orig.strip()
        if not orig:
            continue
        
        if i in orig_to_cleaned:
            cleaned_idx = orig_to_cleaned[i]
            cleaned = cleaned_paragraphs[cleaned_idx].strip()
            
            if orig == cleaned:
                # No change
                lines.append('')
                lines.append(orig)
            else:
                # Change detected
                lines.append('')
                lines.append(f'#CHANGE: c{change_id:03d}')
                lines.append('#STATUS: pending')
                
                reason = _infer_reason(orig, cleaned, target_lang, target_sexual, target_violence)
                lines.append(f'#REASON: {reason}')
                
                lines.append('#ORIGINAL')
                lines.append(orig)
                lines.append('#CLEANED')
                lines.append(cleaned)
                lines.append('#END')
                
                change_id += 1
        else:
            # Original paragraph was removed entirely
            lines.append('')
            lines.append(f'#CHANGE: c{change_id:03d}')
            lines.append('#STATUS: pending')
            lines.append('#REASON: content removed for target rating')
            lines.append('#ORIGINAL')
            lines.append(orig)
            lines.append('#CLEANED')
            lines.append('')  # Empty cleaned version
            lines.append('#END')
            change_id += 1
    
    return lines, change_id


def _infer_reason(original: str, cleaned: str, target_lang: int, target_sexual: int, target_violence: int) -> str:
    """Infer why a change was made based on content."""
    orig_lower = original.lower()
    
    # Check for profanity
    strong_profanity = ['fuck', 'fucking', 'fucked', 'shit']
    moderate_profanity = ['damn', 'hell', 'crap', 'ass', 'bitch', 'bastard']
    
    for word in strong_profanity:
        if word in orig_lower and word not in cleaned.lower():
            return f'language=R exceeds target={LEVEL_TO_RATING[target_lang]}'
    
    for word in moderate_profanity:
        if word in orig_lower and word not in cleaned.lower():
            return f'language=PG-13 exceeds target={LEVEL_TO_RATING[target_lang]}'
    
    # Check for sexual content indicators
    sexual_words = ['kiss', 'body', 'touch', 'caress', 'embrace', 'passion', 'desire']
    for word in sexual_words:
        if word in orig_lower and word not in cleaned.lower():
            return f'sexual content exceeds target={LEVEL_TO_RATING[target_sexual]}'
    
    # Check for violence indicators
    violence_words = ['blood', 'wound', 'kill', 'stab', 'slash', 'gore']
    for word in violence_words:
        if word in orig_lower and word not in cleaned.lower():
            return f'violence exceeds target={LEVEL_TO_RATING[target_violence]}'
    
    return 'content modified for target rating'


# --- Main Commands ---

def cmd_rate(bw: BookWashFile, client: GeminiClient, 
             target_lang: int, target_sexual: int, target_violence: int,
             verbose: bool = False) -> int:
    """Rate all chapters (Pass A)."""
    print(f"Rating {len(bw.chapters)} chapters...")
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


def cmd_clean(bw: BookWashFile, client: GeminiClient, verbose: bool = False,
               max_iterations: int = 3, verify: bool = True) -> int:
    """Clean flagged chapters (Pass B) with optional verification loop."""
    chapters_to_clean = [ch for ch in bw.chapters if ch.needs_cleaning]
    
    if not chapters_to_clean:
        print("No chapters need cleaning.")
        return 0
    
    print(f"Cleaning {len(chapters_to_clean)} chapters...")
    target_lang = bw.target_language
    target_sexual = bw.target_sexual
    target_violence = bw.target_violence
    print(f"Target levels: language={target_lang} ({LEVEL_TO_RATING[target_lang]}), "
          f"adult={target_sexual} ({LEVEL_TO_RATING[target_sexual]}), "
          f"violence={target_violence} ({LEVEL_TO_RATING[target_violence]})")
    if verify:
        print(f"Verification enabled (max {max_iterations} iterations per chapter)")
    print()
    
    changes_made = 0
    global_change_id = 1
    verified_count = 0
    
    for i, chapter in enumerate(chapters_to_clean):
        title_str = f" ({chapter.title})" if chapter.title else ""
        print(f"[{i+1}/{len(chapters_to_clean)}] Chapter {chapter.number}{title_str}...")
        
        # Get paragraphs for cleaning
        original_paragraphs = chapter.get_paragraphs_for_cleaning()
        if not original_paragraphs:
            print("  (empty chapter, skipping)")
            continue
        
        # Join paragraphs for cleaning (double newline separated)
        original_text = '\n\n'.join(original_paragraphs)
        
        try:
            # Cleaning loop with verification
            current_text = original_text
            iteration = 0
            final_rating = None
            
            while iteration < max_iterations:
                iteration += 1
                
                # Calculate aggression level based on iteration and target strictness
                # For G/PG targets, escalate aggression faster
                is_strict_target = target_lang <= 2 or target_sexual <= 2
                if iteration == 1:
                    aggression = 1
                elif iteration == 2:
                    aggression = 2 if is_strict_target else 1
                else:
                    aggression = 3 if is_strict_target else 2
                
                # Clean the text
                if iteration == 1:
                    print(f"  Cleaning (pass {iteration})...")
                else:
                    agg_str = {1: "", 2: " [aggressive]", 3: " [VERY aggressive]"}.get(aggression, "")
                    print(f"  Re-cleaning (pass {iteration}){agg_str}...")
                
                cleaned_text = client.clean_text(current_text, target_lang, target_sexual, target_violence, aggression)
                
                if not verify:
                    # No verification - just use the cleaned text
                    current_text = cleaned_text
                    break
                
                # Verify: rate the cleaned content
                print(f"  Verifying...")
                
                # Truncate for rating if very long
                text_for_rating = cleaned_text
                if len(text_for_rating) > 10000:
                    text_for_rating = text_for_rating[:10000] + "\n\n[truncated for rating]"
                
                final_rating = client.rate_chapter(text_for_rating)
                still_exceeds = final_rating.exceeds_target(target_lang, target_sexual, target_violence)
                
                print(f"    Post-clean rating: L={final_rating.language} A={final_rating.sexual} V={final_rating.violence}")
                
                if not still_exceeds:
                    print(f"    ✓ Meets target after {iteration} pass(es)")
                    verified_count += 1
                    current_text = cleaned_text
                    break
                else:
                    print(f"    ✗ Still exceeds target, ", end="")
                    if iteration < max_iterations:
                        print("trying again...")
                        current_text = cleaned_text  # Use cleaned version for next pass
                    else:
                        print(f"max iterations reached")
                        current_text = cleaned_text
            
            # Parse cleaned paragraphs
            cleaned_paragraphs = [p.strip() for p in re.split(r'\n\n+', current_text.strip()) if p.strip()]
            
            # Generate change blocks (compare original to final cleaned)
            new_content, global_change_id = find_changes(
                original_paragraphs, cleaned_paragraphs,
                chapter.number, global_change_id,
                target_lang, target_sexual, target_violence
            )
            
            # Count changes made
            chapter_changes = sum(1 for line in new_content if line.startswith('#CHANGE:'))
            changes_made += chapter_changes
            
            if chapter_changes > 0:
                print(f"  {chapter_changes} changes made")
                # Replace chapter content with new content including change blocks
                chapter.content_lines = new_content
            else:
                print("  No changes needed")
            
            # Update chapter rating with post-clean rating
            if final_rating:
                chapter.rating = final_rating
            
            # Mark as cleaned (no longer needs cleaning if verified)
            if verify and final_rating and not final_rating.exceeds_target(target_lang, target_sexual, target_violence):
                chapter.needs_cleaning = False
            else:
                # Still needs cleaning if we couldn't verify or hit max iterations
                chapter.needs_cleaning = False  # Mark false anyway to avoid infinite loops
            
        except Exception as e:
            print(f"  Error cleaning chapter: {e}")
            import traceback
            traceback.print_exc()
    
    print()
    print(f"Cleaning complete: {changes_made} total changes made")
    if verify:
        print(f"Verification: {verified_count}/{len(chapters_to_clean)} chapters meet target rating")
    
    return changes_made


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description='BookWash LLM Integration - Two-pass content moderation with verification',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Rate all chapters (Pass A)
    python bookwash_llm.py --rate book.bookwash --api-key YOUR_KEY
    
    # Clean flagged chapters with verification (Pass B)  
    python bookwash_llm.py --clean book.bookwash --api-key YOUR_KEY
    
    # Clean without verification (faster, less accurate)
    python bookwash_llm.py --clean --no-verify book.bookwash --api-key YOUR_KEY
    
    # Full pipeline (both passes)
    python bookwash_llm.py --rate --clean book.bookwash --api-key YOUR_KEY
    
    # Custom target levels and max iterations
    python bookwash_llm.py --rate --clean book.bookwash --language 2 --sexual 2 --max-iterations 5
        """
    )
    
    parser.add_argument('input', help='Input .bookwash file')
    parser.add_argument('--rate', action='store_true', help='Run rating pass (Pass A)')
    parser.add_argument('--clean', action='store_true', help='Run cleaning pass (Pass B)')
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
    
    args = parser.parse_args()
    
    # Validate input
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return 1
    
    if not args.rate and not args.clean:
        print("Error: Must specify --rate and/or --clean")
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
