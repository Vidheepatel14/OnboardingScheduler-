from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config.settings import LOCAL_TIMEZONE, WORK_END_HOUR, WORK_START_HOUR
from .auth import get_google_service

LOCAL_TZ = ZoneInfo(LOCAL_TIMEZONE)


def _parse_google_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _parse_user_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def find_free_slots():
    service = get_google_service('calendar', 'v3')
    now = datetime.now(LOCAL_TZ)
    free_slots = []
    
    for i in range(5): # Check next 5 days
        day_start = (now + timedelta(days=i)).replace(hour=WORK_START_HOUR, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(hour=WORK_END_HOUR)
        
        # Skip weekends or past time
        if day_start.weekday() >= 5 or day_end < now: continue
        
        events_result = service.events().list(
            calendarId='primary', timeMin=day_start.isoformat(), timeMax=day_end.isoformat(),
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        current = day_start
        for event in events:
            start = _parse_google_datetime(event['start'].get('dateTime', event['start'].get('date')))
            
            if start > current:
                duration = (start - current).total_seconds() / 3600
                if duration >= 0.5:
                    free_slots.append(f"{current.isoformat()} to {start.isoformat()}")
            
            end = _parse_google_datetime(event['end'].get('dateTime', event['end'].get('date')))
            current = max(current, end)
            
        if current < day_end:
            free_slots.append(f"{current.isoformat()} to {day_end.isoformat()}")
            
    return free_slots


def create_calendar_invite(email: str, task_name: str, start_time: str, end_time: str) -> str:
    service = get_google_service('calendar', 'v3')
    start_dt = _parse_user_datetime(start_time)
    end_dt = _parse_user_datetime(end_time)

    event = {
        "summary": f"ONBOARDING: {task_name}",
        "description": f"Scheduled by AI Onboarding Concierge for onboarding task: {task_name}",
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": LOCAL_TIMEZONE,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": LOCAL_TIMEZONE,
        },
        "reminders": {"useDefault": True},
    }
    if email:
        event["attendees"] = [{"email": email}]

    created_event = service.events().insert(
        calendarId="primary",
        body=event,
        sendUpdates="all",
    ).execute()
    event_link = created_event.get("htmlLink")
    if event_link:
        return f"Calendar event created: {event_link}"
    return "Calendar event created"
