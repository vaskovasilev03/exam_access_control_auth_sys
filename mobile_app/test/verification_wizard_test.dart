import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:mobile_app/features/dashboard/models/student_models.dart';
import 'package:mobile_app/features/verification/widgets/twin_access_qr_sheet.dart';
import 'package:mobile_app/features/verification/widgets/face_hud_painter.dart';
import 'package:mobile_app/features/verification/widgets/document_frame_painter.dart';
import 'package:mobile_app/features/verification/gdpr_consent_view.dart';
import 'package:mobile_app/features/verification/services/face_detector_service.dart';
import 'package:mobile_app/features/verification/face_scan_view.dart';

void main() {
  group('StudentProfileModel Twin & GDPR Deserialization Tests', () {
    test('Correctly parses is_twin_exception and gdpr_consent_given when present', () {
      final json = {
        'id': 'test-uuid-123',
        'full_name': 'Иван Иванов',
        'student_id_number': '121220001',
        'email': 'ivan@tu-sofia.bg',
        'faculty': 'ФКСТ',
        'specialty': 'КСИ',
        'course': 3,
        'stream': 1,
        'group': 42,
        'status': 'APPROVED',
        'has_face_embedding': true,
        'is_twin_exception': true,
        'gdpr_consent_given': true,
      };

      final model = StudentProfileModel.fromJson(json);

      expect(model.id, equals('test-uuid-123'));
      expect(model.fullName, equals('Иван Иванов'));
      expect(model.isTwinException, isTrue);
      expect(model.gdprConsentGiven, isTrue);
      expect(model.isApproved, isTrue);
      expect(model.hasAccessToExams, isTrue);
    });

    test('Defaults is_twin_exception and gdpr_consent_given to false when absent or null', () {
      final json = {
        'id': 'test-uuid-456',
        'full_name': 'Георги Георгиев',
        'student_id_number': '121220002',
        'email': 'georgi@tu-sofia.bg',
        'faculty': 'ФКСТ',
        'specialty': 'КСИ',
        'course': 2,
        'stream': 1,
        'group': 15,
        'status': 'PENDING',
        'has_face_embedding': false,
      };

      final model = StudentProfileModel.fromJson(json);

      expect(model.isTwinException, isFalse);
      expect(model.gdprConsentGiven, isFalse);
      expect(model.isPendingScan, isTrue);
      expect(model.isPendingApproval, isFalse);
      expect(model.isPendingDuplicateReview, isFalse);
      expect(model.hasAccessToExams, isFalse);
    });

    test('Correctly identifies PENDING_DUPLICATE_REVIEW as isPendingApproval and isPendingDuplicateReview', () {
      final json = {
        'id': 'test-uuid-789',
        'full_name': 'Николай Николов',
        'student_id_number': '121220003',
        'email': 'nikolay@tu-sofia.bg',
        'faculty': 'ФКСТ',
        'specialty': 'КСИ',
        'course': 2,
        'stream': 1,
        'group': 15,
        'status': 'PENDING_DUPLICATE_REVIEW',
        'has_face_embedding': false,
      };

      final model = StudentProfileModel.fromJson(json);

      expect(model.isPendingApproval, isTrue);
      expect(model.isPendingDuplicateReview, isTrue);
      expect(model.isPendingScan, isFalse);
      expect(model.isApproved, isFalse);
      expect(model.isRejected, isFalse);
      expect(model.hasAccessToExams, isFalse);
    });
  });

  group('TwinAccessQrSheet Widget Tests', () {
    testWidgets('Renders twin QR pass with student credentials and scannable QR', (WidgetTester tester) async {
      const twinStudent = StudentProfileModel(
        id: 'twin-uuid-999',
        fullName: 'Александър Димитров',
        studentIdNumber: '121222099',
        email: 'alex@tu-sofia.bg',
        faculty: 'ФКСТ',
        specialty: 'Компютърно и софтуерно инженерство',
        course: 4,
        stream: 2,
        group: 30,
        status: 'APPROVED',
        hasFaceEmbedding: true,
        isTwinException: true,
        gdprConsentGiven: true,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (ctx) => ElevatedButton(
                onPressed: () => TwinAccessQrSheet.show(ctx, twinStudent),
                child: const Text('Open Sheet'),
              ),
            ),
          ),
        ),
      );

      // Open bottom sheet
      await tester.tap(find.text('Open Sheet'));
      await tester.pumpAndSettle();

      // Verify header and badge
      expect(find.text('Дигитален изпитен пропуск'), findsOneWidget);
      expect(find.text('Потвърден близнак / Верифициран достъп'), findsOneWidget);

      // Verify student details displayed
      expect(find.text('Александър Димитров'), findsOneWidget);
      expect(find.text('Фак. №: 121222099'), findsOneWidget);
      expect(find.textContaining('Курс 4, Поток 2, Група 30'), findsOneWidget);

      // Verify QR image view rendered
      expect(find.byType(QrImageView), findsOneWidget);
    });
  });

  group('GdprConsentView Widget Tests', () {
    testWidgets('Gating mechanism disables continue button until consent is checked', (WidgetTester tester) async {
      bool consentGranted = false;

      await tester.pumpWidget(
        MaterialApp(
          home: GdprConsentView(
            onConsentGranted: () {
              consentGranted = true;
            },
          ),
        ),
      );

      // Verify initial state
      expect(find.text('Биометрично съгласие & GDPR декларация'), findsOneWidget);
      expect(find.text('Продължи към заснемане'), findsOneWidget);

      // Button should be disabled initially
      final buttonFinder = find.widgetWithText(ElevatedButton, 'Продължи към заснемане');
      ElevatedButton button = tester.widget<ElevatedButton>(buttonFinder);
      expect(button.onPressed, isNull);

      // Scroll to make checkbox visible in test viewport
      final checkboxFinder = find.byType(Checkbox);
      expect(checkboxFinder, findsOneWidget);
      await tester.ensureVisible(checkboxFinder);
      await tester.pumpAndSettle();
      await tester.tap(checkboxFinder);
      await tester.pumpAndSettle();

      // Button should now be active
      button = tester.widget<ElevatedButton>(buttonFinder);
      expect(button.onPressed, isNotNull);

      // Tap button and verify callback
      await tester.tap(buttonFinder);
      await tester.pump();
      expect(consentGranted, isTrue);
    });
  });

  group('Canvas Painter Execution Tests', () {
    testWidgets('FaceHudPainter paints without errors', (WidgetTester tester) async {
      await tester.pumpWidget(
        CustomPaint(
          size: const Size(400, 800),
          painter: FaceHudPainter(
            borderColor: Colors.green,
            isFaceDetected: true,
            countdownProgress: 0.5,
          ),
        ),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('DocumentFramePainter paints without errors', (WidgetTester tester) async {
      await tester.pumpWidget(
        CustomPaint(
          size: const Size(400, 800),
          painter: DocumentFramePainter(
            borderColor: Colors.white,
          ),
        ),
      );
      expect(tester.takeException(), isNull);
    });
  });

  group('FaceDetectorService & ScanFacePhase Tests', () {
    test('FaceDetectorService behaves as a singleton and has reset method', () {
      final s1 = FaceDetectorService();
      final s2 = FaceDetectorService();
      expect(identical(s1, s2), isTrue);
      expect(() => s1.reset(), returnsNormally);
    });

    test('ScanFacePhase has expected enum states in correct progression', () {
      expect(ScanFacePhase.values, containsAll([
        ScanFacePhase.searching,
        ScanFacePhase.found,
        ScanFacePhase.countdown,
        ScanFacePhase.completed,
      ]));
    });
  });
}
