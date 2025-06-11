import os
import time
import smtplib
import requests
import re
import json
from email.mime.text import MIMEText
from datetime import datetime
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
    def __init__(self, notion_api_key: str, notion_database_id: str, openai_api_key: str,
                 email_template: str = None, analysis_prompt: str = None, summary_prompt: str = None):
        """Initialize with API keys and optional templates"""
        self.notion = Client(auth=notion_api_key)
        self.database_id = notion_database_id
        openai.api_key = openai_api_key
        self.email_template = email_template or self.load_default_email_template()
        self.analysis_prompt_template = analysis_prompt
        self.summary_prompt_template = summary_prompt

    def load_default_email_template(self) -> str:
        """Load default email template from file"""
        try:
            with open('email_template.txt', 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return ""

    @retry(tries=3, delay=2)
    def get_leads_to_contact(self) -> List[Dict[str, Any]]:
        """Get leads from Notion that haven't been contacted yet"""
        try:
            # Query Notion database for leads without a draft
            response = self.notion.databases.query(
                database_id=self.database_id,
                filter={
                    "and": [
                        {
                            "property": "Cold email draft",
                            "rich_text": {
                                "is_empty": True
                            }
                        }
                    ]
                }
            )
            return response.get("results", [])
        except Exception as e:
            print(f"Error fetching leads: {e}")
            return []

    @retry(tries=3, delay=2)
    def generate_email_draft(self, lead: Dict[str, Any]) -> str:
        """Generate personalized email draft based on lead information"""
        # Extract lead information
        name = lead["properties"].get("Name", {}).get("title", [{}])[0].get("text", {}).get("content", "")
        company = lead["properties"].get("Organisation", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
        # Log which lead we're generating a draft for
        print(f"\nGenerating email draft for {name} at {company}")
        # Extract first name only
        first_name = name.split()[0] if name else ""
        industry = lead["properties"].get("Industry", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
        
        # Format template with lead information
        try:
            email_draft = self.email_template.format(
                name=first_name,
                company=company,
                industry=industry
            )
            
        except KeyError as e:
            print(f"Warning: Template placeholder {e} not found in data. Using empty string.")
            email_draft = self.email_template.format(
                name=first_name or "",
                company=company or "",
                industry=industry or ""
            )
        
        return email_draft

    @retry(tries=3, delay=2)
    def update_notion_with_draft(self, page_id: str, draft: str) -> None:
        """Update Notion page with generated email draft"""
        try:
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    "Cold email draft": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": draft
                                }
                            }
                        ]
                    }
                }
            )
        except Exception as e:
            print(f"Error updating Notion: {e}")

    def setup_smtp_settings(self):
        """Setup SMTP settings for Zoho Mail"""
        print("Configuring SMTP settings...")
        self.smtp_settings = {
            'host': os.getenv('SMTP_HOST', 'smtp.zoho.com'),
            'port': int(os.getenv('SMTP_PORT', '587')),
            'username': os.getenv('SENDER_EMAIL'),
            'password': os.getenv('ZOHO_APP_PASSWORD'),
        }
        




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
                
                # Update Notion with draft
                self.update_notion_with_draft(lead["id"], draft)
                
                # Get email address
                email = lead["properties"].get("Email", {}).get("email", "")
                if not email and not TEST_MODE:
                    print(f"No email found for lead {lead['id']}")
                    continue
                
                # Email sending disabled in draft-only mode
                # sent = self.send_email(
                #     to_email=email or "no-email@example.com",
                #     subject="Would love to connect",
                #     body=draft
                # )
                # Logging disabled when email sending is turned off
                # if sent:
                #     print("Email sending skipped in test mode.")
                # else:
                #     print("Email sending skipped in test mode.")

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