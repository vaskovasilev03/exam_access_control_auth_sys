import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../../core/theme_tokens.dart';
import '../auth/auth_repository.dart';
import '../auth/change_password_sheet.dart';
import '../auth/login_screen.dart';
import '../verification/verification_wizard_screen.dart';
import '../verification/widgets/twin_access_qr_sheet.dart';
import 'models/student_models.dart';
import 'admin_students_view.dart';
import 'admin_exams_view.dart';

class DashboardScreen extends StatefulWidget {
  final AuthRepository? authRepository;

  const DashboardScreen({super.key, this.authRepository});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  int _selectedTabIndex = 0; // 0: Student Profile / Students, 1: Exam's Window
  late final PageController _pageController;

  bool _isLoading = true; // Първоначално зареждане
  bool _isRefreshing = false; // Плавно фоново обновяване без скриване на горния панел
  String? _errorMessage;

  StudentProfileModel? _profile;
  List<ExamItemModel> _exams = [];
  bool _isLoadingExams = false;
  String? _examsErrorMessage;

  // Административен режим: списък със студенти и избран студент за симулация
  List<StudentSummaryModel> _adminStudents = [];
  bool _isLoadingStudents = false;
  String? _studentsErrorMessage;
  StudentSummaryModel? _selectedStudent;

  @override
  void initState() {
    super.initState();
    _pageController = PageController(initialPage: _selectedTabIndex);
    _loadInitialData();
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  Future<void> _loadInitialData() async {
    if (widget.authRepository == null) {
      setState(() {
        _isLoading = false;
        _errorMessage = 'Липсва автентикационна сесия.';
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final profile = await widget.authRepository!.getStudentProfile();
      if (!mounted) return;
      setState(() {
        _profile = profile;
        _isLoading = false;
      });

      if (profile.isSuperadmin) {
        // За администратор: зареждаме студентите за първия таб и ВСИЧКИ изпити за втория
        _loadAdminStudents();
        _loadExams();
      } else {
        // За редовен студент: зареждаме изпитите само при биометричен достъп
        if (profile.hasAccessToExams) {
          _loadExams();
        } else {
          setState(() {
            _exams = [];
            _isLoadingExams = false;
          });
        }
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.toString().replaceAll('Exception: ', '');
        _isLoading = false;
      });
    }
  }

  Future<void> _loadAdminStudents() async {
    if (widget.authRepository == null) return;
    setState(() {
      _isLoadingStudents = true;
      _studentsErrorMessage = null;
    });

    try {
      final students = await widget.authRepository!.getImpersonationList();
      if (!mounted) return;
      setState(() {
        _adminStudents = students;
        _isLoadingStudents = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _studentsErrorMessage = e.toString().replaceAll('Exception: ', '');
        _isLoadingStudents = false;
      });
    }
  }

  Future<void> _loadExams({String? impersonateId}) async {
    if (widget.authRepository == null) return;
    setState(() {
      _isLoadingExams = true;
      _examsErrorMessage = null;
    });

    try {
      final exams = await widget.authRepository!.getMyExams(
        impersonateId: impersonateId ?? _selectedStudent?.id,
      );
      if (!mounted) return;
      setState(() {
        _exams = exams;
        _isLoadingExams = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _examsErrorMessage = e.toString().replaceAll('Exception: ', '');
        _isLoadingExams = false;
      });
    }
  }

  /// Гладко обновяване на данните без скриване на горната лента и табовете
  Future<void> _refreshAll() async {
    if (widget.authRepository == null || _isRefreshing) return;

    setState(() {
      _isRefreshing = true;
      _errorMessage = null;
    });

    try {
      final profile = await widget.authRepository!.getStudentProfile();
      if (!mounted) return;
      setState(() {
        _profile = profile;
      });

      if (profile.isSuperadmin) {
        await Future.wait([
          _loadAdminStudents(),
          _loadExams(impersonateId: _selectedStudent?.id),
        ]);
      } else {
        if (profile.hasAccessToExams) {
          final exams = await widget.authRepository!.getMyExams();
          if (mounted) {
            setState(() {
              _exams = exams;
              _examsErrorMessage = null;
            });
          }
        } else {
          setState(() {
            _exams = [];
            _isLoadingExams = false;
          });
        }
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.toString().replaceAll('Exception: ', '')),
          backgroundColor: UiThemeTokens.destructive,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isRefreshing = false;
        });
      }
    }
  }

  void _onTabTapped(int index) {
    if (_selectedTabIndex == index) return;
    setState(() => _selectedTabIndex = index);
    _pageController.animateToPage(
      index,
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeInOut,
    );
    if (index == 1 && _profile != null) {
      if (_profile!.isSuperadmin) {
        if (_exams.isEmpty && !_isLoadingExams) {
          _loadExams(impersonateId: _selectedStudent?.id);
        }
      } else if (_profile!.hasAccessToExams && _exams.isEmpty && !_isLoadingExams) {
        _loadExams();
      }
    }
  }

  void _openVerificationWizard() async {
    if (widget.authRepository == null) return;
    if (_profile != null && _profile!.isPendingApproval) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Вашите документи вече са изпратени и се обработват. Не можете да изпращате повторно до решение на администратор.'),
          backgroundColor: Colors.orange,
        ),
      );
      return;
    }
    final apiClient = widget.authRepository!.getApiClient();

    final result = await Navigator.push<bool>(
      context,
      MaterialPageRoute(
        builder: (context) => VerificationWizardScreen(apiClient: apiClient),
      ),
    );

    if (result == true) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Документите са изпратени за одобрение!'),
            backgroundColor: Colors.green,
          ),
        );
      }
      _refreshAll();
    }
  }

  void _openLivenessScan() => _openVerificationWizard();

  void _openTwinQrPassSheet() {
    if (_profile == null) return;
    TwinAccessQrSheet.show(context, _profile!);
  }

  void _openChangePasswordSheet() {
    if (widget.authRepository == null) return;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: UiThemeTokens.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.only(
          topLeft: UiThemeTokens.borderRadius.topLeft,
          topRight: UiThemeTokens.borderRadius.topRight,
        ),
      ),
      builder: (context) => ChangePasswordSheet(
        authRepository: widget.authRepository!,
        isInitialSetup: false,
        onSuccess: () {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Паролата е сменена успешно.'),
              backgroundColor: Colors.green,
            ),
          );
        },
      ),
    );
  }

  void _onStudentSelected(StudentSummaryModel? student) {
    setState(() {
      _selectedStudent = student;
    });
    _loadExams(impersonateId: student?.id);
    if (student != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Избран студент за преглед на изпити: ${student.fullName} (${student.studentIdNumber})'),
          backgroundColor: Colors.amber.shade800,
          duration: const Duration(seconds: 2),
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Премахнат филтър по студент. Показват се всички изпити.'),
          backgroundColor: UiThemeTokens.primary,
          duration: Duration(seconds: 2),
        ),
      );
    }
  }

  Future<void> _handleLogout() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          'Изход от профила',
          style: UiThemeTokens.getSansFont(fontWeight: FontWeight.bold, fontSize: 18),
        ),
        content: Text(
          'Сигурни ли сте, че искате да излезете от системата?',
          style: UiThemeTokens.getSansFont(fontSize: 14),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        actions: [
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 44,
                  child: OutlinedButton(
                    onPressed: () => Navigator.pop(context, false),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: UiThemeTokens.border),
                      shape: RoundedRectangleBorder(
                        borderRadius: UiThemeTokens.borderRadius,
                      ),
                    ),
                    child: Text(
                      'Отказ',
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
                    onPressed: () => Navigator.pop(context, true),
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

    if (confirm == true && mounted && widget.authRepository != null) {
      await widget.authRepository!.logout();
      if (!mounted) return;
      Navigator.pushAndRemoveUntil(
        context,
        MaterialPageRoute(
          builder: (context) => LoginScreen(authRepository: widget.authRepository!),
        ),
        (route) => false,
      );
    }
  }

  /// Потвърждение при натискане на хардуерен Back бутон на начален таб
  Future<bool?> _showExitConfirmationDialog() {
    return showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: UiThemeTokens.background,
        shape: RoundedRectangleBorder(
          borderRadius: UiThemeTokens.borderRadius,
          side: const BorderSide(color: UiThemeTokens.border),
        ),
        title: Text(
          'Затваряне на приложението',
          style: UiThemeTokens.getSansFont(fontWeight: FontWeight.bold, fontSize: 18),
        ),
        content: Text(
          'Желаете ли да затворите Exam Gate?',
          style: UiThemeTokens.getSansFont(fontSize: 14),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        actions: [
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 44,
                  child: OutlinedButton(
                    onPressed: () => Navigator.pop(context, false),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: UiThemeTokens.border),
                      shape: RoundedRectangleBorder(
                        borderRadius: UiThemeTokens.borderRadius,
                      ),
                    ),
                    child: Text(
                      'Отказ',
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
                    onPressed: () => Navigator.pop(context, true),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: UiThemeTokens.primary,
                      foregroundColor: UiThemeTokens.primaryForeground,
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: UiThemeTokens.borderRadius,
                      ),
                    ),
                    child: Text(
                      'Затвори',
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
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;

        // 1. Ако сме в "Изпитен Прозорец", връщаме към "Студентски Профил"
        if (_selectedTabIndex != 0) {
          _onTabTapped(0);
          return;
        }

        // 2. Ако сме в "Студентски Профил", питаме за потвърждение за затваряне
        final shouldExit = await _showExitConfirmationDialog();
        if (shouldExit == true) {
          SystemNavigator.pop();
        }
      },
      child: Scaffold(
        backgroundColor: UiThemeTokens.background,
        body: SafeArea(
          child: _isLoading
              ? const Center(child: CircularProgressIndicator(color: UiThemeTokens.primary))
              : _errorMessage != null
                  ? _buildErrorView()
                  : Column(
                      children: [
                        _buildTopHeader(),
                        _buildTopTabSwitcher(),
                        if (_isRefreshing)
                          const LinearProgressIndicator(
                            minHeight: 2.5,
                            color: UiThemeTokens.primary,
                            backgroundColor: Colors.transparent,
                          ),
                        if (_profile != null && !_profile!.isSuperadmin && !_profile!.isApproved)
                          _buildPersistentAlertBanner(),
                        Expanded(
                          child: PageView(
                            controller: _pageController,
                            onPageChanged: (index) {
                              setState(() => _selectedTabIndex = index);
                              if (index == 1 &&
                                  _profile != null &&
                                  _profile!.hasAccessToExams &&
                                  _exams.isEmpty &&
                                  !_isLoadingExams) {
                                _loadExams();
                              }
                            },
                            children: [
                              _buildStudentProfileTab(),
                              _buildExamsWindowTab(),
                            ],
                          ),
                        ),
                      ],
                    ),
        ),
      ),
    );
  }

  Widget _buildErrorView() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 56, color: UiThemeTokens.destructive),
            const SizedBox(height: 16),
            Text(
              'Възникна грешка при зареждане',
              style: UiThemeTokens.getSansFont(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text(
              _errorMessage ?? 'Неизвестна грешка',
              textAlign: TextAlign.center,
              style: UiThemeTokens.getSansFont(color: UiThemeTokens.mutedForeground),
            ),
            const SizedBox(height: 24),
            ElevatedButton(
              onPressed: _loadInitialData,
              child: const Text('Опитай отново'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTopHeader() {
    final isSuper = _profile?.isSuperadmin == true;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 12.0),
      decoration: const BoxDecoration(
        color: UiThemeTokens.card,
        border: Border(bottom: BorderSide(color: UiThemeTokens.border)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Row(
              children: [
                Icon(
                  isSuper ? Icons.admin_panel_settings_rounded : Icons.school_rounded,
                  size: 26,
                  color: UiThemeTokens.primary,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Row(
                        children: [
                          Flexible(
                            child: Text(
                              'Exam Gate',
                              overflow: TextOverflow.ellipsis,
                              style: UiThemeTokens.getSansFont(
                                fontSize: 17,
                                fontWeight: FontWeight.bold,
                                color: UiThemeTokens.primary,
                              ),
                            ),
                          ),
                          if (isSuper) ...[
                            const SizedBox(width: 6),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1.5),
                              decoration: BoxDecoration(
                                color: Colors.amber.shade700.withValues(alpha: 0.18),
                                borderRadius: BorderRadius.circular(4),
                                border: Border.all(color: Colors.amber.shade700, width: 0.8),
                              ),
                              child: Text(
                                'SUPERADMIN',
                                style: TextStyle(
                                  fontSize: 9,
                                  fontWeight: FontWeight.bold,
                                  color: Colors.amber.shade700,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                      if (_profile != null)
                        Text(
                          isSuper
                              ? (_profile!.email.isNotEmpty ? _profile!.email : 'Административен профил')
                              : 'Фак. № ${_profile!.studentIdNumber}',
                          overflow: TextOverflow.ellipsis,
                          maxLines: 1,
                          style: UiThemeTokens.getSansFont(
                            fontSize: 12,
                            color: UiThemeTokens.mutedForeground,
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              IconButton(
                icon: _isRefreshing
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: UiThemeTokens.primary),
                      )
                    : const Icon(Icons.refresh, color: UiThemeTokens.mutedForeground),
                tooltip: 'Обнови',
                onPressed: _isRefreshing ? null : _refreshAll,
              ),
              IconButton(
                icon: const Icon(Icons.logout, color: UiThemeTokens.destructive),
                tooltip: 'Изход',
                onPressed: _handleLogout,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildTopTabSwitcher() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16.0, 16.0, 16.0, 8.0),
      child: AnimatedBuilder(
        animation: _pageController,
        builder: (context, child) {
          // Извличаме позицията на превъртане в реално време (от 0.0 до 1.0)
          final page = (_pageController.hasClients && _pageController.page != null)
              ? _pageController.page!
              : _selectedTabIndex.toDouble();
          final progress = page.clamp(0.0, 1.0);

          return Container(
            padding: const EdgeInsets.all(4.0),
            decoration: BoxDecoration(
              color: UiThemeTokens.input,
              borderRadius: UiThemeTokens.borderRadius,
              border: Border.all(color: UiThemeTokens.border),
            ),
            child: LayoutBuilder(
              builder: (context, constraints) {
                final tabWidth = constraints.maxWidth / 2;

                return Stack(
                  children: [
                    // 1. Плаващо / плъзгащо се хапче, движещо се заедно със суайпването в реално време
                    Positioned(
                      top: 0,
                      bottom: 0,
                      left: progress * tabWidth,
                      width: tabWidth,
                      child: Container(
                        decoration: BoxDecoration(
                          color: UiThemeTokens.primary,
                          borderRadius: UiThemeTokens.borderRadius,
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withValues(alpha: 0.1),
                              blurRadius: 4,
                              offset: const Offset(0, 2),
                            ),
                          ],
                        ),
                      ),
                    ),

                    // 2. Интерактивни бутони с плавно преливащ цвят на текста (Color.lerp)
                    Row(
                      children: [
                        Expanded(
                          child: GestureDetector(
                            behavior: HitTestBehavior.opaque,
                            onTap: () => _onTabTapped(0),
                            child: Padding(
                              padding: const EdgeInsets.symmetric(vertical: 12.0),
                              child: Center(
                                child: Text(
                                  _profile?.isSuperadmin == true ? 'Студенти' : 'Студентски Профил',
                                  style: UiThemeTokens.getSansFont(
                                    fontSize: 13,
                                    fontWeight: FontWeight.bold,
                                    color: Color.lerp(
                                      UiThemeTokens.primaryForeground,
                                      UiThemeTokens.mutedForeground,
                                      progress,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                        Expanded(
                          child: GestureDetector(
                            behavior: HitTestBehavior.opaque,
                            onTap: () => _onTabTapped(1),
                            child: Padding(
                              padding: const EdgeInsets.symmetric(vertical: 12.0),
                              child: Center(
                                child: Row(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    Text(
                                      _profile?.isSuperadmin == true ? 'Всички Изпити' : 'Изпитен Прозорец',
                                      style: UiThemeTokens.getSansFont(
                                        fontSize: 13,
                                        fontWeight: FontWeight.bold,
                                        color: Color.lerp(
                                          UiThemeTokens.mutedForeground,
                                          UiThemeTokens.primaryForeground,
                                          progress,
                                        ),
                                      ),
                                    ),
                                    if (_profile != null && !_profile!.isSuperadmin && !_profile!.hasAccessToExams) ...[
                                      const SizedBox(width: 4),
                                      Icon(
                                        Icons.lock_outline,
                                        size: 14,
                                        color: Color.lerp(
                                          UiThemeTokens.mutedForeground,
                                          UiThemeTokens.primaryForeground.withValues(alpha: 0.8),
                                          progress,
                                        ),
                                      ),
                                    ],
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                );
              },
            ),
          );
        },
      ),
    );
  }

  Widget _buildPersistentAlertBanner() {
    if (_profile == null) return const SizedBox.shrink();

    final isPendingApproval = _profile!.isPendingApproval;
    final isRejected = _profile!.isRejected;
    final isPendingScan = _profile!.isPendingScan;

    Color bg;
    Color border;
    IconData icon;
    String text;
    Widget? actionButton;

    if (isPendingApproval) {
      bg = const Color(0xFFFFF8E1);
      border = const Color(0xFFFFE082);
      icon = Icons.hourglass_top_outlined;
      text = _profile!.isPendingDuplicateReview
          ? 'Вашият биометричен профил се преглежда от администратор (отчетено биометрично сходство). Очаквайте решение.'
          : 'Вашият биометричен профил се преглежда от администратор. Очаквайте потвърждение.';
      actionButton = null; // Премахнат излишният бутон "Провери" - използва се горната лента
    } else if (isRejected) {
      bg = const Color(0xFFFFEBEE);
      border = const Color(0xFFFFCDD2);
      icon = Icons.warning_amber_rounded;
      final reason = _profile!.rejectionReason != null && _profile!.rejectionReason!.isNotEmpty
          ? ' Причина: ${_profile!.rejectionReason}'
          : '';
      text = 'Биометричната Ви верификация беше отхвърлена.$reason Моля, сканирайте се отново.';
      actionButton = ElevatedButton(
        onPressed: _openLivenessScan,
        style: ElevatedButton.styleFrom(
          backgroundColor: UiThemeTokens.destructive,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          textStyle: UiThemeTokens.getSansFont(fontSize: 12, fontWeight: FontWeight.bold),
        ),
        child: const Text('Сканирай сега'),
      );
    } else if (isPendingScan) {
      bg = const Color(0xFFE8F5E9);
      border = const Color(0xFFC8E6C9);
      icon = Icons.face_retouching_natural;
      text = 'Изисква се биометрична верификация за пълен достъп до изпитния график.';
      actionButton = ElevatedButton(
        onPressed: _openLivenessScan,
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.green.shade700,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          textStyle: UiThemeTokens.getSansFont(fontSize: 12, fontWeight: FontWeight.bold),
        ),
        child: const Text('Верифицирай се'),
      );
    } else {
      return const SizedBox.shrink();
    }

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 6.0),
      padding: const EdgeInsets.all(12.0),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: UiThemeTokens.borderRadius,
        border: Border.all(color: border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Icon(icon, size: 22, color: UiThemeTokens.foreground),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: UiThemeTokens.getSansFont(fontSize: 12, fontWeight: FontWeight.w500, color: UiThemeTokens.foreground),
            ),
          ),
          if (actionButton != null) ...[
            const SizedBox(width: 8),
            actionButton,
          ],
        ],
      ),
    );
  }

  Widget _buildStudentProfileTab() {
    if (_profile == null) return const SizedBox.shrink();

    // За Superadmin: показваме директно интерактивния панел със студенти и филтри
    if (_profile!.isSuperadmin) {
      return AdminStudentsView(
        students: _adminStudents,
        isLoading: _isLoadingStudents,
        errorMessage: _studentsErrorMessage,
        selectedStudent: _selectedStudent,
        onStudentSelected: _onStudentSelected,
        onRefresh: _loadAdminStudents,
      );
    }

    // За редовен студент: показваме стандартните профилни карти
    return RefreshIndicator(
      onRefresh: _refreshAll,
      color: UiThemeTokens.primary,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16.0),
        children: [
          _buildProfileHeaderCard(),
          const SizedBox(height: 16),
          _buildAccountStatusCard(),
          const SizedBox(height: 16),
          _buildAcademicInfoCard(),
          const SizedBox(height: 16),
          _buildSecurityOptionsCard(),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _buildProfileHeaderCard() {
    final initials = _profile!.fullName.trim().split(' ').map((e) => e.isNotEmpty ? e[0] : '').take(2).join();

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Row(
          children: [
            CircleAvatar(
              radius: 32,
              backgroundColor: UiThemeTokens.primary,
              child: Text(
                initials.toUpperCase(),
                style: UiThemeTokens.getSansFont(fontSize: 22, fontWeight: FontWeight.bold, color: Colors.white),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _profile!.fullName,
                    style: UiThemeTokens.getSansFont(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _profile!.email,
                    style: UiThemeTokens.getSansFont(fontSize: 13, color: UiThemeTokens.mutedForeground),
                  ),
                  const SizedBox(height: 6),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: UiThemeTokens.input,
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      'Фак. №: ${_profile!.studentIdNumber}',
                      style: UiThemeTokens.getSansFont(fontSize: 12, fontWeight: FontWeight.w600, color: UiThemeTokens.foreground),
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

  Widget _buildAccountStatusCard() {
    final isApproved = _profile!.isApproved;
    final isPendingApproval = _profile!.isPendingApproval;
    final isRejected = _profile!.isRejected;

    Widget statusBadge;
    Widget? actionButton;

    if (isApproved) {
      statusBadge = Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.all(4),
            decoration: const BoxDecoration(
              color: Colors.green,
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.check, size: 14, color: Colors.white),
          ),
          const SizedBox(width: 8),
          Text(
            'Одобрен',
            style: UiThemeTokens.getSansFont(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.green.shade800),
          ),
        ],
      );
    } else if (isPendingApproval) {
      final bool isDuplicate = _profile!.isPendingDuplicateReview;
      statusBadge = Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
              color: Colors.orange.shade700,
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.schedule, size: 14, color: Colors.white),
          ),
          const SizedBox(width: 8),
          Text(
            isDuplicate ? 'Чака преглед (сходство)' : 'Чака одобрение',
            style: UiThemeTokens.getSansFont(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.orange.shade800),
          ),
        ],
      );
      // Премахнат бутон при чакащо одобрение или преглед за дубликат
      actionButton = null;
    } else if (isRejected) {
      statusBadge = Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.all(4),
            decoration: const BoxDecoration(
              color: UiThemeTokens.destructive,
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.close, size: 14, color: Colors.white),
          ),
          const SizedBox(width: 8),
          Text(
            'Отхвърлен',
            style: UiThemeTokens.getSansFont(fontSize: 14, fontWeight: FontWeight.bold, color: UiThemeTokens.destructive),
          ),
        ],
      );
      actionButton = ElevatedButton.icon(
        onPressed: _openLivenessScan,
        icon: const Icon(Icons.camera_alt_outlined, size: 16),
        label: const Text('Повторно сканиране'),
        style: ElevatedButton.styleFrom(
          backgroundColor: UiThemeTokens.destructive,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          textStyle: UiThemeTokens.getSansFont(fontSize: 13, fontWeight: FontWeight.bold),
        ),
      );
    } else {
      statusBadge = Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.all(4),
            decoration: const BoxDecoration(
              color: Colors.grey,
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.info_outline, size: 14, color: Colors.white),
          ),
          const SizedBox(width: 8),
          Text(
            'Непотвърден',
            style: UiThemeTokens.getSansFont(fontSize: 14, fontWeight: FontWeight.bold, color: UiThemeTokens.mutedForeground),
          ),
        ],
      );
      actionButton = ElevatedButton.icon(
        onPressed: _openLivenessScan,
        icon: const Icon(Icons.camera_alt_outlined, size: 16),
        label: const Text('Сканирай лице'),
        style: ElevatedButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          textStyle: UiThemeTokens.getSansFont(fontSize: 13, fontWeight: FontWeight.bold),
        ),
      );
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Статус на акаунта',
              style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: UiThemeTokens.input,
                    borderRadius: UiThemeTokens.borderRadius,
                  ),
                  child: statusBadge,
                ),
                ?actionButton,
              ],
            ),
            if (isRejected && _profile!.rejectionReason != null && _profile!.rejectionReason!.isNotEmpty) ...[
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: UiThemeTokens.destructive.withValues(alpha: 0.08),
                  borderRadius: UiThemeTokens.borderRadius,
                  border: Border.all(color: UiThemeTokens.destructive.withValues(alpha: 0.3)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.info_outline, size: 16, color: UiThemeTokens.destructive),
                        const SizedBox(width: 6),
                        Text(
                          'Причина за отхвърляне:',
                          style: UiThemeTokens.getSansFont(
                            fontSize: 13,
                            fontWeight: FontWeight.bold,
                            color: UiThemeTokens.destructive,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _profile!.rejectionReason!,
                      style: UiThemeTokens.getSansFont(fontSize: 13, color: UiThemeTokens.foreground),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildAcademicInfoCard() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Академична информация',
              style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            _buildInfoRow('Факултет', _profile!.faculty),
            const Divider(height: 20, color: UiThemeTokens.border),
            _buildInfoRow('Специалност', _profile!.specialty),
            const Divider(height: 20, color: UiThemeTokens.border),
            _buildInfoRow('Курс', '${_profile!.course} курс'),
            const Divider(height: 20, color: UiThemeTokens.border),
            _buildInfoRow('Поток', '${_profile!.stream} поток'),
            const Divider(height: 20, color: UiThemeTokens.border),
            _buildInfoRow('Група', '${_profile!.group} група'),
          ],
        ),
      ),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          label,
          style: UiThemeTokens.getSansFont(fontSize: 13, color: UiThemeTokens.mutedForeground),
        ),
        Text(
          value,
          style: UiThemeTokens.getSansFont(fontSize: 13, fontWeight: FontWeight.w600),
        ),
      ],
    );
  }

  Widget _buildSecurityOptionsCard() {
    final isImp = _profile?.isImpersonating == true;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Сигурност и достъп',
              style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 14),
            if (isImp) ...[
              Container(
                padding: const EdgeInsets.all(12.0),
                decoration: BoxDecoration(
                  color: UiThemeTokens.input,
                  borderRadius: UiThemeTokens.borderRadius,
                  border: Border.all(color: UiThemeTokens.border),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.lock_outline, size: 18, color: UiThemeTokens.mutedForeground),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Смяната на парола е заключена по време на симулация, за да се защитят данните на реалния студент.',
                        style: UiThemeTokens.getSansFont(fontSize: 12, color: UiThemeTokens.mutedForeground),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
            ] else ...[
              OutlinedButton.icon(
                onPressed: _openChangePasswordSheet,
                icon: const Icon(Icons.lock_reset, size: 18),
                label: const Text('Смяна на парола'),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(double.infinity, 48),
                  side: const BorderSide(color: UiThemeTokens.border),
                  shape: RoundedRectangleBorder(borderRadius: UiThemeTokens.borderRadius),
                  textStyle: UiThemeTokens.getSansFont(fontSize: 14, fontWeight: FontWeight.bold),
                ),
              ),
              const SizedBox(height: 10),
            ],
            if (_profile?.isTwinException == true) ...[
              OutlinedButton.icon(
                onPressed: _openTwinQrPassSheet,
                icon: const Icon(Icons.qr_code_2_rounded, size: 18),
                label: const Text('Дигитален изпитен пропуск (QR)'),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(double.infinity, 48),
                  side: const BorderSide(color: UiThemeTokens.border),
                  shape: RoundedRectangleBorder(borderRadius: UiThemeTokens.borderRadius),
                  textStyle: UiThemeTokens.getSansFont(fontSize: 14, fontWeight: FontWeight.bold),
                ),
              ),
              const SizedBox(height: 10),
            ],
            OutlinedButton.icon(
              onPressed: _handleLogout,
              icon: const Icon(Icons.logout, size: 18, color: UiThemeTokens.destructive),
              label: const Text('Изход от профила'),
              style: OutlinedButton.styleFrom(
                minimumSize: const Size(double.infinity, 48),
                foregroundColor: UiThemeTokens.destructive,
                side: BorderSide(color: UiThemeTokens.destructive.withValues(alpha: 0.5)),
                shape: RoundedRectangleBorder(borderRadius: UiThemeTokens.borderRadius),
                textStyle: UiThemeTokens.getSansFont(fontSize: 14, fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildExamsWindowTab() {
    // За Superadmin: изпитният прозорец е винаги достъпен (никога не се замъглява/gated)
    // и показва изчерпателния панел AdminExamsView с пълна филтрация
    if (_profile?.isSuperadmin == true) {
      return AdminExamsView(
        exams: _exams,
        isLoading: _isLoadingExams,
        errorMessage: _examsErrorMessage,
        selectedStudent: _selectedStudent,
        onClearSelectedStudent: () => _onStudentSelected(null),
        onRefresh: () => _loadExams(impersonateId: _selectedStudent?.id),
      );
    }

    final hasAccess = _profile != null && _profile!.hasAccessToExams;

    if (!hasAccess) {
      return _buildBlurredGatedExamWindow();
    }

    if (_isLoadingExams) {
      return const Center(child: CircularProgressIndicator(color: UiThemeTokens.primary));
    }

    if (_examsErrorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, size: 48, color: UiThemeTokens.destructive),
              const SizedBox(height: 12),
              Text(
                'Грешка при зареждане на изпитите',
                style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 6),
              Text(
                _examsErrorMessage!,
                textAlign: TextAlign.center,
                style: UiThemeTokens.getSansFont(color: UiThemeTokens.mutedForeground, fontSize: 13),
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: _loadExams,
                child: const Text('Презареди'),
              ),
            ],
          ),
        ),
      );
    }

    if (_exams.isEmpty) {
      return RefreshIndicator(
        onRefresh: _refreshAll,
        color: UiThemeTokens.primary,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(32.0),
          children: [
            const SizedBox(height: 40),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(28.0),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.event_available_outlined, size: 56, color: UiThemeTokens.primary),
                    const SizedBox(height: 16),
                    Text(
                      'Нямате предстоящи изпити',
                      style: UiThemeTokens.getSansFont(fontSize: 17, fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Всички регистрирани изпити за вашата група и поток ще се появят тук.',
                      textAlign: TextAlign.center,
                      style: UiThemeTokens.getSansFont(color: UiThemeTokens.mutedForeground, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _refreshAll,
      color: UiThemeTokens.primary,
      child: ListView.builder(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16.0),
        itemCount: _exams.length,
        itemBuilder: (context, index) {
          final exam = _exams[index];
          return _buildExamCard(exam);
        },
      ),
    );
  }

  Widget _buildBlurredGatedExamWindow() {
    final isPendingApproval = _profile != null && _profile!.isPendingApproval;

    return ClipRect(
      child: Stack(
        children: [
          // Размито предварително съдържание (Mockup exam layout зад блъра)
          ListView(
            padding: const EdgeInsets.all(16.0),
            physics: const NeverScrollableScrollPhysics(),
            children: [
              _buildMockExamCard('Математически анализ III', 'Зала 1151', '12.06.2026 г. в 09:00 ч.', 'доц. д-р И. Петров'),
              const SizedBox(height: 12),
              _buildMockExamCard('Обектно-ориентирано програмиране', 'Зала 2110', '18.06.2026 г. в 11:30 ч.', 'проф. д-р С. Георгиев'),
              const SizedBox(height: 12),
              _buildMockExamCard('Бази от данни', 'Зала 4203', '25.06.2026 г. в 14:00 ч.', 'доц. д-р М. Димитрова'),
            ],
          ),

          // Блър ефект (Gaussian blur) - изолиран строго в очертанията на този прозорец
          Positioned.fill(
            child: ClipRect(
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 9.0, sigmaY: 9.0),
                child: Container(
                  color: Colors.white.withValues(alpha: 0.35),
                ),
              ),
            ),
          ),

          // Централна заключваща карта с биометричен статус
          Center(
            child: SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 12.0),
              child: Card(
                elevation: 4,
                shape: RoundedRectangleBorder(
                  borderRadius: UiThemeTokens.borderRadius,
                  side: BorderSide(color: UiThemeTokens.border.withValues(alpha: 0.8)),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 20.0),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: (isPendingApproval ? Colors.orange : UiThemeTokens.primary).withValues(alpha: 0.1),
                          shape: BoxShape.circle,
                        ),
                        child: Icon(
                          isPendingApproval ? Icons.hourglass_top_outlined : Icons.fingerprint,
                          size: 40,
                          color: isPendingApproval ? Colors.orange.shade800 : UiThemeTokens.primary,
                        ),
                      ),
                      const SizedBox(height: 16),
                      Text(
                        isPendingApproval
                            ? 'Вашият биометричен профил се обработва!'
                            : 'Трябва да преминете биометрично сканиране, преди да получите достъп до този раздел!',
                        textAlign: TextAlign.center,
                        style: UiThemeTokens.getSansFont(
                          fontSize: 15,
                          fontWeight: FontWeight.bold,
                          color: UiThemeTokens.foreground,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        isPendingApproval
                            ? 'Вие вече изпратихте снимка за верификация. Моля, изчакайте администратор да одобри данните Ви, за да получите пълен достъп до графика.'
                            : 'За гарантиране на сигурността в изпитните зали, прегледът на графика и определената зала изисква потвърдена биометрия.',
                        textAlign: TextAlign.center,
                        style: UiThemeTokens.getSansFont(
                          fontSize: 12,
                          color: UiThemeTokens.mutedForeground,
                        ),
                      ),
                      // Не показваме бутон за повторно сканиране, ако вече се чака одобрение
                      if (!isPendingApproval) ...[
                        const SizedBox(height: 18),
                        ElevatedButton.icon(
                          onPressed: _openLivenessScan,
                          icon: const Icon(Icons.camera_alt_outlined, size: 18),
                          label: const Text('Към биометрично сканиране'),
                          style: ElevatedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                            textStyle: UiThemeTokens.getSansFont(fontSize: 14, fontWeight: FontWeight.bold),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMockExamCard(String subject, String room, String date, String lecturer) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Text(
                    subject,
                    style: UiThemeTokens.getSansFont(fontWeight: FontWeight.bold, fontSize: 15),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: UiThemeTokens.primary,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    room,
                    style: UiThemeTokens.getSansFont(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(date, style: UiThemeTokens.getSansFont(fontSize: 12, color: UiThemeTokens.mutedForeground)),
            const SizedBox(height: 4),
            Text(lecturer, style: UiThemeTokens.getSansFont(fontSize: 12, color: UiThemeTokens.mutedForeground)),
          ],
        ),
      ),
    );
  }

  Widget _buildExamCard(ExamItemModel exam) {
    return Card(
      margin: const EdgeInsets.only(bottom: 14.0),
      child: Padding(
        padding: const EdgeInsets.all(18.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    exam.subject,
                    style: UiThemeTokens.getSansFont(fontSize: 16, fontWeight: FontWeight.bold),
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(
                    color: UiThemeTokens.primary,
                    borderRadius: BorderRadius.circular(5),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.meeting_room_outlined, size: 14, color: Colors.white),
                      const SizedBox(width: 4),
                      Text(
                        'Зала ${exam.roomNumber}',
                        style: UiThemeTokens.getSansFont(
                          color: Colors.white,
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                const Icon(Icons.event_outlined, size: 16, color: UiThemeTokens.primary),
                const SizedBox(width: 8),
                Text(
                  exam.formattedDateTime,
                  style: UiThemeTokens.getSansFont(fontSize: 13, fontWeight: FontWeight.w600),
                ),
              ],
            ),
            if (exam.lecturer != null && exam.lecturer!.isNotEmpty) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  const Icon(Icons.person_outline, size: 16, color: UiThemeTokens.mutedForeground),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Преподавател: ${exam.lecturer}',
                      style: UiThemeTokens.getSansFont(fontSize: 13, color: UiThemeTokens.mutedForeground),
                    ),
                  ),
                ],
              ),
            ],
            if (exam.sessionType != null && exam.sessionType!.isNotEmpty) ...[
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: UiThemeTokens.input,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  'Сесия: ${exam.sessionType}',
                  style: UiThemeTokens.getSansFont(fontSize: 11, fontWeight: FontWeight.w600, color: UiThemeTokens.mutedForeground),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}