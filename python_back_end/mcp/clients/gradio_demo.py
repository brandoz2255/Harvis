import gradio as gr, requests, uuid, os, json

API = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp/invoke")
KEY = os.getenv("MCP_KEY", "dev-key")

def call_tool(name, args_json):
    try:
        args = json.loads(args_json.strip() or "{}")
    except Exception as e:
        return f"Args JSON error: {e}"
    req = {"jsonrpc":"2.0","id":str(uuid.uuid4()),"method":"tool.invoke",
           "params":{"name":name,"args":args}}
    r = requests.post(API, json=req, headers={"Authorization": f"Bearer {KEY}"})
    try:
        return json.dumps(r.json(), indent=2)
    except Exception:
        return r.text

tool_names = [
    "get_system_info",
    "execute_command",
    "list_processes",
    "kill_process",
    "environment_get",
    "environment_set",
    "zip_create",
    "zip_extract",
    "csv_parse",
    "json_parse",
    "xml_parse",
    "pdf_extract_text",
    "word_extract",
]

demo = gr.Interface(fn=call_tool,
    inputs=[gr.Dropdown(tool_names, label="Tool"),
            gr.Textbox(label="Args (JSON)", lines=8, value='{}')],
    outputs=gr.Code(label="Response"),
    title="MCP OS-OPS – Tool Tester")
if __name__ == "__main__":
    demo.launch()
