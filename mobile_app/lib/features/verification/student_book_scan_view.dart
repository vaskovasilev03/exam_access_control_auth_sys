import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'package:mobile_app/core/theme_tokens.dart';
import 'package:mobile_app/features/verification/widgets/document_frame_painter.dart';

class StudentBookScanView extends StatefulWidget {
  final void Function(XFile photo) onPhotoCaptured;
  final VoidCallback onBack;

  const StudentBookScanView({
    super.key,
    required this.onPhotoCaptured,
    required this.onBack,
  });

  @override
  State<StudentBookScanView> createState() => _StudentBookScanViewState();
}

class _StudentBookScanViewState extends State<StudentBookScanView> {
  CameraController? _cameraController;
  List<CameraDescription> _availableCameras = [];
  int _selectedCameraIndex = 0;
  bool _isInitializing = true;
  bool _isCapturing = false;
  bool _isFlashOn = false;
  bool _showInstructions = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _initCamera();
  }

  Future<void> _initCamera() async {
    // Settling delay so previous camera controller can fully release Android Camera2 HAL
    await Future.delayed(const Duration(milliseconds: 250));
    if (!mounted) return;

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

      // Default to rear camera for document scanning
      int backIndex = _availableCameras.indexWhere(
        (cam) => cam.lensDirection == CameraLensDirection.back,
      );
      _selectedCameraIndex = backIndex != -1 ? backIndex : 0;

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
      await oldController.dispose();
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
        _isFlashOn = false;
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

  Future<void> _toggleFlash() async {
    if (_cameraController == null || !_cameraController!.value.isInitialized) return;
    try {
      final newMode = _isFlashOn ? FlashMode.off : FlashMode.torch;
      await _cameraController!.setFlashMode(newMode);
      if (mounted) {
        setState(() => _isFlashOn = !_isFlashOn);
      }
    } catch (e) {
      debugPrint('Flash mode error: $e');
    }
  }

  Future<void> _switchCamera() async {
    if (_availableCameras.length < 2 || _isCapturing) return;
    setState(() => _isInitializing = true);
    _selectedCameraIndex = (_selectedCameraIndex + 1) % _availableCameras.length;
    await _setupController(_availableCameras[_selectedCameraIndex]);
  }

  Future<void> _captureDocument() async {
    if (_cameraController == null ||
        !_cameraController!.value.isInitialized ||
        _isCapturing) {
      return;
    }

    setState(() => _isCapturing = true);

    try {
      final XFile photo = await _cameraController!.takePicture();

      if (!mounted) return;
      widget.onPhotoCaptured(photo);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Грешка при заснемане: $e'),
          backgroundColor: UiThemeTokens.destructive,
        ),
      );
      if (mounted) {
        setState(() => _isCapturing = false);
      }
    }
  }

  Future<void> _handleBack() async {
    if (_cameraController != null) {
      if (_isFlashOn) {
        try {
          await _cameraController!.setFlashMode(FlashMode.off);
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
    if (_isFlashOn && _cameraController != null) {
      _cameraController?.setFlashMode(FlashMode.off);
    }
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
                  Icons.menu_book_rounded,
                  size: 36,
                  color: UiThemeTokens.foreground,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                'Инструкции за книжка',
                style: UiThemeTokens.getSansFont(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 16),
              _buildInstructionRow(
                icon: Icons.auto_stories_rounded,
                text: 'Отворете студентската книжка на първа страница',
              ),
              const SizedBox(height: 12),
              _buildInstructionRow(
                icon: Icons.crop_free_rounded,
                text: 'Позиционирайте вертикалната страница в рамката (снимка горе вляво, печат долу вдясно)',
              ),
              const SizedBox(height: 12),
              _buildInstructionRow(
                icon: Icons.verified_rounded,
                text: 'Уверете се, че имената, факултетният номер и печатът са добре осветени и четливи',
              ),
              const SizedBox(height: 24),
              Row(
                children: [
                  Expanded(
                    child: SizedBox(
                      height: 44,
                      child: OutlinedButton(
                        onPressed: _handleBack,
                        style: OutlinedButton.styleFrom(
                          side: const BorderSide(color: UiThemeTokens.border),
                          shape: RoundedRectangleBorder(
                            borderRadius: UiThemeTokens.borderRadius,
                          ),
                        ),
                        child: Text(
                          'Назад',
                          style: UiThemeTokens.getSansFont(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: UiThemeTokens.foreground,
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: SizedBox(
                      height: 44,
                      child: ElevatedButton(
                        onPressed: () {
                          setState(() => _showInstructions = false);
                        },
                        style: ElevatedButton.styleFrom(
                          backgroundColor: UiThemeTokens.primary,
                          foregroundColor: UiThemeTokens.primaryForeground,
                          elevation: 0,
                          shape: RoundedRectangleBorder(
                            borderRadius: UiThemeTokens.borderRadius,
                          ),
                        ),
                        child: Text(
                          'Продължи',
                          style: UiThemeTokens.getSansFont(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: UiThemeTokens.primaryForeground,
                          ),
                        ),
                      ),
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

    final previewSize = _cameraController!.value.previewSize;
    final double previewWidth = previewSize != null ? previewSize.height : 1080;
    final double previewHeight = previewSize != null ? previewSize.width : 1920;

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          // Camera Preview (High-definition 1:1 sensor feed)
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

          // Document Frame Overlay
          Positioned.fill(
            child: CustomPaint(
              painter: DocumentFramePainter(
                borderColor: Colors.white.withValues(alpha: 0.90),
              ),
            ),
          ),

          // Top Navigation & Instruction Header
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
                              horizontal: 10,
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
                              'СТЪПКА 3 ОТ 4 • КНИЖКА',
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
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            icon: Icon(
                              _isFlashOn
                                  ? Icons.flash_on_rounded
                                  : Icons.flash_off_rounded,
                              color: _isFlashOn ? Colors.amber : Colors.white,
                            ),
                            onPressed: _toggleFlash,
                          ),
                          if (_availableCameras.length > 1)
                            IconButton(
                              icon: const Icon(
                                Icons.cameraswitch_outlined,
                                color: Colors.white,
                              ),
                              onPressed: _switchCamera,
                            ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 8,
                    ),
                    decoration: BoxDecoration(
                      color: Colors.black.withValues(alpha: 0.65),
                      borderRadius: BorderRadius.circular(24),
                      border: Border.all(
                        color: Colors.white.withValues(alpha: 0.2),
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.crop_free_rounded,
                          color: Colors.white70,
                          size: 16,
                        ),
                        const SizedBox(width: 8),
                        Text(
                          'Позиционирайте страницата в рамката',
                          style: UiThemeTokens.getSansFont(
                            color: Colors.white,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),

          // Bottom Shutter Controls
          Positioned(
            bottom: 36,
            left: 0,
            right: 0,
            child: SafeArea(
              child: Center(
                child: GestureDetector(
                  onTap: _isCapturing ? null : _captureDocument,
                  child: Container(
                    width: 76,
                    height: 76,
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 4),
                    ),
                    child: Container(
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: _isCapturing
                            ? UiThemeTokens.mutedForeground
                            : Colors.white,
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
                          : const Icon(
                              Icons.camera_alt_outlined,
                              color: Colors.black87,
                              size: 28,
                            ),
                    ),
                  ),
                ),
              ),
            ),
          ),

          // Instructions Modal Popup
          if (_showInstructions) Positioned.fill(child: _buildInstructionsOverlay()),
        ],
      ),
    );
  }
}

