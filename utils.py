import random
from datetime import datetime
import logging
import re


FIRST_NAMES = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles", "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
STREET_NAMES = ["Main St", "Highland Ave", "Maple Ave", "Oak St", "Park Ave", "Pine St", "Elm St", "Washington St", "Lake St", "Hill St"]
FLORIDA_CITIES = ["Miami", "Orlando", "Tampa", "Jacksonville", "St. Petersburg", "Hialeah", "Tallahassee", "Fort Lauderdale", "Port St. Lucie", "Cape Coral"]
BODY_TEMPLATES = [
    "Dear #fullname#,\n\nAttached is the document you requested.\n\nPlease let us know if you have any questions.\n\nThank you.",
    "Hello #fullname#,\n\nYour document is ready for download.\n\nThank you for your patience.",
    "Hi #fullname#,\n\nWe have an important document for you. Please find it attached.\n\nSincerely,\nThe Team",
]

def random_id(length=10):
    return ''.join(random.choices('0123456789', k=length))

def replace_tags(text, recipient_email):
    out = text or ''
    
    # Generate random data
    full_name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    random_num = str(random.randint(10000000, 99999999))
    street_number = random.randint(100, 9999)
    street_name = random.choice(STREET_NAMES)
    city = random.choice(FLORIDA_CITIES)
    zip_code = random.randint(32003, 34997)
    address = f"{street_number} {street_name}, {city}, FL {zip_code}"
    
    # Replace tags
    out = re.sub('#email#', recipient_email, out, flags=re.IGNORECASE)
    out = re.sub('#fullname#', full_name, out, flags=re.IGNORECASE)
    out = re.sub('#num#', random_num, out, flags=re.IGNORECASE)
    out = re.sub('#address#', address, out, flags=re.IGNORECASE)
    
    # Handle #ranbody# separately to include other tags
    if '#ranbody#' in out.lower():
        ran_body_template = random.choice(BODY_TEMPLATES)
        email_prefix = recipient_email.split('@')[0]
        ran_body = ran_body_template.replace('#fullname#', email_prefix)
        ran_body = ran_body.replace('#email#', recipient_email)
        ran_body = ran_body.replace('#address#', address)
        out = re.sub('#ranbody#', ran_body, out, flags=re.IGNORECASE)

    out = re.sub('#date#', datetime.utcnow().strftime('%Y-%m-%d'), out, flags=re.IGNORECASE)
    out = re.sub('#time#', datetime.utcnow().strftime('%H:%M:%S'), out, flags=re.IGNORECASE)
    
    return out

from xhtml2pdf import pisa
from io import BytesIO

def html_to_pdf_bytes(html):
    result = BytesIO()
    pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=result)
    return result.getvalue()