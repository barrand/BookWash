import 'dart:convert';
import 'package:http/http.dart' as http;

/// Response from Ollama containing cleaned text and metadata
class OllamaFilterResponse {
  final String cleanedText;
  final String originalText;
  final List<String> removedWords; // List of specific words/phrases removed
  final bool wasModified;

  OllamaFilterResponse({
    required this.cleanedText,
    required this.originalText,
    required this.removedWords,
    required this.wasModified,
  });

  /// Analyze differences between original and cleaned text
  factory OllamaFilterResponse.fromTexts({
    required String original,
    required String cleaned,
  }) {
    final wasModified = original.trim() != cleaned.trim();
    final removedWords = wasModified
        ? _detectRemovedWords(original, cleaned)
        : <String>[];

    return OllamaFilterResponse(
      cleanedText: cleaned,
      originalText: original,
      removedWords: removedWords,
      wasModified: wasModified,
    );
  }

  /// Detect specific words/phrases that were removed
  static List<String> _detectRemovedWords(String original, String cleaned) {
    final removed = <String>[];

    // Simple word-level comparison
    final originalWords = original.toLowerCase().split(RegExp(r'\s+'));
    final cleanedWords = cleaned.toLowerCase().split(RegExp(r'\s+'));
    final cleanedSet = cleanedWords.toSet();

    // Common profanity/sexual/violent words to specifically check
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
      final cleanWord = word.replaceAll(
        RegExp(r'[^\w]'),
        '',
      ); // Remove punctuation
      if (keywords.contains(cleanWord) && !cleanedSet.contains(cleanWord)) {
        if (!removed.contains(cleanWord)) {
          removed.add(cleanWord);
        }
      }
    }

    return removed;
  }
}

/// Service for communicating with local Ollama LLM
class OllamaService {
  final String baseUrl;
  final String model;
  final Duration timeout;

  OllamaService({
    this.baseUrl = 'http://localhost:11434',
    this.model = 'qwen3:8b',
    this.timeout = const Duration(seconds: 60),
  });

  /// Check if Ollama is running and accessible
  Future<bool> checkConnection() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/api/tags'))
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
          .get(Uri.parse('$baseUrl/api/tags'))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final models = data['models'] as List<dynamic>?;
        if (models != null) {
          return models
              .map((m) => m['name'] as String? ?? '')
              .where((name) => name.isNotEmpty)
              .toList();
        }
      }
      return [];
    } catch (e) {
      return [];
    }
  }

  /// Send a filtering request to Ollama
  ///
  /// [text] - The paragraph or text chunk to filter
  /// [prompt] - The system prompt with filtering instructions
  Future<String> filterText({
    required String text,
    required String prompt,
  }) async {
    final requestBody = {
      'model': model,
      'prompt': '$prompt\n\nText to filter:\n$text',
      'stream': false,
      'options': {
        'temperature': 0.1, // Low temperature for consistent filtering
        'top_p': 0.9,
      },
    };

    final response = await http
        .post(
          Uri.parse('$baseUrl/api/generate'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(requestBody),
        )
        .timeout(timeout);

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['response'] as String? ?? '';
    } else {
      throw Exception(
        'Ollama request failed with status ${response.statusCode}: ${response.body}',
      );
    }
  }

  /// Filter a paragraph based on sensitivity levels
  ///
  /// Returns a response with cleaned text and removal details
  Future<OllamaFilterResponse> filterParagraph({
    required String paragraph,
    required int profanityLevel,
    required int sexualContentLevel,
    required int violenceLevel,
  }) async {
    // If all levels are 5 (Unrated), skip filtering entirely
    if (profanityLevel == 5 && sexualContentLevel == 5 && violenceLevel == 5) {
      return OllamaFilterResponse(
        cleanedText: paragraph,
        originalText: paragraph,
        removedWords: [],
        wasModified: false,
      );
    }

    final prompt = _buildFilteringPrompt(
      profanityLevel: profanityLevel,
      sexualContentLevel: sexualContentLevel,
      violenceLevel: violenceLevel,
    );

    final cleanedText = await filterText(text: paragraph, prompt: prompt);

    return OllamaFilterResponse.fromTexts(
      original: paragraph,
      cleaned: cleanedText,
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

    // Note which dimensions are unrated
    final unratedDimensions = <String>[];
    if (profanityLevel == 5) unratedDimensions.add('language/profanity');
    if (sexualContentLevel == 5) unratedDimensions.add('sexual content');
    if (violenceLevel == 5) unratedDimensions.add('violence');

    if (unratedDimensions.isNotEmpty) {
      buffer.writeln();
      buffer.writeln('⚠️ UNRATED DIMENSIONS - DO NOT FILTER:');
      buffer.writeln(
        'The following content types are UNRATED and must be kept EXACTLY as written:',
      );
      for (final dim in unratedDimensions) {
        buffer.writeln(
          '  - $dim: Keep ALL content unchanged, no matter how strong',
        );
      }
    }

    buffer.writeln();
    buffer.writeln('IMPORTANT RULES:');
    buffer.writeln('1. Preserve the narrative flow and story coherence');
    buffer.writeln(
      '2. Replace removed content with appropriate alternatives or ellipsis [...]',
    );
    buffer.writeln('3. Keep all formatting, punctuation, and structure intact');
    buffer.writeln('4. Only modify content that violates the specified levels');
    buffer.writeln(
      '5. Return ONLY the cleaned text, no explanations or metadata',
    );
    buffer.writeln();

    // Profanity filtering instructions
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
          buffer.writeln(
            '- Result should be suitable for all ages and young children',
          );
          break;
        case 2: // PG Rated
          buffer.writeln('- Remove strong profanity and crude language');
          buffer.writeln(
            '- Remove: f-words, ass, asshole, bitch, bastard, and more intense insults',
          );
          buffer.writeln(
            '- Keep ONLY: very mild expressions (darn, gosh, heck, jeez)',
          );
          buffer.writeln('- Result should be family-friendly');
          break;
        case 3: // PG-13 Rated
          buffer.writeln('- Remove f-words and extreme profanity');
          buffer.writeln(
            '- Remove: fuck, fucking, fucked, motherfucker, c-words, extreme slurs',
          );
          buffer.writeln(
            '- Keep: ass, asshole, bitch, damn, hell, crap, bastard, son of a bitch',
          );
          buffer.writeln('- Result should be teenage-appropriate');
          break;
        case 4: // R Rated
          buffer.writeln('- Remove ONLY f-word variations');
          buffer.writeln(
            '- Remove: fuck, fucking, fucked, motherfucker, and any f-word variations',
          );
          buffer.writeln(
            '- Keep: ALL other profanity including ass, asshole, bitch, damn, hell, crap, bastard, son of a bitch',
          );
          buffer.writeln(
            '- Result should be adult content with extreme profanity removed',
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
            '- Remove: kissing, romantic scenes, affection, attraction, relationships beyond friendship',
          );
          buffer.writeln(
            '- Keep ONLY: factual relationships ("they were married", "they were friends")',
          );
          buffer.writeln('- Result should be suitable for young children');
          break;
        case 2: // PG Rated
          buffer.writeln(
            '- Remove suggestive content, sexual implications, and detailed romantic scenes',
          );
          buffer.writeln(
            '- Remove: passionate kissing, sensual descriptions, sexual tension, innuendo',
          );
          buffer.writeln(
            '- Keep: "they fell in love", hand-holding, basic affection, chaste kissing',
          );
          buffer.writeln('- Result should be family-friendly romance');
          break;
        case 3: // PG-13 Rated
          buffer.writeln(
            '- Remove explicit sexual content and graphic descriptions',
          );
          buffer.writeln(
            '- Remove: sex scenes, explicit anatomical details, graphic sexual acts',
          );
          buffer.writeln(
            '- Keep: passionate kissing, romantic chemistry, innuendo, "they spent the night together"',
          );
          buffer.writeln(
            '- Result should be teenage-appropriate romantic content',
          );
          break;
        case 4: // R Rated
          buffer.writeln(
            '- Remove only extremely graphic sexual descriptions and pornographic content',
          );
          buffer.writeln(
            '- Remove: explicit anatomical descriptions, graphic sex acts with extreme detail',
          );
          buffer.writeln(
            '- Keep: "they made love", intimate scenes, sensual descriptions, most sexual content',
          );
          buffer.writeln(
            '- Result should be adult romantic/sexual content with extreme pornography removed',
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
          buffer.writeln('- Result should be suitable for young children');
          break;
        case 2: // PG Rated
          buffer.writeln(
            '- Remove graphic violence, detailed injuries, weapons usage, and serious threats',
          );
          buffer.writeln(
            '- Remove: blood, detailed fights, stabbings, shootings, severe injuries',
          );
          buffer.writeln(
            '- Keep: "they fought", "he was hurt", mild arguments, tension, accidental bumps',
          );
          buffer.writeln('- Result should be family-friendly conflict');
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
          buffer.writeln(
            '- Result should be teenage-appropriate action content',
          );
          break;
        case 4: // R Rated
          buffer.writeln(
            '- Remove only extreme gore and the most graphic descriptions',
          );
          buffer.writeln(
            '- Remove: "guts spilled across the floor", "flayed skin", extreme torture with graphic detail',
          );
          buffer.writeln(
            '- Keep: brutal fights, serious injuries, "badly beaten", combat with blood, violent deaths',
          );
          buffer.writeln(
            '- Result should be adult violence with extreme gore removed',
          );
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
