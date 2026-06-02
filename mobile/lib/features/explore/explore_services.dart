import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:google_mlkit_translation/google_mlkit_translation.dart';
import 'package:image_picker/image_picker.dart';

enum PhotoSource { camera, gallery }

class CapturedPhoto {
  const CapturedPhoto({required this.bytes, this.path});

  final Uint8List bytes;
  final String? path;
}

class OcrTranslationResult {
  const OcrTranslationResult({required this.text, this.translatedText});

  final String text;
  final String? translatedText;
}

class GeoPoint {
  const GeoPoint({required this.latitude, required this.longitude});

  final double latitude;
  final double longitude;
}

abstract class PhotoPickerService {
  Future<CapturedPhoto?> pick(PhotoSource source);

  Future<List<CapturedPhoto>> pickMany(PhotoSource source) async {
    final photo = await pick(source);
    return photo == null ? const [] : [photo];
  }
}

abstract class OcrTranslationService {
  Future<OcrTranslationResult> recognizeAndTranslate(CapturedPhoto photo);
}

abstract class LocationReader {
  Future<GeoPoint?> currentPosition();
}

final photoPickerServiceProvider = Provider<PhotoPickerService>((ref) {
  return ImagePickerPhotoService();
});

final ocrTranslationServiceProvider = Provider<OcrTranslationService>((ref) {
  final service = MlKitOcrTranslationService();
  ref.onDispose(service.dispose);
  return service;
});

final locationReaderProvider = Provider<LocationReader>((ref) {
  return GeolocatorLocationReader();
});

class ImagePickerPhotoService implements PhotoPickerService {
  ImagePickerPhotoService({ImagePicker? picker})
    : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  @override
  Future<CapturedPhoto?> pick(PhotoSource source) async {
    final image = await _picker.pickImage(
      source: source == PhotoSource.camera
          ? ImageSource.camera
          : ImageSource.gallery,
      maxWidth: 1280,
      imageQuality: 86,
    );
    if (image == null) {
      return null;
    }
    return CapturedPhoto(bytes: await image.readAsBytes(), path: image.path);
  }

  @override
  Future<List<CapturedPhoto>> pickMany(PhotoSource source) async {
    if (source == PhotoSource.camera) {
      final photo = await pick(source);
      return photo == null ? const [] : [photo];
    }
    final images = await _picker.pickMultiImage(
      maxWidth: 1280,
      imageQuality: 86,
    );
    return Future.wait(
      images.map((image) async {
        return CapturedPhoto(
          bytes: await image.readAsBytes(),
          path: image.path,
        );
      }),
    );
  }
}

class MlKitOcrTranslationService implements OcrTranslationService {
  MlKitOcrTranslationService()
    : _recognizer = TextRecognizer(script: TextRecognitionScript.japanese);

  final TextRecognizer _recognizer;

  @override
  Future<OcrTranslationResult> recognizeAndTranslate(
    CapturedPhoto photo,
  ) async {
    if (photo.path == null) {
      return const OcrTranslationResult(text: '', translatedText: null);
    }
    final input = InputImage.fromFilePath(photo.path!);
    final recognized = await _recognizer.processImage(input);
    return OcrTranslationResult(
      text: recognized.text,
      translatedText: await _translateJapanese(recognized.text),
    );
  }

  Future<String?> _translateJapanese(String text) async {
    if (text.trim().isEmpty) return null;
    final manager = OnDeviceTranslatorModelManager();
    try {
      await manager.downloadModel(
        TranslateLanguage.japanese.bcpCode,
        isWifiRequired: false,
      );
      await manager.downloadModel(
        TranslateLanguage.chinese.bcpCode,
        isWifiRequired: false,
      );
      final translator = OnDeviceTranslator(
        sourceLanguage: TranslateLanguage.japanese,
        targetLanguage: TranslateLanguage.chinese,
      );
      try {
        return await translator.translateText(text);
      } finally {
        await translator.close();
      }
    } catch (_) {
      return null;
    }
  }

  void dispose() {
    _recognizer.close();
  }
}

class GeolocatorLocationReader implements LocationReader {
  @override
  Future<GeoPoint?> currentPosition() async {
    try {
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        return null;
      }
      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.medium,
          timeLimit: Duration(seconds: 2),
        ),
      );
      return GeoPoint(
        latitude: position.latitude,
        longitude: position.longitude,
      );
    } catch (_) {
      return null;
    }
  }
}
