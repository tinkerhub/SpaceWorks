# Telegram and email setup

Both are configured per makerspace in the staff console by someone holding `manage_makerspace` (a
Space Manager or the superadmin). Both are modules: a card only appears while its module (`telegram`,
`email`) is on.

## Before you start: the encryption key

Bot tokens, SMTP passwords and chat webhooks are stored encrypted with `API_CLIENT_ENC_KEY`. The
installer generates it. If it is missing, saving any of them fails with **503**:

> Secrets can't be saved on this server because its encryption key (API_CLIENT_ENC_KEY) isn't set.

Fix it on the server, then save again:

```bash
cd /opt/spaceworks
grep -c '^API_CLIENT_ENC_KEY=.\+' .env   # 1 = set, 0 = missing
# If missing, generate one and put it in .env as API_CLIENT_ENC_KEY=<value>:
scripts/spaceworks-compose.sh bundled run --rm --no-deps -T backend --role management \
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled up -d
```

**Back the key up and never change it casually**: with a different key, every saved token and password
becomes unreadable and must be entered again. Alerts and mail are delivered by the Celery `worker`
(the bundled stack runs it); test messages are sent directly.

## Telegram

1. In Telegram, create a bot with **@BotFather** and copy its token (`123456789:AAE…`).
2. Add the bot to your staff group. Get the group's chat ID (supergroups look like `-1001234567890`;
   a public channel can be given as `@channelname`).
3. In the console: **Settings → Integrations → Telegram alerts**. Enter **Telegram group chat ID** and
   **Telegram bot token**, then **Save integration settings**. The token is never shown again; leave
   the field blank to keep it.
4. Press **Send Telegram test alert** (disabled while you have unsaved edits).

| Test result | Fix |
|---|---|
| `not_configured` | Save both the token and the chat ID first |
| `bad_token` | Copy the whole token from BotFather again |
| `chat_not_found` | Check the chat ID, and that the bot is in the group |
| `not_in_chat` | Add the bot to the group (or let it post) |
| `rate_limited` | Wait a minute |
| `unreachable` | The server cannot reach `api.telegram.org`; check outbound internet |
| `token_unreadable` | `API_CLIENT_ENC_KEY` is missing or changed; fix it, then save the token again |
| `rejected` | Telegram's own reason is shown after the message |

Telegram is **outbound only**: alerts carry no accept/reject buttons, and decisions are made in the
console. By default it sends hardware-request and booking alerts; turn others on per feature under
**Settings → Notifications → Notification channels**.

**More than one group.** Under **Settings → Notifications → Rooms → Add a room**, pick Telegram and
enter that group's **Telegram chat ID**. Rooms reuse the makerspace's bot (add the same bot to each
group) and can be narrowed to machines, machine types or inventory categories. Until you add a room,
alerts go to the chat saved under Integrations. The test button only tests that main chat, not rooms.

`TELEGRAM_BOT_TOKEN` in the server environment is an optional deployment-wide fallback bot used when a
makerspace has none; the bundled Compose file does not pass it to the backend, so set the token in the
console instead.

## Email

There are two senders:

| Sender | Where | Used for |
|---|---|---|
| **Platform** | Superadmin: **Platform settings → Platform email** (not shown on an origin-locked site), or `EMAIL_*` / `DEFAULT_FROM_EMAIL` in `.env` | Password-reset codes, and every makerspace without its own SMTP |
| **Makerspace SMTP** | **Settings → Notifications → Email (SMTP)** | That makerspace's notification mail. Leave the host empty to use the platform sender |

`.env` example for the platform sender (any SMTP relay):

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp-relay.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-login
EMAIL_HOST_PASSWORD=your-smtp-key
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=Makerspace <noreply@example.org>
```

Then rerun `bash scripts/init-host-orchestration.sh` and `scripts/spaceworks-compose.sh bundled up -d`.
`EMAIL_BACKEND` must be the SMTP backend (the bundled Compose default); with the console backend mail
is only logged, even when a test reports success. Until some sender is configured, **Forgot
password?** is hidden and staff recover through **Users → Reset password**.

Makerspace SMTP fields: **SMTP host** (a public DNS name; IP addresses and private hosts are refused),
**SMTP port** (25, 465, 587 or 2525), **SMTP username**, **SMTP password** (write-only), **SMTP from
email**, and either **Use STARTTLS (587)** or **Use implicit SSL (465)**. **Save email settings**, then
**Send test email**: it goes to *your own* account's email address (set one on your account first) and
is recorded in the email log.

| Test message | Usually means |
|---|---|
| The mail server rejected the SMTP username or password. | Wrong login or app password |
| The mail server refused the sender address. | The from email is not allowed by that relay |
| Couldn't connect to the mail server. / refused the connection. | Wrong host or port, or outbound SMTP blocked by the host's firewall |
| The secure connection failed. | Port 587 needs STARTTLS; port 465 needs implicit SSL |
| The mail server's host name couldn't be found. | Typo in the host |
| Your account has no email address to send the test to. | Add an email to your own account |

If the test passes but nothing arrives, check spam and the relay's own logs.

## Who receives what

Under **Settings → Notifications**:

- **Notification channels** turns each channel on or off per feature.
- **Who gets notified** overrides the default (everyone whose role covers the alert) with roles, named
  people, all members or the person the message is about. Empty means the default.
- **Rooms** splits chat alerts across groups (above).
- **Advanced email mutes** silences individual email events.

**Settings → Integrations → Integration health** shows, for each channel and room, whether a
credential is stored, when it last delivered and its last error. A revoked token or webhook shows up
there first.
