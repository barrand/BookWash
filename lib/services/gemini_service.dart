import 'package:bookwash/models/change_detail.dart';
import 'package:bookwash/models/categorized_changes.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'rate_limiter.dart';

/// Response from Gemini containing cleaned text and metadata
class GeminiFilterResponse {
  final String cleanedText;
  final String originalText;
  final List<String> removedWords;
  final List<String>
  detectedChanges; // Specific replacements like "damn -> darn"
  final bool wasModified;
  final CategorizedChanges categorizedChanges;

  GeminiFilterResponse({
    required this.cleanedText,
    required this.originalText,
    required this.removedWords,
    required this.detectedChanges,
    required this.wasModified,
    required this.categorizedChanges,
  });

  factory GeminiFilterResponse.fromTexts({
    required String original,
    required String cleaned,
    required int chapterIndex,
    bool skipProfanityCategorization = false,
    bool skipSexualCategorization = false,
    bool skipViolenceCategorization = false,
  }) {
    final wasModified = original.trim() != cleaned.trim();
    final categorizedChanges = wasModified
        ? _categorizeChanges(
            original,
            cleaned,
            chapterIndex,
            skipProfanity: skipProfanityCategorization,
            skipSexual: skipSexualCategorization,
            skipViolence: skipViolenceCategorization,
          )
        : CategorizedChanges(profanity: [], sexual: [], violence: []);
    final removedWords = wasModified
        ? _detectRemovedWords(original, cleaned)
        : <String>[];
    final detectedChanges = wasModified
        ? _detectSpecificChanges(original, cleaned)
        : <String>[];

    return GeminiFilterResponse(
      cleanedText: cleaned,
      originalText: original,
      removedWords: removedWords,
      detectedChanges: detectedChanges,
      wasModified: wasModified,
      categorizedChanges: categorizedChanges,
    );
  }

  static CategorizedChanges _categorizeChanges(
    String original,
    String cleaned,
    int chapterIndex, {
    bool skipProfanity = false,
    bool skipSexual = false,
    bool skipViolence = false,
  }) {
    final profanityChanges = <ChangeDetail>[];
    final sexualChanges = <ChangeDetail>[];
    final violenceChanges = <ChangeDetail>[];

    final originalWords = original.toLowerCase().split(RegExp(r'\s+'));
    final cleanedSet = cleaned.toLowerCase().split(RegExp(r'\s+')).toSet();

    const profanityKeywords = {
      'damn',
      'shit',
      'bullshit',
      'crap',
      'hell',
      'ass',
      'asshole',
      'bitch',
      'fuck',
      'fucking',
      'fucked',
      'motherfucker',
      'bastard',
    };

    const sexualKeywords = {
      'cleavage',
      'neckline',
      'sexy',
      'passionate',
      'kiss',
      'kissing',
    };

    const violenceKeywords = {
      'punch',
      'hit',
      'fight',
      'blood',
      'kill',
      'violence',
      'weapon',
    };

    String obfuscateWord(String word) {
      if (word.length <= 2) return '*' * word.length;
      if (word.length == 3) return '${word[0]}*${word[2]}';
      return '${word[0]}${'*' * (word.length - 2)}${word[word.length - 1]}';
    }

    for (final word in originalWords) {
      final cleanWord = word.replaceAll(RegExp(r'[^\w]'), '');
      if (cleanWord.isEmpty) continue;

      if (!cleanedSet.contains(cleanWord)) {
        if (profanityKeywords.contains(cleanWord) && !skipProfanity) {
          profanityChanges.add(
            ChangeDetail(
              category: 'profanity',
              obfuscatedWord: obfuscateWord(cleanWord),
              chapterIndex: chapterIndex,
              originalWord: cleanWord,
            ),
          );
        } else if (sexualKeywords.contains(cleanWord) && !skipSexual) {
          sexualChanges.add(
            ChangeDetail(
              category: 'sexual',
              obfuscatedWord: obfuscateWord(cleanWord),
              chapterIndex: chapterIndex,
              originalWord: cleanWord,
            ),
          );
        } else if (violenceKeywords.contains(cleanWord) && !skipViolence) {
          violenceChanges.add(
            ChangeDetail(
              category: 'violence',
              obfuscatedWord: obfuscateWord(cleanWord),
              chapterIndex: chapterIndex,
              originalWord: cleanWord,
            ),
          );
        }
      }
    }

    return CategorizedChanges(
      profanity: profanityChanges,
      sexual: sexualChanges,
      violence: violenceChanges,
    );
  }

  static List<String> _detectRemovedWords(String original, String cleaned) {
    final removed = <String>[];
    final originalWords = original.toLowerCase().split(RegExp(r'\s+'));
    final cleanedWords = cleaned.toLowerCase().split(RegExp(r'\s+'));
    final cleanedSet = cleanedWords.toSet();

    final keywords = [
      'damn',
      'shit',
      'bullshit',
      'crap',
      'hell',
      'ass',
      'asshole',
      'bitch',
      'fuck',
      'fucking',
      'fucked',
      'motherfucker',
      'bastard',
      'cleavage',
      'neckline',
      'sexy',
      'passionate',
      'kiss',
      'kissing',
      'punch',
      'hit',
      'fight',
      'blood',
      'kill',
      'violence',
      'weapon',
    ];

    for (final word in originalWords) {
      final cleanWord = word.replaceAll(RegExp(r'[^\w]'), '');
      if (keywords.contains(cleanWord) && !cleanedSet.contains(cleanWord)) {
        if (!removed.contains(cleanWord)) {
          removed.add(cleanWord);
        }
      }
    }

    return removed;
  }

  /// Detect specific word replacements (e.g., "damn" -> "darn")
  static List<String> _detectSpecificChanges(String original, String cleaned) {
    final changes = <String>[];

    // Keywords we're looking for
    final keywords = {
      'damn',
      'shit',
      'bullshit',
      'crap',
      'hell',
      'ass',
      'asshole',
      'bitch',
      'fuck',
      'fucking',
      'fucked',
      'motherfucker',
      'bastard',
      'cleavage',
      'neckline',
      'sexy',
      'passionate',
      'kiss',
      'kissing',
      'punch',
      'hit',
      'fight',
      'blood',
      'kill',
      'violence',
      'weapon',
    };

    // Simple approach: look for words that appear in original but not in cleaned
    final originalLower = original.toLowerCase();
    final cleanedLower = cleaned.toLowerCase();

    for (final keyword in keywords) {
      final keywordRegex = RegExp(
        r'\b' + keyword + r'\b',
        caseSensitive: false,
      );
      final inOriginal = keywordRegex.hasMatch(originalLower);
      final inCleaned = keywordRegex.hasMatch(cleanedLower);

      if (inOriginal && !inCleaned) {
        // Try to find what it was replaced with by looking at context
        final match = keywordRegex.firstMatch(original);
        if (match != null) {
          // For now, just note that it was removed/changed
          changes.add('$keyword (removed/changed)');
        }
      }
    }

    // If no specific changes detected but text differs, note generic change
    if (changes.isEmpty && original.trim() != cleaned.trim()) {
      changes.add('Content modified');
    }

    return changes;
  }
}

/// Service for communicating with Google Gemini API
class GeminiService {
  /*
  Rating Principles (summary for maintainability):
  - G: No profanity, insults, romantic/sexual content, or physical violence.
  - PG: Very mild exclamations; innocent light romance; mild, non-graphic action.
  - PG-13: Moderate profanity (excluding f-word), implied intimacy, sustained action with limited non-graphic blood.
  - R: Strong profanity including f-word, explicit (non-pornographic) sexual references, intense violence without extreme gore detail.
  - X: Graphic sexual detail or extreme gore/torture (always remove for any filtering level below 5/unrated).
  Filtering relies on model's internal classification, not exhaustive word lists; replacements must be minimal and preserve narrative tone & paragraph count.
  */
  final String apiKey;
  final String model;
  final Duration timeout;
  final SimpleRateLimiter? rateLimiter;

  GeminiService({
    required this.apiKey,
    String? model,
    this.timeout = const Duration(seconds: 75), // slightly longer default
    SimpleRateLimiter? rateLimiter,
  }) : model =
           model ??
           const String.fromEnvironment(
             'GEMINI_MODEL',
             defaultValue: 'gemini-2.0-flash-exp',
           ),
       rateLimiter = rateLimiter ?? _buildDefaultLimiter();

  static SimpleRateLimiter _buildDefaultLimiter() {
    final rpmStr = const String.fromEnvironment(
      'GEMINI_RPM_LIMIT',
      defaultValue: '50',
    );
    final rpm = int.tryParse(rpmStr) ?? 50;
    return SimpleRateLimiter(maxRequestsPerMinute: rpm);
  }

  /// Expose current filtering prompt (for harness/testing) without issuing a request.
  String buildFilteringPrompt({
    required int profanityLevel,
    required int sexualContentLevel,
    required int violenceLevel,
  }) => _buildFilteringPrompt(
    profanityLevel: profanityLevel,
    sexualContentLevel: sexualContentLevel,
    violenceLevel: violenceLevel,
  );

  /// Check if API key is valid
  Future<bool> checkConnection() async {
    if (apiKey.isEmpty) return false;

    try {
      final response = await http
          .get(
            Uri.parse(
              'https://generativelanguage.googleapis.com/v1beta/models/$model?key=$apiKey',
            ),
          )
          .timeout(const Duration(seconds: 5));
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  /// Get list of available models
  Future<List<String>> getAvailableModels() async {
    try {
      final response = await http
          .get(
            Uri.parse(
              'https://generativelanguage.googleapis.com/v1beta/models?key=$apiKey',
            ),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final models = data['models'] as List<dynamic>?;
        if (models != null) {
          return models
              .map((m) => m['name'] as String? ?? '')
              .where((name) => name.contains('gemini'))
              .map((name) => name.replaceAll('models/', ''))
              .toList();
        }
      }
      return [model]; // Return default if API call fails
    } catch (e) {
      return [model];
    }
  }

  /// Send a filtering request to Gemini
  Future<String> filterText({
    required String text,
    required String prompt,
    void Function(Duration)? onRateLimit,
  }) async {
    int attempt = 0;
    const maxAttempts = 5;

    while (attempt < maxAttempts) {
      final requestBody = {
        'contents': [
          {
            'parts': [
              {'text': '$prompt\n\nText to filter:\n$text'},
            ],
          },
        ],
        'generationConfig': {
          'temperature': 0.1,
          'topP': 0.9,
          'maxOutputTokens': 8192,
        },
        'safetySettings': [
          {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_NONE'},
          {'category': 'HARM_CATEGORY_HATE_SPEECH', 'threshold': 'BLOCK_NONE'},
          {
            'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT',
            'threshold': 'BLOCK_NONE',
          },
          {
            'category': 'HARM_CATEGORY_DANGEROUS_CONTENT',
            'threshold': 'BLOCK_NONE',
          },
        ],
      };

      // Rate limiter slot
      if (rateLimiter != null) {
        await rateLimiter!.acquire();
      }

      final response = await http
          .post(
            Uri.parse(
              'https://generativelanguage.googleapis.com/v1beta/models/$model:generateContent?key=$apiKey',
            ),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(requestBody),
          )
          .timeout(timeout);

      if (response.statusCode == 200) {
        final data = jsonDecode(utf8.decode(response.bodyBytes));
        final candidates = data['candidates'] as List<dynamic>?;
        if (candidates != null && candidates.isNotEmpty) {
          final content = candidates[0]['content'];
          final parts = content['parts'] as List<dynamic>?;
          if (parts != null && parts.isNotEmpty) {
            return parts[0]['text'] as String? ?? '';
          }
        }
        return '';
      } else if (response.statusCode == 429) {
        // Rate limit exceeded
        attempt++;
        if (attempt >= maxAttempts) {
          throw Exception(
            'Gemini request failed after $maxAttempts attempts due to rate limiting.',
          );
        }
        // Exponential backoff (scaled up slightly): 3s, 6s, 12s, 24s with optional jitter
        final baseSeconds = const String.fromEnvironment(
          'GEMINI_BACKOFF_BASE_SECONDS',
          defaultValue: '3',
        );
        final base = int.tryParse(baseSeconds) ?? 3;
        var delay = Duration(seconds: base * (1 << (attempt - 1)));
        // Add light jitter ±15%
        final jitterMillis = (delay.inMilliseconds * 0.15).round();
        final sign = (DateTime.now().millisecond % 2 == 0) ? 1 : -1;
        delay = Duration(
          milliseconds:
              delay.inMilliseconds +
              sign * (DateTime.now().microsecondsSinceEpoch % jitterMillis),
        );
        print('Rate limit hit. Waiting for $delay before retrying...');
        if (onRateLimit != null) {
          onRateLimit(delay);
        }
        await Future.delayed(delay);
      } else {
        throw Exception(
          'Gemini request failed with status ${response.statusCode}: ${response.body}',
        );
      }
    }
    throw Exception('Gemini request failed after $maxAttempts attempts.');
  }

  /// Filter a paragraph based on sensitivity levels
  Future<GeminiFilterResponse> filterParagraph({
    required String paragraph,
    required int profanityLevel,
    required int sexualContentLevel,
    required int violenceLevel,
    required int chapterIndex,
    void Function(Duration)? onRateLimit,
  }) async {
    // If all levels are 5 (Unrated), skip filtering entirely
    if (profanityLevel == 5 && sexualContentLevel == 5 && violenceLevel == 5) {
      return GeminiFilterResponse(
        cleanedText: paragraph,
        originalText: paragraph,
        removedWords: [],
        detectedChanges: [],
        wasModified: false,
        categorizedChanges: CategorizedChanges(
          profanity: [],
          sexual: [],
          violence: [],
        ),
      );
    }

    final prompt = _buildFilteringPrompt(
      profanityLevel: profanityLevel,
      sexualContentLevel: sexualContentLevel,
      violenceLevel: violenceLevel,
    );

    var cleanedText = await filterText(
      text: paragraph, // Send original text
      prompt: prompt,
      onRateLimit: onRateLimit,
    );

    // R-level safeguard: if any dimension is R (4) and model returned an empty
    // paragraph, revert to original to enforce "minimal/no filtering" rule.
    final anyR =
        profanityLevel == 4 || sexualContentLevel == 4 || violenceLevel == 4;
    if (anyR && paragraph.trim().isNotEmpty && cleanedText.trim().isEmpty) {
      cleanedText = paragraph; // preserve original content
    }

    return GeminiFilterResponse.fromTexts(
      original: paragraph,
      cleaned: cleanedText,
      chapterIndex: chapterIndex,
      skipProfanityCategorization: skipProfanityCategorization,
      skipSexualCategorization: skipSexualCategorization,
      skipViolenceCategorization: skipViolenceCategorization,
    );
  }

  /// Convert rating level to name
  String _getRatingName(int level) {
    switch (level) {
      case 1:
        return 'G';
      case 2:
        return 'PG';
      case 3:
        return 'PG-13';
      case 4:
        return 'R';
      case 5:
        return 'Unrated';
      default:
        return 'Unknown';
    }
  }

  /// Build a comprehensive filtering prompt based on sensitivity levels
  String _buildFilteringPrompt({
    required int profanityLevel,
    required int sexualContentLevel,
    required int violenceLevel,
  }) {
    final buffer = StringBuffer();

    buffer.writeln(
      'You are a content filter for books. Your task is to clean the following text by removing or rephrasing inappropriate content based on the specified sensitivity levels.',
    );

    // Note which dimensions are unrated
    final unratedDimensions = <String>[];
    if (profanityLevel == 5) unratedDimensions.add('language/profanity');
    if (sexualContentLevel == 5) unratedDimensions.add('sexual content');
    if (violenceLevel == 5) unratedDimensions.add('violence');

    if (unratedDimensions.isNotEmpty) {
      buffer.writeln('⚠️ UNRATED DIMENSIONS - DO NOT FILTER:');
      buffer.writeln(
        'The following content types are UNRATED and must be kept EXACTLY as written:',
      );
      for (final dim in unratedDimensions) {
        buffer.writeln(
          '  - $dim: Keep ALL content unchanged, no matter how strong',
        );
      }
      buffer.writeln();
    }
    buffer.writeln();
    buffer.writeln('CRITICAL RULES - FOLLOW EXACTLY:');
    buffer.writeln(
      '1. Return ONLY the cleaned text itself - no explanations, no metadata, no commentary, no prefixes like "Here is..."',
    );
    buffer.writeln(
      '2. NEVER use [...] or ellipses - always replace removed content with natural, flowing alternatives that maintain story coherence',
    );
    buffer.writeln('3. ⚠️ ABSOLUTELY CRITICAL PARAGRAPH PRESERVATION ⚠️');
    buffer.writeln(
      '   - The input text contains multiple paragraphs separated by double line breaks (\\n\\n)',
    );
    buffer.writeln('   - You MUST output the EXACT SAME NUMBER of paragraphs');
    buffer.writeln(
      '   - Separate each paragraph with EXACTLY double line breaks (\\n\\n)',
    );
    buffer.writeln(
      '   - DO NOT merge paragraphs together under ANY circumstances',
    );
    buffer.writeln('   - DO NOT split paragraphs into multiple paragraphs');
    buffer.writeln(
      '   - Count the input paragraphs and ensure your output has the same count',
    );
    buffer.writeln(
      '   - If the input has 10 paragraphs, your output MUST have 10 paragraphs',
    );
    buffer.writeln(
      '4. Keep ALL punctuation, formatting, quotation marks, and text structure EXACTLY as they appear',
    );
    buffer.writeln(
      '5. CRITICAL CHARACTER ENCODING: Use ONLY basic ASCII characters (a-z, A-Z, 0-9, and standard punctuation like -.,;:!?\'")',
    );
    buffer.writeln(
      '6. NEVER use unicode dashes, quotes, or special characters. Use regular hyphens (-), regular apostrophes, and regular quotes',
    );
    buffer.writeln(
      '7. If you see characters like em-dashes or curly quotes in the original, keep them. Only avoid adding NEW unicode characters',
    );
    buffer.writeln(
      '8. When removing content, use MINIMAL replacements - prefer simple phrases over creative elaboration',
    );
    buffer.writeln(
      '9. DO NOT add new plot elements, details, or story content that was not in the original text',
    );
    buffer.writeln(
      '10. DO NOT hallucinate or invent replacement content - keep it simple and vague',
    );
    buffer.writeln(
      '11. Preserve the emotional tone and narrative voice - if a character is angry, keep them angry (just without prohibited words)',
    );
    buffer.writeln(
      '12. The cleaned text must read naturally and smoothly - no awkward gaps or jumps',
    );
    buffer.writeln();
    buffer.writeln('REPLACEMENT EXAMPLES:');
    buffer.writeln('BAD: "Maya looked like [...] in public"');
    buffer.writeln(
      'GOOD: "Maya looked upset in public" or "Maya looked angry in public"',
    );
    buffer.writeln(
      'BAD: "skin felt under her fingers-warm" (with weird dash character)',
    );
    buffer.writeln(
      'GOOD: "skin felt under her fingers - warm" (with regular hyphen and spaces)',
    );
    buffer.writeln('BAD: "They [...] together that night"');
    buffer.writeln(
      'GOOD: "They spent the evening together" or "They stayed together that night"',
    );
    buffer.writeln(
      'CRITICAL: Check your output text - if you see garbled characters, FIX THEM with regular ASCII characters',
    );
    buffer.writeln();
    buffer.writeln('CRITICAL: For sexual content removal:');
    buffer.writeln(
      '- Use SIMPLE, VAGUE phrases: "they connected", "they were together", "later that evening"',
    );
    buffer.writeln(
      '- DO NOT invent new activities or details (no "they talked", "they cooked dinner", "they watched movies")',
    );
    buffer.writeln(
      '- DO NOT add story elements that were not present in the original',
    );
    buffer.writeln(
      '- If the entire paragraph is sexual content, replace with a single simple sentence or remove entirely',
    );
    buffer.writeln();

    // Language filtering instructions (principle-based, minimal examples)
    if (profanityLevel < 5) {
      buffer.writeln(
        'LANGUAGE/PROFANITY FILTERING (Target Rating: ${_getRatingName(profanityLevel)}):',
      );
      buffer.writeln();
      buffer.writeln('🎯 YOUR TASK:');
      buffer.writeln('1. Read each sentence/phrase in the text');
      buffer.writeln(
        '2. Ask yourself: "What rating would this language get?" (G, PG, PG-13, R, or X)',
      );
      buffer.writeln(
        '3. If the rating is HIGHER than ${_getRatingName(profanityLevel)}, remove or replace that language',
      );
      buffer.writeln(
        '4. If the rating matches or is lower than ${_getRatingName(profanityLevel)}, keep it',
      );
      buffer.writeln();
      switch (profanityLevel) {
        case 1: // G Rated
          buffer.writeln('TARGET: G (Early readers / children).');
          buffer.writeln(
            'Keep only neutral everyday language. Remove all insults and any form of profanity (even mild).',
          );
          buffer.writeln(
            'If a word expresses crude bodily function or insult → replace with a neutral emotional descriptor ("upset", "bothered").',
          );
          buffer.writeln(
            'CRITICAL: Do NOT remove professional, academic, investigative, or procedural language when it contains no profanity.',
          );
          break;
        case 2: // PG Rated
          buffer.writeln('TARGET: PG (Family friendly).');
          buffer.writeln(
            '✅ EXPLICITLY ALLOWED: "darn", "dang", "gosh", "golly", "jeez", "heck", "shoot", "crud" (and similar very mild exclamations).',
          );
          buffer.writeln(
            '❌ MUST REMOVE: "damn", "hell", "crap", "shit", "ass", "bitch", "bastard", "fuck" (and all stronger profanity).',
          );
          buffer.writeln(
            'Replace removed words with neutral emotion ("frustrated", "upset") or allowed mild exclamations.',
          );
          buffer.writeln(
            'CRITICAL: If content contains only PG-allowed words like "gosh" or "darn", DO NOT MODIFY IT.',
          );
          buffer.writeln(
            'When uncertain at PG, prefer keeping mild, non-profane exclamations unmodified.',
          );
          break;
        case 3: // PG-13 Rated
          buffer.writeln('TARGET: PG-13 (Teen).');
          buffer.writeln(
            '✅ EXPLICITLY ALLOWED: "damn", "hell", "crap", "ass", "bastard", "bitch" (moderate profanity), plus all PG-allowed words.',
          );
          buffer.writeln(
            '❌ MUST REMOVE: "fuck", "fucking", "shit" (strong profanity and f-word variants).',
          );
          buffer.writeln(
            'CRITICAL: If content uses only PG-13-allowed profanity (damn, hell, crap, ass, bastard, bitch), DO NOT MODIFY IT.',
          );
          buffer.writeln(
            'Edge cases: Compound words like "half-ass" and contextual uses of "bastard"/"bitch" (non-hate-speech, descriptive) are ALLOWED at PG-13.',
          );
          buffer.writeln(
            'Only remove or soften f-word variants and extremely graphic language.',
          );
          break;
        case 4: // R Rated
          buffer.writeln('TARGET: R (Adult - MINIMAL TO NO FILTERING).');
          buffer.writeln(
            '⚠️ CRITICAL: R rating allows ALL standard profanity including f-word and all sexual/violent language.',
          );
          buffer.writeln(
            '✅ KEEP EVERYTHING: All profanity, strong language, explicit references are ALLOWED at R rating.',
          );
          buffer.writeln(
            '❌ Only remove if content would be rated NC-17/X: extreme torture detail, graphic sexual penetration descriptions, or snuff content.',
          );
          buffer.writeln(
            'CRITICAL: For R rating, your default action is to RETURN THE TEXT UNCHANGED. Only filter the most extreme NC-17/X content.',
          );
          buffer.writeln(
            'If in doubt at R, prefer keeping the original wording unchanged.',
          );
          break;
      }
      buffer.writeln();
    }

    // Sexual content filtering instructions (principle-based)
    if (sexualContentLevel < 5) {
      buffer.writeln(
        'SEXUAL CONTENT FILTERING (Target Rating: ${_getRatingName(sexualContentLevel)}):',
      );
      buffer.writeln();
      buffer.writeln('🎯 YOUR TASK:');
      buffer.writeln('1. Read each sentence/phrase/scene in the text');
      buffer.writeln(
        '2. Ask yourself: "What rating would this romantic/sexual content get?" (G, PG, PG-13, R, or X)',
      );
      buffer.writeln(
        '3. If the rating is HIGHER than ${_getRatingName(sexualContentLevel)}, remove or replace that content',
      );
      buffer.writeln(
        '4. If the rating matches or is lower than ${_getRatingName(sexualContentLevel)}, keep it',
      );
      buffer.writeln();
      switch (sexualContentLevel) {
        case 1: // G
          buffer.writeln(
            'G: Remove all romantic or suggestive content. Keep only neutral relationships (friends, family).',
          );
          buffer.writeln(
            'If a paragraph is entirely romantic/sexual → replace with a single neutral summary or remove.',
          );
          break;
        case 2: // PG
          buffer.writeln(
            'PG: Permit mild innocent romance (brief hand-hold, a quick non-sensual kiss, hugs, friendly physical contact).',
          );
          buffer.writeln(
            '✅ ALLOWED: Holding hands, cheek kiss, brief kiss on lips, emotional connection, gentle touch.',
          );
          buffer.writeln(
            '❌ REMOVE: Passionate kissing, body focus, sensuality, arousal, implied intimacy, sexual tension.',
          );
          buffer.writeln(
            'CRITICAL: If content shows only innocent hand-holding and brief kisses, DO NOT MODIFY IT.',
          );
          break;
        case 3: // PG-13
          buffer.writeln(
            'PG-13: Allow implied intimacy (fade-to-black), passionate kissing, romantic physical contact.',
          );
          buffer.writeln(
            '✅ ALLOWED: Passionate kissing, bodies pressed close, "spent the night together", "made love" (implied only), sensual tension, partial undressing leading to fade-to-black.',
          );
          buffer.writeln(
            '❌ REMOVE: Explicit sexual acts, anatomical detail, graphic descriptions of intercourse, visible nudity descriptions.',
          );
          buffer.writeln(
            'CRITICAL: If content implies intimacy but fades to black ("later that evening" / "they were together"), DO NOT MODIFY IT.',
          );
          buffer.writeln(
            'HARD GUARDRAIL: If a paragraph contains ONLY heated kissing + bodies pressed + implied progression (no anatomical specifics, no explicit act terms) you MUST return it EXACTLY AS WRITTEN (no summarizing, shortening, tonal softening, or replacement).',
          );
          break;
        case 4: // R
          buffer.writeln(
            'R: Allow explicit sexual content and references (MINIMAL FILTERING).',
          );
          buffer.writeln(
            '✅ ALLOWED: Explicit sexual acts, undressing, touching intimate areas, sensual detail, moaning/gasping, penetration references.',
          );
          buffer.writeln(
            '❌ Only remove if NC-17/X: Extreme fetish detail, graphic close-up anatomical descriptions written like pornography.',
          );
          buffer.writeln(
            'CRITICAL: R rating allows sexually explicit content. Default to KEEPING THE TEXT UNCHANGED unless it crosses into pornographic territory.',
          );
          break;
      }
      buffer.writeln();
    }

    // Violence filtering instructions (principle-based)
    if (violenceLevel < 5) {
      buffer.writeln(
        'VIOLENCE FILTERING (Target Rating: ${_getRatingName(violenceLevel)}):',
      );
      buffer.writeln();
      buffer.writeln('🎯 YOUR TASK:');
      buffer.writeln('1. Read each sentence/phrase/scene in the text');
      buffer.writeln(
        '2. Ask yourself: "What rating would this violence get?" (G, PG, PG-13, R, or X)',
      );
      buffer.writeln(
        '3. If the rating is HIGHER than ${_getRatingName(violenceLevel)}, remove or replace that content',
      );
      buffer.writeln(
        '4. If the rating matches or is lower than ${_getRatingName(violenceLevel)}, keep it',
      );
      buffer.writeln();
      switch (violenceLevel) {
        case 1: // G
          buffer.writeln(
            'G: Keep only non-physical conflict (arguments, tension). Remove all physical harm, weapons, injury, threat mentions.',
          );
          buffer.writeln(
            'ALLOWED AT G: Abstract references like "heated dispute", "verbal clash", "threat of violence" (as long as NO physical contact happens). Do NOT remove words like "violence" when they refer to potential or avoided harm. Preserve professional/legal/investigative descriptions of conflict if no injury occurs.',
          );
          buffer.writeln(
            'DO NOT: invent new outcomes, escalate a verbal exchange into physical action, or delete an entire paragraph that only contains verbal tension.',
          );
          buffer.writeln(
            'HARD GUARDRAIL: If a paragraph has ONLY verbal disagreement / posture / abstract threat language, RETURN IT UNCHANGED (no shortening, no paraphrase).',
          );
          break;
        case 2: // PG
          buffer.writeln('PG: Allow mild, non-graphic physical action.');
          buffer.writeln(
            '✅ ALLOWED: Shoving, scuffling, brief fights, mention of being hit, non-graphic pain ("it hurt").',
          );
          buffer.writeln(
            '❌ REMOVE: Blood, injury detail, weapon focus, prolonged violence, graphic pain descriptions.',
          );
          buffer.writeln(
            'CRITICAL: If content shows only brief scuffles without blood or injury detail, DO NOT MODIFY IT.',
          );
          buffer.writeln(
            'GUARDRAIL: A playground shove + minor scrape stays UNCHANGED. Do NOT add moralizing narration or alter chronology. If you must soften, replace ONLY the single offending word/phrase (e.g., remove explicit "blood" mention).',
          );
          break;
        case 3: // PG-13
          buffer.writeln(
            'PG-13: Allow sustained action with blood and injury.',
          );
          buffer.writeln(
            '✅ ALLOWED: Blood mentions ("drawing blood", "crimson spread"), weapon use (blades, guns), injuries (wounds, cuts), staggering, pain.',
          );
          buffer.writeln(
            '❌ REMOVE: Graphic gore (organs visible, bone showing through flesh), extreme torture detail, prolonged suffering focus.',
          );
          buffer.writeln(
            'CRITICAL: If content mentions blood and weapons without extreme gore, DO NOT MODIFY IT.',
          );
          buffer.writeln(
            'EDGE: Single-sentence vivid injury descriptions are fine; only tone down multi-sentence anatomical gore sequences.',
          );
          break;
        case 4: // R
          buffer.writeln(
            'R: Allow intense violence, graphic injury, and gore (MINIMAL FILTERING).',
          );
          buffer.writeln(
            '✅ ALLOWED: Graphic violence, blood spurting, visible bone/organs, intense injury detail, screaming, violent death.',
          );
          buffer.writeln(
            '❌ Only remove if NC-17/X: Prolonged torture porn, sadistic detail designed purely to shock with no narrative purpose.',
          );
          buffer.writeln(
            'CRITICAL: R rating allows graphic violence. Default to KEEPING THE TEXT UNCHANGED unless it crosses into torture-porn territory.',
          );
          buffer.writeln(
            'HARD GUARDRAIL: NEVER delete an entire paragraph at R. NEVER output an empty paragraph. If violence is extreme, lightly soften ONLY the most gratuitous anatomical or lingering torture descriptors; retain sequence of events.',
          );
          buffer.writeln(
            'If a paragraph is sustained torture: keep structure; you may replace ultra-graphic clauses with concise phrases like "inflicted severe pain" or "the injuries were extensive". DO NOT remove all content.',
          );
          buffer.writeln(
            'If unsure whether detail is NC-17/X, KEEP IT. Ambiguity defaults to preservation at R.',
          );
          break;
      }
      buffer.writeln();
    }

    buffer.writeln(
      'Now, filter the following text according to these rules. Return ONLY the cleaned text:',
    );
    buffer.writeln('FAILURE CONDITIONS TO AVOID:');
    buffer.writeln('- Deleting or collapsing paragraphs (must preserve count)');
    buffer.writeln(
      '- Returning blank paragraphs (never output length 0 unless original was blank)',
    );
    buffer.writeln('- Adding new plot details (events not present originally)');
    buffer.writeln('- Moralizing tone shifts or character voice changes');
    buffer.writeln(
      '- Replacing entire R-rated violent paragraphs with emptiness',
    );
    buffer.writeln(
      '- Expanding mild scenes with invented explanatory sentences',
    );
    buffer.writeln();

    return buffer.toString();
  }
}

/// Content rating (G, PG, PG-13, R, X)
enum ContentRating { G, PG, PG13, R, X }

/// Ratings for different content types
class ContentRatings {
  final ContentRating language;
  final ContentRating sexualContent;
  final ContentRating violence;

  ContentRatings({
    required this.language,
    required this.sexualContent,
    required this.violence,
  });

  /// Parse rating from string (e.g., "PG" -> ContentRating.PG)
  static ContentRating parseRating(String rating) {
    switch (rating.toUpperCase()) {
      case 'G':
        return ContentRating.G;
      case 'PG':
        return ContentRating.PG;
      case 'PG-13':
      case 'PG13':
        return ContentRating.PG13;
      case 'R':
        return ContentRating.R;
      case 'X':
        return ContentRating.X;
      default:
        return ContentRating.PG;
    }
  }

  @override
  String toString() {
    return 'Language: ${language.name}, Sexual: ${sexualContent.name}, Violence: ${violence.name}';
  }
}

/// Response from rating a chapter
class ChapterRatingResponse {
  final ContentRatings ratings;
  final String summary;

  ChapterRatingResponse({required this.ratings, required this.summary});
}

/// Extension to add rating method to GeminiService
extension RatingExtension on GeminiService {
  /// Rate a chapter for content and return ratings
  Future<ChapterRatingResponse> rateChapter({
    required String text,
    void Function(Duration)? onRateLimit,
  }) async {
    final prompt =
        '''Analyze the following text and rate it for content in three categories.
  For each category, respond with ONLY one of: G, PG, PG-13, R, or X

  Categories (updated definitions for consistency with filtering logic):
  1. LANGUAGE (profanity, cursing)
    - G: No profanity or insults at all (no "stupid", "idiot")
    - PG: ONLY very mild exclamations (darn, gosh, gee, jeez, heck) and neutral language. No damn/hell/crap/ass/shit/f*** etc.
    - PG-13: Includes moderate profanity (damn, hell, crap, ass, bastard) but NO f-word usage
    - R: Strong profanity including f-word usage, repeated harsh profanity
    - X: Extreme or graphic sexual profanity / hate slurs (language only)

  2. SEXUAL CONTENT (romantic, sexual, suggestive)
    - G: No romantic/sexual content (only platonic)
    - PG: Light romance: brief hand-holding, a single brief kiss, mild affection
    - PG-13: Passionate kissing, implied intimacy (fade-to-black), mild sensual language
    - R: Descriptive sexual scenes or sustained intimate detail
    - X: Explicit sexual activity described graphically

  3. VIOLENCE (fighting, gore, harm)
    - G: No physical violence (arguments only)
    - PG: Mild action, non-detailed scuffles, no blood
    - PG-13: Combat, injuries, some blood, weapon use without gore detail
    - R: Graphic injury detail, notable gore, intense sustained violence
    - X: Extreme gore/torture, sadistic or shocking graphic detail

  Respond in exactly this format (one rating per line):
  LANGUAGE: [G/PG/PG-13/R/X]
  SEXUAL: [G/PG/PG-13/R/X]
  VIOLENCE: [G/PG/PG-13/R/X]
  SUMMARY: [Brief 1-2 sentence summary of the most restrictive content]

  Text to analyze:''';

    try {
      final result = await filterText(
        text: text,
        prompt: prompt,
        onRateLimit: onRateLimit,
      );

      // Parse the response
      final lines = result.split('\n');
      ContentRating language = ContentRating.G;
      ContentRating sexual = ContentRating.G;
      ContentRating violence = ContentRating.G;
      String summary = '';

      for (final line in lines) {
        if (line.startsWith('LANGUAGE:')) {
          language = ContentRatings.parseRating(
            line.replaceAll('LANGUAGE:', '').trim(),
          );
        } else if (line.startsWith('SEXUAL:')) {
          sexual = ContentRatings.parseRating(
            line.replaceAll('SEXUAL:', '').trim(),
          );
        } else if (line.startsWith('VIOLENCE:')) {
          violence = ContentRatings.parseRating(
            line.replaceAll('VIOLENCE:', '').trim(),
          );
        } else if (line.startsWith('SUMMARY:')) {
          summary = line.replaceAll('SUMMARY:', '').trim();
        }
      }

      return ChapterRatingResponse(
        ratings: ContentRatings(
          language: language,
          sexualContent: sexual,
          violence: violence,
        ),
        summary: summary,
      );
    } catch (e) {
      print('Error rating chapter: $e');
      // Default to PG if error
      return ChapterRatingResponse(
        ratings: ContentRatings(
          language: ContentRating.PG,
          sexualContent: ContentRating.PG,
          violence: ContentRating.PG,
        ),
        summary: 'Error rating content',
      );
    }
  }
}
