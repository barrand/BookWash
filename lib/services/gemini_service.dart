import 'dart:convert';
import 'package:http/http.dart' as http;

/// Response from Gemini containing cleaned text and metadata
class GeminiFilterResponse {
  final String cleanedText;
  final String originalText;
  final List<String> removedWords;
  final bool wasModified;

  GeminiFilterResponse({
    required this.cleanedText,
    required this.originalText,
    required this.removedWords,
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

    return GeminiFilterResponse(
      cleanedText: cleaned,
      originalText: original,
      removedWords: removedWords,
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
    buffer.writeln(
      '3. CRITICAL PARAGRAPH STRUCTURE: Keep ALL paragraph breaks EXACTLY as they appear - use double line breaks (\\n\\n) between paragraphs',
    );
    buffer.writeln(
      '4. DO NOT merge paragraphs together - maintain the same number of paragraphs as the input',
    );
    buffer.writeln(
      '5. Keep ALL punctuation, formatting, quotation marks, and text structure EXACTLY as they appear',
    );
    buffer.writeln(
      '6. CRITICAL CHARACTER ENCODING: Use ONLY basic ASCII characters (a-z, A-Z, 0-9, and standard punctuation like -.,;:!?\'")',
    );
    buffer.writeln(
      '7. NEVER use unicode dashes, quotes, or special characters. Use regular hyphens (-), regular apostrophes, and regular quotes',
    );
    buffer.writeln(
      '8. If you see characters like em-dashes or curly quotes in the original, keep them. Only avoid adding NEW unicode characters',
    );
    buffer.writeln(
      '9. When removing content, use MINIMAL replacements - prefer simple phrases over creative elaboration',
    );
    buffer.writeln(
      '10. DO NOT add new plot elements, details, or story content that was not in the original text',
    );
    buffer.writeln(
      '11. DO NOT hallucinate or invent replacement content - keep it simple and vague',
    );
    buffer.writeln(
      '12. Preserve the emotional tone and narrative voice - if a character is angry, keep them angry (just without prohibited words)',
    );
    buffer.writeln(
      '13. The cleaned text must read naturally and smoothly - no awkward gaps or jumps',
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
      buffer.writeln('LANGUAGE/PROFANITY FILTERING (Level $profanityLevel):');
      switch (profanityLevel) {
        case 1: // G Rated
          buffer.writeln(
            '- Remove ALL profanity, curse words, insults, and crude language',
          );
          buffer.writeln(
            '- Remove: jerk, fool, dope, stupid, idiot, dumb, crap, damn, hell, ass, bitch, f-words, ALL curse words',
          );
          buffer.writeln('- Replace with mild alternatives');
          buffer.writeln('- Result: suitable for all ages and young children');
          break;
        case 2: // PG Rated
          buffer.writeln('- Remove strong profanity and crude language');
          buffer.writeln(
            '- Remove: f-words, ass, asshole, bitch, bastard, and intense insults',
          );
          buffer.writeln(
            '- Keep ONLY: very mild expressions (darn, gosh, heck, jeez)',
          );
          buffer.writeln('- Result: family-friendly content');
          break;
        case 3: // PG-13 Rated
          buffer.writeln('- Remove f-words and extreme profanity');
          buffer.writeln(
            '- Remove: fuck, fucking, fucked, motherfucker, c-words, extreme slurs',
          );
          buffer.writeln(
            '- Keep: ass, asshole, bitch, damn, hell, crap, bastard, son of a bitch',
          );
          buffer.writeln('- Result: teenage-appropriate language');
          break;
        case 4: // R Rated
          buffer.writeln('- Remove ONLY f-word variations');
          buffer.writeln(
            '- Remove: fuck, fucking, fucked, motherfucker, and any f-word variations',
          );
          buffer.writeln(
            '- Keep: ALL other profanity including ass, asshole, bitch, damn, hell, crap, bastard',
          );
          buffer.writeln(
            '- Result: adult content with extreme profanity removed',
          );
          break;
      }
      buffer.writeln();
    }

    // Sexual content filtering instructions
    if (sexualContentLevel < 5) {
      buffer.writeln('SEXUAL CONTENT FILTERING (Level $sexualContentLevel):');
      switch (sexualContentLevel) {
        case 1: // G Rated
          buffer.writeln(
            '- Remove ALL romantic and sexual content beyond basic plot necessity',
          );
          buffer.writeln(
            '- Remove: kissing, romantic scenes, affection, attraction, physical intimacy of any kind',
          );
          buffer.writeln(
            '- Remove: ALL body descriptions with sexual or romantic context (breasts, curves, physical attraction, beauty)',
          );
          buffer.writeln(
            '- Remove: ANY touching beyond handshakes or brief hugs',
          );
          buffer.writeln(
            '- Remove: sleeping together, bedroom scenes, undressing, showering with romantic context',
          );
          buffer.writeln(
            '- Keep ONLY: factual relationships ("they were married", "they were together", "they were partners")',
          );
          buffer.writeln(
            '- Replace with MINIMAL text: "they connected", "they were close", "their relationship continued"',
          );
          buffer.writeln(
            '- DO NOT invent activities or details - keep replacements extremely simple and vague',
          );
          buffer.writeln(
            '- Result: suitable for young children - completely non-romantic',
          );
          break;
        case 2: // PG Rated
          buffer.writeln(
            '- Remove ALL suggestive content, sexual implications, sensuality, and detailed romantic scenes',
          );
          buffer.writeln(
            '- Remove: passionate kissing, sensual descriptions, sexual tension, innuendo, suggestive language',
          );
          buffer.writeln(
            '- Remove: ALL body descriptions with romantic/sexual context (attractive, beautiful body, curves, physique, etc.)',
          );
          buffer.writeln(
            '- Remove: ANY descriptions of touching beyond holding hands (no caressing, no intimate touching, no embracing with detail)',
          );
          buffer.writeln(
            '- Remove: bedroom scenes, undressing descriptions, showering together, sleeping together with detail',
          );
          buffer.writeln(
            '- Remove: arousal, desire, attraction beyond "they were attracted to each other"',
          );
          buffer.writeln(
            '- Remove: thoughts of intimacy, self-pleasure, sexual fantasies, imagining intimate acts',
          );
          buffer.writeln(
            '- Keep: "they fell in love", "they held hands", "he kissed her briefly", basic statements of affection',
          );
          buffer.writeln(
            '- Replace with SIMPLE phrases: "they grew closer", "they connected", "later that night"',
          );
          buffer.writeln(
            '- DO NOT invent new activities, conversations, or plot elements not in the original',
          );
          buffer.writeln(
            '- Result: family-friendly romance with no sensuality whatsoever',
          );
          break;
        case 3: // PG-13 Rated
          buffer.writeln(
            '- Remove explicit sexual content and graphic descriptions',
          );
          buffer.writeln(
            '- Remove: sex scenes, explicit anatomical details, graphic sexual acts, detailed intimate touching',
          );
          buffer.writeln(
            '- Remove: descriptions of arousal, explicit body descriptions, references to sexual organs',
          );
          buffer.writeln(
            '- Remove: detailed descriptions of undressing, explicit bedroom scenes, graphic physical intimacy',
          );
          buffer.writeln(
            '- Keep: passionate kissing, romantic chemistry, mild innuendo, "they spent the night together", vague physical attraction',
          );
          buffer.writeln(
            '- Replace with BRIEF fade-to-black: "they were together", "later that night", "afterward"',
          );
          buffer.writeln(
            '- DO NOT elaborate on what happened - keep it extremely vague',
          );
          buffer.writeln(
            '- Result: teenage-appropriate romantic content with clear but non-explicit intimacy',
          );
          break;
        case 4: // R Rated
          buffer.writeln(
            '- Remove only extremely graphic sexual descriptions and pornographic content',
          );
          buffer.writeln(
            '- Remove: explicit anatomical descriptions, graphic sex acts with extreme detail, pornographic language',
          );
          buffer.writeln(
            '- Remove: detailed descriptions of sexual acts in graphic terms, explicit positions, clinical sexual details',
          );
          buffer.writeln(
            '- Keep: "they made love", intimate scenes with sensuality, references to sex, romantic body descriptions',
          );
          buffer.writeln(
            '- Tone down extremely graphic sections with simple language - avoid clinical or pornographic detail',
          );
          buffer.writeln(
            '- DO NOT add flowery or elaborate descriptions - keep it straightforward',
          );
          buffer.writeln(
            '- Result: adult romantic/sexual content with only the most extreme pornographic elements removed',
          );
          break;
      }
      buffer.writeln();
    }

    // Violence filtering instructions
    if (violenceLevel < 5) {
      buffer.writeln('VIOLENCE FILTERING (Level $violenceLevel):');
      switch (violenceLevel) {
        case 1: // G Rated
          buffer.writeln(
            '- Remove ALL violence, physical conflict, weapons, injuries, and threats',
          );
          buffer.writeln(
            '- Remove: fighting, punching, weapons, blood, injuries, death scenes, threats',
          );
          buffer.writeln(
            '- Keep ONLY: abstract references ("there was a conflict", "they disagreed")',
          );
          buffer.writeln('- Result: suitable for young children');
          break;
        case 2: // PG Rated
          buffer.writeln(
            '- Remove graphic violence, detailed injuries, weapons usage, and serious threats',
          );
          buffer.writeln(
            '- Remove: blood, detailed fights, stabbings, shootings, severe injuries',
          );
          buffer.writeln(
            '- Keep: "they fought", "he was hurt", mild arguments, tension',
          );
          buffer.writeln('- Result: family-friendly conflict');
          break;
        case 3: // PG-13 Rated
          buffer.writeln(
            '- Remove extreme violence, torture, graphic injuries, and brutal combat',
          );
          buffer.writeln(
            '- Remove: torture scenes, dismemberment, graphic mutilation, execution-style deaths',
          );
          buffer.writeln(
            '- Keep: fight scenes, combat, "a black eye formed", self-defense, action sequences',
          );
          buffer.writeln('- Result: teenage-appropriate action content');
          break;
        case 4: // R Rated
          buffer.writeln(
            '- Remove only extreme gore and the most graphic descriptions',
          );
          buffer.writeln(
            '- Remove: "guts spilled", "flayed skin", extreme torture with graphic detail',
          );
          buffer.writeln(
            '- Keep: brutal fights, serious injuries, "badly beaten", combat with blood, violent deaths',
          );
          buffer.writeln('- Result: adult violence with extreme gore removed');
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
