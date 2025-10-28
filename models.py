from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

def init_db(app=None):
    if app:
        db.init_app(app)
        with app.app_context():
            db.create_all()

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(200))
    sender_name = db.Column(db.String(200))
    sender_email = db.Column(db.String(200))
    reply_to = db.Column(db.String(200))
    subjects_raw = db.Column(db.Text)
    body_plain = db.Column(db.Text)
    body_html = db.Column(db.Text)
    html_template = db.Column(db.Text)
    pdf_html_template = db.Column(db.Text)
    min_delay = db.Column(db.Integer, default=1)
    max_delay = db.Column(db.Integer, default=5)
    status = db.Column(db.String(50), default='queued')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hourly_limit = db.Column(db.Integer, default=100)
    daily_limit = db.Column(db.Integer, default=1000)
    smtp_host = db.Column(db.String(200))
    smtp_port = db.Column(db.Integer)
    smtp_user = db.Column(db.String(200))
    smtp_pass = db.Column(db.String(200))
    use_postal = db.Column(db.Boolean, default=True)
    attach_pdf = db.Column(db.Boolean, default=False)
    manual_attachment_path = db.Column(db.String(4096))
    uploaded_attachment_path = db.Column(db.String(4096))
    schedule_type = db.Column(db.String(50), default='now')
    schedule_time = db.Column(db.DateTime)
    next_send_time = db.Column(db.DateTime)
    use_starttls = db.Column(db.Boolean, default=True)
    minute_limit = db.Column(db.Integer, default=10)

class Recipient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'))
    email = db.Column(db.String(300))
    sent = db.Column(db.Boolean, default=False)
    last_error = db.Column(db.Text)

class SendLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer)
    recipient = db.Column(db.String(300))
    subject = db.Column(db.String(500))
    attachment_name = db.Column(db.String(500))
    status = db.Column(db.String(50))
    message = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)