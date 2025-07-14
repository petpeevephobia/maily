import os
import time
import smtplib
import requests
import re
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
from bs4 import BeautifulSoup
import openai

import pandas as pd
from dotenv import load_dotenv
from notion_client import Client
from tqdm import tqdm
from retry import retry

# Load environment variables
load_dotenv()

# Test mode configuration
TEST_MODE = True
TEST_EMAIL = "nadra@thenadraagency.com"
TEST_LIMIT = 3
BCC_EMAIL = "nadra@solvia.app"





def extract_notion_id(url_or_id: str) -> str:
    """Extract and format Notion database ID from URL or ID string"""
    # Try to extract ID from URL first
    url_match = re.search(r'notion\.so/(?:[^/]+/)?([a-zA-Z0-9]+)', url_or_id)
    if url_match:
        raw_id = url_match.group(1)
    else:
        # If not URL, clean the provided ID
        raw_id = ''.join(c for c in url_or_id if c.isalnum())
    
    # Format ID with hyphens if it's the right length
    if len(raw_id) == 32:
        return f"{raw_id[:8]}-{raw_id[8:12]}-{raw_id[12:16]}-{raw_id[16:20]}-{raw_id[20:]}"
    return raw_id











class ColdEmailer:
    def __init__(self, notion_api_key: str, notion_database_id: str, openai_api_key: str = None,
                 email_template: str = None, analysis_prompt: str = None, summary_prompt: str = None,
                 email_subject: str = '{name}, you don\'t want to miss this'):
        """Initialize with API keys and optional templates"""
        self.notion = Client(auth=notion_api_key)
        self.database_id = notion_database_id
        if openai_api_key:
            openai.api_key = openai_api_key
        self.email_template = email_template or self.load_default_email_template()
        self.analysis_prompt_template = analysis_prompt
        self.summary_prompt_template = summary_prompt
        self.email_subject = email_subject

    def load_default_email_template(self) -> str:
        """Load default email template from file"""
        try:
            with open('email_template.txt', 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def get_leads_to_contact(self) -> list:
        """Get leads from Notion database that need to be contacted"""
        try:
            print("Querying Notion database...")

            
            # Query the database for leads
            response = self.notion.databases.query(
                database_id=self.database_id,
                filter={
                    "and": [
                        {
                            "property": "Status",
                            "status": {
                                "equals": "Not contacted"
                            }
                        },
                        {
                            "property": "Cold email draft",
                            "rich_text": {
                                "is_empty": True
                            }
                        },
                        {
                            "property": "Email",
                            "email": {
                                "is_not_empty": True
                            }
                        }
                    ]
                }
            )
            results = response.get('results', [])
            print(f"\nThere are {len(results)} leads not contacted.")
            
            return results
        except Exception as e:
            print(f"Error getting leads: {str(e)}")
            return []

    def get_leads_for_followup(self, limit: int = None) -> list:
        """Get leads from Notion database that are ready for follow-up emails"""
        try:
            print("Querying Notion database for follow-up leads...")
            
            # Calculate date 2 days ago
            two_days_ago = (datetime.now() - timedelta(days=2)).isoformat()
            
            # Query the database for leads ready for follow-up
            response = self.notion.databases.query(
                database_id=self.database_id,
                filter={
                    "and": [
                        {
                            "property": "Contacted Date",
                            "date": {
                                "on_or_before": two_days_ago
                            }
                        },
                        {
                            "property": "Email",
                            "email": {
                                "is_not_empty": True
                            }
                        },
                        {
                            "property": "Follow-Up email draft",
                            "rich_text": {
                                "is_empty": True
                            }
                        },
                        {
                            "property": "Follow-Up Date",
                            "date": {
                                "is_empty": True
                            }
                        }
                    ]
                }
            )
            results = response.get('results', [])
            
            # Apply limit if specified
            if limit:
                results = results[:limit]
            
            print(f"\nThere are {len(results)} leads ready for follow-up emails (contacted 2+ days ago, no follow-up draft, no follow-up date).")
            
            return results
        except Exception as e:
            print(f"Error getting follow-up leads: {str(e)}")
            return []

    def generate_followup_draft(self, lead: dict, followup_template: str = None, followup_subject: str = None) -> dict:
        """Generate follow-up email draft for a lead"""
        try:
            # Get lead details
            name = lead.get('properties', {}).get('Name', {}).get('title', [{}])[0].get('text', {}).get('content', '')
            email = lead.get('properties', {}).get('Email', {}).get('email', '')
            company = lead.get('properties', {}).get('Organisation', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
            
            # Get first name only
            first_name = name.split()[0] if name else ''
            
            # Get the original cold email draft to reference
            cold_email_draft = lead.get('properties', {}).get('Cold email draft', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
            
            # Get contacted date
            contacted_date = lead.get('properties', {}).get('Contacted Date', {}).get('date', {}).get('start', '')
            
            # Use provided template or load from external file
            if followup_template:
                template_content = followup_template
            else:
                # Load follow-up email template from external file
                try:
                    with open('followup_template.txt', 'r', encoding='utf-8') as f:
                        template_content = f.read().strip()
                except FileNotFoundError:
                    # Fallback template if file is not found
                    template_content = """Hey {name},

I wanted to follow up on my previous email about {company}. I know you're busy, so I'll keep this brief.

Did you get a chance to review my initial message? I'd love to hear your thoughts or schedule a quick call if you're interested.

Looking forward to connecting!

Best regards,
Nadra"""
                    print("Warning: followup_template.txt not found, using fallback template")
            
            content = template_content.format(
                name=first_name,
                company=company
            )
            
            # Use provided subject or default
            if followup_subject:
                subject = followup_subject.format(
                    name=first_name,
                    company=company
                )
            else:
                subject = "{name}, I know what it's like".format(
                    name=first_name,
                    company=company
                )
            
            return {
                'to_name': name,
                'to_email': email,
                'company': company,
                'subject': subject,
                'content': content,
                'original_draft': cold_email_draft,
                'contacted_date': contacted_date
            }
        except Exception as e:
            print(f"Error generating follow-up draft: {str(e)}")
            return None

    def store_followup_draft(self, lead_id: str, subject: str, content: str) -> bool:
        """Store follow-up email draft in Notion database"""
        try:
            self.notion.pages.update(
                page_id=lead_id,
                properties={
                    "Follow-Up email draft": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": f"Subject: {subject}\n\n{content}"
                                }
                            }
                        ]
                    }
                }
            )
            return True
        except Exception as e:
            print(f"Error storing follow-up draft: {str(e)}")
            return False

    def generate_email_draft(self, lead: dict) -> dict:
        """Generate email draft for a lead"""
        try:
            # Get lead details
            name = lead.get('properties', {}).get('Name', {}).get('title', [{}])[0].get('text', {}).get('content', '')
            email = lead.get('properties', {}).get('Email', {}).get('email', '')
            company = lead.get('properties', {}).get('Organisation', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
            
            # Get first name only
            first_name = name.split()[0] if name else ''
            
            # Generate email content
            content = self.email_template.format(
                name=first_name,
                company=company
            )
            
            # Generate subject
            subject = self.email_subject.format(
                name=first_name,
                company=company
            )
            
            return {
                'to_name': name,
                'to_email': email,
                'company': company,
                'subject': subject,
                'content': content
            }
        except Exception as e:
            print(f"Error generating email draft: {str(e)}")
            return None

    def test_smtp_connection(self) -> bool:
        """Test SMTP connection and send a test email"""
        try:
            # Get Zoho credentials
            zoho_email = os.getenv('ZOHO_EMAIL')
            zoho_app_password = os.getenv('ZOHO_APP_PASSWORD')
            
            if not zoho_email or not zoho_app_password:
                raise Exception("Missing Zoho email configuration")
            
            # Create test message
            msg = MIMEMultipart()
            msg['From'] = zoho_email
            msg['To'] = zoho_email  # Send to self
            msg['Subject'] = "Test Email from Maily"
            
            # Add body
            msg.attach(MIMEText("This is a test email from Maily to verify SMTP connection.", 'plain'))
            
            # Create SMTP connection
            smtp_server = "smtp.zoho.com"
            smtp_port = 587
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(zoho_email, zoho_app_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            print(f"\nSMTP Test Error: {str(e)}")
            return False

    def send_email(self, to_email: str, subject: str, content: str, lead_id: str = None, test_mode: bool = False, is_followup: bool = False) -> bool:
        """Send email using Zoho SMTP and update Notion status if successful"""
        try:
            # Get Zoho credentials from environment variables
            zoho_email = os.getenv('ZOHO_EMAIL')
            zoho_app_password = os.getenv('ZOHO_APP_PASSWORD')
            
            if not zoho_email or not zoho_app_password:
                raise Exception("Missing Zoho email configuration. Please set ZOHO_EMAIL and ZOHO_APP_PASSWORD environment variables.")
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = zoho_email
            msg['To'] = to_email
            
            # Add BCC if not in test mode (test mode means we're already sending to our email)
            if to_email != zoho_email:  # If not in test mode
                msg['Bcc'] = BCC_EMAIL
            
            # Modify subject line for test mode
            if test_mode:
                msg['Subject'] = f"[TEST] {subject}"
            else:
                msg['Subject'] = subject
            
            # Add body
            msg.attach(MIMEText(content, 'plain'))
            
            # Create SMTP connection
            smtp_server = "smtp.zoho.com"
            smtp_port = 587
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(zoho_email, zoho_app_password)
            
            # Get all recipients (To + Bcc)
            recipients = [to_email]
            if 'Bcc' in msg:
                recipients.append(msg['Bcc'])
            
            server.send_message(msg, to_addrs=recipients)
            server.quit()

            # Update Notion status, draft, and contacted date if lead_id is provided and NOT a follow-up email
            if lead_id and not is_followup:
                current_date = datetime.now().isoformat()
                self.notion.pages.update(
                    page_id=lead_id,
                    properties={
                        "Status": {
                            "status": {
                                "name": "Attempted contact"
                            }
                        },
                        "Cold email draft": {
                            "rich_text": [
                                {
                                    "text": {
                                        "content": f"Subject: {subject}\n\n{content}"
                                    }
                                }
                            ]
                        },
                        "Contacted Date": {
                            "date": {
                                "start": current_date
                            }
                        }
                    }
                )
            
            return True
        except Exception as e:
            print(f"\nError sending email: {str(e)}")
            return False

    def run(self):
        """Main execution flow"""
        print("Starting cold email automation...")
        if TEST_MODE:
            print(f"⚠️ RUNNING IN TEST MODE - All emails will be sent to {TEST_EMAIL}")
            print(f"⚠️ Limited to {TEST_LIMIT} emails")
        
        # Get leads to contact
        leads = self.get_leads_to_contact()
        print(f"Found {len(leads)} leads to contact")
        
        max_emails = TEST_LIMIT if TEST_MODE else int(os.getenv("MAX_EMAILS_PER_DAY", 30))
        delay = int(os.getenv("DELAY_BETWEEN_EMAILS", 60))
        
        for lead in tqdm(leads[:max_emails], desc="Processing leads"):
            try:
                # Countdown before processing each lead to respect rate limits
                if delay > 0:
                    for remaining in range(delay, 0, -1):
                        print(f"Waiting {remaining} seconds before next draft...", end='\r')
                        time.sleep(1)
                    # Clear the countdown line
                    print(' ' * 50, end='\r')
                # Generate draft
                draft = self.generate_email_draft(lead)
                
                # Get email address
                email = lead["properties"].get("Email", {}).get("email", "")
                if not email and not TEST_MODE:
                    print(f"No email found for lead {lead['id']}")
                    continue
                
                # Send email
                sent = self.send_email(
                    to_email=email,
                    subject="Would love to connect",
                    content=draft['content'],
                    lead_id=lead['id'],
                    test_mode=TEST_MODE
                )
                if sent:
                    print(f"Email sent to {email}")
                else:
                    print(f"Email sending failed for {email}")

            except Exception as e:
                print(f"Error processing lead {lead['id']}: {e}")
                continue










if __name__ == "__main__":
    emailer = ColdEmailer()
    emailer.run()

# PRODUCTION CODE (commented out) - Remove TEST_MODE when ready to launch
"""
To switch to production mode:
1. Set TEST_MODE = False at the top of the file
2. Remove the test email address
3. Remove the TEST_LIMIT
4. The code will then:
   - Send emails to actual lead email addresses
   - Use the real subject line
   - Process all leads from Notion
   - Respect the MAX_EMAILS_PER_DAY from .env
""" 

def run(notion_api_key: str, notion_database_id: str, sender_email: str, email_template: str, email_subject: str = '{name}, you don\'t want to miss this', lead_limit: int = 10) -> list:
    """Run the cold emailer"""
    try:
        # Initialize the cold emailer
        emailer = ColdEmailer(
            notion_api_key=notion_api_key,
            notion_database_id=notion_database_id,
            email_template=email_template,
            email_subject=email_subject
        )
        
        # Get leads to be processed
        leads = emailer.get_leads_to_contact()
        results = []
        
        # Process leads up to the limit
        for lead in leads[:lead_limit]:
            try:
                # Generate draft
                draft = emailer.generate_email_draft(lead)
                if draft:
                    # Send email
                    sent = emailer.send_email(
                        to_email=draft['to_email'],
                        subject=draft['subject'],
                        content=draft['content'],
                        lead_id=lead['id'],
                        test_mode=TEST_MODE
                    )
                    results.append({
                        'name': draft['to_name'],
                        'email': draft['to_email'],
                        'company': draft['company'],
                        'status': 'Sent' if sent else 'Failed'
                    })
            except Exception as e:
                results.append({
                    'name': 'Error',
                    'email': str(e),
                    'company': 'N/A',
                    'status': 'Error'
                })
        
        return results
    except Exception as e:
        print(f"Error running cold emailer: {str(e)}")
        return [] 