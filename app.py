import os
import json
from flask import Flask, render_template, request, jsonify
from notion_client import Client
import cold_emailer
import markupsafe
import smtplib

app = Flask(__name__)

# Load default email template
default_email_template = ""
try:
    with open('email_template.txt', 'r', encoding='utf-8') as f:
        default_email_template = f.read()
except Exception as e:
    print(f"Error loading email template: {str(e)}")
    default_email_template = "Hey {name},\n\nI hope this email finds you well. I noticed you're at {company} and thought you might be interested in our services.\n\nBest regards,\nNadra"

@app.route('/')
def index():
    # Load existing configuration
    config = {}
    if os.path.exists('config.json'):
        with open('config.json', 'r') as f:
            config = json.load(f)
    
    return render_template('index.html', 
                         config=config,
                         default_email_template=default_email_template)

@app.route('/', methods=['POST'])
def handle_post():
    action = request.form.get('action')
    
    # Get form data
    notion_api_key = request.form.get('notion_api_key')
    notion_database_id = request.form.get('notion_database_id')
    zoho_email = request.form.get('zoho_email')
    zoho_app_password = request.form.get('zoho_app_password')
    email_template = request.form.get('email_template', default_email_template)
    email_subject = request.form.get('email_subject', '{name}, you don\'t want to miss this')
    lead_limit = request.form.get('lead_limit')
    test_mode = 'test_mode' in request.form  # Check if checkbox is checked
    
    print("\n" + "="*50)
    print("FORM SUBMISSION DEBUG")
    print("="*50)
    print(f"Action: {action}")
    print(f"Test mode checkbox state: {test_mode}")
    print(f"Test mode in form: {'test_mode' in request.form}")
    print("="*50 + "\n")
    
    # Store configuration
    config = {
        'notion_api_key': notion_api_key,
        'notion_database_id': notion_database_id,
        'zoho_email': zoho_email,
        'zoho_app_password': zoho_app_password,
        'email_template': email_template,
        'email_subject': email_subject,
        'lead_limit': lead_limit,
        'test_mode': test_mode
    }
    
    # Save configuration
    with open('config.json', 'w') as f:
        json.dump(config, f)
    
    if action == 'test':
        try:
            # Test Notion connection
            notion = Client(auth=notion_api_key)
            database = notion.databases.retrieve(database_id=notion_database_id)
            notion_success = f"Successfully connected to Notion database: {database.get('title', [{'plain_text': 'Untitled'}])[0]['plain_text']}"
            
            # Test Zoho SMTP connection

            emailer = cold_emailer.ColdEmailer(
                notion_api_key=notion_api_key,
                
                notion_database_id=notion_database_id,
                email_template=email_template,
                email_subject=email_subject
            )
            
            # Set environment variables for Zoho SMTP
            os.environ['ZOHO_EMAIL'] = zoho_email
            os.environ['ZOHO_APP_PASSWORD'] = zoho_app_password
            
            # Test SMTP connection
            smtp_success = emailer.test_smtp_connection()
            if smtp_success:
                zoho_success = f"Successfully connected to Zoho Mail and sent test email to {zoho_email}"
            else:
                zoho_success = "Failed to connect to Zoho Mail. Please check your credentials and try again."
            
            return render_template('index.html', 
                                config=config,
                                default_email_template=default_email_template,
                                success_message=f"{notion_success}<br>{zoho_success}")
        except Exception as e:
            return render_template('index.html', 
                                config=config,
                                default_email_template=default_email_template,
                                error_message=str(e))
    
    elif action == 'preview':
        try:
            # Set environment variables for Zoho SMTP
            os.environ['ZOHO_EMAIL'] = zoho_email
            os.environ['ZOHO_APP_PASSWORD'] = zoho_app_password
            
            # Get leads to be processed
            emailer = cold_emailer.ColdEmailer(
                notion_api_key=notion_api_key,
                notion_database_id=notion_database_id,
                email_template=email_template,
                email_subject=email_subject
            )
            
            leads = emailer.get_leads_to_contact()
            
            preview_leads = []
            for lead in leads[:int(lead_limit)]:
                try:
                    name = lead.get('properties', {}).get('Name', {}).get('title', [{}])[0].get('text', {}).get('content', '')
                    email = lead.get('properties', {}).get('Email', {}).get('email', '')
                    company = lead.get('properties', {}).get('Organisation', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
                    status = lead.get('properties', {}).get('Status', {}).get('status', {}).get('name', '')
                    
                    # Determine actual recipient email
                    recipient_email = zoho_email if test_mode else email
                    print(f"Processing lead: {name}")
                    print(f"  - Notion email: {email}")
                    print(f"  - Will send to: {recipient_email} {'(Test Mode)' if test_mode else ''}")
                    print(f"  - Company: {company}")
                    print(f"  - Status: {status}")
                    
                    # Generate email draft
                    draft = emailer.generate_email_draft(lead)
                    
                    preview_leads.append({
                        'name': name,
                        'email': recipient_email,
                        'company': company,
                        'status': status,
                        'subject': draft['subject'] if draft else 'Error generating draft',
                        'content': draft['content'] if draft else 'Error generating draft',
                        'is_test': test_mode
                    })
                except Exception as e:
                    print(f"Error processing lead: {str(e)}")
            
            return render_template('preview.html', 
                                leads=preview_leads,
                                config=config,
                                default_email_template=default_email_template)
        except Exception as e:
            print(f"Error in preview: {str(e)}")
            return render_template('index.html', 
                                config=config,
                                default_email_template=default_email_template,
                                error_message=str(e))
    
    elif action == 'run':
        try:
            # Set environment variables for Zoho SMTP
            os.environ['ZOHO_EMAIL'] = zoho_email
            os.environ['ZOHO_APP_PASSWORD'] = zoho_app_password
            
            # Run the cold emailer
            emailer = cold_emailer.ColdEmailer(
                notion_api_key=notion_api_key,
                notion_database_id=notion_database_id,
                email_template=email_template,
                email_subject=email_subject
            )
            
            # Get leads and limit them
            leads = emailer.get_leads_to_contact()
            limited_leads = leads[:int(lead_limit)]
            
            results = []
            for lead in limited_leads:
                try:
                    # Generate draft
                    draft = emailer.generate_email_draft(lead)
                    if draft:
                        # In test mode, send to user's email instead of lead's email
                        original_email = draft['to_email']
                        to_email = zoho_email if test_mode else original_email
                        print(f"\nEmail recipient:")
                        print(f"  - Original lead email: {original_email}")
                        print(f"  - Test mode: {'Yes' if test_mode else 'No'}")
                        print(f"  - Will send to: {to_email}")
                        
                        # Send email
                        sent = emailer.send_email(
                            to_email=to_email,
                            subject=draft['subject'],
                            content=draft['content'],
                            lead_id=lead['id'] if not test_mode else None  # Only update Notion if not in test mode
                        )
                        results.append({
                            'name': draft['to_name'],
                            'email': to_email,
                            'company': draft['company'],
                            'status': 'Sent' if sent else 'Failed',
                            'is_test': test_mode
                        })
                except Exception as e:
                    results.append({
                        'name': 'Error',
                        'email': str(e),
                        'company': 'N/A',
                        'status': 'Error',
                        'is_test': test_mode
                    })
            
            return render_template('results.html', results=results)
        except Exception as e:
            return render_template('index.html', 
                                config=config,
                                default_email_template=default_email_template,
                                error_message=str(e))

# Add nl2br filter
@app.template_filter('nl2br')
def nl2br(value):
    """Convert newlines to HTML line breaks"""
    if value is None:
        return ""
    return markupsafe.Markup(str(value).replace('\n', '<br>'))

if __name__ == '__main__':
    app.run(debug=True) 