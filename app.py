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
import gc
import psutil

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

# Store import tasks to prevent garbage collection
import_tasks = {}

# File-based progress storage for recovery after restarts
import os

def get_memory_usage():
    """Get current memory usage in MB"""
    try:
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024
    except:
        return 0

def check_memory_limit():
    """Check if memory usage is approaching limits and force cleanup if needed"""
    memory_mb = get_memory_usage()
    if memory_mb > 80:  # If memory usage exceeds 80MB
        print(f"WARNING: High memory usage detected: {memory_mb:.1f} MB")
        gc.collect()
        time.sleep(0.5)  # Give GC time to work
        return True
    return False

def save_progress(session_id, progress_data):
    """Save progress to file for recovery after restarts"""
    try:
        progress_file = f"import_progress_{session_id}.json"
        with open(progress_file, 'w') as f:
            json.dump(progress_data, f)
    except Exception as e:
        print(f"Error saving progress: {str(e)}")

def load_progress(session_id):
    """Load progress from file for recovery after restarts"""
    try:
        progress_file = f"import_progress_{session_id}.json"
        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading progress: {str(e)}")
    return None

def cleanup_progress_file(session_id):
    """Clean up progress file after completion"""
    try:
        progress_file = f"import_progress_{session_id}.json"
        if os.path.exists(progress_file):
            os.remove(progress_file)
    except Exception as e:
        print(f"Error cleaning up progress file: {str(e)}")

def stream_leads_from_csv(csv_url):
    """Stream leads from CSV without loading all into memory"""
    import requests, csv, io
    response = requests.get(csv_url)
    if response.status_code != 200:
        raise Exception('Could not access Google Sheet')
    
    csv_content = response.text
    csv_reader = csv.DictReader(io.StringIO(csv_content))
    
    for row in csv_reader:
        yield row

def count_leads_in_csv(csv_url):
    """Count leads in CSV without loading all content into memory"""
    import requests
    response = requests.get(csv_url)
    if response.status_code != 200:
        raise Exception('Could not access Google Sheet')
    
    # Count lines more efficiently
    lines = response.text.split('\n')
    # Remove empty lines and header
    non_empty_lines = [line for line in lines if line.strip()]
    return max(0, len(non_empty_lines) - 1)  # Subtract 1 for header

@app.before_request
def ensure_session_id():
    if 'import_session_id' not in session:
        session['import_session_id'] = str(uuid.uuid4())

@app.route('/')
def index():
    # Redirect to cold emails page as default
    return redirect('/cold-emails')

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

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
    import re
    spreadsheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', google_sheets_url)
    if not spreadsheet_id_match:
        return 'Invalid Google Sheets URL', 400
    spreadsheet_id = spreadsheet_id_match.group(1)
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
    
    # Count total leads without loading all into memory
    try:
        total_leads = count_leads_in_csv(csv_url)
    except Exception as e:
        return f'Could not access Google Sheet: {str(e)}', 400
    
    print(f"Starting import for {total_leads} leads")
    
    # Start import in background thread
    def do_import():
        try:
            print(f"Import thread started for session {session_id}")
            print(f"Memory usage at start: {get_memory_usage():.1f} MB")
            
            # Initialize progress
            progress_data = {'current': 0, 'total': total_leads, 'status': 'starting'}
            import_progress[session_id] = progress_data
            save_progress(session_id, progress_data)
            
            from notion_client import Client
            notion = Client(auth=notion_api_key)
            
            # Get existing emails if skip_duplicates is enabled
            existing_emails = set()
            if skip_duplicates:
                try:
                    print(f"Checking for duplicates...")
                    progress_data['status'] = 'checking_duplicates'
                    import_progress[session_id] = progress_data
                    save_progress(session_id, progress_data)
                    
                    resp = notion.databases.query(database_id=notion_database_id)
                    for page in resp.get('results', []):
                        email = page.get('properties', {}).get('Email', {}).get('email', '')
                        if email:
                            existing_emails.add(email.lower())
                    print(f"Found {len(existing_emails)} existing emails")
                except Exception as e:
                    print(f"Warning: Could not fetch existing emails: {str(e)}")
            
            progress_data['status'] = 'importing'
            import_progress[session_id] = progress_data
            save_progress(session_id, progress_data)
            print(f"Starting import of {total_leads} leads")
            
            # Process leads one by one to minimize memory usage
            imported_count = 0
            skipped_count = 0
            error_count = 0
            
            # Stream leads from CSV instead of loading all into memory
            csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
            
            for lead_idx, row in enumerate(stream_leads_from_csv(csv_url)):
                try:
                    # Extract data with minimal memory usage
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
                    
                    # Skip if required fields are empty
                    if not first_name or not last_name or not email:
                        print(f"Skipping lead {lead_idx + 1}: Missing required fields")
                        error_count += 1
                        progress_data['current'] = lead_idx + 1
                        progress_data['errors'] = error_count
                        import_progress[session_id] = progress_data
                        save_progress(session_id, progress_data)
                        continue
                    
                    # Skip duplicates if enabled
                    if skip_duplicates and email.lower() in existing_emails:
                        print(f"Skipping lead {lead_idx + 1}: Duplicate email")
                        skipped_count += 1
                        progress_data['current'] = lead_idx + 1
                        progress_data['skipped'] = skipped_count
                        import_progress[session_id] = progress_data
                        save_progress(session_id, progress_data)
                        continue
                    
                    # Build properties with minimal memory allocation
                    full_name = f"{first_name} {last_name}".strip()
                    properties = {}
                    
                    # Only add properties that have values
                    properties["Name"] = {"title": [{"text": {"content": full_name}}]}
                    properties["Email"] = {"email": email}
                    properties["Lead Source"] = {"select": {"name": "Cold Outreach"}}
                    properties["Status"] = {"status": {"name": "Not contacted"}}
                    
                    if company_phone:
                        properties["Phone"] = {"phone_number": company_phone}
                    if title:
                        properties["Title"] = {"rich_text": [{"text": {"content": title}}]}
                    if company_name:
                        properties["Organisation"] = {"rich_text": [{"text": {"content": company_name}}]}
                    if website:
                        website_url = website if website.startswith(('http://', 'https://')) else f'https://{website}'
                        properties["Website"] = {"url": website_url}
                    if linkedin:
                        linkedin_url = linkedin if linkedin.startswith(('http://', 'https://')) else f'https://{linkedin}'
                        properties["Social Media"] = {"url": linkedin_url}
                    if location:
                        properties["Location"] = {"rich_text": [{"text": {"content": location}}]}
                    if category:
                        properties["Industry"] = {"rich_text": [{"text": {"content": category}}]}
                    
                    # Create the page
                    notion.pages.create(parent={"database_id": notion_database_id}, properties=properties)
                    
                    # Add to existing emails set to prevent duplicates within the same import
                    if skip_duplicates:
                        existing_emails.add(email.lower())
                    
                    imported_count += 1
                    print(f"Imported lead {lead_idx + 1}: {full_name} ({email})")
                        
                except Exception as e:
                    print(f"Error importing lead {lead_idx + 1}: {str(e)}")
                    error_count += 1
                
                # Update progress after each lead
                progress_data['current'] = lead_idx + 1
                progress_data['imported'] = imported_count
                progress_data['skipped'] = skipped_count
                progress_data['errors'] = error_count
                import_progress[session_id] = progress_data
                save_progress(session_id, progress_data)
                
                # Force garbage collection every 3 leads to keep memory usage very low
                if (lead_idx + 1) % 3 == 0:
                    gc.collect()
                    print(f"Memory usage after lead {lead_idx + 1}: {get_memory_usage():.1f} MB")
                
                # Small delay between leads to be gentle on Render
                time.sleep(0.3)
            
            print(f"Import completed: {imported_count} imported, {skipped_count} skipped, {error_count} errors")
            progress_data['current'] = total_leads
            progress_data['status'] = 'completed'
            progress_data['imported'] = imported_count
            progress_data['skipped'] = skipped_count
            progress_data['errors'] = error_count
            import_progress[session_id] = progress_data
            save_progress(session_id, progress_data)
            
            # Clean up progress file
            cleanup_progress_file(session_id)
            
        except Exception as e:
            print(f"Import error: {str(e)}")
            progress_data['status'] = 'error'
            progress_data['error'] = str(e)
            import_progress[session_id] = progress_data
            save_progress(session_id, progress_data)
    
    # Use non-daemon thread to prevent it from being killed
    import_thread = threading.Thread(target=do_import, daemon=False)
    import_tasks[session_id] = import_thread
    import_thread.start()
    
    return '', 202

@app.route('/resume-import', methods=['POST'])
def resume_import():
    """Resume import from where it left off"""
    session_id = session.get('import_session_id')
    
    # Load progress from file
    progress_data = load_progress(session_id)
    if not progress_data or progress_data.get('status') in ['completed', 'error']:
        return jsonify({'error': 'No active import to resume'})
    
    # Get form data
    notion_api_key = request.form.get('notion_api_key')
    notion_database_id = request.form.get('notion_database_id')
    google_sheets_url = request.form.get('google_sheets_url')
    skip_duplicates = 'skip_duplicates' in request.form
    
    # Parse Google Sheet again
    import re, requests, csv, io
    spreadsheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', google_sheets_url)
    if not spreadsheet_id_match:
        return jsonify({'error': 'Invalid Google Sheets URL'})
    
    spreadsheet_id = spreadsheet_id_match.group(1)
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
    response = requests.get(csv_url)
    if response.status_code != 200:
        return jsonify({'error': 'Could not access Google Sheet'})
    
    # Resume from where we left off
    current_position = progress_data.get('current', 0)
    print(f"Resuming import from position {current_position}")
    
    def resume_import():
        try:
            from notion_client import Client
            notion = Client(auth=notion_api_key)
            
            # Get existing emails if skip_duplicates is enabled
            existing_emails = set()
            if skip_duplicates:
                try:
                    resp = notion.databases.query(database_id=notion_database_id)
                    for page in resp.get('results', []):
                        email = page.get('properties', {}).get('Email', {}).get('email', '')
                        if email:
                            existing_emails.add(email.lower())
                except Exception as e:
                    print(f"Warning: Could not fetch existing emails: {str(e)}")
            
            # Resume progress
            imported_count = progress_data.get('imported', 0)
            skipped_count = progress_data.get('skipped', 0)
            error_count = progress_data.get('errors', 0)
            
            progress_data['status'] = 'importing'
            import_progress[session_id] = progress_data
            save_progress(session_id, progress_data)
            
            # Stream leads from CSV and skip to current position
            csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
            
            for lead_idx, row in enumerate(stream_leads_from_csv(csv_url)):
                # Skip leads that were already processed
                if lead_idx < current_position:
                    continue
                
                try:
                    # Extract data with minimal memory usage
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
                    
                    # Skip if required fields are empty
                    if not first_name or not last_name or not email:
                        print(f"Skipping lead {lead_idx + 1}: Missing required fields")
                        error_count += 1
                        progress_data['current'] = lead_idx + 1
                        progress_data['errors'] = error_count
                        import_progress[session_id] = progress_data
                        save_progress(session_id, progress_data)
                        continue
                    
                    # Skip duplicates if enabled
                    if skip_duplicates and email.lower() in existing_emails:
                        print(f"Skipping lead {lead_idx + 1}: Duplicate email")
                        skipped_count += 1
                        progress_data['current'] = lead_idx + 1
                        progress_data['skipped'] = skipped_count
                        import_progress[session_id] = progress_data
                        save_progress(session_id, progress_data)
                        continue
                    
                    # Build properties with minimal memory allocation
                    full_name = f"{first_name} {last_name}".strip()
                    properties = {}
                    
                    # Only add properties that have values
                    properties["Name"] = {"title": [{"text": {"content": full_name}}]}
                    properties["Email"] = {"email": email}
                    properties["Lead Source"] = {"select": {"name": "Cold Outreach"}}
                    properties["Status"] = {"status": {"name": "Not contacted"}}
                    
                    if company_phone:
                        properties["Phone"] = {"phone_number": company_phone}
                    if title:
                        properties["Title"] = {"rich_text": [{"text": {"content": title}}]}
                    if company_name:
                        properties["Organisation"] = {"rich_text": [{"text": {"content": company_name}}]}
                    if website:
                        website_url = website if website.startswith(('http://', 'https://')) else f'https://{website}'
                        properties["Website"] = {"url": website_url}
                    if linkedin:
                        linkedin_url = linkedin if linkedin.startswith(('http://', 'https://')) else f'https://{linkedin}'
                        properties["Social Media"] = {"url": linkedin_url}
                    if location:
                        properties["Location"] = {"rich_text": [{"text": {"content": location}}]}
                    if category:
                        properties["Industry"] = {"rich_text": [{"text": {"content": category}}]}
                    
                    # Create the page
                    notion.pages.create(parent={"database_id": notion_database_id}, properties=properties)
                    
                    # Add to existing emails set to prevent duplicates within the same import
                    if skip_duplicates:
                        existing_emails.add(email.lower())
                    
                    imported_count += 1
                    print(f"Imported lead {lead_idx + 1}: {full_name} ({email})")
                        
                except Exception as e:
                    print(f"Error importing lead {lead_idx + 1}: {str(e)}")
                    error_count += 1
                
                # Update progress after each lead
                progress_data['current'] = lead_idx + 1
                progress_data['imported'] = imported_count
                progress_data['skipped'] = skipped_count
                progress_data['errors'] = error_count
                import_progress[session_id] = progress_data
                save_progress(session_id, progress_data)
                
                # Force garbage collection every 3 leads to keep memory usage very low
                if (lead_idx + 1) % 3 == 0:
                    gc.collect()
                    print(f"Memory usage after lead {lead_idx + 1}: {get_memory_usage():.1f} MB")
                
                # Small delay between leads to be gentle on Render
                time.sleep(0.3)
            
            print(f"Import completed: {imported_count} imported, {skipped_count} skipped, {error_count} errors")
            progress_data['current'] = total_leads
            progress_data['status'] = 'completed'
            progress_data['imported'] = imported_count
            progress_data['skipped'] = skipped_count
            progress_data['errors'] = error_count
            import_progress[session_id] = progress_data
            save_progress(session_id, progress_data)
            
            # Clean up progress file
            cleanup_progress_file(session_id)
            
        except Exception as e:
            print(f"Resume import error: {str(e)}")
            progress_data['status'] = 'error'
            progress_data['error'] = str(e)
            import_progress[session_id] = progress_data
            save_progress(session_id, progress_data)
    
    # Start resume thread
    resume_thread = threading.Thread(target=resume_import, daemon=False)
    import_tasks[session_id] = resume_thread
    resume_thread.start()
    
    # Count total leads without loading all into memory
    try:
        total_leads = count_leads_in_csv(csv_url)
    except Exception as e:
        return jsonify({'error': f'Could not access Google Sheet: {str(e)}'})
    return jsonify({'status': 'resuming', 'current': current_position, 'total': total_leads})

@app.route('/import-status')
def import_status():
    session_id = session.get('import_session_id')
    prog = import_progress.get(session_id)
    if not prog:
        prog = load_progress(session_id)
    if not prog:
        prog = {'current': 0, 'total': 1, 'status': 'unknown'}
    return jsonify(prog)

@app.route('/debug-import')
def debug_import():
    """Debug endpoint to check import status and files"""
    session_id = session.get('import_session_id')
    debug_info = {
        'session_id': session_id,
        'memory_progress': import_progress.get(session_id),
        'file_progress': load_progress(session_id),
        'active_tasks': list(import_tasks.keys()),
        'all_progress_files': []
    }
    
    # List all progress files
    try:
        for file in os.listdir('.'):
            if file.startswith('import_progress_') and file.endswith('.json'):
                debug_info['all_progress_files'].append(file)
    except Exception as e:
        debug_info['file_list_error'] = str(e)
    
    return jsonify(debug_info)

@app.route('/import-progress')
def import_progress_sse():
    session_id = session.get('import_session_id')
    def event_stream():
        last_sent = -1
        last_status = None
        while True:
            # Check both memory and file-based progress
            prog = import_progress.get(session_id)
            if not prog:
                # Try to load from file (recovery after restart)
                prog = load_progress(session_id)
                if prog:
                    import_progress[session_id] = prog
                    print(f"Recovered progress from file: {prog}")
            
            if not prog:
                prog = {'current': 0, 'total': 1, 'status': 'unknown'}
            
            # Send progress update if changed
            if prog['current'] != last_sent or prog.get('status') != last_status:
                data = {
                    "current": prog['current'], 
                    "total": prog['total'],
                    "status": prog.get('status', 'unknown')
                }
                if prog.get('error'):
                    data['error'] = prog['error']
                if prog.get('imported'):
                    data['imported'] = prog['imported']
                if prog.get('skipped'):
                    data['skipped'] = prog['skipped']
                if prog.get('errors'):
                    data['errors'] = prog['errors']
                
                yield f"data: {json.dumps(data)}\n\n"
                last_sent = prog['current']
                last_status = prog.get('status')
            
            # Check if import is complete or failed
            if prog.get('status') in ['completed', 'error'] or prog['current'] >= prog['total']:
                # Clean up completed task
                if session_id in import_tasks:
                    del import_tasks[session_id]
                break
            
            time.sleep(0.5)  # Reduced frequency to prevent overwhelming the client
        
        # Send final update
        prog = import_progress.get(session_id)
        if not prog:
            prog = load_progress(session_id)
        if not prog:
            prog = {'current': 0, 'total': 1, 'status': 'unknown'}
            
        data = {
            "current": prog['current'], 
            "total": prog['total'],
            "status": prog.get('status', 'completed')
        }
        if prog.get('error'):
            data['error'] = prog['error']
        if prog.get('imported'):
            data['imported'] = prog['imported']
        if prog.get('skipped'):
            data['skipped'] = prog['skipped']
        if prog.get('errors'):
            data['errors'] = prog['errors']
        
        yield f"data: {json.dumps(data)}\n\n"
    
    return Response(event_stream(), mimetype='text/event-stream')

@app.route('/import-chunk', methods=['POST'])
def import_chunk():
    print("\n==== /import-chunk CALLED ====")
    print(f"notion_api_key: {request.form.get('notion_api_key')}")
    print(f"notion_database_id: {request.form.get('notion_database_id')}")
    print(f"google_sheets_url: {request.form.get('google_sheets_url')}")
    print(f"skip_duplicates: {'skip_duplicates' in request.form}")
    print(f"start: {request.form.get('start', 0)}")
    print(f"count: {request.form.get('count', 10)}")
    notion_api_key = request.form.get('notion_api_key')
    notion_database_id = request.form.get('notion_database_id')
    google_sheets_url = request.form.get('google_sheets_url')
    skip_duplicates = 'skip_duplicates' in request.form
    start = int(request.form.get('start', 0))
    count = int(request.form.get('count', 10))

    import re
    spreadsheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', google_sheets_url)
    if not spreadsheet_id_match:
        return jsonify({'error': 'Invalid Google Sheets URL'}), 400
    spreadsheet_id = spreadsheet_id_match.group(1)
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"

    # Get total leads
    try:
        total_leads = count_leads_in_csv(csv_url)
    except Exception as e:
        return jsonify({'error': f'Could not access Google Sheet: {str(e)}'}), 400

    # Get existing emails if skip_duplicates is enabled
    from notion_client import Client
    notion = Client(auth=notion_api_key)
    existing_emails = set()
    if skip_duplicates:
        try:
            resp = notion.databases.query(database_id=notion_database_id)
            for page in resp.get('results', []):
                email = page.get('properties', {}).get('Email', {}).get('email', '')
                if email:
                    existing_emails.add(email.lower())
        except Exception as e:
            print(f"Warning: Could not fetch existing emails: {str(e)}")

    # Process only the chunk
    imported_count = 0
    skipped_count = 0
    error_count = 0
    processed = 0
    leads_processed = 0
    errors_detail = []  # Collect error details here
    print(f"Processing chunk: start={start}, count={count}")
    for idx, row in enumerate(stream_leads_from_csv(csv_url)):
        if idx < start:
            continue
        if leads_processed >= count:
            break
        print(f"Processing row {idx}: {row.get('First Name', '')} {row.get('Last Name', '')} - {row.get('E-mail', '')}")
    
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
        # Skip if required fields are empty
        if not first_name or not last_name or not email:
            print(f"  Skipping row {idx}: Missing required fields (first_name='{first_name}', last_name='{last_name}', email='{email}')")
            error_count += 1
            errors_detail.append({
                'row': idx + 1,  # 1-based index for user
                'reason': 'Missing required fields',
                'fields': {
                    'First Name': first_name,
                    'Last Name': last_name,
                    'E-mail': email
                },
                'row_data': row
            })
            continue
        # Skip duplicates if enabled
        if skip_duplicates and email.lower() in existing_emails:
            print(f"  Skipping row {idx}: Duplicate email '{email}'")
            skipped_count += 1
            continue
        full_name = f"{first_name} {last_name}".strip()
        properties = {
            "Name": {"title": [{"text": {"content": full_name}}]},
            "Email": {"email": email},
            "Lead Source": {"select": {"name": "Cold Outreach"}},
            "Status": {"status": {"name": "Not contacted"}}
        }
        if company_phone:
            properties["Phone"] = {"phone_number": company_phone}
        if title:
            properties["Title"] = {"rich_text": [{"text": {"content": title}}]}
        if company_name:
            properties["Organisation"] = {"rich_text": [{"text": {"content": company_name}}]}
        if website:
            website_url = website if website.startswith(('http://', 'https://')) else f'https://{website}'
            properties["Website"] = {"url": website_url}
        if linkedin:
            linkedin_url = linkedin if linkedin.startswith(('http://', 'https://')) else f'https://{linkedin}'
            properties["Social Media"] = {"url": linkedin_url}
        if location:
            properties["Location"] = {"rich_text": [{"text": {"content": location}}]}
        if category:
            properties["Industry"] = {"rich_text": [{"text": {"content": category}}]}
        # Only wrap the Notion API call in try/except
        try:
            notion.pages.create(parent={"database_id": notion_database_id}, properties=properties)
            print(f"  Successfully imported: {full_name} ({email})")
            if skip_duplicates:
                existing_emails.add(email.lower())
            imported_count += 1
        except Exception as e:
            print(f"Error importing lead {first_name} {last_name}: {str(e)}")
            error_count += 1
            errors_detail.append({
                'row': idx + 1,
                'reason': f'Exception: {str(e)}',
                'fields': {
                    'First Name': first_name,
                    'Last Name': last_name,
                    'E-mail': email
                },
                'row_data': row
            })
        leads_processed += 1
    response_data = {
        'imported': imported_count,
        'skipped': skipped_count,
        'errors': error_count,
        'start': start,
        'count': leads_processed,
        'total': total_leads,
        'next_start': start + leads_processed if (start + leads_processed) < total_leads else None,
        'errors_detail': errors_detail
    }
    print(f"Returning response: {response_data}")
    return jsonify(response_data)

# Add nl2br filter
@app.template_filter('nl2br')
def nl2br(value):
    """Convert newlines to HTML line breaks"""
    if value is None:
        return ""
    return markupsafe.Markup(str(value).replace('\n', '<br>'))

if __name__ == '__main__':
    app.run(debug=True) 