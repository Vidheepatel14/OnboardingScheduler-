import base64
from email.mime.text import MIMEText
from .auth import get_google_service


def send_invite(email, task_name, start_time, end_time):
    from .google_cal import create_calendar_invite

    return create_calendar_invite(email, task_name, start_time, end_time)

def draft_hr_email(user_email, email_body):
    """
    Sends an AI-drafted email to HR on behalf of the user.
    """
    service = get_google_service('gmail', 'v1')
    hr_email_address = "hr@yourcompany.com" # Change to your test email
    
    subject = f"Policy Question Escalation from {user_email}"
    
    # The AI is now writing the entire body of the email!
    message = MIMEText(email_body)
    message['to'] = hr_email_address
    message['from'] = "me" 
    message['subject'] = subject
    
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    
    try:
        service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
        return "SUCCESS: AI-drafted email sent to HR."
    except Exception as e:
        return f"ERROR: Failed to send email. {str(e)}"
