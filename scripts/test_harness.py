#!/usr/bin/env python3
"""
BookWash Python Test Harness
----------------------------
Tests the full rating and cleaning pipeline using bookwash_llm.py.
Creates temporary .bookwash files, runs multi-pass cleaning, and verifies results.

Usage examples:
  # Run comprehensive test suite with full pipeline
  python scripts/test_harness.py --test-suite
  
  # Run rate-only (no cleaning, just rating verification)
  python scripts/test_harness.py --test-suite --rate-only
  
  # Run holdout suite
  python scripts/test_harness.py --holdout
  
  # Test a custom paragraph
  python scripts/test_harness.py --text "Some content here" --expected-language PG

Environment:
  Set GEMINI_API_KEY for API calls.
"""

import argparse
import os
import sys
import time
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import functools
print = functools.partial(print, flush=True)

# Import the actual bookwash_llm module
try:
    from scripts import bookwash_llm
except ImportError:
    import bookwash_llm


class Rating(Enum):
    G = 1
    PG = 2
    PG13 = 3
    R = 4
    X = 5


def parse_rating(s: str) -> Rating:
    """Parse rating string to enum."""
    s = s.upper().strip().replace('-', '')
    if s == 'G':
        return Rating.G
    elif s == 'PG':
        return Rating.PG
    elif s in ('PG13', 'PG 13'):
        return Rating.PG13
    elif s == 'R':
        return Rating.R
    elif s in ('X', 'UNRATED', 'NC17', 'NC-17'):
        return Rating.X
    else:
        raise ValueError(f"Unknown rating: {s}")


def rating_to_str(r: Rating) -> str:
    """Convert rating enum to string."""
    if r == Rating.PG13:
        return "PG-13"
    return r.name


def rating_to_level(r: Rating) -> int:
    """Convert rating enum to numeric level (1-5)."""
    return r.value


@dataclass
class TestParagraph:
    """A test paragraph with expected ratings."""
    text: str
    category: str  # 'language', 'adult', 'violence'
    expected_rating: Rating
    label: str


@dataclass
class TestResult:
    """Result of a single test."""
    label: str
    category: str
    expected_rating: Rating
    pre_clean_rating: Optional[Rating] = None
    post_clean_rating: Optional[Rating] = None
    target_rating: Rating = Rating.PG  # Default target
    num_changes: int = 0
    passes_used: int = 0
    pre_clean_match: bool = False
    post_clean_meets_target: bool = False
    error: Optional[str] = None


@dataclass
class ConfusionMatrix:
    """Track rating prediction accuracy."""
    true_positives: int = 0   # Correctly identified content that should be filtered
    false_positives: int = 0  # Incorrectly flagged content as needing filtering
    true_negatives: int = 0   # Correctly identified clean content
    false_negatives: int = 0  # Missed content that should be filtered
    
    def record(self, expected_needs_filter: bool, actual_needs_filter: bool):
        """Record a result."""
        if expected_needs_filter and actual_needs_filter:
            self.true_positives += 1
        elif not expected_needs_filter and actual_needs_filter:
            self.false_positives += 1
        elif not expected_needs_filter and not actual_needs_filter:
            self.true_negatives += 1
        else:  # expected but not actual
            self.false_negatives += 1
    
    @property
    def total(self) -> int:
        return self.true_positives + self.false_positives + self.true_negatives + self.false_negatives
    
    @property
    def accuracy(self) -> float:
        return (self.true_positives + self.true_negatives) / self.total if self.total > 0 else 0.0
    
    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0
    
    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0
    
    def print_summary(self, name: str):
        print(f"\n[{name} Filter]")
        print(f"  TP: {self.true_positives}  FP: {self.false_positives}")
        print(f"  FN: {self.false_negatives}  TN: {self.true_negatives}")
        print(f"  Accuracy: {self.accuracy * 100:.1f}%")
        if self.true_positives + self.false_negatives == 0:
            print("  Precision: N/A (no positive cases)")
            print("  Recall: N/A (no positive cases)")
        else:
            print(f"  Precision: {self.precision * 100:.1f}%")
            print(f"  Recall: {self.recall * 100:.1f}%")


def build_test_suite() -> List[TestParagraph]:
    """Build the main test corpus."""
    return [
        # LANGUAGE - G: no profanity
        TestParagraph(
            text='''The astronomy club met just after dusk, laptops glowing while the horizon still held a thin lavender band. Their advisor outlined the schedule for the meteor watch, careful and methodical, inviting quiet questions.
They unpacked the tripod mounts and calibration charts. Conversation stayed practical—exposure values, predicted cloud drift, alignment tolerances. No one bickered; they simply adjusted lenses and compared readings.
During a brief break, two students traded notes about future internships at observatories. The tone remained professional, curious rather than competitive, focused on techniques they hoped to master.''',
            category='language',
            expected_rating=Rating.G,
            label='G-Language: technical astronomy collaboration, neutral tone',
        ),
        
        # LANGUAGE - PG: mild exclamations only (darn, gosh, heck)
        TestParagraph(
            text='''The community theater rehearsal lurched forward. "Golly, that cue was early," Mara said, grinning as the prop mailbox toppled harmlessly. Someone muttered a cheerful "jeez" while resetting the scene markers.
They tried the scene again; a missed lighting change prompted a gentle "darn, I'll tighten that timing." The director responded with a calm nod, jotting a timing fix. No sharp words, only mild exclamations peppered the adjustments.
Backstage, two volunteers wrestled with tangled extension cords. "Heck, these knots have personalities," one joked. Laughter stayed light; frustration expressed through allowed gentle terms.''',
            category='language',
            expected_rating=Rating.PG,
            label='PG-Language: rehearsal with mild exclamations only',
        ),
        
        # LANGUAGE - PG-13: moderate profanity (damn, hell, crap) but no f-word or s-word
        TestParagraph(
            text='''The regional newsroom hummed around deadline. "This layout is damn cramped," Felix said, nudging columns. The editor acknowledged without flinching, sliding ads a notch. Pressure showed, but profanity stayed mid-level.
"Crap, the data feed stalled again," a designer groaned, refreshing analytics. Another replied, "Hell, reroute through the mirror—faster than waiting." Cooperative urgency surfaced in clipped phrases.
Draft headlines traded quick revisions: a misplaced stat corrected, a quote trimmed. "Assumption here is shaky—rephrase," the copy chief advised. No f-word or s-word surfaced; only moderate newsroom gristle.''',
            category='language',
            expected_rating=Rating.PG13,
            label='PG-13-Language: newsroom moderate profanity (no f-word or s-word)',
        ),
        
        # LANGUAGE - R: strong profanity including f-word
        TestParagraph(
            text='''The startup war room burned with overtime glare. "This fucking deploy pipeline is choking again," Rina snapped, slamming a log window wider. Logs spat stack traces; someone swore under their breath.
"We promised that client a working build by dawn—fix the auth proxy," another engineer pushed. Chairs creaked as they pivoted across terminals.
Memory leaks triggered cascading restarts. "Kill that bastard process and patch the config," Rina ordered. A teammate: "Already killed—fucked cache index was corrupt." Rapid, harsh language braided into technical triage.''',
            category='language',
            expected_rating=Rating.R,
            label='R-Language: high-intensity technical meltdown with f-word',
        ),
        
        # LANGUAGE - R: s-word (shit) - CRITICAL TEST
        TestParagraph(
            text='''The meeting derailed quickly. "This is complete shit," Marcus said, tossing the proposal aside. The room fell silent. No one had expected him to be so blunt about the quality.
"I mean, look at these numbers," he continued. "They're bullshit. Someone clearly didn't check the calculations." A few nervous glances were exchanged around the table.''',
            category='language',
            expected_rating=Rating.R,
            label='R-Language: contains "shit" and "bullshit" - should exceed PG',
        ),
        
        # LANGUAGE - R: subtle profanity (shit in compound word)
        TestParagraph(
            text='''It was a shitshow from the start. The equipment failed, the catering was late, and half the guests got lost on the way. Someone called it a "clusterfuck of epic proportions."''',
            category='language',
            expected_rating=Rating.R,
            label='R-Language: contains "shitshow" and "clusterfuck"',
        ),
        
        # LANGUAGE - R: single strong word in otherwise clean text
        TestParagraph(
            text='''The garden was beautiful in spring, with roses blooming along the fence and butterflies dancing over the lavender. Mrs. Henderson tended her tomatoes with care. "Well, shit," she muttered when she noticed the aphids had returned.''',
            category='language',
            expected_rating=Rating.R,
            label='R-Language: single "shit" in clean context - should still be R',
        ),
        
        # LANGUAGE - PG-13: creative "ass" compounds
        TestParagraph(
            text='''"You absolute jackass," Mira said, though she was half-smiling. "Who plans a road trip without checking the gas gauge?" 
Tom shrugged. "It seemed like a good idea at the time."
"That's the most assbackward logic I've ever heard," she replied, shaking her head. "We're stuck in the middle of nowhere because you're a complete ass."''',
            category='language',
            expected_rating=Rating.PG13,
            label='PG-13-Language: creative ass compounds (jackass, assbackward)',
        ),
        
        # LANGUAGE - PG-13: creative "damn" and "hell" usage
        TestParagraph(
            text='''The old mechanic wiped his hands on a rag. "Well I'll be damned," he muttered, peering under the hood. "This engine's been through hell and back."
"Can you fix it?" Sarah asked hopefully.
"Fix it? Darlin', this thing's held together with prayers and pure damnation. But I'll give it a helluva try."''',
            category='language',
            expected_rating=Rating.PG13,
            label='PG-13-Language: creative damn/hell variants (damned, damnation, helluva)',
        ),
        
        # LANGUAGE - PG-13: "bastard" in various forms
        TestParagraph(
            text='''The inheritance letter arrived on a Tuesday. "So the old bastard finally kicked it," James said without emotion. His sister frowned.
"Don't speak ill of the dead."
"Why not? He was a cold-hearted son of a bitch who never gave us the time of day." James crumpled the letter. "Bastardized the whole family name with his schemes."''',
            category='language',
            expected_rating=Rating.PG13,
            label='PG-13-Language: bastard, son of a bitch, bastardized',
        ),
        
        # LANGUAGE - R: creative f-word compounds
        TestParagraph(
            text='''The band's tour bus broke down for the third time that week. "This is un-fucking-believable," the drummer groaned.
"Abso-fucking-lutely," agreed the bassist. "Our manager is a grade-A fuckwit for booking this rust bucket."
The lead singer just laughed. "Welcome to rock and roll, you magnificent fuckers."''',
            category='language',
            expected_rating=Rating.R,
            label='R-Language: creative f-word infixes and compounds',
        ),
        
        # LANGUAGE - R: creative shit compounds
        TestParagraph(
            text='''"I don't give a rat's ass about your excuses," the coach bellowed. "That was some chickenshit playing out there!"
The team hung their heads.
"You played like absolute horseshit. Batshit crazy decisions, one after another. Get your shit together or we're done."''',
            category='language',
            expected_rating=Rating.R,
            label='R-Language: creative shit compounds (chickenshit, horseshit, batshit)',
        ),
        
        # ADULT - G: no romantic content
        TestParagraph(
            text='''Two siblings cataloged seashells along a quiet shoreline, debating the Latin names with playful precision. Their conversation remained purely academic, trading field guide page numbers.
They paused to compare spiral patterns, noting erosion differences. Cooperation felt easy—familial, non-romantic, comfortably neutral.
Lunch under a weathered pier involved sharing simple sandwiches and discussing school projects. No suggestive remarks appeared; focus stayed on the classification task.''',
            category='adult',
            expected_rating=Rating.G,
            label='G-Adult: sibling scientific collaboration, no romance',
        ),
        
        # ADULT - PG: mild budding romance, brief hug
        TestParagraph(
            text='''During a weekend volunteer shift at a community garden, two participants compared seedling trays. Conversation was light—soil moisture, sprouting rates. Friendly rapport, nothing charged.
They coordinated watering sequence, briefly brushing hands while passing a trowel. A gentle smile; no escalation beyond mild connection.
As they packed tools, he asked about joining a small group hike later. She agreed; tone hopeful but soft. A brief, simple hug goodbye—no lingering.''',
            category='adult',
            expected_rating=Rating.PG,
            label='PG-Adult: budding interest with mild affectionate gestures',
        ),
        
        # ADULT - PG-13: sustained kissing, implied intimacy but no explicit detail
        TestParagraph(
            text='''A late gallery opening left two visitors wandering quiet halls. Their conversation thinned into charged pauses near a luminous abstract. Fingers grazed while gesturing at texture; neither withdrew.
Outside on the terrace cool air tightened the mood. He stepped closer; they shared a long, deep kiss—hands at waist and jaw, bodies aligned. Breath hitched but no explicit anatomical detail surfaced.
Cab ride narrated art impressions while knees touched—a subtle tension, nothing explicit stated. Arrival at her building ended with an embrace and one final intensifying kiss that tapered naturally. Door closing implied the rest, fade-to-black without explicit act terms.''',
            category='adult',
            expected_rating=Rating.PG13,
            label='PG-13-Adult: sustained kissing with implied intimacy, no explicit detail',
        ),
        
        # ADULT - PG-13: suggestive body descriptions
        TestParagraph(
            text='''Eyes locked on that full, slightly moist lip, Kip gulped. She had turned into a woman in the time she'd been away. Her skirt did swoosh back and forth in a most pleasing manner as she walked, revealing slim, well-turned calves.''',
            category='adult',
            expected_rating=Rating.PG13,
            label='PG-13-Adult: suggestive body focus, gaze on lips/calves',
        ),
        
        # ADULT - R: explicit encounter
        TestParagraph(
            text='''Rain hammered the loft's skylight as they shed damp jackets. Lips met with urgent focus; hands traced contours under thinning lamplight. Shirts lifted; warm skin contact deepened.
She guided his hand over her torso; he responded with deliberate, intimate strokes. Soft sounds marked escalating arousal while they moved toward the couch.
Clothing slid aside—bare skin against fabric, descriptive tactile detail of pressure and rhythm building. Gasps and low moans framed the encounter. He kissed along her lower abdomen; she arched, directing pace.''',
            category='adult',
            expected_rating=Rating.R,
            label='R-Adult: explicit encounter, sustained explicit tactile detail',
        ),
        
        # VIOLENCE - G: purely verbal dispute
        TestParagraph(
            text='''A town hall dispute unfolded over funding priorities. Voices rose, but participants stayed behind tables. Words like "escalate" and "conflict" appeared in arguments, yet no one crossed into physical threat.
One speaker warned that ignoring infrastructure could "invite future violence"—an abstract projection, not an immediate act. Others countered with economic stats.
Gestures sharpened: pointed fingers, firm hand chops on lecterns. Security observed, non-intervening, as discourse remained verbal only.''',
            category='violence',
            expected_rating=Rating.G,
            label='G-Violence: purely verbal civic dispute, abstract threats only',
        ),
        
        # VIOLENCE - PG: minor contact, no blood
        TestParagraph(
            text='''Youth league soccer scrimmage ran energetic but mostly clean. A midfield bump sent one player sliding harmlessly; they stood quickly, dusting off.
Later a misjudged tackle caused a brief tumble—coach shouted reminders about form. No blood, only a grass stain on a sleeve.
Near end, an accidental elbow brushed a shoulder during a leap; apology exchanged instantly, situation defused. Game closed with handshakes and casual jokes.''',
            category='violence',
            expected_rating=Rating.PG,
            label='PG-Violence: youth soccer minor contact, no injury detail',
        ),
        
        # VIOLENCE - PG-13: weapon threat, minor blood
        TestParagraph(
            text='''Urban alley pursuit: a fleeing courier clipped a trash bin, drawing a swift shout. Chaser vaulted debris; tension climbed.
Corner turn produced a stumble—palms scraped, a thin line of blood forming but quickly ignored as running resumed.
The chased individual brandished a small pocket knife defensively; light gleamed off the blade. No stab yet—threat posture only.
A tackle finally landed; both hit damp pavement. Knife skittered aside, leaving a shallow cut on a forearm—crimson bead visible, not gory.''',
            category='violence',
            expected_rating=Rating.PG13,
            label='PG-13-Violence: pursuit with minor blood and weapon threat',
        ),
        
        # VIOLENCE - R: graphic injuries
        TestParagraph(
            text='''The siege breach detonated with concussive force, splintering inner gate beams. Fragments lanced outward, embedding in exposed arms and shoulders—quick dark streaks marking initial wounds.
Inside the courtyard, close-quarter clashes yielded slashes that opened muscle; steam-like breath mingled with rising metallic scent. A defender coughed crimson onto flagstones.
One combatant's thigh was pierced; blood pumped rhythmically until a rough tourniquet cinched. Bone showed momentarily through a shattered wrist guard in another exchange.''',
            category='violence',
            expected_rating=Rating.R,
            label='R-Violence: siege battle with graphic wounds and gore detail',
        ),
        
        # SUBTLE ADULT - Innuendo (should be PG-13+)
        TestParagraph(
            text='''He picked up the banana from the fruit bowl, making deliberate eye contact as he slowly peeled it. "You know," he said with a sly grin, running his tongue along the tip, "I've always loved these." She shifted in her seat, feeling her cheeks flush.''',
            category='adult',
            expected_rating=Rating.R,
            label='R-Adult: obvious fruit euphemism innuendo',
        ),
        
        # SUBTLE ADULT - Sexual tension/arousal
        TestParagraph(
            text='''Their eyes met across the crowded room. Her pulse quickened as he approached, his cologne wrapping around her senses. When he leaned in to whisper, his breath warm against her ear, she felt a familiar heat pool in her stomach. Her fingers trembled slightly as they brushed his arm.''',
            category='adult',
            expected_rating=Rating.PG13,
            label='PG-13-Adult: sexual tension and arousal cues',
        ),
        
        # SUBTLE ADULT - Almost moment
        TestParagraph(
            text='''They were alone in the elevator when it stopped between floors. He turned to her, eyes dark with unspoken intention. One step closer. Her back found the wall. His hand rose, hovering near her cheek. "If we weren't at the office..." he breathed. The elevator lurched, lights flickering back on.''',
            category='adult',
            expected_rating=Rating.PG13,
            label='PG-13-Adult: almost moment with implied desire',
        ),
        
        # SUBTLE ADULT - Morning after implication
        TestParagraph(
            text='''She woke to unfamiliar sheets and the smell of coffee. Fragments of the night returned—the bar, the dancing, the taxi. Her dress lay crumpled by the door. He appeared in the doorway wearing only boxers, two steaming mugs in hand. "Good morning. Sleep well?"''',
            category='adult',
            expected_rating=Rating.PG13,
            label='PG-13-Adult: morning after with implied activity',
        ),
        
        # SUBTLE ADULT - Chest focus (should be PG-13)
        TestParagraph(
            text='''Kip followed Liv through the hall. She was as slender as he was fat. Her eyes large lucid brown, her skin smooth and clear. Thank Orholam, at least her chest was bigger than his. He tried not to stare.''',
            category='adult',
            expected_rating=Rating.PG13,
            label='PG-13-Adult: chest size comparison with trying not to stare',
        ),
    ]


def build_holdout_suite() -> List[TestParagraph]:
    """Build holdout validation corpus with different domains."""
    return [
        # LANGUAGE HOLDOUT
        TestParagraph(
            text='''Students rotated through a planetarium exhibit, recording star positions without commentary beyond coordinate values. The guide quietly adjusted the projector focus. No casual exclamations surfaced; tone stayed instructional and plain.''',
            category='language',
            expected_rating=Rating.G,
            label='G-Language-Holdout: neutral planetarium lab session',
        ),
        TestParagraph(
            text='''Community robotics club wrestled with a stubborn servo. "Gosh this bracket is snug," one said, easing tension screws. Another added, "Darn calibration slipped again." Mild exclamations broke technical focus but stayed gentle.''',
            category='language',
            expected_rating=Rating.PG,
            label='PG-Language-Holdout: robotics troubleshooting with mild exclamations',
        ),
        TestParagraph(
            text='''Editorial team argued layout timing. "Damn sidebar bleeds into the footer," an assistant noted. Another replied, "Hell, just nudge the grid." Minor stress language appeared repeatedly without any f-word variants.''',
            category='language',
            expected_rating=Rating.PG13,
            label='PG13-Language-Holdout: newsroom moderate profanity',
        ),
        TestParagraph(
            text='''Overnight warehouse audit deteriorated. "This fucking scanner froze again," the supervisor snapped. A clerk muttered, "Shit, inventory count corrupted." Strong profanity peppered rapid instructions.''',
            category='language',
            expected_rating=Rating.R,
            label='R-Language-Holdout: warehouse audit with strong profanity',
        ),
        
        # ADULT HOLDOUT
        TestParagraph(
            text='''Consultants reviewed quarterly compliance matrices, exchanging only formal clarifications. Seating distance remained professional; no personal remarks or romantic shading—pure task alignment for hours.''',
            category='adult',
            expected_rating=Rating.G,
            label='G-Adult-Holdout: strictly professional compliance meeting',
        ),
        TestParagraph(
            text='''Two volunteers closed up a library event, sharing a quick side hug after stacking chairs. A soft smile and a polite "See you Tuesday"—no sustained physical contact, just mild budding friendliness.''',
            category='adult',
            expected_rating=Rating.PG,
            label='PG-Adult-Holdout: brief hug, mild friendly warmth',
        ),
        TestParagraph(
            text='''They lingered outside the tram station. A series of deep kisses, hands resting at waist and shoulder. Breathless pause; a quiet agreement to head home separately. Implied attraction, no anatomical detail.''',
            category='adult',
            expected_rating=Rating.PG13,
            label='PG13-Adult-Holdout: sustained kissing, implied intimacy only',
        ),
        TestParagraph(
            text='''Inside the dim studio they undressed between staggered kisses. Palms traced hips and chest; clothing dropped. Clear mutual movement, explicit caresses, bodies aligned in rhythmic thrusts described through pressure and pace.''',
            category='adult',
            expected_rating=Rating.R,
            label='R-Adult-Holdout: explicit encounter, non-pornographic detail',
        ),
        
        # VIOLENCE HOLDOUT
        TestParagraph(
            text='''Debate club final round escalated vocally—rapid rebuttals, clipped tone, pointed rhetorical flourishes. No physical advance, only emphatic gestures. Entire confrontation non-physical.''',
            category='violence',
            expected_rating=Rating.G,
            label='G-Violence-Holdout: verbal debate only',
        ),
        TestParagraph(
            text='''Trail run collision: two joggers bumped shoulders at a narrow turn, one stumbling to a knee. Quick stand, minor wince, no blood described. They exchanged apologies and resumed pace.''',
            category='violence',
            expected_rating=Rating.PG,
            label='PG-Violence-Holdout: minor trail collision, no blood',
        ),
        TestParagraph(
            text='''Back alley confrontation: a pocket knife flashed; defender's forearm received a shallow cut, thin blood line forming before pressure was applied. Brief grapple, weapon kicked aside. No gore.''',
            category='violence',
            expected_rating=Rating.PG13,
            label='PG13-Violence-Holdout: knife threat with minor blood',
        ),
        TestParagraph(
            text='''Warehouse brawl: pipe strike fractured a hand—knuckles split, bone edge visible momentarily. A gash at the scalp leaked dark streaks down collar. One fighter coughed thick blood after a solar plexus blow.''',
            category='violence',
            expected_rating=Rating.R,
            label='R-Violence-Holdout: brief graphic fight injuries',
        ),
    ]


def rate_text(text: str, model: str = "gemini-1.5-flash") -> dict:
    """Rate text using bookwash_llm.py logic."""
    import google.generativeai as genai
    
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    
    genai.configure(api_key=api_key)
    
    # Use the same rating prompt from bookwash_llm.py with proper definitions
    rating_prompt = f'''You are a content rating assistant. Rate the following text for:
1. Language/Profanity (G, PG, PG-13, R, X)
2. Adult/Sexual Content (G, PG, PG-13, R, X)  
3. Violence (G, PG, PG-13, R, X)

LANGUAGE RATING SCALE:
- G: No profanity or insults at all
- PG: Only very mild exclamations (darn, gosh, gee, jeez, heck)
- PG-13: Moderate profanity (damn, hell, crap, ass, bastard) but NO f-word or s-word
- R: Strong profanity including f-word (fuck, fucking) or s-word (shit, bullshit, shitty)
- X: Extreme sexual profanity or hate slurs

CRITICAL: Words like "shit", "bullshit", "shitshow", "fuck", "fucking" are R-level and MUST be rated R!

ADULT/SEXUAL CONTENT RATING SCALE:
- G: No romantic/sexual content, no body-focused descriptions
- PG: Light romance (hand-holding, brief kiss), no suggestive body descriptions
- PG-13: Passionate kissing, implied intimacy (fade-to-black), OR suggestive clothing/body descriptions (cleavage, tight/revealing clothes, bare skin emphasis, physical attractiveness focus)
- R: Descriptive sexual scenes, sustained intimate detail, OR explicit body descriptions focusing on breasts, thighs, buttocks, or other sensual areas
- X: Explicit sexual activity described graphically

VIOLENCE RATING SCALE:
- G: No physical violence (arguments only)
- PG: Mild action, non-detailed scuffles, no blood
- PG-13: Combat, injuries, some blood, weapon use without gore detail
- R: Graphic injury detail, notable gore, intense sustained violence
- X: Extreme gore/torture, sadistic detail

Be vigilant for SUBTLE adult content:
- Innuendo & double entendres (suggestive language with dual meanings)
- Sexual tension cues (quickened pulse, flushed cheeks, trembling from attraction)
- Suggestive body descriptions (focusing on lips, curves, calves, chest)
- "Almost" moments (interrupted intimacy, near-kisses with tension)
- Implied/off-screen activity (morning-after scenes, disheveled appearance)

Respond with ONLY a JSON object in this format:
{{"language": "X", "adult": "X", "violence": "X"}}

Text to rate:
{text}'''

    model_instance = genai.GenerativeModel(model)
    response = model_instance.generate_content(rating_prompt)
    
    import json
    import re
    
    # Extract JSON from response
    response_text = response.text.strip()
    # Try to find JSON in the response
    json_match = re.search(r'\{[^}]+\}', response_text)
    if json_match:
        return json.loads(json_match.group())
    else:
        raise ValueError(f"Could not parse rating response: {response_text}")


def run_test_suite(paragraphs: List[TestParagraph], rate_only: bool = False, model: str = "gemini-1.5-flash"):
    """Run test suite and compute confusion matrices."""
    
    # Separate matrices for each category
    matrices = {
        'language': ConfusionMatrix(),
        'adult': ConfusionMatrix(),
        'violence': ConfusionMatrix(),
    }
    
    # Track detailed results
    results = []
    
    print(f"\n{'='*60}")
    print(f"Running {'rate-only' if rate_only else 'full'} test suite with model: {model}")
    print(f"{'='*60}\n")
    
    for i, para in enumerate(paragraphs, 1):
        print(f"[{i}/{len(paragraphs)}] {para.label}")
        print(f"  Expected: {para.category}={rating_to_str(para.expected_rating)}")
        
        try:
            ratings = rate_text(para.text, model=model)
            
            # Map category name to response key
            category_key = para.category
            if category_key == 'adult':
                category_key = 'adult'
            
            actual_str = ratings.get(category_key, 'G')
            actual = parse_rating(actual_str)
            
            print(f"  Actual:   {category_key}={rating_to_str(actual)}")
            
            # For confusion matrix: "needs filter" means rating > G for the category
            # We test at PG level (filter anything > G)
            expected_needs_filter = para.expected_rating.value > Rating.G.value
            actual_needs_filter = actual.value > Rating.G.value
            
            matrices[para.category].record(expected_needs_filter, actual_needs_filter)
            
            # Check if rating matches expected
            match = actual == para.expected_rating
            status = "✅" if match else "❌"
            print(f"  Result:   {status} {'Match' if match else f'Expected {rating_to_str(para.expected_rating)}, got {rating_to_str(actual)}'}")
            
            results.append({
                'label': para.label,
                'expected': para.expected_rating,
                'actual': actual,
                'match': match,
            })
            
            # Rate limit pause
            time.sleep(1.0)
            
        except Exception as e:
            print(f"  Error: {e}")
            results.append({
                'label': para.label,
                'expected': para.expected_rating,
                'actual': None,
                'match': False,
                'error': str(e),
            })
        
        print()
    
    # Print confusion matrices
    print("\n" + "="*60)
    print("CONFUSION MATRIX SUMMARY (filter threshold: > G)")
    print("="*60)
    
    for category, matrix in matrices.items():
        if matrix.total > 0:
            matrix.print_summary(category.title())
    
    # Print overall stats
    total_tests = len(results)
    correct = sum(1 for r in results if r['match'])
    errors = sum(1 for r in results if r.get('error'))
    
    print("\n" + "="*60)
    print("OVERALL RESULTS")
    print("="*60)
    print(f"Total tests: {total_tests}")
    print(f"Correct ratings: {correct} ({correct/total_tests*100:.1f}%)")
    print(f"Incorrect ratings: {total_tests - correct - errors} ({(total_tests - correct - errors)/total_tests*100:.1f}%)")
    print(f"Errors: {errors}")
    
    return results, matrices


@dataclass
class PipelineTestChapter:
    """A test chapter for full pipeline testing."""
    name: str                    # Short name for the test
    paragraphs: List[str]        # List of paragraph texts
    expected_original_ratings: dict  # {'language': Rating, 'adult': Rating, 'violence': Rating}
    target_ratings: dict         # {'language': int, 'adult': int, 'violence': int} - target levels (1-5)
    
    def get_content(self) -> str:
        """Join paragraphs with double newlines."""
        return '\n\n'.join(self.paragraphs)


def build_pipeline_test_chapters() -> List[PipelineTestChapter]:
    """Build test chapters for full pipeline testing.
    
    Each chapter contains multiple paragraphs in different genres that together 
    should trigger a specific rating level. After cleaning, all should meet targets.
    
    Genres: Sci-Fi, Fantasy, True Crime, Historical Fiction, Horror, Romance, Thriller
    """
    return [
        # =======================================================================
        # TEST 1: SCI-FI - R-level language in space station crisis
        # =======================================================================
        PipelineTestChapter(
            name="SciFi-Language-SpaceStation",
            paragraphs=[
                '''Commander Yuki Tanaka floated through the central hub of Orbital Station Kepler-7, her magnetic boots clicking against the deck plates as she surveyed the damage. The meteor shower had punched through three hull sections, and the emergency seals were holding—barely. Red warning lights pulsed along every corridor, casting everything in an apocalyptic glow. Through the observation port, she could see debris from their destroyed solar array tumbling slowly into the void.''',
                
                '''"What's our oxygen situation?" she asked into her comm, already dreading the answer. Chief Engineer Okonkwo's voice crackled back with barely contained panic. "It's complete bullshit, Commander. The recyclers are running at thirty percent capacity. We've got maybe eighteen hours before CO2 levels become critical." He paused, and she heard him kick something metallic. "The backup systems are fucked—meteor fragment went right through the goddamn filtration matrix."''',
                
                '''Tanaka pulled up the station schematic on her wrist display, her mind racing through contingencies. Forty-two souls aboard, three months from the nearest rescue vessel. "What about the emergency pods?" she asked. Okonkwo laughed bitterly. "Half of them are slag, Commander. The ones that work can hold maybe twenty people. We'd have to choose who lives and who stays behind to suffocate. This whole situation is a complete shitshow."''',
                
                '''She closed her eyes, forcing herself to breathe slowly despite the stale taste of recycled air. There had to be another way. "Get me Dr. Reeves from xenobiology," she ordered. "And tell everyone to stay calm. We're not dying out here—I don't give a damn what the numbers say." As she pushed off toward the command module, she wondered if she actually believed her own words, or if she was just too stubborn to admit when they were screwed.''',
                
                '''The station groaned around her, metal flexing in ways it wasn't designed to flex. Somewhere below, she heard the hiss of another micro-leak being sealed. Eighteen hours. She'd pulled off miracles before, but never with stakes this high. Never with this many lives hanging on her decisions. "Alright, you bastard universe," she muttered to herself. "Let's see what you've got."''',
            ],
            expected_original_ratings={'language': Rating.R, 'adult': Rating.G, 'violence': Rating.G},
            target_ratings={'language': 2, 'adult': 2, 'violence': 5},  # PG language target
        ),
        
        # =======================================================================
        # TEST 2: FANTASY - PG-13 language in magical academy
        # =======================================================================
        PipelineTestChapter(
            name="Fantasy-Language-MageAcademy",
            paragraphs=[
                '''Apprentice Theron Blackwood stared at the smoldering crater where his summoning circle had been, acrid smoke curling up from the scorched flagstones. The salamander he'd attempted to conjure was nowhere to be seen—instead, a very confused and very angry badger sat in the center of the ritual space, chittering at him with obvious malice. Behind him, he heard Master Aldric's heavy sigh, a sound that had become depressingly familiar over the past semester.''',
                
                '''"Damn it, Blackwood," the old mage said, pinching the bridge of his nose. "That's the third misfire this week. What the hell kind of incantation did you use?" He gestured, and the badger vanished in a puff of lavender smoke, returned to whatever forest it had been minding its own business in. "The pronunciation guide exists for a reason, boy. 'Ignis' and 'Irritus' are entirely different words with entirely different outcomes."''',
                
                '''Theron's face burned with embarrassment as the other apprentices snickered behind their textbooks. Elara Moonwhisper, naturally, had conjured a perfect salamander on her first try—it now curled contentedly around her wrist like living jewelry, its scales flickering with inner fire. "Perhaps," she said sweetly, "if Blackwood spent less time in the tavern and more time studying, he wouldn't summon woodland creatures by accident."''',
                
                '''"Oh, crap off, Moonwhisper," Theron muttered, gathering his scattered notes. His familiar, a sardonic raven named Inkblot, landed on his shoulder and made a sound suspiciously like laughter. "You're not helping," he told the bird. Master Aldric raised an eyebrow at his language but said nothing—they'd had that particular discussion before, and the old mage had reluctantly accepted that Theron's vocabulary was a lost cause.''',
                
                '''As the class filed out, Theron lingered, staring at the scorch marks on the floor. His father had been the greatest summoner of his generation, able to call forth beings of pure elemental fury with a whispered word. And here was Theron, his only heir, accidentally teleporting badgers. "Damn," he said softly to himself, then louder: "Damn, damn, damn." Inkblot cawed in what might have been sympathy. Or mockery. With that bird, it was impossible to tell.''',
            ],
            expected_original_ratings={'language': Rating.PG13, 'adult': Rating.G, 'violence': Rating.G},
            target_ratings={'language': 3, 'adult': 2, 'violence': 5},  # PG-13 language target (should pass as-is)
        ),
        
        # =======================================================================
        # TEST 3: HISTORICAL ROMANCE - R-level adult content in Regency era
        # =======================================================================
        PipelineTestChapter(
            name="HistoricalRomance-Adult-Regency",
            paragraphs=[
                '''Lady Arabella Ashworth had scandalized society before—wearing trousers to a hunt, refusing three perfectly acceptable proposals, publicly contradicting the Duke of Wessex on matters of philosophy—but nothing had prepared her for the scandal of finding herself alone in Lord Blackmoore's private library at midnight. The masquerade ball continued below, a distant symphony of laughter and music, while she stood frozen before the man who had haunted her thoughts for an entire season.''',
                
                '''"You shouldn't be here," she whispered, though she made no move toward the door. The candlelight caught the silver threads in his mask, turning his eyes into pools of shadow and flame. "Neither should you," he replied, his voice low and rough as unpolished stone. "And yet." He stepped closer, and she caught the scent of sandalwood and something darker, more dangerous. Her heart hammered against her corset stays.''',
                
                '''When he kissed her, it was nothing like the chaste pecks she'd received from hopeful suitors. His mouth claimed hers with an urgency that left her gasping, his hands finding the curve of her waist, the arch of her back. She pressed against him, propriety forgotten, feeling the heat of his body through the thin silk of her gown. His fingers traced slowly up her spine, finding the delicate buttons at her nape, and she shivered as cool air touched newly exposed skin.''',
                
                '''The gown pooled at her feet like spilled moonlight. His hands explored the swell of her hips, the softness of her breasts above her corset, and she arched into his touch with a soft moan. "We shouldn't," she breathed, even as she pulled him toward the chaise lounge. "No," he agreed, his lips tracing fire down her throat, "we absolutely should not." But neither of them stopped. The clock on the mantle struck one as they fell together onto velvet cushions, a tangle of limbs and whispered names and pleasure that built like a symphony reaching its crescendo.''',
                
                '''Afterward, she lay in his arms, her hair tumbled loose across his chest, watching the candles gutter low. Tomorrow there would be consequences—society's censure, her family's disappointment, the impossible choice between reputation and desire. But that was tomorrow. Tonight, she traced patterns on his skin and listened to his heartbeat slow, and allowed herself to pretend that this stolen moment could last forever.''',
            ],
            expected_original_ratings={'language': Rating.G, 'adult': Rating.R, 'violence': Rating.G},
            target_ratings={'language': 2, 'adult': 2, 'violence': 5},  # PG adult target
        ),
        
        # =======================================================================
        # TEST 4: TRUE CRIME/HORROR - R-level violence in serial killer investigation  
        # =======================================================================
        PipelineTestChapter(
            name="TrueCrime-Violence-SerialKiller",
            paragraphs=[
                '''Detective Maria Santos had seen a lot of death in her fifteen years with Homicide, but nothing had prepared her for what waited in the basement of 1847 Millbrook Lane. The smell hit her first—copper and rot and something chemical, like formaldehyde mixed with decay. Her flashlight beam cut through the darkness, illuminating concrete walls covered with photographs, hundreds of them, arranged in meticulous grids. All faces. All women. All smiling, unaware of what was coming.''',
                
                '''The first body was positioned in a chair, hands folded primly in what remained of its lap. The killer had taken his time with this one—surgical incisions traced patterns across the torso, skin peeled back to expose muscle and bone in a grotesque anatomical display. Blood had pooled beneath the chair, dried to a dark crust that crackled under Santos's boots. The victim's eyes were gone, replaced with polished river stones that caught the light with obscene cheerfulness.''',
                
                '''She found the second victim on the workbench, and this time she had to step outside to vomit. The body had been partially disassembled, organs arranged in labeled jars like specimens in a medical school laboratory. The heart sat in a place of honor on a small pedestal, pierced through with a surgical needle trailing red thread. A handwritten note beside it read: "She gave me her heart. I kept it."''',
                
                '''The forensics team worked through the night, cataloging horrors that would haunt their dreams for years. Three more bodies in the walls, sealed behind fresh drywall. A journal detailing each kill in clinical, emotionless prose. And in the corner, a chest freezer humming quietly, its contents still mercifully unknown. Santos watched them work, her hand resting on her service weapon, wondering how many more victims they would find before this nightmare ended.''',
                
                '''The killer was still out there. The journal's final entry was dated just three days ago, and it described a woman with red hair and green eyes who worked at the coffee shop on Meridian Street. Santos pulled out her phone, her fingers already dialing, knowing that somewhere in the city, another photograph was about to be added to that basement wall.''',
            ],
            expected_original_ratings={'language': Rating.G, 'adult': Rating.G, 'violence': Rating.R},
            target_ratings={'language': 2, 'adult': 2, 'violence': 3},  # PG-13 violence target
        ),
        
        # =======================================================================
        # TEST 5: URBAN FANTASY - Mixed R content (language + suggestive) in supernatural noir
        # =======================================================================
        PipelineTestChapter(
            name="UrbanFantasy-Mixed-SupernaturalNoir",
            paragraphs=[
                '''The vampire's blood bar was exactly the kind of dive you'd expect in the supernatural district—low lighting to hide the clientele's less human features, jazz playing from a century-old phonograph, and a bartender with too many eyes who never asked questions. Private investigator Jack Marlow pushed through the beaded curtain, his silver-loaded revolver heavy against his hip. He'd been tracking the succubus for three weeks, and his sources said she fed here on weekends.''',
                
                '''He spotted her immediately. She lounged in a corner booth, all curves and crimson lips and an aura that made every head in the room turn her direction. Her dress was barely legal, clinging to her body like a second skin, the neckline plunging to reveal the swell of her breasts. When she noticed him watching, she smiled, running her tongue slowly across her lower lip in unmistakable invitation. Even knowing what she was, he felt his body respond to her supernatural allure.''',
                
                '''"You're the detective," she purred as he approached, her voice like honey and sin. "I was wondering when you'd find me." She gestured to the seat across from her, and he took it, keeping his hand near his weapon. "You've been a busy woman, Miss...?" "Lilith will do," she said. "And yes, I've been fucking my way through your city's elite. Is that a crime?" Her eyes glinted red in the low light. "It is when they turn up dead afterward, drained of life force."''',
                
                '''"Those assholes deserved what they got," Lilith replied, all pretense of seduction dropping from her face. "Every one of them. You want to know what the mayor did to his interns? What the police commissioner's private parties involved?" She leaned forward, and Jack caught a glimpse of something ancient and terrible behind her beautiful mask. "I'm not a murderer, detective. I'm a goddamn public service." She slid a folder across the table. "But if you need a villain, start with the shit in there."''',
                
                '''Jack opened the folder and felt his stomach turn. Photographs, documents, testimony—enough to bring down half the city's power structure. "Why give this to me?" he asked. Lilith stood, adjusting her dress in a way that drew his eyes despite himself. "Because you're one of the few honest men left in this corrupt hellhole. And because you're cute when you're trying not to stare at my chest." She vanished in a whisper of perfume and brimstone, leaving him alone with evidence that would either make his career or get him killed.''',
            ],
            expected_original_ratings={'language': Rating.R, 'adult': Rating.PG13, 'violence': Rating.G},
            target_ratings={'language': 2, 'adult': 2, 'violence': 5},  # PG targets
        ),
        
        # =======================================================================
        # TEST 6: MILITARY THRILLER - R-level violence + language in combat
        # =======================================================================
        PipelineTestChapter(
            name="MilitaryThriller-Violence-Combat",
            paragraphs=[
                '''The convoy hit the IED at 0347 hours, the lead Humvee lifting off the road in a blossom of fire and shrapnel. Sergeant First Class Derek "Reaper" Morrison was in the third vehicle when the world turned to chaos—the crack of small arms fire echoing off the canyon walls, muzzle flashes sparking from the ridgeline above. "Contact right! Contact right!" someone was screaming into the radio. "Fucking ambush! We've got hostiles on the ridge!"''',
                
                '''Morrison kicked open his door and rolled into the ditch, his M4 already seeking targets. The lead vehicle was a wreck, flames licking at the twisted metal. He could see Corporal Williams trying to pull someone from the burning cab, his fatigues on fire, screaming as his hands blistered against the superheated door handle. A round caught Williams in the neck, and blood sprayed in an arterial fountain, painting the sand dark. He crumpled without a sound.''',
                
                '''"Covering fire! Get those wounded to cover!" Morrison emptied his magazine into the ridgeline, brass casings pinging off the rocks around him. Private Reyes was dragging herself toward him, leaving a dark trail—her right leg was gone below the knee, white bone jutting from raw meat. "I've got you," he said, grabbing her drag handle. "Stay with me, Reyes." Her eyes were glassy with shock, her lips moving in soundless prayer.''',
                
                '''The firefight lasted twelve minutes that felt like hours. When the last hostile went down, Morrison surveyed the carnage with hollow eyes. Four dead, seven wounded, two vehicles destroyed. Reyes was still alive, barely, a tourniquet cinched tight above her ruined leg. Medic Cho was elbow-deep in someone's chest cavity, trying to find the bleeder that was pumping their life out onto the desert floor. "Shit," Morrison said softly, then louder: "Where's that fucking medevac?"''',
                
                '''The helicopter arrived twenty-three minutes later, its rotors kicking up dust clouds that stung his eyes. As they loaded the wounded, Morrison found himself staring at the body bags lined up beside the road. Williams. Kowalski. Pham. Gutierrez. Four more names for the wall, four more letters he'd have to help write. The war ground on, indifferent to their sacrifice, and tomorrow there would be another patrol, another mission, another chance to add to the butcher's bill.''',
            ],
            expected_original_ratings={'language': Rating.R, 'adult': Rating.G, 'violence': Rating.R},
            target_ratings={'language': 2, 'adult': 2, 'violence': 3},  # PG language, PG-13 violence
        ),
        
        # =======================================================================
        # TEST 7: GOTHIC ROMANCE - R-level adult in Victorian setting
        # =======================================================================
        PipelineTestChapter(
            name="GothicRomance-Adult-Victorian",
            paragraphs=[
                '''The storm that brought Lord Ashworth to Thornwood Manor also brought the end of Catherine's carefully constructed respectability. She had been the governess for three years, invisible and proper, teaching French and watercolors to children who would never truly see her as anything more than a servant. But when the brooding master of the house took shelter in the library from the thunder, finding her alone among the books, something ancient and undeniable sparked to life between them.''',
                
                '''He was still in his riding clothes, rain-drenched and wild-eyed, his dark hair plastered to his forehead. The rumors about him swirled through the village—a wife dead under mysterious circumstances, a temper that had broken more than one servant's nerve, secrets that the old house kept locked behind its stones. Catherine knew she should curtsey and leave. Instead, she stood frozen as he approached, his eyes burning into hers with an intensity that made her breath catch.''',
                
                '''"You're trembling," he observed, his voice a low rumble that seemed to vibrate through her bones. "The storm," she whispered, though they both knew it was a lie. His hand rose to cup her face, calloused thumb tracing the line of her cheekbone, and she leaned into his touch like a flower seeking sun. When he kissed her, it was with the desperate hunger of a man who had denied himself for far too long.''',
                
                '''She didn't resist as he unlaced her dress, layer by layer, until she stood before him in nothing but her shift and stockings. His hands mapped the territory of her body—the curve of her waist, the weight of her breasts, the softness of her thighs beneath the thin cotton. She gasped as his mouth found her throat, her fingers tangling in his hair, pulling him closer. They came together on the library floor, the storm raging outside as they created their own tempest within. His movements were urgent, demanding, and she rose to meet him with equal fire, crying out as pleasure crashed through her like lightning.''',
                
                '''Later, as they lay tangled among scattered books and discarded clothing, the fire burning low in the grate, Catherine knew her life had irrevocably changed. There could be no going back to propriety now, no pretending she was still the respectable Miss Blackwood. She had become something else entirely—his lover, his secret, his downfall or his salvation. The storm had passed, but what it had awakened in Thornwood Manor would not be so easily quieted.''',
            ],
            expected_original_ratings={'language': Rating.G, 'adult': Rating.R, 'violence': Rating.G},
            target_ratings={'language': 2, 'adult': 2, 'violence': 5},  # PG adult target
        ),
        
        # =======================================================================
        # TEST 8: CYBERPUNK - R-level language + violence in dystopian setting
        # =======================================================================
        PipelineTestChapter(
            name="Cyberpunk-Mixed-Dystopia",
            paragraphs=[
                '''Neo-Shanghai's undercity never slept, a neon-soaked warren of black markets and bootleg clinics where the megacorps' long shadow couldn't quite reach. Razor Chen navigated the crowds with practiced ease, her cybernetic eye cataloging threats and exits while her meat eye watched for familiar faces. The data chip in her skull pocket was worth more than most of these people would see in a lifetime—stolen research from Helix Biotech that would bring the whole rotten corporation crashing down.''',
                
                '''"There she is." The voice came from everywhere and nowhere, broadcast directly into her auditory implants. Corporate hunters, at least three of them, their locations triangulating through the crowd. "Shit," Razor muttered, her hand drifting to the monofilament blade concealed in her forearm. "This is about to get really fucking ugly." She ducked into an alley, boot heels splashing through puddles of something she didn't want to identify.''',
                
                '''The first hunter found her behind a noodle stand, his thermal optics giving him away before he could raise his weapon. Razor's blade sang through the air, opening his throat in a spray of arterial crimson. He gurgled and fell, clutching at the wound as his blood mixed with the alley's other fluids. The second came from above, dropping from a fire escape, but she was already moving—the blade took his hand off at the wrist, and her follow-up strike buried itself in his chest, grinding against ribs before finding his heart.''',
                
                '''"Fuck this," the third hunter announced over their shared channel, his voice tight with fear. "The payout's not worth dying for." Razor heard his footsteps retreating, but she knew it wouldn't end here. Helix would send more. They always sent more. She stepped over the bodies, wiping her blade clean on a dead man's jacket, and kept moving deeper into the undercity's bowels. The revolution was coming, and it would be paid for in corporate blood.''',
                
                '''An hour later, she reached the safehouse—a converted server farm hidden beneath an abandoned temple. The resistance cell was already waiting, their faces a mix of hope and desperate fear. "You got it?" their leader asked. Razor pulled the chip from her pocket, its surface still warm from her body heat. "Two men died for this shit," she said flatly. "It better be worth it." The leader's smile was sharp as a blade. "Oh, it will be. When this data goes public, Helix's human experimentation program will be exposed to the whole damn world. Those bastards are finally going to burn."''',
            ],
            expected_original_ratings={'language': Rating.R, 'adult': Rating.G, 'violence': Rating.R},
            target_ratings={'language': 2, 'adult': 2, 'violence': 3},  # PG language, PG-13 violence
        ),
    ]


def create_temp_bookwash_file(chapter: PipelineTestChapter, temp_dir: Path) -> Path:
    """Create a temporary .bookwash file from a test chapter."""
    now = datetime.now().isoformat()
    content = f'''#BOOKWASH 1.0
#SOURCE: test_harness_pipeline.epub
#CREATED: {now}
#SETTINGS: target_language={chapter.target_ratings['language']} target_sexual={chapter.target_ratings['adult']} target_violence={chapter.target_ratings['violence']}

#CHAPTER: 1
#TITLE: {chapter.name}

{chapter.get_content()}
'''
    
    filepath = temp_dir / f"{chapter.name.replace(' ', '_')}.bookwash"
    filepath.write_text(content, encoding='utf-8')
    return filepath


def run_pipeline_tests(chapters: List[PipelineTestChapter], model: str = "gemini-2.0-flash", verbose: bool = False, save_output_dir: Optional[str] = None):
    """Run full pipeline tests on chapters.
    
    For each chapter:
    1. Create a temp .bookwash file
    2. Run cmd_rate to rate it
    3. Run cmd_identify + cmd_fill for cleaning
    4. Verify final ratings meet targets
    
    Args:
        save_output_dir: If provided, copy final .bookwash files here for review
    """
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    
    print(f"\n{'='*70}")
    print(f"FULL PIPELINE TESTS")
    print(f"Model: {model}")
    if save_output_dir:
        print(f"Saving output to: {save_output_dir}")
    print(f"{'='*70}\n")
    
    results = []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        for i, chapter in enumerate(chapters, 1):
            print(f"\n[{i}/{len(chapters)}] Testing: {chapter.name}")
            print(f"  Targets: lang={chapter.target_ratings['language']}, adult={chapter.target_ratings['adult']}, viol={chapter.target_ratings['violence']}")
            print(f"  Expected original: lang={chapter.expected_original_ratings['language'].name}, adult={chapter.expected_original_ratings['adult'].name}, viol={chapter.expected_original_ratings['violence'].name}")
            
            result = {
                'name': chapter.name,
                'expected_original': chapter.expected_original_ratings,
                'targets': chapter.target_ratings,
                'pre_clean_rating': None,
                'post_clean_rating': None,
                'num_changes': 0,
                'passes_used': 0,
                'success': False,
                'error': None,
            }
            
            try:
                # Create temp file
                filepath = create_temp_bookwash_file(chapter, temp_path)
                print(f"  Created: {filepath.name}")
                
                # Parse it
                bw = bookwash_llm.parse_bookwash(filepath)
                
                # Create Gemini client
                client = bookwash_llm.GeminiClient(api_key=api_key, model=model)
                
                # Get targets from test chapter
                target_lang = chapter.target_ratings['language']
                target_adult = chapter.target_ratings['adult']
                target_viol = chapter.target_ratings['violence']
                
                # PASS A: Rate chapters
                print("  Running Pass A (rate)...")
                bookwash_llm.cmd_rate(bw, client, target_lang, target_adult, target_viol, verbose=verbose)
                bookwash_llm.write_bookwash(bw, filepath)
                
                # Record pre-clean ratings
                if bw.chapters and bw.chapters[0].rating:
                    rating = bw.chapters[0].rating
                    result['pre_clean_rating'] = {
                        'language': parse_rating(rating.language),
                        'adult': parse_rating(rating.sexual),
                        'violence': parse_rating(rating.violence),
                    }
                    print(f"  Pre-clean ratings: lang={rating.language}, adult={rating.sexual}, viol={rating.violence}")
                    
                    needs_cleaning = bw.chapters[0].needs_cleaning
                    print(f"  Needs cleaning: {needs_cleaning}")
                    
                    if needs_cleaning:
                        # Use cmd_clean which has the full verification loop with aggression escalation
                        print("  Running cmd_clean (identify + fill + verify loop)...")
                        changes_made = bookwash_llm.cmd_clean(bw, client, verbose=verbose, max_iterations=3, verify=True)
                        bookwash_llm.write_bookwash(bw, filepath)
                        
                        # Count final changes
                        content = filepath.read_text()
                        num_changes = content.count('#CHANGE:')
                        result['num_changes'] = num_changes
                        print(f"  Change blocks created: {num_changes}")
                        
                        # Re-parse and re-rate using cleaned text
                        bw = bookwash_llm.parse_bookwash(filepath)
                        
                        # Get the cleaned text for re-rating
                        if bw.chapters:
                            cleaned_text = bw.chapters[0].get_text_with_cleaned()
                            
                            # Use the SAME rating function as cmd_clean uses internally
                            # This ensures consistency between internal and external verification
                            print("  Re-rating cleaned content (using same function as cmd_clean)...")
                            llm = bookwash_llm.GeminiClient(api_key=api_key, model=model)
                            chapter_rating = llm.rate_chapter(cleaned_text)
                            
                            result['post_clean_rating'] = {
                                'language': parse_rating(chapter_rating.language),
                                'adult': parse_rating(chapter_rating.sexual),  # rate_chapter uses 'sexual'
                                'violence': parse_rating(chapter_rating.violence),
                            }
                            print(f"  Post-clean ratings: lang={chapter_rating.language}, adult={chapter_rating.sexual}, viol={chapter_rating.violence}")
                            result['passes_used'] = 3  # cmd_clean runs all passes
                    else:
                        result['post_clean_rating'] = result['pre_clean_rating']
                        result['passes_used'] = 1
                
                # Check if final ratings meet targets
                if result['post_clean_rating']:
                    lang_ok = result['post_clean_rating']['language'].value <= chapter.target_ratings['language']
                    adult_ok = result['post_clean_rating']['adult'].value <= chapter.target_ratings['adult']
                    viol_ok = result['post_clean_rating']['violence'].value <= chapter.target_ratings['violence']
                    result['success'] = lang_ok and adult_ok and viol_ok
                    
                    if result['success']:
                        print(f"  ✅ PASS - All ratings meet targets")
                    else:
                        issues = []
                        if not lang_ok:
                            issues.append(f"language ({result['post_clean_rating']['language'].name} > target {chapter.target_ratings['language']})")
                        if not adult_ok:
                            issues.append(f"adult ({result['post_clean_rating']['adult'].name} > target {chapter.target_ratings['adult']})")
                        if not viol_ok:
                            issues.append(f"violence ({result['post_clean_rating']['violence'].name} > target {chapter.target_ratings['violence']})")
                        print(f"  ❌ FAIL - Issues: {', '.join(issues)}")
                
            except Exception as e:
                import traceback
                result['error'] = str(e)
                print(f"  ❌ ERROR: {e}")
                if verbose:
                    traceback.print_exc()
            
            # Always save output file to test_output directory
            if filepath.exists():
                import shutil
                output_dir = Path(save_output_dir) if save_output_dir else Path("test_output")
                output_dir.mkdir(parents=True, exist_ok=True)
                dest = output_dir / filepath.name
                shutil.copy(filepath, dest)
                print(f"  Saved to: {dest}")
            
            results.append(result)
            
            # Rate limit between tests
            time.sleep(2.0)
    
    # Print summary
    print(f"\n{'='*70}")
    print("PIPELINE TEST SUMMARY")
    print(f"{'='*70}\n")
    
    passed = sum(1 for r in results if r['success'])
    failed = sum(1 for r in results if not r['success'] and not r['error'])
    errors = sum(1 for r in results if r['error'])
    
    print(f"Passed: {passed}/{len(results)}")
    print(f"Failed: {failed}/{len(results)}")
    print(f"Errors: {errors}/{len(results)}")
    
    print("\nDetailed Results:")
    for r in results:
        status = "✅ PASS" if r['success'] else ("❌ ERROR" if r['error'] else "❌ FAIL")
        print(f"  {r['name']}: {status}")
        if r['pre_clean_rating']:
            pre = r['pre_clean_rating']
            print(f"    Pre:  lang={pre['language'].name}, adult={pre['adult'].name}, viol={pre['violence'].name}")
        if r['post_clean_rating']:
            post = r['post_clean_rating']
            print(f"    Post: lang={post['language'].name}, adult={post['adult'].name}, viol={post['violence'].name}")
        print(f"    Changes: {r['num_changes']}, Passes: {r['passes_used']}")
        if r['error']:
            print(f"    Error: {r['error']}")
    
    return results


def main():
    parser = argparse.ArgumentParser(description='BookWash Python Test Harness')
    parser.add_argument('--test-suite', action='store_true', help='Run main test suite (rating only)')
    parser.add_argument('--holdout', action='store_true', help='Run holdout validation suite (rating only)')
    parser.add_argument('--pipeline', action='store_true', help='Run full pipeline tests (rate + clean + verify)')
    parser.add_argument('--hard', action='store_true', help='Only run the 3 most difficult pipeline tests')
    parser.add_argument('--rate-only', action='store_true', help='Only rate, do not clean (for test-suite/holdout)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--save-output', type=str, default=None, help='Directory to save output .bookwash files (default: delete after test)')
    parser.add_argument('--model', default='gemini-2.0-flash', help='Model to use')
    parser.add_argument('--text', help='Custom text to test')
    parser.add_argument('--expected-language', default='G', help='Expected language rating')
    parser.add_argument('--expected-adult', default='G', help='Expected adult rating')
    parser.add_argument('--expected-violence', default='G', help='Expected violence rating')
    
    args = parser.parse_args()
    
    if args.text:
        # Test custom text
        print(f"Rating custom text with model: {args.model}")
        print(f"Text: {args.text[:100]}...")
        print()
        
        try:
            ratings = rate_text(args.text, model=args.model)
            print(f"Results:")
            print(f"  Language: {ratings.get('language', 'N/A')}")
            print(f"  Adult: {ratings.get('adult', 'N/A')}")
            print(f"  Violence: {ratings.get('violence', 'N/A')}")
            
            # Compare to expected
            print("\nComparison:")
            for cat, expected in [('language', args.expected_language), ('adult', args.expected_adult), ('violence', args.expected_violence)]:
                actual = ratings.get(cat, 'G')
                match = parse_rating(actual) == parse_rating(expected)
                status = "✅" if match else "❌"
                print(f"  {cat}: expected={expected}, actual={actual} {status}")
        except Exception as e:
            print(f"Error: {e}")
    
    elif args.pipeline:
        # Full pipeline tests
        chapters = build_pipeline_test_chapters()
        
        # Filter to only hard tests if requested
        if args.hard:
            hard_tests = ['TrueCrime-Violence-SerialKiller', 'UrbanFantasy-Mixed-SupernaturalNoir', 'Cyberpunk-Mixed-Dystopia']
            chapters = [c for c in chapters if c.name in hard_tests]
            print(f"Running {len(chapters)} hard tests only...\n")
        
        run_pipeline_tests(chapters, model=args.model, verbose=args.verbose, save_output_dir=args.save_output)
            
    elif args.test_suite:
        paragraphs = build_test_suite()
        run_test_suite(paragraphs, rate_only=args.rate_only, model=args.model)
        
    elif args.holdout:
        paragraphs = build_holdout_suite()
        run_test_suite(paragraphs, rate_only=args.rate_only, model=args.model)
        
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
