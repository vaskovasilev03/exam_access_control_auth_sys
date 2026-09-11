import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:mobile_app/core/theme_tokens.dart';
import 'package:mobile_app/features/dashboard/models/student_models.dart';

class TwinAccessQrSheet extends StatefulWidget {
  final StudentProfileModel profile;

  const TwinAccessQrSheet({super.key, required this.profile});

  static Future<void> show(BuildContext context, StudentProfileModel profile) {
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => TwinAccessQrSheet(profile: profile),
    );
  }

  @override
  State<TwinAccessQrSheet> createState() => _TwinAccessQrSheetState();
}

class _TwinAccessQrSheetState extends State<TwinAccessQrSheet> {
  late DateTime _generatedAt;

  @override
  void initState() {
    super.initState();
    _generatedAt = DateTime.now();
  }

  void _refreshCode() {
    setState(() {
      _generatedAt = DateTime.now();
    });
  }

  String _buildQrPayload() {
    final payload = {
      'type': 'TWIN_EXAM_PASS',
      'student_id': widget.profile.id,
      'student_id_number': widget.profile.studentIdNumber,
      'full_name': widget.profile.fullName,
      'faculty': widget.profile.faculty,
      'specialty': widget.profile.specialty,
      'is_twin_exception': true,
      'timestamp': _generatedAt.toUtc().toIso8601String(),
    };
    return jsonEncode(payload);
  }

  String _formatTime(DateTime dt) {
    final h = dt.hour.toString().padLeft(2, '0');
    final m = dt.minute.toString().padLeft(2, '0');
    final s = dt.second.toString().padLeft(2, '0');
    return '$h:$m:$s ч.';
  }

  @override
  Widget build(BuildContext context) {
    final qrData = _buildQrPayload();

    return Container(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.of(context).size.height * 0.90,
      ),
      decoration: const BoxDecoration(
        color: UiThemeTokens.background,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: SafeArea(
        top: false,
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 20.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Handle bar
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  margin: const EdgeInsets.only(bottom: 20),
                  decoration: BoxDecoration(
                    color: UiThemeTokens.border,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),

              // Title and verified badge
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: UiThemeTokens.primary.withValues(alpha: 0.12),
                      borderRadius: UiThemeTokens.borderRadius,
                    ),
                    child: const Icon(
                      Icons.qr_code_2_rounded,
                      size: 22,
                      color: UiThemeTokens.primary,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Дигитален изпитен пропуск',
                          style: UiThemeTokens.getSansFont(
                            fontSize: 17,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Row(
                          children: [
                            const Icon(
                              Icons.verified,
                              size: 14,
                              color: Colors.green,
                            ),
                            const SizedBox(width: 5),
                            Text(
                              'Потвърден близнак / Верифициран достъп',
                              style: UiThemeTokens.getSansFont(
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                                color: Colors.green.shade700,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close, size: 20),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),

              const SizedBox(height: 20),

              // QR Box Card
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: UiThemeTokens.border),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.04),
                      blurRadius: 10,
                      offset: const Offset(0, 4),
                    ),
                  ],
                ),
                child: Column(
                  children: [
                    QrImageView(
                      data: qrData,
                      version: QrVersions.auto,
                      size: 220.0,
                      backgroundColor: Colors.white,
                      errorCorrectionLevel: QrErrorCorrectLevel.M,
                      eyeStyle: const QrEyeStyle(
                        eyeShape: QrEyeShape.square,
                        color: Colors.black87,
                      ),
                      dataModuleStyle: const QrDataModuleStyle(
                        dataModuleShape: QrDataModuleShape.square,
                        color: Colors.black87,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(
                          Icons.access_time_rounded,
                          size: 14,
                          color: UiThemeTokens.mutedForeground,
                        ),
                        const SizedBox(width: 6),
                        Text(
                          'Генериран в: ${_formatTime(_generatedAt)}',
                          style: UiThemeTokens.getSansFont(
                            fontSize: 12,
                            color: UiThemeTokens.mutedForeground,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 18),

              // Student Identity Information Card
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: UiThemeTokens.card,
                  borderRadius: UiThemeTokens.borderRadius,
                  border: Border.all(color: UiThemeTokens.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      widget.profile.fullName,
                      style: UiThemeTokens.getSansFont(
                        fontSize: 15,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Фак. №: ${widget.profile.studentIdNumber}',
                      style: UiThemeTokens.getSansFont(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: UiThemeTokens.foreground,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${widget.profile.specialty} • Курс ${widget.profile.course}, Поток ${widget.profile.stream}, Група ${widget.profile.group}',
                      style: UiThemeTokens.getSansFont(
                        fontSize: 12,
                        color: UiThemeTokens.mutedForeground,
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 14),

              // Exam hall instruction notice
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: UiThemeTokens.input,
                  borderRadius: UiThemeTokens.borderRadius,
                  border: Border.all(color: UiThemeTokens.border),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(
                      Icons.info_outline_rounded,
                      size: 16,
                      color: UiThemeTokens.mutedForeground,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Покажете този QR пропуск на квестора или терминала на входа на изпитната зала, в случай че системата изисква потвърждение на самоличността при идентични близнаци.',
                        style: UiThemeTokens.getSansFont(
                          fontSize: 12,
                          color: UiThemeTokens.mutedForeground,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 18),

              // Action buttons
              Row(
                children: [
                  Expanded(
                    child: SizedBox(
                      height: 44,
                      child: OutlinedButton.icon(
                        onPressed: _refreshCode,
                        icon: const Icon(Icons.refresh_rounded, size: 16),
                        label: const Text('Обнови'),
                        style: OutlinedButton.styleFrom(
                          side: const BorderSide(color: UiThemeTokens.border),
                          shape: RoundedRectangleBorder(
                            borderRadius: UiThemeTokens.borderRadius,
                          ),
                          textStyle: UiThemeTokens.getSansFont(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
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
                        onPressed: () => Navigator.pop(context),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: UiThemeTokens.primary,
                          foregroundColor: UiThemeTokens.primaryForeground,
                          shape: RoundedRectangleBorder(
                            borderRadius: UiThemeTokens.borderRadius,
                          ),
                          textStyle: UiThemeTokens.getSansFont(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        child: const Text('Затвори'),
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
}

