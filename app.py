from flask import Flask, request, render_template, redirect
import os
import json
import uuid
import requests
import smtplib
from email.message import EmailMessage
import threading

app = Flask(__name__)

DB_FILE = "url_db.json"

EMAIL_ADDRESS = os.getenv("EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASS")


def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_geolocation(ip):
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}", timeout=3)
        return res.json()
    except Exception as e:
        print("[Geo Error]:", e)
        return {}


# ---------- EMAIL ----------
def send_email_alert(ip_data, short_code, recipient_email):
    try:
        print("[DEBUG] Sending email...")

        msg = EmailMessage()
        msg['Subject'] = f"🚨 Visitor Alert /{short_code}"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = recipient_email

        msg.set_content(f"""
Visitor Alert!

Short Code: {short_code}
IP: {ip_data.get('query', 'N/A')}
City: {ip_data.get('city', 'N/A')}
Region: {ip_data.get('regionName', 'N/A')}
Country: {ip_data.get('country', 'N/A')}
ISP: {ip_data.get('isp', 'N/A')}
""")

        # ✅ Added timeout (prevents hanging)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            print("[DEBUG] Logging in...")
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)

            print("[DEBUG] Sending...")
            smtp.send_message(msg)

        print("[✔] Email sent successfully")

    except Exception as e:
        print("[✘] Email error:", e)


# ---------- BACKGROUND ----------
def background_task(ip, code, email):
    geo_data = get_geolocation(ip)
    geo_data["query"] = ip
    send_email_alert(geo_data, code, email)


# ---------- ROUTES ----------
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get("url")
        recipient_email = request.form.get("to_email")

        if not url.startswith("http"):
            url = "http://" + url

        short_code = uuid.uuid4().hex[:6]

        db = load_db()
        db[short_code] = {"url": url, "email": recipient_email}
        save_db(db)

        short_url = request.host_url + "track/" + short_code
        return render_template("index.html", short_url=short_url)

    return render_template("index.html")


@app.route('/track/<code>')
def track(code):
    db = load_db()
    entry = db.get(code)

    if not entry:
        return "Invalid link", 404

    real_url = entry["url"]
    recipient_email = entry["email"]

    ip_header = request.headers.get("X-Forwarded-For", request.remote_addr)
    ip = ip_header.split(",")[0].strip() if "," in ip_header else ip_header

    # 🚀 Background thread (FIXED)
    thread = threading.Thread(
        target=background_task,
        args=(ip, code, recipient_email),
        daemon=True   # ✅ important fix
    )
    thread.start()

    return redirect(real_url)


# ---------- MAIN ----------
if __name__ == "__main__":
    app.run(debug=True)