# Plan: Replacing tmux with systemd User Services

## Goal
Remove the dependency on `tmux` for managing the Persona services. Replace it with a robust, OS-native process management system that reduces administrative overhead and improves the development loop.

## The Problem with tmux
- **Administrative Friction**: Managing sessions, panes, and windows is a chore.
- **Opaque Logging**: Viewing logs requires attaching to a session and switching windows.
- **Slow Iteration**: Restarting the "whole stack" via a script is slower than restarting a single service.
- **Clumsiness**: Managing the lifecycle of the Chromium window alongside tmux sessions feels disconnected.

## Proposed Solution: systemd User Services
Leverage the built-in `systemd` user instance to manage the four core services as background daemons.

### 1. Service Architecture
Create four unit files in `~/.config/systemd/user/`:
- `persona-hub.service`
- `persona-llm.service`
- `persona-speech-output.service`
- `persona-speech-input.service`

Each service will be configured to:
- Start in the project directory.
- Use `uv run` to ensure the correct environment.
- Automatically restart on failure.

### 2. The New "Launcher" (persona_start.sh)
The shell script will shift from "Process Manager" to "UI Launcher":
1. **Trigger Services**: Call `systemctl --user start persona-hub persona-llm ...`
2. **Handle UI**: 
   - Close existing `persona_chat` windows.
   - Launch the Chromium app window.
3. **User Experience**: The user just runs `./persona_start.sh` and the window appears.

### 3. New Operational Flow
| Action | Tmux Way | systemd Way |
| :--- | :--- | :--- |
| **Start everything** | `./persona_start.sh` | `./persona_start.sh` |
| **Check Logs** | `tmux attach` $\rightarrow$ switch windows | `journalctl --user -f` |
| **Restart Hub** | Kill session $\rightarrow$ `./persona_start.sh` | `systemctl --user restart persona-hub` |
| **Stop everything** | `tmux kill-session` | `systemctl --user stop persona-hub ...` |
| **Debug a service** | Attach to tmux and watch | `journalctl --user -u persona-llm -f` |

## Implementation Steps
1. **Define Service Files**: Write the `.service` templates with correct paths and dependencies.
2. **Install Services**: Move files to `~/.config/systemd/user/` and run `systemctl --user daemon-reload`.
3. **Refactor Launcher**: Rewrite `persona_start.sh` to use `systemctl` commands instead of `tmux send-keys`.
4. **Update Shutdown**: Update `persona_shutdown.sh` to stop the services.
5. **Verify**: Ensure services start in the correct order (Output $\rightarrow$ LLM $\rightarrow$ Hub $\rightarrow$ Input).

## Benefits
- **Solid Ground**: The OS manages the processes. If the Hub crashes, systemd brings it back.
- **Developer Velocity**: Restarting just the Hub (where most changes happen) takes milliseconds.
- **Simplicity**: No more tmux keybindings or session management.
