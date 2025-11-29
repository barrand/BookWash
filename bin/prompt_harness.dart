import 'dart:io';
import 'package:bookwash/services/gemini_service.dart';
import 'package:bookwash/services/gemini_service.dart'
    show GeminiFilterResponse; // explicit

/*
Prompt Harness
--------------
A lightweight CLI to inspect the active filtering prompt and run sample paragraphs
through Gemini for different rating combinations.

Usage examples:
  # Run comprehensive test suite with rated paragraphs
  dart run bin/prompt_harness.dart --test-suite --dry-run
  dart run bin/prompt_harness.dart --test-suite  # with API key

  # Override model (defaults to gemini-2.5-flash or GEMINI_MODEL env)
  dart run bin/prompt_harness.dart --test-suite --model gemini-2.0-flash-exp

  # Use built-in sample text across language levels (sexual/violence fixed)
  dart run bin/prompt_harness.dart --sample --language-all --sexual PG --violence PG

  # Custom text for a specific rating set
  dart run bin/prompt_harness.dart --text "He shouted: damn hell crap shit! They kissed." --language PG --sexual PG --violence PG

  # Show only the constructed prompt (no API call)
  dart run bin/prompt_harness.dart --show-prompt --language PG --sexual PG --violence PG

Environment:
  Set GEMINI_API_KEY or pass --api-key <key>.

Notes:
  - Each paragraph must be separated by a blank line (two '\n').
  - The harness reports length diff and removed keyword approximations.
  - Network calls are sequential; keep samples short.
*/

enum RatingLevel { G, PG, PG13, R, Unrated }

String enumName(RatingLevel level) => level.toString().split('.').last;

int _mapRating(RatingLevel level) {
  switch (level) {
    case RatingLevel.G:
      return 1;
    case RatingLevel.PG:
      return 2;
    case RatingLevel.PG13:
      return 3;
    case RatingLevel.R:
      return 4;
    case RatingLevel.Unrated:
      return 5;
  }
}

RatingLevel _parseRating(String raw) {
  final v = raw.trim().toUpperCase();
  switch (v) {
    case 'G':
      return RatingLevel.G;
    case 'PG':
      return RatingLevel.PG;
    case 'PG-13':
    case 'PG13':
      return RatingLevel.PG13;
    case 'R':
      return RatingLevel.R;
    case 'UNRATED':
    case 'NONE':
    case '5':
      return RatingLevel.Unrated;
    default:
      throw ArgumentError('Unknown rating: $raw');
  }
}

class TestParagraph {
  final String text;
  final String category; // 'language', 'sexual', 'violence'
  final RatingLevel rating;
  final String label;

  TestParagraph({
    required this.text,
    required this.category,
    required this.rating,
    required this.label,
  });
}

class ConfusionMatrix {
  int truePositives = 0; // Correctly removed inappropriate content
  int falsePositives = 0; // Incorrectly removed appropriate content
  int trueNegatives = 0; // Correctly kept appropriate content
  int falseNegatives = 0; // Incorrectly kept inappropriate content

  void recordResult({required bool shouldModify, required bool wasModified}) {
    if (shouldModify && wasModified) {
      truePositives++;
    } else if (!shouldModify && wasModified) {
      falsePositives++;
    } else if (!shouldModify && !wasModified) {
      trueNegatives++;
    } else if (shouldModify && !wasModified) {
      falseNegatives++;
    }
  }

  double get accuracy =>
      total > 0 ? (truePositives + trueNegatives) / total : 0;
  double get precision => (truePositives + falsePositives) > 0
      ? truePositives / (truePositives + falsePositives)
      : 0;
  double get recall => (truePositives + falseNegatives) > 0
      ? truePositives / (truePositives + falseNegatives)
      : 0;
  int get total =>
      truePositives + falsePositives + trueNegatives + falseNegatives;

  void printSummary(String filterName) {
    stdout.writeln('\n[$filterName Filter]');
    stdout.writeln('  TP: $truePositives  FP: $falsePositives');
    stdout.writeln('  FN: $falseNegatives  TN: $trueNegatives');
    stdout.writeln('  Accuracy: ${(accuracy * 100).toStringAsFixed(1)}%');
    final noPositives =
        (truePositives + falseNegatives) ==
        0; // nothing should have been removed
    if (noPositives) {
      stdout.writeln('  Precision: N/A (no positive cases)');
      stdout.writeln('  Recall: N/A (no positive cases)');
    } else {
      stdout.writeln('  Precision: ${(precision * 100).toStringAsFixed(1)}%');
      stdout.writeln('  Recall: ${(recall * 100).toStringAsFixed(1)}%');
    }
  }
}

List<TestParagraph> buildTestSuite() {
  return [
    // LANGUAGE (fresh corpus, 7 paragraphs each)
    TestParagraph(
      text:
          '''The astronomy club met just after dusk, laptops glowing while the horizon still held a thin lavender band. Their advisor outlined the schedule for the meteor watch, careful and methodical, inviting quiet questions.

They unpacked the tripod mounts and calibration charts. Conversation stayed practical—exposure values, predicted cloud drift, alignment tolerances. No one bickered; they simply adjusted lenses and compared readings.

During a brief break, two students traded notes about future internships at observatories. The tone remained professional, curious rather than competitive, focused on techniques they hoped to master.

When the first streak carved a faint line across the upper sky, they logged time stamps, cross-referencing with published orbital debris forecasts. Precise, neutral documentation filled their shared sheet.

Later they double-checked catalog entries for anything persistent, ruling out satellites. Each correction was polite: suggestions phrased as offers, never as barbed critique.

Near midnight, dew settled on the cases. They wiped surfaces, rotated lenses back into protective foam, and summarized observations. Nothing sensational—solid data, stable procedure.

They locked up, agreeing on next week's tasks. The whole session exemplified careful, profanity‑free collaboration for a junior readership.''',
      category: 'language',
      rating: RatingLevel.G,
      label: 'G-Language: technical astronomy collaboration, neutral tone',
    ),
    TestParagraph(
      text:
          '''The community theater rehearsal lurched forward. "Golly, that cue was early," Mara said, grinning as the prop mailbox toppled harmlessly. Someone muttered a cheerful "jeez" while resetting the scene markers.

They tried the scene again; a missed lighting change prompted a gentle "darn, I’ll tighten that timing." The director responded with a calm nod, jotting a timing fix. No sharp words, only mild exclamations peppered the adjustments.

Backstage, two volunteers wrestled with tangled extension cords. "Heck, these knots have personalities," one joked. Laughter stayed light; frustration expressed through allowed gentle terms.

In the dressing alcove, costume hems were re-pinned. "Shoot, the thread snapped," someone observed, already rethreading the needle. The tone stayed constructive—no harsh language.

Act three's blocking ran a third time. Minor stumbles earned a few "gosh" and "dang" remarks, but no escalation. The cast encouraged each other with upbeat pats on shoulders.

They wrapped by recording revision notes: timing tweaks, prop stability, entrance spacing. No insults appeared; only collaborative phrasing and mild, PG-safe exclamations.

Leaving the building, Mara summarized progress, optimistic. The dialogue throughout remained within family-friendly bounds while still sounding authentically human.''',
      category: 'language',
      rating: RatingLevel.PG,
      label: 'PG-Language: rehearsal with mild exclamations only',
    ),
    TestParagraph(
      text:
          '''The regional newsroom hummed around deadline. "This layout is damn cramped," Felix said, nudging columns. The editor acknowledged without flinching, sliding ads a notch. Pressure showed, but profanity stayed mid-level.

"Crap, the data feed stalled again," a designer groaned, refreshing analytics. Another replied, "Hell, reroute through the mirror—faster than waiting." Cooperative urgency surfaced in clipped phrases.

Draft headlines traded quick revisions: a misplaced stat corrected, a quote trimmed. "Assumption here is shaky—rephrase," the copy chief advised. No f-word surfaced; only moderate newsroom gristle.

At the coffee station someone muttered "damn printer roller" while clearing a jam. Tension vented through permitted words, never escalating to stronger slurs.

Late afternoon brought a vendor call mix-up. "Hell, they shipped the wrong charts." The reply stayed practical: reorder, annotate impacted graphs, proceed.

Final checks: bylines aligned, disclaimers inserted, pagination recalculated. "Crap margin drift fixed," a layout assistant announced with relief.

Edition locked, they archived assets. Language throughout stayed squarely PG-13: moderate stress expressions without any forbidden extremes.''',
      category: 'language',
      rating: RatingLevel.PG13,
      label: 'PG-13-Language: newsroom moderate profanity (no f-word)',
    ),
    TestParagraph(
      text:
          '''The startup war room burned with overtime glare. "This fucking deploy pipeline is choking again," Rina snapped, slamming a log window wider. Logs spat stack traces; someone swore under their breath.

"We promised that client a working build by dawn—fix the shit in the auth proxy," another engineer pushed. Chairs creaked as they pivoted across terminals.

Memory leaks triggered cascading restarts. "Kill that bastard process and patch the config," Rina ordered. A teammate: "Already killed—fucked cache index was corrupt." Rapid, harsh language braided into technical triage.

An investor ping lit a phone. "Tell them the fuckups are contained," someone said, half sarcastic. Stress peaked but stayed directed at problems, not people personally.

Midnight: a stray environment variable collapsed security headers. "Christ, that’s a shit oversight," Rina muttered, patching and redeploying. Relief punctuated by one more coarse exhale.

Toward final verification they reviewed error graphs: f-word variants peppered anxious recap. Still, no personal hate speech—just intense adult frustration.

Build stabilized; they slumped back. The dialogue remained fully R-grade, retaining every strong profanity while focused on resolving the meltdown rather than gratuitous insult.''',
      category: 'language',
      rating: RatingLevel.R,
      label:
          'R-Language: high-intensity technical meltdown with strong profanity',
    ),

    // SEXUAL CONTENT (fresh corpus, 7 paragraphs each)
    TestParagraph(
      text:
          '''Two siblings cataloged seashells along a quiet shoreline, debating the Latin names with playful precision. Their conversation remained purely academic, trading field guide page numbers.

They paused to compare spiral patterns, noting erosion differences. Cooperation felt easy—familial, non-romantic, comfortably neutral.

Lunch under a weathered pier involved sharing simple sandwiches and discussing school projects. No suggestive remarks appeared; focus stayed on the classification task.

Afternoon tide pools revealed a striped crab. They logged observations, calibrating a phone microscope. Dialogue remained factual.

Later they planned a weekend presentation, splitting slides: morphology, habitat range, conservation notes—no emotional subtext beyond cooperative encouragement.

Packing specimens, they wrapped fragile pieces in labeled paper. Compliments centered on careful handling, never drifting toward intimacy.

They left the shore at dusk, satisfied with collected data. Entire exchange stayed G-rated, anchored in sibling collaboration and science.''',
      category: 'sexual',
      rating: RatingLevel.G,
      label: 'G-Sexual: sibling scientific collaboration, no romance',
    ),
    TestParagraph(
      text:
          '''During a weekend volunteer shift at a community garden, two participants compared seedling trays. Conversation was light—soil moisture, sprouting rates. Friendly rapport, nothing charged.

They coordinated watering sequence, briefly brushing hands while passing a trowel. A gentle smile; no escalation beyond mild connection.

After a shared joke about stubborn weeds, one offered a refill of herbal tea. "Thanks," she said, cheeks faintly warm—still innocent.

Near break time, they reviewed growth logs side by side. He encouraged her pruning approach; affirmation remained respectful and restrained.

As they packed tools, he asked about joining a small group hike later. She agreed; tone hopeful but soft. A brief, simple hug goodbye—no lingering.

Evening message exchanged hiking details; no romantic wording, just planning. Atmosphere remained gentle.

Overall interaction: mild budding interest expressed through subtle gestures, a single brief hug—fully PG, no passionate contact.''',
      category: 'sexual',
      rating: RatingLevel.PG,
      label: 'PG-Sexual: budding interest with mild affectionate gestures',
    ),
    TestParagraph(
      text:
          '''A late gallery opening left two visitors wandering quiet halls. Their conversation thinned into charged pauses near a luminous abstract. Fingers grazed while gesturing at texture; neither withdrew.

Outside on the terrace cool air tightened the mood. He stepped closer; they shared a long, deep kiss—hands at waist and jaw, bodies aligned. Breath hitched but no explicit anatomical detail surfaced.

They separated briefly, eyes meeting—another series of heated kisses followed. A murmured suggestion to leave before closing time carried implied direction.

In the foyer they adjusted coats, laughter muted. Physical closeness persisted, but description still bound to surface passion only.

Cab ride narrated art impressions while knees touched—a subtle tension, nothing explicit stated.

Arrival at her building ended with an embrace and one final intensifying kiss that tapered naturally. Door closing implied the rest, fade-to-black without explicit act terms.

Scene contains only passionate kissing + implied progression; remains PG-13 without anatomical or explicit intercourse description.''',
      category: 'sexual',
      rating: RatingLevel.PG13,
      label:
          'PG-13-Sexual: sustained kissing with implied intimacy, no explicit detail',
    ),
    TestParagraph(
      text:
          '''Rain hammered the loft’s skylight as they shed damp jackets. Lips met with urgent focus; hands traced contours under thinning lamplight. Shirts lifted; warm skin contact deepened.

She guided his hand over her torso; he responded with deliberate, intimate strokes. Soft sounds marked escalating arousal while they moved toward the couch.

Clothing slid aside—bare skin against fabric, descriptive tactile detail of pressure and rhythm building. Gasps and low moans framed the encounter.

He kissed along her lower abdomen; she arched, directing pace. Their dialogue fell to fragments amidst explicit caresses.

Penetration occurred, described with clear bodily movement and urgent repetition—sweat gathering, shifting positions to adjust angle and intensity.

Release arrived in staggered waves; they remained entwined, breathing rough, exchanging brief, intimate remarks about satisfaction.

Afterward, they cleaned up casually, retaining a tone of continued desire. Scene is explicit but avoids graphic anatomical porn-style close-ups—firmly R-rated.''',
      category: 'sexual',
      rating: RatingLevel.R,
      label: 'R-Sexual: explicit encounter, sustained explicit tactile detail',
    ),

    // VIOLENCE (fresh corpus, 7 paragraphs each)
    TestParagraph(
      text:
          '''A town hall dispute unfolded over funding priorities. Voices rose, but participants stayed behind tables. Words like "escalate" and "conflict" appeared in arguments, yet no one crossed into physical threat.

One speaker warned that ignoring infrastructure could "invite future violence"—an abstract projection, not an immediate act. Others countered with economic stats.

Gestures sharpened: pointed fingers, firm hand chops on lecterns. Security observed, non-intervening, as discourse remained verbal only.

Another delegate invoked historical clashes metaphorically—"We cannot repeat those battles"—purely figurative, prompting nods.

Temporary tension spiked when two leaned forward simultaneously, but chairs stayed anchored; no approach, no contact.

Moderators refocused debate with procedural reminders. Language cooled incrementally.

Session adjourned without any physical altercation—entire sequence is verbal tension and abstract threat references; G-level for violence.''',
      category: 'violence',
      rating: RatingLevel.G,
      label: 'G-Violence: purely verbal civic dispute, abstract threats only',
    ),
    TestParagraph(
      text:
          '''Youth league soccer scrimmage ran energetic but mostly clean. A midfield bump sent one player sliding harmlessly; they stood quickly, dusting off.

Later a misjudged tackle caused a brief tumble—coach shouted reminders about form. No blood, only a grass stain on a sleeve.

Spectators reacted with mild concern that faded once both resumed jogging. A slight ankle twist prompted substitution for caution.

Bench conversation centered on hydration and drills, not pain or injury description. Minor contact framed as routine.

Near end, an accidental elbow brushed a shoulder during a leap; apology exchanged instantly, situation defused.

Game closed with handshakes and casual jokes. Physical action never escalated into graphic harm.

Overall: mild scuffles, incidental bumps—non-graphic, squarely PG violence profile.''',
      category: 'violence',
      rating: RatingLevel.PG,
      label: 'PG-Violence: youth soccer minor contact, no injury detail',
    ),
    TestParagraph(
      text:
          '''Urban alley pursuit: a fleeing courier clipped a trash bin, drawing a swift shout. Chaser vaulted debris; tension climbed.

Corner turn produced a stumble—palms scraped, a thin line of blood forming but quickly ignored as running resumed.

The chased individual brandished a small pocket knife defensively; light gleamed off the blade. No stab yet—threat posture only.

A tackle finally landed; both hit damp pavement. Knife skittered aside, leaving a shallow cut on a forearm—crimson bead visible, not gory.

Brief struggle: grunts, a strained wrist twist, one knee impact. Nearby siren doppler indicated approaching authorities.

Resolution: courier restrained, minor bleeding wiped with a cloth. Weapon recovered and bag contents inspected.

Scene includes blood mention and weapon use without gore—PG-13 appropriate violence level.''',
      category: 'violence',
      rating: RatingLevel.PG13,
      label: 'PG-13-Violence: pursuit with minor blood and weapon threat',
    ),
    TestParagraph(
      text:
          '''The siege breach detonated with concussive force, splintering inner gate beams. Fragments lanced outward, embedding in exposed arms and shoulders—quick dark streaks marking initial wounds.

Inside the courtyard, close-quarter clashes yielded slashes that opened muscle; steam-like breath mingled with rising metallic scent. A defender coughed crimson onto flagstones.

One combatant’s thigh was pierced; blood pumped rhythmically until a rough tourniquet cinched. Bone showed momentarily through a shattered wrist guard in another exchange.

Flames from an overturned brazier seared a fallen fighter’s cloak, skin blistering beneath before being dragged clear.

An archer’s arrow tore through a neck side—labored gurgle, hands clamped futilely; collapse followed swiftly.

After twenty brutal minutes, survivors stood amid pooled, dark slicks and scattered viscera fragments near the breach point.

Graphic gore and sustained anatomical injury detail place this firmly in R-level violence territory (not pornographic torture, but intense).''',
      category: 'violence',
      rating: RatingLevel.R,
      label: 'R-Violence: siege battle with graphic wounds and gore detail',
    ),
  ];
}

// Holdout corpus (distinct domains; avoid phrases used in prompt tuning)
List<TestParagraph> buildHoldoutSuite() {
  return [
    // LANGUAGE HOLDOUT
    TestParagraph(
      text:
          '''Students rotated through a planetarium exhibit, recording star positions without commentary beyond coordinate values. The guide quietly adjusted the projector focus. No casual exclamations surfaced; tone stayed instructional and plain.

Later they transcribed calibration marks, comparing numerical drift. Dialogue remained impersonal, procedural. A summary sheet listed timestamp, lens angle, offset—nothing emotive.

Final cleanup involved powering down consoles in silence. Neutral academic atmosphere throughout.''',
      category: 'language',
      rating: RatingLevel.G,
      label: 'G-Language-Holdout: neutral planetarium lab session',
    ),
    TestParagraph(
      text:
          '''Community robotics club wrestled with a stubborn servo. "Gosh this bracket is snug," one said, easing tension screws. Another added, "Darn calibration slipped again." Mild exclamations broke technical focus but stayed gentle.

After a brief retry someone sighed "Heck, we’ll shim it." Cooperative exchanges used only soft, PG-safe terms.

Device finally cycled correctly; a cheerful "Jeez that took forever" closed the session.''',
      category: 'language',
      rating: RatingLevel.PG,
      label:
          'PG-Language-Holdout: robotics troubleshooting with mild exclamations',
    ),
    TestParagraph(
      text:
          '''Editorial team argued layout timing. "Damn sidebar bleeds into the footer," an assistant noted. Another replied, "Hell, just nudge the grid." Minor stress language appeared repeatedly without any f-word variants.

Proof cycle completed with a final: "Crap, misaligned caption fixed now." Moderate newsroom profanity only.''',
      category: 'language',
      rating: RatingLevel.PG13,
      label: 'PG13-Language-Holdout: newsroom moderate profanity',
    ),
    TestParagraph(
      text:
          '''Overnight warehouse audit deteriorated. "This fucking scanner froze again," the supervisor snapped. A clerk muttered, "Shit, inventory count corrupted." Strong profanity peppered rapid instructions.

Later: "Reboot the bastard handheld, then flush the fucked cache entries." Intense language throughout, no slurs or hate speech—standard R-grade frustration.''',
      category: 'language',
      rating: RatingLevel.R,
      label: 'R-Language-Holdout: warehouse audit with strong profanity',
    ),

    // SEXUAL HOLDOUT
    TestParagraph(
      text:
          '''Consultants reviewed quarterly compliance matrices, exchanging only formal clarifications. Seating distance remained professional; no personal remarks or romantic shading—pure task alignment for hours.''',
      category: 'sexual',
      rating: RatingLevel.G,
      label: 'G-Sexual-Holdout: strictly professional compliance meeting',
    ),
    TestParagraph(
      text:
          '''Two volunteers closed up a library event, sharing a quick side hug after stacking chairs. A soft smile and a polite "See you Tuesday"—no sustained physical contact, just mild budding friendliness.''',
      category: 'sexual',
      rating: RatingLevel.PG,
      label: 'PG-Sexual-Holdout: brief hug, mild friendly warmth',
    ),
    TestParagraph(
      text:
          '''They lingered outside the tram station. A series of deep kisses, hands resting at waist and shoulder. Breathless pause; a quiet agreement to head home separately. Implied attraction, no anatomical detail, scene ends as late trains rumbled past.''',
      category: 'sexual',
      rating: RatingLevel.PG13,
      label: 'PG13-Sexual-Holdout: sustained kissing, implied intimacy only',
    ),
    TestParagraph(
      text:
          '''Inside the dim studio they undressed between staggered kisses. Palms traced hips and chest; clothing dropped. Clear mutual movement, explicit caresses, bodies aligned in rhythmic thrusts described through pressure and pace, not voyeuristic close-ups. After climax they exchanged drowsy compliments, still entwined.''',
      category: 'sexual',
      rating: RatingLevel.R,
      label: 'R-Sexual-Holdout: explicit encounter, non-pornographic detail',
    ),

    // VIOLENCE HOLDOUT
    TestParagraph(
      text:
          '''Debate club final round escalated vocally—rapid rebuttals, clipped tone, pointed rhetorical flourishes. No physical advance, only emphatic gestures. Entire confrontation non-physical.''',
      category: 'violence',
      rating: RatingLevel.G,
      label: 'G-Violence-Holdout: verbal debate only',
    ),
    TestParagraph(
      text:
          '''Trail run collision: two joggers bumped shoulders at a narrow turn, one stumbling to a knee. Quick stand, minor wince, no blood described. They exchanged apologies and resumed pace—light physical contact, no injury detail.''',
      category: 'violence',
      rating: RatingLevel.PG,
      label: 'PG-Violence-Holdout: minor trail collision, no blood',
    ),
    TestParagraph(
      text:
          '''Back alley confrontation: a pocket knife flashed; defender’s forearm received a shallow cut, thin blood line forming before pressure was applied. Brief grapple, weapon kicked aside. No gore, limited injury description.''',
      category: 'violence',
      rating: RatingLevel.PG13,
      label: 'PG13-Violence-Holdout: knife threat with minor blood',
    ),
    TestParagraph(
      text:
          '''Warehouse brawl: pipe strike fractured a hand—knuckles split, bone edge visible momentarily. A gash at the scalp leaked dark streaks down collar. One fighter coughed thick blood after a solar plexus blow. Short, graphic injury snapshots without lingering torture focus.''',
      category: 'violence',
      rating: RatingLevel.R,
      label: 'R-Violence-Holdout: brief graphic fight injuries',
    ),
  ];
}

String buildSampleText() {
  return [
    'He yelled: damn hell crap shit! It was a mess.',
    'They held hands briefly, then shared a passionate kiss under the moon before fading into implied intimacy.',
    'Steel clashed, blood spilled lightly while the weapon strike echoed, but nothing was described in graphic detail.',
  ].join('\n\n');
}

Future<GeminiFilterResponse> _runFilter(
  GeminiService service, {
  required String paragraph,
  required RatingLevel language,
  required RatingLevel sexual,
  required RatingLevel violence,
  required int chapterIndex,
}) async {
  return service.filterParagraph(
    paragraph: paragraph,
    profanityLevel: _mapRating(language),
    sexualContentLevel: _mapRating(sexual),
    violenceLevel: _mapRating(violence),
    chapterIndex: chapterIndex,
  );
}

void _printDiff(String original, String cleaned, {List<String>? knownRemoved}) {
  if (original == cleaned) {
    stdout.writeln('  Unchanged');
    return;
  }
  stdout.writeln(
    '  Length: original=${original.length} cleaned=${cleaned.length}',
  );
  if (knownRemoved != null) {
    if (knownRemoved.isEmpty) {
      stdout.writeln('  Removed tokens (approx): none');
    } else {
      stdout.writeln(
        '  Removed tokens (simulated): ${knownRemoved.take(12).join(', ')}${knownRemoved.length > 12 ? ' …' : ''}',
      );
    }
    return; // Skip heuristic diff when we have explicit list
  }
  // Fallback heuristic diff (API responses)
  final oTokens = original
      .split(RegExp(r'\s+'))
      .map((e) => e.trim())
      .where((e) => e.isNotEmpty)
      .toList();
  final cTokens = cleaned
      .split(RegExp(r'\s+'))
      .map((e) => e.trim())
      .where((e) => e.isNotEmpty)
      .toList();
  final removed = <String>[];
  // Track removals with order preservation
  for (final t in oTokens) {
    // Remove token once if count decreased
    final countOrig = oTokens.where((x) => x == t).length;
    final countClean = cTokens.where((x) => x == t).length;
    if (countClean < countOrig && !removed.contains(t)) {
      removed.add(t);
    }
  }
  stdout.writeln(
    '  Removed tokens (approx): ${removed.isEmpty ? 'none' : removed.take(12).join(', ')}${removed.length > 12 ? ' …' : ''}',
  );
}

void main(List<String> args) async {
  final argMap = <String, String>{};
  final flags = <String>{};
  for (var i = 0; i < args.length; i++) {
    final a = args[i];
    if (a.startsWith('--')) {
      final eq = a.indexOf('=');
      if (eq > 0) {
        argMap[a.substring(2, eq)] = a.substring(eq + 1);
      } else {
        final key = a.substring(2);
        if (i + 1 < args.length && !args[i + 1].startsWith('--')) {
          argMap[key] = args[++i];
        } else {
          flags.add(key);
        }
      }
    }
  }

  final showPromptOnly = flags.contains('show-prompt');
  final useSample = flags.contains('sample');
  final languageAll = flags.contains('language-all');
  final dryRun = flags.contains('dry-run');
  final testSuite = flags.contains('test-suite');
  final holdoutSuite = flags.contains('holdout');

  final apiKey =
      argMap['api-key'] ?? Platform.environment['GEMINI_API_KEY'] ?? '';
  final modelArg = argMap['model'];
  if (!showPromptOnly && apiKey.isEmpty && !dryRun) {
    stderr.writeln(
      'Missing API key. Set GEMINI_API_KEY or pass --api-key <key>, or use --dry-run to simulate.',
    );
    exit(2);
  }

  final languageRating = _parseRating(argMap['language'] ?? 'PG');
  final sexualRating = _parseRating(argMap['sexual'] ?? 'PG');
  final violenceRating = _parseRating(argMap['violence'] ?? 'PG');

  final text = useSample
      ? buildSampleText()
      : (argMap['text'] ?? 'Example paragraph with mild content.');
  final paragraphs = text.split('\n\n');

  final service = GeminiService(
    apiKey: apiKey.isEmpty ? 'DUMMY' : apiKey,
    model: modelArg,
  );

  if (showPromptOnly) {
    final prompt = service.buildFilteringPrompt(
      profanityLevel: _mapRating(languageRating),
      sexualContentLevel: _mapRating(sexualRating),
      violenceLevel: _mapRating(violenceRating),
    );
    stdout.writeln('--- Constructed Prompt ---');
    stdout.writeln(prompt);
    return;
  }

  // Define simulateClean before testSuite logic
  (String cleaned, List<String> removedTokens) simulateClean(
    String paragraph,
    RatingLevel lang,
  ) {
    final strong = <String>{'fuck', 'fucking', 'fucked', 'motherfucker'};
    final moderate = <String>{
      'damn',
      'hell',
      'crap',
      'shit',
      'bitch',
      'bastard',
      'ass',
    };
    final mild = <String>{'darn', 'gosh', 'jeez', 'heck'}; // PG allowed
    final removed = <String>[];
    final buf = StringBuffer();
    for (final token in paragraph.split(RegExp(r'(\s+)'))) {
      final lower = token.toLowerCase();
      final alpha = RegExp(r'^[a-zA-Z]+$').hasMatch(lower);
      if (!alpha) {
        buf.write(token);
        continue;
      }
      bool remove = false;
      switch (lang) {
        case RatingLevel.G:
          if (strong.contains(lower) ||
              moderate.contains(lower) ||
              mild.contains(lower))
            remove = true;
          break;
        case RatingLevel.PG:
          if (strong.contains(lower) || moderate.contains(lower)) remove = true;
          break;
        case RatingLevel.PG13:
          if (strong.contains(lower)) remove = true;
          break;
        case RatingLevel.R:
        case RatingLevel.Unrated:
          remove = false;
          break;
      }
      if (remove) {
        removed.add(token);
      } else {
        buf.write(token);
      }
    }
    final cleaned = buf.toString().replaceAll(RegExp(r'\s+'), ' ').trim();
    return (cleaned, removed);
  }

  if (testSuite) {
    // Run comprehensive test suite
    final suite = buildTestSuite();
    stdout.writeln('=== COMPREHENSIVE TEST SUITE ===');
    stdout.writeln('Test paragraphs: ${suite.length}');
    stdout.writeln(
      'API Key: ${apiKey.isNotEmpty ? 'SET' : 'MISSING'}  DryRun=${dryRun ? 'ON' : 'OFF'}',
    );
    stdout.writeln('');

    // Confusion matrices for each filter level
    final matrices = <RatingLevel, ConfusionMatrix>{
      RatingLevel.G: ConfusionMatrix(),
      RatingLevel.PG: ConfusionMatrix(),
      RatingLevel.PG13: ConfusionMatrix(),
      RatingLevel.R: ConfusionMatrix(),
    };

    // Group by category
    final byCategory = <String, List<TestParagraph>>{};
    for (final p in suite) {
      byCategory.putIfAbsent(p.category, () => []).add(p);
    }

    for (final category in ['language', 'sexual', 'violence']) {
      final paragraphs = byCategory[category] ?? [];
      stdout.writeln('\n### ${category.toUpperCase()} TEST SET ###');
      for (final para in paragraphs) {
        stdout.writeln('\n[${para.label}]');
        stdout.writeln('Original: "${para.text}"');

        // Test against each filter level
        for (final filterLevel in [
          RatingLevel.G,
          RatingLevel.PG,
          RatingLevel.PG13,
          RatingLevel.R,
        ]) {
          final langLevel = category == 'language'
              ? filterLevel
              : RatingLevel.Unrated;
          final sexLevel = category == 'sexual'
              ? filterLevel
              : RatingLevel.Unrated;
          final violLevel = category == 'violence'
              ? filterLevel
              : RatingLevel.Unrated;

          stdout.write('  Filter=${enumName(filterLevel)}: ');

          // Determine if content should be modified
          // Content should be modified if its rating is ABOVE the filter level
          final shouldModify = para.rating.index > filterLevel.index;

          bool wasModified = false;
          if (dryRun) {
            final result = simulateClean(para.text, langLevel);
            final cleaned = result.$1;
            final removed = result.$2;
            wasModified = (para.text != cleaned);
            if (!wasModified) {
              stdout.writeln('✓ unchanged');
            } else {
              stdout.writeln(
                'removed ${removed.length} token(s): ${removed.isEmpty ? 'none' : removed.join(', ')}',
              );
            }
          } else {
            try {
              final resp = await _runFilter(
                service,
                paragraph: para.text,
                language: langLevel,
                sexual: sexLevel,
                violence: violLevel,
                chapterIndex: 0,
              );
              wasModified = resp.wasModified;
              if (wasModified) {
                stdout.writeln(
                  'modified (len ${para.text.length} → ${resp.cleanedText.length})',
                );
              } else {
                stdout.writeln('✓ unchanged');
              }
            } catch (e) {
              stdout.writeln('ERROR: $e');
            }
          }

          // Record result in confusion matrix
          matrices[filterLevel]!.recordResult(
            shouldModify: shouldModify,
            wasModified: wasModified,
          );
        }

        // Validation check: content at/below its rating should remain unchanged
        final shouldBeUnchanged = [
          para.rating,
          if (para.rating.index < RatingLevel.R.index) RatingLevel.R,
        ];
        stdout.writeln(
          '  Expected: unchanged for ${shouldBeUnchanged.map((r) => enumName(r)).join(', ')} filters',
        );
      }
    }

    stdout.writeln('\n=== TEST SUITE COMPLETE ===');

    // Print confusion matrices
    stdout.writeln('\n=== CONFUSION MATRIX ANALYSIS ===');
    for (final level in [
      RatingLevel.G,
      RatingLevel.PG,
      RatingLevel.PG13,
      RatingLevel.R,
    ]) {
      matrices[level]!.printSummary(enumName(level));
    }

    stdout.writeln('\n=== INTERPRETATION ===');
    stdout.writeln(
      'TP (True Positive): Correctly removed inappropriate content',
    );
    stdout.writeln(
      'FP (False Positive): Incorrectly removed appropriate content',
    );
    stdout.writeln('TN (True Negative): Correctly kept appropriate content');
    stdout.writeln(
      'FN (False Negative): Incorrectly kept inappropriate content',
    );
    stdout.writeln('\nAccuracy: Overall correctness of the filter');
    stdout.writeln(
      'Precision: Of items flagged, how many were correctly flagged',
    );
    stdout.writeln('Recall: Of inappropriate items, how many were caught');

    return;
  }

  if (holdoutSuite) {
    final suite = buildHoldoutSuite();
    stdout.writeln('=== HOLDOUT TEST SUITE ===');
    stdout.writeln('Paragraphs: ${suite.length}');
    stdout.writeln(
      'API Key: ${apiKey.isNotEmpty ? 'SET' : 'MISSING'}  DryRun=${dryRun ? 'ON' : 'OFF'}',
    );
    stdout.writeln(
      'Note: This corpus is a holdout set not used in prompt tuning. Avoid adjusting prompt based solely on these results unless starting a new revision cycle.',
    );

    final matrices = <RatingLevel, ConfusionMatrix>{
      RatingLevel.G: ConfusionMatrix(),
      RatingLevel.PG: ConfusionMatrix(),
      RatingLevel.PG13: ConfusionMatrix(),
      RatingLevel.R: ConfusionMatrix(),
    };

    final byCategory = <String, List<TestParagraph>>{};
    for (final p in suite) {
      byCategory.putIfAbsent(p.category, () => []).add(p);
    }

    for (final category in ['language', 'sexual', 'violence']) {
      stdout.writeln('\n### HOLDOUT ${category.toUpperCase()} ###');
      for (final para in byCategory[category] ?? []) {
        stdout.writeln('\n[${para.label}]');
        stdout.writeln('Original: "${para.text}"');
        for (final filterLevel in [
          RatingLevel.G,
          RatingLevel.PG,
          RatingLevel.PG13,
          RatingLevel.R,
        ]) {
          final langLevel = category == 'language'
              ? filterLevel
              : RatingLevel.Unrated;
          final sexLevel = category == 'sexual'
              ? filterLevel
              : RatingLevel.Unrated;
          final violLevel = category == 'violence'
              ? filterLevel
              : RatingLevel.Unrated;
          stdout.write('  Filter=${enumName(filterLevel)}: ');
          final shouldModify = para.rating.index > filterLevel.index;
          bool wasModified = false;
          if (dryRun) {
            final result = simulateClean(para.text, langLevel);
            final cleaned = result.$1;
            wasModified = para.text != cleaned;
            stdout.writeln(
              wasModified ? 'modified (simulated)' : '✓ unchanged',
            );
          } else {
            try {
              final resp = await _runFilter(
                service,
                paragraph: para.text,
                language: langLevel,
                sexual: sexLevel,
                violence: violLevel,
                chapterIndex: 0,
              );
              wasModified = resp.wasModified;
              stdout.writeln(wasModified ? 'modified' : '✓ unchanged');
            } catch (e) {
              stdout.writeln('ERROR: $e');
            }
          }
          matrices[filterLevel]!.recordResult(
            shouldModify: shouldModify,
            wasModified: wasModified,
          );
        }
        stdout.writeln(
          '  Expected: unchanged for ${enumName(para.rating)}${para.rating.index < RatingLevel.R.index ? ', R' : ''} filters',
        );
      }
    }

    stdout.writeln('\n=== HOLDOUT CONFUSION MATRIX ===');
    for (final level in [
      RatingLevel.G,
      RatingLevel.PG,
      RatingLevel.PG13,
      RatingLevel.R,
    ]) {
      matrices[level]!.printSummary('Holdout ${enumName(level)}');
    }
    return;
  }

  stdout.writeln('--- Prompt Harness ---');
  stdout.writeln('Paragraph count: ${paragraphs.length}');
  stdout.writeln(
    'Language=${enumName(languageRating)} Sexual=${enumName(sexualRating)} Violence=${enumName(violenceRating)}',
  );
  stdout.writeln(
    'API Key: ${apiKey.isNotEmpty ? 'SET' : 'MISSING'}  DryRun=${dryRun ? 'ON' : 'OFF'}',
  );
  stdout.writeln('Model: ${service.model}');
  stdout.writeln('');

  Future<void> runScenario(RatingLevel lang) async {
    stdout.writeln(
      '== Scenario: Language=${enumName(lang)}, Sexual=${enumName(sexualRating)}, Violence=${enumName(violenceRating)} ==',
    );
    for (var i = 0; i < paragraphs.length; i++) {
      stdout.writeln(' Paragraph ${i + 1}');
      if (dryRun) {
        final result = simulateClean(paragraphs[i], lang);
        final cleaned = result.$1;
        final removedTokens = result.$2;
        _printDiff(paragraphs[i], cleaned, knownRemoved: removedTokens);
      } else {
        final resp = await _runFilter(
          service,
          paragraph: paragraphs[i],
          language: lang,
          sexual: sexualRating,
          violence: violenceRating,
          chapterIndex: i,
        );
        _printDiff(paragraphs[i], resp.cleanedText);
      }
    }
    stdout.writeln('');
  }

  if (languageAll) {
    for (final lvl in [
      RatingLevel.G,
      RatingLevel.PG,
      RatingLevel.PG13,
      RatingLevel.R,
    ]) {
      await runScenario(lvl);
    }
  } else {
    await runScenario(languageRating);
  }

  stdout.writeln('Done.');
}
