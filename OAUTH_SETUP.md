# OAuth Setup For Regular Users

## Current State

The repo supports both authentication modes:

- service-account authentication for automation-oriented identities
- OAuth authentication for regular user accounts

The server can decide between them based on the configured email identity.

## Authentication Model

```text
automation-bot@your-project.iam.gserviceaccount.com -> service account
user@example.com                                    -> OAuth user flow
```

## Setup Steps

### 1. Create an OAuth Client

1. Open Google Cloud Console credentials
2. Create an OAuth client ID
3. Choose a web application client
4. Add your configured callback endpoints
5. Download the generated client credentials JSON

Register exact callback URLs. Wildcards are rejected. Use HTTPS for an external
callback, or HTTP only for a loopback callback, for example:

```text
https://oauth.example.com/oauth2callback
http://127.0.0.1:8000/oauth2callback
```

### 2. Configure Environment

```bash
export GOOGLE_OAUTH_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_OAUTH_CLIENT_SECRET="your-client-secret"

# Optional alternative
export GOOGLE_CLIENT_SECRET_PATH="/path/to/oauth-client.json"
chmod 600 /path/to/oauth-client.json
```

The file must be a regular file owned by the runtime user; symbolic links and
group/world-readable modes are rejected. Streamable HTTP listens on
`127.0.0.1` unless a deployment explicitly sets both a remote
`WORKSPACE_MCP_BIND_HOST` and `WORKSPACE_MCP_ALLOW_REMOTE_BIND=true`.

### 3. Enable Required APIs

Enable whichever Google APIs your deployment needs, for example:

- Google Sheets API
- Google Calendar API
- Gmail API
- Google Drive API

## Testing OAuth

Start the repo with its normal local setup command, then test with a regular user identity such as:

```text
user@example.com
```

Expected flow:

1. The server detects a regular user account
2. It generates an authorization URL
3. The user grants access
4. Credentials are stored and reused for later requests

## Configuration Summary

### Service Account

```bash
USER_GOOGLE_EMAIL="automation-bot@your-project.iam.gserviceaccount.com"
GOOGLE_CLIENT_SECRET_PATH="/path/to/service-account-key.json"
```

### OAuth User

```bash
GOOGLE_OAUTH_CLIENT_ID="your-id.apps.googleusercontent.com"
GOOGLE_OAUTH_CLIENT_SECRET="your-secret"
```

### API Key

```bash
GOOGLE_API_KEY="your-api-key"
```

## Multi-User Support

Credentials can be stored per user identity, for example:

- `user1@example.com`
- `user2@example.com`

## Troubleshooting

### Service Account JSON Used For OAuth

- cause: service-account credentials were used where an OAuth client was required
- fix: create a dedicated OAuth client ID

### Callback Misconfiguration

- cause: callback endpoint does not match the configured OAuth client
- fix: align the configured callback endpoints with the OAuth client settings

## Outcome

OAuth support is available for regular users once client credentials and callback configuration are
set correctly.
