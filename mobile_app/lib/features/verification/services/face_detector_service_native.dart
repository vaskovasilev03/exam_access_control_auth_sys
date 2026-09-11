import 'dart:async';
import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:tflite_flutter/tflite_flutter.dart';

class FaceDetectorService {
  static final FaceDetectorService _instance = FaceDetectorService._internal();
  factory FaceDetectorService() => _instance;
  FaceDetectorService._internal();

  Interpreter? _interpreter;
  bool _isProcessing = false;
  bool _isInitialized = false;

  // Pre-allocated nested lists reused across all inferences.
  // Modifying these in-place guarantees zero heap allocations per frame
  // and ensures tflite_flutter receives real, live camera pixel data on every inference.
  final List<List<List<List<double>>>> _input = List.generate(
    1,
    (_) => List.generate(
      128,
      (_) => List.generate(128, (_) => List.filled(3, 0.0)),
    ),
  );
  final List<List<List<double>>> _outputBoxes = List.generate(
    1,
    (_) => List.generate(896, (_) => List.filled(16, 0.0)),
  );
  final List<List<List<double>>> _outputScores = List.generate(
    1,
    (_) => List.generate(896, (_) => List.filled(1, 0.0)),
  );

  // Coordinate lookup tables for fast 128x128 downsampling
  int _lastSrcWidth = 0;
  int _lastSrcHeight = 0;
  int _lastRowStride = 0;
  final Int32List _rowOffsets = Int32List(128);
  final Int32List _colOffsets = Int32List(128);

  bool get isInitialized => _interpreter != null;

  Future<void> initialize() async {
    if (_isInitialized && _interpreter != null) return;

    try {
      _interpreter = await Interpreter.fromAsset('assets/models/blazeface.tflite');

      // Pre-warm the TFLite interpreter with a dummy inference.
      // This forces kernel compilation and buffer allocation during initial setup,
      // ensuring that the first real frame causes zero UI freeze or stutter.
      _interpreter!.runForMultipleInputs(
        [_input],
        {0: _outputBoxes, 1: _outputScores},
      );

      _isInitialized = true;
      debugPrint('BlazeFace model loaded and pre-warmed successfully');
    } catch (e) {
      debugPrint('Error loading BlazeFace model: $e');
    }
  }

  void _updateLookupTables(int srcWidth, int srcHeight, int rowStride) {
    if (srcWidth == _lastSrcWidth &&
        srcHeight == _lastSrcHeight &&
        rowStride == _lastRowStride) {
      return;
    }

    _lastSrcWidth = srcWidth;
    _lastSrcHeight = srcHeight;
    _lastRowStride = rowStride;

    final double rowStep = srcHeight / 128.0;
    final double colStep = srcWidth / 128.0;

    for (int y = 0; y < 128; y++) {
      final int srcY = (y * rowStep).floor().clamp(0, srcHeight - 1);
      _rowOffsets[y] = srcY * rowStride;
    }

    for (int x = 0; x < 128; x++) {
      _colOffsets[x] = (x * colStep).floor().clamp(0, srcWidth - 1);
    }
  }

  bool? detectFace(CameraImage image) {
    if (_interpreter == null) return true;

    // Simple re-entrancy guard
    if (_isProcessing) {
      return null;
    }

    _isProcessing = true;

    try {
      if (image.planes.isEmpty || image.planes[0].bytes.isEmpty) {
        return null;
      }
      final bytes = image.planes[0].bytes;
      final int srcWidth = image.width;
      final int srcHeight = image.height;
      final int rowStride = image.planes[0].bytesPerRow;

      _updateLookupTables(srcWidth, srcHeight, rowStride);

      // Fast downsampling directly into the pre-allocated reusable nested list
      const double normFactor = 1.0 / 255.0;
      final rowLists = _input[0];
      for (int y = 0; y < 128; y++) {
        final int rowOffset = _rowOffsets[y];
        final rowList = rowLists[y];
        for (int x = 0; x < 128; x++) {
          final int srcIndex = rowOffset + _colOffsets[x];
          final double normValue =
              srcIndex < bytes.length ? bytes[srcIndex] * normFactor : 0.0;
          final pixel = rowList[x];
          pixel[0] = normValue;
          pixel[1] = normValue;
          pixel[2] = normValue;
        }
      }

      _interpreter!.runForMultipleInputs(
        [_input],
        {0: _outputBoxes, 1: _outputScores},
      );

      double maxScore = -100.0;
      final scoresList = _outputScores[0];
      for (int i = 0; i < 896; i++) {
        final double score = scoresList[i][0];
        if (score > maxScore) {
          maxScore = score;
        }
      }

      return maxScore > 0.35;
    } catch (e) {
      debugPrint('BlazeFace frame processing error: $e');
      return null;
    } finally {
      _isProcessing = false;
    }
  }

  void reset() {
    _isProcessing = false;
  }

  void dispose() {
    _interpreter?.close();
    _interpreter = null;
    _isInitialized = false;
  }
}
