import 'dart:async';
import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'package:tflite_flutter/tflite_flutter.dart';
import 'package:dio/dio.dart';
import 'package:mobile_app/core/api_client.dart';
import 'package:mobile_app/core/theme_tokens.dart';
import 'package:mobile_app/features/liveness/widgets/face_overlay_painter.dart';

enum LivenessStep { holding, processing, success }

class LivenessScreen extends StatefulWidget {
  final ApiClient apiClient;

  const LivenessScreen({super.key, required this.apiClient});

  @override
  State<LivenessScreen> createState() => _LivenessScreenState();
}

class _LivenessScreenState extends State<LivenessScreen> {
  CameraController? _cameraController;
  Interpreter? _interpreter;

  LivenessStep _currentStep = LivenessStep.holding;
  String _instructionText = "Позиционирайте лицето си в овала";
  Color _stepColor = Colors.white;
  bool _isProcessing = false;
  bool _isProcessingFrame = false;

  // Контролери за новата 5-секундна софтуерна опашка
  int _countdown = 5;
  Timer? _countdownTimer;
  int _consecutiveFramesWithFace = 0;
  
  // Регулатор за FPS плавност (Throttle)
  DateTime _lastProcessedTime = DateTime.now();

  @override
  void initState() {
    super.initState();
    _loadModelAndInitCamera();
  }

  Future<void> _loadModelAndInitCamera() async {
    try {
      // Зареждаме бинарния ИИ модел на Google
      _interpreter = await Interpreter.fromAsset('assets/models/blazeface.tflite');
      
      final cameras = await availableCameras();
      final frontCam = cameras.firstWhere((cam) => cam.lensDirection == CameraLensDirection.front);

      _cameraController = CameraController(
        frontCam,
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.yuv420,
      );

      await _cameraController!.initialize();
      if (!mounted) return;
      setState(() {});

      _startLiveImageStream();
    } catch (e) {
      _showError("Критична грешка при инициализация на TensorFlow: $e");
    }
  }

  void _startLiveImageStream() async {
    if (_cameraController == null || _interpreter == null) return;

    await _cameraController!.startImageStream((CameraImage image) {
      if (_isProcessing || _isProcessingFrame || _currentStep == LivenessStep.success) return;

      final now = DateTime.now();
      // Анализираме кадър през ИИ само веднъж на 350ms, за да запазим високия FPS на видеото
      if (now.difference(_lastProcessedTime).inMilliseconds < 350) return;
      _lastProcessedTime = now;

      _isProcessingFrame = true;

      try {
        if (image.planes.isEmpty || image.planes[0].bytes.isEmpty) {
          _isProcessingFrame = false;
          return;
        }

        // Извличаме бърза светлинна матрица 128x128x3 от паметта на Y-слоя
        var inputTensor = _convertYUVToNativeTensor(image);
        
        var outputBoxes = List.filled(1 * 896 * 16, 0.0).reshape([1, 896, 16]);
        var outputScores = List.filled(1 * 896 * 1, 0.0).reshape([1, 896, 1]);
        
        var inputs = [inputTensor];
        var outputs = {0: outputBoxes, 1: outputScores};

        // Изпълняваме инференцията на Google BlazeFace
        _interpreter!.runForMultipleInputs(inputs, outputs);

        _processTensorResults(outputScores, outputBoxes);

      } catch (e) {
        debugPrint("Проблем при Tensor рутината: $e");
      } finally {
        _isProcessingFrame = false;
      }
    });
  }

  List<dynamic> _convertYUVToNativeTensor(CameraImage image) {
    final bytes = image.planes[0].bytes;
    final int srcWidth = image.width;
    final int srcHeight = image.height;
    
    var input = List.filled(1 * 128 * 128 * 3, 0.0).reshape([1, 128, 128, 3]);

    double rowStep = srcHeight / 128;
    double colStep = srcWidth / 128;

    for (int y = 0; y < 128; y++) {
      int srcY = (y * rowStep).floor().clamp(0, srcHeight - 1);
      for (int x = 0; x < 128; x++) {
        int srcX = (x * colStep).floor().clamp(0, srcWidth - 1);
        int srcIndex = srcY * srcWidth + srcX;
        
        if (srcIndex < bytes.length) {
          double normValue = bytes[srcIndex] / 255.0;
          input[0][y][x][0] = normValue;
          input[0][y][x][1] = normValue;
          input[0][y][x][2] = normValue;
        }
      }
    }
    return input;
  }

  void _processTensorResults(List<dynamic> scores, List<dynamic> boxes) {
    double maxConfidence = 0.0;
    for (int i = 0; i < 896; i++) {
      if (scores[0][i][0] > maxConfidence) {
        maxConfidence = scores[0][i][0];
      }
    }

    if (!mounted) return;

    // 🔴 АКО НЯМА ЛИЦЕ: Нулираме таймера и зачервяваме рамката веднага
    if (maxConfidence < 0.45) { 
      _consecutiveFramesWithFace = 0;
      _resetCountdown();
      setState(() {
        _instructionText = "🔴 Позиционирайте лицето си вътре в овала!";
        _stepColor = UiThemeTokens.destructive;
      });
      return;
    }

    _consecutiveFramesWithFace++;
    if (_consecutiveFramesWithFace < 2) return;

    // 🟢 ИМА ЛИЦЕ: Стартираме брояча, ако още не е пуснат
    if (_countdownTimer == null) {
      _startCountdown();
    }

    setState(() {
      _stepColor = Colors.green;
      if (_countdown > 0) {
        _instructionText = "🟢 Останете неподвижно: $_countdown сек.";
      } else {
        _instructionText = "📸 Заснемане...";
      }
    });
  }

  void _startCountdown() {
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) return;
      setState(() {
        if (_countdown > 1) {
          _countdown--;
        } else {
          _countdown = 0;
          _countdownTimer?.cancel();
          _countdownTimer = null;
          _isProcessing = true;
          
          // Затваряме стрийма и правим финалната снимка
          _cameraController!.stopImageStream();
          _captureAndSend();
        }
      });
    });
  }

  void _resetCountdown() {
    _countdownTimer?.cancel();
    _countdownTimer = null;
    _countdown = 5;
  }

  Future<void> _captureAndSend() async {
    if (_cameraController == null || !_cameraController!.value.isInitialized) return;

    setState(() {
      _currentStep = LivenessStep.processing;
      _instructionText = "Пакетиране на биометричен шаблон...";
    });

    try {
      final XFile photo = await _cameraController!.takePicture();
      final bytes = await photo.readAsBytes();

      final formData = FormData.fromMap({
        "status": "LIVENESS_PASSED",
        "file": MultipartFile.fromBytes(bytes, filename: "liveness_verification.jpg"),
      });

      final response = await widget.apiClient.dio.post('/students/validate', data: formData);

      if (!mounted) return;

      if (response.statusCode == 200) {
        setState(() {
          _currentStep = LivenessStep.success;
          _instructionText = "Успех! Биометричният шаблон е генериран.";
        });

        await Future.delayed(const Duration(seconds: 2));
        if (mounted) {
          Navigator.pop(context, true);
        }
      }
    } catch (e) {
      _showError("Мрежова грешка при изпращане на файла.");
      setState(() {
        _isProcessing = false;
        _currentStep = LivenessStep.holding;
        _stepColor = UiThemeTokens.destructive;
      });
      _resetCountdown();
      _startLiveImageStream();
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: UiThemeTokens.destructive),
    );
  }

  @override
  void dispose() {
    _countdownTimer?.cancel();
    if (_cameraController != null && _cameraController!.value.isStreamingImages) {
      _cameraController!.stopImageStream();
    }
    _cameraController?.dispose();
    _interpreter?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return const Scaffold(
        backgroundColor: Colors.black,
        body: Center(child: CircularProgressIndicator(color: Colors.white)),
      );
    }

    // 🔥 ФИКС ЗА ЗУУМА: Нова, прецизна умножителна формула
    final size = MediaQuery.of(context).size;
    final cameraAspect = _cameraController!.value.aspectRatio; 
    final deviceAspect = size.aspectRatio; 
    
    double scale = 1.0 / (cameraAspect * deviceAspect);
    if (scale < 1.0) scale = 1.0; // Гарантираме запълване на дисплея без прекомерен кроп

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          Positioned.fill(
            child: ClipRect(
              child: Transform.scale(
                scale: scale, // Вече няма разтегляне и няма огромен мащаб!
                child: Center(child: CameraPreview(_cameraController!)),
              ),
            ),
          ),
          Positioned.fill(
            child: CustomPaint(
              painter: FaceOverlayPainter(borderColor: _stepColor),
            ),
          ),
          Positioned(
            top: 60, left: 24, right: 24,
            child: Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: Colors.black.withValues(alpha: 0.8),
                borderRadius: UiThemeTokens.borderRadius,
              ),
              child: Column(
                children: [
                  Text(
                    _instructionText,
                    textAlign: TextAlign.center,
                    style: UiThemeTokens.getSansFont(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold),
                  ),
                  if (_isProcessing) ...[
                    const SizedBox(height: 14),
                    const LinearProgressIndicator(color: Colors.white),
                  ]
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}