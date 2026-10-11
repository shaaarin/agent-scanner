from mcp.server.fastmcp import FastMCP
mcp = FastMCP("sast-safe-fixture")

@mcp.tool()
def add(a: int, b: int):
    return a + b
