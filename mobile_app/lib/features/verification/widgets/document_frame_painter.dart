import 'package:flutter/material.dart';

class DocumentFramePainter extends CustomPainter {
  final Color borderColor;

  DocumentFramePainter({required this.borderColor});

  @override
  void paint(Canvas canvas, Size size) {
    // Vertical Portrait Aspect Ratio ~ 1 : 1.40 (Bulgarian student book page)
    final maxFrameWidth = size.width * 0.78;
    final maxFrameHeight = size.height * 0.54;

    double frameWidth = maxFrameWidth;
    double frameHeight = frameWidth * 1.40;
    if (frameHeight > maxFrameHeight) {
      frameHeight = maxFrameHeight;
      frameWidth = frameHeight / 1.40;
    }

    final center = Offset(size.width / 2, size.height * 0.49);
    final docRect = Rect.fromCenter(
      center: center,
      width: frameWidth,
      height: frameHeight,
    );
    final rDocRect = RRect.fromRectAndRadius(docRect, const Radius.circular(12));

    // Document outer border
    final borderPaint = Paint()
      ..color = borderColor.withValues(alpha: 0.85)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2;
    canvas.drawRRect(rDocRect, borderPaint);

    // Prominent corner brackets
    final bracketPaint = Paint()
      ..color = borderColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.5
      ..strokeCap = StrokeCap.round;

    const bLen = 24.0;
    // Top-left bracket
    canvas.drawPath(
      Path()
        ..moveTo(docRect.left, docRect.top + bLen)
        ..lineTo(docRect.left, docRect.top)
        ..lineTo(docRect.left + bLen, docRect.top),
      bracketPaint,
    );
    // Top-right bracket
    canvas.drawPath(
      Path()
        ..moveTo(docRect.right - bLen, docRect.top)
        ..lineTo(docRect.right, docRect.top)
        ..lineTo(docRect.right, docRect.top + bLen),
      bracketPaint,
    );
    // Bottom-left bracket
    canvas.drawPath(
      Path()
        ..moveTo(docRect.left, docRect.bottom - bLen)
        ..lineTo(docRect.left, docRect.bottom)
        ..lineTo(docRect.left + bLen, docRect.bottom),
      bracketPaint,
    );
    // Bottom-right bracket
    canvas.drawPath(
      Path()
        ..moveTo(docRect.right - bLen, docRect.bottom)
        ..lineTo(docRect.right, docRect.bottom)
        ..lineTo(docRect.right, docRect.bottom - bLen),
      bracketPaint,
    );

    // Subtle guide zones (Photo, Header lines, 4 text lines, Stamp circle)
    final guidePaint = Paint()
      ..color = Colors.white.withValues(alpha: 0.28)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.3
      ..strokeCap = StrokeCap.round;

    // 1. Photo box guideline (top-left of student book)
    final photoRect = Rect.fromLTWH(
      docRect.left + docRect.width * 0.08,
      docRect.top + docRect.height * 0.06,
      docRect.width * 0.32,
      docRect.height * 0.28,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(photoRect, const Radius.circular(6)),
      guidePaint,
    );

    final photoTextPainter = TextPainter(
      text: TextSpan(
        text: 'СНИМКА',
        style: TextStyle(
          color: Colors.white.withValues(alpha: 0.35),
          fontSize: 9.0,
          fontWeight: FontWeight.bold,
          letterSpacing: 1.0,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    photoTextPainter.paint(
      canvas,
      Offset(
        photoRect.center.dx - photoTextPainter.width / 2,
        photoRect.center.dy - photoTextPainter.height / 2,
      ),
    );

    // 2. Header lines (top-right of student book)
    final headerLeft = docRect.left + docRect.width * 0.48;
    final headerRight = docRect.right - docRect.width * 0.08;
    final headerLine1Y = docRect.top + docRect.height * 0.11;
    final headerLine2Y = docRect.top + docRect.height * 0.18;
    canvas.drawLine(Offset(headerLeft, headerLine1Y), Offset(headerRight, headerLine1Y), guidePaint);
    canvas.drawLine(Offset(headerLeft, headerLine2Y), Offset(headerRight, headerLine2Y), guidePaint);

    // 3. 4 Horizontal text lines (middle-lower section)
    final contentLeft = docRect.left + docRect.width * 0.08;
    final contentRight = docRect.right - docRect.width * 0.08;
    final lineYs = [
      docRect.top + docRect.height * 0.42,
      docRect.top + docRect.height * 0.51,
      docRect.top + docRect.height * 0.60,
      docRect.top + docRect.height * 0.69,
    ];
    for (final y in lineYs) {
      canvas.drawLine(Offset(contentLeft, y), Offset(contentRight, y), guidePaint);
    }

    // 4. Stamp / Seal circular zone guideline (bottom-right)
    final stampCenter = Offset(
      docRect.right - docRect.width * 0.24,
      docRect.bottom - docRect.height * 0.14,
    );
    final stampRadius = docRect.width * 0.13;
    canvas.drawCircle(stampCenter, stampRadius, guidePaint);

    final stampTextPainter = TextPainter(
      text: TextSpan(
        text: 'ПЕЧАТ',
        style: TextStyle(
          color: Colors.white.withValues(alpha: 0.35),
          fontSize: 8.5,
          fontWeight: FontWeight.bold,
          letterSpacing: 1.0,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    stampTextPainter.paint(
      canvas,
      Offset(
        stampCenter.dx - stampTextPainter.width / 2,
        stampCenter.dy - stampTextPainter.height / 2,
      ),
    );
  }

  @override
  bool shouldRepaint(covariant DocumentFramePainter oldDelegate) {
    return oldDelegate.borderColor != borderColor;
  }
}

