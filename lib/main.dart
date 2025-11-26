import 'dart:io';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'services/epub_parser.dart';
import 'services/epub_writer.dart';
import 'services/ollama_service.dart';
import 'services/gemini_service.dart';
import 'models/chunk_change.dart';
import 'widgets/change_review_dialog.dart';

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
  int profanityLevel = 3;
  int sexualContentLevel = 3;
  int violenceLevel = 3;
  bool isProcessing = false;
  bool isCancelling = false;
  double progress = 0.0;
  bool showDetails = false;

  // AI Provider selection
  String selectedProvider = 'gemini'; // 'ollama' or 'gemini'
  String geminiApiKey = ''; // User will need to provide this

  // Service instances
  late OllamaService ollamaService;
  GeminiService? geminiService;

  // Model selection
  List<String> availableModels = [];
  String selectedModel = 'gemini-2.0-flash-exp'; // Default Gemini model
  bool isLoadingModels = false;

  // Processing statistics
  int totalParagraphs = 0;
  int processedParagraphs = 0;
  int modifiedParagraphs = 0;

  // Removal summaries by level
  Map<String, Map<int, int>> removalCounts = {
    'profanity': {1: 0, 2: 0, 3: 0, 4: 0},
    'sexual': {1: 0, 2: 0, 3: 0, 4: 0},
    'violence': {1: 0, 2: 0, 3: 0, 4: 0},
  };

  List<String> removalDetails = [];

  // Real-time logging
  List<String> liveLogMessages = [];
  final _scrollController = ScrollController();

  // Cleaned book data
  List<String> cleanedParagraphs = [];
  Map<int, int> paragraphToChapter =
      {}; // original paragraph index -> chapter index
  Map<int, int> cleanedParagraphToChapter =
      {}; // cleaned paragraph index -> chapter index

  // Change review system
  List<ChunkChange> pendingChanges = [];
  int currentReviewIndex = 0;
  bool isReviewingChanges = false;

  @override
  void initState() {
    super.initState();
    ollamaService = OllamaService(model: selectedModel);
    _loadSavedApiKey();
    _loadAvailableModels();
  }

  Future<void> _loadSavedApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    final savedKey = prefs.getString('gemini_api_key') ?? '';
    if (savedKey.isNotEmpty) {
      setState(() {
        geminiApiKey = savedKey;
        geminiService = GeminiService(apiKey: geminiApiKey);
      });
    }
  }

  Future<void> _saveApiKey(String key) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('gemini_api_key', key);
  }

  Future<void> _loadAvailableModels() async {
    setState(() {
      isLoadingModels = true;
    });

    try {
      List<String> models;
      if (selectedProvider == 'ollama') {
        models = await ollamaService.getAvailableModels();
        if (models.isEmpty) {
          models = ['qwen3:8b', 'phi3:mini', 'qwen3-coder:30b'];
        }
      } else {
        // Gemini models - Only free tier models
        models = [
          'gemini-2.0-flash-exp', // Best free tier: 1500 RPD, 10 RPM
          'gemini-1.5-flash', // Good free tier: 1500 RPD, 15 RPM
        ];
      }

      setState(() {
        availableModels = models;
        isLoadingModels = false;
        // If current model not in list, use first available
        if (models.isNotEmpty && !models.contains(selectedModel)) {
          selectedModel = models.first;
          if (selectedProvider == 'ollama') {
            ollamaService = OllamaService(model: selectedModel);
          }
        }
      });
    } catch (e) {
      print('Failed to load models: $e');
      setState(() {
        isLoadingModels = false;
        // Fallback to default models if fetch fails
        if (selectedProvider == 'ollama') {
          availableModels = ['qwen3:8b', 'phi3:mini', 'qwen3-coder:30b'];
        } else {
          availableModels = ['gemini-2.0-flash-exp', 'gemini-1.5-flash'];
        }
      });
    }
  }

  void _onModelChanged(String? newModel) {
    if (newModel != null && newModel != selectedModel) {
      setState(() {
        selectedModel = newModel;
        if (selectedProvider == 'ollama') {
          ollamaService = OllamaService(model: selectedModel);
        } else if (geminiService != null) {
          geminiService = GeminiService(
            apiKey: geminiApiKey,
            model: selectedModel,
          );
        }
      });
    }
  }

  Future<void> _showGeminiApiKeyDialog() async {
    final controller = TextEditingController(text: geminiApiKey);
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Enter Gemini API Key'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Get your free API key from:'),
            const SizedBox(height: 8),
            const Text(
              'https://aistudio.google.com/apikey',
              style: TextStyle(color: Colors.blue, fontSize: 12),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: 'API Key',
                hintText: 'AIza...',
              ),
              obscureText: true,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );

    if (result != null && result.isNotEmpty) {
      await _saveApiKey(result); // Save to persistent storage
      setState(() {
        geminiApiKey = result;
        geminiService = GeminiService(apiKey: geminiApiKey);
        selectedModel = 'gemini-2.0-flash-exp';
      });
      await _loadAvailableModels();
    }
  }

  Future<void> selectFile() async {
    print('DEBUG: Opening file picker...');

    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['epub'],
      withData: true, // Important for web - loads bytes
    );

    print(
      'DEBUG: File picker result: ${result != null ? "Got result" : "null"}',
    );

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
            content: Text(
              'Could not access file. Please use desktop app for full functionality.',
            ),
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
        throw Exception(
          'Web platform not yet supported. Please run the desktop app.',
        );
      }

      print('DEBUG: Starting EPUB parse for: ${file.path}');

      // Parse the EPUB file
      final epub = await EpubParser.parseEpub(file.path!);

      print(
        'DEBUG: EPUB parsed successfully - ${epub.metadata.title} by ${epub.metadata.author}',
      );
      print(
        'DEBUG: ${epub.chapters.length} chapters, ${epub.totalParagraphs} paragraphs',
      );

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

  void cancelProcessing() {
    setState(() {
      isCancelling = true;
    });
  }

  Future<void> saveCleanedBook() async {
    if (cleanedParagraphs.isEmpty || parsedEpub == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('No cleaned book to save')));
      return;
    }

    try {
      // Let user choose save location
      final outputPath = await FilePicker.platform.saveFile(
        dialogTitle: 'Save Cleaned Book',
        fileName: '${parsedEpub!.metadata.title}_cleaned.epub',
        type: FileType.custom,
        allowedExtensions: ['epub'],
      );

      if (outputPath == null) {
        print('User cancelled save');
        return;
      }

      // Write EPUB file
      final epubWriter = EpubWriter();
      await epubWriter.writeEpub(
        outputPath: outputPath,
        originalEpub: parsedEpub!,
        cleanedParagraphs: cleanedParagraphs,
        paragraphToChapter:
            cleanedParagraphToChapter, // Use the cleaned mapping
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Book saved to: $outputPath'),
            duration: const Duration(seconds: 5),
          ),
        );
      }
    } catch (e) {
      print('Error saving book: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error saving book: $e'),
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

    // Check Ollama connection first
    final isConnected = await ollamaService.checkConnection();
    if (!isConnected) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Cannot connect to Ollama. Please ensure Ollama is running (ollama serve)',
            ),
            duration: Duration(seconds: 5),
            backgroundColor: Colors.red,
          ),
        );
      }
      return;
    }

    setState(() {
      isProcessing = true;
      isCancelling = false;
      progress = 0.0;
      totalParagraphs = 0;
      processedParagraphs = 0;
      modifiedParagraphs = 0;
      removalCounts = {
        'profanity': {1: 0, 2: 0, 3: 0, 4: 0},
        'sexual': {1: 0, 2: 0, 3: 0, 4: 0},
        'violence': {1: 0, 2: 0, 3: 0, 4: 0},
      };
      removalDetails = [];
      liveLogMessages = [];
      cleanedParagraphs = [];
      paragraphToChapter = {};
      cleanedParagraphToChapter = {};
      pendingChanges = [];
      currentReviewIndex = 0;
    });

    try {
      print(
        'Starting book processing with ${selectedProvider == 'gemini' ? 'Gemini' : 'Ollama'}...',
      );

      // Collect all paragraphs from all chapters
      final allParagraphs = <String>[];

      for (
        int chapterIdx = 0;
        chapterIdx < parsedEpub!.chapters.length;
        chapterIdx++
      ) {
        final chapter = parsedEpub!.chapters[chapterIdx];
        for (final paragraph in chapter.paragraphs) {
          paragraphToChapter[allParagraphs.length] = chapterIdx;
          allParagraphs.add(paragraph);
        }
      }

      setState(() {
        totalParagraphs = allParagraphs.length;
      });

      print('Total paragraphs to process: ${allParagraphs.length}');

      // Determine chunking strategy based on provider
      if (selectedProvider == 'gemini') {
        // Gemini: Process in large chunks (multiple chapters at once)
        await _processInLargeChunks(allParagraphs);
      } else {
        // Ollama: Process paragraph by paragraph (original behavior)
        await _processParagraphByParagraph(allParagraphs);
      }
      print('Finished processing - Cancelled: $isCancelling');

      // If there are pending changes, show review dialog
      if (pendingChanges.isNotEmpty && !isCancelling && mounted) {
        setState(() {
          isProcessing = false;
          isReviewingChanges = true;
        });

        // Show review dialog
        await showDialog(
          context: context,
          barrierDismissible: false,
          builder: (context) => ChangeReviewDialog(
            changes: pendingChanges,
            onComplete: _applyApprovedChanges,
          ),
        );

        return;
      }

      // Cleaned paragraphs are already stored in the cleanedParagraphs list
      setState(() {
        isProcessing = false;
        if (!isCancelling) {
          progress = 1.0;
        }
      });

      if (mounted) {
        final message = isCancelling
            ? 'Processing cancelled: $processedParagraphs/$totalParagraphs paragraphs processed, $modifiedParagraphs modified'
            : 'Book processed: $processedParagraphs paragraphs filtered, $modifiedParagraphs modified. Ready to save!';

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(message),
            duration: const Duration(seconds: 4),
            backgroundColor: isCancelling ? Colors.orange : null,
            behavior: SnackBarBehavior.floating,
            margin: EdgeInsets.only(
              bottom: MediaQuery.of(context).size.height - 100,
              left: 10,
              right: 10,
            ),
          ),
        );
      }
    } catch (e, stackTrace) {
      print('Error processing book: $e');
      print('Stack trace: $stackTrace');

      setState(() {
        isProcessing = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error processing book: $e'),
            duration: const Duration(seconds: 5),
            backgroundColor: Colors.red,
            behavior: SnackBarBehavior.floating,
            margin: EdgeInsets.only(
              bottom: MediaQuery.of(context).size.height - 100,
              left: 10,
              right: 10,
            ),
          ),
        );
      }
    }
  }

  // Process book in larger chunks for API (reduce API calls), then split for review
  Future<void> _processInLargeChunks(List<String> allParagraphs) async {
    const apiChunkSize =
        50; // Send 50 paragraphs per API call (reduces API calls by 10x)

    final apiChunks = <List<int>>[]; // API chunks - larger

    // Create larger chunks for API calls
    for (int i = 0; i < allParagraphs.length; i += apiChunkSize) {
      final end = (i + apiChunkSize).clamp(0, allParagraphs.length);
      apiChunks.add([i, end]);
    }

    print(
      'Processing ${apiChunks.length} API chunks (${allParagraphs.length} total paragraphs, $apiChunkSize paragraphs per API call)',
    );

    for (int apiChunkIdx = 0; apiChunkIdx < apiChunks.length; apiChunkIdx++) {
      if (isCancelling) break;

      final apiStart = apiChunks[apiChunkIdx][0];
      final apiEnd = apiChunks[apiChunkIdx][1];

      // Combine paragraphs into one large chunk for API
      final apiChunkText = allParagraphs.sublist(apiStart, apiEnd).join('\n\n');

      print(
        'Processing API chunk ${apiChunkIdx + 1}/${apiChunks.length} (paragraphs $apiStart-$apiEnd)...',
      );

      try {
        if (geminiService == null) {
          throw Exception('Gemini service not initialized.');
        }

        final response = await geminiService!.filterParagraph(
          paragraph: apiChunkText,
          profanityLevel: profanityLevel,
          sexualContentLevel: sexualContentLevel,
          violenceLevel: violenceLevel,
        );

        // Check paragraph count consistency
        final cleanedChunkParagraphs = response.cleanedText
            .split('\n\n')
            .where((p) => p.trim().isNotEmpty)
            .toList();
        final originalParagraphCount = apiEnd - apiStart;

        if (cleanedChunkParagraphs.length != originalParagraphCount) {
          final lossPercentage =
              (1 - (cleanedChunkParagraphs.length / originalParagraphCount)) *
              100;
          print(
            'WARNING: Paragraph count mismatch in API chunk $apiChunkIdx! Original: $originalParagraphCount, Cleaned: ${cleanedChunkParagraphs.length} (${lossPercentage.toStringAsFixed(1)}% change)',
          );
        }

        // If modified, break the large API chunk into smaller review chunks
        if (response.wasModified) {
          // The challenge: we sent 50 paragraphs to Gemini, got back modified text
          // Now we need to split it into review chunks without losing alignment

          // For now, show the entire API chunk as one review
          // This keeps original and cleaned text properly aligned
          final chunkChange = ChunkChange(
            chunkIndex: pendingChanges.length,
            originalText: apiChunkText,
            proposedText: response.cleanedText,
            startParagraphIdx: apiStart,
            endParagraphIdx: apiEnd,
            detectedChanges: response.detectedChanges,
          );

          pendingChanges.add(chunkChange);

          final percentThrough = ((apiEnd / allParagraphs.length) * 100)
              .toStringAsFixed(1);
          setState(() {
            modifiedParagraphs += originalParagraphCount;

            // Create detailed log entry
            final logEntry =
                '• ${percentThrough}% - Detected changes in API chunk ${apiChunkIdx + 1} (paragraphs $apiStart-$apiEnd): ${response.detectedChanges.take(3).join(", ")}';
            liveLogMessages.add(logEntry);
          });
        } else {
          // No modifications - add original content directly
          for (int i = apiStart; i < apiEnd; i++) {
            final originalChapterIdx = paragraphToChapter[i]!;
            cleanedParagraphToChapter[cleanedParagraphs.length] =
                originalChapterIdx;
            cleanedParagraphs.add(allParagraphs[i]);
          }
        }
      } catch (e) {
        print('Error processing API chunk $apiChunkIdx: $e');
        // Keep original paragraphs if filtering fails - add directly to cleaned list
        for (int i = apiStart; i < apiEnd; i++) {
          final originalChapterIdx = paragraphToChapter[i]!;
          cleanedParagraphToChapter[cleanedParagraphs.length] =
              originalChapterIdx;
          cleanedParagraphs.add(allParagraphs[i]);
        }

        setState(() {
          liveLogMessages.add(
            '⚠️ Error in API chunk ${apiChunkIdx + 1}: Using original content',
          );
        });
      }

      // Update progress
      setState(() {
        processedParagraphs = apiEnd;
        progress = apiEnd / allParagraphs.length;
      });
    }
  }

  // Process book paragraph by paragraph (for Ollama)
  Future<void> _processParagraphByParagraph(List<String> allParagraphs) async {
    for (int i = 0; i < allParagraphs.length; i++) {
      // Check for cancellation
      if (isCancelling) {
        print('Processing cancelled by user');
        break;
      }

      final paragraph = allParagraphs[i];
      final chapterIdx = paragraphToChapter[i]!;

      // Skip very short paragraphs (likely formatting elements)
      if (paragraph.trim().length < 10) {
        cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
        cleanedParagraphs.add(paragraph);
        setState(() {
          processedParagraphs++;
          progress = (i + 1) / allParagraphs.length;
        });
        continue;
      }

      print('Processing paragraph ${i + 1}/${allParagraphs.length}...');

      try {
        // Filter the paragraph through Ollama
        final response = await ollamaService.filterParagraph(
          paragraph: paragraph,
          profanityLevel: profanityLevel,
          sexualContentLevel: sexualContentLevel,
          violenceLevel: violenceLevel,
        );

        cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
        cleanedParagraphs.add(response.cleanedText);

        // Track if content was changed
        if (response.wasModified) {
          setState(() {
            modifiedParagraphs++;

            // Add detailed log message
            if (response.removedWords.isNotEmpty) {
              final logMessage = _createLogMessage(
                i + 1,
                response.removedWords,
              );
              liveLogMessages.add(logMessage);

              // Auto-scroll to bottom
              if (_scrollController.hasClients) {
                _scrollController.animateTo(
                  _scrollController.position.maxScrollExtent,
                  duration: const Duration(milliseconds: 300),
                  curve: Curves.easeOut,
                );
              }
            } else {
              liveLogMessages.add('Paragraph ${i + 1}: Content modified');
            }
          });
          removalDetails.add(
            'Modified paragraph ${i + 1} (Chapter ${paragraphToChapter[i]! + 1})',
          );
        }
      } catch (e) {
        print('Error processing paragraph $i: $e');
        // Keep original paragraph if filtering fails
        cleanedParagraphToChapter[cleanedParagraphs.length] = chapterIdx;
        cleanedParagraphs.add(paragraph);
      }

      // Update progress
      setState(() {
        processedParagraphs++;
        progress = (i + 1) / allParagraphs.length;
      });
    }
  }

  /// Apply the changes that user approved during review
  Future<void> _applyApprovedChanges(List<ChunkChange> approvedChanges) async {
    setState(() {
      isReviewingChanges = false;
      liveLogMessages.add(
        '📝 Applying ${approvedChanges.length} approved changes...',
      );
    });

    for (final change in approvedChanges) {
      // Split the proposed text back into paragraphs
      final cleanedChunkParagraphs = change.proposedText
          .split('\n\n')
          .where((p) => p.trim().isNotEmpty)
          .toList();

      final start = change.startParagraphIdx;
      final end = change.endParagraphIdx;
      final originalParagraphCount = end - start;

      // Add cleaned paragraphs and map to chapters
      for (int i = 0; i < cleanedChunkParagraphs.length; i++) {
        // Map the new cleaned paragraph to its original chapter
        // We assume paragraphs stay in order, so map proportionally
        final originalIdx =
            start +
            ((i * originalParagraphCount) ~/ cleanedChunkParagraphs.length);
        final originalChapterIdx = paragraphToChapter[originalIdx]!;

        // Add to cleaned paragraphs and map to chapter
        cleanedParagraphToChapter[cleanedParagraphs.length] =
            originalChapterIdx;
        cleanedParagraphs.add(cleanedChunkParagraphs[i]);
      }
    }

    // For rejected changes, add original content
    final allParagraphs = <String>[];
    for (
      int chapterIdx = 0;
      chapterIdx < parsedEpub!.chapters.length;
      chapterIdx++
    ) {
      final chapter = parsedEpub!.chapters[chapterIdx];
      allParagraphs.addAll(chapter.paragraphs);
    }

    for (final change in pendingChanges) {
      if (!change.isApproved) {
        // Add original paragraphs for rejected changes
        for (
          int i = change.startParagraphIdx;
          i < change.endParagraphIdx;
          i++
        ) {
          final originalChapterIdx = paragraphToChapter[i]!;
          cleanedParagraphToChapter[cleanedParagraphs.length] =
              originalChapterIdx;
          cleanedParagraphs.add(allParagraphs[i]);
        }
      }
    }

    setState(() {
      isProcessing = false;
      progress = 1.0;
      liveLogMessages.add(
        '✅ Book processed: ${cleanedParagraphs.length} paragraphs, ${approvedChanges.length} changes applied',
      );
    });

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Changes applied! Ready to save.'),
          duration: Duration(seconds: 3),
        ),
      );
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
                                const Icon(
                                  Icons.check_circle,
                                  color: Colors.green,
                                ),
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
                      onPressed: (isProcessing || isLoadingFile)
                          ? null
                          : selectFile,
                      icon: isLoadingFile
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.folder_open),
                      label: Text(
                        isLoadingFile ? 'Loading...' : 'Browse EPUB Files',
                      ),
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
                    // AI Provider Selector
                    Row(
                      children: [
                        const Text(
                          'AI Provider:',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: DropdownButton<String>(
                            value: selectedProvider,
                            isExpanded: true,
                            items: const [
                              DropdownMenuItem(
                                value: 'ollama',
                                child: Text('Ollama (Local)'),
                              ),
                              DropdownMenuItem(
                                value: 'gemini',
                                child: Text('Google Gemini (Cloud)'),
                              ),
                            ],
                            onChanged: isProcessing
                                ? null
                                : (String? newProvider) {
                                    if (newProvider != null) {
                                      setState(() {
                                        selectedProvider = newProvider;
                                        if (newProvider == 'gemini') {
                                          _showGeminiApiKeyDialog();
                                        } else {
                                          _loadAvailableModels();
                                        }
                                      });
                                    }
                                  },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    // Model Selector
                    Row(
                      children: [
                        const Text(
                          'AI Model:',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: isLoadingModels
                              ? const Row(
                                  children: [
                                    SizedBox(
                                      width: 16,
                                      height: 16,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                      ),
                                    ),
                                    SizedBox(width: 8),
                                    Text(
                                      'Loading models...',
                                      style: TextStyle(fontSize: 12),
                                    ),
                                  ],
                                )
                              : DropdownButton<String>(
                                  value: selectedModel,
                                  isExpanded: true,
                                  items: availableModels
                                      .map(
                                        (model) => DropdownMenuItem(
                                          value: model,
                                          child: Text(model),
                                        ),
                                      )
                                      .toList(),
                                  onChanged: isProcessing
                                      ? null
                                      : _onModelChanged,
                                ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Language',
                      profanityLevel,
                      (value) => setState(() => profanityLevel = value.toInt()),
                      [
                        '1 - G Rated: No profanity or crude language (Most censorship)',
                        '2 - PG Rated: Mild language allowed (Heavy censorship)',
                        '3 - PG-13 Rated: Some strong language (Light censorship)',
                        '4 - R Rated: Strong language allowed (Censorship of F word only)',
                        '5 - Unrated: Everything allowed (No censorship)',
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Sexual Content',
                      sexualContentLevel,
                      (value) =>
                          setState(() => sexualContentLevel = value.toInt()),
                      [
                        '1 - G Rated: No sexual content allowed (Most censorship)',
                        '2 - PG Rated: Light romance only (Heavy censorship)',
                        '3 - PG-13 Rated: Romantic scenes allowed (Light censorship)',
                        '4 - R Rated: Suggestive content allowed (Censorship of X rated content only)',
                        '5 - Unrated: Everything allowed (No censorship)',
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildSliderSection(
                      'Violence',
                      violenceLevel,
                      (value) => setState(() => violenceLevel = value.toInt()),
                      [
                        '1 - G Rated: No violence (Most censorship)',
                        '2 - PG Rated: Mild conflict only (Heavy censorship)',
                        '3 - PG-13 Rated: Action/combat allowed (Light censorship)',
                        '4 - R Rated: Intense violence allowed (Censorship of intense gore only)',
                        '5 - Unrated: Everything allowed (No censorship)',
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Debug info (remove after testing)
            Text(
              'State: isProcessing=$isProcessing, cleanedParagraphs=${cleanedParagraphs.length}, isCancelling=$isCancelling',
              style: const TextStyle(fontSize: 10, color: Colors.grey),
            ),
            const SizedBox(height: 8),

            // Process/Cancel Buttons
            if (!isProcessing)
              ElevatedButton.icon(
                onPressed: (parsedEpub == null || isLoadingFile)
                    ? null
                    : processBook,
                icon: const Icon(Icons.cleaning_services),
                label: const Text('Clean Book'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
              )
            else
              Row(
                children: [
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: null,
                      icon: const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      label: const Text('Processing...'),
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  ElevatedButton.icon(
                    onPressed: isCancelling ? null : cancelProcessing,
                    icon: const Icon(Icons.cancel),
                    label: Text(isCancelling ? 'Cancelling...' : 'Cancel'),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      backgroundColor: Colors.red.withOpacity(0.8),
                    ),
                  ),
                ],
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
                      const SizedBox(height: 12),
                      // Real-time statistics
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.blue.withOpacity(0.1),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                            color: Colors.blue.withOpacity(0.3),
                          ),
                        ),
                        child: Column(
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceAround,
                              children: [
                                _buildStatItem(
                                  'Processed',
                                  '$processedParagraphs / $totalParagraphs',
                                  Icons.article,
                                ),
                                _buildStatItem(
                                  'Modified',
                                  '$modifiedParagraphs',
                                  Icons.edit,
                                  color: modifiedParagraphs > 0
                                      ? Colors.orange
                                      : Colors.grey,
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                      // Live logging display
                      if (liveLogMessages.isNotEmpty)
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Live Processing Log:',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Container(
                              height: 150,
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: Colors.black.withOpacity(0.3),
                                borderRadius: BorderRadius.circular(4),
                                border: Border.all(
                                  color: Colors.orange.withOpacity(0.5),
                                ),
                              ),
                              child: ListView.builder(
                                controller: _scrollController,
                                itemCount: liveLogMessages.length,
                                itemBuilder: (context, index) {
                                  return Padding(
                                    padding: const EdgeInsets.symmetric(
                                      vertical: 2,
                                    ),
                                    child: Text(
                                      liveLogMessages[index],
                                      style: const TextStyle(
                                        fontSize: 11,
                                        fontFamily: 'monospace',
                                        color: Colors.orange,
                                      ),
                                    ),
                                  );
                                },
                              ),
                            ),
                            const SizedBox(height: 16),
                          ],
                        ),
                    ],
                  ),
                ),
              ),

            // Save Edited Book Button (always visible, disabled until processing completes)
            const SizedBox(height: 20),
            ElevatedButton.icon(
              onPressed: cleanedParagraphs.isNotEmpty ? saveCleanedBook : null,
              icon: const Icon(Icons.save),
              label: const Text('Save Edited Book'),
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
                backgroundColor: cleanedParagraphs.isNotEmpty
                    ? Colors.green
                    : null,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Obfuscate a word by replacing middle characters with asterisks
  String _obfuscateWord(String word) {
    if (word.length <= 2) {
      return '*' * word.length;
    } else if (word.length == 3) {
      return '${word[0]}*${word[2]}';
    } else {
      final asterisks = '*' * (word.length - 2);
      return '${word[0]}$asterisks${word[word.length - 1]}';
    }
  }

  /// Create log message for removed words
  String _createLogMessage(int paragraphNum, List<String> removedWords) {
    // Categorize words
    final profanityWords = <String>[];
    final sexualWords = <String>[];
    final violenceWords = <String>[];

    // Common profanity keywords
    const profanityKeywords = [
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
    ];

    // Sexual content keywords
    const sexualKeywords = [
      'cleavage',
      'neckline',
      'sexy',
      'passionate',
      'kiss',
      'kissing',
    ];

    // Violence keywords
    const violenceKeywords = [
      'punch',
      'hit',
      'fight',
      'blood',
      'kill',
      'violence',
      'weapon',
    ];

    for (final word in removedWords) {
      final lowerWord = word.toLowerCase();
      if (profanityKeywords.contains(lowerWord)) {
        profanityWords.add(word);
      } else if (sexualKeywords.contains(lowerWord)) {
        sexualWords.add(word);
      } else if (violenceKeywords.contains(lowerWord)) {
        violenceWords.add(word);
      }
    }

    final parts = <String>[];

    // Add profanity with obfuscation
    if (profanityWords.isNotEmpty) {
      final obfuscated = profanityWords.map(_obfuscateWord).join(', ');
      parts.add('profanity ($obfuscated)');
    }

    // Add sexual content with obfuscation
    if (sexualWords.isNotEmpty) {
      final obfuscated = sexualWords.map(_obfuscateWord).join(', ');
      parts.add('sexual ($obfuscated)');
    }

    // Add violence with obfuscation
    if (violenceWords.isNotEmpty) {
      final obfuscated = violenceWords.map(_obfuscateWord).join(', ');
      parts.add('violence ($obfuscated)');
    }

    if (parts.isEmpty) {
      return 'Paragraph $paragraphNum: Content modified';
    }

    return 'Paragraph $paragraphNum: Removed ${parts.join(', ')}';
  }

  Widget _buildStatItem(
    String label,
    String value,
    IconData icon, {
    Color? color,
  }) {
    return Column(
      children: [
        Icon(icon, size: 32, color: color ?? Colors.blue),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.bold,
            color: color ?? Colors.blue,
          ),
        ),
        Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey)),
      ],
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
          max: 5,
          divisions: 4,
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
}
