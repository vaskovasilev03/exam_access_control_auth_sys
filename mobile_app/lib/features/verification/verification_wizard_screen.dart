import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'package:mobile_app/core/api_client.dart';
import 'package:mobile_app/core/theme_tokens.dart';
import 'package:mobile_app/features/verification/gdpr_consent_view.dart';
import 'package:mobile_app/features/verification/face_scan_view.dart';
import 'package:mobile_app/features/verification/student_book_scan_view.dart';
import 'package:mobile_app/features/verification/dossier_review_view.dart';

class VerificationWizardScreen extends StatefulWidget {
  final ApiClient apiClient;

  const VerificationWizardScreen({super.key, required this.apiClient});

  @override
  State<VerificationWizardScreen> createState() =>
      _VerificationWizardScreenState();
}

class _VerificationWizardScreenState extends State<VerificationWizardScreen> {
  int _currentStep = 0; // 0: GDPR, 1: Face, 2: Book, 3: Review
  XFile? _facePhoto;
  XFile? _studentBookPhoto;

  void _onConsentGranted() {
    setState(() {
      _currentStep = 1;
    });
  }

  void _onFaceCaptured(XFile photo) {
    setState(() {
      _facePhoto = photo;
      // If student book photo is already present (e.g. during retake), return straight to review
      if (_studentBookPhoto != null) {
        _currentStep = 3;
      } else {
        _currentStep = 2;
      }
    });
  }

  void _onBookCaptured(XFile photo) {
    setState(() {
      _studentBookPhoto = photo;
      _currentStep = 3;
    });
  }

  void _retakeFace() {
    setState(() {
      _currentStep = 1;
    });
  }

  void _retakeBook() {
    setState(() {
      _currentStep = 2;
    });
  }

  void _onUploadSuccess() {
    Navigator.pop(context, true);
  }

  Future<bool> _onWillPop() async {
    if (_currentStep == 0) return true;

    final shouldExit = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: UiThemeTokens.background,
        shape: RoundedRectangleBorder(
          borderRadius: UiThemeTokens.borderRadius,
          side: const BorderSide(color: UiThemeTokens.border),
        ),
        title: Row(
          children: [
            const Icon(
              Icons.warning_amber_rounded,
              color: UiThemeTokens.mutedForeground,
              size: 20,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                'Прекъсване на процеса',
                style: UiThemeTokens.getSansFont(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
        content: Text(
          'Сигурни ли сте, че искате да напуснете верификацията? Заснетите кадри няма да бъдат запазени.',
          style: UiThemeTokens.getSansFont(
            fontSize: 13,
            color: UiThemeTokens.foreground,
          ),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        actions: [
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 44,
                  child: OutlinedButton(
                    onPressed: () => Navigator.pop(ctx, false),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: UiThemeTokens.border),
                      shape: RoundedRectangleBorder(
                        borderRadius: UiThemeTokens.borderRadius,
                      ),
                    ),
                    child: Text(
                      'Остани',
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
                    onPressed: () => Navigator.pop(ctx, true),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: UiThemeTokens.destructive,
                      foregroundColor: Colors.white,
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: UiThemeTokens.borderRadius,
                      ),
                    ),
                    child: Text(
                      'Изход',
                      style: UiThemeTokens.getSansFont(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );

    return shouldExit ?? false;
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _currentStep == 0,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;
        final shouldExit = await _onWillPop();
        if (shouldExit && context.mounted) {
          Navigator.pop(context);
        }
      },
      child: _buildCurrentStepView(),
    );
  }

  Widget _buildCurrentStepView() {
    switch (_currentStep) {
      case 0:
        return GdprConsentView(
          key: const ValueKey('gdpr_step'),
          onConsentGranted: _onConsentGranted,
        );
      case 1:
        return FaceScanView(
          key: const ValueKey('face_step'),
          onPhotoCaptured: _onFaceCaptured,
          onBack: () => setState(() => _currentStep = _studentBookPhoto != null ? 3 : 0),
        );
      case 2:
        return StudentBookScanView(
          key: const ValueKey('book_step'),
          onPhotoCaptured: _onBookCaptured,
          onBack: () => setState(() => _currentStep = _facePhoto != null && _studentBookPhoto != null ? 3 : 1),
        );
      case 3:
        if (_facePhoto != null && _studentBookPhoto != null) {
          return DossierReviewView(
            key: const ValueKey('review_step'),
            apiClient: widget.apiClient,
            facePhoto: _facePhoto!,
            studentBookPhoto: _studentBookPhoto!,
            onRetakeFace: _retakeFace,
            onRetakeBook: _retakeBook,
            onUploadSuccess: _onUploadSuccess,
          );
        }
        return const SizedBox.shrink();
      default:
        return const SizedBox.shrink();
    }
  }
}
