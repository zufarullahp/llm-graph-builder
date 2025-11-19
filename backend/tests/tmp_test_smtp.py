# tmp_test_smtp.py
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

host = os.environ["SMTP_HOST"]
port = int(os.environ["SMTP_PORT"])
username = os.environ["SMTP_USERNAME"]
password = os.environ["SMTP_PASSWORD"]
sender = os.environ.get("SMTP_FROM", username)

to_email = "a.zufarullahp@gmail.com"
subject = "Test SMTP dari Privas AI"
body = "SMTP Spaceship + SSL OK!"

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = to_email

print(f"Connecting with SSL to {host}:{port}...")

with smtplib.SMTP_SSL(host, port) as server:
    server.login(username, password)
    server.sendmail(sender, [to_email], msg.as_string())

print("Email terkirim!")
