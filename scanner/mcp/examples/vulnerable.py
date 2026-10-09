# SAST-only fixture: never launched by the platform.
import os
import subprocess
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("sast-vulnerable-fixture")

@mcp.tool()
def calculate(expression: str):
    return eval(expression)

@mcp.tool()
def run_command(command: str):
    return subprocess.check_output(command, shell=True)

@mcp.tool()
def read_file(path: str):
    return open(path).read()

@mcp.tool()
def environment():
    return dict(os.environ)
