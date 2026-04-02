# Service Account Authentication Fix

## Problem

The MCP server originally tried to use the OAuth browser flow for service-account identities. That
fails because service accounts should authenticate directly with their JSON key file.

## Solution

Add service-account detection in the Google auth layer and branch authentication accordingly:

- service-account emails ending in `.gserviceaccount.com` use direct key-based credentials
- regular user emails continue using the OAuth flow

## Example Logic

```python
is_service_account = user_google_email.endswith(".gserviceaccount.com")

if is_service_account:
    credentials = service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=required_scopes,
    )
else:
    credentials = get_credentials(...)
```

## Configuration

Use placeholders like these in local setup:

```bash
export GOOGLE_CLIENT_SECRET_PATH="/path/to/service-account-key.json"
export USER_GOOGLE_EMAIL="automation-bot@your-project.iam.gserviceaccount.com"
```

## Expected Behavior

For service accounts:

1. Detect the service-account identity
2. Load credentials from the configured JSON key file
3. Authenticate directly without browser OAuth
4. Return an authenticated service client

For regular users:

1. Use the existing OAuth flow
2. Generate an authorization URL
3. Store credentials after consent
4. Reuse cached credentials when available

## Test Approach

Start the repo's normal dev setup and confirm logs show service-account detection plus successful
direct authentication.

For a spreadsheet test, use a generic sheet URL shape such as:

```text
https://docs.google.com/spreadsheets/d/<sheet-id>
```

## Files Modified

- `auth/google_auth.py`

## Outcome

- no browser OAuth required for service accounts
- regular-user OAuth support remains intact
- automation and local testing both stay supported
