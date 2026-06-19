import os
import time
import cv2
import face_recognition
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from .database import SessionLocal
from .models import Student, Exam, ExamRegistration, AccessLog

def generate_live_frames(room_number: str):
    """ Симулира гладък видео стрийм с таймери за плавно превключване на цветовете без забиване """
    video_path = "/code/app/sample_video.mp4"
    if not os.path.exists(video_path): return

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened(): return

    db: Session = SessionLocal()
    students_in_db = db.query(Student).filter(Student.face_embedding != None).all()
    known_face_encodings = [np.array(s.face_embedding) for s in students_in_db]
    known_face_names = {s.full_name: s for s in students_in_db}

    TOLERANCE = 0.6
    
    # Времеви маркери за управление на състоянията
    stream_start_time = time.time()
    green_state_end_time = 0  # Кога трябва да приключи зеленият статус
    locked_student_name = ""  # За кой студент сме заключили зеленото състояние

    while True:
        success, frame = cap.read()
        if not success:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            success, frame = cap.read()
            if not success: break

        current_time = time.time()
        elapsed_time = current_time - stream_start_time
        
        # Полета за рисуване по подразбиране
        box_color = (0, 0, 255) # Червено
        status_text = "SCANNING / UNKNOWN"
        face_to_draw = None

        # --- 🕒 ФАЗА 1: ТОПЪЛ СТАРТ (Първите 5 секунди) ---
        if elapsed_time < 5.0:
            box_color = (255, 255, 255) # Бяло
            status_text = f"STARTING STREAM... ({int(5 - elapsed_time)}s)"
            cv2.putText(frame, status_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, box_color, 2)
            
        # --- 🟢 ФАЗА 2: ЗАКЛЮЧЕНО ЗЕЛЕНО СЪСТОЯНИЕ (Задържане без забиване) ---
        elif current_time < green_state_end_time:
            # През тези 3 секунди ИИ НЕ СЕ ИЗПЪЛНЯВА. Просто рисуваме зелено гладко!
            box_color = (0, 255, 0) # Зелено
            status_text = f"ACCESS GRANTED: {locked_student_name}"
            
            # Намираме лице в кадъра само за да има къде да нарисуваме кутийката
            small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_small_frame)
            if face_locations:
                face_to_draw = face_locations[0]

        # --- 🤖 ФАЗА 3: СТАНДАРТНО АКТИВНО ИИ РАЗПОЗНАВАНЕ ---
        else:
            small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_small_frame)

            if face_locations:
                face_to_draw = face_locations[0]
                face_encoding = face_recognition.face_encodings(rgb_small_frame, face_locations)[0]
                student_found = None
                
                if known_face_encodings:
                    matches = face_recognition.compare_faces(known_face_encodings, face_encoding, TOLERANCE)
                    if any(matches):
                        best_match_index = np.argmin(face_recognition.face_distance(known_face_encodings, face_encoding))
                        full_name = list(known_face_names.keys())[best_match_index]
                        student_found = known_face_names[full_name]

                if student_found:
                    current_now = datetime.now().astimezone()
                    
                    # 1. Проверка дали вече е вътре (ALREADY GRANTED) -> СИНЬО
                    already_in_room = db.query(AccessLog).filter(
                        AccessLog.student_id == student_found.id,
                        AccessLog.location == room_number,
                        AccessLog.status == "GRANTED",
                        func.date(AccessLog.created_at) == current_now.date()
                    ).first()

                    if already_in_room:
                        box_color = (255, 191, 0) # Синьо
                        status_text = f"ALREADY GRANTED: {student_found.full_name}"
                    
                    else:
                        # 2. Проверка на изпитния график
                        valid_registration = db.query(ExamRegistration).join(Exam).filter(
                            ExamRegistration.student_id == student_found.id,
                            Exam.room_number == room_number,
                            func.date(Exam.date_time) == current_now.date()
                        ).first()
                        
                        is_time_valid = False
                        if valid_registration:
                            exam_time = valid_registration.exam.date_time
                            if (exam_time - timedelta(minutes=30)) <= current_now <= (exam_time + timedelta(minutes=15)):
                                is_time_valid = True

                        # 3. ПЪРВОНАЧАЛЕН УСПЕХ -> ЗАКЛЮЧВАМЕ ЗЕЛЕНОТО ЗА 3 СЕКУНДИ
                        if valid_registration and is_time_valid:
                            box_color = (0, 255, 0) # Зелено
                            status_text = f"ACCESS GRANTED: {student_found.full_name}"
                            
                            # Еднократен запис в БД
                            new_log = AccessLog(student_id=student_found.id, location=room_number, status="GRANTED")
                            db.add(new_log)
                            db.commit()
                            print(f"💾 [FIRST LOGIN] Успешен запис в БД за {student_found.full_name}")
                            
                            # 🔥 АКТИВИРАМЕ ТАЙМЕРА ЗА ЗАДЪРЖАНЕ (Вместо sleep)
                            green_state_end_time = time.time() + 3.0  # Заключваме за 3 секунди напред
                            locked_student_name = student_found.full_name
                            
                        elif valid_registration and not is_time_valid:
                            box_color = (0, 165, 255) # Оранжево
                            status_text = "WRONG TIME"
                        else:
                            anywhere_today = db.query(ExamRegistration).join(Exam).filter(
                                ExamRegistration.student_id == student_found.id,
                                func.date(Exam.date_time) == current_now.date()
                            ).first()
                            
                            if anywhere_today:
                                # Намерихме къде трябва да бъде!
                                correct_room = anywhere_today.exam.room_number
                                box_color = (0, 0, 255) # Червено (защото залата е грешна за тук)
                                status_text = f"WRONG ROOM! GO TO ROOM {correct_room}"
                            else:
                                # Няма изпит никъде днес
                                box_color = (0, 0, 255) # Червено
                                status_text = "NO EXAM TODAY"
            else:
                cv2.putText(frame, "WAITING FOR FACE...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # --- 🖼️ РИСУВАНЕ НА КУТИЙКАТА (Ако има лице на екрана) ---
        if face_to_draw:
            top, right, bottom, left = face_to_draw
            top *= 4; right *= 4; bottom *= 4; left *= 4
            cv2.rectangle(frame, (left, top), (right, bottom), box_color, 3)
            cv2.putText(frame, status_text, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

        # Кодиране и изпращане на кадъра (Винаги работи гладко с 25 FPS)
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret: continue
            
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.04) # 25 FPS
        
    db.close()
    cap.release()