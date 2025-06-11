import os
import json
from flask import Flask, render_template, request, jsonify
from cold_emailer import ColdEmailer
from notion_client import Client
from functools import lru_cache

app = Flask(__name__)

# Cache the prompt templates to reduce memory usage
@lru_cache(maxsize=1)
def load_prompt_templates():
    """Load prompt templates from JSON file"""
    try:
        with open('prompt_templates.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'email_templates': {}}

@app.route('/health')
def health_check():
    """Health check endpoint for Render.com"""
    return jsonify({"status": "healthy"}), 200

@app.route('/save_template', methods=['POST'])
def save_template():
    """Save a template to the JSON file"""
    try:
        data = request.get_json()
        template_type = data.get('type')
        name = data.get('name')
        content = data.get('content')
        
        if not all([template_type, name, content]):
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        # Load existing templates
        try:
            with open('prompt_templates.json', 'r') as f:
                templates = json.load(f)
        except FileNotFoundError:
            templates = {'email_templates': {}}
        
        # Update templates
        if template_type == 'email':
            templates['email_templates'][name] = content
        
        # Save back to file
        with open('prompt_templates.json', 'w') as f:
            json.dump(templates, f)
        
        # Clear the cache
        load_prompt_templates.cache_clear()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_template', methods=['POST'])
def delete_template():
    """Delete a template from the JSON file"""
    try:
        data = request.get_json()
        template_type = data.get('type')
        name = data.get('name')
        
        if not all([template_type, name]):
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        # Load existing templates
        try:
            with open('prompt_templates.json', 'r') as f:
                templates = json.load(f)
        except FileNotFoundError:
            return jsonify({'success': False, 'error': 'No templates found'})
        
        # Delete template
        if template_type == 'email' and name in templates['email_templates']:
            del templates['email_templates'][name]
        
        # Save back to file
        with open('prompt_templates.json', 'w') as f:
            json.dump(templates, f)
        
        # Clear the cache
        load_prompt_templates.cache_clear()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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
        # Get form data
        notion_api_key = request.form.get('notion_api_key')
        notion_database_id = request.form.get('notion_database_id')
        email_template = request.form.get('email_template')
        lead_limit = request.form.get('lead_limit')
        
        # Save config
        config = {
            'notion_api_key': notion_api_key,
            'notion_database_id': notion_database_id,
            'email_template': email_template,
            'lead_limit': lead_limit
        }
        with open(config_path, 'w') as f:
            json.dump(config, f)
        
        # Initialize emailer
        try:
            emailer = ColdEmailer(
                notion_api_key=notion_api_key,
                notion_database_id=notion_database_id,
                openai_api_key=os.getenv('OPENAI_API_KEY', ''),
                email_template=email_template
            )
            
            # If testing connection
            if request.form.get('action') == 'test':
                try:
                    db_info = emailer.notion.databases.retrieve(notion_database_id)
                    db_title = db_info['title'][0]['plain_text'] if db_info.get('title') else 'Untitled'
                except Exception as e:
                    error_message = f"Error connecting to Notion: {str(e)}"
                    error_field = 'notion_database_id'
            else:
                # Run automation
                leads = emailer.get_leads_to_contact()
                if lead_limit:
                    try:
                        limit_int = int(lead_limit)
                        leads = leads[:limit_int]
                    except ValueError:
                        pass
                
                results = []
                for lead in leads:
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
                
        except Exception as e:
            error_message = str(e)
            if "Missing required parameters" in str(e):
                error_field = 'notion_api_key' if not notion_api_key else 'notion_database_id'
    
    # Load prompt templates
    prompt_templates = load_prompt_templates()
    
    return render_template('index.html',
                         config=config,
                         db_title=db_title,
                         error_message=error_message,
                         error_field=error_field,
                         default_email_template=default_email_template,
                         prompt_templates=prompt_templates)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000))) 