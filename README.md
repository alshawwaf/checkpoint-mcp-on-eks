# Check Point MCP on Amazon EKS

Check Point's `@chkp` MCP servers and a security-operations agent, running on **Amazon EKS** behind one
authenticated MCP gateway. This is the EKS counterpart of
[checkpoint-mcp-on-aws-agentcore](https://github.com/alshawwaf/checkpoint-mcp-on-aws-agentcore).

> Work in progress. The full README (architecture, quick start, why EKS instead of Bedrock AgentCore,
> runbooks, security notes) lands with the first release.

```
python -m venv .venv
.venv\Scripts\Activate.ps1          # or: source .venv/bin/activate
pip install -e ".[dev]"
python -m chkpmcpeks doctor
```
