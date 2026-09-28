import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_app/features/auth/auth_repository.dart';
import 'package:mobile_app/features/auth/login_screen.dart';
import 'package:mobile_app/features/dashboard/dashboard_screen.dart';
import 'package:mobile_app/features/dashboard/models/student_models.dart';
import 'package:mobile_app/core/secure_storage_service.dart';

class FakeSecureStorageService extends Fake implements SecureStorageService {
  bool clearAllCalled = false;

  @override
  Future<void> clearAll() async {
    clearAllCalled = true;
  }

  @override
  Future<({String? studentId, String? password})> getCredentials() async {
    return (studentId: null, password: null);
  }
}

class FakeAuthRepository extends Fake implements AuthRepository {
  final FakeSecureStorageService storageService;
  bool deleteAccountCalled = false;
  bool returnErrorOnDelete = false;

  FakeAuthRepository({required this.storageService});

  @override
  SecureStorageService getStorageService() => storageService;

  @override
  Future<({String? studentId, String? password})> getSavedCredentials() {
    return storageService.getCredentials();
  }

  @override
  Future<StudentProfileModel> getStudentProfile({String? impersonateId}) async {
    return const StudentProfileModel(
      id: 'student-uuid-gdpr',
      fullName: 'Тестов Студент',
      studentIdNumber: '110126001',
      email: 'student@tu-sofia.bg',
      faculty: 'ФКСТ',
      specialty: 'КСИ',
      course: 3,
      stream: 1,
      group: 40,
      status: 'APPROVED',
      hasFaceEmbedding: true,
      isSuperadmin: false,
      isImpersonating: false,
    );
  }

  @override
  Future<List<ExamItemModel>> getMyExams({String? impersonateId}) async {
    return [];
  }

  @override
  Future<String> deleteAccount() async {
    if (returnErrorOnDelete) {
      throw Exception('Сървърна грешка при изтриване');
    }
    deleteAccountCalled = true;
    await storageService.clearAll();
    return 'Акаунтът и всички свързани данни бяха заличени успешно.';
  }
}

void main() {
  group('GDPR Art. 17 Delete Account Tests', () {
    late FakeSecureStorageService fakeStorage;
    late FakeAuthRepository fakeAuthRepo;

    setUp(() {
      fakeStorage = FakeSecureStorageService();
      fakeAuthRepo = FakeAuthRepository(storageService: fakeStorage);
    });

    testWidgets('LoginScreen shows confirmation snackbar when infoMessage is provided', (WidgetTester tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(
            authRepository: fakeAuthRepo,
            infoMessage: 'Акаунтът и всички свързани данни бяха заличени успешно.',
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Акаунтът и всички свързани данни бяха заличени успешно.'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle_outline), findsOneWidget);
    });

    testWidgets('DashboardScreen renders GDPR Delete Account button in profile tab', (WidgetTester tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          home: DashboardScreen(authRepository: fakeAuthRepo),
        ),
      );

      await tester.pumpAndSettle();

      // Find the red GDPR button
      final buttonFinder = find.byIcon(Icons.delete_forever_rounded);
      expect(buttonFinder, findsOneWidget);
    });

    testWidgets('Tapping GDPR button opens confirmation dialog and Cancel does not delete', (WidgetTester tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: DashboardScreen(authRepository: fakeAuthRepo),
        ),
      );

      await tester.pumpAndSettle();

      final buttonFinder = find.byIcon(Icons.delete_forever_rounded);
      await tester.ensureVisible(buttonFinder);
      await tester.tap(buttonFinder);
      await tester.pumpAndSettle();

      // Verify Confirmation Dialog content
      expect(find.text('Изтриване на профила'), findsOneWidget);
      expect(
        find.text('Сигурни ли сте? Това действие ще изтрие необратимо вашето лицево досие, книжка и регистрации за изпити.'),
        findsOneWidget,
      );
      expect(find.text('Отказ'), findsOneWidget);
      expect(find.text('Изтрий профила'), findsOneWidget);

      // Tap Cancel
      await tester.tap(find.text('Отказ'));
      await tester.pumpAndSettle();

      // Dialog is dismissed, no deletion happened
      expect(find.text('Изтриване на профила'), findsNothing);
      expect(fakeAuthRepo.deleteAccountCalled, isFalse);
      expect(fakeStorage.clearAllCalled, isFalse);
    });

    testWidgets('Confirming dialog triggers deleteAccount, clearAll, and navigates to LoginScreen with SnackBar', (WidgetTester tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          home: DashboardScreen(authRepository: fakeAuthRepo),
        ),
      );

      await tester.pumpAndSettle();

      final buttonFinder = find.byIcon(Icons.delete_forever_rounded);
      await tester.ensureVisible(buttonFinder);
      await tester.tap(buttonFinder);
      await tester.pumpAndSettle();

      // Tap Confirm 'Изтрий профила'
      await tester.tap(find.text('Изтрий профила'));
      await tester.pump(); // Start async deletion
      await tester.pumpAndSettle(); // Settle navigation to LoginScreen

      // Verify deletion occurred and storage was cleared
      expect(fakeAuthRepo.deleteAccountCalled, isTrue);
      expect(fakeStorage.clearAllCalled, isTrue);

      // Verify user is navigated to LoginScreen
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.text('Exam Gate: Студенти'), findsOneWidget);

      // Verify confirming SnackBar is rendered
      expect(find.text('Акаунтът и всички свързани данни бяха заличени успешно.'), findsOneWidget);
    });
  });
}
