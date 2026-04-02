# 🛠️ Enable Google Workspace Services

## ✅ Currently Enabled

After the latest update:
- ✅ **Sheets** - Read/write spreadsheets
- ✅ **Calendar** - Manage calendar events

---

## 📋 All Available Services (10 Total)

The MCP server supports these Google Workspace services:

| Service | Tools | Key Features |
|---------|-------|--------------|
| **sheets** | 11 tools | Read/write cells, create spreadsheets, manage sheets, comments |
| **calendar** | 5 tools | List calendars, get/create/modify/delete events |
| **gmail** | ~8 tools | Read/send emails, manage labels, search |
| **drive** | ~10 tools | List/upload/download files, manage folders, permissions |
| **docs** | ~6 tools | Create/read/edit documents |
| **chat** | ~5 tools | Send messages, manage spaces |
| **forms** | ~4 tools | Create/read forms, manage responses |
| **slides** | ~5 tools | Create/edit presentations |
| **tasks** | ~6 tools | Manage Google Tasks lists |
| **search** | ~3 tools | Search across Google Workspace |

---

## 🚀 How to Enable Services

### Option 1: Enable Specific Services (Recommended)

Edit `test_setup.sh` line 84:

```bash
# Enable Sheets + Calendar + Gmail
uv run main.py --transport streamable-http --tools sheets calendar gmail

# Enable all core services
uv run main.py --transport streamable-http --tools sheets calendar gmail drive docs
```

### Option 2: Enable ALL Services

```bash
# Remove --tools argument to load everything
uv run main.py --transport streamable-http
```

Or use all services explicitly:
```bash
uv run main.py --transport streamable-http --tools gmail drive calendar docs sheets chat forms slides tasks search
```

---

## 📅 Calendar Tools Available

Now that Calendar is enabled, you can:

### 1. **list_calendars**
List all accessible calendars
```
Show my calendars
```

### 2. **get_events**
Get calendar events (with filters)
```
What's on my calendar today?
Show events from Nov 1-15
```

### 3. **create_event**
Create new calendar events
```
Schedule meeting with John tomorrow at 2pm
Create event "Team Sync" on Friday 3-4pm
```

### 4. **modify_event**
Update existing events
```
Move my 3pm meeting to 4pm
Add attendees to event ID abc123
```

### 5. **delete_event**
Delete calendar events
```
Cancel event ID abc123
```

---

## 🔑 Required Scopes

Calendar tools need these Google API scopes:

```python
'https://www.googleapis.com/auth/calendar'          # Full calendar access
'https://www.googleapis.com/auth/calendar.events'   # Events only
'https://www.googleapis.com/auth/calendar.readonly' # Read-only
```

Your service account already has these if configured properly!

---

## 🧪 Testing Calendar

### Restart Server
```bash
cd google_workspace_mcp
./test_setup.sh
```

Should show:
```
✅ Dependencies ready

🚀 Starting MCP server...
   Transport: HTTP (streamable-http)
   Port: 8000
   Tools: Sheets + Calendar  ← NEW!
   Mode: Single-user
```

### Test in Telegram

```
/mcp_list
```

Should show Calendar tools:
```
📅 Calendar Tools:
- list_calendars
- get_events
- create_event
- modify_event
- delete_event
```

Then try:
```
Show my calendars
What's on my calendar today?
Create event "Test Meeting" tomorrow at 2pm
```

---

## 📦 Adding More Services

Want Gmail too? Just add it:

```bash
# In test_setup.sh line 84:
uv run main.py --transport streamable-http --tools sheets calendar gmail
```

Want Drive for file uploads?
```bash
uv run main.py --transport streamable-http --tools sheets calendar gmail drive
```

Want EVERYTHING?
```bash
uv run main.py --transport streamable-http
# (No --tools argument = all services)
```

---

## ⚠️ Important Notes

1. **Service Account Permissions**: Your service account needs access to calendars
   - For personal calendar: Share calendar with service account email
   - For domain: Grant domain-wide delegation

2. **API Enablement**: Make sure Google Calendar API is enabled in Cloud Console
   - Go to [APIs & Services](https://console.cloud.google.com/apis/library)
   - Search "Google Calendar API"
   - Click "Enable"

3. **Scopes**: Service account needs calendar scopes configured

---

**Status:** ✅ Calendar enabled! Restart server to use it! 🎉
