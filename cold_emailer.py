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
    def __init__(self, notion_api_key: str = None, notion_database_id: str = None):
        print("Initializing ColdEmailer...")
        # Use passed API key or fallback to environment variable
        notion_api_key = notion_api_key or os.getenv("NOTION_API_KEY")
        
        # Load and validate database ID from parameters or environment
        self.database_id = notion_database_id or os.getenv("NOTION_DATABASE_ID")
        if not notion_api_key or not self.database_id:
            raise ValueError("Missing required parameters: NOTION_API_KEY and NOTION_DATABASE_ID must be set")
        print(f"Using database ID: {self.database_id}")
        
        self.notion = Client(auth=notion_api_key)
        
        # Verify database access
        try:
            db_info = self.notion.databases.retrieve(self.database_id)
            print("✅ Successfully connected to Notion database")
            print(f"Database title: {db_info['title'][0]['plain_text'] if db_info.get('title') else 'Untitled'}")
        except Exception as e:
            print(f"❌ Error connecting to database: {e}")
            raise
            
        self.load_email_template()
        self.setup_smtp_settings()
        openai.api_key = os.getenv("OPENAI_API_KEY")
        




    def setup_smtp_settings(self):
        """Setup SMTP settings for Zoho Mail"""
        print("Configuring SMTP settings...")
        self.smtp_settings = {
            'host': os.getenv('SMTP_HOST', 'smtp.zoho.com'),
            'port': int(os.getenv('SMTP_PORT', '587')),
            'username': os.getenv('SENDER_EMAIL'),
            'password': os.getenv('ZOHO_APP_PASSWORD'),
        }
        




    def load_email_template(self):
        """Load email template from file"""
        print("Loading email template...")
        try:
            with open('email_template.txt', 'r', encoding='utf-8') as file:
                self.email_template = file.read()
        except FileNotFoundError:
            print("Warning: email_template.txt not found. Using default template.")
            self.email_template = """Hey {name},

I noticed your work at {company} in the {industry} industry and I'm impressed with what you're doing.

Would you be open to a brief conversation about how we might be able to help?

Best regards,
Nadra
Co-founder at The Nadra Agency
thenadraagency.com"""





    def get_leads_to_contact(self) -> List[Dict[str, Any]]:
        """Get leads from Notion database that haven't been contacted yet"""
        print("Fetching leads to contact from Notion...")
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
                    }
                ]
            },
            page_size=30
        )
        
        return response["results"][:TEST_LIMIT] if TEST_MODE else response["results"]





    @retry(tries=3, delay=2)
    def analyze_website(self, url: str) -> Tuple[str, List[Dict[str, str]]]:
        """Analyze website for CRO improvements"""
        print(f"Analyzing website: {url}")
        try:
            # Fetch website content
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html5lib')
            html_content = str(soup)
            
            # Analyze with OpenAI
            analysis_prompt = f"""Analyze this website's HTML for exactly 3 major conversion rate optimization (CRO) flaws.
For each flaw:
1. Quote the problematic HTML code
2. Explain why it's a problem
3. Provide a specific percentage impact on conversion rate (be dramatic but realistic)
4. Give the exact solution with code if applicable

Format as JSON:
{{
    "flaws": [
        {{
            "code": "quoted HTML code",
            "problem": "explanation",
            "impact": "percentage and numbers",
            "solution": "specific solution"
        }}
    ]
}}

Website HTML: {html_content[:10000]}"""  # First 10K chars to stay within token limits

            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": analysis_prompt}],
                temperature=0.7
            )
            
            analysis = response.choices[0].message.content
            
            # Generate summary
            summary_prompt = f"""Based on this CRO analysis, create a compelling 2-paragraph summary that will grab the reader's attention.
Focus on the potential revenue/conversion impact. Use specific numbers and percentages.
Make it persuasive but professional.

Analysis: {analysis}"""

            summary_response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.7
            )
            
            summary = summary_response.choices[0].message.content
            
            # Parse analysis JSON safely
            try:
                analysis_data = json.loads(analysis)
            except json.JSONDecodeError:
                # Fallback: extract JSON object from string
                start = analysis.find('{')
                end = analysis.rfind('}')
                if start != -1 and end != -1:
                    analysis_data = json.loads(analysis[start:end+1])
                else:
                    raise
            return summary, analysis_data.get("flaws", [])
            
        except Exception as e:
            print(f"\nError analyzing website: {e}")
            return "", []





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
        website = lead["properties"].get("Website", {}).get("url", "")
        
        # Get website analysis if URL is available
        cro_summary = ""
        if website:
            try:
                summary, flaws = self.analyze_website(website)
                if summary and flaws:
                    cro_summary = f"Based on our analysis of your website, we've identified several opportunities for improvement:\n\n{summary}\n"
            except Exception as e:
                print(f"Error in website analysis: {e}")
        
        # Format template with lead information
        try:
            email_draft = self.email_template.format(
                name=first_name,
                company=company,
                industry=industry
            )
            
            # Add CRO summary if available
            if cro_summary:
                email_draft = email_draft.replace(
                    "Would you be open to a brief conversation about how we might be able to help?",
                    f"{cro_summary}\nWould you be open to a brief conversation about implementing these improvements?"
                )
            
        except KeyError as e:
            print(f"Warning: Template placeholder {e} not found in data. Using empty string.")
            email_draft = self.email_template.format(
                name=first_name or "",
                company=company or "",
                industry=industry or ""
            )
        
        # Normalize multiple blank lines to exactly one blank line (two newlines)
        email_draft = re.sub(r"\n{3,}", "\n\n", email_draft)
        return email_draft





    @retry(tries=3, delay=2)
    def update_notion_with_draft(self, page_id: str, draft: str):
        """Update Notion page with the email draft"""
        print("Updating Notion with email draft...")
        # Only update the Cold email draft; leave Status unchanged
        self.notion.pages.update(
            page_id=page_id,
            properties={
                "Cold email draft": {
                    "rich_text": [{
                        "text": {
                            "content": draft
                        }
                    }]
                }
            }
        )





    @retry(tries=3, delay=2)
    def send_email(self, to_email: str, subject: str, body: str) -> bool:
        """Send email using Zoho Mail SMTP"""
        print(f"send_email called for: {to_email} (mode: {'TEST' if TEST_MODE else 'PRODUCTION'})")
        message = MIMEText(body)
        # In test mode, override recipient
        if TEST_MODE:
            subject = f"[TEST] Would have sent to: {to_email} - {subject}"
            # Always send to TEST_EMAIL only
            actual_recipients = [TEST_EMAIL]
        else:
            actual_recipients = [to_email]
        
        # Set the displayed To header to the actual recipients
        message['To'] = TEST_EMAIL if TEST_MODE else to_email
        message['From'] = os.getenv('SENDER_EMAIL')
        message['Reply-To'] = os.getenv('REPLY_TO_EMAIL')
        message['Subject'] = subject

        try:
            with smtplib.SMTP(self.smtp_settings['host'], self.smtp_settings['port']) as server:
                server.starttls()
                server.login(self.smtp_settings['username'], self.smtp_settings['password'])
                # Explicitly send to the intended recipients
                server.send_message(message, from_addr=self.smtp_settings['username'], to_addrs=actual_recipients)
            return True
        except Exception as e:
            print(f"\nError sending email: {e}")
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