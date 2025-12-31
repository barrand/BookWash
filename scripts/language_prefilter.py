"""
Language Prefilter - Regex-based profanity replacement for unambiguous cases.

This module applies deterministic regex replacements BEFORE any LLM processing.
Only words/phrases with NO legitimate alternate meanings are replaced here.

Words like "bastard" (illegitimate child), "bitch" (female dog), "ass" (donkey),
"damn" (condemn), "hell" (place), etc. are NOT replaced here because they have
legitimate non-profane meanings that require context to evaluate.
"""

import re
from typing import Tuple, List

# =============================================================================
# PHRASE REPLACEMENTS (applied first - longer matches before shorter)
# =============================================================================
# These are multi-word phrases where the meaning is unambiguous

PHRASE_REPLACEMENTS: List[Tuple[str, str]] = [
    # "son of a bitch" variations
    ("son of a bitch", "scoundrel"),
    ("sons of bitches", "scoundrels"),
    ("son-of-a-bitch", "scoundrel"),
    
    # "what the X" phrases
    ("what the fuck", "what on earth"),
    ("what the hell", "what on earth"),
    ("what the shit", "what on earth"),
    
    # "who/where/how/why the X" phrases
    ("who the fuck", "who on earth"),
    ("who the hell", "who on earth"),
    ("where the fuck", "where in the world"),
    ("where the hell", "where on earth"),
    ("how the fuck", "how on earth"),
    ("how the hell", "how on earth"),
    ("why the fuck", "why on earth"),
    ("why the hell", "why on earth"),
    
    # "oh X" exclamations
    ("oh hell", "oh no"),
    ("oh shit", "oh no"),
    ("oh fuck", "oh no"),
    
    # "go to hell" / dismissals
    ("go to hell", "go away"),
    ("burn in hell", "get lost"),
    ("damn you", "curse you"),
    ("damn them", "curse them"),
    ("damn it", "curses"),
    ("fuck off", "get lost"),
    ("fuck you", "forget you"),
    ("screw you", "forget you"),
    
    # "shut up" intensifiers
    ("shut the fuck up", "shut up"),
    ("shut the hell up", "shut up"),
    
    # "for X's sake"
    ("for fuck's sake", "for goodness' sake"),
    ("for fuck sake", "for goodness' sake"),
    ("for god's sake", "for goodness' sake"),
    ("god's sake", "goodness' sake"),
    ("for christ's sake", "for goodness' sake"),
    
    # State descriptions
    ("fucked up", "messed up"),
    ("screwed up", "messed up"),
    ("pissed off", "ticked off"),
    
    # "kick X ass" variations
    ("kick your ass", "beat you"),
    ("kick his ass", "beat him"),
    ("kick her ass", "beat her"),
    ("kick their ass", "beat them"),
    ("kick my ass", "beat me"),
    ("kicked my ass", "beat me"),
    ("kicked his ass", "beat him"),
    ("kicked her ass", "beat her"),
    ("kicked their ass", "beat them"),
    ("kicks ass", "is great"),
    ("kick ass", "great"),
    ("kick-ass", "great"),
    
    # "pain in the ass"
    ("pain in the ass", "pain in the neck"),
    ("pain in my ass", "pain in my neck"),
    
    # "X my ass" (disbelief)
    ("my ass", "yeah right"),  # Be careful - only when standalone expression
    
    # "don't give a X"
    ("don't give a shit", "don't care"),
    ("don't give a damn", "don't care"),
    ("don't give a fuck", "don't care"),
    ("doesn't give a shit", "doesn't care"),
    ("doesn't give a damn", "doesn't care"),
    ("doesn't give a fuck", "doesn't care"),
    ("didn't give a shit", "didn't care"),
    ("didn't give a damn", "didn't care"),
    ("didn't give a fuck", "didn't care"),
    ("could give a shit", "could care"),
    ("couldn't give a shit", "couldn't care"),
    
    # "get the hell/fuck out"
    ("get the hell out", "get out"),
    ("get the fuck out", "get out"),
    
    # "the hell with" / "to hell with"
    ("the hell with", "forget"),
    ("to hell with", "forget"),
    
    # Compound insults
    ("fucking idiot", "complete idiot"),
    ("fucking moron", "complete moron"),
    ("fucking stupid", "completely stupid"),
    
    # "holy X"
    ("holy shit", "oh wow"),
    ("holy fuck", "holy goodness"),
    ("holy crap", "holy cow"),
]

# =============================================================================
# SINGLE WORD REPLACEMENTS (applied after phrases)
# =============================================================================
# Only words with NO legitimate alternate meanings

WORD_REPLACEMENTS: List[Tuple[str, str]] = [
    # Core profanity - shit family
    ("shit", "crud"),
    ("shitty", "crummy"),
    ("bullshit", "nonsense"),
    ("horseshit", "nonsense"),
    ("batshit", "completely"),
    ("apeshit", "berserk"),
    ("shitshow", "disaster"),
    ("shitstorm", "disaster"),
    ("shithead", "idiot"),
    ("shitheads", "idiots"),
    ("shithole", "dump"),
    ("shitholes", "dumps"),
    ("dipshit", "idiot"),
    ("dipshits", "idiots"),
    ("chickenshit", "cowardly"),
    
    # Core profanity - fuck family
    ("fucking", "freaking"),
    ("fuckin", "freaking"),
    ("fuckin'", "freaking"),
    ("fucker", "jerk"),
    ("fuckers", "jerks"),
    ("fuckhead", "fool"),
    ("fuckheads", "fools"),
    ("fuckwit", "idiot"),
    ("fuckwits", "idiots"),
    ("fuckface", "jerk"),
    ("motherfucker", "scoundrel"),
    ("motherfuckers", "scoundrels"),
    ("motherfucking", "freaking"),
    ("clusterfuck", "disaster"),
    ("mindfuck", "confusion"),
    
    # Ass compounds (not standalone "ass" - that could mean donkey)
    ("asshole", "jerk"),
    ("assholes", "jerks"),
    ("asshat", "fool"),
    ("asshats", "fools"),
    ("assface", "jerk"),
    ("asswipe", "jerk"),
    ("asswipes", "jerks"),
    ("smartass", "wisecracker"),
    ("smartasses", "wisecrackers"),
    ("dumbass", "idiot"),
    ("dumbasses", "idiots"),
    ("jackass", "fool"),
    ("jackasses", "fools"),
    ("hardass", "tough person"),
    ("kickass", "great"),
    ("badass", "tough"),
    ("badasses", "tough ones"),
    ("fatass", "fatty"),
    ("lardass", "fatty"),
    
    # Damn family (standalone "damn" could be religious condemnation)
    ("damn", "darn"),
    ("damned", "darned"),
    ("goddamn", "cursed"),
    ("goddamned", "cursed"),
    ("goddamnit", "curses"),
    ("dammit", "curses"),
    ("damnit", "curses"),
    
    # Other insults
    ("bastards", "scoundrels"),  # Plural is usually insult, not "illegitimate children"
  
    # Blasphemy (when clearly expletive)
    ("chrissake", "goodness' sake"),
    ("chrissakes", "goodness' sake"),
]


def _preserve_case(original: str, replacement: str) -> str:
    """
    Apply the case pattern from original to replacement.
    
    Examples:
        _preserve_case("SHIT", "crud") -> "CRUD"
        _preserve_case("Shit", "crud") -> "Crud"
        _preserve_case("shit", "crud") -> "crud"
        _preserve_case("What the hell", "what on earth") -> "What on earth"
    """
    if original.isupper():
        return replacement.upper()
    elif original.islower():
        return replacement.lower()
    elif len(original) > 0 and original[0].isupper():
        # First letter is uppercase - capitalize first letter of replacement
        return replacement[0].upper() + replacement[1:] if replacement else replacement
    else:
        # Default to lowercase
        return replacement.lower()


def _create_word_pattern(word: str) -> re.Pattern:
    """Create a word-boundary regex pattern for a word."""
    # Escape special regex characters
    escaped = re.escape(word)
    # Use word boundaries, case insensitive
    return re.compile(r'\b' + escaped + r'\b', re.IGNORECASE)


def _create_phrase_pattern(phrase: str) -> re.Pattern:
    """Create a regex pattern for a phrase (may span word boundaries)."""
    escaped = re.escape(phrase)
    return re.compile(escaped, re.IGNORECASE)


def prefilter_language(text: str) -> str:
    """
    Apply regex replacements for unambiguous profanity before LLM processing.
    
    This function:
    1. Applies phrase replacements first (longer matches)
    2. Then applies single word replacements
    3. Preserves original case (SHIT->CRUD, Shit->Crud, shit->crud)
    
    Args:
        text: The input text to filter
        
    Returns:
        Text with unambiguous profanity replaced
    """
    result = text
    
    # Phase 1: Replace phrases (sorted by length, longest first)
    sorted_phrases = sorted(PHRASE_REPLACEMENTS, key=lambda x: len(x[0]), reverse=True)
    
    for phrase, replacement in sorted_phrases:
        pattern = _create_phrase_pattern(phrase)
        
        def phrase_replacer(match: re.Match) -> str:
            return _preserve_case(match.group(0), replacement)
        
        result = pattern.sub(phrase_replacer, result)
    
    # Phase 2: Replace single words
    for word, replacement in WORD_REPLACEMENTS:
        pattern = _create_word_pattern(word)
        
        def word_replacer(match: re.Match) -> str:
            return _preserve_case(match.group(0), replacement)
        
        result = pattern.sub(word_replacer, result)
    
    return result


def get_replacement_count(text: str) -> int:
    """
    Count how many replacements would be made without actually making them.
    Useful for statistics/logging.
    """
    count = 0
    
    # Count phrase matches
    sorted_phrases = sorted(PHRASE_REPLACEMENTS, key=lambda x: len(x[0]), reverse=True)
    temp_text = text
    
    for phrase, _ in sorted_phrases:
        pattern = _create_phrase_pattern(phrase)
        matches = pattern.findall(temp_text)
        count += len(matches)
        # Remove matches so we don't double-count overlaps
        temp_text = pattern.sub("", temp_text)
    
    # Count word matches
    for word, _ in WORD_REPLACEMENTS:
        pattern = _create_word_pattern(word)
        matches = pattern.findall(temp_text)
        count += len(matches)
    
    return count


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    # Test cases
    test_cases = [
        "What the hell is going on?",
        "WHAT THE HELL IS GOING ON?",
        "What The Hell Is Going On?",
        "This is bullshit!",
        "He's such an asshole.",
        "Son of a bitch!",
        "Oh shit, I forgot!",
        "That was a shitshow.",
        "Don't give a damn about it.",
        "The jackass kicked my ass.",
        "Go to hell!",
        "Shut the fuck up!",
        "For fuck's sake!",
        "He's a goddamn idiot.",
        "That motherfucker!",
        "I'm pissed off.",
        "This is fucked up.",
        # Edge cases - should NOT be replaced:
        "The bitch had puppies.",  # "bitch" alone not in our list
        "He was born a bastard.",  # "bastard" alone not in our list
        "Damn his soul to hell.",  # "damn" and "hell" alone not in our list
        "The ass carried the load.", # "ass" alone not in our list
    ]
    
    print("=" * 60)
    print("LANGUAGE PREFILTER TEST")
    print("=" * 60)
    
    for test in test_cases:
        result = prefilter_language(test)
        if test != result:
            print(f"\n  IN: {test}")
            print(f" OUT: {result}")
        else:
            print(f"\n  [NO CHANGE]: {test}")
    
    print("\n" + "=" * 60)
    print(f"Total phrase patterns: {len(PHRASE_REPLACEMENTS)}")
    print(f"Total word patterns: {len(WORD_REPLACEMENTS)}")
    print("=" * 60)
