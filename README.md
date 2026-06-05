# Claude Code Notify

A notification bot that monitors Claude Code sessions across multiple servers and sends alerts via Feishu (Lark) when tasks start, complete, or run for too long.

## Features

- **Multi-server monitoring**: Monitor Claude Code sessions on multiple remote servers via SSH
- **Smart notifications**: Only notify when:
  - A new task starts (session becomes busy)
  - A task completes (session becomes idle)
  - User message changes (new task detected)
  - Task runs longer than threshold (default: 30 minutes)
- **Duplicate prevention**: Track notification state to avoid repeated alerts
- **Background running**: Run as a daemon with auto-restart on failure
- **Feishu integration**: Send private chat notifications using Feishu Open API

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Local Machine                          │
│                                                             │
│  ┌─────────────────┐      ┌─────────────────────────────┐  │
│  │ claude-notify   │      │  Feishu Open API            │  │
│  │ (Python)        │─────▶│  - Private chat messages    │  │
│  └────────┬────────┘      └─────────────────────────────┘  │
│           │                                                 │
│           │ SSH (every 10s)                                 │
│           ▼                                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  ~/.claude/sessions/*.json                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
           │                    │                    │
           ▼                    ▼                    ▼
    ┌──────────┐         ┌──────────┐         ┌──────────┐
    │ Server 1 │         │ Server 2 │         │ Server N │
    └──────────┘         └──────────┘         └──────────┘
```

## Installation

```bash
git clone https://github.com/your-username/claude-notify.git
cd claude-notify
pip install -r requirements.txt
```

## Configuration

Create config file at `~/.config/claude-notify/config.json`:

```json
{
  "servers": [
    {
      "name": "Production",
      "ssh_host": "prod-server"
    },
    {
      "name": "Development",
      "ssh_host": "dev-server"
    }
  ],
  "poll_interval": 10,
  "notify": {
    "on_task_complete": true,
    "on_task_start": true,
    "on_long_running": true,
    "long_running_threshold_minutes": 30
  },
  "feishu": {
    "webhook_url": "",
    "app_id": "cli_xxxxx",
    "app_secret": "xxxxx",
    "chat_id": "",
    "user_id": "ou_xxxxx"
  }
}
```

### Configuration Fields

| Field | Description |
|-------|-------------|
| `servers[].name` | Display name for the server |
| `servers[].ssh_host` | SSH host alias (from `~/.ssh/config`) |
| `poll_interval` | Polling interval in seconds |
| `notify.on_task_complete` | Notify when task completes |
| `notify.on_task_start` | Notify when task starts |
| `notify.on_long_running` | Notify when task runs too long |
| `notify.long_running_threshold_minutes` | Minutes before long-running alert |
| `feishu.app_id` | Feishu app ID |
| `feishu.app_secret` | Feishu app secret |
| `feishu.user_id` | Your Feishu open_id (for private chat) |

## Usage

### Start monitoring

```bash
./run.sh
```

### Stop monitoring

```bash
./stop.sh
```

### Check status

```bash
./status.sh
```

### View logs

```bash
tail -f monitor.log
```

## How It Works

1. **Session Detection**: Read `~/.claude/sessions/*.json` on each server via SSH
2. **State Tracking**: Track each session's status (busy/idle) and user messages
3. **Notification Logic**:
   - New session found with `status=busy` → Task start notification
   - Status changes from `busy` to `idle` → Task complete notification
   - Status remains `busy` but user message changes → New task notification
   - Status remains `busy` for > threshold → Long-running notification
4. **Deduplication**: Use `start_notified` and `complete_notified` flags to prevent duplicates

## Feishu Setup

1. Create a Feishu app at [open.feishu.cn](https://open.feishu.cn)
2. Add permissions:
   - `im:message:send_as_bot` (send messages)
   - `contact:user.id:readonly` (lookup user by phone)
3. Get your `open_id` via API or Feishu developer console
4. Configure in `config.json`

## Requirements

- Python 3.9+
- SSH access to target servers
- Feishu app with messaging permissions

## License

MIT
