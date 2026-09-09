class StudentProfileModel {
  final String id;
  final String fullName;
  final String studentIdNumber;
  final String email;
  final String faculty;
  final String specialty;
  final int course;
  final int stream;
  final int group;
  final String status;
  final bool hasFaceEmbedding;
  final String? rejectionReason;
  final bool isSuperadmin;
  final bool isImpersonating;

  const StudentProfileModel({
    required this.id,
    required this.fullName,
    required this.studentIdNumber,
    required this.email,
    required this.faculty,
    required this.specialty,
    required this.course,
    required this.stream,
    required this.group,
    required this.status,
    required this.hasFaceEmbedding,
    this.rejectionReason,
    this.isSuperadmin = false,
    this.isImpersonating = false,
  });

  factory StudentProfileModel.fromJson(Map<String, dynamic> json) {
    return StudentProfileModel(
      id: json['id'] as String? ?? '',
      fullName: json['full_name'] as String? ?? '',
      studentIdNumber: json['student_id_number'] as String? ?? '',
      email: json['email'] as String? ?? '',
      faculty: json['faculty'] as String? ?? '',
      specialty: json['specialty'] as String? ?? '',
      course: json['course'] as int? ?? 0,
      stream: json['stream'] as int? ?? 0,
      group: json['group'] as int? ?? 0,
      status: json['status'] as String? ?? 'PENDING',
      hasFaceEmbedding: json['has_face_embedding'] as bool? ?? false,
      rejectionReason: json['rejection_reason'] as String?,
      isSuperadmin: json['is_superadmin'] as bool? ?? false,
      isImpersonating: json['is_impersonating'] as bool? ?? false,
    );
  }

  bool get isApproved => status.toUpperCase() == 'APPROVED';
  bool get isPendingApproval => status.toUpperCase() == 'PENDING_APPROVAL';
  bool get isRejected => status.toUpperCase() == 'REJECTED';
  bool get isPendingScan => status.toUpperCase() == 'PENDING';
  bool get hasAccessToExams => isApproved && hasFaceEmbedding;
}

class ExamItemModel {
  final String registrationId;
  final String examId;
  final String subject;
  final String? lecturer;
  final String roomNumber;
  final DateTime? dateTime;
  final String? sessionType;
  final String? faculty;
  final String? specialty;
  final int? course;
  final String? stream;
  final String? group;

  const ExamItemModel({
    required this.registrationId,
    required this.examId,
    required this.subject,
    this.lecturer,
    required this.roomNumber,
    this.dateTime,
    this.sessionType,
    this.faculty,
    this.specialty,
    this.course,
    this.stream,
    this.group,
  });

  factory ExamItemModel.fromJson(Map<String, dynamic> json) {
    DateTime? dt;
    if (json['date_time'] != null) {
      dt = DateTime.tryParse(json['date_time'].toString());
    }
    return ExamItemModel(
      registrationId: json['registration_id'] as String? ?? '',
      examId: json['exam_id'] as String? ?? '',
      subject: json['subject'] as String? ?? '',
      lecturer: json['lecturer'] as String?,
      roomNumber: json['room_number'] as String? ?? '',
      dateTime: dt,
      sessionType: json['session_type'] as String?,
      faculty: json['faculty'] as String?,
      specialty: json['specialty'] as String?,
      course: json['course'] as int?,
      stream: json['stream']?.toString(),
      group: json['group']?.toString(),
    );
  }

  String get formattedDateTime {
    if (dateTime == null) return 'Датата не е уточнена';
    final local = dateTime!.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final year = local.year.toString();
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month.$year г. в $hour:$minute ч.';
  }
}

class StudentSummaryModel {
  final String id;
  final String fullName;
  final String studentIdNumber;
  final String faculty;
  final String specialty;
  final int course;
  final int stream;
  final int group;
  final String status;
  final bool hasFaceEmbedding;

  const StudentSummaryModel({
    required this.id,
    required this.fullName,
    required this.studentIdNumber,
    required this.faculty,
    required this.specialty,
    required this.course,
    required this.stream,
    required this.group,
    required this.status,
    required this.hasFaceEmbedding,
  });

  factory StudentSummaryModel.fromJson(Map<String, dynamic> json) {
    return StudentSummaryModel(
      id: json['id'] as String? ?? '',
      fullName: json['full_name'] as String? ?? '',
      studentIdNumber: json['student_id_number'] as String? ?? '',
      faculty: json['faculty'] as String? ?? '',
      specialty: json['specialty'] as String? ?? '',
      course: json['course'] as int? ?? 1,
      stream: json['stream'] as int? ?? 1,
      group: json['group'] as int? ?? 1,
      status: json['status'] as String? ?? 'PENDING',
      hasFaceEmbedding: json['has_face_embedding'] as bool? ?? false,
    );
  }

  bool get isApproved => status.toUpperCase() == 'APPROVED';
  bool get isPendingApproval => status.toUpperCase() == 'PENDING_APPROVAL';
  bool get isRejected => status.toUpperCase() == 'REJECTED';
}

