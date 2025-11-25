import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'services/epub_parser.dart';

void main() {
  runApp(const BookWashApp());
}

class BookWashApp extends StatelessWidget {
  const BookWashApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BookWash',
      theme: ThemeData.dark(useMaterial3: true),
      themeMode: ThemeMode.dark,
      home: const BookWashHome(),
    );
  }
}

class BookWashHome extends StatefulWidget {
  const BookWashHome({super.key});

  @override
  State<BookWashHome> createState() => _BookWashHomeState();
}

class _BookWashHomeState extends State<BookWashHome> {
  String? selectedFilePath;
  String? selectedFileName;
  ParsedEpub? parsedEpub;
  bool isLoadingFile = false;
  int profanityLevel = 1;
  int sexualContentLevel = 1;
  int violenceLevel = 1;
  bool isProcessing = false;
  double progress = 0.0;
  bool showDetails = false;

  // Removal summaries by level
  Map<String, Map<int, int>> removalCounts = {
    'profanity': {1: 0, 2: 0, 3: 0, 4: 0},
    'sexual': {1: 0, 2: 0, 3: 0, 4: 0},
    'violence': {1: 0, 2: 0, 3: 0, 4: 0},
  };

  List<String> removalDetails = [];

  Future<void> selectFile() async {
    print('DEBUG: Opening file picker...');

    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['epub'],
      withData: true, // Important for web - loads bytes
    );

    print('DEBUG: File picker result: ${result != null ? "Got result" : "null"}');

    if (result == null) {
      print('DEBUG: Result was null, user probably cancelled');
      return;
    }

    print('DEBUG: Files in result: ${result.files.length}');

    if (result.files.isEmpty) {
      print('DEBUG: No files in result');
      return;
    }

    final file = result.files.single;

    print('DEBUG: Selected file - Name: ${file.name}');
    print('DEBUG: Platform - path: ${file.path}, bytes: ${file.bytes?.length}');

    // On web, path is null and we need to use bytes
    // On desktop, path is available
    if (file.path == null && file.bytes == null) {
      print('ERROR: No file path or bytes available!');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Could not access file. Please use desktop app for full functionality.'),
            backgroundColor: Colors.orange,
          ),
        );
      }
      return;
    }

    setState(() {
      selectedFilePath = file.path ?? file.name;
      selectedFileName = file.name;
      isLoadingFile = true;
      parsedEpub = null;
    });

    try {
      // On desktop, use file path. On web, we'd need to modify the parser
      // to accept bytes, but for now, show an error on web
      if (file.path == null) {
        throw Exception('Web platform not yet supported. Please run the desktop app.');
      }

      print('DEBUG: Starting EPUB parse for: ${file.path}');

      // Parse the EPUB file
      final epub = await EpubParser.parseEpub(file.path!);

      print(
        'DEBUG: EPUB parsed successfully - ${epub.metadata.title} by ${epub.metadata.author}',
      );
      print('DEBUG: ${epub.chapters.length} chapters, ${epub.totalParagraphs} paragraphs');

      setState(() {
        parsedEpub = epub;
        isLoadingFile = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Loaded: ${epub.metadata.title} - ${epub.chapters.length} chapters, ${epub.totalParagraphs} paragraphs',
            ),
            duration: const Duration(seconds: 3),
          ),
        );
      }
    } catch (e, stackTrace) {
      print('ERROR: Failed to parse EPUB - $e');
      print('STACKTRACE: $stackTrace');

      setState(() {
        isLoadingFile = false;
        selectedFilePath = null;
        selectedFileName = null;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error loading EPUB: $e'),
            duration: const Duration(seconds: 5),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> processBook() async {
    if (parsedEpub == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select an EPUB file first')),
      );
      return;
    }

    setState(() {
      isProcessing = true;
      progress = 0.0;
      removalCounts = {
        'profanity': {1: 0, 2: 0, 3: 0, 4: 0},
        'sexual': {1: 0, 2: 0, 3: 0, 4: 0},
        'violence': {1: 0, 2: 0, 3: 0, 4: 0},
      };
      removalDetails = [];
    });

    try {
      // Simulate processing with progress updates
      for (int i = 0; i <= 100; i += 5) {
        await Future.delayed(const Duration(milliseconds: 200));
        setState(() {
          progress = i / 100.0;
          // Simulate random removals being detected
          if (i % 10 == 0) {
            final level = (i ~/ 10) % 4 + 1;
            removalCounts['profanity']![level] =
                removalCounts['profanity']![level]! + 1;
            removalDetails.add(
              'Removed profanity level $level word at paragraph ${i ~/ 5}',
            );
          }
        });
      }

      setState(() {
        isProcessing = false;
        progress = 1.0;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Book cleaned successfully: ${selectedFileName}_cleaned.epub',
            ),
            duration: const Duration(seconds: 4),
          ),
        );
      }
    } catch (e) {
      setState(() {
        isProcessing = false;
      });
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Error processing book: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BookWash - EPUB Content Cleaner'),
        centerTitle: true,
        elevation: 0,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // File Selection Section
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Step 1: Select EPUB File',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 12),
                    if (isLoadingFile)
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.blue.withOpacity(0.1),
                          border: Border.all(color: Colors.blue),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Row(
                          children: [
                            SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                            SizedBox(width: 12),
                            Text('Loading EPUB...'),
                          ],
                        ),
                      )
                    else if (selectedFileName != null && parsedEpub != null)
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.green.withOpacity(0.1),
                          border: Border.all(color: Colors.green),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const Icon(Icons.check_circle, color: Colors.green),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    selectedFileName!,
                                    style: const TextStyle(color: Colors.green),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${parsedEpub!.chapters.length} chapters, ${parsedEpub!.totalParagraphs} paragraphs',
                              style: TextStyle(
                                fontSize: 12,
                                color: Colors.green[300],
                              ),
                            ),
                          ],
                        ),
                      )
                    else
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.grey.withOpacity(0.1),
                          border: Border.all(color: Colors.grey),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          'No file selected',
                          style: TextStyle(color: Colors.grey),
                        ),
                      ),
                    const SizedBox(height: 12),
                    ElevatedButton.icon(
                      onPressed: (isProcessing || isLoadingFile) ? null : selectFile,
                      icon: isLoadingFile
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.folder_open),
                      label: Text(isLoadingFile ? 'Loading...' : 'Browse EPUB Files'),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Sensitivity Sliders Section
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Step 2: Set Sensitivity Levels',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Profanity Sensitivity',
                      profanityLevel,
                      (value) => setState(() => profanityLevel = value.toInt()),
                      [
                        '1 - Strict (Remove all)',
                        '2 - Moderate (Keep mild)',
                        '3 - Permissive (Strong only)',
                        '4 - Minimal (F-words only)',
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Sexual Content Sensitivity',
                      sexualContentLevel,
                      (value) =>
                          setState(() => sexualContentLevel = value.toInt()),
                      [
                        '1 - Strict (None)',
                        '2 - Moderate (Light)',
                        '3 - Suggestive (Some detail)',
                        '4 - Graphic (Full detail)',
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Violence Sensitivity',
                      violenceLevel,
                      (value) => setState(() => violenceLevel = value.toInt()),
                      [
                        '1 - Strict (Minimal)',
                        '2 - Moderate (Some injury)',
                        '3 - Suggestive (Severe)',
                        '4 - Minimal (Graphic gore)',
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Process Button
            ElevatedButton.icon(
              onPressed: (parsedEpub == null || isProcessing || isLoadingFile)
                  ? null
                  : processBook,
              icon: isProcessing
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.cleaning_services),
              label: Text(isProcessing ? 'Processing...' : 'Clean Book'),
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
              ),
            ),
            const SizedBox(height: 20),

            // Progress Section
            if (isProcessing || progress > 0)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Step 3: Processing',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 12),
                      LinearProgressIndicator(value: progress, minHeight: 8),
                      const SizedBox(height: 8),
                      Text(
                        '${(progress * 100).toStringAsFixed(0)}% Complete',
                        style: const TextStyle(
                          fontSize: 14,
                          color: Colors.grey,
                        ),
                      ),
                      const SizedBox(height: 16),
                      _buildRemovalSummary(),
                    ],
                  ),
                ),
              ),

            // Reveal Details Button
            if (!isProcessing && removalDetails.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: TextButton.icon(
                  onPressed: () => setState(() => showDetails = !showDetails),
                  icon: Icon(
                    showDetails ? Icons.expand_less : Icons.expand_more,
                  ),
                  label: Text(showDetails ? 'Hide Details' : 'Show Details'),
                ),
              ),

            // Details Section
            if (showDetails && removalDetails.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Detailed Removal Log',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Container(
                          constraints: const BoxConstraints(maxHeight: 300),
                          child: ListView.builder(
                            shrinkWrap: true,
                            itemCount: removalDetails.length,
                            itemBuilder: (context, index) {
                              return Padding(
                                padding: const EdgeInsets.symmetric(
                                  vertical: 4,
                                ),
                                child: Text(
                                  '• ${removalDetails[index]}',
                                  style: const TextStyle(fontSize: 12),
                                ),
                              );
                            },
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildSliderSection(
    String title,
    int currentValue,
    Function(double) onChanged,
    List<String> labels,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
        ),
        const SizedBox(height: 8),
        Slider(
          value: currentValue.toDouble(),
          min: 1,
          max: 4,
          divisions: 3,
          label: currentValue.toString(),
          onChanged: onChanged,
        ),
        Text(
          labels[currentValue - 1],
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey[600],
            fontStyle: FontStyle.italic,
          ),
        ),
      ],
    );
  }

  Widget _buildRemovalSummary() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Removals by Level:',
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500),
        ),
        const SizedBox(height: 8),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Expanded(
              child: _buildRemovalCard(
                'Profanity',
                removalCounts['profanity']!,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _buildRemovalCard(
                'Sexual Content',
                removalCounts['sexual']!,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _buildRemovalCard('Violence', removalCounts['violence']!),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildRemovalCard(String title, Map<int, int> counts) {
    int total = counts.values.fold(0, (a, b) => a + b);
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.withOpacity(0.3)),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w500),
          ),
          const SizedBox(height: 4),
          Text(
            'Total: $total',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 4),
          ...counts.entries.map(
            (e) => Text(
              'L${e.key}: ${e.value}',
              style: const TextStyle(fontSize: 10),
            ),
          ),
        ],
      ),
    );
  }
}
