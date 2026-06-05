# Development Log

## 2026-06-05

### Project Initialization

- Created project structure with modular design
- Implemented SSH connection pool using subprocess
- Implemented session parser to read `~/.claude/sessions/*.json`
- Implemented task extractor to parse Claude Code logs
- Implemented Feishu notification module using Open API
- Implemented main monitoring loop with state tracking

### Key Design Decisions

1. **SSH Connection**: Use subprocess with SSH host aliases instead of paramiko
   - Simpler, leverages existing `~/.ssh/config`
   - Supports jump hosts via ProxyCommand

2. **Notification Logic**: Track by session_id + user message
   - Avoid duplicate notifications for same task
   - Detect new tasks by message content change

3. **State Management**: In-memory dict with notify flags
   - `start_notified`: Prevent repeated start notifications
   - `complete_notified`: Prevent repeated complete notifications
   - `last_user_message`: Detect task changes

### Bug Fixes

#### Fix 1: Repeated Notifications

**Problem**: Same task triggered multiple "task start" notifications

**Root Cause**: SSH connection instability caused sessions to be removed and re-detected

**Solution**: 
- Track notification state by session_id
- Only notify when status actually changes or user message changes
- Remove complex cleanup logic that was causing false deletions

#### Fix 2: Missing Completion Notifications

**Problem**: Task completion notifications were not sent

**Root Cause**: Cooldown timer prevented notifications within 30 seconds of previous notification

**Solution**: Remove cooldown timer, rely on state flags instead

### Feishu Integration

- Used Feishu Open API for private chat notifications
- Retrieved user open_id via phone number lookup API
- Configured app permissions: `contact:user.id:readonly`

### Testing

- Verified SSH connections to ZJUtt and ZJUtt_1531
- Verified Feishu notification delivery
- Verified state change detection (idle → busy → idle)
- Verified duplicate notification prevention

---

## Future Improvements

- [ ] Support for more notification channels (Telegram, Discord, etc.)
- [ ] Web dashboard for monitoring status
- [ ] Historical task tracking and statistics
- [ ] Configurable notification templates
- [ ] Support for Claude Code session names/labels
