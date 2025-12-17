/// Desktop implementation of ApiService using local Python scripts
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as path;

import 'api_service.dart';
import 'bookwash_parser.dart';

/// Create the desktop API service
ApiService createApiService({String? baseUrl, String? apiKey}) {
  return DesktopApiService(apiKey: apiKey ?? '');
}

class DesktopApiService implements ApiService {
  String _apiKey;
  // Desktop does not use auth; method is a no-op to satisfy interface
  @override
  void setAuth(String username, String password) {}
  final Map<String, _LocalSession> _sessions = {};
  String? _scriptsDir;

  DesktopApiService({required String apiKey}) : _apiKey = apiKey;

  String get scriptsDir {
    if (_scriptsDir != null) return _scriptsDir!;

    // Find the scripts directory relative to the executable
    final execDir = path.dirname(Platform.script.toFilePath());

    // Try different possible locations
    final candidates = [
      path.join(execDir, '..', 'scripts'),
      path.join(execDir, 'scripts'),
      path.join(execDir, '..', '..', 'scripts'),
      path.join(Directory.current.path, 'scripts'),
    ];

    for (final candidate in candidates) {
      if (Directory(candidate).existsSync()) {
        _scriptsDir = path.canonicalize(candidate);
        return _scriptsDir!;
      }
    }

    // Fallback to current directory
    _scriptsDir = path.join(Directory.current.path, 'scripts');
    return _scriptsDir!;
  }

  @override
  bool get requiresBackendUrl => false;

  @override
  void setBackendUrl(String url) {
    // Not used on desktop
  }

  @override
  void setApiKey(String key) {
    _apiKey = key;
  }

  @override
  Future<ProcessingSession> uploadEpub(
    String filePath,
    List<int> fileBytes,
    String fileName,
  ) async {
    // On desktop, we just store the file path reference
    final sessionId = DateTime.now().millisecondsSinceEpoch.toString();

    // If fileBytes provided (e.g., from file picker), write to temp location
    String actualPath = filePath;
    if (fileBytes.isNotEmpty && filePath.isEmpty) {
      final tempDir = await Directory.systemTemp.createTemp('bookwash_');
      actualPath = path.join(tempDir.path, fileName);
      await File(actualPath).writeAsBytes(fileBytes);
    }

    final session = _LocalSession(
      sessionId: sessionId,
      filename: fileName,
      epubPath: actualPath,
    );
    _sessions[sessionId] = session;

    return ProcessingSession(
      sessionId: sessionId,
      filename: fileName,
      status: 'uploaded',
    );
  }

  @override
  Future<void> startProcessing({
    required String sessionId,
    required int targetAdult,
    required int targetViolence,
    required String model,
  }) async {
    final session = _sessions[sessionId];
    if (session == null) {
      throw Exception('Session not found');
    }

    session.status = 'processing';
    session.targetAdult = targetAdult;
    session.targetViolence = targetViolence;
    session.model = model;

    // Start processing in background
    _processInBackground(session);
  }

  Future<void> _processInBackground(_LocalSession session) async {
    try {
      session.addLog('📚 Starting BookWash processing...');
      session.addLog('📖 Input: ${path.basename(session.epubPath)}');

      // Step 1: Convert EPUB to .bookwash
      session.addLog('');
      session.addLog('═══════════════════════════════════════════');
      session.addLog('📝 Step 1: Converting EPUB to .bookwash format...');
      session.addLog('═══════════════════════════════════════════');
      session.phase = 'converting';
      session.progress = 5;

      final bookwashPath = session.epubPath.replaceAll('.epub', '.bookwash');
      session.bookwashPath = bookwashPath;

      final convertResult = await Process.run('python3', [
        path.join(scriptsDir, 'epub_to_bookwash.py'),
        session.epubPath,
        bookwashPath,
      ]);

      if (convertResult.exitCode != 0) {
        throw Exception('EPUB conversion failed: ${convertResult.stderr}');
      }

      session.addLog('✅ EPUB converted to .bookwash format');

      // Step 2: Rate and clean with LLM
      session.addLog('');
      session.addLog('═══════════════════════════════════════════');
      session.addLog('🤖 Step 2: Rating and cleaning content with AI...');
      session.addLog('═══════════════════════════════════════════');

      final ratingNames = {1: 'G', 2: 'PG', 3: 'PG-13', 4: 'Unfiltered'};
      session.addLog(
        'Target levels: '
        'Adult=${ratingNames[session.targetAdult]}, '
        'Violence=${ratingNames[session.targetViolence]}',
      );

      session.phase = 'rating';
      session.progress = 10;

      final process = await Process.start(
        'python3',
        [
          '-u',
          path.join(scriptsDir, 'bookwash_llm.py'),
          '--rate',
          '--clean',
          '--sexual',
          session.targetAdult.toString(),
          '--violence',
          session.targetViolence.toString(),
          '--model',
          session.model,
          bookwashPath,
        ],
        environment: {'GEMINI_API_KEY': _apiKey, 'PYTHONUNBUFFERED': '1'},
      );

      // Stream stdout
      process.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
            session.addLog(line);
            _parseProgress(session, line);
          });

      // Stream stderr
      process.stderr
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
            session.addLog('⚠️ $line');
          });

      final exitCode = await process.exitCode;
      if (exitCode != 0) {
        throw Exception('LLM processing failed');
      }

      session.addLog('✅ Content rated and cleaned');
      session.progress = 95;

      // Step 3: Parse changes
      session.addLog('');
      session.addLog('═══════════════════════════════════════════');
      session.addLog('📋 Step 3: Extracting changes for review...');
      session.addLog('═══════════════════════════════════════════');

      await _parseChanges(session);

      final pendingCount = session.changes
          .where((c) => c.status == 'pending')
          .length;
      session.addLog('✅ Found $pendingCount pending changes to review');

      session.progress = 100;
      session.phase = 'complete';
      session.status = 'review';

      session.addLog('');
      session.addLog('═══════════════════════════════════════════');
      session.addLog('🎉 Processing complete!');
      session.addLog('═══════════════════════════════════════════');
      session.addLog('Review changes below, then export when ready.');
    } catch (e) {
      session.addLog('❌ Error: $e');
      session.status = 'error';
      session.error = e.toString();
    }
  }

  void _parseProgress(_LocalSession session, String line) {
    // Parse "[1/7]" format
    final match = RegExp(r'\[(\d+)/(\d+)\]').firstMatch(line);
    if (match != null) {
      final current = int.tryParse(match.group(1) ?? '0') ?? 0;
      final total = int.tryParse(match.group(2) ?? '0') ?? 0;
      final pct = current / total;

      if (session.phase == 'rating' || session.progress < 50) {
        session.progress = 10 + (pct * 40).toInt();
      } else {
        session.progress = 50 + (pct * 45).toInt();
      }
    }

    if (line.contains('Cleaning') && line.contains('chapters')) {
      session.phase = 'cleaning';
      session.progress = 50;
    } else if (line.contains('No chapters need cleaning')) {
      session.phase = 'cleaning';
      session.progress = 95;
    }
  }

  Future<void> _parseChanges(_LocalSession session) async {
    if (session.bookwashPath == null) return;

    final bookwashFile = await BookWashParser.parse(session.bookwashPath!);

    session.changes = [];
    for (int i = 0; i < bookwashFile.chapters.length; i++) {
      final chapter = bookwashFile.chapters[i];
      for (final change in chapter.changes) {
        session.changes.add(
          ChangeItem(
            id: change.id,
            chapter: i,
            chapterTitle: chapter.title,
            status: change.status,
            reason: change.reason,
            original: change.original,
            cleaned: change.cleaned,
          ),
        );
      }
    }
  }

  @override
  Stream<LogMessage> streamLogs(String sessionId) async* {
    final session = _sessions[sessionId];
    if (session == null) return;

    int lastIndex = 0;
    while (true) {
      if (session.logs.length > lastIndex) {
        for (int i = lastIndex; i < session.logs.length; i++) {
          yield session.logs[i];
        }
        lastIndex = session.logs.length;
      }

      if (session.status == 'review' ||
          session.status == 'error' ||
          session.status == 'complete') {
        break;
      }

      await Future.delayed(const Duration(milliseconds: 100));
    }
  }

  @override
  Stream<ProcessingSession> streamStatus(String sessionId) async* {
    final session = _sessions[sessionId];
    if (session == null) return;

    while (true) {
      yield ProcessingSession(
        sessionId: sessionId,
        filename: session.filename,
        status: session.status,
        progress: session.progress.toDouble(),
        phase: session.phase,
        changes: session.changes,
      );

      if (session.status == 'review' ||
          session.status == 'error' ||
          session.status == 'complete') {
        break;
      }

      await Future.delayed(const Duration(milliseconds: 500));
    }
  }

  @override
  Future<ProcessingSession> getSession(String sessionId) async {
    final session = _sessions[sessionId];
    if (session == null) {
      throw Exception('Session not found');
    }

    return ProcessingSession(
      sessionId: sessionId,
      filename: session.filename,
      status: session.status,
      progress: session.progress.toDouble(),
      phase: session.phase,
      changes: session.changes,
    );
  }

  @override
  Future<void> updateChange(
    String sessionId,
    String changeId,
    String status,
  ) async {
    final session = _sessions[sessionId];
    if (session == null) {
      throw Exception('Session not found');
    }

    // Update in memory
    for (final change in session.changes) {
      if (change.id == changeId) {
        change.status = status;
        break;
      }
    }

    // Update in file
    if (session.bookwashPath != null) {
      final content = await File(session.bookwashPath!).readAsString();
      final lines = content.split('\n');
      final newLines = <String>[];
      bool foundChange = false;

      for (final line in lines) {
        if (line.startsWith('#CHANGE: $changeId')) {
          foundChange = true;
        } else if (foundChange && line.startsWith('#STATUS:')) {
          newLines.add('#STATUS: $status');
          foundChange = false;
          continue;
        }
        newLines.add(line);
      }

      await File(session.bookwashPath!).writeAsString(newLines.join('\n'));
    }
  }

  @override
  Future<int> acceptAllChanges(String sessionId) async {
    final session = _sessions[sessionId];
    if (session == null) {
      throw Exception('Session not found');
    }

    int count = 0;
    for (final change in session.changes) {
      if (change.status == 'pending') {
        await updateChange(sessionId, change.id, 'accepted');
        count++;
      }
    }

    return count;
  }

  @override
  Future<List<int>> exportEpub(String sessionId) async {
    final session = _sessions[sessionId];
    if (session == null || session.bookwashPath == null) {
      throw Exception('Session not found or not processed');
    }

    final outputPath = session.epubPath.replaceAll('.epub', '_cleaned.epub');

    final result = await Process.run('python3', [
      path.join(scriptsDir, 'bookwash_to_epub.py'),
      session.bookwashPath!,
      '-o',
      outputPath,
    ]);

    if (result.exitCode != 0) {
      throw Exception('Export failed: ${result.stderr}');
    }

    session.status = 'complete';
    session.outputPath = outputPath;

    return await File(outputPath).readAsBytes();
  }

  @override
  Future<void> deleteSession(String sessionId) async {
    _sessions.remove(sessionId);
  }

  @override
  Future<bool> healthCheck() async {
    // On desktop, always healthy
    return true;
  }
}

class _LocalSession {
  final String sessionId;
  final String filename;
  final String epubPath;
  String? bookwashPath;
  String? outputPath;
  String status = 'uploaded';
  int progress = 0;
  String phase = 'idle';
  String? error;
  int targetAdult = 2;
  int targetViolence = 3;
  String model = 'gemini-2.0-flash';
  List<LogMessage> logs = [];
  List<ChangeItem> changes = [];

  _LocalSession({
    required this.sessionId,
    required this.filename,
    required this.epubPath,
  });

  void addLog(String message) {
    logs.add(LogMessage(time: DateTime.now(), message: message));
  }
}
