import os
import json
from flask import Flask, render_template, request
from cold_emailer import ColdEmailer
from notion_client import Client

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

@app.route('/', methods=['GET', 'POST'])
def index():
    # Load existing config if available
    config_path = 'config.json'
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                config = {}
    # Initialize feedback variables
    db_title = None
    error_message = None
    error_field = None
    if request.method == 'POST':
        # Determine action: test connection or run automation
        action = request.form.get('action')
        # Get and save Notion and Zoho SMTP credentials
        notion_api_key = request.form.get('notion_api_key')
        notion_database_id = request.form.get('notion_database_id')
        sender_email = request.form.get('sender_email')
        zoho_app_password = request.form.get('zoho_app_password')
        config = {
            'notion_api_key': notion_api_key,
            'notion_database_id': notion_database_id,
            'sender_email': sender_email,
            'zoho_app_password': zoho_app_password
        }
        # Persist config
        with open(config_path, 'w') as f:
            json.dump(config, f)
        # Set SMTP credentials in environment for ColdEmailer
        os.environ['SENDER_EMAIL'] = sender_email
        os.environ['ZOHO_APP_PASSWORD'] = zoho_app_password
        # Initialize client with Notion credentials
        emailer = ColdEmailer(notion_api_key, notion_database_id)
        if action == 'test':
            # Test Notion connection
            try:
                db_info = emailer.notion.databases.retrieve(notion_database_id)
                db_title = db_info.get('title', [{}])[0].get('plain_text', '')
                error_message = None
                error_field = None
            except Exception as e:
                msg = str(e).lower()
                if 'authorization' in msg or '401' in msg or 'permission' in msg:
                    error_field = 'notion_api_key'
                    error_message = 'Invalid Notion API Key. Please check your integration token.'
                elif '404' in msg or 'not found' in msg or 'could not find database' in msg:
                    error_field = 'notion_database_id'
                    error_message = 'Notion Database not found. Check ID and sharing with Maily integration.'
                else:
                    error_field = None
                    error_message = 'Error connecting to Notion: ' + str(e)
                db_title = None
            # Test Zoho SMTP connection
            smtp_ok = True
            smtp_error_message = None
            smtp_error_field = None
            try:
                import smtplib
                host = os.getenv('SMTP_HOST', 'smtp.zoho.com')
                port = int(os.getenv('SMTP_PORT', '587'))
                smtp = smtplib.SMTP(host, port, timeout=10)
                smtp.starttls()
                smtp.login(sender_email, zoho_app_password)
                smtp.quit()
            except Exception as e:
                smtp_ok = False
                msg = str(e).lower()
                if 'authentication' in msg or '535' in msg or 'failed' in msg:
                    smtp_error_field = 'zoho_app_password'
                    smtp_error_message = 'Invalid Zoho email or app password.'
                else:
                    smtp_error_field = None
                    smtp_error_message = 'Error connecting to Zoho SMTP: ' + str(e)
            return render_template('index.html', config=config, db_title=db_title,
                                   error_message=error_message, error_field=error_field,
                                   smtp_ok=smtp_ok, smtp_error_message=smtp_error_message,
                                   smtp_error_field=smtp_error_field)
        # Else run the automation
        leads = emailer.get_leads_to_contact()
        results = []
        for lead in leads:
            # Skip if draft exists
            existing = lead.get('properties', {}).get('Cold email draft', {}).get('rich_text', [])
            if existing:
                draft = ''.join(item.get('text', {}).get('content', '') for item in existing)
            else:
                draft = emailer.generate_email_draft(lead)
                emailer.update_notion_with_draft(lead['id'], draft)
            name = lead.get('properties', {}).get('Name', {}).get('title', [{}])[0].get('text', {}).get('content', '')
            company = lead.get('properties', {}).get('Organisation', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
            results.append({'name': name, 'company': company, 'draft': draft})
        return render_template('results.html', results=results)
    # Render form (initial GET)
    return render_template('index.html', config=config, db_title=None,
                           error_message=None, error_field=None)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port) 