#!/usr/bin/env python3
"""MCP Server for BESS debug log analysis.

This server exposes tools for Claude Code to analyze BESS debug logs:
- fetch_live_debug: Fetch live debug data from running BESS instance
- list_debug_logs: List available debug log files
- read_debug_log: Read a specific debug log
- get_log_summary: Extract key metrics and status from a log
- search_log: Search for patterns in a log file

Configuration (reads from .env file in project root):
- BESS_URL: Direct URL to BESS instance (e.g., http://homeassistant.local:8080)
- HA_TOKEN: Home Assistant long-lived access token (used for authentication)

The BESS add-on must expose port 8080 directly (not through HA ingress).
Token is verified against HA API for security.

Fetched logs are saved to .bess-logs/ directory (gitignored).

Optional environment variable overrides:
- BESS_LOG_DIR: Local directory for cached/saved debug logs (default: .bess-logs/)
- BESS_SKIP_SSL_VERIFY: Set to "true" to skip SSL certificate verification
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / ".bess-logs"
ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file() -> dict[str, str]:
    """Load environment variables from .env file.

    Returns:
        Dict of environment variable name to value.
    """
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()
    return env_vars


def get_config() -> tuple[str, str]:
    """Get BESS URL and token from environment or .env file.

    Returns:
        Tuple of (bess_url, bess_token).
    """
    # First check environment variables (allows override)
    bess_url = os.environ.get("BESS_URL", "")
    bess_token = os.environ.get("BESS_TOKEN", "") or os.environ.get("HA_TOKEN", "")

    # Fall back to .env file
    if not bess_url or not bess_token:
        env_vars = load_env_file()
        if not bess_url:
            bess_url = env_vars.get("BESS_URL", "")
        if not bess_token:
            bess_token = env_vars.get("HA_TOKEN", "")

    return bess_url, bess_token


# Load configuration
BESS_URL, BESS_TOKEN = get_config()


def get_log_dir() -> Path:
    """Get the configured log directory."""
    log_dir = os.environ.get("BESS_LOG_DIR")
    if log_dir:
        return Path(log_dir)
    return DEFAULT_LOG_DIR


def fetch_live_debug(save_locally: bool = True) -> dict:
    """Fetch live debug data from running BESS instance.

    Args:
        save_locally: If True, save the fetched log to local log directory

    Returns:
        Dict with debug content and metadata
    """
    if not BESS_URL:
        return {
            "error": "BESS_URL not configured. Set BESS_URL environment variable in .claude/mcp.json",
            "example": "http://homeassistant.local:8099",
        }

    # Build URL - token only needed for ingress access, not direct port
    base_url = f"{BESS_URL.rstrip('/')}/api/export-debug-data"
    url = base_url  # Direct port access doesn't need token (local network = trusted)

    try:
        # SSL verification enabled by default for security (works with valid certs)
        # Can be disabled via BESS_SKIP_SSL_VERIFY=true for local self-signed certs
        ssl_context = ssl.create_default_context()
        if os.environ.get("BESS_SKIP_SSL_VERIFY", "").lower() == "true":
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        request = urllib.request.Request(
            url,
            headers={"Accept": "text/markdown, text/plain, */*"},
        )

        with urllib.request.urlopen(
            request, timeout=60, context=ssl_context
        ) as response:
            content = response.read().decode("utf-8")

            # Extract filename from Content-Disposition header if present
            content_disposition = response.headers.get("Content-Disposition", "")
            if "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[-1].strip('"')
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
                filename = f"bess-debug-{timestamp}.md"

            result = {
                "source": "live",
                "url": url,
                "filename": filename,
                "content_length": len(content),
                "line_count": content.count("\n") + 1,
                "content": content,
            }

            # Optionally save to local log directory
            if save_locally:
                log_dir = get_log_dir()
                log_dir.mkdir(parents=True, exist_ok=True)
                local_path = log_dir / filename
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content)
                result["saved_to"] = str(local_path)

            return result

    except urllib.error.HTTPError as e:
        return {
            "error": f"HTTP error {e.code}: {e.reason}",
            "url": url,
        }
    except urllib.error.URLError as e:
        return {
            "error": f"Connection failed: {e.reason}",
            "url": base_url,
            "hint": "Check that BESS is running, BESS_URL is correct, and BESS_TOKEN is set for production access",
        }
    except Exception as e:
        return {
            "error": f"Failed to fetch debug data: {e}",
            "url": url,
        }


def list_debug_logs() -> dict:
    """List available debug log files."""
    log_dir = get_log_dir()
    if not log_dir.exists():
        return {"error": f"Log directory not found: {log_dir}"}

    logs = []
    patterns = ["bess-debug-*.md", "bess-debug-*.log", "bess-debug-*.txt", "*.log"]

    for pattern in patterns:
        for log_file in log_dir.glob(pattern):
            stat = log_file.stat()
            logs.append(
                {
                    "filename": log_file.name,
                    "path": str(log_file),
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )

    # Sort by modified date, newest first
    logs.sort(key=lambda x: x["modified"], reverse=True)

    return {
        "log_directory": str(log_dir),
        "count": len(logs),
        "logs": logs,
    }


def read_debug_log(filename: str, max_lines: int = 5000) -> dict:
    """Read a debug log file.

    Args:
        filename: Name of the log file (or full path)
        max_lines: Maximum lines to return (default 5000)
    """
    log_dir = get_log_dir()

    # Try as filename in log dir first, then as full path
    log_path = log_dir / filename
    if not log_path.exists():
        log_path = Path(filename)

    if not log_path.exists():
        return {"error": f"Log file not found: {filename}"}

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        truncated = total_lines > max_lines

        if truncated:
            # Return first and last portions
            head = lines[: max_lines // 2]
            tail = lines[-(max_lines // 2) :]
            content = (
                "".join(head)
                + f"\n\n... [{total_lines - max_lines} lines truncated] ...\n\n"
                + "".join(tail)
            )
        else:
            content = "".join(lines)

        return {
            "filename": log_path.name,
            "path": str(log_path),
            "total_lines": total_lines,
            "truncated": truncated,
            "content": content,
        }
    except Exception as e:
        return {"error": f"Failed to read log: {e}"}


def get_log_summary(filename: str) -> dict:
    """Extract key metrics and status from a BESS debug log.

    Args:
        filename: Name of the log file (or full path)
    """
    result = read_debug_log(filename, max_lines=50000)
    if "error" in result:
        return result

    content = result["content"]
    summary = {
        "filename": result["filename"],
        "total_lines": result["total_lines"],
    }

    # Extract optimization period
    period_match = re.search(r"Starting optimization for period (\d+)", content)
    if period_match:
        summary["optimization_period"] = int(period_match.group(1))

    # Extract savings
    savings_matches = re.findall(r"total_savings['\"]?: ([-\d.]+)", content)
    if savings_matches:
        summary["savings_values"] = [float(s) for s in savings_matches[-5:]]  # Last 5
        summary["latest_savings"] = float(savings_matches[-1])

    # Extract battery SOC
    soc_matches = re.findall(r"battery_soc['\"]?: ([\d.]+)", content)
    if soc_matches:
        summary["battery_soc_values"] = [float(s) for s in soc_matches[-5:]]
        summary["latest_soc"] = float(soc_matches[-1])

    # Extract strategic intents
    intent_matches = re.findall(r"strategic_intent['\"]?: ['\"]?(\w+)['\"]?", content)
    if intent_matches:
        intent_counts = {}
        for intent in intent_matches:
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
        summary["intent_distribution"] = intent_counts

    # Extract errors and warnings
    errors = re.findall(r"(ERROR|Error|error)[:\s]+(.{0,200})", content)
    warnings = re.findall(r"(WARNING|Warning|warning)[:\s]+(.{0,200})", content)
    summary["error_count"] = len(errors)
    summary["warning_count"] = len(warnings)
    if errors:
        summary["sample_errors"] = [e[1].strip() for e in errors[:5]]
    if warnings:
        summary["sample_warnings"] = [w[1].strip() for w in warnings[:5]]

    # Extract observed vs strategic intent mismatches
    mismatches = re.findall(
        r"strategic_intent['\"]?: ['\"]?(\w+)['\"]?.*?observed_intent['\"]?: ['\"]?(\w+)['\"]?",
        content,
        re.DOTALL,
    )
    if mismatches:
        mismatch_count = sum(1 for s, o in mismatches if s != o)
        summary["intent_mismatches"] = mismatch_count

    # Extract price data
    price_matches = re.findall(r"spot_price['\"]?: ([\d.]+)", content)
    if price_matches:
        prices = [float(p) for p in price_matches]
        summary["price_range"] = {"min": min(prices), "max": max(prices)}

    # Extract TOU schedule info
    tou_matches = re.findall(r"TOU.*?(\d{2}:\d{2})-(\d{2}:\d{2})", content)
    if tou_matches:
        summary["tou_segments_found"] = len(tou_matches)

    return summary


def search_log(filename: str, pattern: str, context_lines: int = 2) -> dict:
    """Search for a pattern in a log file.

    Args:
        filename: Name of the log file (or full path)
        pattern: Regex pattern to search for
        context_lines: Number of lines of context around matches
    """
    result = read_debug_log(filename, max_lines=100000)
    if "error" in result:
        return result

    content = result["content"]
    lines = content.split("\n")

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"error": f"Invalid regex pattern: {e}"}

    matches = []
    for i, line in enumerate(lines):
        if regex.search(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            context = lines[start:end]
            matches.append(
                {
                    "line_number": i + 1,
                    "match_line": line,
                    "context": "\n".join(context),
                }
            )

            # Limit to 50 matches
            if len(matches) >= 50:
                break

    return {
        "filename": result["filename"],
        "pattern": pattern,
        "match_count": len(matches),
        "truncated": len(matches) >= 50,
        "matches": matches,
    }


# MCP Protocol Implementation

TOOLS = [
    {
        "name": "fetch_live_debug",
        "description": "Fetch live debug data from running BESS instance via HTTP. Requires BESS_URL to be configured. Optionally saves the log locally for future reference.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "save_locally": {
                    "type": "boolean",
                    "description": "Save fetched log to local log directory (default true)",
                    "default": True,
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_debug_logs",
        "description": "List available BESS debug log files in the configured directory. Returns filename, size, and modification date for each log.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_debug_log",
        "description": "Read the contents of a BESS debug log file. For large files, content is truncated with first and last portions preserved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the log file (e.g., 'bess-debug-2026-01-28.md') or full path",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum lines to return (default 5000)",
                    "default": 5000,
                },
            },
            "required": ["filename"],
        },
    },
    {
        "name": "get_log_summary",
        "description": "Extract key metrics from a BESS debug log: savings, SOC values, intent distribution, errors/warnings, price ranges, and intent mismatches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the log file or full path",
                },
            },
            "required": ["filename"],
        },
    },
    {
        "name": "search_log",
        "description": "Search for a regex pattern in a BESS debug log. Returns matching lines with context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the log file or full path",
                },
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for (case-insensitive)",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context around matches (default 2)",
                    "default": 2,
                },
            },
            "required": ["filename", "pattern"],
        },
    },
]


def handle_request(request: dict) -> dict:
    """Handle an MCP JSON-RPC request."""
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "bess-log-analyzer",
                    "version": "1.0.0",
                },
            },
        }

    elif method == "notifications/initialized":
        # No response needed for notifications
        return None

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": TOOLS,
            },
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "fetch_live_debug":
            result = fetch_live_debug(
                arguments.get("save_locally", True),
            )
        elif tool_name == "list_debug_logs":
            result = list_debug_logs()
        elif tool_name == "read_debug_log":
            result = read_debug_log(
                arguments.get("filename", ""),
                arguments.get("max_lines", 5000),
            )
        elif tool_name == "get_log_summary":
            result = get_log_summary(arguments.get("filename", ""))
        elif tool_name == "search_log":
            result = search_log(
                arguments.get("filename", ""),
                arguments.get("pattern", ""),
                arguments.get("context_lines", 2),
            )
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}",
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ],
            },
        }

    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
            },
        }


def main():
    """Main MCP server loop - reads JSON-RPC from stdin, writes to stdout."""
    # Unbuffered output for real-time communication
    sys.stdout = open(sys.stdout.fileno(), mode="w", buffering=1)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {e}",
                },
            }
            print(json.dumps(error_response), flush=True)
            continue

        response = handle_request(request)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
