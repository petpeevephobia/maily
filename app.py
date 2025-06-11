import os
import json
from flask import Flask, render_template, request, jsonify
from cold_emailer import ColdEmailer
from notion_client import Client

app = Flask(__name__)

# Prompt template management functions
def load_prompt_templates():
    """Load saved prompt templates from file"""
    templates_path = 'prompt_templates.json'
    default_structure = {
        'analysis_prompts': {},
        'summary_prompts': {},
        'email_templates': {}
    }
    
    if os.path.exists(templates_path):
        try:
            with open(templates_path, 'r', encoding='utf-8') as f:
                loaded_templates = json.load(f)
                # Ensure all required keys exist (for backward compatibility)
                for key in default_structure:
                    if key not in loaded_templates:
                        loaded_templates[key] = {}
                return loaded_templates
        except (json.JSONDecodeError, IOError):
            pass
    
    return default_structure

def save_prompt_templates(templates):
    """Save prompt templates to file"""
    templates_path = 'prompt_templates.json'
    with open(templates_path, 'w', encoding='utf-8') as f:
        json.dump(templates, f, indent=2, ensure_ascii=False)

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

# API routes for prompt template management
@app.route('/api/prompt-templates', methods=['GET'])
def get_prompt_templates():
    """Get all saved prompt templates"""
    templates = load_prompt_templates()
    return jsonify(templates)

@app.route('/api/prompt-templates', methods=['POST'])
def save_prompt_template():
    """Save a new prompt template"""
    data = request.get_json()
    template_type = data.get('type')  # 'analysis' or 'summary'
    template_name = data.get('name')
    template_content = data.get('content')
    
    if not all([template_type, template_name, template_content]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    templates = load_prompt_templates()
    
    if template_type == 'analysis':
        templates['analysis_prompts'][template_name] = template_content
    elif template_type == 'summary':
        templates['summary_prompts'][template_name] = template_content
    elif template_type == 'email':
        templates['email_templates'][template_name] = template_content
    else:
        return jsonify({'error': 'Invalid template type'}), 400
    
    save_prompt_templates(templates)
    return jsonify({'success': True})

@app.route('/api/prompt-templates/<template_type>/<template_name>', methods=['DELETE'])
def delete_prompt_template(template_type, template_name):
    """Delete a saved prompt template"""
    templates = load_prompt_templates()
    
    if template_type == 'analysis' and template_name in templates['analysis_prompts']:
        del templates['analysis_prompts'][template_name]
    elif template_type == 'summary' and template_name in templates['summary_prompts']:
        del templates['summary_prompts'][template_name]
    elif template_type == 'email' and template_name in templates['email_templates']:
        del templates['email_templates'][template_name]
    else:
        return jsonify({'error': 'Template not found'}), 404
    
    save_prompt_templates(templates)
    return jsonify({'success': True})

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
    # Load default email template
    default_email_template = ""
    try:
        with open('email_template.txt', 'r', encoding='utf-8') as f:
            default_email_template = f.read()
    except FileNotFoundError:
        default_email_template = ""
    if request.method == 'POST':
        # Determine action: test connection or run automation
        action = request.form.get('action')
        # Get and save Notion and Zoho SMTP credentials
        notion_api_key = request.form.get('notion_api_key')
        notion_database_id = request.form.get('notion_database_id')
        # Future use: Email sending functionality
        # sender_email = request.form.get('sender_email')
        # zoho_app_password = request.form.get('zoho_app_password')
        # Get optional OpenAI prompt overrides
        analysis_prompt = request.form.get('analysis_prompt')
        summary_prompt = request.form.get('summary_prompt')
        # Get optional custom email template
        email_template = request.form.get('email_template')
        # Get optional limit on number of leads
        lead_limit = request.form.get('lead_limit')
        config = {
            'notion_api_key': notion_api_key,
            'notion_database_id': notion_database_id,
            # Future use: Email sending functionality
            # 'sender_email': sender_email,
            # 'zoho_app_password': zoho_app_password,
            'analysis_prompt': analysis_prompt,
            'summary_prompt': summary_prompt,
            'email_template': email_template,
            'lead_limit': lead_limit
        }
        # Persist config
        with open(config_path, 'w') as f:
            json.dump(config, f)
        # Future use: Email sending functionality
        # Set SMTP credentials in environment for ColdEmailer
        # os.environ['SENDER_EMAIL'] = sender_email
        # os.environ['ZOHO_APP_PASSWORD'] = zoho_app_password
        # Initialize client with Notion credentials
        emailer = ColdEmailer(notion_api_key, notion_database_id)
        # Apply prompt overrides to ColdEmailer instance
        if analysis_prompt:
            emailer.analysis_prompt_template = analysis_prompt
        if summary_prompt:
            emailer.summary_prompt_template = summary_prompt
        # Apply custom email template if provided
        if email_template:
            emailer.email_template = email_template
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
            # Future use: Email sending functionality
            # Test Zoho SMTP connection
            # smtp_ok = True
            # smtp_error_message = None
            # smtp_error_field = None
            # try:
            #     import smtplib
            #     host = os.getenv('SMTP_HOST', 'smtp.zoho.com')
            #     port = int(os.getenv('SMTP_PORT', '587'))
            #     smtp = smtplib.SMTP(host, port, timeout=10)
            #     smtp.starttls()
            #     smtp.login(sender_email, zoho_app_password)
            #     smtp.quit()
            # except Exception as e:
            #     smtp_ok = False
            #     msg = str(e).lower()
            #     if 'authentication' in msg or '535' in msg or 'failed' in msg:
            #         smtp_error_field = 'zoho_app_password'
            #         smtp_error_message = 'Invalid Zoho email or app password.'
            #     else:
            #         smtp_error_field = None
            #         smtp_error_message = 'Error connecting to Zoho SMTP: ' + str(e)
            # Load prompt templates for the UI
            prompt_templates = load_prompt_templates()
            return render_template('index.html', config=config, db_title=db_title,
                                   error_message=error_message, error_field=error_field,
                                   # Future use: Email sending functionality
                                   # smtp_ok=smtp_ok, smtp_error_message=smtp_error_message,
                                   # smtp_error_field=smtp_error_field,
                                   default_email_template=default_email_template,
                                   prompt_templates=prompt_templates)
        # Else run the automation
        leads = emailer.get_leads_to_contact()
        # Apply lead limit if provided
        if lead_limit:
            try:
                limit_int = int(lead_limit)
                leads = leads[:limit_int]
            except ValueError:
                pass
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
    # Load prompt templates for the UI
    prompt_templates = load_prompt_templates()
    return render_template('index.html', config=config, db_title=None,
                           error_message=None, error_field=None,
                           default_email_template=default_email_template,
                           prompt_templates=prompt_templates)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port) 