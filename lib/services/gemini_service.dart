import 'dart:convert';
import 'package:http/http.dart' as http;

/// Response from Gemini containing cleaned text and metadata
class GeminiFilterResponse {
  final String cleanedText;
  final String originalText;
  final List<String> removedWords;
  final List<String>
  detectedChanges; // Specific replacements like "damn -> darn"
  final bool wasModified;

  GeminiFilterResponse({
    required this.cleanedText,
    required this.originalText,
    required this.removedWords,
    required this.detectedChanges,
    required this.wasModified,
  });

  factory GeminiFilterResponse.fromTexts({
    required String original,
    required String cleaned,
  }) {
    final wasModified = original.trim() != cleaned.trim();
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
  final String apiKey;
  final String model;
  final Duration timeout;

  GeminiService({
    required this.apiKey,
    this.model = 'gemini-2.0-flash-exp', // Free tier: 1500 RPD, 10 RPM
    this.timeout = const Duration(seconds: 60),
  });

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
  }) async {
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
        'maxOutputTokens': 2048,
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
      final data = jsonDecode(response.body);
      final candidates = data['candidates'] as List<dynamic>?;
      if (candidates != null && candidates.isNotEmpty) {
        final content = candidates[0]['content'];
        final parts = content['parts'] as List<dynamic>?;
        if (parts != null && parts.isNotEmpty) {
          return parts[0]['text'] as String? ?? '';
        }
      }
      return '';
    } else {
      throw Exception(
        'Gemini request failed with status ${response.statusCode}: ${response.body}',
      );
    }
  }

  /// Normalize unicode characters to ASCII equivalents
  String _normalizeText(String text) {
    return text
        // Replace em-dashes and en-dashes with regular hyphens
        .replaceAll('\u2014', '-') // em dash
        .replaceAll('\u2013', '-') // en dash
        .replaceAll('\u2012', '-') // figure dash
        // Replace curly quotes with straight quotes
        .replaceAll('\u2018', "'") // left single quote
        .replaceAll('\u2019', "'") // right single quote
        .replaceAll('\u201C', '"') // left double quote
        .replaceAll('\u201D', '"') // right double quote
        // Replace ellipsis
        .replaceAll('\u2026', '...') // ellipsis
        // Remove any other problematic unicode characters
        .replaceAll(RegExp(r'[^\x00-\x7F]+'), ''); // Remove non-ASCII
  }

  /// Filter a paragraph based on sensitivity levels
  Future<GeminiFilterResponse> filterParagraph({
    required String paragraph,
    required int profanityLevel,
    required int sexualContentLevel,
    required int violenceLevel,
  }) async {
    // If all levels are 5 (Unrated), skip filtering entirely
    if (profanityLevel == 5 && sexualContentLevel == 5 && violenceLevel == 5) {
      return GeminiFilterResponse(
        cleanedText: paragraph,
        originalText: paragraph,
        removedWords: [],
        detectedChanges: [],
        wasModified: false,
      );
    }

    // Normalize input text to ASCII
    final normalizedInput = _normalizeText(paragraph);

    final prompt = _buildFilteringPrompt(
      profanityLevel: profanityLevel,
      sexualContentLevel: sexualContentLevel,
      violenceLevel: violenceLevel,
    );

    final cleanedText = await filterText(text: normalizedInput, prompt: prompt);

    // Normalize output text as well to catch any issues
    final normalizedOutput = _normalizeText(cleanedText);

    return GeminiFilterResponse.fromTexts(
      original: paragraph,
      cleaned: normalizedOutput,
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

    // Language filtering instructions
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
          buffer.writeln('⚠️ TARGET: G RATING (Suitable for ages 5-10) ⚠️');
          buffer.writeln(
            'Ask: "Would a kindergarten teacher approve this language?"',
          );
          buffer.writeln('If NO → Remove it');
          buffer.writeln();
          buffer.writeln('G-rated language includes ONLY:');
          buffer.writeln(
            '- Neutral words: okay, fine, upset, angry, annoyed, silly',
          );
          buffer.writeln('- No insults, no name-calling, no crude words');
          buffer.writeln();
          buffer.writeln('PG or higher language (REMOVE):');
          buffer.writeln(
            '- Any insults: stupid, idiot, jerk, fool, dumb, moron',
          );
          buffer.writeln(
            '- Mild curses: darn, heck, gosh, oh my god, crap, damn',
          );
          buffer.writeln('- Body words: butt, fart, pee, poop');
          buffer.writeln('- All stronger profanity');
          break;
        case 2: // PG Rated
          buffer.writeln(
            '⚠️ TARGET: PG RATING (Suitable for ages 10+, family viewing) ⚠️',
          );
          buffer.writeln('Ask: "Would this be okay in a family movie?"');
          buffer.writeln('If NO → Remove it');
          buffer.writeln();
          buffer.writeln('PG-rated language includes:');
          buffer.writeln(
            '- Mild expressions: darn, gosh, heck, jeez, oh my god',
          );
          buffer.writeln('- Light insults that aren\'t crude');
          buffer.writeln();
          buffer.writeln('PG-13 or higher language (REMOVE):');
          buffer.writeln(
            '- Moderate profanity: damn, hell, ass, crap, bitch, bastard',
          );
          buffer.writeln('- F-words and stronger profanity');
          break;
        case 3: // PG-13 Rated
          buffer.writeln('⚠️ TARGET: PG-13 RATING (Suitable for teens 13+) ⚠️');
          buffer.writeln('Ask: "Would this be in a PG-13 movie?"');
          buffer.writeln('If it\'s R-rated or X-rated language → Remove it');
          buffer.writeln();
          buffer.writeln('PG-13 language includes:');
          buffer.writeln(
            '- damn, hell, ass, crap, bitch, bastard, son of a bitch',
          );
          buffer.writeln();
          buffer.writeln('R or X-rated language (REMOVE):');
          buffer.writeln(
            '- F-words: fuck, fucking, motherfucker (any variation)',
          );
          buffer.writeln('- Extreme slurs and graphic profanity');
          break;
        case 4: // R Rated
          buffer.writeln('⚠️ TARGET: R RATING (Adult content, 17+) ⚠️');
          buffer.writeln('Ask: "Would this be in an R-rated movie?"');
          buffer.writeln(
            'If it\'s X-rated (pornographic) language → Remove it',
          );
          buffer.writeln();
          buffer.writeln('R-rated language includes:');
          buffer.writeln(
            '- Most profanity including damn, hell, ass, bitch, bastard',
          );
          buffer.writeln();
          buffer.writeln('X-rated language (REMOVE):');
          buffer.writeln('- Excessive f-words (more than occasional)');
          buffer.writeln('- Pornographic or extremely graphic language');
          break;
      }
      buffer.writeln();
    }

    // Sexual content filtering instructions
    if (sexualContentLevel < 5) {
      buffer.writeln(
        'SEXUAL CONTENT FILTERING (Target Rating: ${_getRatingName(sexualContentLevel)}):',
      );
      buffer.writeln();
      buffer.writeln('🎯 YOUR TASK:');
      buffer.writeln('1. Read each sentence/phrase/scene in the text');
      buffer.writeln(
        '2. Ask yourself: \"What rating would this romantic/sexual content get?\" (G, PG, PG-13, R, or X)',
      );
      buffer.writeln(
        '3. If the rating is HIGHER than ${_getRatingName(sexualContentLevel)}, remove or replace that content',
      );
      buffer.writeln(
        '4. If the rating matches or is lower than ${_getRatingName(sexualContentLevel)}, keep it',
      );
      buffer.writeln();
      switch (sexualContentLevel) {
        case 1: // G Rated
          buffer.writeln('⚠️ TARGET: G RATING (Suitable for ages 5-10) ⚠️');
          buffer.writeln(
            'Ask: "Would this be in a children book like Harry Potter?"',
          );
          buffer.writeln('If NO -> Remove it');
          buffer.writeln();
          buffer.writeln('G-rated content includes ONLY:');
          buffer.writeln(
            '- "They were friends", "they were married", "they worked together"',
          );
          buffer.writeln('- Basic family affection (parent hugs child)');
          buffer.writeln(
            '- NO romance, NO attraction, NO physical intimacy at all',
          );
          buffer.writeln();
          buffer.writeln('PG or higher romantic/sexual content (REMOVE ALL):');
          buffer.writeln('- ANY kissing, hugging romantically, hand-holding');
          buffer.writeln('- ANY dating, crushes, flirting, attraction');
          buffer.writeln(
            '- ANY physical descriptions with romantic intent (beautiful, attractive, sexy)',
          );
          buffer.writeln('- ANY touching (caressing, stroking, embracing)');
          buffer.writeln('- ANY bedroom scenes, undressing, sleeping together');
          buffer.writeln(
            '- ANY words like: moaned, gasped, desire, passion, intimate',
          );
          buffer.writeln(
            '- ANY dialogue requesting touch: "touch me", "hold me", "I want you"',
          );
          buffer.writeln(
            '- ANY innuendos or suggestive language (double meanings, winking, suggestive smiles)',
          );
          buffer.writeln(
            '- If entire paragraph is romantic -> REMOVE or replace with "their relationship continued"',
          );
          buffer.writeln();
          buffer.writeln(
            'CRITICAL: This is a CHILDREN\'S rating. Err on the side of removal.',
          );
          buffer.writeln(
            'If you\'re unsure whether something is appropriate -> REMOVE IT',
          );
          buffer.writeln();
          buffer.writeln(
            'CRITICAL BIAS: For G-rated content, you MUST have a strong bias for removing any and all sexual or romantic content, even if it spoils the narrative. Your primary goal is to protect, not to preserve the story.',
          );
          buffer.writeln(
            'If a setting is inherently not G-rated (e.g., a bar, a nightclub, a strip club), you should remove the entire scene or replace it with a generic, G-rated equivalent like "they met at a cafe" or "they went to a restaurant".',
          );
          break;
        case 2: // PG Rated
          buffer.writeln(
            '⚠️ TARGET: PG RATING (Suitable for ages 10+, family viewing) ⚠️',
          );
          buffer.writeln(
            'Ask: "Would this be in a family movie or young adult book?"',
          );
          buffer.writeln('If NO -> Remove it');
          buffer.writeln();
          buffer.writeln('PG-rated content includes:');
          buffer.writeln(
            '- "They fell in love", "they held hands", "he kissed her briefly"',
          );
          buffer.writeln('- Light romantic scenes without sensuality');
          buffer.writeln();
          buffer.writeln('PG-13 or higher content (REMOVE):');
          buffer.writeln(
            '- Passionate kissing with detail, sensual descriptions',
          );
          buffer.writeln(
            '- Sexual tension, innuendo, suggestive language, double meanings',
          );
          buffer.writeln(
            '- Body descriptions (curves, attractive body, physique)',
          );
          buffer.writeln('- Intimate touching, caressing, bedroom scenes');
          buffer.writeln('- Desire, arousal, sexual thoughts or fantasies');
          buffer.writeln(
            '- Suggestive clothing descriptions, provocative appearance',
          );
          buffer.writeln('- ANY dialogue with sexual subtext or flirtation');
          buffer.writeln();
          buffer.writeln(
            'CRITICAL: This is FAMILY VIEWING rating. Err on the side of removal.',
          );
          buffer.writeln(
            'If you\'re unsure whether something is too suggestive -> REMOVE IT',
          );
          buffer.writeln(
            'Think: "Would I let my 10-year-old child read this?" If NO -> REMOVE',
          );
          buffer.writeln();
          buffer.writeln(
            'CRITICAL BIAS: For PG-rated content, you must have a bias for removing suggestive content, even if it slightly impacts the narrative. If a scene is borderline PG-13, you should remove the suggestive elements to make it clearly PG.',
          );
          buffer.writeln(
            'If a setting is inherently sexualized (e.g., a strip club), you must remove the scene entirely or heavily sanitize it to focus only on non-sexual plot points. Do not describe the setting.',
          );
          break;
        case 3: // PG-13 Rated
          buffer.writeln('⚠️ TARGET: PG-13 RATING (Suitable for teens 13+) ⚠️');
          buffer.writeln('Ask: "Would this be in a teen movie or YA novel?"');
          buffer.writeln('If it is R-rated or X-rated -> Remove it');
          buffer.writeln();
          buffer.writeln('PG-13 content includes:');
          buffer.writeln(
            '- Passionate kissing, romantic chemistry, mild innuendo',
          );
          buffer.writeln('- "They spent the night together" (fade-to-black)');
          buffer.writeln('- Vague physical attraction');
          buffer.writeln();
          buffer.writeln('R or X-rated content (REMOVE):');
          buffer.writeln('- Explicit sex scenes, graphic sexual acts');
          buffer.writeln('- Anatomical details, references to sexual organs');
          buffer.writeln('- Detailed undressing, explicit bedroom scenes');
          buffer.writeln('- Descriptions of arousal in graphic terms');
          break;
        case 4: // R Rated
          buffer.writeln('⚠️ TARGET: R RATING (Adult content, 17+) ⚠️');
          buffer.writeln(
            'Ask: "Would this be in an R-rated movie or adult novel?"',
          );
          buffer.writeln('If it is X-rated (pornographic) -> Remove it');
          buffer.writeln();
          buffer.writeln('R-rated content includes:');
          buffer.writeln('- "They made love", intimate scenes with sensuality');
          buffer.writeln('- References to sex, romantic body descriptions');
          buffer.writeln();
          buffer.writeln('X-rated content (REMOVE):');
          buffer.writeln(
            '- Pornographic descriptions, extremely graphic sexual acts',
          );
          buffer.writeln('- Clinical sexual details, explicit positions');
          buffer.writeln('- Excessive graphic sexual content');
          break;
      }
      buffer.writeln();
    }

    // Violence filtering instructions
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
        case 1: // G Rated
          buffer.writeln('⚠️ TARGET: G RATING (Suitable for ages 5-10) ⚠️');
          buffer.writeln(
            'Ask: "Would this be in a children book like Harry Potter?"',
          );
          buffer.writeln('If NO -> Remove it');
          buffer.writeln();
          buffer.writeln('G-rated content includes ONLY:');
          buffer.writeln(
            '- "There was a disagreement", "they argued", "there was tension"',
          );
          buffer.writeln('- NO violence, NO weapons, NO injuries at all');
          buffer.writeln();
          buffer.writeln('PG or higher violence (REMOVE ALL):');
          buffer.writeln(
            '- ANY hitting, punching, kicking, slapping, fighting',
          );
          buffer.writeln('- ANY weapons (guns, knives, swords)');
          buffer.writeln('- ANY blood, injuries, wounds, pain');
          buffer.writeln('- ANY death, killing, threats');
          buffer.writeln(
            '- If entire paragraph is violent -> REMOVE or replace with "there was conflict"',
          );
          break;
        case 2: // PG Rated
          buffer.writeln(
            '⚠️ TARGET: PG RATING (Suitable for ages 10+, family viewing) ⚠️',
          );
          buffer.writeln('Ask: "Would this be in a family action movie?"');
          buffer.writeln('If NO -> Remove it');
          buffer.writeln();
          buffer.writeln('PG-rated content includes:');
          buffer.writeln('- "They fought", "he was hurt", mild tension');
          buffer.writeln('- Light action without graphic detail');
          buffer.writeln();
          buffer.writeln('PG-13 or higher violence (REMOVE):');
          buffer.writeln('- Blood, detailed injuries, graphic fights');
          buffer.writeln('- Stabbings, shootings with detail');
          buffer.writeln('- Severe pain descriptions, torture');
          break;
        case 3: // PG-13 Rated
          buffer.writeln('⚠️ TARGET: PG-13 RATING (Suitable for teens 13+) ⚠️');
          buffer.writeln('Ask: "Would this be in a teen action movie?"');
          buffer.writeln('If it is R-rated or X-rated -> Remove it');
          buffer.writeln();
          buffer.writeln('PG-13 content includes:');
          buffer.writeln('- Action violence, fights, injuries');
          buffer.writeln('- Some blood, weapons use');
          buffer.writeln();
          buffer.writeln('R or X-rated violence (REMOVE):');
          buffer.writeln('- Extremely graphic violence, gore');
          buffer.writeln('- Detailed torture, mutilation');
          buffer.writeln('- Excessive blood and brutal deaths');
          break;
        case 4: // R Rated
          buffer.writeln('⚠️ TARGET: R RATING (Adult content, 17+) ⚠️');
          buffer.writeln('Ask: "Would this be in an R-rated action movie?"');
          buffer.writeln('If it is X-rated (extreme horror/gore) -> Remove it');
          buffer.writeln();
          buffer.writeln('R-rated content includes:');
          buffer.writeln('- Intense violence, graphic injuries');
          buffer.writeln('- Blood, brutal fights, realistic combat');
          buffer.writeln();
          buffer.writeln('X-rated content (REMOVE):');
          buffer.writeln('- Extreme torture porn, sadistic violence');
          buffer.writeln('- Excessive gore for shock value');
          break;
      }
      buffer.writeln();
    }

    buffer.writeln(
      'Now, filter the following text according to these rules. Return ONLY the cleaned text:',
    );

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
  Future<ChapterRatingResponse> rateChapter({required String text}) async {
    final prompt =
        '''Analyze the following text and rate it for content in three categories.
For each category, respond with ONLY one of: G, PG, PG-13, R, or X

Categories:
1. LANGUAGE (profanity, cursing)
   - G: No profanity
   - PG: Mild words like "damn", "hell"
   - PG-13: More frequent mild profanity
   - R: Strong profanity (f-word, etc)
   - X: Extreme profanity

2. SEXUAL CONTENT (romantic, sexual, suggestive)
   - G: No romantic/sexual content
   - PG: Innocent kissing, hand-holding
   - PG-13: Passionate kissing, emotional intimacy, suggestive scenes
   - R: Explicit descriptions of sexual acts
   - X: Graphic pornographic content

3. VIOLENCE (fighting, gore, harm)
   - G: No violence
   - PG: Mild action, slapstick
   - PG-13: Combat, injuries, some blood
   - R: Graphic violence, gore
   - X: Extreme graphic violence

Respond in exactly this format (one rating per line):
LANGUAGE: [G/PG/PG-13/R/X]
SEXUAL: [G/PG/PG-13/R/X]
VIOLENCE: [G/PG/PG-13/R/X]
SUMMARY: [Brief 1-2 sentence summary of the most restrictive content]

Text to analyze:''';

    try {
      final result = await filterText(text: text, prompt: prompt);

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
