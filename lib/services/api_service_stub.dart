/// Stub implementation - should never be used at runtime
/// This file exists for conditional import fallback

import 'api_service.dart';

ApiService createApiService({String? baseUrl, String? apiKey}) {
  throw UnsupportedError(
    'Cannot create ApiService without platform-specific implementation',
  );
}
