from sqlalchemy import or_, and_
from flask import Flask, request, jsonify, render_template, redirect, url_for
import logging
import socket

logging.basicConfig(filename='logs/log.txt', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
from models import db, init_db, Campaign, Recipient, SendLog
from keepalive import start_keepalive
from utils import replace_tags, html_to_pdf_bytes, random_id
import os, threading, time, random, smtplib, requests, base64, re, mimetypes
from email.message import EmailMessage
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///./data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY','dev')
init_db(app)

from datetime import timedelta

def send_email_postal(campaign, recipient, subject, body_plain, body_html, pdf_bytes, pdf_filename, manual_attachment_bytes=None, manual_attachment_filename=None):
    postal_url = os.environ.get('POSTAL_API_URL')
    if not postal_url:
        logging.error("POSTAL_API_URL not set")
        return False, "POSTAL_API_URL not set"

    api_key = campaign.smtp_pass
    if not api_key:
        logging.error("Postal API key not set in campaign")
        return False, "Postal API key not set in campaign"

    endpoint = f"{postal_url.rstrip('/')}/api/v1/send/message"
    headers = {
        'X-Server-API-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    payload = {
        'to': [recipient.email],
        'from': f"{campaign.sender_name} <{campaign.sender_email}>",
        'reply_to': campaign.reply_to,
        'subject': subject,
        'plain_body': body_plain,
        'html_body': body_html,
        'attachments': []
    }

    if pdf_bytes and campaign.attach_pdf:
        payload['attachments'].append({
            'name': pdf_filename,
            'content_type': 'application/pdf',
            'data': base64.b64encode(pdf_bytes).decode('utf-8')
        })
    
    if manual_attachment_bytes and manual_attachment_filename:
        payload['attachments'].append({
            'name': manual_attachment_filename,
            'content_type': 'application/octet-stream',
            'data': base64.b64encode(manual_attachment_bytes).decode('utf-8')
        })

    logging.info(f"Attempting to send email via Postal to {recipient.email} at endpoint {endpoint}")

    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        logging.info(f"Successfully sent email to {recipient.email} via Postal")
        return True, "Sent via Postal"
    except requests.exceptions.RequestException as e:
        logging.error(f"Postal API error for {recipient.email}: {e}", exc_info=True)
        return False, f"Postal API error: {e}"

def send_email_smtp(campaign, recipient, subject, body_plain, body_html, pdf_bytes, pdf_filename, manual_attachment_bytes=None, manual_attachment_filename=None):
    if not campaign.smtp_host:
        logging.error("SMTP host is not configured for this campaign.")
        return False, "SMTP host is not configured for this campaign."
    
    logging.info(f"Attempting to send email via SMTP to {recipient.email} using host {campaign.smtp_host}:{campaign.smtp_port}")

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{campaign.sender_name} <{campaign.sender_email}>"
    if campaign.reply_to:
        msg.add_header('Reply-To', campaign.reply_to)
    msg['To'] = recipient.email
    msg.set_content(body_plain)
    if body_html:
        msg.add_alternative(body_html, subtype='html')
    if pdf_bytes and campaign.attach_pdf:
        msg.add_attachment(pdf_bytes, maintype='application', subtype='pdf', filename=pdf_filename)
    
    if manual_attachment_bytes and manual_attachment_filename:
        maintype, subtype = mimetypes.guess_type(manual_attachment_filename)[0].split('/')
        msg.add_attachment(manual_attachment_bytes, maintype=maintype, subtype=subtype, filename=manual_attachment_filename)

    retries = 3
    for i in range(retries):
        try:
            with smtplib.SMTP(campaign.smtp_host, campaign.smtp_port, timeout=30) as smtp:
                if campaign.use_starttls:
                    smtp.starttls()
                    smtp.ehlo()
                
                logging.info(f"SMTP credentials provided: user='{campaign.smtp_user}', pass provided: {'yes' if campaign.smtp_pass else 'no'}")
                
                # Always attempt login if credentials are provided, regardless of AUTH advertisement
                if campaign.smtp_user and campaign.smtp_pass:
                    logging.info("Attempting SMTP login...")
                    smtp.login(campaign.smtp_user, campaign.smtp_pass)
                    logging.info("SMTP login successful.")
                else:
                    logging.info("Skipping SMTP login as credentials are not provided.")

                smtp.send_message(msg)
            logging.info(f"Successfully sent email to {recipient.email} via SMTP")
            return True, "Sent"
        except (smtplib.SMTPServerDisconnected, socket.timeout, ConnectionRefusedError) as e:
            logging.error(f"Attempt {i+1}/{retries}: Failed to send email to {recipient.email} via SMTP: {e}", exc_info=True)
            if i < retries - 1:
                time.sleep(5 * (i + 1)) # Exponential backoff
            else:
                return False, str(e)
        except Exception as e:
            logging.error(f"Failed to send email to {recipient.email} via SMTP: {e}", exc_info=True)
            return False, str(e)

def generate_attachment_filename(original_filename, recipient_email, campaign_name):
    now_str = datetime.utcnow().strftime("%Y%m%d")
    recipient_prefix = recipient_email.split('@')[0]
    file_extension = os.path.splitext(original_filename)[1]
    # Sanitize campaign_name to be safe for filenames
    safe_campaign_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', campaign_name)
    return f"{now_str}-{safe_campaign_name}-{recipient_prefix}{file_extension}"

def sender_worker_thread():
    logging.info("Sender worker thread started.")
    while True:
        logging.info("Sender worker thread: checking for campaigns.")
        with app.app_context():
            now = datetime.utcnow()
            campaigns = db.session.query(Campaign).filter(
                (Campaign.status.in_(['running', 'queued'])) |
                ((Campaign.status == 'scheduled') & (Campaign.next_send_time <= now))
            ).all()

            logging.info(f"Sender worker thread: found {len(campaigns)} campaigns to process.")

            for c in campaigns:
                if c.daily_limit > 0:
                    daily_sent_count = db.session.query(SendLog).filter(SendLog.campaign_id == c.id, SendLog.timestamp >= now - timedelta(days=1)).count()
                    if daily_sent_count >= c.daily_limit:
                        continue

                if c.hourly_limit > 0:
                    hourly_sent_count = db.session.query(SendLog).filter(SendLog.campaign_id == c.id, SendLog.timestamp >= now - timedelta(hours=1)).count()
                    if hourly_sent_count >= c.hourly_limit:
                        continue
                elif c.minute_limit > 0:
                    minute_sent_count = db.session.query(SendLog).filter(SendLog.campaign_id == c.id, SendLog.timestamp >= now - timedelta(minutes=1)).count()
                    if minute_sent_count >= c.minute_limit:
                        continue

                recipient = db.session.query(Recipient).filter_by(campaign_id=c.id, sent=False).first()

                if not recipient:
                    if c.schedule_type == 'now' or c.schedule_type == 'once':
                        c.status = 'completed'
                    elif c.schedule_type == 'daily':
                        c.next_send_time += timedelta(days=1)
                        # Reset recipients for next send
                        for r in db.session.query(Recipient).filter_by(campaign_id=c.id).all():
                            r.sent = False
                    elif c.schedule_type == 'weekly':
                        c.next_send_time += timedelta(weeks=1)
                        # Reset recipients for next send
                        for r in db.session.query(Recipient).filter_by(campaign_id=c.id).all():
                            r.sent = False
                    
                    db.session.commit()
                    continue

                delay = random.uniform(c.min_delay, c.max_delay)
                time.sleep(delay)

                subjects = c.subjects_raw.splitlines()
                subject = random.choice(subjects) if subjects else ''
                subject = replace_tags(subject, recipient.email)
                
                body_plain = replace_tags(c.body_plain, recipient.email)
                body_html = replace_tags(c.body_html, recipient.email)
                
                pdf_bytes = None
                if c.attach_pdf and c.pdf_html_template:
                    html_for_pdf = replace_tags(c.pdf_html_template, recipient.email)
                    try:
                        pdf_bytes = html_to_pdf_bytes(html_for_pdf)
                    except Exception as e:
                        logging.error(f"pdf conversion failed: {e}")

                pdf_filename = None
                if pdf_bytes:
                    pdf_filename = generate_attachment_filename("document.pdf", recipient.email, c.name)

                manual_attachment_bytes = None
                manual_attachment_filename = None

                # Prioritize uploaded attachment over manual_attachment_path
                attachment_to_use = c.uploaded_attachment_path if c.uploaded_attachment_path else c.manual_attachment_path

                if attachment_to_use:
                    try:
                        with open(attachment_to_use, 'rb') as f:
                            manual_attachment_bytes = f.read()
                        original_manual_filename = os.path.basename(attachment_to_use)
                        manual_attachment_filename = generate_attachment_filename(original_manual_filename, recipient.email, c.name)
                    except Exception as e:
                        logging.error(f"Failed to read manual/uploaded attachment: {e}")

                if c.use_postal:
                    success, message = send_email_postal(c, recipient, subject, body_plain, body_html, pdf_bytes, pdf_filename, manual_attachment_bytes, manual_attachment_filename)
                else:
                    success, message = send_email_smtp(c, recipient, subject, body_plain, body_html, pdf_bytes, pdf_filename, manual_attachment_bytes, manual_attachment_filename)

                attachment_names = []
                if pdf_filename:
                    attachment_names.append(pdf_filename)
                if manual_attachment_filename:
                    attachment_names.append(manual_attachment_filename)
                
                attachment_name_str = ", ".join(attachment_names)

                log = SendLog(
                    campaign_id=c.id,
                    recipient=recipient.email,
                    subject=subject,
                    attachment_name=attachment_name_str,
                    status='sent' if success else 'failed',
                    message=message
                )
                db.session.add(log)

                recipient.sent = True
                if not success:
                    recipient.last_error = message
                
                db.session.commit()
                
                wait_time = 60 + random.uniform(c.min_delay, c.max_delay)
                time.sleep(wait_time)

        time.sleep(random.randint(1, 10))

def start_sender():
    thread = threading.Thread(target=sender_worker_thread)
    thread.daemon = True
    thread.start()

start_sender()

start_keepalive()

@app.route('/')
def index():
    campaigns = db.session.query(Campaign).order_by(Campaign.created_at.desc()).all()
    last_campaign = campaigns[0] if campaigns else None
    return render_template('index.html', campaigns=campaigns, last_campaign=last_campaign)

@app.route('/create_campaign', methods=['POST'])
def create_campaign():
    try:
        name = request.form.get('name') or 'campaign'
        use_postal = bool(request.form.get('postal_api'))
        schedule_type = request.form.get('schedule_type', 'now')
        schedule_time_str = request.form.get('schedule_time')
        schedule_time = datetime.fromisoformat(schedule_time_str) if schedule_time_str else None

        next_send_time = datetime.utcnow()
        status = 'running'
        if schedule_type != 'now' and schedule_time:
            next_send_time = schedule_time
            status = 'scheduled'

        body_html = request.form.get('body_html') or ''
        body_plain = body_html
        body_html = body_html.replace('\n', '<br>')

        uploaded_attachment_path = ''
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file.filename != '':
                upload_folder = os.path.join(app.instance_path, 'uploads')
                os.makedirs(upload_folder, exist_ok=True)
                filename = secure_filename(file.filename)
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                uploaded_attachment_path = file_path

        c = Campaign(
            uid=random_id(),
            name=name,
            sender_name=request.form.get('sender_name'),
            sender_email=request.form.get('sender_email'),
            reply_to=request.form.get('reply_to'),
            subjects_raw=request.form.get('subjects') or '',
            body_plain=body_plain,
            body_html=body_html,
            html_template=request.form.get('html_template') or '',
            pdf_html_template=request.form.get('pdf_html_template') or '',
            min_delay=int(request.form.get('min_delay') or 1),
            max_delay=int(request.form.get('max_delay') or 5),
            status=status,
            hourly_limit=int(request.form.get('hourly_limit') or 100),
            daily_limit=int(request.form.get('daily_limit') or 1000),
            smtp_host=request.form.get('smtp_host'),
            smtp_port=int(request.form.get('smtp_port') or 587),
            smtp_user=request.form.get('smtp_user'),
            smtp_pass=request.form.get('smtp_pass'),
            use_postal=use_postal,
            attach_pdf=bool(request.form.get('attach_pdf')),
            manual_attachment_path=request.form.get('manual_attachment_path') or '',
            uploaded_attachment_path=uploaded_attachment_path,
            schedule_type=schedule_type,
            schedule_time=schedule_time,
            next_send_time=next_send_time,
            use_starttls=bool(request.form.get('use_starttls')),
            minute_limit=int(request.form.get('minute_limit') or 10)
        )
        db.session.add(c)
        db.session.commit()
        for r in (request.form.get('recipients') or '').splitlines():
            r = r.strip()
            if not r: continue
            db.session.add(Recipient(campaign_id=c.id, email=r))
        db.session.commit()
        return jsonify({'ok':True,'id':c.id})
    except Exception as e:
        logging.error(f"Error creating campaign: {e}")
        return jsonify({'ok':False, 'error': str(e)}), 400

@app.route('/api/dashboard')
def api_dashboard():
    campaigns = db.session.query(Campaign).all()
    running = sum(1 for c in campaigns if c.status in ('running','queued'))
    sent = db.session.query(SendLog).filter_by(status='sent').count()
    failed = db.session.query(SendLog).filter_by(status='failed').count()
    pie = [sum(1 for c in campaigns if c.status=='running'), sum(1 for c in campaigns if c.status=='queued'), sum(1 for c in campaigns if c.status=='paused'), sum(1 for c in campaigns if c.status=='completed')]
    return jsonify({'running':running,'sent':sent,'failed':failed,'pie':pie})

@app.route('/history')
def history():
    logs = db.session.query(SendLog).order_by(SendLog.timestamp.desc()).limit(100).all()
    return render_template('history.html', logs=logs)

@app.route('/campaign/<campaign_uid>/history')
def campaign_history(campaign_uid):
    campaign = db.session.query(Campaign).filter_by(uid=campaign_uid).first_or_404()
    logs = db.session.query(SendLog).filter_by(campaign_id=campaign.id).order_by(SendLog.timestamp.desc()).all()
    return render_template('history.html', logs=logs, campaign=campaign)

@app.route('/logs')
def view_logs():
    try:
        with open('logs/log.txt', 'r') as f:
            logs = f.read()
    except FileNotFoundError:
        logs = "Log file not found."
    return render_template('logs.html', logs=logs)

@app.route('/campaign/<campaign_uid>/delete', methods=['POST'])
def delete_campaign(campaign_uid):
    campaign = db.session.query(Campaign).filter_by(uid=campaign_uid).first_or_404()
    
    db.session.query(Recipient).filter_by(campaign_id=campaign.id).delete()
    db.session.query(SendLog).filter_by(campaign_id=campaign.id).delete()
    
    db.session.delete(campaign)
    db.session.commit()
    
    return redirect(url_for('index'))

@app.route('/tags')
def view_tags():
    return render_template('tags.html')

if __name__=='__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)