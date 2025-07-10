from dotenv import load_dotenv
load_dotenv()
import os
import json
from flask import Flask, render_template, request, jsonify, redirect, Response, session
from notion_client import Client
import cold_emailer
import markupsafe
import smtplib
from datetime import datetime
import threading
import time
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'changeme')

# Load default email template
default_email_template = ""
try:
    with open('email_template.txt', 'r', encoding='utf-8') as f:
        default_email_template = f.read()
except Exception as e:
    print(f"Error loading email template: {str(e)}")
    default_email_template = "Hey {name},\n\nI hope this email finds you well. I noticed you're at {company} and thought you might be interested in our services.\n\nBest regards,\nNadra"

# Load default follow-up email template
default_followup_template = ""
try:
    with open('followup_template.txt', 'r', encoding='utf-8') as f:
        default_followup_template = f.read()
except Exception as e:
    print(f"Error loading follow-up template: {str(e)}")
    default_followup_template = "Hey {name},\n\nI wanted to follow up on my previous email about {company}. I know you're busy, so I'll keep this brief.\n\nDid you get a chance to review my initial message? I'd love to hear your thoughts or schedule a quick call if you're interested.\n\nLooking forward to connecting!\n\nBest regards,\nNadra"

# Global dictionary to store progress per session
import_progress = {}

@app.before_request
def ensure_session_id():
    if 'import_session_id' not in session:
        session['import_session_id'] = str(uuid.uuid4())

@app.route('/')
def index():
    # Redirect to cold emails page as default
    return redirect('/cold-emails')

@app.route('/cold-emails')
def cold_emails():
    # Load existing configuration
    config = {}
    if os.path.exists('config.json'):
        with open('config.json', 'r') as f:
            config = json.load(f)
    
    return render_template('cold_emails.html', 
                         config=config,
                         default_email_template=default_email_template)

@app.route('/followup-emails')
def followup_emails():
    # Load existing configuration
    config = {}
    if os.path.exists('config.json'):
        with open('config.json', 'r') as f:
            config = json.load(f)
    
    return render_template('followup_emails.html', 
                         config=config,
                         default_email_template=default_email_template,
                         default_followup_template=default_followup_template)

@app.route('/import-leads')
def import_leads():
    # Load existing configuration
    config = {}
    if os.path.exists('config.json'):
        with open('config.json', 'r') as f:
            config = json.load(f)
    
    return render_template('import_leads.html', 
                         config=config)

@app.route('/cold-emails', methods=['POST'])
def handle_cold_emails():
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
    print("COLD EMAILS FORM SUBMISSION DEBUG")
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
            
            return render_template('cold_emails.html', 
                                config=config,
                                default_email_template=default_email_template,
                                success_message=f"{notion_success}<br>{zoho_success}")
        except Exception as e:
            return render_template('cold_emails.html', 
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
            return render_template('cold_emails.html', 
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
                            lead_id=lead['id'] if not test_mode else None,  # Only update Notion if not in test mode
                            test_mode=test_mode
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
            return render_template('cold_emails.html', 
                                config=config,
                                default_email_template=default_email_template,
                                error_message=str(e))

@app.route('/followup-emails', methods=['POST'])
def handle_followup_emails():
    action = request.form.get('action')
    
    # Get form data
    notion_api_key = request.form.get('notion_api_key')
    notion_database_id = request.form.get('notion_database_id')
    zoho_email = request.form.get('zoho_email')
    zoho_app_password = request.form.get('zoho_app_password')
    lead_limit = request.form.get('lead_limit')
    followup_template = request.form.get('followup_template')
    followup_subject = request.form.get('followup_subject')
    test_mode = 'test_mode' in request.form  # Check if checkbox is checked
    
    print("\n" + "="*50)
    print("FOLLOW-UP EMAILS FORM SUBMISSION DEBUG")
    print("="*50)
    print(f"Action: {action}")
    print(f"Test mode checkbox state: {test_mode}")
    print(f"Test mode in form: {'test_mode' in request.form}")
    print("="*50 + "\n")
    
    # Store configuration (include Zoho settings for test mode)
    config = {
        'notion_api_key': notion_api_key,
        'notion_database_id': notion_database_id,
        'zoho_email': zoho_email,
        'zoho_app_password': zoho_app_password,
        'lead_limit': lead_limit,
        'followup_template': followup_template,
        'followup_subject': followup_subject,
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
            
            # Test Zoho SMTP connection if credentials provided
            if zoho_email and zoho_app_password:
                emailer = cold_emailer.ColdEmailer(
                    notion_api_key=notion_api_key,
                    notion_database_id=notion_database_id
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
                
                return render_template('followup_emails.html', 
                                    config=config,
                                    default_email_template=default_email_template,
                                    default_followup_template=default_followup_template,
                                    success_message=f"{notion_success}<br>{zoho_success}")
            else:
                return render_template('followup_emails.html', 
                                    config=config,
                                    default_email_template=default_email_template,
                                    default_followup_template=default_followup_template,
                                    success_message=notion_success)
        except Exception as e:
            return render_template('followup_emails.html', 
                                config=config,
                                default_email_template=default_email_template,
                                default_followup_template=default_followup_template,
                                error_message=str(e))
    
    elif action == 'preview_followup':
        try:
            # Initialize the cold emailer
            emailer = cold_emailer.ColdEmailer(
                notion_api_key=notion_api_key,
                notion_database_id=notion_database_id
            )
            
            # Get leads ready for follow-up
            leads = emailer.get_leads_for_followup(limit=int(lead_limit) if lead_limit else None)
            
            preview_leads = []
            for lead in leads:
                try:
                    name = lead.get('properties', {}).get('Name', {}).get('title', [{}])[0].get('text', {}).get('content', '')
                    email = lead.get('properties', {}).get('Email', {}).get('email', '')
                    company = lead.get('properties', {}).get('Organisation', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
                    contacted_date = lead.get('properties', {}).get('Contacted Date', {}).get('date', {}).get('start', '')
                    
                    # Generate follow-up draft
                    draft = emailer.generate_followup_draft(lead, followup_template, followup_subject)
                    
                    if draft:
                        preview_leads.append({
                            'name': name,
                            'email': email,
                            'company': company,
                            'contacted_date': contacted_date,
                            'subject': draft['subject'],
                            'content': draft['content']
                        })
                except Exception as e:
                    print(f"Error processing follow-up lead: {str(e)}")
            
            return render_template('followup_preview.html', 
                                leads=preview_leads,
                                config=config,
                                default_email_template=default_email_template,
                                default_followup_template=default_followup_template)
        except Exception as e:
            return render_template('followup_emails.html', 
                                config=config,
                                default_email_template=default_email_template,
                                default_followup_template=default_followup_template,
                                error_message=str(e))
    
    elif action == 'generate_followup':
        try:
            # Set environment variables for Zoho SMTP (needed for both test mode and production)
            if zoho_email and zoho_app_password:
                os.environ['ZOHO_EMAIL'] = zoho_email
                os.environ['ZOHO_APP_PASSWORD'] = zoho_app_password
            
            # Initialize the cold emailer
            emailer = cold_emailer.ColdEmailer(
                notion_api_key=notion_api_key,
                notion_database_id=notion_database_id
            )
            
            # Get leads ready for follow-up
            leads = emailer.get_leads_for_followup(limit=int(lead_limit) if lead_limit else None)
            
            followup_results = []
            for lead in leads:
                try:
                    name = lead.get('properties', {}).get('Name', {}).get('title', [{}])[0].get('text', {}).get('content', '')
                    email = lead.get('properties', {}).get('Email', {}).get('email', '')
                    company = lead.get('properties', {}).get('Organisation', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
                    contacted_date = lead.get('properties', {}).get('Contacted Date', {}).get('date', {}).get('start', '')
                    
                    # Generate follow-up draft
                    draft = emailer.generate_followup_draft(lead, followup_template, followup_subject)
                    
                    if draft:
                        stored = False
                        test_email_sent = False
                        email_sent = False
                        
                        if test_mode and zoho_email and zoho_app_password:
                            # Test mode: send test email to user's email
                            try:
                                test_email_sent = emailer.send_email(
                                    to_email=zoho_email,
                                    subject=draft['subject'],
                                    content=draft['content'],
                                    lead_id=None,  # Don't update Notion for test emails
                                    test_mode=True,
                                    is_followup=True
                                )
                            except Exception as e:
                                print(f"Error sending test email: {str(e)}")
                                test_email_sent = False
                        elif not test_mode and zoho_email and zoho_app_password:
                            # Production mode: send email to lead, store draft, and update Follow-Up Date
                            try:
                                # Send email to the actual lead
                                email_sent = emailer.send_email(
                                    to_email=email,
                                    subject=draft['subject'],
                                    content=draft['content'],
                                    lead_id=lead['id'],
                                    test_mode=False,
                                    is_followup=True
                                )
                                
                                # Store follow-up draft in Notion
                                stored = emailer.store_followup_draft(
                                    lead_id=lead['id'],
                                    subject=draft['subject'],
                                    content=draft['content']
                                )
                                
                                # Update Follow-Up Date column
                                if email_sent:
                                    current_date = datetime.now().isoformat()
                                    emailer.notion.pages.update(
                                        page_id=lead['id'],
                                        properties={
                                            "Follow-Up Date": {
                                                "date": {
                                                    "start": current_date
                                                }
                                            }
                                        }
                                    )
                            except Exception as e:
                                print(f"Error sending follow-up email: {str(e)}")
                                email_sent = False
                                stored = False
                        
                        followup_results.append({
                            'name': name,
                            'email': email,
                            'company': company,
                            'contacted_date': contacted_date,
                            'subject': draft['subject'],
                            'content': draft['content'],
                            'stored': stored,
                            'is_test': test_mode,
                            'test_email_sent': test_email_sent,
                            'email_sent': email_sent
                        })
                except Exception as e:
                    print(f"Error processing follow-up lead: {str(e)}")
                    followup_results.append({
                        'name': 'Error',
                        'email': str(e),
                        'company': 'N/A',
                        'contacted_date': 'N/A',
                        'subject': 'Error',
                        'content': 'Error generating follow-up draft',
                        'stored': False,
                        'is_test': test_mode,
                        'test_email_sent': False,
                        'email_sent': False
                    })
            
            return render_template('followup_results.html', 
                                results=followup_results,
                                config=config,
                                default_email_template=default_email_template,
                                default_followup_template=default_followup_template)
        except Exception as e:
            return render_template('followup_emails.html', 
                                config=config,
                                default_email_template=default_email_template,
                                default_followup_template=default_followup_template,
                                error_message=str(e))

@app.route('/import-leads', methods=['POST'])
def handle_import_leads():
    action = request.form.get('action')
    
    # Get form data
    notion_api_key = request.form.get('notion_api_key')
    notion_database_id = request.form.get('notion_database_id')
    google_sheets_url = request.form.get('google_sheets_url')
    skip_duplicates = 'skip_duplicates' in request.form
    
    print("\n" + "="*50)
    print("IMPORT LEADS FORM SUBMISSION DEBUG")
    print("="*50)
    print(f"Action: {action}")
    print(f"Google Sheets URL: {google_sheets_url}")
    print(f"Skip duplicates: {skip_duplicates}")
    print("="*50 + "\n")
    
    # Store configuration
    config = {
        'notion_api_key': notion_api_key,
        'notion_database_id': notion_database_id,
        'google_sheets_url': google_sheets_url,
        'skip_duplicates': skip_duplicates
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
            
            return render_template('import_leads.html', 
                                config=config,
                                success_message=notion_success)
        except Exception as e:
            return render_template('import_leads.html', 
                                config=config,
                                error_message=str(e))
    
    elif action == 'preview':
        try:
            # Extract spreadsheet ID from Google Sheets URL
            import re
            spreadsheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', google_sheets_url)
            if not spreadsheet_id_match:
                return render_template('import_leads.html', 
                                    config=config,
                                    error_message="Invalid Google Sheets URL format")
            
            spreadsheet_id = spreadsheet_id_match.group(1)
            
            # Read Google Sheets data
            import requests
            
            # Convert to CSV export URL
            csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
            
            response = requests.get(csv_url)
            if response.status_code != 200:
                return render_template('import_leads.html', 
                                    config=config,
                                    error_message="Could not access Google Sheet. Make sure it's publicly accessible.")
            
            # Parse CSV data
            import csv
            import io
            
            csv_content = response.text
            csv_reader = csv.DictReader(io.StringIO(csv_content))
            
            # Collect all leads
            all_leads = []
            for row in csv_reader:
                all_leads.append({
                    'first_name': row.get('First Name', ''),
                    'last_name': row.get('Last Name', ''),
                    'email': row.get('E-mail', ''),
                    'company_phone': row.get('Company Phone Number', ''),
                    'company_name': row.get('Company Name', ''),
                    'website': row.get('Website', ''),
                    'linkedin': row.get('Linkedin', ''),
                    'category': row.get('Category', ''),
                    'title': row.get('Title', ''),
                    'location': row.get('Location', ''),
                    'funded_year': row.get('Funded Year', '')
                })
            
            return render_template('import_preview.html', 
                                leads=all_leads,
                                config=config,
                                total_rows=len(all_leads))
        except Exception as e:
            return render_template('import_leads.html', 
                                config=config,
                                error_message=f"Error processing Google Sheet: {str(e)}")
    
    elif action == 'import':
        try:
            # Extract spreadsheet ID from Google Sheets URL
            import re
            spreadsheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', google_sheets_url)
            if not spreadsheet_id_match:
                return render_template('import_leads.html', 
                                    config=config,
                                    error_message="Invalid Google Sheets URL format")
            
            spreadsheet_id = spreadsheet_id_match.group(1)
            
            # Initialize Notion client
            notion = Client(auth=notion_api_key)
            
            # Read Google Sheets data
            import requests
            
            # Convert to CSV export URL
            csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
            
            response = requests.get(csv_url)
            if response.status_code != 200:
                return render_template('import_leads.html', 
                                    config=config,
                                    error_message="Could not access Google Sheet. Make sure it's publicly accessible.")
            
            # Parse CSV data
            import csv
            import io
            
            csv_content = response.text
            csv_reader = csv.DictReader(io.StringIO(csv_content))
            
            # Get existing emails if skip_duplicates is enabled
            existing_emails = set()
            if skip_duplicates:
                try:
                    response = notion.databases.query(database_id=notion_database_id)
                    for page in response.get('results', []):
                        email = page.get('properties', {}).get('Email', {}).get('email', '')
                        if email:
                            existing_emails.add(email.lower())
                except Exception as e:
                    print(f"Warning: Could not fetch existing emails: {str(e)}")
            
            # Import leads
            imported_count = 0
            skipped_count = 0
            error_count = 0
            
            for row in csv_reader:
                try:
                    first_name = row.get('First Name', '').strip()
                    last_name = row.get('Last Name', '').strip()
                    email = row.get('E-mail', '').strip()
                    company_phone = row.get('Company Phone Number', '').strip()
                    company_name = row.get('Company Name', '').strip()
                    website = row.get('Website', '').strip()
                    linkedin = row.get('Linkedin', '').strip()
                    title = row.get('Title', '').strip()
                    location = row.get('Location', '').strip()
                    category = row.get('Category', '').strip()
                    funded_year = row.get('Funded Year', '').strip()
                    
                    # Skip if required fields are empty
                    if not first_name or not last_name or not email:
                        error_count += 1
                        continue
                    
                    # Skip duplicates if enabled
                    if skip_duplicates and email.lower() in existing_emails:
                        skipped_count += 1
                        continue
                    
                    # Combine first and last name
                    full_name = f"{first_name} {last_name}".strip()
                    
                    # Create lead in Notion
                    properties = {
                        "Name": {
                            "title": [
                                {
                                    "text": {
                                        "content": full_name
                                    }
                                }
                            ]
                        },
                        "Email": {
                            "email": email
                        },
                        "Phone": {
                            "phone_number": company_phone
                        } if company_phone else None,
                        "Title": {
                            "rich_text": [
                                {
                                    "text": {
                                        "content": title
                                    }
                                }
                            ]
                        } if title else None,
                        "Organisation": {
                            "rich_text": [
                                {
                                    "text": {
                                        "content": company_name
                                    }
                                }
                            ]
                        } if company_name else None,
                        "Website": {
                            "url": website if website.startswith(('http://', 'https://')) else f'https://{website}'
                        } if website else None,
                        "Social Media": {
                            "url": linkedin if linkedin.startswith(('http://', 'https://')) else f'https://{linkedin}'
                        } if linkedin else None,
                        "Location": {
                            "rich_text": [
                                {
                                    "text": {
                                        "content": location
                                    }
                                }
                            ]
                        } if location else None,
                        "Industry": {
                            "rich_text": [
                                {
                                    "text": {
                                        "content": category
                                    }
                                }
                            ]
                        } if category else None,
                        "Lead Source": {
                            "select": {"name": "Cold Outreach"}
                        },
                        "Status": {
                            "status": {"name": "Not contacted"}
                        }
                    }
                    # Remove None values (for optional fields not present)
                    properties = {k: v for k, v in properties.items() if v is not None}
                    
                    # Create the page
                    notion.pages.create(
                        parent={"database_id": notion_database_id},
                        properties=properties
                    )
                    
                    imported_count += 1
                    
                    # Add to existing emails set to prevent duplicates within the same import
                    if skip_duplicates:
                        existing_emails.add(email.lower())
                        
                except Exception as e:
                    print(f"Error importing lead {first_name} {last_name}: {str(e)}")
                    error_count += 1
            
            success_message = f"Import completed! Imported {imported_count} leads"
            if skipped_count > 0:
                success_message += f", skipped {skipped_count} duplicates"
            if error_count > 0:
                success_message += f", {error_count} errors"
            
            return render_template('import_leads.html', 
                                config=config,
                                success_message=success_message)
                                
        except Exception as e:
            return render_template('import_leads.html', 
                                config=config,
                                error_message=f"Error during import: {str(e)}")
    
    return render_template('import_leads.html', config=config)

@app.route('/start-import', methods=['POST'])
def start_import():
    # Get session id
    session_id = session.get('import_session_id')
    # Get form data
    notion_api_key = request.form.get('notion_api_key')
    notion_database_id = request.form.get('notion_database_id')
    google_sheets_url = request.form.get('google_sheets_url')
    skip_duplicates = 'skip_duplicates' in request.form
    
    # Parse Google Sheet
    import re, requests, csv, io
    spreadsheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', google_sheets_url)
    if not spreadsheet_id_match:
        return 'Invalid Google Sheets URL', 400
    spreadsheet_id = spreadsheet_id_match.group(1)
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
    response = requests.get(csv_url)
    if response.status_code != 200:
        return 'Could not access Google Sheet', 400
    csv_content = response.text
    csv_reader = csv.DictReader(io.StringIO(csv_content))
    all_leads = list(csv_reader)
    total_leads = len(all_leads)
    
    # Start import in background thread
    def do_import():
        import_progress[session_id] = {'current': 0, 'total': total_leads, 'status': 'starting'}
        try:
            from notion_client import Client
            notion = Client(auth=notion_api_key)
            
            # Get existing emails if skip_duplicates is enabled
            existing_emails = set()
            if skip_duplicates:
                try:
                    import_progress[session_id]['status'] = 'checking_duplicates'
                    resp = notion.databases.query(database_id=notion_database_id)
                    for page in resp.get('results', []):
                        email = page.get('properties', {}).get('Email', {}).get('email', '')
                        if email:
                            existing_emails.add(email.lower())
                except Exception as e:
                    print(f"Warning: Could not fetch existing emails: {str(e)}")
            
            import_progress[session_id]['status'] = 'importing'
            
            # Process leads in batches to reduce memory usage
            batch_size = 10
            for batch_start in range(0, len(all_leads), batch_size):
                batch_end = min(batch_start + batch_size, len(all_leads))
                batch = all_leads[batch_start:batch_end]
                
                for idx, row in enumerate(batch):
                    global_idx = batch_start + idx
                    
                    try:
                        first_name = row.get('First Name', '').strip()
                        last_name = row.get('Last Name', '').strip()
                        email = row.get('E-mail', '').strip()
                        company_phone = row.get('Company Phone Number', '').strip()
                        company_name = row.get('Company Name', '').strip()
                        website = row.get('Website', '').strip()
                        linkedin = row.get('Linkedin', '').strip()
                        title = row.get('Title', '').strip()
                        location = row.get('Location', '').strip()
                        category = row.get('Category', '').strip()
                        funded_year = row.get('Funded Year', '').strip()
                        
                        # Skip if required fields are empty
                        if not first_name or not last_name or not email:
                            import_progress[session_id]['current'] = global_idx + 1
                            continue
                        
                        # Skip duplicates if enabled
                        if skip_duplicates and email.lower() in existing_emails:
                            import_progress[session_id]['current'] = global_idx + 1
                            continue
                        
                        full_name = f"{first_name} {last_name}".strip()
                        properties = {
                            "Name": {"title": [{"text": {"content": full_name}}]},
                            "Email": {"email": email},
                            "Phone": {"phone_number": company_phone} if company_phone else None,
                            "Title": {"rich_text": [{"text": {"content": title}}]} if title else None,
                            "Organisation": {"rich_text": [{"text": {"content": company_name}}]} if company_name else None,
                            "Website": {"url": website if website.startswith(('http://', 'https://')) else f'https://{website}'} if website else None,
                            "Social Media": {"url": linkedin if linkedin.startswith(('http://', 'https://')) else f'https://{linkedin}'} if linkedin else None,
                            "Location": {"rich_text": [{"text": {"content": location}}]} if location else None,
                            "Industry": {"rich_text": [{"text": {"content": category}}]} if category else None,
                            "Lead Source": {"select": {"name": "Cold Outreach"}},
                            "Status": {"status": {"name": "Not contacted"}}
                        }
                        properties = {k: v for k, v in properties.items() if v is not None}
                        
                        # Create the page
                        notion.pages.create(parent={"database_id": notion_database_id}, properties=properties)
                        
                        # Add to existing emails set to prevent duplicates within the same import
                        if skip_duplicates:
                            existing_emails.add(email.lower())
                            
                    except Exception as e:
                        print(f"Error importing lead {global_idx + 1}: {str(e)}")
                    
                    # Update progress less frequently to reduce overhead
                    if global_idx % 5 == 0 or global_idx == len(all_leads) - 1:
                        import_progress[session_id]['current'] = global_idx + 1
                
                # Small delay between batches to prevent overwhelming the API
                time.sleep(0.1)
            
            import_progress[session_id]['current'] = total_leads
            import_progress[session_id]['status'] = 'completed'
            
        except Exception as e:
            print(f"Import error: {str(e)}")
            import_progress[session_id]['status'] = 'error'
            import_progress[session_id]['error'] = str(e)
    
    threading.Thread(target=do_import, daemon=True).start()
    return '', 202

@app.route('/import-progress')
def import_progress_sse():
    session_id = session.get('import_session_id')
    def event_stream():
        last_sent = -1
        last_status = None
        while True:
            prog = import_progress.get(session_id, {'current': 0, 'total': 1, 'status': 'unknown'})
            
            # Send progress update if changed
            if prog['current'] != last_sent or prog.get('status') != last_status:
                data = {
                    "current": prog['current'], 
                    "total": prog['total'],
                    "status": prog.get('status', 'unknown')
                }
                if prog.get('error'):
                    data['error'] = prog['error']
                
                yield f"data: {json.dumps(data)}\n\n"
                last_sent = prog['current']
                last_status = prog.get('status')
            
            # Check if import is complete or failed
            if prog.get('status') in ['completed', 'error'] or prog['current'] >= prog['total']:
                break
            
            time.sleep(0.5)  # Reduced frequency to prevent overwhelming the client
        
        # Send final update
        prog = import_progress.get(session_id, {'current': 0, 'total': 1, 'status': 'unknown'})
        data = {
            "current": prog['current'], 
            "total": prog['total'],
            "status": prog.get('status', 'completed')
        }
        if prog.get('error'):
            data['error'] = prog['error']
        
        yield f"data: {json.dumps(data)}\n\n"
    
    return Response(event_stream(), mimetype='text/event-stream')

# Add nl2br filter
@app.template_filter('nl2br')
def nl2br(value):
    """Convert newlines to HTML line breaks"""
    if value is None:
        return ""
    return markupsafe.Markup(str(value).replace('\n', '<br>'))

if __name__ == '__main__':
    app.run(debug=True) 