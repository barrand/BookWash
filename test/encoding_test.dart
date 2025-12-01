import 'package:flutter_test/flutter_test.dart';
import 'package:html/parser.dart' as html_parser;
import 'package:html/dom.dart' as dom;

void main() {
  test('HTML generation should preserve UTF-8 characters', () {
    const originalHtml = """<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
	<title>The Black Prism</title>
	<meta content="http://www.w3.org/1999/xhtml; charset=utf-8" http-equiv="Content-Type"/><link href="stylesheet.css" type="text/css" rel="stylesheet"/><style type="text/css">
		@page { margin-bottom: 5.000000pt; margin-top: 5.000000pt; }
  </style></head>
  <body class="calibre">
<h1 id="filepos14881" class="calibre9"><span class="calibre10"><a class="calibre3"></a><a href=".html_split_002#filepos3474" class="calibre11">Chapter 1</a></span></h1><div class="calibre21"></div>
<p class="calibre14"><span class="calibre2">Kip crawled toward the battlefield in the darkness, the mist pressing down, blotting out sound, scattering starlight. Though the adults shunned it and the children were forbidden to come here, he’d played on the open field a hundred times—during the day. Tonight, his purpose was grimmer. </span></p>
<p class="calibre18"><span class="calibre2">Reaching the top of the hill, Kip stood and hiked up his pants. The river behind him was hissing, or maybe that was the warriors beneath its surface, dead these sixteen years. He squared his shoulders, ignoring his imagination. The mists made him seem suspended, outside of time. But even if there was no evidence of it, the sun was coming. By the time it did, he had to get to the far side of the battlefield. Farther than he’d ever gone searching. </span></p>
<p class="calibre18"><span class="calibre2">Even Ramir wouldn’t come out here at night. Everyone knew Sundered Rock was haunted. But Ram didn’t have to feed his family; <em class="calibre8">his</em> mother didn’t smoke her wages. </span></p>
<p class="calibre18"><span class="calibre2">Gripping his little belt knife tightly, Kip started walking. It wasn’t just the unquiet dead that might pull him down to the evernight. A pack of giant javelinas had been seen roaming the night, tusks cruel, hooves sharp. They were good eating if you had a matchlock, iron nerves, and good aim, but since the Prisms’ War had wiped out all the town’s men, there weren’t many people who braved death for a little bacon. Rekton was already a shell of what it had once been. The <a class="calibre3"></a><em class="calibre8">alcaldesa</em> wasn’t eager for any of her townspeople to throw their lives away. Besides, Kip didn’t have a matchlock. </span></p>
<p class="calibre18"><span class="calibre2">Nor were javelinas the only creatures that roamed the night. A mountain lion or a golden bear would also probably enjoy a well-marbled Kip. </span></p>
<p class="calibre18"><span class="calibre2">“What’s your name?” the color wight asked.</span></p>
</body></html>""";

    // 1. Parse the original HTML and extract paragraphs
    final originalDoc = html_parser.parse(originalHtml);
    final paragraphs = originalDoc
        .querySelectorAll('p')
        .map((p) => p.text)
        .toList();

    // This simulates the "cleaning" process. We'll use the extracted text directly.
    final cleanedParagraphs = paragraphs;

    // 2. Re-generate the chapter HTML using the logic from EpubWriter
    final newHtml = _generateChapterHtml(
      'Test Chapter',
      cleanedParagraphs,
      originalHtml,
    );

    // 3. Assertions
    // Check that the problematic character sequence is NOT present.
    expect(
      newHtml.contains('â'),
      isFalse,
      reason: "Output contains garbled UTF-8 characters.",
    );
    expect(
      newHtml.contains('â'),
      isFalse,
      reason: "Output contains garbled UTF-8 characters.",
    );
    expect(
      newHtml.contains('â'),
      isFalse,
      reason: "Output contains garbled UTF-8 characters.",
    );

    // Check that the correct characters (or their entities) ARE present.
    // The parser in _generateChapterHtml should handle this correctly.
    expect(newHtml.contains('he’d') || newHtml.contains('he&apos;d'), isTrue);
    expect(
      newHtml.contains('“What’s your name?”') ||
          newHtml.contains('&quot;What&apos;s your name?&quot;'),
      isTrue,
    );

    print('--- Generated HTML ---');
    print(newHtml);
    print('----------------------');
  });
}

/// This is a copy of the logic from EpubWriter._generateChapterHtml for isolated testing.
String _generateChapterHtml(
  String title,
  List<String> paragraphs,
  String originalHtml,
) {
  try {
    final document = html_parser.parse(originalHtml);
    final body = document.body;

    if (body != null) {
      // Clear existing body content
      body.innerHtml = '';

      // Add cleaned paragraphs
      for (final p in paragraphs) {
        final pElement = dom.Element.tag('p');
        pElement.text = p; // The parser should handle escaping
        body.append(pElement);
      }
    }
    // By default, the html package serializes to UTF-8, which is what we want.
    return document.outerHtml;
  } catch (e) {
    print('HTML parsing failed during test. Error: $e');
    return '';
  }
}
