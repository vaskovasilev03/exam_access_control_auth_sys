export 'face_detector_service_native.dart'
    if (dart.library.js_interop) 'face_detector_service_web.dart'
    if (dart.library.html) 'face_detector_service_web.dart';
