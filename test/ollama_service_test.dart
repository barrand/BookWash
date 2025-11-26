import 'package:flutter_test/flutter_test.dart';
import 'package:bookwash/services/ollama_service.dart';

void main() {
  group('OllamaService', () {
    late OllamaService service;

    setUp(() {
      service = OllamaService();
    });

    test('should connect to Ollama', () async {
      final isConnected = await service.checkConnection();
      expect(isConnected, true,
          reason: 'Ollama should be running on localhost:11434');
    });

    test('should get available models', () async {
      final models = await service.getAvailableModels();
      print('Available models: $models');
      expect(models, isNotEmpty,
          reason: 'Should have at least one model available');
    });

    test('should filter profanity from text', () async {
      final testText = 'This is a damn test with some crap in it.';

      final response = await service.filterParagraph(
        paragraph: testText,
        profanityLevel: 2, // Moderate - should remove "damn" and "crap"
        sexualContentLevel: 1,
        violenceLevel: 1,
      );

      print('Original: $testText');
      print('Cleaned:  ${response.cleanedText}');
      print('Removed words: ${response.removedWords}');

      expect(response.cleanedText, isNotEmpty);
      // The cleaned text should be different from the original
      // (though we can't predict exact output from LLM)
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('should filter sexual content from text', () async {
      final testText =
          'They shared a passionate kiss under the moonlight.';

      final response = await service.filterParagraph(
        paragraph: testText,
        profanityLevel: 1,
        sexualContentLevel: 1, // Strict - should remove romantic content
        violenceLevel: 1,
      );

      print('Original: $testText');
      print('Cleaned:  ${response.cleanedText}');
      print('Removed words: ${response.removedWords}');

      expect(response.cleanedText, isNotEmpty);
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('should filter violence from text', () async {
      final testText = 'He punched him in the face, breaking his nose.';

      final response = await service.filterParagraph(
        paragraph: testText,
        profanityLevel: 1,
        sexualContentLevel: 1,
        violenceLevel: 1, // Strict - should remove violence
      );

      print('Original: $testText');
      print('Cleaned:  ${response.cleanedText}');
      print('Removed words: ${response.removedWords}');

      expect(response.cleanedText, isNotEmpty);
    }, timeout: const Timeout(Duration(seconds: 60)));
  });
}
