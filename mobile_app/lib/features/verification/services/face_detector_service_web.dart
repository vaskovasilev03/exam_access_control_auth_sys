import 'package:camera/camera.dart';

class FaceDetectorService {
  static final FaceDetectorService _instance = FaceDetectorService._internal();
  factory FaceDetectorService() => _instance;
  FaceDetectorService._internal();

  bool get isInitialized => true;

  Future<void> initialize() async {}

  bool? detectFace(CameraImage image) {
    return true;
  }

  void reset() {}

  void dispose() {}
}
