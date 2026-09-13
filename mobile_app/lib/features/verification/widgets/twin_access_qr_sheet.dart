import 'dart:async';
import 'dart:convert';
import 'package:crypto/crypto.dart';
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
  QrCode? _qrCode;
  String _passcode = '';
  Timer? _timer;
  int _secondsRemaining = 300;
  int _lastBucket = -1;

  @override
  void initState() {
    super.initState();
    _generateCode();
    _initTimer();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _initTimer() {
    _updateRemainingTime();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      _updateRemainingTime();
    });
  }

  void _updateRemainingTime() {
    final now = DateTime.now().toUtc();
    final epochSec = now.millisecondsSinceEpoch ~/ 1000;
    final bucket = epochSec ~/ 300;
    final remaining = 300 - (epochSec % 300);

    if (_lastBucket != -1 && bucket != _lastBucket) {
      // 5-минутният прозорец изтече: автоматично регенериране без натискане
      _generateCode();
    } else {
      if (_secondsRemaining != remaining) {
        setState(() {
          _secondsRemaining = remaining;
        });
      }
    }
  }

  void _generateCode() {
    _generatedAt = DateTime.now();
    final epochSec = _generatedAt.toUtc().millisecondsSinceEpoch ~/ 1000;
    _lastBucket = epochSec ~/ 300;
    _secondsRemaining = 300 - (epochSec % 300);

    _passcode = _generateDynamicPasscode(
      widget.profile.id,
      widget.profile.studentIdNumber,
      _generatedAt,
    );
    final payload = _buildQrPayload();
    final validation = QrValidator.validate(
      data: payload,
      version: QrVersions.auto,
      errorCorrectionLevel: QrErrorCorrectLevel.L,
    );
    if (mounted) {
      setState(() {
        _qrCode = validation.isValid ? validation.qrCode : null;
      });
    } else {
      _qrCode = validation.isValid ? validation.qrCode : null;
    }
  }

  String _generateDynamicPasscode(String studentId, String studentIdNumber, DateTime dt) {
    final epochSec = dt.toUtc().millisecondsSinceEpoch ~/ 1000;
    final bucket = epochSec ~/ 300;
    final seed = 'TWIN_PASS:${studentId.trim()}:${studentIdNumber.trim()}:$bucket';
    final digest = sha256.convert(utf8.encode(seed)).toString();
    final codeNum = int.parse(digest.substring(0, 8), radix: 16) % 1000000;
    return codeNum.toString().padLeft(6, '0');
  }

  String _formattedPasscode(String code) {
    if (code.length == 6) {
      return '${code.substring(0, 3)} ${code.substring(3, 6)}';
    }
    return code;
  }

  void _refreshCode() {
    setState(() {
      _generateCode();
    });
  }

  String _formatRemainingTime(int totalSeconds) {
    final m = totalSeconds ~/ 60;
    final s = totalSeconds % 60;
    return '$m:${s.toString().padLeft(2, '0')} мин.';
  }

  String _buildQrPayload() {
    final payload = {
      'type': 'TWIN_EXAM_PASS',
      'student_id': widget.profile.id,
      'student_id_number': widget.profile.studentIdNumber,
      'is_twin_exception': true,
      'passcode': _passcode,
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
                              'Верифициран достъп',
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
                    RepaintBoundary(
                      child: _qrCode != null
                          ? QrImageView.withQr(
                              qr: _qrCode!,
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
                            )
                          : const SizedBox(
                              width: 220.0,
                              height: 220.0,
                              child: Center(
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: UiThemeTokens.primary,
                                ),
                              ),
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
              const SizedBox(height: 14),

              // Manual Verification Passcode Card (For Examiner Manual Entry)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                decoration: BoxDecoration(
                  color: UiThemeTokens.primary.withValues(alpha: 0.06),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: UiThemeTokens.primary.withValues(alpha: 0.25)),
                ),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(
                          Icons.pin_outlined,
                          size: 15,
                          color: UiThemeTokens.primary,
                        ),
                        const SizedBox(width: 6),
                        Text(
                          'КОД ЗА РЪЧНО ВЪВЕЖДАНЕ ОТ КВЕСТОР',
                          style: UiThemeTokens.getSansFont(
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            color: UiThemeTokens.primary,
                            letterSpacing: 0.5,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: UiThemeTokens.border),
                          ),
                          child: Text(
                            _formattedPasscode(_passcode),
                            style: UiThemeTokens.getMonoFont(
                              fontSize: 26,
                              fontWeight: FontWeight.w900,
                              color: UiThemeTokens.foreground,
                              letterSpacing: 4,
                            ),
                          ),
                        ),
                        const SizedBox(width: 14),
                        Tooltip(
                          message: 'Оставащо време до автоматично обновяване: ${_formatRemainingTime(_secondsRemaining)}',
                          child: SizedBox(
                            width: 34,
                            height: 34,
                            child: Stack(
                              alignment: Alignment.center,
                              children: [
                                CircularProgressIndicator(
                                  value: _secondsRemaining / 300.0,
                                  strokeWidth: 3.2,
                                  backgroundColor: UiThemeTokens.border,
                                  valueColor: AlwaysStoppedAnimation<Color>(
                                    _secondsRemaining <= 30
                                        ? UiThemeTokens.destructive
                                        : UiThemeTokens.primary,
                                  ),
                                ),
                                Icon(
                                  Icons.lock_clock_outlined,
                                  size: 15,
                                  color: _secondsRemaining <= 30
                                      ? UiThemeTokens.destructive
                                      : UiThemeTokens.mutedForeground,
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Text(
                      'Валиден още ${_formatRemainingTime(_secondsRemaining)}',
                      style: UiThemeTokens.getSansFont(
                        fontSize: 11,
                        color: _secondsRemaining <= 30 ? UiThemeTokens.destructive : UiThemeTokens.mutedForeground,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 14),

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
                          elevation: 0,
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          minimumSize: const Size(0, 44),
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

