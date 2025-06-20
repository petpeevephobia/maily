# Maily Product Versions

This document outlines the different versions of Maily, a cold email automation tool that integrates with Notion databases.

## Version 1: Email Generation Only
**Status**: Basic functionality

### Features
- ✅ Connect to Notion database
- ✅ Query leads with "Not contacted" status
- ✅ Generate personalized email drafts using templates
- ✅ Preview emails before sending
- ✅ Template customization with variables (`{name}`, `{company}`)
- ✅ Subject line customization

### Limitations
- ❌ No email sending capability
- ❌ No status updates in Notion
- ❌ Manual copy/paste required for sending emails

### Use Case
Perfect for users who want to generate personalized email content but prefer to send emails manually through their own email client.

---

## Version 2: Email Generation + Sending + Status Updates
**Status**: Enhanced automation

### Features
- ✅ All features from Version 1
- ✅ Automated email sending via Zoho SMTP
- ✅ Bulk email processing
- ✅ Rate limiting and delays between emails
- ✅ Test mode for safe testing
- ✅ Automatic status updates in Notion:
  - Updates "Status" to "Attempted contact"
  - Stores email draft in "Cold email draft" field
- ✅ BCC functionality for tracking
- ✅ Error handling and logging

### Limitations
- ❌ No date tracking for when emails were sent
- ❌ Limited to Zoho email provider

### Use Case
Ideal for users who want full automation of their cold email campaigns with proper status tracking in their CRM.

---

## Version 3: Full Automation with Date Tracking
**Status**: Complete solution (Current Version)

### Features
- ✅ All features from Version 2
- ✅ **NEW**: Automatic "Contacted Date" tracking
  - Records exact date and time when each email is sent
  - Updates "Contacted Date" field in Notion database
  - ISO format timestamp for precise tracking
- ✅ **NEW**: Follow-up email generation
  - Automatically generates follow-up emails for leads that meet criteria
  - Stores follow-up drafts in "Follow-Up email draft" column
  - Smart filtering based on lead status and previous contact
- ✅ Complete audit trail of all email activities
- ✅ Enhanced reporting capabilities

### Technical Implementation
```python
# When email is successfully sent:
"Contacted Date": {
    "date": {
        "start": current_date  # ISO format timestamp
    }
}

# Follow-up email criteria:
# - Status = "Attempted contact"
# - "Cold email draft" is filled
# - "Contacted Date" is filled
# - "Follow-Up email draft" is empty
# - Email address is present
```

### Use Case
Perfect for sales teams and agencies that need:
- Complete automation of cold email campaigns
- Detailed tracking of when prospects were contacted
- Automated follow-up email generation
- Full audit trail for compliance and reporting
- Integration with existing Notion CRM workflows

---

## Version Comparison Summary

| Feature | Version 1 | Version 2 | Version 3 |
|---------|-----------|-----------|-----------|
| Email Generation | ✅ | ✅ | ✅ |
| Email Sending | ❌ | ✅ | ✅ |
| Status Updates | ❌ | ✅ | ✅ |
| Date Tracking | ❌ | ❌ | ✅ |
| Follow-up Emails | ❌ | ❌ | ✅ |
| Test Mode | ❌ | ✅ | ✅ |
| Rate Limiting | ❌ | ✅ | ✅ |
| BCC Tracking | ❌ | ✅ | ✅ |

## Migration Path

- **Version 1 → Version 2**: Add SMTP configuration and enable sending
- **Version 2 → Version 3**: Add "Contacted Date" field to Notion database schema

## Database Schema Requirements

### Version 1
- Name (title)
- Email (email)
- Organisation (rich_text)
- Status (status)
- Cold email draft (rich_text)

### Version 2
- All Version 1 fields
- No additional fields required

### Version 3
- All Version 2 fields
- **Contacted Date** (date) - **Required**
- **Follow-Up email draft** (rich_text) - **Required**

## Configuration

Each version requires the same basic configuration:
- Notion API Key
- Notion Database ID
- Email template
- Email subject template

Versions 2 and 3 additionally require:
- Zoho Email
- Zoho App Password

## Future Roadmap

Potential features for future versions:
- Multi-email provider support (Gmail, Outlook, etc.)
- Email open/click tracking
- Follow-up email automation
- A/B testing capabilities
- Advanced analytics and reporting
- Integration with other CRM platforms 