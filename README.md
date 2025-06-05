# Cold Email Automation

This Python script automates the process of sending cold emails to leads stored in a Notion database. It integrates with both Notion and Gmail APIs to manage leads and send emails.

## Setup Instructions

1. Clone this repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file based on `.env.example` and fill in the following secrets:

### Required Secrets

#### Notion API Setup
1. Go to https://www.notion.so/my-integrations
2. Create a new integration
3. Copy the API key to `NOTION_API_KEY`
4. Share your leads database with the integration
5. Copy the database ID from the database URL to `NOTION_DATABASE_ID`

#### Gmail API Setup
1. Go to Google Cloud Console
2. Create a new project
3. Enable the Gmail API
4. Create OAuth 2.0 credentials
   - Application type: Desktop app
   - Download the client configuration file
5. Run the following script to get your refresh token:
```python
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file(
    'path/to/client_secrets.json',
    ['https://www.googleapis.com/auth/gmail.send']
)
creds = flow.run_local_server(port=0)
print(f"Refresh Token: {creds.refresh_token}")
```
6. Fill in the following in your `.env`:
   - `GMAIL_CLIENT_ID`
   - `GMAIL_CLIENT_SECRET`
   - `GMAIL_REFRESH_TOKEN`

### Email Configuration
- `SENDER_EMAIL`: Your Gmail address
- `REPLY_TO_EMAIL`: Email address for replies

### Rate Limiting (Optional)
- `MAX_EMAILS_PER_DAY`: Maximum number of emails to send per day (default: 30)
- `DELAY_BETWEEN_EMAILS`: Delay in seconds between emails (default: 60)

## Usage

Run the script:
```bash
python cold_emailer.py
```

## Features

1. Fetches leads from Notion database that haven't been contacted
2. Generates personalized email drafts
3. Updates Notion with the email drafts
4. Sends emails via Gmail
5. Handles rate limiting and error retries
6. Updates lead status in Notion after contact attempt

## Notion Database Requirements

Your Notion database should have the following properties:
- Name (title)
- Email (email)
- Organisation (rich text)
- Industry (rich text)
- Status (status) with options:
  - Not contacted
  - Attempted contact
  - Strategy call
  - Proposal sent
  - Lost
  - Won
- Cold email draft (rich text)

## Error Handling

The script includes:
- Retry mechanism for API calls
- Rate limiting to avoid hitting API limits
- Error logging for failed operations
- Graceful handling of missing data

## Customization

### Email Templates
You can customize the email template in the `generate_email_draft` method of the `ColdEmailer` class. The current template uses:
- Recipient's name
- Company name
- Industry
- Customizable message body

### Rate Limiting
Adjust the following environment variables to control email sending:
- `MAX_EMAILS_PER_DAY`: Prevent exceeding daily limits
- `DELAY_BETWEEN_EMAILS`: Add delay between sends to avoid spam flags

## Best Practices

1. **Email Content**
   - Keep emails concise and professional
   - Personalize content based on lead data
   - Include clear call-to-action
   - Follow anti-spam regulations

2. **Rate Limiting**
   - Start with conservative limits
   - Monitor delivery rates
   - Adjust based on domain reputation

3. **Data Management**
   - Regularly backup your Notion database
   - Monitor email bounce rates
   - Update lead status promptly

## Troubleshooting

### Common Issues

1. **API Authentication Errors**
   - Verify API keys are correct
   - Check if tokens are expired
   - Ensure proper permissions are set

2. **Rate Limiting Issues**
   - Reduce `MAX_EMAILS_PER_DAY`
   - Increase `DELAY_BETWEEN_EMAILS`
   - Check API quota limits

3. **Email Delivery Problems**
   - Verify sender email is verified
   - Check spam score of content
   - Monitor bounce notifications

### Debug Mode

Add `DEBUG=True` to your `.env` file to enable verbose logging.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## Security Notes

- Never commit `.env` file
- Regularly rotate API keys
- Monitor for unauthorized access
- Keep dependencies updated

## Support

For issues and feature requests, please send an email to solviapteltd@gmail.com.

## Deployment on Fly.io

You can deploy this app as a Fly.io service:

1. Install the Fly CLI:
   ```bash
   curl -L https://fly.io/install.sh | sh
   ```
2. Login and initialize your Fly app:
   ```bash
   fly auth login
   fly launch --name maily --region iad --dockerfile Dockerfile --copy-config
   ```
   - When prompted, choose `Dockerfile` (not Buildpacks).
   - Confirm the app name `maily` and region (e.g., `iad`).

3. Deploy the application:
   ```bash
   fly deploy
   ```

4. Open your live app:
   ```bash
   fly open
   ```

Fly will build the Docker image, push it, and run your Flask app on port `5000`. Configuration (`config.json`) is persisted locally; for production, consider using Fly volumes or secrets for sensitive values.

Refer to Fly.io docs for advanced setup: https://fly.io/docs/getting-started/ 