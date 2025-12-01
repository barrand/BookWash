#!/usr/bin/env python3
"""
BookWash Python Test Harness
----------------------------
A CLI to test the rating and cleaning prompts in bookwash_llm.py.
Includes confusion matrix support for evaluating rating accuracy.

Usage examples:
  # Run comprehensive test suite (rate only, no cleaning)
  python scripts/test_harness.py --test-suite --rate-only
  
  # Run test suite with rate + clean verification
  python scripts/test_harness.py --test-suite
  
  # Run holdout suite (separate validation set)
  python scripts/test_harness.py --holdout --rate-only
  
  # Test a custom paragraph
  python scripts/test_harness.py --text "Some content here" --expected-language PG --expected-adult PG-13 --expected-violence PG

Environment:
  Set GEMINI_API_KEY for API calls.
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import functools
print = functools.partial(print, flush=True)


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


@dataclass
class TestParagraph:
    """A test paragraph with expected ratings."""
    text: str
    category: str  # 'language', 'adult', 'violence'
    expected_rating: Rating
    label: str


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
        
        # LANGUAGE - PG-13: moderate profanity (damn, hell, crap) but no f-word
        TestParagraph(
            text='''The regional newsroom hummed around deadline. "This layout is damn cramped," Felix said, nudging columns. The editor acknowledged without flinching, sliding ads a notch. Pressure showed, but profanity stayed mid-level.
"Crap, the data feed stalled again," a designer groaned, refreshing analytics. Another replied, "Hell, reroute through the mirror—faster than waiting." Cooperative urgency surfaced in clipped phrases.
Draft headlines traded quick revisions: a misplaced stat corrected, a quote trimmed. "Assumption here is shaky—rephrase," the copy chief advised. No f-word surfaced; only moderate newsroom gristle.''',
            category='language',
            expected_rating=Rating.PG13,
            label='PG-13-Language: newsroom moderate profanity (no f-word)',
        ),
        
        # LANGUAGE - R: strong profanity including f-word
        TestParagraph(
            text='''The startup war room burned with overtime glare. "This fucking deploy pipeline is choking again," Rina snapped, slamming a log window wider. Logs spat stack traces; someone swore under their breath.
"We promised that client a working build by dawn—fix the shit in the auth proxy," another engineer pushed. Chairs creaked as they pivoted across terminals.
Memory leaks triggered cascading restarts. "Kill that bastard process and patch the config," Rina ordered. A teammate: "Already killed—fucked cache index was corrupt." Rapid, harsh language braided into technical triage.''',
            category='language',
            expected_rating=Rating.R,
            label='R-Language: high-intensity technical meltdown with strong profanity',
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
    
    # Use the same rating prompt from bookwash_llm.py
    rating_prompt = f'''You are a content rating assistant. Rate the following text for:
1. Language/Profanity (G, PG, PG-13, R, X)
2. Adult/Sexual Content (G, PG, PG-13, R, X)
3. Violence (G, PG, PG-13, R, X)

Rating scale:
- G: Family friendly, no objectionable content
- PG: Mild content (mild exclamations like "darn", brief hug, verbal conflict)
- PG-13: Moderate content (some profanity like "damn/hell" but no f-word, sustained kissing/implied intimacy, weapon threats with minor blood)
- R: Strong content (f-word and strong profanity, explicit sexual activity, graphic violence/gore)
- X: Extreme/explicit content

IMPORTANT: Be vigilant for SUBTLE adult content that should still be rated:
- Innuendo & double entendres (suggestive language with dual meanings)
- Sexual tension cues (quickened pulse, flushed cheeks, trembling from attraction)
- Internal desires & fantasies (character thoughts about physical attraction)
- "Almost" moments (interrupted intimacy, near-kisses with tension)
- Implied/off-screen activity (morning-after scenes, disheveled appearance)
- Voyeuristic descriptions (lingering on body parts, clothing details)
- Sensory arousal (scent, warmth, taste described erotically)
- Power dynamics with sexual undertones

Any of these should be rated at least PG-13, and explicit versions should be R or X.

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


def main():
    parser = argparse.ArgumentParser(description='BookWash Python Test Harness')
    parser.add_argument('--test-suite', action='store_true', help='Run main test suite')
    parser.add_argument('--holdout', action='store_true', help='Run holdout validation suite')
    parser.add_argument('--rate-only', action='store_true', help='Only rate, do not clean')
    parser.add_argument('--model', default='gemini-1.5-flash', help='Model to use')
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
