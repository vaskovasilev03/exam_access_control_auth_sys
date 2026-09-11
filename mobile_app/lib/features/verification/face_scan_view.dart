import 'dart:async';
import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'package:mobile_app/core/theme_tokens.dart';
import 'package:mobile_app/features/verification/widgets/face_hud_painter.dart';
import 'package:mobile_app/features/verification/services/face_detector_service.dart';

enum ScanFacePhase {
  searching,
  found,
  countdown,
  completed,
}

class FaceScanView extends StatefulWidget {
  final void Function(XFile photo) onPhotoCaptured;
  final VoidCallback onBack;

  const FaceScanView({
    super.key,
    required this.onPhotoCaptured,
    required this.onBack,
  });

  @override
  State<FaceScanView> createState() => _FaceScanViewState();
}

class _FaceScanViewState extends State<FaceScanView> {
  CameraController? _cameraController;
  List<CameraDescription> _availableCameras = [];
  int _selectedCameraIndex = 0;
  bool _isInitializing = true;
  bool _isCapturing = false;
  String? _errorMessage;

  // Interactive scan state
  bool _showInstructions = true;
  bool _isScanning = false;
  bool _isFaceDetected = false;
  ScanFacePhase _facePhase = ScanFacePhase.searching;
  int _countdown = 3;
  Timer? _countdownTimer;
  Timer? _foundTransitionTimer;
  int _consecutiveNoFace = 0;
  String? _feedbackMessage;

  // Frame throttling and async execution flags
  bool _isProcessingFrame = false;
  int _lastProcessTime = 0;

  final FaceDetectorService _faceDetectorService = FaceDetectorService();

  @override
  void initState() {
    super.initState();
    _initScanner();
  }

  Future<void> _initScanner() async {
    await _faceDetectorService.initialize();
    if (mounted) {
      await _initCamera();
    }
  }

  Future<void> _initCamera() async {
    try {
      _availableCameras = await availableCameras();
      if (_availableCameras.isEmpty) {
        if (!mounted) return;
        setState(() {
          _errorMessage = 'Не е намерена активна камера на устройството.';
          _isInitializing = false;
        });
        return;
      }

      // Default to front camera for face capture
      int frontIndex = _availableCameras.indexWhere(
        (cam) => cam.lensDirection == CameraLensDirection.front,
      );
      _selectedCameraIndex = frontIndex != -1 ? frontIndex : 0;

      await _setupController(_availableCameras[_selectedCameraIndex]);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Грешка при зареждане на камерата: $e';
        _isInitializing = false;
      });
    }
  }

  Future<void> _setupController(CameraDescription camera) async {
    final oldController = _cameraController;
    if (oldController != null) {
      _cameraController = null;
      if (oldController.value.isStreamingImages) {
        try {
          await oldController.stopImageStream();
        } catch (_) {}
      }
      await oldController.dispose();
      // Allow Camera2 HAL a short breath to fully release sensor
      await Future.delayed(const Duration(milliseconds: 100));
    }

    final controller = CameraController(
      camera,
      ResolutionPreset.medium,
      enableAudio: false,
    );

    try {
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() {
        _cameraController = controller;
        _isInitializing = false;
        _errorMessage = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Неуспешна инициализация на сензора: $e';
        _isInitializing = false;
      });
    }
  }

  Future<void> _switchCamera() async {
    if (_availableCameras.length < 2 || _isCapturing || _isScanning) return;
    setState(() => _isInitializing = true);
    _selectedCameraIndex = (_selectedCameraIndex + 1) % _availableCameras.length;
    await _setupController(_availableCameras[_selectedCameraIndex]);
  }

  void _onShutterTap() {
    if (_isCapturing || _facePhase == ScanFacePhase.completed) return;
    if (_isScanning) {
      _cancelScanning(userCancelled: true);
    } else {
      _startScanning();
    }
  }

  void _startScanning() async {
    if (_cameraController == null ||
        !_cameraController!.value.isInitialized ||
        _isCapturing ||
        _showInstructions ||
        _isScanning) {
      return;
    }

    _foundTransitionTimer?.cancel();
    _countdownTimer?.cancel();
    _isProcessingFrame = false;
    _lastProcessTime = 0;

    setState(() {
      _isScanning = true;
      _feedbackMessage = null;
      _countdown = 3;
      _facePhase = ScanFacePhase.searching;
      _isFaceDetected = false;
      _consecutiveNoFace = 0;
    });

    try {
      if (!_cameraController!.value.isStreamingImages) {
        await _cameraController!.startImageStream((CameraImage image) {
          if (!_isScanning || _isCapturing || _facePhase == ScanFacePhase.completed) return;

          final now = DateTime.now().millisecondsSinceEpoch;
          // Ultra-fast check: if under 350ms or previous inference is running, exit immediately (< 0.005ms)
          if (_isProcessingFrame || (now - _lastProcessTime < 350)) {
            return;
          }

          _isProcessingFrame = true;
          _lastProcessTime = now;

          // Asynchronous microtask execution guarantees the camera callback returns immediately
          // keeping the camera feed running at a silky smooth 60 FPS
          Future.microtask(() {
            try {
              final faceFound = _faceDetectorService.detectFace(image);
              if (faceFound == null || !mounted || !_isScanning || _isCapturing || _facePhase == ScanFacePhase.completed) return;

              if (faceFound) {
                _consecutiveNoFace = 0;
                if (_facePhase == ScanFacePhase.searching) {
                  _onFaceFound();
                }
              } else {
                _consecutiveNoFace++;
                // During active countdown, allow 4 frames (~1.4s) tolerance for natural blinks/micro-movements
                final int threshold = _facePhase == ScanFacePhase.countdown ? 4 : 3;
                if (_consecutiveNoFace >= threshold) {
                  _onFaceLost();
                }
              }
            } finally {
              _isProcessingFrame = false;
            }
          });
        });
      }
    } catch (e) {
      debugPrint('Stream start error: $e');
      // Fallback: If streaming is not supported on this platform, start countdown directly
      if (mounted) {
        _onFaceFound();
      }
    }
  }

  void _onFaceFound() {
    if (!mounted || !_isScanning || _isCapturing || _facePhase == ScanFacePhase.completed) {
      return;
    }

    setState(() {
      _isFaceDetected = true;
      _facePhase = ScanFacePhase.found;
    });

    _foundTransitionTimer?.cancel();
    _foundTransitionTimer = Timer(const Duration(milliseconds: 500), () {
      if (!mounted || !_isScanning || _isCapturing) return;

      setState(() {
        _countdown = 3;
        _facePhase = ScanFacePhase.countdown;
      });

      _startCountdown();
    });
  }

  void _onFaceLost() {
    if (!mounted || !_isScanning || _isCapturing || _facePhase == ScanFacePhase.completed) {
      return;
    }

    if (_facePhase != ScanFacePhase.searching) {
      _foundTransitionTimer?.cancel();
      _countdownTimer?.cancel();
      _countdownTimer = null;

      setState(() {
        _isFaceDetected = false;
        _facePhase = ScanFacePhase.searching;
        _countdown = 3;
        _feedbackMessage = 'Лицето не е центрирано. Позиционирайте в овала.';
      });
    }
  }

  void _cancelScanning({bool userCancelled = false}) async {
    if (_isCapturing || _facePhase == ScanFacePhase.completed) return;

    _foundTransitionTimer?.cancel();
    _countdownTimer?.cancel();
    _countdownTimer = null;
    _consecutiveNoFace = 0;
    _isProcessingFrame = false;

    if (_cameraController != null && _cameraController!.value.isStreamingImages) {
      try {
        await _cameraController!.stopImageStream();
      } catch (_) {}
    }

    if (mounted) {
      setState(() {
        _isScanning = false;
        _isFaceDetected = false;
        _facePhase = ScanFacePhase.searching;
        _countdown = 3;
        if (userCancelled) {
          _feedbackMessage = 'Операцията е прекратена';
        }
      });
    }
  }

  void _startCountdown() {
    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) async {
      if (!mounted || !_isScanning || _facePhase != ScanFacePhase.countdown) {
        timer.cancel();
        return;
      }

      if (_countdown > 1) {
        setState(() {
          _countdown--;
        });
      } else {
        // Countdown reached 0 (3 seconds completed)
        timer.cancel();
        _countdownTimer = null;

        // Verify face is still detected before completing (allow micro-blinks)
        if (!_isFaceDetected || _consecutiveNoFace >= 2) {
          _onFaceLost();
          return;
        }

        // Stop camera stream immediately to avoid processing frames during picture capture
        if (_cameraController != null && _cameraController!.value.isStreamingImages) {
          try {
            await _cameraController!.stopImageStream();
          } catch (_) {}
        }

        setState(() {
          _countdown = 0;
          _facePhase = ScanFacePhase.completed;
        });

        // Brief delay so user sees 'Готово!' with green check before camera snap
        await Future.delayed(const Duration(milliseconds: 300));
        if (mounted && _isScanning) {
          await _captureAndComplete();
        }
      }
    });
  }

  Future<void> _captureAndComplete() async {
    if (_cameraController == null || !_cameraController!.value.isInitialized || _isCapturing) {
      return;
    }

    setState(() => _isCapturing = true);

    try {
      if (_cameraController != null && _cameraController!.value.isStreamingImages) {
        try {
          await _cameraController!.stopImageStream();
        } catch (_) {}
      }

      // Small pause to allow camera session buffer to settle
      await Future.delayed(const Duration(milliseconds: 100));

      if (_cameraController == null || !_cameraController!.value.isInitialized) return;

      final XFile photo = await _cameraController!.takePicture();

      if (!mounted) return;
      widget.onPhotoCaptured(photo);
    } catch (e) {
      debugPrint('Capture error: $e');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Грешка при заснемане: $e'),
          backgroundColor: UiThemeTokens.destructive,
        ),
      );
      setState(() {
        _isCapturing = false;
        _isScanning = false;
        _facePhase = ScanFacePhase.searching;
        _feedbackMessage = 'Грешка при заснемане. Опитайте отново.';
      });
    }
  }

  Future<void> _handleBack() async {
    _foundTransitionTimer?.cancel();
    _countdownTimer?.cancel();
    _isProcessingFrame = false;

    if (_cameraController != null) {
      if (_cameraController!.value.isStreamingImages) {
        try {
          await _cameraController!.stopImageStream();
        } catch (_) {}
      }
      final controller = _cameraController;
      _cameraController = null;
      await controller?.dispose();
      await Future.delayed(const Duration(milliseconds: 80));
    }

    widget.onBack();
  }

  @override
  void dispose() {
    _foundTransitionTimer?.cancel();
    _countdownTimer?.cancel();
    _cameraController?.dispose();
    super.dispose();
  }

  Widget _buildInstructionsOverlay() {
    return Container(
      color: Colors.black.withValues(alpha: 0.75),
      child: Center(
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 28.0),
          padding: const EdgeInsets.all(24.0),
          decoration: BoxDecoration(
            color: UiThemeTokens.background,
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.35),
                blurRadius: 20,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: UiThemeTokens.input,
                  shape: BoxShape.circle,
                ),
                child: const Icon(
                  Icons.camera_front_rounded,
                  size: 36,
                  color: UiThemeTokens.foreground,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                'Инструкции за заснемане',
                style: UiThemeTokens.getSansFont(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 16),
              _buildInstructionRow(
                icon: Icons.face_rounded,
                text: 'Позиционирайте лицето си в овала',
              ),
              const SizedBox(height: 12),
              _buildInstructionRow(
                icon: Icons.wb_sunny_outlined,
                text: 'Уверете се, че сте на добре осветено място',
              ),
              const SizedBox(height: 12),
              _buildInstructionRow(
                icon: Icons.touch_app_outlined,
                text: 'Когато сте готови, натиснете бутона долу за стартиране на 5 сек. проверка',
              ),
              const SizedBox(height: 24),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _handleBack,
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        side: const BorderSide(color: UiThemeTokens.border),
                        shape: RoundedRectangleBorder(
                          borderRadius: UiThemeTokens.borderRadius,
                        ),
                      ),
                      child: const Text('Назад'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: ElevatedButton(
                      onPressed: () {
                        setState(() => _showInstructions = false);
                      },
                      style: ElevatedButton.styleFrom(
                        backgroundColor: UiThemeTokens.primary,
                        foregroundColor: UiThemeTokens.primaryForeground,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        shape: RoundedRectangleBorder(
                          borderRadius: UiThemeTokens.borderRadius,
                        ),
                      ),
                      child: const Text('Продължи'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildInstructionRow({required IconData icon, required String text}) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 18, color: UiThemeTokens.primary),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            text,
            style: UiThemeTokens.getSansFont(
              fontSize: 13,
              color: UiThemeTokens.foreground,
              height: 1.35,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildStatusIndicator() {
    Color badgeBg;
    Color textColor = Colors.white;
    Widget iconWidget;
    String statusText;

    if (_isScanning) {
      switch (_facePhase) {
        case ScanFacePhase.searching:
          badgeBg = Colors.black.withValues(alpha: 0.75);
          iconWidget = const SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
          );
          statusText = 'Търсене на лице...';
          break;
        case ScanFacePhase.found:
          badgeBg = Colors.green.shade800.withValues(alpha: 0.85);
          iconWidget = const Icon(Icons.check_circle_rounded, size: 16, color: Colors.white);
          statusText = 'Намерено!';
          break;
        case ScanFacePhase.countdown:
          badgeBg = Colors.green.shade900.withValues(alpha: 0.85);
          iconWidget = const Icon(Icons.timer_outlined, size: 16, color: Colors.greenAccent);
          statusText = 'Стойте неподвижно!... $_countdown';
          break;
        case ScanFacePhase.completed:
          badgeBg = Colors.green.shade800.withValues(alpha: 0.90);
          iconWidget = const Icon(Icons.check_circle_rounded, size: 16, color: Colors.white);
          statusText = 'Готово!';
          break;
      }
    } else {
      if (_feedbackMessage != null) {
        badgeBg = UiThemeTokens.destructive.withValues(alpha: 0.90);
        iconWidget = const Icon(Icons.error_outline_rounded, size: 16, color: Colors.white);
        statusText = _feedbackMessage!;
      } else {
        badgeBg = Colors.black.withValues(alpha: 0.65);
        iconWidget = const Icon(Icons.center_focus_strong_outlined, size: 16, color: Colors.white70);
        statusText = 'Позиционирайте лицето в овала';
      }
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: badgeBg,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: _isFaceDetected ? Colors.greenAccent.withValues(alpha: 0.4) : Colors.white24,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          iconWidget,
          const SizedBox(width: 8),
          Text(
            statusText,
            style: UiThemeTokens.getSansFont(
              color: textColor,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_errorMessage != null) {
      return Scaffold(
        backgroundColor: Colors.black,
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          elevation: 0,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back, color: Colors.white),
            onPressed: _handleBack,
          ),
        ),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.error_outline_rounded,
                  color: UiThemeTokens.destructive,
                  size: 48,
                ),
                const SizedBox(height: 16),
                Text(
                  _errorMessage!,
                  textAlign: TextAlign.center,
                  style: UiThemeTokens.getSansFont(
                    color: Colors.white,
                    fontSize: 14,
                  ),
                ),
                const SizedBox(height: 20),
                ElevatedButton(
                  onPressed: () {
                    setState(() => _isInitializing = true);
                    _initCamera();
                  },
                  child: const Text('Опитай отново'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    if (_isInitializing ||
        _cameraController == null ||
        !_cameraController!.value.isInitialized) {
      return const Scaffold(
        backgroundColor: Colors.black,
        body: Center(
          child: CircularProgressIndicator(color: Colors.white),
        ),
      );
    }

    final countdownProgress = _facePhase == ScanFacePhase.countdown
        ? (3 - _countdown) / 3.0
        : (_facePhase == ScanFacePhase.completed ? 1.0 : 0.0);

    final previewSize = _cameraController!.value.previewSize;
    final double previewWidth = previewSize != null ? previewSize.height : 1080;
    final double previewHeight = previewSize != null ? previewSize.width : 1920;

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          // Live Camera Preview (High-definition 1:1 sensor feed without digital scale blur)
          Positioned.fill(
            child: ClipRect(
              child: SizedBox.expand(
                child: FittedBox(
                  fit: BoxFit.cover,
                  child: SizedBox(
                    width: previewWidth,
                    height: previewHeight,
                    child: CameraPreview(_cameraController!),
                  ),
                ),
              ),
            ),
          ),

          // Vector Biometric HUD Overlay (Simple oval, no side darkening)
          Positioned.fill(
            child: CustomPaint(
              painter: FaceHudPainter(
                borderColor: _isFaceDetected ? Colors.greenAccent : Colors.white.withValues(alpha: 0.80),
                isFaceDetected: _isFaceDetected,
                countdownProgress: _isScanning && _isFaceDetected ? countdownProgress : 0.0,
              ),
            ),
          ),

          // Top Header (Safe area)
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
              child: Column(
                children: [
                  Row(
                    children: [
                      IconButton(
                        icon: const Icon(Icons.arrow_back, color: Colors.white),
                        onPressed: _handleBack,
                      ),
                      Expanded(
                        child: Center(
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 6,
                            ),
                            decoration: BoxDecoration(
                              color: Colors.black.withValues(alpha: 0.65),
                              borderRadius: BorderRadius.circular(16),
                              border: Border.all(
                                color: Colors.white.withValues(alpha: 0.2),
                              ),
                            ),
                            child: Text(
                              'СТЪПКА 2 ОТ 4 • ЛИЦЕ',
                              overflow: TextOverflow.ellipsis,
                              style: UiThemeTokens.getSansFont(
                                color: Colors.white,
                                fontSize: 11,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                        ),
                      ),
                      if (_availableCameras.length > 1)
                        IconButton(
                          icon: const Icon(
                            Icons.cameraswitch_outlined,
                            color: Colors.white,
                          ),
                          onPressed: _switchCamera,
                        )
                      else
                        const SizedBox(width: 48),
                    ],
                  ),
                  const SizedBox(height: 14),
                  // Changing Status Banner above the oval
                  _buildStatusIndicator(),
                ],
              ),
            ),
          ),

          // Bottom Shutter Controls with Single-Tap and Red Cancel 'X'
          Positioned(
            bottom: 36,
            left: 0,
            right: 0,
            child: Column(
              children: [
                GestureDetector(
                  onTap: _onShutterTap,
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 250),
                    curve: Curves.easeInOut,
                    width: 80,
                    height: 80,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: _isCapturing || _facePhase == ScanFacePhase.completed
                            ? Colors.greenAccent
                            : (_isScanning
                                ? UiThemeTokens.destructive
                                : (_isFaceDetected ? Colors.greenAccent : Colors.white)),
                        width: 3.5,
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: _isScanning && _facePhase != ScanFacePhase.completed
                              ? UiThemeTokens.destructive.withValues(alpha: 0.45)
                              : (_isFaceDetected
                                  ? Colors.greenAccent.withValues(alpha: 0.4)
                                  : Colors.black.withValues(alpha: 0.3)),
                          blurRadius: 16,
                          spreadRadius: 2,
                        ),
                      ],
                    ),
                    child: Center(
                      child: Container(
                        width: 64,
                        height: 64,
                        decoration: BoxDecoration(
                          color: _isCapturing || _facePhase == ScanFacePhase.completed
                              ? Colors.greenAccent
                              : (_isScanning ? UiThemeTokens.destructive : Colors.white),
                          shape: BoxShape.circle,
                        ),
                        child: _isCapturing
                            ? const Center(
                                child: SizedBox(
                                  width: 24,
                                  height: 24,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2.5,
                                    color: Colors.black,
                                  ),
                                ),
                              )
                            : Icon(
                                _facePhase == ScanFacePhase.completed
                                    ? Icons.check_rounded
                                    : (_isScanning
                                        ? Icons.close_rounded
                                        : Icons.camera_alt_outlined),
                                color: _isScanning && _facePhase != ScanFacePhase.completed
                                    ? Colors.white
                                    : Colors.black87,
                                size: _isScanning ? 32 : 28,
                              ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  _isScanning
                      ? (_facePhase == ScanFacePhase.completed ? 'Заснемане...' : 'Натиснете за отказ')
                      : 'Натиснете за стартиране',
                  style: UiThemeTokens.getSansFont(
                    color: _isScanning && _facePhase != ScanFacePhase.completed
                        ? Colors.redAccent.shade100
                        : Colors.white70,
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),

          // Instructions Modal Popup (Frame 2 in sketch)
          if (_showInstructions) Positioned.fill(child: _buildInstructionsOverlay()),
        ],
      ),
    );
  }
}
