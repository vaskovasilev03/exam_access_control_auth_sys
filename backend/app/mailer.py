import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

def send_welcome_email(student_email: str, student_name: str, temp_password: str):
    """ Изпраща HTML имейл до студента с неговата временна парола """
    if not SMTP_USER or not SMTP_PASSWORD:
        print("Настройките за SMTP не са конфигурирани. Имейлът не е изпратен.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Временни учетни данни за Изпитната Система"
    msg["From"] = SMTP_USER
    msg["To"] = student_email

    # Красив академичен HTML шаблон
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px;">
          <h2 style="color: #0056b3; text-align: center;">Добре дошли в Университетската Изпитна Система</h2>
          <p>Здравейте, <strong>{student_name}</strong>,</p>
          <p>Администрацията на университета успешно импортира вашия профил в базата данни за управление на изпитния контрол достъп.</p>
          
          <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #0056b3; margin: 20px 0;">
            <p style="margin: 0;"><strong>Вашите временни данни за достъп до мобилното приложение:</strong></p>
            <p style="margin: 5px 0;"><strong>Имейл:</strong> {student_email}</p>
            <p style="margin: 5px 0;"><strong>Временна парола:</strong> <span style="font-family: monospace; font-size: 16px; background: #e9ecef; padding: 2px 6px; border-radius: 3px;">{temp_password}</span></p>
          </div>
          
          <p style="color: #d9534f;"><strong>ВАЖНО:</strong> При първото влизане в мобилното приложение ще бъдете подканени да промените тази временна парола със собствена, след което ще трябва да преминете през биометрична верификация на лицето (Liveness Проверка).</p>
          <hr style="border: 0; border-top: 1px solid #ddd; margin: 20px 0;">
          <p style="font-size: 12px; color: #777; text-align: center;">Това е автоматично съобщение, генерирано от университетската система. Моля, не отговаряйте на този имейл.</p>
        </div>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        # Свързване със SMTP сървъра през TLS сигурност
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, student_email, msg.as_string())
        print(f"Успешно изпратен имейл до: {student_email}")
        return True
    except Exception as e:
        print(f"Грешка при изпращане на имейл до {student_email}: {e}")
        return False