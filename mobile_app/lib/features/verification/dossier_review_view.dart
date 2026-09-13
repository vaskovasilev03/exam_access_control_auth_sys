import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'package:dio/dio.dart';
import 'package:mobile_app/core/api_client.dart';
import 'package:mobile_app/core/theme_tokens.dart';

class DossierReviewView extends StatefulWidget {
  final ApiClient apiClient;
  final XFile facePhoto;
  final XFile studentBookPhoto;
  final VoidCallback onRetakeFace;
  final VoidCallback onRetakeBook;
  final VoidCallback onUploadSuccess;

  const DossierReviewView({
    super.key,
    required this.apiClient,
    required this.facePhoto,
    required this.studentBookPhoto,
    required this.onRetakeFace,
    required this.onRetakeBook,
    required this.onUploadSuccess,
  });

  @override
  State<DossierReviewView> createState() => _DossierReviewViewState();
}

class _DossierReviewViewState extends State<DossierReviewView> {
  bool _isUploading = false;
  String _uploadStatusText = 'Обработка на файловете...';

  Future<void> _submitDossier() async {
    setState(() {
      _isUploading = true;
      _uploadStatusText = 'Изпращане на документи и биометрична проверка...';
    });

    try {
      final faceBytes = await widget.facePhoto.readAsBytes();
      final bookBytes = await widget.studentBookPhoto.readAsBytes();

      final formData = FormData.fromMap({
        'face_photo': MultipartFile.fromBytes(
          faceBytes,
          filename: 'face_photo.jpg',
        ),
        'student_book_photo': MultipartFile.fromBytes(
          bookBytes,
          filename: 'student_book.jpg',
        ),
      });

      final response = await widget.apiClient.dio.post(
        '/students/upload-verification-docs',
        data: formData,
      );

      if (!mounted) return;

      if (response.statusCode == 200) {
        final data = response.data;
        final String message = data is Map && data['message'] != null
            ? data['message'] as String
            : 'Документите са качени успешно и очакват преглед от администратор.';

        _showSuccessDialog(message);
      }
    } on DioException catch (e) {
      if (!mounted) return;
      setState(() => _isUploading = false);

      String errorDetail = 'Възникна неочаквана мрежова грешка при качването.';
      if (e.response?.data is Map && e.response?.data['detail'] != null) {
        errorDetail = e.response!.data['detail'].toString();
      }

      _showErrorDialog(errorDetail);
    } catch (e) {
      if (!mounted) return;
      setState(() => _isUploading = false);
      _showErrorDialog('Грешка при обработката на файловете: $e');
    }
  }

  void _showErrorDialog(String detail) {
    final bool isLivenessFailure = detail.contains('Liveness') ||
        detail.contains('автентичност') ||
        detail.contains('екран') ||
        detail.contains('маска');

    showDialog(
      context: context,
      barrierDismissible: false,
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
              color: UiThemeTokens.destructive,
              size: 22,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                isLivenessFailure
                    ? 'Неуспешна проверка за автентичност'
                    : 'Грешка при верификацията',
                style: UiThemeTokens.getSansFont(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
        content: Text(
          detail,
          style: UiThemeTokens.getSansFont(
            fontSize: 13,
            color: UiThemeTokens.foreground,
          ),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        actions: [
          if (isLivenessFailure)
            Row(
              children: [
                Expanded(
                  child: SizedBox(
                    height: 44,
                    child: OutlinedButton(
                      onPressed: () {
                        Navigator.pop(ctx);
                        widget.onRetakeFace();
                      },
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: UiThemeTokens.border),
                        shape: RoundedRectangleBorder(
                          borderRadius: UiThemeTokens.borderRadius,
                        ),
                      ),
                      child: Text(
                        'Снимай отново',
                        style: UiThemeTokens.getSansFont(
                          fontSize: 13,
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
                      onPressed: () => Navigator.pop(ctx),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: UiThemeTokens.primary,
                        foregroundColor: UiThemeTokens.primaryForeground,
                        elevation: 0,
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        minimumSize: const Size(0, 44),
                        shape: RoundedRectangleBorder(
                          borderRadius: UiThemeTokens.borderRadius,
                        ),
                      ),
                      child: Text(
                        'Разбрах',
                        style: UiThemeTokens.getSansFont(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: UiThemeTokens.primaryForeground,
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            )
          else
            SizedBox(
              width: double.infinity,
              height: 44,
              child: ElevatedButton(
                onPressed: () => Navigator.pop(ctx),
                style: ElevatedButton.styleFrom(
                  backgroundColor: UiThemeTokens.primary,
                  foregroundColor: UiThemeTokens.primaryForeground,
                  elevation: 0,
                  shape: RoundedRectangleBorder(
                    borderRadius: UiThemeTokens.borderRadius,
                  ),
                ),
                child: Text(
                  'Разбрах',
                  style: UiThemeTokens.getSansFont(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: UiThemeTokens.primaryForeground,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  void _showSuccessDialog(String message) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: UiThemeTokens.background,
        shape: RoundedRectangleBorder(
          borderRadius: UiThemeTokens.borderRadius,
          side: const BorderSide(color: UiThemeTokens.border),
        ),
        title: Row(
          children: [
            const Icon(
              Icons.check_circle_rounded,
              color: Colors.green,
              size: 22,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                'Успешно изпращане',
                style: UiThemeTokens.getSansFont(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
        content: Text(
          message,
          style: UiThemeTokens.getSansFont(
            fontSize: 13,
            color: UiThemeTokens.foreground,
          ),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        actions: [
          SizedBox(
            width: double.infinity,
            height: 44,
            child: ElevatedButton(
              onPressed: () {
                Navigator.pop(ctx);
                widget.onUploadSuccess();
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: UiThemeTokens.primary,
                foregroundColor: UiThemeTokens.primaryForeground,
                elevation: 0,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                minimumSize: const Size(0, 44),
                shape: RoundedRectangleBorder(
                  borderRadius: UiThemeTokens.borderRadius,
                ),
              ),
              child: Text(
                'Към таблото',
                style: UiThemeTokens.getSansFont(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: UiThemeTokens.primaryForeground,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPhotoCard({
    required String title,
    required String badgeLabel,
    required XFile photoFile,
    required VoidCallback onRetake,
    required double aspectRatio,
    Alignment alignment = Alignment.center,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: UiThemeTokens.card,
        borderRadius: UiThemeTokens.borderRadius,
        border: Border.all(color: UiThemeTokens.border),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                title,
                style: UiThemeTokens.getSansFont(
                  fontSize: 14,
                  fontWeight: FontWeight.bold,
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: UiThemeTokens.input,
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: UiThemeTokens.border),
                ),
                child: Text(
                  badgeLabel,
                  style: UiThemeTokens.getSansFont(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: UiThemeTokens.mutedForeground,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: AspectRatio(
              aspectRatio: aspectRatio,
              child: FutureBuilder<Uint8List>(
                future: photoFile.readAsBytes(),
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting) {
                    return Container(
                      color: UiThemeTokens.input,
                      child: const Center(
                        child: SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      ),
                    );
                  }
                  if (snapshot.hasData && snapshot.data != null) {
                    return Image.memory(
                      snapshot.data!,
                      fit: BoxFit.cover,
                      alignment: alignment,
                      width: double.infinity,
                      filterQuality: FilterQuality.high,
                    );
                  }
                  return Container(
                    color: UiThemeTokens.input,
                    child: const Center(
                      child: Icon(
                        Icons.broken_image_outlined,
                        color: UiThemeTokens.mutedForeground,
                      ),
                    ),
                  );
                },
              ),
            ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: _isUploading ? null : onRetake,
              icon: const Icon(Icons.camera_alt_outlined, size: 16),
              label: const Text('Снимай отново'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 12),
                side: const BorderSide(color: UiThemeTokens.border),
                shape: RoundedRectangleBorder(
                  borderRadius: UiThemeTokens.borderRadius,
                ),
                textStyle: UiThemeTokens.getSansFont(
                  fontSize: 13,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: UiThemeTokens.background,
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Header Badge
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 5,
                      ),
                      decoration: BoxDecoration(
                        color: UiThemeTokens.input,
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: UiThemeTokens.border),
                      ),
                      child: Text(
                        'СТЪПКА 4 ОТ 4 • ПРЕГЛЕД НА ДОСИЕТО',
                        style: UiThemeTokens.getSansFont(
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                          color: UiThemeTokens.mutedForeground,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Проверете заснетите документи',
                      style: UiThemeTokens.getSansFont(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Уверете се, че лицето е ясно видимо, а студентската книжка има четлив факултетен номер и печат.',
                      style: UiThemeTokens.getSansFont(
                        fontSize: 13,
                        color: UiThemeTokens.mutedForeground,
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Card 1: Face Photo
                    _buildPhotoCard(
                      title: 'Биометрично лице',
                      badgeLabel: 'Лицево селфи',
                      photoFile: widget.facePhoto,
                      onRetake: widget.onRetakeFace,
                      aspectRatio: 3 / 4,
                      alignment: const Alignment(0.0, -0.15),
                    ),

                    const SizedBox(height: 16),

                    // Card 2: Student Book Photo
                    _buildPhotoCard(
                      title: 'Студентска книжка',
                      badgeLabel: 'Официален документ',
                      photoFile: widget.studentBookPhoto,
                      onRetake: widget.onRetakeBook,
                      aspectRatio: 3 / 4,
                      alignment: Alignment.center,
                    ),

                    const SizedBox(height: 16),

                    // Verification Checklist Summary
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: UiThemeTokens.card,
                        borderRadius: UiThemeTokens.borderRadius,
                        border: Border.all(color: UiThemeTokens.border),
                      ),
                      child: Column(
                        children: [
                          Row(
                            children: [
                              const Icon(
                                Icons.check_circle_outline_rounded,
                                size: 16,
                                color: Colors.green,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  'GDPR съгласие за биометрична обработка: Потвърдено',
                                  style: UiThemeTokens.getSansFont(
                                    fontSize: 12,
                                    color: UiThemeTokens.foreground,
                                  ),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              const Icon(
                                Icons.check_circle_outline_rounded,
                                size: 16,
                                color: Colors.green,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  'Двукомпонентен файлов пакет: Готов за изпращане',
                                  style: UiThemeTokens.getSansFont(
                                    fontSize: 12,
                                    color: UiThemeTokens.foreground,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),

            // Bottom Action Bar
            Container(
              padding: const EdgeInsets.all(20),
              decoration: const BoxDecoration(
                color: UiThemeTokens.card,
                border: Border(top: BorderSide(color: UiThemeTokens.border)),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (_isUploading) ...[
                    Row(
                      children: [
                        const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: UiThemeTokens.primary,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            _uploadStatusText,
                            style: UiThemeTokens.getSansFont(
                              fontSize: 12,
                              color: UiThemeTokens.mutedForeground,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                  ],
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: _isUploading ? null : _submitDossier,
                      icon: const Icon(Icons.cloud_upload_outlined, size: 18),
                      label: const Text('Потвърди и изпрати за одобрение'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: UiThemeTokens.primary,
                        foregroundColor: UiThemeTokens.primaryForeground,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(
                          borderRadius: UiThemeTokens.borderRadius,
                        ),
                        textStyle: UiThemeTokens.getSansFont(
                          fontSize: 14,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

