import pytest

from chkpmcpeks import config
from chkpmcpeks.config import StackConfig


def test_default_servers_are_catalog_members():
    assert len(config.DEFAULT_SERVERS) == 9
    assert all(s in config.SERVER_CATALOG for s in config.DEFAULT_SERVERS)


def test_catalog_has_15_servers_and_all_excludes_flagged():
    assert len(config.SERVER_CATALOG) == 15
    expanded = config.parse_servers("all")
    assert "argos-erm" not in expanded and "quantum-gaia" not in expanded
    assert len(expanded) == 11


def test_parse_servers_variants():
    assert config.parse_servers("a, b c") == ("a", "b", "c")
    assert config.parse_servers("") == ()


def test_secret_names_match_agentcore_project():
    cfg = StackConfig()
    assert cfg.secret_name("reputation-service") == "chkp/reputation-service"
    assert StackConfig(prefix="demo").secret_name("reputation-service") == "chkp/reputation-service-demo"


def test_every_credentialed_server_has_a_shape():
    for server, meta in config.SERVER_CATALOG.items():
        if meta["creds"]:
            assert meta["creds"] in config.CRED_SHAPE, server


def test_target_and_tool_names():
    assert config.target_name("reputation-service") == "reputationservice"
    assert config.split_tool_name("reputationservice_get_url_reputation") == (
        "reputationservice", "get_url_reputation")
    assert config.split_tool_name("noseparator") == (None, "noseparator")
    for server in config.SERVER_CATALOG:
        assert "_" not in config.target_name(server)


def test_pkg_spec_is_pinned_and_image_tag_immutable():
    cfg = StackConfig()
    assert cfg.pkg_spec("reputation-service") == "@chkp/reputation-service-mcp@1.3.1"
    assert cfg.image_tag("reputation-service") == "reputation-service-1.3.1"


@pytest.mark.parametrize("tool,mutating", [
    ("show_hosts", False), ("get_url_reputation", False), ("add_host", True),
    ("publish", True), ("set_access_rule", True), ("quarantine_email", True), ("show_logs", False),
])
def test_mutating_tool_patterns(tool, mutating):
    assert config.is_mutating_tool(tool) is mutating


def test_validate_rejects_unknown_server_and_bad_prefix():
    with pytest.raises(ValueError):
        StackConfig(servers=("nope",)).validate()
    with pytest.raises(ValueError):
        StackConfig(prefix="Bad_Prefix").validate()


def test_dns_cidr_is_service_cidr_dot_10():
    from chkpmcpeks.deploy import dns_cidr

    assert dns_cidr("172.20.0.0/16") == "172.20.0.10/32"
    assert dns_cidr("10.100.0.0/16") == "10.100.0.10/32"


def test_generated_values_carry_llm_choice_and_policy_sources():
    from chkpmcpeks.config import StackConfig
    from chkpmcpeks.deploy import generated_values

    out = {"cognito_issuer": "i", "cognito_jwks_url": "j", "external_client_id": "e", "agent_client_id": "a",
           "cognito_scope": "s", "cognito_token_url": "t", "agent_client_secret_name": "c",
           "llm_secret_name": "l", "certificate_arn": "arn", "alb_inbound_cidrs": ["0.0.0.0/0"],
           "vpc_cidr": "10.40.0.0/16", "public_subnet_cidrs": ["10.40.240.0/24"],
           "cluster_service_cidr": "172.20.0.0/16"}
    v = generated_values(StackConfig(), out, settings={"llm_provider": "anthropic"})
    assert v["agent"]["llm"] == {"provider": "anthropic", "model": ""}
    assert v["networkPolicy"]["albCidrs"] == ["10.40.240.0/24"]
    assert v["networkPolicy"]["dnsCidrs"] == ["172.20.0.10/32"]
    assert v["networkPolicy"]["serviceCidr"] == "172.20.0.0/16"
    assert generated_values(StackConfig(), out, settings={})["agent"]["llm"]["provider"] == "bedrock"


def test_only_terraform_settings_become_tf_vars(tmp_path, monkeypatch):
    from chkpmcpeks import terraform
    from chkpmcpeks.config import StackConfig

    monkeypatch.setattr(terraform, "stack_settings",
                        lambda prefix="": {"domain_name": "x.example.com", "llm_provider": "anthropic"})
    args = terraform.tf_vars(StackConfig())
    assert "domain_name=x.example.com" in args and not any("llm_provider" in a for a in args)
