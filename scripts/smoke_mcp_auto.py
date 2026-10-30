"""Live API/MCPB regression for automatic argument checks; no mock services.

MCP_TEST_API=http://localhost:8000 python3 scripts/smoke_mcp_auto.py
Creates a disposable real MCP server inside worker jobs. Records are retained.
"""
import io
import json
import os
from pathlib import Path
import time
import urllib.request
import uuid
import zipfile

from smoke_mcp import BASE, api

SOURCE = '''import asyncio, json, os, subprocess
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
server = Server("automatic-argument-regression")
def definition(name, field, schema):
    return Tool(name=name, inputSchema={"type":"object","properties":{field:schema},"required":[field]})
@server.list_tools()
async def tools():
    base = [definition("evaluate", "expression", {"type":"string"}),
            definition("compute_js", "expression", {"type":"string"}),
            definition("echo", "text", {"type":"string"}),
            definition("parse_json", "document", {"type":"string"}),
            definition("write_file", "path", {"type":"string"}),
            definition("enum_value", "value", {"type":"string","enum":["one","two"]}),
            definition("external_schema", "text", {"$ref":"https://example.invalid/schema"}),
            definition("regex_schema", "text", {"type":"string","pattern":"^(a+)+$"})]
    return base + [definition(f"echo_{i}", "text", {"type":"string"}) for i in range(int(os.environ.get("AUTO_EXTRA_TOOLS", "0")))]
@server.call_tool()
async def call(name, arguments):
    if name.startswith("echo_"):
        text = arguments["text"]
    elif name == "evaluate":
        text = str(eval(arguments["expression"]))
    elif name == "compute_js":
        code = "try { console.log(eval(process.argv[1])); } catch (e) { console.log(e.message); }"
        text = subprocess.check_output(["node", "-e", code, arguments["expression"]],text=True)
    elif name == "echo":
        text = arguments["text"]
    elif name == "parse_json":
        text = json.dumps(json.loads(arguments["document"]))
    else:
        raise RuntimeError("Excluded tools must never be called by automatic checks")
    return [TextContent(type="text",text=text)]
async def main():
    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())
asyncio.run(main())
'''


def upload():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        archive.writestr('manifest.json',json.dumps({'manifest_version':'0.3','name':'automatic-check-regression','version':'1.0.0',
            'server':{'type':'python','entry_point':'server.py','mcp_config':{'command':'python','args':['server.py']}}}))
        archive.writestr('server.py',SOURCE)
    boundary='auto-'+uuid.uuid4().hex
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="auto.mcpb"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+data.getvalue()+f'\r\n--{boundary}--\r\n'.encode()
    req=urllib.request.Request(BASE+'/mcp-artifacts/upload',data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(req,timeout=30) as response:
        return json.load(response)


def run(asset,name,config):
    scan=api('/scans',{'name':name,'type':'mcp','asset_kind':'mcp','asset_id':asset['id'],
        'session_id':'auto-regression-'+uuid.uuid4().hex,'config':{'scanner_ids':['mcp_dynamic'],'timeout_seconds':60,**config}})
    api(f"/scans/{scan['id']}/start",{})
    deadline=time.monotonic()+100
    while time.monotonic()<deadline:
        scan=api(f"/scans/{scan['id']}")
        if scan['status'] in {'success','partially_failed','failed'}:
            break
        time.sleep(1)
    result=json.loads(scan.get('results') or '{}')
    report=api(f"/scans/{scan['id']}/report")
    return {'name':name,'scan_id':scan['id'],'status':scan['status'],'config':json.loads(scan['config']),'result':result,'report':report}


def main():
    artifact=upload()
    asset=api('/mcp-assets',{'name':'Автопроверки: живая регрессия '+uuid.uuid4().hex[:8],
        'config':{'kind':'bundle','artifact_id':artifact['id'],'user_config':{}}})
    rows=[]
    baseline=run(asset,'auto: disabled',{})
    assert baseline['status']=='success' and not baseline['result']['findings'] and len(baseline['result']['checks'])==2
    rows.append(baseline)
    manual={'tool':'evaluate','arguments':{'expression':'2+2'},'contains':'4'}
    row=run(asset,'auto: manual compatibility',{'allow_tool_calls':True,'probes':[manual]})
    assert row['status']=='success' and not row['result']['findings'] and len(row['result']['checks'])==3
    rows.append(row)
    for name,extra in [('automatic',{}),('combined',{'probes':[manual]})]:
        row=run(asset,'auto: '+name,{'auto_probes':True,'allow_tool_calls':True,**extra})
        result=row['result']
        assert row['status']=='success',row
        assert {f['rule_id'] for f in result['findings']}=={'mcp.dynamic.argument-code-execution.python','mcp.dynamic.argument-code-execution.javascript'}
        assert len(result['findings'])==2 and result['automatic_checks']['executed']==8
        skipped={x['tool'] for x in result['automatic_checks']['skipped_tools']}
        assert {'write_file','enum_value','external_schema','regex_schema'}<=skipped
        assert row['report']['metrics']['findings_total']==2
        assert row['report']['rating']=='unsafe'
        rows.append(row)
    rejected=False
    try:
        api('/scans',{'name':'must reject auto without consent','type':'mcp','asset_kind':'mcp','asset_id':asset['id'],
            'session_id':uuid.uuid4().hex,'config':{'scanner_ids':['mcp_dynamic'],'auto_probes':True}})
    except RuntimeError as exc:
        rejected=str(exc).startswith('422:')
    assert rejected,'Automatic calls without allow_tool_calls must be rejected'
    asset_summary=api(f"/assets/mcp/{asset['id']}/summary")
    assert asset_summary['findings_total']==2 and asset_summary['rating']=='unsafe'
    large=api('/mcp-assets',{'name':'Автопроверки: лимит вызовов '+uuid.uuid4().hex[:8],
        'config':{'kind':'bundle','artifact_id':artifact['id'],'user_config':{'AUTO_EXTRA_TOOLS':15}}})
    row=run(large,'auto: maximum calls',{'auto_probes':True,'allow_tool_calls':True})
    assert row['status']=='success' and len(row['result']['findings'])==2
    summary=row['result']['automatic_checks']
    assert summary['generated']==summary['executed']==summary['call_limit']==20 and summary['limit_reached']
    rows.append(row)
    output=Path(os.getenv('MCP_AUTO_TEST_OUTPUT','mcp-auto-results.json'))
    output.write_text(json.dumps({'all_passed':True,'permission_rejection':rejected,'asset_id':asset['id'],'runs':rows},ensure_ascii=False,indent=2))
    print(json.dumps({'all_passed':True,'scans':[r['scan_id'] for r in rows],'output':str(output)},ensure_ascii=False))


if __name__=='__main__':
    main()
