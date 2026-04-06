#!/usr/bin/env python3
"""MCP SSH Server for security audit of 95.211.47.37"""

import asyncio
import paramiko
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

SSH_HOST = "95.211.47.37"
SSH_USER = "root"
SSH_KEY = "/Users/azamatyakubov/.ssh/id_ed25519_zaliv"

app = Server("ssh-audit-server")


def run_ssh(command: str) -> str:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=SSH_HOST,
            username=SSH_USER,
            key_filename=SSH_KEY,
            timeout=30,
        )
        stdin, stdout, stderr = client.exec_command(command, timeout=60)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out + (f"\n[stderr]: {err}" if err.strip() else "")
    finally:
        client.close()


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="ssh_exec",
            description="Execute any shell command on the remote server 95.211.47.37 (root access). Use for full server management: install packages, edit configs, restart services, manage Docker containers, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run on the remote server",
                    }
                },
                "required": ["command"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "ssh_exec":
        command = arguments["command"]
        result = await asyncio.get_event_loop().run_in_executor(
            None, run_ssh, command
        )
        return [types.TextContent(type="text", text=result)]
    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
