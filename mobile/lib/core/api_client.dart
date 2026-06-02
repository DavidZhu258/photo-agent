import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/explore/models.dart';

const _defaultApiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://127.0.0.1:8000',
);

final apiClientProvider = Provider<VisualExploreClient>((ref) {
  return PhotoAgentApiClient(
    Dio(
      BaseOptions(
        baseUrl: _defaultApiBaseUrl,
        connectTimeout: const Duration(seconds: 2),
        receiveTimeout: const Duration(seconds: 20),
      ),
    ),
  );
});

abstract class VisualExploreClient {
  Future<VisualExploreResponse> explore({
    required Uint8List imageBytes,
    List<Uint8List> additionalImages = const [],
    required String ocrText,
    String? translatedText,
    String userContextText = '',
    String explorationFocus = 'auto',
    double? lat,
    double? lng,
    double? heading,
    List<String> interestTags = const [],
  });
}

class PhotoAgentApiClient implements VisualExploreClient {
  PhotoAgentApiClient(this._dio);

  final Dio _dio;

  @override
  Future<VisualExploreResponse> explore({
    required Uint8List imageBytes,
    List<Uint8List> additionalImages = const [],
    required String ocrText,
    String? translatedText,
    String userContextText = '',
    String explorationFocus = 'auto',
    double? lat,
    double? lng,
    double? heading,
    List<String> interestTags = const [],
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/v1/visual/explore',
      data: {
        'image_base64': base64Encode(imageBytes),
        'gps_lat': lat,
        'gps_lng': lng,
        'heading_degrees': heading,
        'client_ocr_text': ocrText,
        'client_ocr_translated_text': translatedText,
        'client_ocr_language': ocrText.trim().isEmpty ? null : 'ja',
        'images_base64': additionalImages.map(base64Encode).toList(),
        'user_context_text': userContextText,
        'exploration_focus': explorationFocus,
        'interest_tags': interestTags,
      },
    );
    return VisualExploreResponse.fromJson(response.data ?? {});
  }
}
