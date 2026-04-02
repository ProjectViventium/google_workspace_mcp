# 🔐 Google Workspace MCP - Authentication Methods

## Three Ways to Authenticate (Priority Order)

### 1. 🔑 API Key (PUBLIC Sheets - EASIEST!)

**For:** Reading **public** or **view-only** spreadsheets
**Setup:**
```bash
export GOOGLE_API_KEY="YOUR_API_KEY_HERE"
```

**Get an API Key:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create API Key
3. Enable Google Sheets API
4. Copy the key

**Pros:**
- ✅ No OAuth needed
- ✅ Works for public sheets instantly
- ✅ No browser clicks
- ✅ Perfect for read-only access

**Cons:**
- ❌ Can't modify sheets
- ❌ Can't access private sheets

---

### 2. 🤖 Service Account (SERVER-SIDE - AUTOMATED!)

**For:** Server/bot access to private sheets (what we're using now)
**Setup:**
```bash
export GOOGLE_CLIENT_SECRET_PATH="/path/to/service-account.json"
export USER_GOOGLE_EMAIL="your-bot@project.iam.gserviceaccount.com"
```

**Pros:**
- ✅ No OAuth needed
- ✅ Works for private sheets (if shared with service account)
- ✅ Fully automated
- ✅ Can read AND write

**Cons:**
- ❌ Sheets must be explicitly shared with service account email
- ❌ Requires service account setup in Google Cloud

---

### 3. 🔐 OAuth (USER ACCESS - MOST POWERFUL!)

**For:** User authentication, accessing user's private sheets
**Setup:** Automatic - user clicks auth link

**Pros:**
- ✅ Access user's private sheets
- ✅ Full permissions
- ✅ Can read AND write

**Cons:**
- ❌ Requires browser click
- ❌ User must grant permissions
- ❌ Not good for automation

---

## How It Works

The code checks in this order:

```python
1. Has GOOGLE_API_KEY? → Use API key (public access)
2. Is service account email? → Use service account (automated)
3. Else → Use OAuth (user auth)
```

---

## Quick Fix for Your Case

Since the spreadsheet is **public**, just add an API key:

```bash
# In test_setup.sh
export GOOGLE_API_KEY="YOUR_GOOGLE_API_KEY"
```

Then restart the server - it will use the API key and work instantly! No service account, no OAuth! ✨

---

## Testing

```bash
# Start server
cd google_workspace_mcp
./test_setup.sh
```

Expected log:
```
[INFO] Using API key for public/readonly access
[INFO] Successfully built sheets service with API key
```

Or with service account:
```
[INFO] Detected service account: viventium-bot-mcp@...
[INFO] Loading service account from: .../service-account.json
[INFO] Service account authenticated successfully
```

---

**Status:** ✅ All three methods now supported!
