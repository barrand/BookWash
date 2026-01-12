/// Platform-agnostic API service for BookWash processing.
///
/// On desktop: runs Python scripts directly
/// On web: calls FastAPI backend via HTTP
library;

import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;

// Import the correct implementation based on platform
import 'api_service_stub.dart'
    if (dart.library.io) 'api_service_desktop.dart'
    if (dart.library.html) 'api_service_web.dart'
    as impl;

/// Represents a processing session
class ProcessingSession {
  final String sessionId;
  final String filename;
  String status;
  double progress;
  String phase;
  List<ChangeItem> changes;
  List<LogMessage> logs;

  ProcessingSession({
    required this.sessionId,
    required this.filename,
    this.status = 'uploaded',
    this.progress = 0.0,
    this.phase = 'idle',
    List<ChangeItem>? changes,
    List<LogMessage>? logs,
  }) : changes = changes ?? [],
       logs = logs ?? [];
}

/// Represents a single content change
class ChangeItem {
  final String id;
  final int chapter;
  final String chapterTitle;
  String status;
  final String reason;
  final String original;
  final String cleaned;

  ChangeItem({
    required this.id,
    required this.chapter,
    required this.chapterTitle,
    required this.status,
    required this.reason,
    required this.original,
    required this.cleaned,
  });

  factory ChangeItem.fromJson(Map<String, dynamic> json) {
    return ChangeItem(
      id: json['id'] ?? '',
      chapter: json['chapter'] ?? 0,
      chapterTitle: json['chapter_title'] ?? '',
      status: json['status'] ?? 'pending',
      reason: json['reason'] ?? '',
      original: json['original'] ?? '',
      cleaned: json['cleaned'] ?? '',
    );
  }
}

/// Log message with timestamp
class LogMessage {
  final DateTime time;
  final String message;

  LogMessage({required this.time, required this.message});

  factory LogMessage.fromJson(Map<String, dynamic> json) {
    return LogMessage(
      time: DateTime.tryParse(json['time'] ?? '') ?? DateTime.now(),
      message: json['message'] ?? '',
    );
  }
}

/// Abstract API service interface
abstract class ApiService {
  /// Factory constructor that returns the platform-specific implementation
  factory ApiService({String? baseUrl, String? apiKey}) {
    return impl.createApiService(baseUrl: baseUrl, apiKey: apiKey);
  }

  /// Whether this service requires a backend URL (web) or runs locally (desktop)
  bool get requiresBackendUrl;

  /// Set the backend URL (for web)
  void setBackendUrl(String url);

  /// Set the Gemini API key (for desktop)
  void setApiKey(String key);

  /// Optional: set Basic Auth credentials (for web servers requiring auth)
  void setAuth(String username, String password);

  /// Upload an EPUB file and create a processing session
  Future<ProcessingSession> uploadEpub(
    String filePath,
    List<int> fileBytes,
    String fileName,
  );

  /// Start processing a session
  Future<void> startProcessing({
    required String sessionId,
    required List<String> languageWords,
    required int targetAdult,
    required int targetViolence,
    required String model,
  });

  /// Stream of log messages for a session
  Stream<LogMessage> streamLogs(String sessionId);

  /// Stream of session status updates
  Stream<ProcessingSession> streamStatus(String sessionId);

  /// Get the current session state
  Future<ProcessingSession> getSession(String sessionId);

  /// Update a change's status (accept/reject)
  Future<void> updateChange(String sessionId, String changeId, String status);

  /// Accept all pending changes
  Future<int> acceptAllChanges(String sessionId);

  /// Export the processed EPUB
  Future<List<int>> exportEpub(String sessionId);

  /// Delete/cleanup a session
  Future<void> deleteSession(String sessionId);

  /// Health check
  Future<bool> healthCheck();
}

/// Check if running on web
bool get isWeb => kIsWeb;
