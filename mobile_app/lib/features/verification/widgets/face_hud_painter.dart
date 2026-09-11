import 'dart:math' as math;
import 'package:flutter/material.dart';

class FaceHudPainter extends CustomPainter {
  final Color borderColor;
  final bool isFaceDetected;
  final double countdownProgress; // 0.0 to 1.0 (5s countdown)

  FaceHudPainter({
    required this.borderColor,
    this.isFaceDetected = false,
    this.countdownProgress = 0.0,
  });

  @override
  void paint(Canvas canvas, Size size) {
    // Centered oval slightly elevated to accommodate lower camera UI controls
    final ovalWidth = size.width * 0.72;
    final ovalHeight = size.height * 0.46;
    final center = Offset(size.width / 2, size.height * 0.44);
    final ovalRect = Rect.fromCenter(
      center: center,
      width: ovalWidth,
      height: ovalHeight,
    );

    // Primary clean oval border
    final borderPaint = Paint()
      ..color = borderColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = isFaceDetected ? 3.5 : 2.5;
    canvas.drawOval(ovalRect, borderPaint);

    // Subtle outer glow/pulse when face detected
    if (isFaceDetected) {
      final glowPaint = Paint()
        ..color = borderColor.withValues(alpha: 0.30)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 6.0;
      canvas.drawOval(ovalRect, glowPaint);
    }

    // Circular/oval progress arc around perimeter during 5-second countdown
    if (countdownProgress > 0.0) {
      final progressPaint = Paint()
        ..color = Colors.greenAccent
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 5.0;
      final sweepAngle = 2 * math.pi * countdownProgress.clamp(0.0, 1.0);
      canvas.drawArc(ovalRect, -math.pi / 2, sweepAngle, false, progressPaint);
    }
  }

  @override
  bool shouldRepaint(covariant FaceHudPainter oldDelegate) {
    return oldDelegate.borderColor != borderColor ||
        oldDelegate.isFaceDetected != isFaceDetected ||
        oldDelegate.countdownProgress != countdownProgress;
  }
}

